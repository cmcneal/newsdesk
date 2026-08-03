# Multi-pattern tabs: per-topic digests and per-article summaries

Status: approved
Date: 2026-08-03

## Problem

Today every topic has exactly one `pattern` (run per article) and one
`digest_pattern` (run once across the topic's top articles). You can only
read one lens on a story or a topic's daily brief, whichever the config
picked, without re-running the whole pipeline under a different pattern.

## Goals

- Every topic's digest can run several patterns (e.g. 5-sentence summary,
  extract wisdom, extract insights, extract business ideas) and show them as
  tabs, so you pick the lens per topic per edition.
- Every article can likewise get more than one pattern, shown as tabs inside
  its expandable summary, so you read to whatever depth you want per story.
- Cost stays bounded: not every article needs to justify running 4 patterns.
  Ranked position within a topic determines how many patterns an article
  gets, via a configurable tier list (e.g. "top 3 get all 4 patterns, the
  rest get just the 5-sentence summary").
- Both `pattern_tiers` and `digest_patterns` are configurable per topic
  (via the existing `topic_defaults` + per-topic override merge), not a
  single hardcoded set of patterns baked into the code.

## Non-goals

- No new pattern discovery UI. Which patterns exist is still whatever's in
  `newsdesk/patterns.py::CURATED` plus anything in the Fabric repo or a
  local override, unchanged.
- No change to how articles are fetched, deduped, or ranked. This only
  changes what happens to already-ranked articles at summarization time.
- No live re-tabbing without a rebuild: switching tabs is client-side over
  content already baked into the static HTML at build time, same as today's
  single-pattern summaries.

## Config schema

```yaml
topic_defaults:
  digest_patterns: [create_5_sentence_summary, extract_wisdom, extract_insights, extract_business_ideas]
  pattern_tiers:
    - top: 3
      patterns: [create_5_sentence_summary, extract_wisdom, extract_insights, extract_business_ideas]
    - patterns: [create_5_sentence_summary]   # catch-all: no "top" key, must be last
```

`digest_patterns` is a flat list; every pattern in it runs once for the
topic's digest, every edition (not tiered, since it's one call per pattern
per topic, not per article: cheap regardless of topic size).

`pattern_tiers` is an ordered list of bands. Each band except the last has a
`top` count; a band with no `top` is the catch-all and must be the last
band. An article's 0-indexed rank position within its topic is walked
against the bands in order (subtracting each band's `top` as it's consumed)
to find which band it falls into, and it gets every pattern in that band.

Both fields live at `topic_defaults` level by default and can be overridden
per-topic exactly like `max_items`/`min_score` already are today (the
existing `{**defaults, **topic_dict}` merge in `Config.all_topics()`
requires no change to support this: `pattern_tiers`/`digest_patterns` are
just two more keys that participate in the same merge).

### Backward compatibility

`Topic` keeps its existing `pattern: str = ""` and `digest_pattern: str = ""`
fields (so a config using the old singular keys doesn't raise a
`TypeError` on construction) and adds `pattern_tiers: list[dict] = field(default_factory=list)`
and `digest_patterns: list[str] = field(default_factory=list)`.
`Topic.__post_init__` synthesizes the new fields from the old ones when the
new ones weren't given:

```python
if not self.pattern_tiers and self.pattern:
    self.pattern_tiers = [{"patterns": [self.pattern]}]
if not self.digest_patterns and self.digest_pattern:
    self.digest_patterns = [self.digest_pattern]
```

