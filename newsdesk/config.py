"""Configuration loading. One YAML file drives the whole board."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import state as state_mod

ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _expand(value: Any) -> Any:
    """Expand ${VAR} and ${VAR:-default} inside strings, recursively."""
    if isinstance(value, str):
        return ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


@dataclass
class Source:
    url: str
    name: str = ""
    weight: float = 1.0
    kind: str = "rss"          # rss | atom (both handled by feedparser)
    full_text: bool = True     # fetch the article page for better summaries
    paywalled: bool = False    # skip full-text fetch, summarize from the feed blurb

    def __post_init__(self) -> None:
        if not self.name:
            from urllib.parse import urlparse
            self.name = urlparse(self.url).netloc.replace("www.", "")


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


@dataclass
class Config:
    raw: dict
    path: Path

    # --- convenience accessors -------------------------------------------
    # Each property below merges hardcoded defaults with whatever the user's
    # config.yaml overrides, so every key always has a value and callers
    # never need `.get(key, default)` at every use site. Adding a new
    # top-level config.yaml section (a `foo:` block) generally means adding
    # a matching `foo` property here following the same
    # `d = {...defaults...}; d.update(self.raw.get("foo", {})); return d`
    # shape as `patterns`/`scoring`/`output` below.
    @property
    def profile(self) -> dict:
        return self.raw.get("profile", {})

    @property
    def llm(self) -> dict:
        return self.raw.get("llm", {})

    @property
    def patterns(self) -> dict:
        d = {"repo": "danielmiessler/fabric", "ref": "main",
             "cache_dir": ".cache/patterns", "default": "extract_insights"}
        d.update(self.raw.get("patterns", {}))
        return d

    @property
    def scoring(self) -> dict:
        d = {"half_life_hours": 20.0, "corroboration_bonus": 0.35,
             "keyword_weight": 0.6, "title_multiplier": 2.0, "max_age_hours": 96,
             "cluster_threshold": 0.40, "cluster_min_shared": 3}
        d.update(self.raw.get("scoring", {}))
        return d

    @property
    def output(self) -> dict:
        d = {"dir": "out", "db": "newsdesk.sqlite3", "keep_days": 30,
             "title": "Newsdesk", "theme": "auto"}
        d.update(self.raw.get("output", {}))
        return d

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

    def resolve(self, rel: str) -> Path:
        """Resolve a config-relative path."""
        p = Path(rel).expanduser()
        return p if p.is_absolute() else (self.path.parent / p)


def load(path: str | Path = "config.yaml") -> Config:
    path = Path(path).expanduser().resolve()
    with open(path, encoding="utf-8") as fh:
        raw = _expand(yaml.safe_load(fh) or {})
    return Config(raw=raw, path=path)
