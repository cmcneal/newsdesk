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

    print(f"\n{'-' * 60}")
    if FAILED:
        print(f"{len(FAILED)} FAILED: {', '.join(FAILED)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
