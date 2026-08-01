"""Configuration loading. One YAML file drives the whole board."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

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
    pattern: str = ""            # Fabric pattern run per article
    digest_pattern: str = ""     # Fabric pattern run across the topic's top items
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


@dataclass
class Config:
    raw: dict
    path: Path

    # --- convenience accessors -------------------------------------------
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

    @property
    def topics(self) -> list[Topic]:
        defaults = self.raw.get("topic_defaults", {}) or {}
        out = []
        for t in self.raw.get("topics", []):
            merged = {**defaults, **t}
            merged.setdefault("pattern", self.patterns["default"])
            out.append(Topic(**merged))
        return out

    def resolve(self, rel: str) -> Path:
        """Resolve a config-relative path."""
        p = Path(rel).expanduser()
        return p if p.is_absolute() else (self.path.parent / p)


def load(path: str | Path = "config.yaml") -> Config:
    path = Path(path).expanduser().resolve()
    with open(path) as fh:
        raw = _expand(yaml.safe_load(fh) or {})
    return Config(raw=raw, path=path)
