# Sources & Topics Settings UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/settings` page to `newsdesk serve` that lets you enable/disable sources and topics without editing YAML, plus a "Rebuild now" button — and fix `serve` printing an unusable `http://0.0.0.0:8787/` URL.

**Architecture:** Toggle state lives in a JSON sidecar file next to the active config (never rewrites `config.yaml`/`my.yaml`). `Config.topics` filters against it at load time so every command respects it. `newsdesk serve` grows a small stdlib-only HTTP handler (`newsdesk/webapp.py`) that serves the existing static board plus `/settings` and a tiny JSON API. The settings page reuses the board's exact CSS via a new shared partial.

**Tech Stack:** Python stdlib (`http.server`, `socketserver`, `subprocess`, `json`), Jinja2 (already a dependency), no new packages.

**Spec:** `docs/superpowers/specs/2026-08-01-sources-settings-ui-design.md`

---

## File Structure

- Create: `newsdesk/state.py` — sidecar state file read/write, topic-scoped source keys
- Create: `newsdesk/webapp.py` — settings page rendering, JSON API, rebuild subprocess tracking
- Create: `templates/_shared.css.j2` — CSS extracted from `dashboard.html.j2`, included by both templates
- Create: `templates/settings.html.j2` — the settings page
- Modify: `newsdesk/config.py` — `Config.topics` filters via `state.py`; new `Config.all_topics()` for the unfiltered list
- Modify: `newsdesk/cli.py` — `cmd_serve` uses `webapp.py`, `--host` defaults to `127.0.0.1`, printed URL always usable
- Modify: `templates/dashboard.html.j2` — `<style>` becomes an include of `_shared.css.j2`; rail gets a "Sources" link
- Create: `tests/test_state.py` — state.py + Config filtering, including the shared-URL-across-topics case
- Create: `tests/test_webapp.py` — end-to-end against a real running handler, same style as `tests/test_pipeline.py`
- Modify: `.gitignore` — ignore `*.state.json`
- Modify: `README.md` — document `/settings`, the rebuild button, and the corrected `serve` host default

---

### Task 1: Initialize git

This repo has no version control yet. Everything after this task assumes `git commit` works.

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Confirm there's no existing repo**

Run: `git status`
Expected: `fatal: not a git repository (or any of the parent directories): .git`

- [ ] **Step 2: Add the sidecar state file pattern to .gitignore**

Open `.gitignore` (currently):
```
.venv/
__pycache__/
*.pyc
.cache/
out/
*.sqlite3
*.sqlite3-wal
*.sqlite3-shm
build.log
```

Replace with:
```
.venv/
__pycache__/
*.pyc
.cache/
out/
*.sqlite3
*.sqlite3-wal
*.sqlite3-shm
build.log
*.state.json
```

- [ ] **Step 3: Initialize the repo and make the first commit**

```bash
git init
git add -A
git status
```

Review the `git status` output before committing — this repo currently has `my.yaml` (personal, hand-tuned config) and `newsdesk.zip` sitting in the working tree. Confirm with the user whether either should be excluded before committing; don't commit them silently if in doubt.

```bash
git commit -m "chore: initial commit"
```

---

### Task 2: `newsdesk/state.py` — sidecar state file

**Files:**
- Create: `newsdesk/state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_state.py`:

```python
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
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run python -m tests.test_state`
Expected: `ModuleNotFoundError: No module named 'newsdesk.state'`

- [ ] **Step 3: Write `newsdesk/state.py`**

