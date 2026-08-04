"""Unit tests for multi-pattern tiers/digests: Topic.patterns_for_rank,
backward compatibility with the old singular pattern/digest_pattern keys,
the digests table migration, tiered summarize_articles, multi-pattern
digest_topic, and render.build_view's multi-summary shape.

All network-free; run with `python -m tests.test_multi_pattern`.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from newsdesk import config as config_mod  # noqa: E402
from newsdesk import render as render_mod  # noqa: E402
from newsdesk import summarize  # noqa: E402
from newsdesk.config import Topic  # noqa: E402
from newsdesk.store import Store  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{'  ' + detail if detail else ''}")
    if not cond:
        FAILED.append(name)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="newsdesk-mp-test-"))

    # --- Topic.patterns_for_rank ---------------------------------------------
    t = Topic(name="Test", pattern_tiers=[
        {"top": 3, "patterns": ["a", "b"]},
        {"patterns": ["c"]},
    ])
    check("position inside first tier gets that tier's patterns",
          t.patterns_for_rank(0) == ["a", "b"])
    check("last position still inside top:3 gets the first tier's patterns",
          t.patterns_for_rank(2) == ["a", "b"])
    check("first position outside top:3 gets the catch-all patterns",
          t.patterns_for_rank(3) == ["c"])
    check("a position well outside top:3 still gets the catch-all patterns",
          t.patterns_for_rank(10) == ["c"])

    empty = Topic(name="Empty")
    check("no pattern_tiers means no patterns for any position",
          empty.patterns_for_rank(0) == [])

    # --- backward compatibility ------------------------------------------------
    old = Topic(name="Old", pattern="extract_insights", digest_pattern="create_5_sentence_summary")
    check("old singular pattern synthesizes a single catch-all tier",
          old.pattern_tiers == [{"patterns": ["extract_insights"]}])
    check("old singular digest_pattern synthesizes a one-item list",
          old.digest_patterns == ["create_5_sentence_summary"])

    new = Topic(name="New", pattern="extract_insights",
               pattern_tiers=[{"patterns": ["extract_wisdom"]}])
    check("explicit pattern_tiers wins over the old singular pattern",
          new.pattern_tiers == [{"patterns": ["extract_wisdom"]}])

    # --- Config.all_topics(): explicit empty pattern_tiers must survive -------
    cfg_path = tmp / "config.yaml"
    cfg_path.write_text("""
topics:
  - name: No Summaries
    slug: no-summaries
    pattern_tiers: []
