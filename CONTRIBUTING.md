# Contributing to newsdesk

This is a small, single-purpose tool with no framework and no build step
beyond `uv sync`. The goal of this guide is to get you from clone to a
working change fast, with concrete examples of the kinds of contributions
this project actually gets.

## Setup

```bash
uv sync
cp config.yaml my.yaml
uv run newsdesk -c my.yaml doctor
```

`my.yaml` is gitignored on purpose: it's your personal, hand-tuned config
(your feed picks, your API keys via `${ANTHROPIC_API_KEY}`), never
`config.yaml`, which stays the shared template every contributor starts
from.

Run the test suite before and after any change:

```bash
uv run python -m tests.test_pipeline
uv run python -m tests.test_state
uv run python -m tests.test_webapp
```

All three should print `all checks passed`. `test_pipeline` needs network
access once (to fetch a Fabric pattern, which is then cached); the other two
are fully offline.

## How the pieces fit together

```
feeds --> fetch --> rank --> Fabric patterns --> static HTML
          (etag)   (explain)  (cached forever)   (one file per day)
```

| File | Responsibility |
| --- | --- |
| `newsdesk/config.py` | Loads `config.yaml`, merges defaults, applies settings-UI toggles |
| `newsdesk/state.py` | The sidecar file behind the settings-UI toggles |
| `newsdesk/store.py` | All SQLite access: articles, summaries, digests, feed state |
| `newsdesk/fetch.py` | Pulls feeds (conditional GET) and full article text |
| `newsdesk/score.py` | Turns fetched articles into a ranked, explainable list |
| `newsdesk/patterns.py` | Downloads and caches Fabric prompt patterns |
| `newsdesk/summarize.py` | LLM provider abstraction + running a pattern over an article |
| `newsdesk/render.py` | A tiny markdown subset + Jinja2 rendering to static HTML |
| `newsdesk/webapp.py` | The `/settings` page backend served by `newsdesk serve` |
| `newsdesk/cli.py` | Wires all of the above into the `build`/`doctor`/`serve`/etc. commands |

Read `newsdesk/cli.py::cmd_build` first if you're new here: it's the one
function that calls into every other module in the order they actually run.

## Where to look for the "why," not just the "what"

Comments in this codebase are deliberately sparse on *what* the code does
(the code says that) and focused on *why* it's shaped the way it is when
that's not obvious from reading it: a subtle invariant, a workaround for a
real bug, a design tradeoff. If you're about to "simplify" something that
looks convoluted, check for a comment first, it's often there for a reason
you haven't hit yet (see `newsdesk/score.py`'s `cluster()` docstring for an
example of the level of detail to aim for in your own contributions).

For anything substantial enough to have needed a design decision, there's a
real example of how this project documents that: `docs/superpowers/specs/`
and `docs/superpowers/plans/` hold the actual spec and implementation plan
written for the settings-UI feature, including the reasoning that led to
scoping source-toggle identity per-topic instead of per-URL. Worth reading
once to calibrate the kind of "why" this project values; you don't need to
follow that exact process for your own PRs.

## Common contributions, with a walkthrough for each

### Adding or tuning a source or topic

No code change needed. Edit `config.yaml` (or your `my.yaml`), then:

```bash
uv run newsdesk -c my.yaml doctor   # confirm the feed URL is actually live
uv run newsdesk -c my.yaml topics   # see where new stories would rank, fast
```

If you're proposing a *default* source or topic added to `config.yaml`
itself (the shared template), explain in your PR why it earns a spot there:
this file is meant to stay a curated starting point, not grow unbounded.

### Adding a new Fabric pattern to the curated list

