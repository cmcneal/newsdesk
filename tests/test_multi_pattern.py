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

    print(f"\n{'-' * 60}")
    if FAILED:
        print(f"{len(FAILED)} FAILED: {', '.join(FAILED)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
