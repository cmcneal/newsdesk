"""Unit tests for the settings-UI sidecar state file."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from newsdesk import state  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{'  ' + detail if detail else ''}")
    if not cond:
        FAILED.append(name)


def main() -> int:
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="newsdesk-state-test-"))

    # --- state_path -------------------------------------------------------
    check("state_path derives from config stem",
          state.state_path(Path("/x/my.yaml")) == Path("/x/my.state.json"))
    check("state_path derives from config.yaml",
          state.state_path(Path("/x/config.yaml")) == Path("/x/config.state.json"))

    # --- source_key ---------------------------------------------------------
    check("source_key scopes by topic",
          state.source_key("security", "https://a.test/feed") !=
          state.source_key("deep", "https://a.test/feed"))

    # --- load: missing file -------------------------------------------------
    missing = tmp / "none.state.json"
    loaded = state.load(missing)
    check("missing state file means nothing disabled",
          loaded == {"disabled_topics": set(), "disabled_sources": set()})

    # --- save + load round-trip (verify atomic write still works) -------
    p = tmp / "test.state.json"
    state.save(p, {"disabled_topics": {"business"}, "disabled_sources": {"security|https://a.test/feed"}})
    round_tripped = state.load(p)
    check("round-trip preserves disabled topics", round_tripped["disabled_topics"] == {"business"})
    check("round-trip preserves disabled sources",
          round_tripped["disabled_sources"] == {"security|https://a.test/feed"})

    # --- load: corrupted JSON file ------------------------------------------
    corrupted = tmp / "corrupted.state.json"
    corrupted.write_text("{ this is not valid json }", encoding="utf-8")
    loaded = state.load(corrupted)
    check("corrupted JSON file returns empty default",
          loaded == {"disabled_topics": set(), "disabled_sources": set()})

    # --- load: unreadable file (simulated via partial write) ---------------
    partial = tmp / "partial.state.json"
    partial.write_text('{"disabled_topics": ["b', encoding="utf-8")
    loaded = state.load(partial)
    check("partial/truncated JSON file returns empty default",
          loaded == {"disabled_topics": set(), "disabled_sources": set()})

    # --- set_enabled: invalid kind -----------------------------------------
    p3 = tmp / "invalid_kind.state.json"
    try:
        state.set_enabled(p3, "invalid_kind", "foo", True)
        check("set_enabled rejects invalid kind", False, "no exception raised")
    except ValueError as e:
        check("set_enabled rejects invalid kind", "invalid_kind" in str(e))

    # --- set_enabled ----------------------------------------------------------
    p2 = tmp / "toggle.state.json"
    state.set_enabled(p2, "topic", "business", False)
    check("disabling a topic persists", state.load(p2)["disabled_topics"] == {"business"})
    state.set_enabled(p2, "topic", "business", True)
    check("re-enabling a topic clears it", state.load(p2)["disabled_topics"] == set())

    key = state.source_key("security", "https://a.test/feed")
    state.set_enabled(p2, "source", key, False)
    check("disabling a source persists", state.load(p2)["disabled_sources"] == {key})

    # a source shared across two topics: disabling the security-scoped key
    # must not touch the deep-scoped key for the same URL
    other_key = state.source_key("deep", "https://a.test/feed")
    state.set_enabled(p2, "source", other_key, False)
    check("shared URL: both topic-scoped keys tracked independently",
          state.load(p2)["disabled_sources"] == {key, other_key})
    state.set_enabled(p2, "source", key, True)
    check("shared URL: re-enabling one topic's copy leaves the other disabled",
          state.load(p2)["disabled_sources"] == {other_key})

    # --- Config.topics integration ------------------------------------------
    from newsdesk import config as config_mod

    cfg_dir = tmp / "cfgtest"
    cfg_dir.mkdir()
    cfg_text = """
topics:
  - name: Security
    slug: security
    sources:
      - {url: "https://a.test/feed", name: A, weight: 1.0}
      - {url: "https://shared.test/feed", name: Shared, weight: 1.0}
  - name: Deep Reads
    slug: deep
    sources:
      - {url: "https://shared.test/feed", name: Shared, weight: 1.0}
      - {url: "https://b.test/feed", name: B, weight: 1.0}
"""
    cfg_path = cfg_dir / "config.yaml"
    cfg_path.write_text(cfg_text)

    cfg = config_mod.load(cfg_path)
    check("no state file: all_topics == topics count",
          len(cfg.all_topics()) == len(cfg.topics) == 2)

    state_file = state.state_path(cfg_path)
    state.set_enabled(state_file, "topic", "deep", False)
    cfg = config_mod.load(cfg_path)
    check("disabled topic dropped from .topics", [t.slug for t in cfg.topics] == ["security"])
    check("disabled topic still present in .all_topics",
          sorted(t.slug for t in cfg.all_topics()) == ["deep", "security"])
    state.set_enabled(state_file, "topic", "deep", True)

    # shared URL across two topics: disabling it in `security` must not
    # remove it from `deep`
    shared_in_security = state.source_key("security", "https://shared.test/feed")
    state.set_enabled(state_file, "source", shared_in_security, False)
    cfg = config_mod.load(cfg_path)
    sec = next(t for t in cfg.topics if t.slug == "security")
    deep = next(t for t in cfg.topics if t.slug == "deep")
    check("source disabled in one topic is gone from that topic",
          "Shared" not in [s.name for s in sec.sources], str([s.name for s in sec.sources]))
    check("same source URL still present in the other topic",
          "Shared" in [s.name for s in deep.sources], str([s.name for s in deep.sources]))
    check("security topic still has its other source",
          "A" in [s.name for s in sec.sources])

    # stale state entry (topic/source no longer in config) is a harmless no-op
    state.set_enabled(state_file, "topic", "no-such-topic", False)
    cfg = config_mod.load(cfg_path)
    check("stale disabled-topic entry does not error and topics still resolve",
          sorted(t.slug for t in cfg.topics) == ["deep", "security"])

    print(f"\n{'-' * 60}")
    if FAILED:
        print(f"{len(FAILED)} FAILED: {', '.join(FAILED)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