```python
"""Per-config sidecar state: which topics/sources are toggled off from the
settings UI.

config.yaml / my.yaml is never rewritten by the settings page -- comments and
formatting are hand-authored and must survive forever. Toggle state lives in
a small JSON file next to the config instead, and Config.topics filters
against it at load time (see newsdesk/config.py).
"""
from __future__ import annotations

import json
from pathlib import Path


def state_path(config_path: Path) -> Path:
    """<config-stem>.state.json next to the config, e.g. my.yaml -> my.state.json."""
    return config_path.with_name(config_path.stem + ".state.json")


def source_key(topic_slug: str, url: str) -> str:
    """Sources are scoped per topic: the same feed can legitimately appear in
    more than one topic (e.g. schneier.com/feed under both `security` and
    `deep` in the shipped config), each with its own weight. Disabling it in
    one topic's settings section must not disable it in another."""
    return f"{topic_slug}|{url}"


def load(path: Path) -> dict:
    """Returns {"disabled_topics": set[str], "disabled_sources": set[str]}."""
    if not path.exists():
        return {"disabled_topics": set(), "disabled_sources": set()}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        "disabled_topics": set(raw.get("disabled_topics", [])),
        "disabled_sources": set(raw.get("disabled_sources", [])),
    }


def save(path: Path, state: dict) -> None:
    payload = {
        "disabled_topics": sorted(state["disabled_topics"]),
        "disabled_sources": sorted(state["disabled_sources"]),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def set_enabled(path: Path, kind: str, key: str, enabled: bool) -> dict:
    """Flip one topic or source and persist. kind is 'topic' or 'source'."""
    current = load(path)
    field = "disabled_topics" if kind == "topic" else "disabled_sources"
    if enabled:
        current[field].discard(key)
    else:
        current[field].add(key)
    save(path, current)
    return current
```

- [ ] **Step 4: Run the tests again to confirm they pass**

Run: `uv run python -m tests.test_state`
Expected: `all checks passed`

- [ ] **Step 5: Commit**

```bash
git add newsdesk/state.py tests/test_state.py
git commit -m "feat: add sidecar state file for settings UI toggles"
```

---

### Task 3: `Config.topics` filters via state; add `Config.all_topics()`

**Files:**
- Modify: `newsdesk/config.py:97-105` (the `topics` property)
- Test: extend `tests/test_state.py`

- [ ] **Step 1: Add the failing test to `tests/test_state.py`**

Append to `main()` in `tests/test_state.py`, before the final `print`/`return` block:

```python
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
          "Shared" not in [s.name for s in sec.sources], [s.name for s in sec.sources])
    check("same source URL still present in the other topic",
          "Shared" in [s.name for s in deep.sources], [s.name for s in deep.sources])
    check("security topic still has its other source",
          "A" in [s.name for s in sec.sources])

    # stale state entry (topic/source no longer in config) is a harmless no-op
    state.set_enabled(state_file, "topic", "no-such-topic", False)
    cfg = config_mod.load(cfg_path)
    check("stale disabled-topic entry does not error",
          sorted(t.slug for t in cfg.topics) == ["deep", "security"] or True)
```

Note the last check is intentionally permissive (`or True`) — its only job is to prove `cfg.topics` doesn't raise when the state file references a topic slug that no longer exists in `config.yaml`. Remove the `or True` once you confirm it also returns the sane two-topic list (it should, since the stale slug never matches).

- [ ] **Step 2: Run to confirm the new assertions fail**

Run: `uv run python -m tests.test_state`
Expected: `AttributeError: 'Config' object has no attribute 'all_topics'`

- [ ] **Step 3: Modify `newsdesk/config.py`**

Add the import near the top (after the existing `import yaml`):

```python
from . import state as state_mod
```

Replace the `topics` property (currently `newsdesk/config.py:97-105`):

```python
    @property
    def topics(self) -> list[Topic]:
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
            merged.setdefault("pattern", self.patterns["default"])
            out.append(Topic(**merged))
        return out

    @property
    def topics(self) -> list[Topic]:
        """Topics/sources with settings-UI toggles applied. This is what
        every command (build, doctor, topics, last30days, serve) should use."""
        disabled = state_mod.load(state_mod.state_path(self.path))
        out = []
        for topic in self.all_topics():
            if topic.slug in disabled["disabled_topics"]:
                continue
            topic.sources = [
                s for s in topic.sources
                if state_mod.source_key(topic.slug, s.url) not in disabled["disabled_sources"]
            ]
            out.append(topic)
        return out
```

- [ ] **Step 4: Run the tests again**

Run: `uv run python -m tests.test_state`
Expected: `all checks passed`

- [ ] **Step 5: Run the existing pipeline test to confirm nothing broke**

Run: `uv run python -m tests.test_pipeline`
Expected: `all checks passed` (this exercises `cfg.topics` end-to-end with no state file present — the "everything enabled" path)

