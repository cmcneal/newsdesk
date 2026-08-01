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
