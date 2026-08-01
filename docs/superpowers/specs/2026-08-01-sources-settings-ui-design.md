# Sources & topics settings UI

Status: approved
Date: 2026-08-01

## Problem

Every source/topic edit today means opening `config.yaml` (or `my.yaml`) in a
text editor, hand-editing YAML, and re-running `newsdesk build`. There's no way
to see or toggle sources/topics from the board itself, which is where you
notice a feed has gone stale or noisy.

## Goals

- See every topic and its sources from the browser, styled exactly like the
  existing board (same rail, same type system, same palette).
- Toggle a source or a topic on/off without touching YAML.
- Trigger a rebuild from the same page, with visible busy/done state.
- Never rewrite `config.yaml`/`my.yaml` — hand-authored comments and structure
  must survive forever.

## Non-goals

- Editing weights, keywords (include/boost/exclude), patterns, or scoring from
  the UI. Still config.yaml territory.
- Adding or removing sources/topics entirely (CRUD). Toggling existing entries
  only.
- Auth. This is a local personal tool; see "Security" below for the scope of
  that assumption.

## Design

### Persistence: sidecar state file, not a config rewrite

A JSON file lives next to the active config, named after it:
`<config-stem>.state.json` (e.g. `my.yaml` → `my.state.json`). Shape:

```json
{"disabled_topics": ["business"], "disabled_sources": ["security|https://example.com/feed"]}
```

Topic identity is the slug. Source identity is **`"<topic-slug>|<url>"`, not
the bare URL.** The same feed can legitimately appear under more than one
topic in this exact config (e.g. `schneier.com/feed` is a source of both
`security` and `deep`, `simonwillison.net/atom/everything` of both `ai` and
`deep`, each with its own weight). `store.py::feed_state` keys fetch/etag
state by bare URL because that's about the HTTP fetch, which is genuinely
shared — but *enabling a source is a per-topic decision*, so disabling it in
one topic's section of the settings page must not silently disable it in
another topic that happens to share the feed. The topic-scoped key makes that
the only possible reading.

`Config.topics` (in `newsdesk/config.py`) loads this file at the same time it
builds the topic list, and:
- drops any topic whose slug is in `disabled_topics`
- for each remaining topic, drops any of its sources where `"<topic.slug>|<source.url>"`
  is in `disabled_sources`

This makes the filtering apply uniformly to every command that reads
`cfg.topics` — `build`, `doctor`, `topics`, `last30days` — not just `serve`.
No command-specific special-casing.

The state file is created on first toggle; absence means "everything enabled"
(today's behavior, unchanged). It's config-adjacent, so it's gitignored like
the db and cache, and per-config (switching `-c` switches state too).

### New module: `newsdesk/state.py`

Small, focused, mirrors the shape of `config.py`:

```python
def load(path: Path) -> dict          # {"disabled_topics": set[str], "disabled_sources": set[str]}
def save(path: Path, state: dict) -> None
def state_path(config_path: Path) -> Path   # derives "<stem>.state.json" next to config
```

`config.py` imports this to filter `topics` — a small, explicit dependency,
not a circular one (`state.py` doesn't import `config.py`).

### UI: `/settings`, served alongside the board

`cmd_serve` currently hands everything to
`http.server.SimpleHTTPRequestHandler` for static files. It gains a subclass
that intercepts a few paths before falling back to static serving:

- `GET /settings` → renders `templates/settings.html.j2` with the current
  topic/source list and enabled state (server reloads config fresh per
  request — this is a low-traffic local tool, no caching complexity needed).
- `GET /api/state` → `{"disabled_topics": [...], "disabled_sources": [...]}`
- `POST /api/toggle` → body `{"type": "topic"|"source", "id": "...", "enabled": bool}`,
  updates and re-saves the state file, returns the new state.
- `POST /api/rebuild` → spawns `newsdesk build` (same config, `-c` value
  carried through) as a detached subprocess if one isn't already running;
  returns `{"status": "started"}` or `{"status": "already-running"}`.
- `GET /api/rebuild/status` → `{"status": "idle"|"running"|"done"|"error", "log_tail": "..."}`
  by polling the subprocess and tailing its output into a bounded in-memory
  buffer (last 4KB, matching the granularity `build` already logs at).

No new dependency — this stays on the standard library
(`http.server`/`socketserver`/`subprocess`), matching the project's existing
"no framework" posture.

### Template: `templates/settings.html.j2`

Shares the dashboard's `<style>` block verbatim (extract the shared CSS into
one `{% include %}`'d partial so the two templates can't visually drift — this
is the one refactor worth doing as part of this work, since duplicating ~200
lines of CSS across two templates is exactly the kind of thing that rots).

Layout mirrors the board's rail + sections structure (validated with the user
via the visual companion — option A, not the flat admin-table alternative):

- Rail: "Sources" wordmark/breadcrumb back to the board, then a "Rebuild now"
  button with inline busy/done/error state, no navigation list (there's only
  one page here).
- Main: one section per topic, styled like `.topic-head` on the board
  (top rule, eyebrow, heading), containing a checkbox row per source
  (checkbox, source name, weight as a muted hint) plus one checkbox for the
  topic itself at the top of its section ("disable this whole topic").
- Checkbox changes `POST` immediately to `/api/toggle` (optimistic UI, revert
  on error) — no separate "Save" step, consistent with how the board's own
  theme toggle behaves (instant, persisted to localStorage).
- A small note: "Changes apply on the next build."

### Bug fix: `serve` defaulting to a non-usable host

`cli.py::cmd_serve` today defaults `--host` to `0.0.0.0` and prints
`http://{args.host}:{args.port}/` verbatim — so a plain `newsdesk serve`
prints `http://0.0.0.0:8787/`, which most browsers won't resolve. Fix:
default `--host` to `127.0.0.1`; `--host 0.0.0.0` remains available for
serving to the LAN. The printed line always shows a real, clickable host
(`localhost` when bound to `0.0.0.0`, the literal host otherwise).

## Security

`serve` now accepts small POSTs that write a local file and spawn a
subprocess. Scope is unchanged from today's trust model: this binds to
localhost by default, is a single-user local tool, and the state file only
toggles among sources/topics already present in the loaded config — it can't
inject new URLs or arbitrary config. Rebuild spawns the same `newsdesk build`
the user already runs by hand/cron; no new capability, just a UI trigger for
an existing one. If `--host 0.0.0.0` is used to expose it on a LAN, the
settings/rebuild endpoints are exposed too — worth a one-line callout in the
README next to the existing `--host` flag docs.

## Testing

Extend `tests/test_pipeline.py` (or a new `tests/test_state.py` following the
same no-framework, plain-assertions style) to cover:
- disabling a topic removes it from `cfg.topics`
- disabling a source removes it from its topic's `sources` but keeps the topic
- state file absence behaves identically to "everything enabled" (regression
  guard for existing configs with no state file)
- toggling a topic/source not present in config is a no-op (stale state entry
  after a config edit shouldn't error)
- **a source URL shared by two topics (e.g. add a fixture where `alpha.xml` is
  a source of both topics) can be disabled in one topic without affecting the
  other** — the scenario the topic-scoped `"<slug>|<url>"` key exists to
  prevent

## Open questions for implementation

None — scope is settled. Weight/keyword editing, source add/remove, and auth
are explicitly deferred (see Non-goals).