- [ ] **Step 6: Commit**

```bash
git add newsdesk/config.py tests/test_state.py
git commit -m "feat: Config.topics filters by settings-UI toggle state"
```

---

### Task 4: Extract shared CSS into `templates/_shared.css.j2`

**Files:**
- Create: `templates/_shared.css.j2`
- Modify: `templates/dashboard.html.j2:11-218`

- [ ] **Step 1: Create `templates/_shared.css.j2`**

Cut the entire CSS ruleset currently between `<style>` and `</style>` in `templates/dashboard.html.j2` (lines 12–218, everything from `:root{` through the `@media print{...}` rule) into this new file, verbatim, with one addition: extend the `.tools button` rules so a plain `<a>` styled as a tool button (used by the new "Sources" link) matches. Change:

```css
.tools button{
  font-family:var(--mono); font-size:.68rem; text-transform:uppercase; letter-spacing:.06em;
  background:none; border:1px solid var(--rule); color:var(--ink-2);
  padding:.3rem .5rem; border-radius:3px; cursor:pointer;
}
.tools button:hover{border-color:var(--accent); color:var(--accent)}
```

to:

```css
.tools button, .tools a{
  font-family:var(--mono); font-size:.68rem; text-transform:uppercase; letter-spacing:.06em;
  background:none; border:1px solid var(--rule); color:var(--ink-2);
  padding:.3rem .5rem; border-radius:3px; cursor:pointer;
  text-decoration:none; display:inline-block;
}
.tools button:hover, .tools a:hover{border-color:var(--accent); color:var(--accent)}
```

Every other rule is copied unchanged — do not reflow, reformat, or "clean up" while moving it. This is a mechanical extraction, not a rewrite.

- [ ] **Step 2: Replace the `<style>` block in `templates/dashboard.html.j2`**

Change:

```html
<style>
:root{
  ...
@media print{.rail,.filter{display:none} main{margin:0; max-width:none}}
</style>
```

to:

```html
<style>
{% include "_shared.css.j2" %}
</style>
```

- [ ] **Step 3: Add the "Sources" link to the rail tools**

In `templates/dashboard.html.j2`, find:

```html
    <div class="tools">
      <button id="theme-toggle" type="button">Theme</button>
      <button id="expand-all" type="button">Expand all</button>
    </div>
```

Replace with:

```html
    <div class="tools">
      <button id="theme-toggle" type="button">Theme</button>
      <button id="expand-all" type="button">Expand all</button>
      <a href="/settings">Sources</a>
    </div>
```

- [ ] **Step 4: Verify the board still renders correctly**

Run: `uv run python -m tests.test_pipeline`
Expected: `all checks passed` — in particular the `"index written"` and `"topics present in html"` checks confirm the template still renders with the include resolved.

- [ ] **Step 5: Commit**

```bash
git add templates/_shared.css.j2 templates/dashboard.html.j2
git commit -m "refactor: extract dashboard CSS into a shared partial"
```

---

### Task 5: `templates/settings.html.j2`

**Files:**
- Create: `templates/settings.html.j2`

- [ ] **Step 1: Create the template**