""")
    cfg = config_mod.load(cfg_path)
    topic = cfg.all_topics()[0]
    check("explicit empty pattern_tiers is not clobbered by the old default pattern",
          topic.pattern_tiers == [], str(topic.pattern_tiers))

    # --- Store digests table migration ----------------------------------------
    old_db_path = tmp / "old.sqlite3"
    conn = sqlite3.connect(old_db_path)
    conn.execute("""
        CREATE TABLE digests (
            edition TEXT NOT NULL, topic TEXT NOT NULL, pattern TEXT,
            model TEXT, output TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY (edition, topic)
        )
    """)
    conn.execute("INSERT INTO digests VALUES "
                 "('2026-08-01', 'security', 'old_pattern', 'm', 'old output', 'now')")
    conn.commit()
    conn.close()

    store = Store(old_db_path)  # should migrate without raising
    cols = store.db.execute("PRAGMA table_info(digests)").fetchall()
    pattern_col = next(c for c in cols if c["name"] == "pattern")
    check("digests table migrated: pattern is now part of the primary key",
          pattern_col["pk"] > 0)
    check("old pre-migration digest row is gone (regeneration is cheap and expected)",
          store.get_digest("2026-08-01", "security", "old_pattern") is None)

    store.put_digest("2026-08-02", "security", "pattern_a", "output a", "model")
    store.put_digest("2026-08-02", "security", "pattern_b", "output b", "model")
    check("two digests for the same edition/topic, different patterns, both stored",
          store.get_digest("2026-08-02", "security", "pattern_a") == "output a" and
          store.get_digest("2026-08-02", "security", "pattern_b") == "output b")

    fresh_store = Store(tmp / "fresh.sqlite3")  # no digests table pre-existing at all
    fresh_cols = fresh_store.db.execute("PRAGMA table_info(digests)").fetchall()
    check("fresh install: digests table also has pattern in its primary key",
          next(c for c in fresh_cols if c["name"] == "pattern")["pk"] > 0)

    # --- summarize_articles: tiered budget spending ----------------------------
    class StubProvider(summarize.Provider):
        name = "stub"

        def complete(self, system: str, user: str) -> str:
            return f"stubbed: {system[:10]}"

    class FakeLibrary:
        def get(self, pattern: str) -> tuple[str, str]:
            return (f"system for {pattern}", "")

    def fake_row(aid: str, word_count: int = 500) -> dict:
        return {"id": aid, "title": f"Title {aid}", "source": "Src", "url": f"https://x/{aid}",
                "published_at": None, "body": "word " * word_count, "blurb": "blurb",
                "word_count": word_count}

    tiered_topic = Topic(name="Tiered", pattern_tiers=[
        {"top": 1, "patterns": ["extract_insights", "create_5_sentence_summary"]},
        {"patterns": ["create_5_sentence_summary"]},
    ])
    items = [{"row": fake_row(f"a{i}")} for i in range(3)]
    mp_store = Store(tmp / "mp.sqlite3")
    for it in items:
        mp_store.upsert_article({**it["row"], "canonical_url": it["row"]["url"], "topic": "tiered",
                                 "score": 0, "score_parts": {}, "cluster_id": it["row"]["id"]})
    items = [{"row": mp_store.by_id(it["row"]["id"])} for it in items]  # real Row objects

    made = summarize.summarize_articles(items, mp_store, StubProvider(), FakeLibrary(),
                                        tiered_topic, max_items=3, budget=99)
    check("tiered summarize: top article gets 2 patterns, rest get 1 each (4 total calls)",
          made == 4, str(made))
    check("top article has both tier patterns cached",
          mp_store.get_summary("a0", "extract_insights") is not None and
          mp_store.get_summary("a0", "create_5_sentence_summary") is not None)
    check("second article only has the catch-all pattern cached",
          mp_store.get_summary("a1", "extract_insights") is None and
          mp_store.get_summary("a1", "create_5_sentence_summary") is not None)

    # budget exhaustion stops mid-article, on a fresh store so nothing is cached yet
    mp_store2 = Store(tmp / "mp2.sqlite3")
    for it in items:
        mp_store2.upsert_article({**it["row"], "canonical_url": it["row"]["url"], "topic": "tiered",
                                  "score": 0, "score_parts": {}, "cluster_id": it["row"]["id"]})
    limited = summarize.summarize_articles(items, mp_store2, StubProvider(), FakeLibrary(),
                                           tiered_topic, max_items=3, budget=1)
    check("a budget of 1 stops after exactly one pattern-call, mid-article",
          limited == 1, str(limited))

    # --- digest_topic: multiple patterns ----------------------------------------
    digest_topic_obj = Topic(name="Digest", digest_patterns=["pattern_x", "pattern_y"],
                             pattern_tiers=[{"patterns": ["create_5_sentence_summary"]}])
    for it in items:
        mp_store.put_summary(it["row"]["id"], "create_5_sentence_summary", "a summary", "model")
    digests = summarize.digest_topic(items, mp_store, StubProvider(), FakeLibrary(),
                                     digest_topic_obj, "2026-08-01")
    check("digest_topic returns one entry per configured digest pattern",
          set(digests.keys()) == {"pattern_x", "pattern_y"}, str(digests.keys()))

    none_digest = summarize.digest_topic(items, mp_store, summarize.NoneProvider(), FakeLibrary(),
                                         digest_topic_obj, "2026-08-01")
    check("cached digests survive a NoneProvider rerun", none_digest == digests)

    # --- digest_topic: empty items must not drop an already-cached digest
    #     for a later pattern in topic.digest_patterns -----------------------
    empty_digest_topic = Topic(name="EmptyDigest", digest_patterns=["cached_pattern", "uncached_pattern"],
                               pattern_tiers=[{"patterns": ["create_5_sentence_summary"]}])
    check("EmptyDigest topic slug derivation matches expectation",
          empty_digest_topic.slug == "emptydigest", empty_digest_topic.slug)
    mp_store.put_digest("2026-08-02", "emptydigest", "cached_pattern", "already cached", "model")
    empty_result = summarize.digest_topic([], mp_store, StubProvider(), FakeLibrary(),
                                          empty_digest_topic, "2026-08-02")
    check("cached digest for a later pattern survives when items is empty",
          empty_result.get("cached_pattern") == "already cached", str(empty_result))
    check("uncached pattern has no entry when there's nothing to digest",
          "uncached_pattern" not in empty_result, str(empty_result))

    # --- humanize_pattern --------------------------------------------------------
    check("humanize strips extract_ prefix and title-cases",
          render_mod.humanize_pattern("extract_business_ideas") == "Business Ideas")
    check("humanize strips create_ prefix and keeps digits",
          render_mod.humanize_pattern("create_5_sentence_summary") == "5 Sentence Summary")
    check("humanize with no known prefix just title-cases",
          render_mod.humanize_pattern("some_other_pattern") == "Some Other Pattern")

    # --- build_view: multi-summary cards ------------------------------------------
    ranked_items = [
        {"row": mp_store.by_id("a0"), "score": 1.0, "parts": {"matched": []}, "also": []},
        {"row": mp_store.by_id("a1"), "score": 0.5, "parts": {"matched": []}, "also": []},
    ]
    view = render_mod.build_view(tiered_topic, ranked_items, mp_store, None)
    check("top-tier card has two summaries",
          len(view["cards"][0]["summaries"]) == 2, str(view["cards"][0]["summaries"]))
    check("summaries are in tier order (extract_insights first)",
          view["cards"][0]["summaries"][0]["pattern"] == "extract_insights")
    check("lower-tier card has one summary",
          len(view["cards"][1]["summaries"]) == 1, str(view["cards"][1]["summaries"]))

    print(f"\n{'-' * 60}")
    if FAILED:
        print(f"{len(FAILED)} FAILED: {', '.join(FAILED)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
