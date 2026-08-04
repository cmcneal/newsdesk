# Multi-Pattern Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every topic runs several patterns per article (tiered by rank) and several patterns for its digest, shown as tabs on the board, instead of one fixed pattern each.

**Architecture:** `Topic` gains `pattern_tiers` (ordered rank bands, each listing which patterns apply) and `digest_patterns` (a flat list), replacing the old singular `pattern`/`digest_pattern` with backward-compatible synthesis. `summarize.py` runs every pattern a given article's tier calls for and every configured digest pattern; `render.py` bulk-loads and shapes them into per-article and per-topic tab data; the template renders tabs that toggle via the `hidden` attribute, matching the board's existing conventions.

**Tech Stack:** Same as the rest of the project: stdlib + PyYAML + Jinja2, no new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-03-multi-pattern-tabs-design.md`

---

## File Structure

- Modify: `newsdesk/config.py`: `Topic.pattern_tiers`/`digest_patterns`, `Topic.patterns_for_rank`, backward-compat synthesis, `Config.all_topics()` setdefault fix
- Modify: `newsdesk/store.py`: digests table migration, `get_digest` gains a `pattern` param
- Modify: `newsdesk/summarize.py`: tier-aware `summarize_articles`, multi-pattern `digest_topic`, new `_build_digest_content` helper
- Modify: `newsdesk/render.py`: new `humanize_pattern`, `build_view` multi-summary shape, `render()` nested digests shape + new Jinja filter
- Modify: `templates/_shared.css.j2`: tab styling, drop the now-dead `.eyebrow .pattern` rule
- Modify: `templates/dashboard.html.j2`: digest tabs, per-article tabs, tab-switching JS
- Modify: `newsdesk/cli.py`: `cmd_build`/`cmd_doctor`/`cmd_topics` wired to the new shapes
- Modify: `config.yaml`: `topic_defaults` gains `pattern_tiers`/`digest_patterns`; each topic's old singular keys removed
- Modify: `newsdesk/patterns.py`: `CURATED["per-topic-digest"]` gains the two new patterns
- Modify: `README.md`: "Patterns" section rewritten for the new shape
- Create: `tests/test_multi_pattern.py`: unit tests for everything above, network-free
- Modify: `tests/test_pipeline.py`: fixture config updated to the new shape, assertions updated, new multi-pattern end-to-end checks

---

### Task 1: `Topic.pattern_tiers`/`digest_patterns` and `patterns_for_rank`

**Files:**
- Modify: `newsdesk/config.py`
- Create: `tests/test_multi_pattern.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_multi_pattern.py`:

```python
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
```

Note this file already imports `sqlite3`, `render_mod`, `summarize`, and `Store`, which aren't used yet in this task, they're needed by Tasks 2-4, which append to this same file. Declaring them all up front avoids repeated import-list edits across the four tightly-coupled tasks that build this one test file.

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run python -m tests.test_multi_pattern`
Expected: `AttributeError: 'Topic' object has no attribute 'patterns_for_rank'` (or a `TypeError` on `Topic(pattern_tiers=...)` if that fails first)

- [ ] **Step 3: Modify `newsdesk/config.py`**

Replace the `Topic` dataclass (currently `newsdesk/config.py:43-60`):

```python
@dataclass
class Topic:
    name: str
    slug: str = ""
    pattern: str = ""            # deprecated: use pattern_tiers
    digest_pattern: str = ""     # deprecated: use digest_patterns
    max_items: int = 8
    min_score: float = 0.0
    include: list[str] = field(default_factory=list)   # keywords that boost + gate
    boost: list[str] = field(default_factory=list)     # keywords that only boost
    exclude: list[str] = field(default_factory=list)   # keywords that drop the item
    require_match: bool = True   # drop items matching none of `include`
    sources: list[Source] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.slug:
            self.slug = re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-")
        self.sources = [s if isinstance(s, Source) else Source(**s) for s in self.sources]
```

with:

```python
@dataclass
class Topic:
    name: str
    slug: str = ""
    pattern: str = ""            # deprecated: use pattern_tiers
    digest_pattern: str = ""     # deprecated: use digest_patterns
    pattern_tiers: list[dict] = field(default_factory=list)
    digest_patterns: list[str] = field(default_factory=list)
    max_items: int = 8
    min_score: float = 0.0
    include: list[str] = field(default_factory=list)   # keywords that boost + gate
    boost: list[str] = field(default_factory=list)     # keywords that only boost
    exclude: list[str] = field(default_factory=list)   # keywords that drop the item
    require_match: bool = True   # drop items matching none of `include`
    sources: list[Source] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.slug:
            self.slug = re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-")
        self.sources = [s if isinstance(s, Source) else Source(**s) for s in self.sources]
        # Backward compat: the old singular pattern/digest_pattern keys still
        # work if the new list-based keys weren't given. See
        # docs/superpowers/specs/2026-08-03-multi-pattern-tabs-design.md.
        if not self.pattern_tiers and self.pattern:
            self.pattern_tiers = [{"patterns": [self.pattern]}]
        if not self.digest_patterns and self.digest_pattern:
            self.digest_patterns = [self.digest_pattern]

    def patterns_for_rank(self, position: int) -> list[str]:
        """Which patterns apply to the article at this 0-indexed rank
        position within the topic, per pattern_tiers. Bands are consumed in
        order; a band with no "top" is the catch-all for everything
        remaining and must be the last band."""
        remaining = position
        for band in self.pattern_tiers:
            top = band.get("top")
            if top is None:
                return band["patterns"]
            if remaining < top:
                return band["patterns"]
            remaining -= top
        return []
```

Then replace `Config.all_topics()` (currently `newsdesk/config.py:106-116`):

```python
    def all_topics(self) -> list[Topic]:
        """Every topic/source in config.yaml, ignoring settings-UI toggles.
        Used by the settings page itself, which needs to show disabled
        entries (with their checkbox unchecked), not hide them."""
        defaults = self.raw.get("topic_defaults", {}) or {}
        out = []
        for t in self.raw.get("topics", []):
            merged = {**defaults, **t}
            merged.setdefault("pattern", self.patterns["default"])
            out.append(Topic(**merged))
        return out
```

