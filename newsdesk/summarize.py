"""Runs Fabric patterns over articles.

Providers: ollama (default, local), anthropic (API), none (fall back to the feed blurb).
Summaries are cached by (article_id, pattern), so a re-run costs nothing.
"""
from __future__ import annotations

import logging
import os
import textwrap

import requests

from .patterns import PatternLibrary

log = logging.getLogger("newsdesk.summarize")


class Provider:
    name = "none"

    def complete(self, system: str, user: str) -> str:
        raise NotImplementedError

    def available(self) -> tuple[bool, str]:
        return True, "ok"


class NoneProvider(Provider):
    """No LLM. The board still builds, showing feed blurbs instead of summaries."""
    name = "none"

    def complete(self, system: str, user: str) -> str:
        return ""


class OllamaProvider(Provider):
    def __init__(self, host="http://localhost:11434", model="qwen3:8b",
                 num_ctx=8192, temperature=0.2, timeout=600, keep_alive="10m"):
        self.host = host.rstrip("/")
        self.model = model
        self.options = {"num_ctx": num_ctx, "temperature": temperature}
        self.timeout = timeout
        self.keep_alive = keep_alive
        self.name = f"ollama/{model}"

    def available(self) -> tuple[bool, str]:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=5)
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            if self.model not in models and self.model.split(":")[0] not in \
                    [m.split(":")[0] for m in models]:
                return False, f"model '{self.model}' not pulled (have: {', '.join(models) or 'none'})"
            return True, "ok"
        except requests.RequestException as exc:
            return False, f"ollama unreachable at {self.host}: {exc}"

    def complete(self, system: str, user: str) -> str:
        resp = requests.post(
            f"{self.host}/api/chat",
            json={"model": self.model, "stream": False, "keep_alive": self.keep_alive,
                  "options": self.options,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=self.timeout)
        resp.raise_for_status()
        text = resp.json().get("message", {}).get("content", "")
        # Reasoning models emit <think> blocks; keep only the answer.
        if "</think>" in text:
            text = text.split("</think>", 1)[1]
        return text.strip()


class AnthropicProvider(Provider):
    def __init__(self, model="claude-sonnet-4-6", max_tokens=1600,
                 api_key_env="ANTHROPIC_API_KEY", timeout=180):
        self.model, self.max_tokens, self.timeout = model, max_tokens, timeout
        self.api_key = os.environ.get(api_key_env, "")
        self.api_key_env = api_key_env
        self.name = f"anthropic/{model}"

    def available(self) -> tuple[bool, str]:
        return (True, "ok") if self.api_key else (False, f"{self.api_key_env} is not set")

    def complete(self, system: str, user: str) -> str:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": self.model, "max_tokens": self.max_tokens, "system": system,
                  "messages": [{"role": "user", "content": user}]},
            timeout=self.timeout)
        resp.raise_for_status()
        return "".join(b.get("text", "") for b in resp.json().get("content", [])).strip()


def build_provider(llm_cfg: dict) -> Provider:
    kind = (llm_cfg.get("provider") or "none").lower()
    if kind == "ollama":
        return OllamaProvider(**(llm_cfg.get("ollama") or {}))
    if kind == "anthropic":
        return AnthropicProvider(**(llm_cfg.get("anthropic") or {}))
    return NoneProvider()


# ----------------------------------------------------------------------------

def article_input(row, max_chars: int = 18000) -> str:
    body = (row["body"] or "").strip() or (row["blurb"] or "")
    return textwrap.dedent(f"""\
        TITLE: {row['title']}
        SOURCE: {row['source']}
        PUBLISHED: {row['published_at'] or 'unknown'}
        URL: {row['url']}

        {body[:max_chars]}
        """)


def run_pattern(provider: Provider, library: PatternLibrary, pattern: str, content: str) -> str:
    system, user_template = library.get(pattern)
    user = f"{user_template}\n\n{content}" if user_template.strip() else content
    return provider.complete(system, user)


def summarize_articles(items, store, provider, library, pattern: str,
                       limit: int, min_words: int = 120, force: bool = False) -> int:
    """Run the per-article pattern over the top `limit` items. Returns calls made."""
    if isinstance(provider, NoneProvider):
        return 0
    calls = 0
    for item in items[:limit]:
        row = item["row"]
        if not force and store.get_summary(row["id"], pattern):
            continue
        if (row["word_count"] or 0) < min_words and not (row["blurb"] or "").strip():
            continue
        try:
            out = run_pattern(provider, library, pattern, article_input(row))
        except Exception as exc:  # noqa: BLE001 - one bad article must not kill the run
            log.warning("summary failed for %s: %s", row["title"][:60], exc)
            continue
        if out:
            store.put_summary(row["id"], pattern, out, provider.name)
            calls += 1
    return calls


def digest_topic(items, store, provider, library, topic, edition: str,
                 pattern: str, top_n: int = 8, force: bool = False) -> str:
    """One synthesized 'what matters today' brief per topic."""
    if isinstance(provider, NoneProvider) or not pattern:
        return ""
    cached = store.get_digest(edition, topic.slug)
    if cached and not force:
        return cached

    lines = []
    for i, item in enumerate(items[:top_n], 1):
        row = item["row"]
        summary = store.get_summary(row["id"], topic.pattern) or row["blurb"] or ""
        lines.append(f"{i}. {row['title']} ({row['source']})\n{summary[:1200]}\n")
    if not lines:
        return ""

    content = (f"Topic: {topic.name}\nEdition: {edition}\n\n"
               "Today's ranked items:\n\n" + "\n".join(lines))
    try:
        out = run_pattern(provider, library, pattern, content)
    except Exception as exc:  # noqa: BLE001
        log.warning("digest failed for %s: %s", topic.name, exc)
        return ""
    if out:
        store.put_digest(edition, topic.slug, pattern, out, provider.name)
    return out
