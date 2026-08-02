"""Feed collection and article body extraction."""
from __future__ import annotations

import concurrent.futures as futures
import logging
import re
from datetime import datetime, timezone
from html import unescape

import feedparser
import requests

from .config import Source, Topic
from .store import Store, article_id, normalize_url, now

log = logging.getLogger("newsdesk.fetch")

UA = "newsdesk/1.0 (+personal news board; contact: local)"
TIMEOUT = 25
TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str | None, limit: int = 600) -> str:
    if not text:
        return ""
    clean = unescape(TAG_RE.sub(" ", text))
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:limit]


def _published(entry) -> str | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        tm = entry.get(key)
        if tm:
            try:
                return datetime(*tm[:6], tzinfo=timezone.utc).isoformat(timespec="seconds")
            except (TypeError, ValueError):
                continue
    return None


def read_feed(source: Source, store: Store) -> list[dict]:
    """Pull one feed. Uses ETag / Last-Modified so repeat runs are cheap."""
    state = store.feed_state(source.url)
    headers = {"User-Agent": UA}
    if state.get("etag"):
        headers["If-None-Match"] = state["etag"]
    if state.get("last_modified"):
        headers["If-Modified-Since"] = state["last_modified"]

    try:
        resp = requests.get(source.url, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as exc:
        store.save_feed_state(source.url, error=str(exc))
        log.warning("feed failed %s: %s", source.name, exc)
        return []

    if resp.status_code == 304:
        store.save_feed_state(source.url, etag=state.get("etag"))
        return []
    if resp.status_code >= 400:
        store.save_feed_state(source.url, error=f"HTTP {resp.status_code}")
        log.warning("feed %s returned HTTP %s", source.name, resp.status_code)
        return []

    try:
        parsed = feedparser.parse(resp.content)
        items = []
        feed_title = parsed.feed.get("title", source.name)
        for entry in parsed.entries:
            link = entry.get("link") or entry.get("id")
            title = strip_html(entry.get("title"), 300)
            if not link or not title:
                continue
            blurb = strip_html(entry.get("summary") or
                               (entry.get("content") or [{}])[0].get("value"))
            items.append({
                "id": article_id(link, title),
                "url": link,
                "canonical_url": normalize_url(link),
                "title": title,
                "source": source.name or feed_title,
                "source_weight": source.weight,
                "author": strip_html(entry.get("author"), 120) or None,
                "published_at": _published(entry),
                "fetched_at": now(),
                "blurb": blurb,
                "_full_text": source.full_text and not source.paywalled,
            })
    except Exception as exc:  # noqa: BLE001 - one malformed feed must not kill the run
        store.save_feed_state(source.url, error=f"parse failed: {exc}")
        log.warning("feed %s failed to parse: %s", source.name, exc)
        return []

    store.save_feed_state(source.url, etag=resp.headers.get("ETag"),
                          last_modified=resp.headers.get("Last-Modified"))
    log.info("%s: %d entries", source.name, len(items))
    return items


def extract_body(url: str) -> tuple[str, int]:
    """Return (article text, word count). Empty on failure; the blurb is the fallback."""
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
            resp.raise_for_status()
            downloaded = resp.text
        text = trafilatura.extract(downloaded, include_comments=False,
                                   include_tables=False, favor_precision=True) or ""
    except Exception as exc:  # noqa: BLE001 - body text is best-effort
        log.debug("body extraction failed for %s: %s", url, exc)
        return "", 0
    text = text.strip()
    return text, len(text.split())


def collect(topics: list[Topic], store: Store, workers: int = 8,
            body_chars: int = 24000) -> dict[str, int]:
    """Fetch every source for every topic and store new articles. Returns per-topic counts."""
    jobs = [(t, s) for t in topics for s in t.sources]
    counts = {t.slug: 0 for t in topics}
    pending: list[tuple[Topic, dict]] = []

    # Two topics can share a source URL (e.g. schneier.com/feed under both
    # "security" and "deep"). Fetch each unique URL once so concurrent jobs
    # don't race on the same feed_state row, then fan the result out to
    # every topic that lists it.
    unique_sources = {s.url: s for _, s in jobs}
    with futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures_by_url = {pool.submit(read_feed, s, store): url
                          for url, s in unique_sources.items()}
        results_by_url: dict[str, list[dict]] = {}
        for fut in futures.as_completed(futures_by_url):
            results_by_url[futures_by_url[fut]] = fut.result()

    for topic, source in jobs:
        for item in results_by_url[source.url]:
            item = dict(item)
            item["topic"] = topic.slug
            pending.append((topic, item))

    # Dedupe within this run: first topic to claim a URL keeps it.
    seen: set[str] = set()
    fresh: list[tuple[Topic, dict]] = []
    for topic, item in pending:
        if item["canonical_url"] in seen:
            continue
        seen.add(item["canonical_url"])
        if store.by_id(item["id"]):
            continue
        fresh.append((topic, item))

    # `.pop` here also strips "_full_text" as a side effect, so every item
    # in `fresh` is clean of it by the time downstream code sees it.
    want_body = [(t, i) for t, i in fresh if i.pop("_full_text", False)]

    with futures.ThreadPoolExecutor(max_workers=workers) as pool:
        bodies = {pool.submit(extract_body, i["url"]): i for _, i in want_body}
        for fut in futures.as_completed(bodies):
            item = bodies[fut]
            text, words = fut.result()
            item["body"] = text[:body_chars]
            item["word_count"] = words

    for topic, item in fresh:
        item.setdefault("body", "")
        item.setdefault("word_count", 0)
        if store.upsert_article(item):
            counts[topic.slug] += 1

    return counts