with:

```python
    def all_topics(self) -> list[Topic]:
        """Every topic/source in config.yaml, ignoring settings-UI toggles.
        Used by the settings page itself, which needs to show disabled
        entries (with their checkbox unchecked), not hide them."""
        defaults = self.raw.get("topic_defaults", {}) or {}
        out = []
        for t in self.raw.get("topics", []):
            merged = {**defaults, **t}
            # Only fall back to the old default-pattern injection when the
            # topic has no pattern_tiers at all (from defaults or its own
            # config) -- otherwise an explicit `pattern_tiers: []` would get
            # silently overwritten by a stale single-pattern tier below.
            if "pattern_tiers" not in merged:
                merged.setdefault("pattern", self.patterns["default"])
            out.append(Topic(**merged))
        return out
```

- [ ] **Step 4: Run the tests again to confirm they pass**

Run: `uv run python -m tests.test_multi_pattern`
Expected: `all checks passed`

- [ ] **Step 5: Run the existing test suites to confirm nothing broke**

```bash
uv run python -m tests.test_state
uv run python -m tests.test_webapp
```

Expected: `all checks passed` for both (`test_pipeline.py` is expected to be broken right now, it still calls the old `summarize_articles`/`digest_topic` signatures; it gets updated in Task 8 -- don't run it yet).

- [ ] **Step 6: Commit**

```bash
git add newsdesk/config.py tests/test_multi_pattern.py
git commit -m "feat: Topic gains pattern_tiers/digest_patterns with backward compat"
```

---

### Task 2: `digests` table migration and `get_digest` pattern param

**Files:**
- Modify: `newsdesk/store.py`
- Test: extend `tests/test_multi_pattern.py`

- [ ] **Step 1: Add the failing test**

Append to `main()` in `tests/test_multi_pattern.py`, right before the final `print`/`return` block:

```python
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
```

- [ ] **Step 2: Run to confirm it fails**

Run: `uv run python -m tests.test_multi_pattern`
Expected: `TypeError: Store.get_digest() takes 3 positional arguments but 4 were given` (or similar, since `get_digest` doesn't accept `pattern` yet and the digests table still has the old PK)

- [ ] **Step 3: Modify `newsdesk/store.py`**

Change the `digests` table definition in `SCHEMA` (currently `newsdesk/store.py:47-55`):

```python
CREATE TABLE IF NOT EXISTS digests (
    edition     TEXT NOT NULL,
    topic       TEXT NOT NULL,
    pattern     TEXT,
    model       TEXT,
    output      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (edition, topic)
);
```

to:

```python
CREATE TABLE IF NOT EXISTS digests (
    edition     TEXT NOT NULL,
    topic       TEXT NOT NULL,
    pattern     TEXT NOT NULL,
    model       TEXT,
    output      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (edition, topic, pattern)
);
```

Add a migration method and call it from `__init__`. Change `Store.__init__` (currently `newsdesk/store.py:92-102`):

```python
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Feeds are fetched on a thread pool, so the connection is shared under a lock.
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.RLock()
        with self._lock:
            self.db.executescript(SCHEMA)
            self.db.commit()
```

to:

```python
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Feeds are fetched on a thread pool, so the connection is shared under a lock.
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.RLock()
        with self._lock:
            self._migrate_digests_table()
            self.db.executescript(SCHEMA)
            self.db.commit()

    def _migrate_digests_table(self) -> None:
        """digests used to key on (edition, topic) alone; multi-pattern
        digests need pattern in the primary key too. Cached digests are
        cheap to regenerate, so an old-shaped table is just dropped and
        recreated by SCHEMA below rather than migrated in place."""
        cols = self.db.execute("PRAGMA table_info(digests)").fetchall()
        if not cols:
            return  # no such table yet; SCHEMA below creates the new shape
        pattern_col = next((c for c in cols if c["name"] == "pattern"), None)
        if pattern_col and pattern_col["pk"] > 0:
            return  # already the new shape
        self.db.execute("DROP TABLE digests")
```

Change `get_digest` (currently `newsdesk/store.py:174-177`):

```python
    def get_digest(self, edition: str, topic: str) -> str | None:
        rows = self._query("SELECT output FROM digests WHERE edition=? AND topic=?",
                           (edition, topic))
        return rows[0]["output"] if rows else None
```

to:

```python
    def get_digest(self, edition: str, topic: str, pattern: str) -> str | None:
        rows = self._query(
            "SELECT output FROM digests WHERE edition=? AND topic=? AND pattern=?",
            (edition, topic, pattern))
        return rows[0]["output"] if rows else None
```

`put_digest` doesn't need to change, it already takes `pattern` as an argument (`newsdesk/store.py:179-182`), only the table's primary key changed underneath it.

- [ ] **Step 4: Run the tests again**

Run: `uv run python -m tests.test_multi_pattern`
Expected: `all checks passed`

- [ ] **Step 5: Commit**

```bash
git add newsdesk/store.py tests/test_multi_pattern.py
git commit -m "feat: digests table keys on (edition, topic, pattern)"
```

---

### Task 3: Tiered `summarize_articles` and multi-pattern `digest_topic`

**Files:**
- Modify: `newsdesk/summarize.py`
- Test: extend `tests/test_multi_pattern.py`

- [ ] **Step 1: Add the failing test**

Append to `main()` in `tests/test_multi_pattern.py`, right before the final `print`/`return` block:

```python
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
```

- [ ] **Step 2: Run to confirm it fails**

Run: `uv run python -m tests.test_multi_pattern`
Expected: `TypeError` on the `summarize_articles(...)` call (signature mismatch: old signature is `(items, store, provider, library, pattern, limit, ...)`)

- [ ] **Step 3: Modify `newsdesk/summarize.py`**

Replace `summarize_articles` (currently `newsdesk/summarize.py:127-147`):

```python
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
```

with:

```python
def summarize_articles(items, store, provider, library, topic,
                       max_items: int, budget: int, min_words: int = 120,
                       force: bool = False) -> int:
    """Run each of the first `max_items` articles' tier-appropriate patterns
    (topic.patterns_for_rank), stopping early once `budget` total pattern
    calls have been made. Returns calls made, so the caller can subtract it
    from a run-wide budget shared across topics."""
    if isinstance(provider, NoneProvider):
        return 0
    calls = 0
    for i, item in enumerate(items[:max_items]):
        row = item["row"]
        if (row["word_count"] or 0) < min_words and not (row["blurb"] or "").strip():
            continue
        for pattern in topic.patterns_for_rank(i):
            if calls >= budget:
                return calls
            if not force and store.get_summary(row["id"], pattern):
                continue
            try:
                out = run_pattern(provider, library, pattern, article_input(row))
            except Exception as exc:  # noqa: BLE001 - one bad article must not kill the run
                log.warning("summary failed for %s (%s): %s", row["title"][:60], pattern, exc)
                continue
            if out:
                store.put_summary(row["id"], pattern, out, provider.name)
                calls += 1
    return calls
```

Replace `digest_topic` (currently `newsdesk/summarize.py:150-181`):

```python
def digest_topic(items, store, provider, library, topic, edition: str,
                 pattern: str, top_n: int = 8, force: bool = False) -> str:
    """One synthesized 'what matters today' brief per topic."""
    if not pattern:
        return ""
    cached = store.get_digest(edition, topic.slug)
    if cached and not force:
        return cached
    if isinstance(provider, NoneProvider):
        # Can't generate a new digest without a model, but a `--no-llm` or
        # LLM-unavailable rebuild shouldn't blank out a digest already
        # cached from an earlier run today.
        return cached or ""

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
```

with:

```python
def _build_digest_content(items, store, topic, edition: str, top_n: int) -> str | None:
    """The digest prompt's input: the topic's top `top_n` articles, each
    with whatever per-article summary is available. Returns None when
    there's nothing to digest (no items)."""
    lines = []
    for i, item in enumerate(items[:top_n], 1):
        row = item["row"]
        summary = ""
        for pattern in topic.patterns_for_rank(i - 1):
            summary = store.get_summary(row["id"], pattern)
            if summary:
                break
        summary = summary or row["blurb"] or ""
        lines.append(f"{i}. {row['title']} ({row['source']})\n{summary[:1200]}\n")
    if not lines:
        return None
    return (f"Topic: {topic.name}\nEdition: {edition}\n\n"
           "Today's ranked items:\n\n" + "\n".join(lines))


def digest_topic(items, store, provider, library, topic, edition: str,
                 top_n: int = 8, force: bool = False) -> dict[str, str]:
    """One synthesized 'what matters today' brief per configured digest
    pattern for this topic. Returns {pattern: output} for whatever patterns
    produced something (cached or freshly generated)."""
    results: dict[str, str] = {}
    content = None  # built lazily; identical for every pattern, so build it once
    for pattern in topic.digest_patterns:
        cached = store.get_digest(edition, topic.slug, pattern)
        if cached and not force:
            results[pattern] = cached
            continue
        if isinstance(provider, NoneProvider):
            # Can't generate a new digest without a model, but a `--no-llm`
            # or LLM-unavailable rebuild shouldn't blank out a digest
            # already cached from an earlier run today.
            if cached:
                results[pattern] = cached
            continue
        if content is None:
            content = _build_digest_content(items, store, topic, edition, top_n)
            if content is None:
                break  # nothing to digest for any pattern
        try:
            out = run_pattern(provider, library, pattern, content)
        except Exception as exc:  # noqa: BLE001
            log.warning("digest failed for %s (%s): %s", topic.name, pattern, exc)
            continue
        if out:
            store.put_digest(edition, topic.slug, pattern, out, provider.name)
            results[pattern] = out
    return results
```

- [ ] **Step 4: Run the tests again**

Run: `uv run python -m tests.test_multi_pattern`
Expected: `all checks passed`

- [ ] **Step 5: Commit**

```bash
git add newsdesk/summarize.py tests/test_multi_pattern.py
git commit -m "feat: tiered per-article summarization and multi-pattern digests"
```

---

### Task 4: `render.py` - `humanize_pattern` and multi-summary `build_view`

**Files:**
- Modify: `newsdesk/render.py`
- Test: extend `tests/test_multi_pattern.py`

- [ ] **Step 1: Add the failing test**

Append to `main()` in `tests/test_multi_pattern.py`, right before the final `print`/`return` block:

```python
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
```

(`mp_store`/`tiered_topic` come from Task 3's additions earlier in the same `main()`; both articles already have `create_5_sentence_summary` cached from Task 3's digest test, and `a0` additionally has `extract_insights` from Task 3's tiered-summarize test.)

- [ ] **Step 2: Run to confirm it fails**

Run: `uv run python -m tests.test_multi_pattern`
Expected: `AttributeError: module 'newsdesk.render' has no attribute 'humanize_pattern'`

- [ ] **Step 3: Modify `newsdesk/render.py`**

Add `humanize_pattern` after `signal_blocks` (currently ending at `newsdesk/render.py:101`):

```python
def humanize_pattern(name: str) -> str:
    """create_5_sentence_summary -> '5 Sentence Summary', extract_wisdom -> 'Wisdom'."""
    for prefix in ("create_", "extract_", "analyze_", "find_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.replace("_", " ").title()
```

Replace `build_view` (currently `newsdesk/render.py:104-139`):

```python
def build_view(topic, ranked, store, cfg) -> dict:
    """Shape one topic's ranked items into template-ready data."""
    items = ranked[:topic.max_items]
    ceiling = max([i["score"] for i in items], default=1.0)
    cards = []
    for item in items:
        row, parts = item["row"], item["parts"]
        summary = store.get_summary(row["id"], topic.pattern)
        cards.append({
            "id": row["id"],
            "title": row["title"],
            "url": row["url"],
            "source": row["source"],
            "author": row["author"],
            "when": relative_time(row["published_at"] or row["fetched_at"]),
            "published_at": row["published_at"],
            "words": row["word_count"] or 0,
            "read_min": max(1, round((row["word_count"] or 0) / 230)) if row["word_count"] else None,
            "blurb": row["blurb"] or "",
            "summary_html": md_to_html(summary) if summary else "",
            "has_summary": bool(summary),
            "score": round(item["score"], 3),
            "blocks": signal_blocks(item["score"], ceiling),
            "parts": parts,
            "matched": parts.get("matched", []),
            "also": [{"source": a["row"]["source"], "url": a["row"]["url"],
                      "title": a["row"]["title"]} for a in item.get("also", [])],
        })
    return {
        "name": topic.name,
        "slug": topic.slug,
        "pattern": topic.pattern,
        "digest_pattern": topic.digest_pattern,
        "count": len(cards),
        "cards": cards,
    }
```

with:

```python
def build_view(topic, ranked, store, cfg) -> dict:
    """Shape one topic's ranked items into template-ready data."""
    items = ranked[:topic.max_items]
    ceiling = max([i["score"] for i in items], default=1.0)
    cached = store.summaries_for([item["row"]["id"] for item in items])
    cards = []
    for i, item in enumerate(items):
        row, parts = item["row"], item["parts"]
        row_summaries = cached.get(row["id"], {})
        summaries = [
            {"pattern": p, "label": humanize_pattern(p), "html": md_to_html(text)}
            for p in topic.patterns_for_rank(i) if (text := row_summaries.get(p))
        ]
        cards.append({
            "id": row["id"],
            "title": row["title"],
            "url": row["url"],
            "source": row["source"],
            "author": row["author"],
            "when": relative_time(row["published_at"] or row["fetched_at"]),
            "published_at": row["published_at"],
            "words": row["word_count"] or 0,
            "read_min": max(1, round((row["word_count"] or 0) / 230)) if row["word_count"] else None,
            "blurb": row["blurb"] or "",
            "summaries": summaries,
            "score": round(item["score"], 3),
            "blocks": signal_blocks(item["score"], ceiling),
            "parts": parts,
            "matched": parts.get("matched", []),
            "also": [{"source": a["row"]["source"], "url": a["row"]["url"],
                      "title": a["row"]["title"]} for a in item.get("also", [])],
        })
    return {
        "name": topic.name,
        "slug": topic.slug,
        "count": len(cards),
        "cards": cards,
    }
```

Replace the `render()` function's digest-shaping line and add the new filter (currently `newsdesk/render.py:142-161`):

```python
def render(views: list[dict], digests: dict[str, str], cfg, meta: dict,
           link_as_index: bool = True) -> Path:
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)),
                      autoescape=select_autoescape(["html"]), trim_blocks=True,
                      lstrip_blocks=True)
    env.filters["md"] = md_to_html
    template = env.get_template("dashboard.html.j2")

    out_dir = cfg.resolve(cfg.output["dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    edition = meta["edition"]

    html_text = template.render(
        title=cfg.output["title"],
        theme=cfg.output.get("theme", "auto"),
        edition=edition,
        views=views,
        digests={k: md_to_html(v) for k, v in digests.items()},
        meta=meta,
    )
```

with:

```python
def render(views: list[dict], digests: dict[str, dict[str, str]], cfg, meta: dict,
           link_as_index: bool = True) -> Path:
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)),
                      autoescape=select_autoescape(["html"]), trim_blocks=True,
                      lstrip_blocks=True)
    env.filters["md"] = md_to_html
    env.filters["humanize"] = humanize_pattern
    template = env.get_template("dashboard.html.j2")

    out_dir = cfg.resolve(cfg.output["dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    edition = meta["edition"]

    html_text = template.render(
        title=cfg.output["title"],
        theme=cfg.output.get("theme", "auto"),
        edition=edition,
        views=views,
        digests={slug: {pattern: md_to_html(text) for pattern, text in patterns.items()}
                for slug, patterns in digests.items()},
        meta=meta,
    )
```

(the rest of `render()`, from `dated = out_dir / "editions" / ...` onward, is unchanged)

- [ ] **Step 4: Run the tests again**

Run: `uv run python -m tests.test_multi_pattern`
Expected: `all checks passed`

- [ ] **Step 5: Commit**

```bash
git add newsdesk/render.py tests/test_multi_pattern.py
git commit -m "feat: render multi-pattern summaries and digests"
```

---

### Task 5: Template and CSS - digest tabs and per-article tabs

**Files:**
- Modify: `templates/_shared.css.j2`
- Modify: `templates/dashboard.html.j2`

- [ ] **Step 1: Update `templates/_shared.css.j2`**

Remove the now-dead rule (the `pattern` eyebrow label is going away in Step 2 below):

Find:
```css
.eyebrow .pattern{color:var(--accent)}
```

Delete that line entirely.

Find the `.brief` rules:
```css
.brief{
  background:var(--card); border:1px solid var(--rule); border-left:3px solid var(--accent);
  padding:1.1rem 1.3rem; margin-bottom:1.75rem; font-size:.97rem;
}
.brief > :first-child{margin-top:0}
.brief > :last-child{margin-bottom:0}
.brief h4{
  font-family:var(--mono); font-size:.7rem; text-transform:uppercase; letter-spacing:.1em;
  color:var(--accent); margin:1.1rem 0 .4rem; font-weight:600;
}
.brief ul{margin:.3rem 0 .7rem; padding-left:1.1rem}
.brief li{margin-bottom:.3rem}
```

Replace with (adds the tab row and the `[hidden]` rule, everything else unchanged):

```css
.brief-tabs{display:flex; gap:.4rem; margin-bottom:.6rem; flex-wrap:wrap}
.brief-tab{
  font-family:var(--mono); font-size:.68rem; text-transform:uppercase; letter-spacing:.06em;
  background:none; border:1px solid var(--rule); color:var(--ink-2);
  padding:.3rem .6rem; border-radius:3px; cursor:pointer;
}
.brief-tab:hover{border-color:var(--accent); color:var(--accent)}
.brief-tab.active{border-color:var(--accent); color:var(--accent); background:var(--accent-soft)}
.brief{
  background:var(--card); border:1px solid var(--rule); border-left:3px solid var(--accent);
  padding:1.1rem 1.3rem; margin-bottom:1.75rem; font-size:.97rem;
}
.brief[hidden]{display:none}
.brief > :first-child{margin-top:0}
.brief > :last-child{margin-bottom:0}
.brief h4{
  font-family:var(--mono); font-size:.7rem; text-transform:uppercase; letter-spacing:.1em;
  color:var(--accent); margin:1.1rem 0 .4rem; font-weight:600;
}
.brief ul{margin:.3rem 0 .7rem; padding-left:1.1rem}
.brief li{margin-bottom:.3rem}
```

Find the `.summary-body` rules:
```css
.summary-body{
  font-size:.93rem; border-left:1px solid var(--rule); padding-left:1rem;
  margin-top:.6rem; color:var(--ink);
}
.summary-body h4{
  font-family:var(--mono); font-size:.68rem; text-transform:uppercase; letter-spacing:.1em;
  color:var(--ink-3); margin:1rem 0 .35rem; font-weight:600;
}
.summary-body > :first-child{margin-top:0}
.summary-body ul{margin:.25rem 0 .6rem; padding-left:1.05rem}
.summary-body li{margin-bottom:.25rem}
```

Replace with (adds the tab row and the `[hidden]` rule):

```css
.summary-tabs{display:flex; gap:.35rem; margin:.6rem 0 .3rem; flex-wrap:wrap}
.summary-tab{
  font-family:var(--mono); font-size:.64rem; text-transform:uppercase; letter-spacing:.05em;
  background:none; border:1px solid var(--rule); color:var(--ink-3);
  padding:.22rem .5rem; border-radius:3px; cursor:pointer;
}
.summary-tab:hover{border-color:var(--accent); color:var(--accent)}
.summary-tab.active{border-color:var(--accent); color:var(--accent); background:var(--accent-soft)}
.summary-body{
  font-size:.93rem; border-left:1px solid var(--rule); padding-left:1rem;
  margin-top:.6rem; color:var(--ink);
}
.summary-body[hidden]{display:none}
.summary-body h4{
  font-family:var(--mono); font-size:.68rem; text-transform:uppercase; letter-spacing:.1em;
  color:var(--ink-3); margin:1rem 0 .35rem; font-weight:600;
}
.summary-body > :first-child{margin-top:0}
.summary-body ul{margin:.25rem 0 .6rem; padding-left:1.05rem}
.summary-body li{margin-bottom:.25rem}
```

- [ ] **Step 2: Update `templates/dashboard.html.j2`**

Find the topic eyebrow and brief block:

```html
    <header class="topic-head">
      <div class="eyebrow">
        <span>{{ "%02d"|format(loop.index) }}</span>
        <span>{{ v.count }} stor{{ 'y' if v.count == 1 else 'ies' }}</span>
        {% if v.pattern %}<span class="pattern">{{ v.pattern }}</span>{% endif %}
      </div>
      <h2>{{ v.name }}</h2>
    </header>

    {% if digests.get(v.slug) %}
    <div class="brief">{{ digests[v.slug]|safe }}</div>
    {% endif %}
```

Replace with:

```html
    <header class="topic-head">
      <div class="eyebrow">
        <span>{{ "%02d"|format(loop.index) }}</span>
        <span>{{ v.count }} stor{{ 'y' if v.count == 1 else 'ies' }}</span>
      </div>
      <h2>{{ v.name }}</h2>
    </header>

    {% if digests.get(v.slug) %}
    <div class="brief-wrap">
      {% if digests[v.slug]|length > 1 %}
      <div class="brief-tabs">
        {% for pattern, html in digests[v.slug].items() %}
        <button type="button" class="brief-tab{% if loop.first %} active{% endif %}" data-pattern="{{ pattern }}">{{ pattern|humanize }}</button>
        {% endfor %}
      </div>
      {% endif %}
      {% for pattern, html in digests[v.slug].items() %}
      <div class="brief" data-pattern="{{ pattern }}"{% if not loop.first %} hidden{% endif %}>{{ html|safe }}</div>
      {% endfor %}
    </div>
    {% endif %}
```

Find the per-article summary block:

```html
        {% if c.has_summary %}
        <details class="summary">
          <summary>{{ v.pattern }}</summary>
          <div class="summary-body">{{ c.summary_html|safe }}</div>
        </details>
        {% elif c.blurb %}
        <p class="blurb">{{ c.blurb }}</p>
        {% endif %}
```

Replace with:

```html
        {% if c.summaries %}
        <details class="summary">
          <summary>{{ c.summaries[0].label }}{% if c.summaries|length > 1 %} ({{ c.summaries|length }}){% endif %}</summary>
          {% if c.summaries|length > 1 %}
          <div class="summary-tabs">
            {% for s in c.summaries %}
            <button type="button" class="summary-tab{% if loop.first %} active{% endif %}" data-pattern="{{ s.pattern }}">{{ s.label }}</button>
            {% endfor %}
          </div>
          {% endif %}
          {% for s in c.summaries %}
          <div class="summary-body" data-pattern="{{ s.pattern }}"{% if not loop.first %} hidden{% endif %}>{{ s.html|safe }}</div>
          {% endfor %}
        </details>
        {% elif c.blurb %}
        <p class="blurb">{{ c.blurb }}</p>
        {% endif %}
```

Find the theme-toggle handler in the `<script>` block:

```javascript
  document.getElementById('theme-toggle').addEventListener('click', () => {
```

Insert immediately before that line:

```javascript
  document.querySelectorAll('.brief-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const wrap = btn.closest('.brief-wrap');
      wrap.querySelectorAll('.brief-tab').forEach(b => b.classList.toggle('active', b === btn));
      wrap.querySelectorAll('.brief[data-pattern]').forEach(el => {
        el.hidden = el.dataset.pattern !== btn.dataset.pattern;
      });
    });
  });

  document.querySelectorAll('.summary-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const details = btn.closest('details.summary');
      details.querySelectorAll('.summary-tab').forEach(b => b.classList.toggle('active', b === btn));
      details.querySelectorAll('.summary-body').forEach(el => {
        el.hidden = el.dataset.pattern !== btn.dataset.pattern;
      });
    });
  });

```

(so the file reads `...tabs setup...\n\n  document.getElementById('theme-toggle')...`: the tab wiring runs once at page load, same as every other `querySelectorAll(...).forEach(...)` handler setup already in this script block)

- [ ] **Step 3: Commit**

```bash
git add templates/_shared.css.j2 templates/dashboard.html.j2
git commit -m "feat: tab UI for multi-pattern digests and summaries"
```

(No automated test yet for the template in isolation, it's exercised end-to-end in Task 8. `newsdesk/render.py`'s `build_view`/`render()` from Tasks 3-4 already produce the shapes this template expects, verified by `tests/test_multi_pattern.py`.)

---

### Task 6: Wire `cli.py` to the new signatures

**Files:**
- Modify: `newsdesk/cli.py`

- [ ] **Step 1: Update `cmd_build`**

Find (currently `newsdesk/cli.py:84-108`):

```python
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
```

Replace with:

```python
    budget = int(cfg.llm.get("max_items_per_run", 40))
    views, digests, scanned = [], {}, 0

    for topic in topics:
        ranked = score.rank(store, topic, cfg.scoring)
        scanned += len(ranked)
        log.info("%-22s %3d ranked", topic.slug, len(ranked))

        if budget > 0 and topic.max_items > 0:
            used = summarize.summarize_articles(
                ranked, store, provider, library, topic,
                max_items=topic.max_items, budget=budget, force=args.force)
            budget -= used
            if used:
                log.info("%-22s %3d summaries", topic.slug, used)

        if topic.digest_patterns:
            digest = summarize.digest_topic(
                ranked[:topic.max_items], store, provider, library, topic,
                edition, force=args.force)
            if digest:
                digests[topic.slug] = digest

        views.append(render.build_view(topic, ranked, store, cfg))
```

- [ ] **Step 2: Update `cmd_doctor`**

Find (currently `newsdesk/cli.py:139-141`):

```python
    wanted = []
    for t in cfg.topics:
        wanted += [t.pattern, t.digest_pattern]
```

Replace with:

```python
    wanted = []
    for t in cfg.topics:
        wanted += [p for band in t.pattern_tiers for p in band["patterns"]] + t.digest_patterns
```

- [ ] **Step 3: Update `cmd_topics`**

Find (currently `newsdesk/cli.py:188`):

```python
        print(f"\n{t.name}  [{t.slug}]  pattern={t.pattern}  digest={t.digest_pattern or '-'}")
```

Replace with:

```python
        tier_desc = ", ".join(
            f"top {b['top']}: {len(b['patterns'])} pattern{'s' if len(b['patterns']) != 1 else ''}"
            if b.get("top") is not None
            else f"rest: {len(b['patterns'])} pattern{'s' if len(b['patterns']) != 1 else ''}"
            for b in t.pattern_tiers) or "none"
        print(f"\n{t.name}  [{t.slug}]  tiers=[{tier_desc}]  digests={len(t.digest_patterns)}")
```

`cmd_last30days` and `cmd_serve` need no changes: `cmd_last30days` never called `digest_topic` (passes `{}` for digests, unaffected by the shape change since it never populates that dict), and `cmd_serve` only touches `webapp.py`, unrelated to summarization.

- [ ] **Step 4: Commit**

```bash
git add newsdesk/cli.py
git commit -m "feat: wire cli.py build/doctor/topics to tiered patterns"
```

(Verified end-to-end in Task 8; `cli.py` has no dedicated unit tests in this project, it's exercised entirely through `tests/test_pipeline.py`.)

---

### Task 7: `config.yaml`, `patterns.py`, and README

**Files:**
- Modify: `config.yaml`
- Modify: `newsdesk/patterns.py`
- Modify: `README.md`

- [ ] **Step 1: Update `config.yaml`**

Find the `topic_defaults` block and the `TOPICS` comment header:

```yaml
# ---------------------------------------------------------------------------
# Applied to every topic unless the topic overrides it.
# ---------------------------------------------------------------------------
topic_defaults:
  max_items: 8
  min_score: 0.15
  require_match: true            # false = keep everything the feed carries

# ---------------------------------------------------------------------------
# TOPICS
#   pattern         Fabric pattern run on each article
#   digest_pattern  Fabric pattern run once across the topic's top stories
#   include         gate + boost (with require_match: true, a story needs one)
#   boost           boost only, never gates
#   exclude         drops the story outright
# ---------------------------------------------------------------------------
topics:
```

Replace with:

```yaml
# ---------------------------------------------------------------------------
# Applied to every topic unless the topic overrides it.
# ---------------------------------------------------------------------------
topic_defaults:
  max_items: 8
  min_score: 0.15
  require_match: true            # false = keep everything the feed carries
  digest_patterns: [create_5_sentence_summary, extract_wisdom, extract_insights, extract_business_ideas]
  pattern_tiers:
    - top: 3                     # the 3 highest-ranked stories in each topic
      patterns: [create_5_sentence_summary, extract_wisdom, extract_insights, extract_business_ideas]
    - patterns: [create_5_sentence_summary]   # everyone else: catch-all, must be last

# ---------------------------------------------------------------------------
# TOPICS
#   pattern_tiers    ranked-position bands -> which patterns run per article
#                    (defaults above; override per-topic to diverge, e.g.
#                    pattern_tiers: [{patterns: [create_network_threat_landscape]}])
#   digest_patterns  patterns run once across the topic's top stories, shown
#                    as tabs above the topic's brief
#   include          gate + boost (with require_match: true, a story needs one)
#   boost            boost only, never gates
#   exclude          drops the story outright
# ---------------------------------------------------------------------------
topics:
```

Then, for each of the six topics below, delete that topic's `pattern:` and `digest_pattern:` lines (they'll all use the `topic_defaults` above instead). Specifically:

In the `security` topic, delete:
```yaml
    pattern: extract_insights
    digest_pattern: create_network_threat_landscape
```

In the `ai` topic, delete:
```yaml
    pattern: extract_wisdom
    digest_pattern: create_5_sentence_summary
```

In the `delivery` topic, delete:
```yaml
    pattern: extract_main_idea
    digest_pattern: extract_insights
```

In the `quality` topic, delete:
```yaml
    pattern: create_5_sentence_summary
    digest_pattern: create_5_sentence_summary
```

In the `business` topic, delete:
```yaml
    pattern: extract_business_ideas
    digest_pattern: create_5_sentence_summary
```

In the `deep` topic, delete:
```yaml
    pattern: extract_wisdom
    digest_pattern: create_reading_plan
```

Each topic's `name:`/`slug:` line should now be followed directly by `max_items:` (or, for `security`, directly by `max_items: 10`; check each topic reads cleanly after the deletion, no blank line artifacts).

- [ ] **Step 2: Update `newsdesk/patterns.py`**

Find (currently `newsdesk/patterns.py:98-102`):

```python
    "per-topic-digest": [
        "create_network_threat_landscape", "create_reading_plan",
        "create_5_sentence_summary", "extract_insights",
    ],
}
```

Replace with:

```python
    "per-topic-digest": [
        "create_network_threat_landscape", "create_reading_plan",
        "create_5_sentence_summary", "extract_insights",
        "extract_wisdom", "extract_business_ideas",
    ],
}
```

- [ ] **Step 3: Update `README.md`**

Find the "Patterns" section:

```markdown
## Patterns

Patterns are fetched from the Fabric repo on first use and cached under `.cache/patterns`,
so you track upstream edits without vendoring anyone else's prompts.

- `pattern` runs on each article. `extract_insights` and `create_5_sentence_summary` are
  the workhorses. `extract_wisdom` is richer and slower.
- `digest_pattern` runs once per topic across that day's top stories. This is what makes
  the board read like a briefing instead of a list.
  `create_network_threat_landscape` for security, `create_5_sentence_summary` for
  everything else, `create_reading_plan` for a long-reads section.

Override any pattern locally by creating `patterns/<name>/system.md` next to your config.
A local file always wins over the cached copy. Set `patterns.offline: true` to work from
cache only.

Summaries are cached on `(article_id, pattern)`, so a re-run costs nothing. Change a
topic's `pattern` and only the new pattern runs.
```

Replace with:

```markdown
## Patterns

Patterns are fetched from the Fabric repo on first use and cached under `.cache/patterns`,
so you track upstream edits without vendoring anyone else's prompts.

Each topic runs more than one pattern, both per article and for its digest, and shows
the results as tabs so you read to whatever depth you want:

- `pattern_tiers` decides which patterns run on each article, based on its ranked
  position within the topic. A story in the top tier might get all four patterns; a
  story further down might only get the 5-sentence summary. This keeps the board
  useful for a quick scan of everything while going deep on what actually ranked well.
  Each band is `{top: N, patterns: [...]}`, except the last, which is the catch-all
  (no `top` key) and applies to everything not covered by an earlier band.
- `digest_patterns` is a flat list: every pattern in it runs once across the topic's
  top stories for that edition, shown as tabs above the topic's brief.

Both default from `topic_defaults` and can be overridden per topic. The shipped
`config.yaml` applies `create_5_sentence_summary`, `extract_wisdom`, `extract_insights`,
and `extract_business_ideas` to every topic's top 3 stories and digest, and just the
5-sentence summary to the rest.

Override any pattern locally by creating `patterns/<name>/system.md` next to your config.
A local file always wins over the cached copy. Set `patterns.offline: true` to work from
cache only.

Summaries are cached on `(article_id, pattern)` and digests on `(edition, topic, pattern)`,
so a re-run costs nothing. Change a topic's `pattern_tiers`/`digest_patterns` and only the
newly-added patterns run.
```

- [ ] **Step 4: Verify config.yaml still parses**

```bash
uv run python -c "from newsdesk import config; cfg = config.load('config.yaml'); print(len(cfg.all_topics()), 'topics loaded'); [print(t.slug, t.pattern_tiers, t.digest_patterns) for t in cfg.all_topics()]"
```

Expected: 6 topics printed, each with the two-band `pattern_tiers` and 4-pattern `digest_patterns` from `topic_defaults` (no per-topic overrides in the shipped config, so all six should look identical apart from slug).

- [ ] **Step 5: Check for em dashes / en dashes in the changed prose**

```bash
uv run python -c "
import pathlib
for f in ['README.md', 'config.yaml']:
    text = pathlib.Path(f).read_text(encoding='utf-8')
    bad = sum(1 for ch in text if ch in '\u2014\u2013')
    print(f, bad)
"
```

Expected: `0` for both (this project has a hard rule against em/en dashes anywhere in code or docs).

- [ ] **Step 6: Commit**

```bash
git add config.yaml newsdesk/patterns.py README.md
git commit -m "docs: update config.yaml, CURATED patterns, and README for tiers"
```

---

### Task 8: Update `tests/test_pipeline.py` and full verification

**Files:**
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Update the fixture config**

Find the `cfg_text` block (currently `tests/test_pipeline.py:65-91`):

```python
    cfg_text = f"""
profile: {{timezone: America/Edmonton}}
llm: {{provider: none, max_items_per_run: 20}}
patterns: {{cache_dir: "{tmp_posix}/patterns-cache", local_dir: "{tmp_posix}/patterns"}}
scoring: {{half_life_hours: 20, corroboration_bonus: 0.35, keyword_weight: 0.6,
           title_multiplier: 2.0, max_age_hours: 96}}
output: {{dir: "{tmp_posix}/out", db: "{tmp_posix}/test.sqlite3", keep_days: 30, title: Newsdesk}}
topic_defaults: {{max_items: 8, min_score: 0.0}}
topics:
  - name: Security & Threat Intel
    slug: security
    pattern: extract_insights
    digest_pattern: create_5_sentence_summary
    include: [exploit, ransomware, CVE, zero-day, malware, supply chain, CISA, vulnerability]
    exclude: [sponsored, "buyer's guide"]
    sources:
      - {{url: "{base}/alpha.xml", name: Alpha, weight: 1.0}}
      - {{url: "{base}/beta.xml", name: Beta, weight: 1.2}}
  - name: AI Engineering
    slug: ai
    pattern: create_5_sentence_summary
    digest_pattern: ""
    include: [LLM, agent, model, benchmark, quantization, inference]
    exclude: [funding round]
    sources:
      - {{url: "{base}/gamma.xml", name: Gamma, weight: 1.0, full_text: false}}
"""
```

Replace with:

```python
    cfg_text = f"""
profile: {{timezone: America/Edmonton}}
llm: {{provider: none, max_items_per_run: 20}}
patterns: {{cache_dir: "{tmp_posix}/patterns-cache", local_dir: "{tmp_posix}/patterns"}}
scoring: {{half_life_hours: 20, corroboration_bonus: 0.35, keyword_weight: 0.6,
           title_multiplier: 2.0, max_age_hours: 96}}
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
```

(`security` now exercises both tiers, since its fixture has more than one article surviving ranking; `ai` stays single-tier/no-digest, close to its old behavior, so the existing `ai`-topic assertions below still hold without modification.)

- [ ] **Step 2: Update the summarize/digest section**

Find (currently `tests/test_pipeline.py:153-173`):

```python
    # --- summarize ------------------------------------------------------
    stub = StubProvider()
    made = summarize.summarize_articles(sec, store, stub, library, topics[0].pattern, limit=3)
    check("summaries generated", made == 3, str(made))
    cached_run = summarize.summarize_articles(sec, store, stub, library, topics[0].pattern, limit=3)
    check("summaries are cached, not re-run", cached_run == 0, str(cached_run))
    check("summary persisted", bool(store.get_summary(sec[0]["row"]["id"], topics[0].pattern)))

    digest = summarize.digest_topic(sec, store, stub, library, topics[0],
                                    "2026-08-01", topics[0].digest_pattern)
    check("digest generated", bool(digest))
    check("digest cached", store.get_digest("2026-08-01", "security") == digest)

    # A later --no-llm rebuild the same day must not blank out a digest
    # already generated by an earlier run with a real provider.
    none_prov = summarize.NoneProvider()
    no_llm_digest = summarize.digest_topic(sec, store, none_prov, library, topics[0],
                                           "2026-08-01", topics[0].digest_pattern)
    check("cached digest survives a --no-llm rerun", no_llm_digest == digest)
    check("none provider makes no calls",
          summarize.summarize_articles(ai, store, none_prov, library, "x", limit=5) == 0)
```

Replace with:

```python
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
```

- [ ] **Step 3: Update the render/output section**

Find (currently `tests/test_pipeline.py:180-206`):

```python
    # --- render ---------------------------------------------------------
    md = render.md_to_html("SUMMARY:\n\n- one **bold** item\n- two\n\n# Heading\n\ntext")
    check("markdown renders bullets", "<li>one <strong>bold</strong> item</li>" in md, md[:80])
    check("markdown renders caps labels", 'class="label"' in md)
    check("markdown escapes html",
          "&lt;script&gt;" in render.md_to_html("<script>alert(1)</script>"))

    views = [render.build_view(t, r, store, cfg)
             for t, r in ((topics[0], sec), (topics[1], ai))]
    check("view carries summaries", views[0]["cards"][0]["has_summary"])
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
    check("also-covered rendered", 'class="also"' in html)
    check("keyboard handler present", "focusAt" in html)
    check("no unrendered jinja left", "{{" not in html and "{%" not in html)
```

Replace with:

```python
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
```

- [ ] **Step 4: Run `test_pipeline.py` alone first**

Run: `uv run python -m tests.test_pipeline`
Expected: `all checks passed`. If `"tiered summarize makes the expected number of calls"` fails, check how many articles actually survive ranking for the `security` topic (print `len(sec)`) and confirm `expected_calls`'s formula matches; the fixture data itself isn't changed by this task, only the config referencing it, so `len(sec)` should be identical to whatever it was before this task.

- [ ] **Step 5: Run the full suite together**

```bash
uv run python -m tests.test_pipeline
uv run python -m tests.test_state
uv run python -m tests.test_webapp
uv run python -m tests.test_multi_pattern
```

Expected: `all checks passed` for all four, run back to back in the same session (catches any cross-test leftover-state issues).

- [ ] **Step 6: Manual sanity check against the real `config.yaml`**

```bash
uv run newsdesk -c config.yaml doctor
uv run newsdesk -c config.yaml build --no-llm
```

Expected: `doctor` reports pattern-warming for all six patterns (`create_5_sentence_summary`, `extract_wisdom`, `extract_insights`, `extract_business_ideas`, plus whatever's still fetchable) without a Python traceback; `build --no-llm` completes and prints a path to the rendered `index.html`. Open that file in a browser (or `uv run newsdesk -c config.yaml serve` and visit it) and confirm: topics with a digest show a tab row above the brief (even with `--no-llm` there should be no digest content since `NoneProvider` skips generation entirely, so the `.brief-wrap` may simply be absent if no digest was ever cached, that's expected). This is primarily a smoke test that nothing crashes against the real, larger config, not a full visual check (that needs a real LLM run, which is out of scope for this pass, do it yourself with your usual `provider: ollama` config whenever convenient).

- [ ] **Step 7: Check for em dashes / en dashes in everything touched this task**

```bash
uv run python -c "
import pathlib
for f in ['tests/test_pipeline.py', 'tests/test_multi_pattern.py']:
    text = pathlib.Path(f).read_text(encoding='utf-8')
    print(f, sum(1 for ch in text if ch in '\u2014\u2013'))
"
```

Expected: `0` for both.

- [ ] **Step 8: Commit**

```bash
git add tests/test_pipeline.py
git commit -m "test: update test_pipeline.py fixture and assertions for tiered patterns"
```

---

## Done criteria

- `uv run python -m tests.test_pipeline`, `tests.test_state`, `tests.test_webapp`, and `tests.test_multi_pattern` all pass, run together in one session.
- `newsdesk -c config.yaml doctor` and `newsdesk -c config.yaml build --no-llm` both complete without a traceback against the real shipped config.
- A topic with more than one cached digest pattern shows a tab row above its brief on the rendered board; clicking a tab switches the visible brief without a page reload.
- An article whose tier has more than one pattern shows a tab row inside its expanded summary; clicking a tab switches the visible summary without collapsing the details element.
- An article with only one cached pattern shows its summary directly, no tab row, unchanged from today's appearance.
- No em dashes or en dashes anywhere in the files this plan touched.
- README's "Patterns" section and `config.yaml`'s comments describe the new `pattern_tiers`/`digest_patterns` shape, not the old singular keys.