```html
<!DOCTYPE html>
<html lang="en" data-theme="{{ theme }}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{{ title }} · Sources</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans+Condensed:wght@500;600;700&family=IBM+Plex+Serif:ital,wght@0,400;0,500;1,400&display=swap" rel="stylesheet">
<style>
{% include "_shared.css.j2" %}
.settings-topic{border-top:2px solid var(--ink); padding-top:.6rem; margin-bottom:2.5rem}
.settings-topic .topic-toggle{
  display:flex; align-items:center; gap:.6rem; margin-bottom:1rem; cursor:pointer;
}
.settings-topic h2{
  font-family:var(--sans); font-weight:700; font-size:1.4rem; letter-spacing:-.01em; margin:0;
}
.src-row{
  display:flex; align-items:center; gap:.6rem; padding:.55rem 0;
  border-bottom:1px solid var(--rule-soft); font-family:var(--mono); font-size:.85rem; cursor:pointer;
}
.src-row .name{flex:1; font-family:var(--sans); font-size:.92rem; color:var(--ink)}
.src-row .weight{color:var(--ink-3); font-size:.72rem}
.src-row.off{opacity:.45}
.back-link{
  font-family:var(--mono); font-size:.72rem; text-decoration:none; color:var(--ink-2);
}
.back-link:hover{color:var(--accent)}
.note{font-family:var(--mono); font-size:.68rem; color:var(--ink-3); margin-top:1rem}
.rebuild-log{
  font-family:var(--mono); font-size:.68rem; color:var(--ink-3); margin-top:.6rem;
  white-space:pre-wrap; max-height:12rem; overflow-y:auto;
}
</style>
</head>
<body>

<aside class="rail">
  <div class="masthead">
    <h1 class="wordmark">{{ title }}</h1>
    <div class="rule"></div>
    <div class="edition">Sources &amp; topics</div>
  </div>

  <div><a class="back-link" href="/">&larr; back to the board</a></div>

  <div class="rail-foot">
    <div class="tools">
      <button id="rebuild" type="button">Rebuild now</button>
    </div>
    <div id="rebuild-log" class="rebuild-log" hidden></div>
    <p class="note">Changes apply on the next build.</p>
  </div>
</aside>

<main>
  {% for t in topics %}
  <section class="settings-topic">
    <label class="topic-toggle">
      <input type="checkbox" data-type="topic" data-id="{{ t.slug }}" {% if t.enabled %}checked{% endif %}>
      <h2>{{ t.name }}</h2>
    </label>
    {% for s in t.sources %}
    <label class="src-row{% if not s.enabled %} off{% endif %}">
      <input type="checkbox" data-type="source" data-id="{{ s.key }}" {% if s.enabled %}checked{% endif %}>
      <span class="name">{{ s.name }}</span>
      <span class="weight">weight {{ s.weight }}</span>
    </label>
    {% endfor %}
  </section>
  {% else %}
  <p class="empty">No topics configured.</p>
  {% endfor %}
</main>

<script>
(function () {
  document.querySelectorAll('input[type=checkbox][data-type]').forEach(cb => {
    cb.addEventListener('change', () => {
      const row = cb.closest('.src-row');
      const prev = cb.checked;
      fetch('/api/toggle', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({type: cb.dataset.type, id: cb.dataset.id, enabled: cb.checked}),
      }).then(r => {
        if (!r.ok) throw new Error('toggle failed');
        if (row) row.classList.toggle('off', !cb.checked);
      }).catch(() => { cb.checked = !prev; });
    });
  });

  const log = document.getElementById('rebuild-log');
  const button = document.getElementById('rebuild');
  let timer = null;

  function poll() {
    fetch('/api/rebuild/status').then(r => r.json()).then(s => {
      log.hidden = false;
      log.textContent = s.status + (s.log_tail ? '\n' + s.log_tail : '');
      if (s.status === 'running') {
        timer = setTimeout(poll, 1500);
      } else {
        button.disabled = false;
      }
    });
  }

  button.addEventListener('click', () => {
    button.disabled = true;
    clearTimeout(timer);
    fetch('/api/rebuild', {method: 'POST'}).then(poll);
  });
})();
</script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add templates/settings.html.j2
git commit -m "feat: add settings page template"
```

(No test yet — this template is exercised end-to-end in Task 6.)

---

### Task 6: `newsdesk/webapp.py` — rendering, API, rebuild tracking

**Files:**
- Create: `newsdesk/webapp.py`
- Test: `tests/test_webapp.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_webapp.py`:

```python
"""End-to-end test of the settings UI: real handler, real socket, real
requests. Same style as tests/test_pipeline.py -- no mocking framework,
just start it and hit it.
"""
from __future__ import annotations

import http.client
import json
import socketserver
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from newsdesk import config as config_mod  # noqa: E402
from newsdesk import state, webapp  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{'  ' + detail if detail else ''}")
    if not cond:
        FAILED.append(name)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="newsdesk-webapp-test-"))
    (tmp / "out").mkdir()
    (tmp / "out" / "index.html").write_text("<h1>board</h1>")
    # Forward slashes only: on Windows, tmp's backslashes would land inside a
    # double-quoted YAML string below and get parsed as escape sequences
    # (e.g. \U expects 8 hex digits), breaking the config load. See the same
    # fix already applied in tests/test_pipeline.py.
    tmp_posix = tmp.as_posix()

    cfg_text = f"""
output: {{dir: "{tmp_posix}/out", db: "{tmp_posix}/test.sqlite3", title: Newsdesk}}
topics:
  - name: Security
    slug: security
    sources:
      - {{url: "https://a.test/feed", name: A, weight: 1.0}}
"""
    cfg_path = tmp / "config.yaml"
    cfg_path.write_text(cfg_text)
    cfg = config_mod.load(cfg_path)

    job = webapp.RebuildJob([sys.executable, "-c", "print('build ok')"])
    handler = webapp.make_handler(cfg.path, cfg.resolve(cfg.output["dir"]), job)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def request(method: str, path: str, body: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        payload = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if payload else {}
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    # --- static board still works -------------------------------------------
    status, data = request("GET", "/index.html")
    check("static board still served", status == 200 and b"board" in data)

    # --- settings page ---------------------------------------------------------
    status, data = request("GET", "/settings")
    check("settings page renders", status == 200)
    check("settings page lists the source", b"A" in data and b"Security" in data)
    check("settings page includes the shared CSS", b"--paper" in data)

    # --- api/state ------------------------------------------------------------
    status, data = request("GET", "/api/state")
    body = json.loads(data)
    check("initial state has nothing disabled",
          body == {"disabled_topics": [], "disabled_sources": []}, str(body))

    # --- api/toggle -------------------------------------------------------------
    key = state.source_key("security", "https://a.test/feed")
    status, data = request("POST", "/api/toggle", {"type": "source", "id": key, "enabled": False})
    check("toggle source off succeeds", status == 200)
    status, data = request("GET", "/api/state")
    check("disabled source now shows in state", json.loads(data)["disabled_sources"] == [key])

    status, data = request("POST", "/api/toggle", {"type": "bogus", "id": "x", "enabled": False})
    check("toggle rejects an unknown type", status == 400)

    # --- api/rebuild ------------------------------------------------------------
    status, data = request("POST", "/api/rebuild")
    check("rebuild starts", status == 200 and json.loads(data)["status"] == "started")

    deadline = time.time() + 5
    final_status = None
    while time.time() < deadline:
        _, data = request("GET", "/api/rebuild/status")
        final_status = json.loads(data)
        if final_status["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    check("rebuild finishes", final_status is not None and final_status["status"] == "done",
          str(final_status))
    check("rebuild log captured", "build ok" in (final_status or {}).get("log_tail", ""))

    httpd.shutdown()
    print(f"\n{'-' * 60}")
    if FAILED:
        print(f"{len(FAILED)} FAILED: {', '.join(FAILED)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run to confirm it fails**

Run: `uv run python -m tests.test_webapp`
Expected: `ModuleNotFoundError: No module named 'newsdesk.webapp'`

- [ ] **Step 3: Write `newsdesk/webapp.py`**

```python
"""Local settings UI + a tiny JSON API for `newsdesk serve`.

Everything here is stdlib-only (http.server, socketserver, subprocess) to
match the project's no-framework posture. This is a single-user,
localhost-by-default tool -- see
docs/superpowers/specs/2026-08-01-sources-settings-ui-design.md for the
trust model.
"""
from __future__ import annotations

import http.server
import json
import subprocess
import threading
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config as config_mod
from . import state as state_mod

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
LOG_TAIL_CHARS = 4096


class RebuildJob:
    """Tracks at most one background `newsdesk build` subprocess at a time."""

    def __init__(self, command: list[str]):
        self.command = command
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._output = ""

    def start(self) -> str:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return "already-running"
            self._output = ""
            self._proc = subprocess.Popen(
                self.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1)
        threading.Thread(target=self._drain, args=(self._proc,), daemon=True).start()
        return "started"

    def _drain(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            with self._lock:
                self._output = (self._output + line)[-LOG_TAIL_CHARS:]
        proc.wait()

    def status(self) -> dict:
        with self._lock:
            if self._proc is None:
                return {"status": "idle", "log_tail": ""}
            code = self._proc.poll()
            st = "running" if code is None else ("done" if code == 0 else "error")
            return {"status": st, "log_tail": self._output}


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)),
                       autoescape=select_autoescape(["html"]), trim_blocks=True,
                       lstrip_blocks=True)


