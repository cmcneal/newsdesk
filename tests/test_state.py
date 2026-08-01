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

    # --- save + load round-trip ---------------------------------------------
    p = tmp / "test.state.json"
    state.save(p, {"disabled_topics": {"business"}, "disabled_sources": {"security|https://a.test/feed"}})
    round_tripped = state.load(p)
    check("round-trip preserves disabled topics", round_tripped["disabled_topics"] == {"business"})
    check("round-trip preserves disabled sources",
          round_tripped["disabled_sources"] == {"security|https://a.test/feed"})

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

    print(f"\n{'-' * 60}")
    if FAILED:
        print(f"{len(FAILED)} FAILED: {', '.join(FAILED)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