`newsdesk/patterns.py::CURATED` is just the list `newsdesk patterns` prints
and `--warm all` pre-downloads; it's not an allowlist; any pattern name that
exists in the [Fabric repo](https://github.com/danielmiessler/fabric) already
works if you reference it in `config.yaml`. Add to `CURATED` when a pattern
is genuinely useful for a news board (as opposed to Fabric's many
video/audio/YouTube-specific patterns, which aren't).

### Adding a new LLM provider

Providers live in `newsdesk/summarize.py`. Every provider is a small class
with two methods:

```python
class Provider:
    name = "none"

    def complete(self, system: str, user: str) -> str:
        raise NotImplementedError

    def available(self) -> tuple[bool, str]:
        return True, "ok"
```

`complete()` sends a system + user prompt and returns the model's answer.
`available()` is what `newsdesk doctor` and a pre-build check call to fail
fast with a clear message instead of dying partway through a long
summarization run, look at `OllamaProvider.available()` for the pattern:
check reachability/config *before* the first real call, return
`(False, "human-readable reason")` rather than raising.

To add one:

1. Write the class in `newsdesk/summarize.py`, following `AnthropicProvider`
   as the simpler of the two existing examples (`OllamaProvider` has extra
   local-model bookkeeping like `keep_alive` that a hosted API doesn't need).
2. Register it in `build_provider()`:
   ```python
   def build_provider(llm_cfg: dict) -> Provider:
       kind = (llm_cfg.get("provider") or "none").lower()
       if kind == "ollama":
           return OllamaProvider(**(llm_cfg.get("ollama") or {}))
       if kind == "anthropic":
           return AnthropicProvider(**(llm_cfg.get("anthropic") or {}))
       # your new provider goes here, following the same shape
       return NoneProvider()
   ```
3. Document the new `provider:` value and its config block in the README's
   "Model choice" section and in `config.yaml`'s comments.
4. Add a `StubProvider`-style check to `tests/test_pipeline.py` if the
   provider has any nontrivial logic worth covering (response parsing,
   `<think>`-block stripping, error handling); a provider that's just an
   HTTP call with no special-casing doesn't need a dedicated test, the
   existing `NoneProvider`/`StubProvider` coverage already exercises the
   calling code around it.

### Adding a new scoring factor

Every term in the score formula is a multiplier, documented at the top of
`newsdesk/score.py`. To add one:

1. Compute your new factor inside `rank()`, alongside `recency`/`keyword`/
   `corroboration`/`depth`.
2. Multiply it into `score`.
3. Add it to `parts` (the dict `rank()` returns per article) so it shows up
   in the signal meter's hover tooltip in `templates/dashboard.html.j2`,
   the whole point of this scoring system is that every factor is visible,
   not a black box.
4. Add a config knob under `scoring:` in `config.yaml` if the factor should
   be tunable (most should be), with a default in
   `Config.scoring`(`newsdesk/config.py`).
5. Update the "How ranking works" formula in `README.md` to match.
6. Add a `tests/test_pipeline.py` check that exercises it with a concrete
   before/after (see the existing `"older story scores lower than newer
   peer"` check for the shape).

### Changing the settings UI (`/settings`)

`newsdesk/webapp.py` is the backend (stdlib `http.server` only, no
framework, on purpose, this is meant to stay a single-user local tool, not
grow into a web app with a dependency tree), `templates/settings.html.j2`
is the page, and `templates/_shared.css.j2` is the CSS both it and the board
share. `tests/test_webapp.py` spins up a real handler on a real socket and
hits it with real HTTP requests rather than mocking anything, follow that
pattern for new endpoints.

### Changing the board's look

`templates/dashboard.html.j2` plus `templates/_shared.css.j2` are the entire
visual system, both pages, board and settings, use the same partial, so a
palette or typography change in `_shared.css.j2` applies everywhere
automatically. Keep it that way: don't fork styles between the two pages.

## Code style

- **stdlib and the existing dependencies only.** No new dependency without a
  strong reason, the project's whole posture is "no framework." `webapp.py`
  is a deliberate example: a JSON API and background subprocess tracking
  built on `http.server`/`subprocess`, not Flask/FastAPI.
- **Tests are plain scripts, not pytest.** Every `tests/test_*.py` file has
  a module-level `check(name, cond, detail)` helper that appends to a
  `FAILED` list, and a `main()` returning `0`/`1`, run via
  `uv run python -m tests.test_whatever`. Match that shape for new test
  files; don't introduce a pytest dependency for one new file.
- **Comment the why, not the what.** See "Where to look for the why" above.
- **Small, focused modules.** If a file you're editing is growing past
  ~200 lines and picking up a second responsibility, that's usually a sign
  it should split, the way `newsdesk/state.py` and `newsdesk/webapp.py` are
  split from `newsdesk/config.py` and `newsdesk/cli.py` rather than folded
  into them.

## Before opening a PR

```bash
uv run python -m tests.test_pipeline
uv run python -m tests.test_state
uv run python -m tests.test_webapp
```

All three passing is the bar. There's no CI configured yet (see
`deploy_prep.md` if you're the maintainer setting the repo up for the first
time), so this is currently the only check; run it yourself before pushing.

Keep PRs scoped to one change. A source/topic tweak, a new provider, and a
scoring change are three separate PRs even if you happen to want all three,
they review faster and revert cleanly if one turns out wrong.