def render_settings_page(cfg_path: Path) -> str:
    """Reloads config.yaml/my.yaml fresh on every call. This is a low-traffic
    local tool and the whole point of /settings is to reflect hand-edits to
    the config made while `serve` is running -- caching a Config at server
    startup would mean a restart is needed to see topic/source changes,
    which defeats half the purpose."""
    cfg = config_mod.load(cfg_path)
    disabled = state_mod.load(state_mod.state_path(cfg_path))
    topics = []
    for topic in cfg.all_topics():
        topics.append({
            "slug": topic.slug,
            "name": topic.name,
            "enabled": topic.slug not in disabled["disabled_topics"],
            "sources": [{
                "name": s.name,
                "weight": s.weight,
                "key": state_mod.source_key(topic.slug, s.url),
                "enabled": state_mod.source_key(topic.slug, s.url) not in disabled["disabled_sources"],
            } for s in topic.sources],
        })
    template = _env().get_template("settings.html.j2")
    return template.render(title=cfg.output["title"], theme=cfg.output.get("theme", "auto"),
                           topics=topics)


def _state_payload(cfg_path: Path) -> dict:
    st = state_mod.load(state_mod.state_path(cfg_path))
    return {"disabled_topics": sorted(st["disabled_topics"]),
            "disabled_sources": sorted(st["disabled_sources"])}


def make_handler(cfg_path: Path, static_dir: Path, rebuild_job: RebuildJob):
    """Builds a request handler class serving `static_dir` for everything
    except the settings routes. One handler instance is created per request
    (stdlib http.server behavior); cfg_path/static_dir/rebuild_job are closed
    over. cfg_path (not a loaded Config) so every settings request re-reads
    config.yaml/my.yaml from disk -- see render_settings_page."""

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(static_dir), **kwargs)

        def log_message(self, fmt, *args):  # noqa: A002 - stdlib signature
            pass  # keep `serve` output to the one startup line

        def do_GET(self):
            if self.path == "/settings":
                self._settings_page()
            elif self.path == "/api/state":
                self._json(200, _state_payload(cfg_path))
            elif self.path == "/api/rebuild/status":
                self._json(200, rebuild_job.status())
            else:
                super().do_GET()

        def do_POST(self):
            if self.path == "/api/toggle":
                self._toggle()
            elif self.path == "/api/rebuild":
                self._json(200, {"status": rebuild_job.start()})
            else:
                self.send_error(404)

        def _settings_page(self) -> None:
            body = render_settings_page(cfg_path).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _toggle(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
                kind, key, enabled = payload["type"], payload["id"], bool(payload["enabled"])
                if kind not in ("topic", "source"):
                    raise ValueError("type must be 'topic' or 'source'")
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                self._json(400, {"error": str(exc)})
                return
            new_state = state_mod.set_enabled(state_mod.state_path(cfg_path), kind, key, enabled)
            self._json(200, {"disabled_topics": sorted(new_state["disabled_topics"]),
                             "disabled_sources": sorted(new_state["disabled_sources"])})

        def _json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler
```

- [ ] **Step 4: Run the test again**

Run: `uv run python -m tests.test_webapp`
Expected: `all checks passed`

If `"rebuild finishes"` is flaky/times out, the most likely cause is `_drain` reading from a `Popen` created inside the `with self._lock` block but the thread started outside it referencing `self._proc` — re-check the thread target receives `proc` as an explicit argument (as written above), not `self._proc`, since a second `start()` call could otherwise race with the drain thread reading a stale reference.

- [ ] **Step 5: Commit**

```bash
git add newsdesk/webapp.py tests/test_webapp.py
git commit -m "feat: settings page backend (state API + rebuild trigger)"
```

---

### Task 7: Wire `cmd_serve`, fix the host default

**Files:**
- Modify: `newsdesk/cli.py:236-250` (`cmd_serve`) and `newsdesk/cli.py:282-285` (the `serve` subparser)

- [ ] **Step 1: Replace `cmd_serve`**

Current (`newsdesk/cli.py:236-250`):

```python
def cmd_serve(args) -> int:
    import functools
    import http.server
    import socketserver
    cfg, _, _ = _setup(args)
    root = cfg.resolve(cfg.output["dir"])
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    with socketserver.TCPServer((args.host, args.port), handler) as httpd:
        print(f"serving {root} at http://{args.host}:{args.port}/")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
```

Replace with:

```python
def cmd_serve(args) -> int:
    import socketserver
    import sys
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
```

- [ ] **Step 2: Fix the `--host` default**

Current (`newsdesk/cli.py:282-285`):

```python
    s = sub.add_parser("serve", help="serve the output directory")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8787)
    s.set_defaults(func=cmd_serve)
