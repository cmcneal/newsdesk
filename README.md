# newsdesk

A daily news board you actually control. It pulls a configurable set of feeds, ranks
them with an explainable score, runs [Fabric](https://github.com/danielmiessler/fabric)
patterns over the top stories with a local or hosted model, and writes one static HTML
page per edition.

The point of difference versus a feed reader: **the ranking shows its work**. Every
story carries a signal meter, and hovering it gives you the exact multiplication that
put it there. Nothing is a black box you have to trust.

```
feeds ──> fetch ──> rank ──> Fabric patterns ──> static HTML
          (etag)   (explain)  (cached forever)   (one file per day)
```

## Quick start

```bash
# install uv once if you don't have it
# Windows:  winget install astral-sh.uv
# macOS:    brew install uv
# Linux:    curl -LsSf https://astral.sh/uv/install.sh | sh

uv sync

cp config.yaml my.yaml          # edit topics, sources, patterns
uv run newsdesk -c my.yaml doctor    # check every feed, pattern, and the model
uv run newsdesk -c my.yaml build
uv run newsdesk -c my.yaml serve     # http://localhost:8787
```

Run `doctor` first. The feed URLs shipped in `config.yaml` are starting points, not
verified endpoints. Publishers move and retire them, and `doctor` tells you which ones
are live before you find out from an empty board.

No model available yet? `build --no-llm` produces the full board using feed blurbs.
Everything except the summaries works.

## Commands

| Command | What it does |
| --- | --- |
| `build` | Fetch, rank, summarize, render. The daily job. |
| `build --no-llm` | Same, without summaries. Seconds instead of minutes. |
| `build --no-fetch` | Re-render from what is already stored. Use while tuning scoring. |
| `build --force` | Re-run patterns even where a summary is cached. |
| `build --topic security` | One topic only. Repeatable. |
| `doctor` | HEAD every feed, warm every pattern, ping the model. Exit code is the problem count. |
| `patterns` | List available Fabric patterns and what is cached. `--warm all` pre-downloads. |
| `topics` | Print the current ranking as text, with scores. The fastest way to tune. |
| `serve` | Serves the board plus a `/settings` page for toggling sources and topics. |
| `last30days` | Best-of-window digest from stored articles. Does not overwrite today's build. |
| `last30days --days 7` | Same, over the last 7 days. |
| `last30days --topic security` | One topic only. Repeatable. |

## How ranking works

```
score = source_weight
      × recency_decay        0.5 ^ (age_hours / half_life_hours)
      × keyword_factor       1 + keyword_weight × hits   (headline hits count double)
      × corroboration        1 + corroboration_bonus × (outlets_covering − 1)
      × depth                mild bonus for substantial pieces
```

Corroboration is the interesting term. Stories are clustered by headline-token
containment, so when three outlets cover the same breach they collapse into one entry
carrying an "also covered" row, and that entry gets pushed up. One story appearing
everywhere is the strongest available signal that something happened, and it also stops
the board from showing you the same event five times.

Every term is tunable under `scoring:` in the config, and every term is visible in the
UI. Start with `newsdesk topics` and adjust until the text output matches your judgment,
then build.

Filtering per topic:

- `include`: gates and boosts. With `require_match: true`, a story needs at least one.
- `boost`: boosts only, never gates. Use for your specific stack and region.
- `exclude`: drops the story outright. Use for sponsored content and vendor guides.

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

## Running it daily

The summarization pass wants CPU and RAM; serving the page wants neither. Build on a
workstation, publish to whatever is always on.

**systemd (build host)**, at `~/.config/systemd/user/newsdesk.service`:

```ini
[Unit]
Description=newsdesk daily build
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=%h/newsdesk
ExecStart=/usr/local/bin/uv run --project %h/newsdesk newsdesk build
```

`~/.config/systemd/user/newsdesk.timer`:

```ini
[Unit]
Description=Build newsdesk each morning

[Timer]
OnCalendar=*-*-* 05:40:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user enable --now newsdesk.timer
loginctl enable-linger $USER      # so it runs when you are not logged in
```

**Publish to an always-on host:**

```bash
rsync -a --delete out/ pi.local:/var/www/newsdesk/
```

Point nginx or Caddy at that directory. The output is plain static HTML with no server
requirement, so it survives the build host being off, and it prints cleanly.

**cron** if you prefer:

```
40 5 * * * cd ~/newsdesk && uv run newsdesk build >> ~/newsdesk/build.log 2>&1
```

## Model choice

`provider: ollama` is the default. On CPU-only hardware, an 8B model at Q4 handles
extraction and summarization well; `keep_alive` is set to 15 minutes so the model stays
resident across the whole run rather than reloading per article. Budget roughly 30 to 90
seconds per article and cap the run with `llm.max_items_per_run`.

`provider: anthropic` is the same pipeline against the API when you want a faster or
sharper pass. Set `ANTHROPIC_API_KEY` and switch one line. Cached summaries mean you can
mix: run locally most days, force a re-run with the API when something matters.

Reasoning models that emit `<think>` blocks are handled; only the answer is stored.

## Using the board

| Key | Action |
| --- | --- |
| `j` / `k` | Next / previous story |
| `o` or `Enter` | Open the story |
| `s` | Toggle the summary |
| `/` | Filter headlines and sources |
| `1`-`9` | Jump to a topic |
| `g` / `G` | Top / bottom |

Hover any signal meter for the score breakdown. Editions are archived under
`out/editions/YYYY-MM-DD.html`.

## Sources & topics from the browser

`newsdesk serve` exposes a `/settings` page (linked from the board's rail) for
turning sources and topics on and off without hand-editing YAML. Toggles are
stored in a small sidecar file next to your config (`my.state.json` for
`my.yaml`); `config.yaml`/`my.yaml` itself is never rewritten, so your
comments and formatting survive. A change takes effect on the next build; the
settings page has its own "Rebuild now" button if you don't want to switch to
a terminal.

Weights, keywords, and patterns are still config.yaml territory: the
settings page only toggles what's already there.

`--host 0.0.0.0` (for serving to your LAN) exposes `/settings` too, including
the rebuild trigger. There's no auth; keep that in mind before binding beyond
localhost on a network you don't trust.

## Layout

```
config.yaml           topics, sources, patterns, scoring   <- the whole product surface
newsdesk/
  config.py           config loading, env expansion, settings-UI toggle filtering
  state.py            sidecar state file for settings-UI toggles (never touches config.yaml)
  store.py            SQLite: articles, summaries, digests, feed state
  fetch.py            feeds (conditional GET) + full-text extraction
  score.py            ranking and cross-source clustering
  patterns.py         Fabric pattern loader and cache
  summarize.py        providers (ollama / anthropic / none) + pattern execution
  render.py           markdown subset + static HTML
  webapp.py           /settings backend: rendering, toggle API, rebuild trigger
  cli.py              build / doctor / patterns / topics / serve / last30days
templates/
  _shared.css.j2       CSS shared by the board and the settings page
  dashboard.html.j2   the board
  settings.html.j2    the settings page (served at /settings)
tests/
  test_pipeline.py    end-to-end against local fixture feeds
  test_state.py        settings-UI state file + config filtering
  test_webapp.py       settings page backend, end-to-end over a real socket
```

```bash
uv run python -m tests.test_pipeline
uv run python -m tests.test_state
uv run python -m tests.test_webapp
```

`test_pipeline` runs the whole pipeline against fixture feeds on localhost. Needs network
only for the first Fabric pattern fetch. `test_state` and `test_webapp` are network-free.

A full pre-rendered board is checked in at [`sample-board.html`](sample-board.html) if you
want to see the output without running a build first: open it directly in a browser.

## Known edges

- Keyword gating is crude by design. A story about "no vulnerabilities found" still
  matches `vulnerability`. Watch `newsdesk topics` for a week and add `exclude` terms.
- Full-text extraction fails on paywalled and JS-rendered pages. Set `paywalled: true` on
  those sources so it summarizes the feed blurb instead of wasting the fetch.
- Clustering compares headlines only. Two outlets using entirely different framing for
  the same event will not collapse.
- The board is read-only. There is no read/saved state in the UI yet, though the schema
  has the columns for it.
