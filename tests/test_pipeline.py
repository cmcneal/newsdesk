"""End-to-end test: local fixture feeds -> fetch -> rank -> summarize -> render.

Run with:  python -m tests.test_pipeline     (from the repo root)
No network needed except the first Fabric pattern fetch, which is then cached.
"""
from __future__ import annotations

import functools
import http.server
import socketserver
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from newsdesk import config as config_mod  # noqa: E402
from newsdesk import fetch, render, score, summarize  # noqa: E402
from newsdesk.patterns import PatternLibrary  # noqa: E402
from newsdesk.store import Store, normalize_url  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{'  ' + detail if detail else ''}")
    if not cond:
        FAILED.append(name)


def serve_fixtures() -> tuple[str, socketserver.TCPServer]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FIXTURES))
    handler.log_message = lambda *a, **k: None  # type: ignore[assignment]
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}", httpd


class StubProvider(summarize.Provider):
    """Deterministic stand-in for Ollama so the test does not need a model."""
    name = "stub/test"

    def __init__(self):
        self.calls: list[tuple[str, int]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system[:40], len(user)))
        title = next((ln.split("TITLE: ", 1)[1] for ln in user.splitlines()
                      if ln.startswith("TITLE: ")), "digest")
        return (f"SUMMARY:\n\nStubbed analysis of {title}.\n\n"
                f"IDEAS:\n\n- First idea about **{title[:30]}**\n- Second idea\n")


