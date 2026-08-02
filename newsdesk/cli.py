"""newsdesk CLI.

    newsdesk build            fetch, rank, summarize, render
    newsdesk build --no-llm   same, but skip summaries (fast, no model needed)
    newsdesk doctor           check feeds, patterns, and the model before you rely on it
    newsdesk patterns         list and pre-cache Fabric patterns
    newsdesk topics           show what each topic is currently pulling
    newsdesk serve            serve the output dir on localhost
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config as config_mod
from . import fetch, render, score, summarize
from .patterns import CURATED, PatternLibrary
from .store import Store

log = logging.getLogger("newsdesk")


def _setup(args):
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s", datefmt="%H:%M:%S")
    if not args.verbose:
        # Dead links and slow hosts are normal here; newsdesk reports them in `doctor`.
        for noisy in ("trafilatura", "urllib3", "charset_normalizer"):
            logging.getLogger(noisy).setLevel(logging.CRITICAL)
    cfg = config_mod.load(args.config)
    store = Store(cfg.resolve(cfg.output["db"]))
    library = PatternLibrary(
        cache_dir=cfg.resolve(cfg.patterns["cache_dir"]),
        repo=cfg.patterns["repo"], ref=cfg.patterns["ref"],
        local_dir=cfg.resolve(cfg.patterns.get("local_dir", "patterns")),
        offline=bool(cfg.patterns.get("offline")))
    return cfg, store, library


def _tz(cfg):
    try:
        return ZoneInfo(cfg.profile.get("timezone", "UTC"))
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


# ---------------------------------------------------------------- build
def cmd_build(args) -> int:
    started = time.time()
    cfg, store, library = _setup(args)
    topics = cfg.topics
    if args.topic:
        topics = [t for t in topics if t.slug in args.topic or t.name in args.topic]
        if not topics:
            log.error("no topic matched %s", args.topic)
            return 2

    tz = _tz(cfg)
    local_now = datetime.now(tz)
    edition = local_now.strftime("%Y-%m-%d")

    if args.no_fetch:
        counts = {t.slug: 0 for t in topics}
        log.info("skipping fetch (--no-fetch)")
    else:
        counts = fetch.collect(topics, store, workers=cfg.raw.get("workers", 8))
        log.info("fetched %d new items", sum(counts.values()))

    provider = summarize.NoneProvider() if args.no_llm else summarize.build_provider(cfg.llm)
    ok, why = provider.available()
    if not ok:
        log.warning("LLM unavailable (%s). Building without summaries.", why)
        provider = summarize.NoneProvider()

    budget = int(cfg.llm.get("max_items_per_run", 40))
    views, digests, scanned = [], {}, 0

    for topic in topics:
        ranked = score.rank(store, topic, cfg.scoring)
        scanned += len(ranked)
        log.info("%-22s %3d ranked", topic.slug, len(ranked))

        per_topic = min(topic.max_items, budget)
        if per_topic > 0:
            used = summarize.summarize_articles(
                ranked, store, provider, library, topic.pattern,
                limit=per_topic, force=args.force)
            budget -= used
            if used:
                log.info("%-22s %3d summaries (%s)", topic.slug, used, topic.pattern)

        if topic.digest_pattern:
            digest = summarize.digest_topic(
                ranked[:topic.max_items], store, provider, library, topic,
                edition, topic.digest_pattern, force=args.force)
            if digest:
                digests[topic.slug] = digest

        views.append(render.build_view(topic, ranked, store, cfg))

    states = [store.feed_state(s.url) for t in topics for s in t.sources]
    meta = {
        "edition": edition,
        "edition_long": local_now.strftime("%A, %d %B %Y · %H:%M %Z"),
        "built_at": local_now.strftime("%H:%M"),
        "model": provider.name,
        "scanned": scanned,
        "sources_ok": sum(1 for s in states if s and not s.get("last_error")),
        "sources_failed": sum(1 for s in states if s and s.get("last_error")),
        "duration": f"{time.time() - started:.0f}s",
    }

    path = render.render(views, digests, cfg, meta)
    removed = store.prune(int(cfg.output["keep_days"]))
    log.info("pruned %d old items", removed)
    print(path)
    return 0


# --------------------------------------------------------------- doctor
def cmd_doctor(args) -> int:
    cfg, store, library = _setup(args)
    problems = 0

    provider = summarize.build_provider(cfg.llm)
    ok, why = provider.available()
    print(f"[{'ok ' if ok else 'FAIL'}] llm  {provider.name}: {why}")
    problems += 0 if ok else 1

    wanted = []
    for t in cfg.topics:
        wanted += [t.pattern, t.digest_pattern]
    for name, status in library.warm([w for w in wanted if w]).items():
        good = status == "ok"
        print(f"[{'ok ' if good else 'FAIL'}] pattern  {name}: {status}")
        problems += 0 if good else 1

    import requests
    for topic in cfg.topics:
        for src in topic.sources:
            try:
                r = requests.head(src.url, timeout=12, allow_redirects=True,
                                  headers={"User-Agent": fetch.UA})
                if r.status_code >= 400:
                    r = requests.get(src.url, timeout=12, headers={"User-Agent": fetch.UA},
                                     stream=True)
                good = r.status_code < 400
                print(f"[{'ok ' if good else 'FAIL'}] feed  {topic.slug}/{src.name}: HTTP {r.status_code}")
                problems += 0 if good else 1
            except Exception as exc:  # noqa: BLE001
                print(f"[FAIL] feed  {topic.slug}/{src.name}: {exc}")
                problems += 1

    print(f"\n{problems} problem(s).")
    return 1 if problems else 0


# ------------------------------------------------------------- patterns
def cmd_patterns(args) -> int:
    cfg, _, library = _setup(args)
    if args.warm:
        names = args.warm if args.warm != ["all"] else CURATED["per-article"] + CURATED["per-topic-digest"]
        for name, status in library.warm(names).items():
            print(f"{status:>6}  {name}")
        return 0
    for group, names in CURATED.items():
        print(f"\n# {group}")
        for n in names:
            cached = (library.cache_dir / n / "system.md").exists()
            print(f"  {'cached' if cached else '      '}  {n}")
    return 0


# --------------------------------------------------------------- topics
def cmd_topics(args) -> int:
    cfg, store, _ = _setup(args)
    for t in cfg.topics:
        ranked = score.rank(store, t, cfg.scoring)
        print(f"\n{t.name}  [{t.slug}]  pattern={t.pattern}  digest={t.digest_pattern or '-'}")
        print(f"  {len(t.sources)} sources, {len(ranked)} ranked, showing {t.max_items}")
        for item in ranked[:t.max_items]:
            r, p = item["row"], item["parts"]
            multi = f" x{p['cluster_size']}" if p["cluster_size"] > 1 else ""
            print(f"    {item['score']:5.2f}{multi:>4}  {r['source'][:18]:18}  {r['title'][:70]}")
    return 0


# ---------------------------------------------------------- last30days
def cmd_last30days(args) -> int:
    cfg, store, library = _setup(args)
    topics = cfg.topics
    if args.topic:
        topics = [t for t in topics if t.slug in args.topic or t.name in args.topic]
        if not topics:
            log.error("no topic matched %s", args.topic)
            return 2

    tz = _tz(cfg)
    local_now = datetime.now(tz)
    days = args.days

    # Scale the half-life so articles from across the window still compete.
    # At 1/4 of the window, a story scores 0.5 (vs 1.0 for brand-new).
    scoring = {**cfg.scoring,
               "max_age_hours": days * 24,
               "half_life_hours": days * 6}

    views, scanned = [], 0
    for topic in topics:
        ranked = score.rank(store, topic, scoring)
        scanned += len(ranked)
        log.info("%-22s %3d ranked", topic.slug, len(ranked))
        views.append(render.build_view(topic, ranked, store, cfg))

    meta = {
        "edition": f"last-{days}d",
        "edition_long": f"Last {days} days · as of {local_now.strftime('%A, %d %B %Y · %H:%M %Z')}",
        "built_at": local_now.strftime("%H:%M"),
        "model": "—",
        "scanned": scanned,
        "sources_ok": 0,
        "sources_failed": 0,
        "duration": "—",
    }

    path = render.render(views, {}, cfg, meta, link_as_index=False)
    print(path)
    return 0


# ---------------------------------------------------------------- serve
def cmd_serve(args) -> int:
    import socketserver
    from . import webapp
    cfg, _, _ = _setup(args)
    root = cfg.resolve(cfg.output["dir"])
    rebuild_cmd = [sys.executable, "-m", "newsdesk.cli", "-c", str(cfg.path), "build"]
    job = webapp.RebuildJob(rebuild_cmd)
    handler = webapp.make_handler(cfg.path, root, job)
    display_host = "localhost" if args.host == "0.0.0.0" else args.host
    with socketserver.TCPServer((args.host, args.port), handler) as httpd:
        print(f"serving {root} at http://{display_host}:{args.port}/  "
              f"(settings: http://{display_host}:{args.port}/settings)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="newsdesk", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-c", "--config", default="config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="fetch, rank, summarize, render")
    b.add_argument("--no-llm", action="store_true", help="skip summaries")
    b.add_argument("--no-fetch", action="store_true", help="rebuild from what is already stored")
    b.add_argument("--force", action="store_true", help="re-run patterns even when cached")
    b.add_argument("--topic", action="append", help="limit to one topic (repeatable)")
    b.set_defaults(func=cmd_build)

    d = sub.add_parser("doctor", help="check feeds, patterns, and the model")
    d.set_defaults(func=cmd_doctor)

    pt = sub.add_parser("patterns", help="list or pre-cache Fabric patterns")
    pt.add_argument("--warm", nargs="*", help="pattern names, or 'all'")
    pt.set_defaults(func=cmd_patterns)

    t = sub.add_parser("topics", help="show current ranking per topic")
    t.set_defaults(func=cmd_topics)

    l30 = sub.add_parser("last30days", help="best-of-window digest from stored articles")
    l30.add_argument("--days", type=int, default=30, help="how many days to look back (default 30)")
    l30.add_argument("--topic", action="append", help="limit to one topic (repeatable)")
    l30.set_defaults(func=cmd_last30days)

    s = sub.add_parser("serve", help="serve the output directory")
    s.add_argument("--host", default="127.0.0.1",
                   help="bind address (default 127.0.0.1; use 0.0.0.0 to serve on the LAN)")
    s.add_argument("--port", type=int, default=8787)
    s.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