This means `my.yaml` (which still uses the old singular keys) keeps working
unmigrated: it just gets a single-tier, single-digest-pattern topic, exactly
today's behavior. `config.yaml` (the shipped template) is updated to the new
list-based shape directly as part of this change, dropping the topic-specific
specialty patterns some topics use today (`security`'s
`create_network_threat_landscape`, `deep`'s `create_reading_plan`) in favor
of the same four patterns applied uniformly, matching what was asked for.
If you want a topic to keep a specialty pattern, add it to that topic's own
`digest_patterns`/`pattern_tiers` override.

### New method: `Topic.patterns_for_rank`

```python
def patterns_for_rank(self, position: int) -> list[str]:
    """Which patterns apply to the article at this 0-indexed rank position
    within the topic, per pattern_tiers. Bands are consumed in order; a
    band with no "top" is the catch-all for everything remaining."""
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

A topic with an empty `pattern_tiers` (shouldn't happen given the
backward-compat synthesis above, but if config sets `pattern_tiers: []`
explicitly) simply summarizes nothing, same as today's `pattern: ""`
already means "no per-article pattern."

## Database changes

`summaries` already keys on `(article_id, pattern)`, so per-article
multi-pattern storage needs no schema change; `store.summaries_for(ids)`
(already exists) returns exactly the `{article_id: {pattern: output}}` shape
needed to bulk-load every cached summary for a topic's articles in one
query.

`digests` currently keys on `(edition, topic)` only, with `pattern` as a
plain (non-key) column. It needs `(edition, topic, pattern)` as the primary
key to hold one row per digest pattern. Per the earlier confirmation,
existing cached digests don't need to survive the upgrade. `Store.__init__`
gets a small migration step run before `executescript(SCHEMA)`:

```python
def _migrate_digests_table(self) -> None:
    cols = self.db.execute("PRAGMA table_info(digests)").fetchall()
    if not cols:
        return  # no such table yet; SCHEMA below will create the new shape
    pattern_col = next((c for c in cols if c["name"] == "pattern"), None)
    if pattern_col and pattern_col["pk"] > 0:
        return  # already the new shape
    self.db.execute("DROP TABLE digests")
```

`get_digest(self, edition, topic, pattern)` gains the `pattern` parameter
(currently `get_digest(self, edition, topic)`); `put_digest` already accepts
`pattern` as an argument, only the underlying table's key changes.

## Summarization logic (`newsdesk/summarize.py`)

`summarize_articles` becomes tier-aware. Its signature changes from
`(items, store, provider, library, pattern, limit, ...)` to
`(items, store, provider, library, topic, max_items, budget, ...)`:

- `max_items` bounds how many *articles* are considered at all (today's
  `topic.max_items`, unchanged in spirit).
- `budget` bounds total *pattern-calls* (LLM calls) across those articles,
  since a single article can now cost more than one call. The caller
  (`cmd_build`) still tracks one global `budget` counter across all topics,
  exactly like today, just now decremented per pattern-call instead of per
  article.
- For each article at position `i`, look up `topic.patterns_for_rank(i)`
  and run every pattern in that list not already cached (unless `force`),
  stopping the moment the budget is exhausted.

`digest_topic` returns a `dict[str, str]` (`{pattern: output}`) instead of a
single string, running once per pattern in `topic.digest_patterns`. Its
article-summary input for the digest prompt picks, per article, the first
pattern in `topic.patterns_for_rank(i)` that has a cached summary (falling
back to the blurb if none do) rather than the old single `topic.pattern`
lookup, since there's no longer one canonical per-article pattern.

## Rendering (`newsdesk/render.py`) and template

`build_view` bulk-loads summaries via `store.summaries_for(ids)` instead of
one `get_summary` call per card, and for each article builds:

```python
"summaries": [
    {"pattern": p, "label": humanize_pattern(p), "html": md_to_html(text)}
    for p in topic.patterns_for_rank(i) if (text := cached.get(p))
],
```

(only patterns that actually have cached output show up, per the
"only show tabs that exist" decision). A small new helper,
`humanize_pattern(name: str) -> str`, strips a leading `create_`/`extract_`/
`analyze_`/`find_` and title-cases the rest (`extract_business_ideas` ->
"Business Ideas", `create_5_sentence_summary` -> "5 Sentence Summary"),
registered as a Jinja filter (`env.filters["humanize"] = humanize_pattern`)
alongside the existing `md` filter.

`digests` passed into the template becomes `dict[str, dict[str, str]]`
(topic slug -> `{pattern: html}`) instead of `dict[str, str]`.

**Topic digest tabs:** a small tab row above the `.brief` box, one button
per pattern with a cached digest, switching which `.brief[data-pattern=...]`
element is visible (all rendered into the DOM, toggled via the `hidden`
attribute, matching how `.story[hidden]` already works elsewhere in this
template rather than introducing a new "hidden" CSS class convention).

**Per-article tabs:** live inside the expanded `.summary-body` area, not in
the `<summary>` line itself. `<summary>` is a native disclosure toggle;
putting interactive tab buttons inside it would mean every tab click also
fires the browser's native open/close toggle, which is exactly the kind of
subtle interaction bug worth avoiding rather than working around with
`stopPropagation`. So `<summary>` keeps showing only the primary pattern's
label (plus a count when there's more than one, e.g. "5 Sentence Summary
(4)"), and the actual tab row is the first thing inside the expanded area,
only reachable once a reader has already opened that story's details,
exactly where the current single pattern name already lives today.

When an article has only one cached pattern, no tab row renders at all,
just the summary body directly, identical to today's single-pattern output.

Existing keyboard/UI behavior is unaffected: `s` still toggles the whole
`<details>` open/closed, "Expand all" still opens every `<details
class="summary">`, filtering still works on `.story[hidden]`. None of that
interacts with the new tabs, which only ever toggle content already inside
an open (or closed) details element.

## `newsdesk/cli.py` changes

- `cmd_build`: update the `summarize_articles` call to the new
  `(items, store, provider, library, topic, max_items, budget, ...)`
  signature; `digest_topic`'s dict return replaces the single digest in the
  `digests` dict passed to `render.render` (`digests[topic.slug] = digest`
  becomes `digests[topic.slug] = digest_dict` when non-empty).
- `cmd_doctor`: warms every pattern across every topic's tiers plus digest
  patterns (`wanted += [p for band in t.pattern_tiers for p in
  band["patterns"]] + t.digest_patterns`) instead of just two.
- `cmd_topics`: prints a tier summary and digest pattern count per topic
  instead of the old single `pattern=`/`digest=` line, e.g.
  `tiers=[top 3: 4 patterns, rest: 1 pattern]  digests=4`.
- `cmd_last30days`: unaffected beyond whatever `render.build_view` needs,
  since it never called `digest_topic` in the first place (it passes an
  empty `digests` dict to `render.render` today).

## `config.yaml`

`topic_defaults` gains `digest_patterns` (the 4 patterns) and
`pattern_tiers` (top 3 get all 4, everyone else gets the 5-sentence
summary alone). Each topic's old singular `pattern:`/`digest_pattern:` line
is removed so every topic uses the shared defaults, unless a specific topic
still wants to diverge (documented as an example via a comment, not
necessarily exercised in the shipped config).

`newsdesk/patterns.py::CURATED["per-topic-digest"]` gains `extract_wisdom`
and `extract_business_ideas` (both already in `CURATED["per-article"]`), so
`newsdesk patterns` lists all four as recognized digest options.

## Testing

- `Topic.patterns_for_rank`: a two-band config returns the top band's
  patterns for positions inside `top`, the catch-all band's patterns
  outside it, and an empty `pattern_tiers` returns `[]`.
- Backward compatibility: a `Topic` built from old-style `pattern`/
  `digest_pattern` keys produces the expected single-tier/single-digest
  synthesis.
- `summarize_articles`: budget is spent per pattern-call, not per article;
  a top-tier article consumes multiple budget units; the run stops the
  moment budget hits zero, mid-article if necessary.
- `digest_topic`: returns one entry per configured digest pattern; a
  `NoneProvider` rerun preserves whichever patterns were already cached
  (extending the existing "cached digest survives `--no-llm`" regression
  test to the multi-pattern case).
- `Store` digests migration: manually create the old-shaped `digests`
  table, construct a `Store` against that database file, confirm the table
  is recreated with `pattern` in its primary key and no exception is
  raised.
- `render.build_view`: an article with two cached patterns produces two
  entries in `summaries` in tier order; an article with only the patterns
  from a lower tier only shows those.
- `humanize_pattern`: a handful of representative pattern names produce the
  expected labels.
- End-to-end (`tests/test_pipeline.py`'s fixture config): updated to the new
  `pattern_tiers`/`digest_patterns` shape, with at least one topic
  configured with two tiers so the fixture run exercises both the "more
  patterns for top stories" and "fewer patterns for the rest" paths, and
  checks that the rendered HTML contains more than one `.summary-body` for
  a top-tier article and more than one `.brief[data-pattern]` for a topic.

## Open questions for implementation

None outstanding for this spec's scope. The source-library research (new
topics, expanded feed lists) is being handled separately and doesn't block
this feature; whichever config ships first should carry the
`pattern_tiers`/`digest_patterns` shape described here regardless of how
many topics/sources it lists.