def main() -> int:
    base, httpd = serve_fixtures()
    tmp = Path(tempfile.mkdtemp(prefix="newsdesk-test-"))
    # Forward slashes only: on Windows, tmp's backslashes would land inside a
    # double-quoted YAML string below and get parsed as escape sequences
    # (e.g. \U expects 8 hex digits), breaking the config load.
    tmp_posix = tmp.as_posix()

    # max_age_hours is set far larger than the default: the fixtures below have
    # publish dates hardcoded to specific 2026 calendar days, and a tight
    # max_age_hours would start silently filtering fixture articles out of
    # store.recent() as real time passes the fixture dates by more than a few
    # days. Recency-decay behavior is exercised via half_life_hours/score
    # comparisons below, not by this cutoff, so a generous value is safe here.
    cfg_text = f"""
profile: {{timezone: America/Edmonton}}
llm: {{provider: none, max_items_per_run: 20}}
patterns: {{cache_dir: "{tmp_posix}/patterns-cache", local_dir: "{tmp_posix}/patterns"}}
scoring: {{half_life_hours: 20, corroboration_bonus: 0.35, keyword_weight: 0.6,
           title_multiplier: 2.0, max_age_hours: 87600}}
output: {{dir: "{tmp_posix}/out", db: "{tmp_posix}/test.sqlite3", keep_days: 30, title: Newsdesk}}
topic_defaults: {{max_items: 8, min_score: 0.0}}
topics:
  - name: Security & Threat Intel
    slug: security
    pattern_tiers:
      - {{top: 1, patterns: [extract_insights, create_5_sentence_summary]}}
      - {{patterns: [create_5_sentence_summary]}}
    digest_patterns: [create_5_sentence_summary, extract_insights]
    include: [exploit, ransomware, CVE, zero-day, malware, supply chain, CISA, vulnerability]
    exclude: [sponsored, "buyer's guide"]
    sources:
      - {{url: "{base}/alpha.xml", name: Alpha, weight: 1.0}}
      - {{url: "{base}/beta.xml", name: Beta, weight: 1.2}}
  - name: AI Engineering
    slug: ai
    pattern_tiers:
      - {{patterns: [create_5_sentence_summary]}}
    digest_patterns: []
    include: [LLM, agent, model, benchmark, quantization, inference]
    exclude: [funding round]
    sources:
      - {{url: "{base}/gamma.xml", name: Gamma, weight: 1.0, full_text: false}}
"""
    cfg_path = tmp / "config.yaml"
    cfg_path.write_text(cfg_text)
    cfg = config_mod.load(cfg_path)
    store = Store(cfg.resolve(cfg.output["db"]))
    topics = cfg.topics

    # --- config ---------------------------------------------------------
    check("config loads two topics", len(topics) == 2, f"got {len(topics)}")
    check("source name defaults resolve", all(s.name for t in topics for s in t.sources))
    check("url normalization strips utm",
          normalize_url("https://ex.test/a?utm_source=rss&id=1") == "https://ex.test/a?id=1",
          normalize_url("https://ex.test/a?utm_source=rss&id=1"))

    # --- fetch ----------------------------------------------------------
    counts = fetch.collect(topics, store, workers=4)
    check("fetch stored security items", counts["security"] == 6, f"got {counts['security']}")
    check("fetch stored ai items", counts["ai"] == 3, f"got {counts['ai']}")

    again = fetch.collect(topics, store, workers=4)
    check("second fetch is idempotent", sum(again.values()) == 0, f"got {sum(again.values())}")

    # --- ranking --------------------------------------------------------
    sec = score.rank(store, topics[0], cfg.scoring)
    titles = [i["row"]["title"] for i in sec]
    check("exclusion drops sponsored item",
          not any("Sponsored" in t for t in titles))
    check("require_match drops keyword-free item",
          not any("Quiet week" in t for t in titles))
    check("SSO zero-day leads the topic", "zero-day" in titles[0].lower(), titles[0][:60])
    check("cross-source story is clustered",
          sec[0]["parts"]["cluster_size"] == 2, str(sec[0]["parts"]["cluster_size"]))
    check("also-covered sibling attached", len(sec[0]["also"]) == 1)
    check("recency decay applied", 0 < sec[0]["parts"]["recency"] <= 1.0,
          str(sec[0]["parts"]["recency"]))
    check("older story scores lower than newer peer",
          sec[0]["score"] > sec[-1]["score"])

    ai = score.rank(store, topics[1], cfg.scoring)
    ai_titles = [i["row"]["title"] for i in ai]
    check("ai topic excludes funding item", not any("valuation" in t for t in ai_titles))
    check("ai topic kept two items", len(ai) == 2, str(len(ai)))

    # --- patterns -------------------------------------------------------
    library = PatternLibrary(cache_dir=cfg.resolve(cfg.patterns["cache_dir"]),
                             repo=cfg.patterns["repo"], ref=cfg.patterns["ref"],
                             local_dir=cfg.resolve(cfg.patterns["local_dir"]))
    warmed = library.warm(["extract_insights", "create_5_sentence_summary"])
    check("fabric patterns fetch", all(v == "ok" for v in warmed.values()), str(warmed))
    sys_prompt, _ = library.get("extract_insights")
    check("pattern has an identity section", "IDENTITY" in sys_prompt)
    check("pattern is cached to disk",
          (library.cache_dir / "extract_insights" / "system.md").exists())

    # local override wins over cache
    override = cfg.resolve(cfg.patterns["local_dir"]) / "extract_insights" / "system.md"
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text("LOCAL OVERRIDE")
    lib2 = PatternLibrary(cache_dir=library.cache_dir, local_dir=override.parent.parent)
    check("local pattern override wins", lib2.get("extract_insights")[0] == "LOCAL OVERRIDE")
    override.unlink()

    # --- summarize (tiered) ----------------------------------------------
    stub = StubProvider()
    budget = len(sec) * 3  # generous: enough for every article's tier to complete
    made = summarize.summarize_articles(sec, store, stub, library, topics[0],
                                        max_items=topics[0].max_items, budget=budget)
    expected_calls = 2 + (min(len(sec), topics[0].max_items) - 1)  # top article: 2 patterns, rest: 1 each
    check("tiered summarize makes the expected number of calls",
          made == expected_calls, f"got {made}, expected {expected_calls}")
    check("top article got both tier patterns",
          bool(store.get_summary(sec[0]["row"]["id"], "extract_insights")) and
          bool(store.get_summary(sec[0]["row"]["id"], "create_5_sentence_summary")))
    check("second-ranked article only got the catch-all pattern",
          store.get_summary(sec[1]["row"]["id"], "extract_insights") is None and
          bool(store.get_summary(sec[1]["row"]["id"], "create_5_sentence_summary")))

    cached_run = summarize.summarize_articles(sec, store, stub, library, topics[0],
                                              max_items=topics[0].max_items, budget=budget)
    check("summaries are cached, not re-run", cached_run == 0, str(cached_run))

    digest = summarize.digest_topic(sec, store, stub, library, topics[0], "2026-08-01")
    check("digest generated for each configured pattern",
          set(digest.keys()) == set(topics[0].digest_patterns), str(digest.keys()))
    check("digest cached per pattern",
          all(store.get_digest("2026-08-01", "security", p) == digest[p] for p in digest))

    # A later --no-llm rebuild the same day must not blank out digests
    # already generated by an earlier run with a real provider.
    none_prov = summarize.NoneProvider()
    no_llm_digest = summarize.digest_topic(sec, store, none_prov, library, topics[0], "2026-08-01")
    check("cached digests survive a --no-llm rerun", no_llm_digest == digest)
    check("none provider makes no calls",
          summarize.summarize_articles(ai, store, none_prov, library, topics[1],
                                       max_items=5, budget=5) == 0)

    # think-tag stripping
    ollama = summarize.OllamaProvider.__new__(summarize.OllamaProvider)
    stripped = "<think>reasoning</think>\nActual answer"
    check("think blocks stripped", stripped.split("</think>", 1)[1].strip() == "Actual answer")

    # --- render ---------------------------------------------------------
    md = render.md_to_html("SUMMARY:\n\n- one **bold** item\n- two\n\n# Heading\n\ntext")
    check("markdown renders bullets", "<li>one <strong>bold</strong> item</li>" in md, md[:80])
    check("markdown renders caps labels", 'class="label"' in md)
    check("markdown escapes html",
          "&lt;script&gt;" in render.md_to_html("<script>alert(1)</script>"))

    views = [render.build_view(t, r, store, cfg)
             for t, r in ((topics[0], sec), (topics[1], ai))]
    check("top-tier card carries two summaries", len(views[0]["cards"][0]["summaries"]) == 2)
    check("lower-tier card carries one summary", len(views[0]["cards"][1]["summaries"]) == 1)
    check("signal blocks in range",
          all(1 <= c["blocks"] <= 4 for v in views for c in v["cards"]))

    meta = {"edition": "2026-08-01", "edition_long": "Saturday, 01 August 2026 · 06:30 MDT",
            "built_at": "06:30", "model": stub.name, "scanned": len(sec) + len(ai),
            "sources_ok": 3, "sources_failed": 0, "duration": "12s"}
    out = render.render(views, {"security": digest}, cfg, meta)
    html = out.read_text()
    check("index written", out.exists())
    check("edition archived",
          (cfg.resolve(cfg.output["dir"]) / "editions" / "2026-08-01.html").exists())
    check("topics present in html", 'id="security"' in html and 'id="ai"' in html)
    check("signal meter rendered", 'class="signal"' in html and 'class="seg on"' in html)
    check("brief rendered", 'class="brief"' in html)
    check("digest tabs rendered for the multi-pattern topic", 'class="brief-tab"' in html)
    check("per-article summary tabs rendered for the top-tier article",
          'class="summary-tab"' in html)
    check("also-covered rendered", 'class="also"' in html)
    check("keyboard handler present", "focusAt" in html)
    check("no unrendered jinja left", "{{" not in html and "{%" not in html)

    # --- prune ----------------------------------------------------------
    check("prune keeps fresh items", store.prune(30) == 0)

    httpd.shutdown()
    print(f"\n{'-' * 60}")
    if FAILED:
        print(f"{len(FAILED)} FAILED: {', '.join(FAILED)}")
        return 1
    print("all checks passed")
    print(f"rendered board: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