```

Replace with:

```python
    s = sub.add_parser("serve", help="serve the output directory")
    s.add_argument("--host", default="127.0.0.1",
                   help="bind address (default 127.0.0.1; use 0.0.0.0 to serve on the LAN)")
    s.add_argument("--port", type=int, default=8787)
    s.set_defaults(func=cmd_serve)
```

- [ ] **Step 3: Manual verification**

Run: `uv run newsdesk -c my.yaml build --no-llm --no-fetch` (or against whatever config/db you already have locally), then `uv run newsdesk -c my.yaml serve`

Expected: prints `serving ... at http://127.0.0.1:8787/  (settings: http://127.0.0.1:8787/settings)`. Open both URLs in a browser — the board loads, and `/settings` shows every topic and source with working checkboxes. Toggle one off, reload `/settings`, confirm it stayed off. Click "Rebuild now" and confirm the log area shows progress and finishes.

Then re-run with `--host 0.0.0.0` and confirm the printed URL still says `localhost`, not `0.0.0.0`.

Stop the server with Ctrl-C when done.

- [ ] **Step 4: Run the full automated test suite**

```bash
uv run python -m tests.test_pipeline
uv run python -m tests.test_state
uv run python -m tests.test_webapp
```

Expected: `all checks passed` for all three.

- [ ] **Step 5: Commit**

```bash
git add newsdesk/cli.py
git commit -m "fix: serve defaults to 127.0.0.1 and wires up the settings UI"
```

---

### Task 8: Document it in the README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the `serve` row in the Commands table**

Find:

```
| `serve` | Static file server over the output directory. |
```

Replace with:

```
| `serve` | Serves the board plus a `/settings` page for toggling sources and topics. |
```

- [ ] **Step 2: Add a short section after "Using the board"**

Insert after the existing "Using the board" section (after the `Hover any signal meter...` paragraph, before `## Layout`):

```markdown
## Sources & topics from the browser

`newsdesk serve` exposes a `/settings` page (linked from the board's rail) for
turning sources and topics on and off without hand-editing YAML. Toggles are
stored in a small sidecar file next to your config (`my.state.json` for
`my.yaml`) — `config.yaml`/`my.yaml` itself is never rewritten, so your
comments and formatting survive. A change takes effect on the next build; the
settings page has its own "Rebuild now" button if you don't want to switch to
a terminal.

Weights, keywords, and patterns are still config.yaml territory — the
settings page only toggles what's already there.

`--host 0.0.0.0` (for serving to your LAN) exposes `/settings` too, including
the rebuild trigger. There's no auth; keep that in mind before binding beyond
localhost on a network you don't trust.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document the settings UI"
```

---

## Done criteria

- `uv run python -m tests.test_pipeline`, `tests.test_state`, and `tests.test_webapp` all pass.
- `newsdesk serve` (no flags) prints a `localhost`/`127.0.0.1` URL, never `0.0.0.0`.
- `/settings` shows every topic and source from the active config, toggling persists across a page reload, and a source shared by two topics can be disabled in one without affecting the other.
- Disabling a source/topic and running `newsdesk build` (or clicking "Rebuild now") measurably drops it from the output.
- README documents the new page and the corrected `serve` default.
