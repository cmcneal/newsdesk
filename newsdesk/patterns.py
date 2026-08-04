"""Fabric pattern loader.

Patterns are pulled from the Fabric repo on first use and cached on disk, so the
board tracks upstream edits without vendoring anyone else's prompts into this repo.
Drop a file at `patterns/<name>/system.md` next to config.yaml to override one
locally, or to add a pattern of your own.
"""
from __future__ import annotations

from pathlib import Path

import requests

RAW = "https://raw.githubusercontent.com/{repo}/{ref}/data/patterns/{name}/{file}"
TIMEOUT = 20


class PatternError(RuntimeError):
    pass


class PatternLibrary:
    def __init__(self, cache_dir: Path, repo: str = "danielmiessler/fabric",
                 ref: str = "main", local_dir: Path | None = None, offline: bool = False):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.repo, self.ref = repo, ref
        self.local_dir = Path(local_dir) if local_dir else None
        self.offline = offline
        self._mem: dict[str, tuple[str, str]] = {}

    def get(self, name: str) -> tuple[str, str]:
        """Return (system_prompt, user_template). user_template may be ''."""
        if name in self._mem:
            return self._mem[name]
        system = self._read(name, "system.md", required=True)
        user = self._read(name, "user.md", required=False) or ""
        self._mem[name] = (system, user)
        return self._mem[name]

    # ------------------------------------------------------------------
    def _read(self, name: str, filename: str, required: bool) -> str | None:
        if self.local_dir:
            local = self.local_dir / name / filename
            if local.exists():
                return local.read_text(encoding="utf-8")

        cached = self.cache_dir / name / filename
        if cached.exists():
            return cached.read_text(encoding="utf-8")

        if self.offline:
            if required:
                raise PatternError(f"pattern '{name}' not cached and offline mode is on")
            return None

        url = RAW.format(repo=self.repo, ref=self.ref, name=name, file=filename)
        try:
            resp = requests.get(url, timeout=TIMEOUT)
        except requests.RequestException as exc:
            if required:
                raise PatternError(f"cannot fetch pattern '{name}': {exc}") from exc
            return None
        if resp.status_code == 404:
            if required:
                raise PatternError(f"pattern '{name}' not found in {self.repo}@{self.ref}")
            return None
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            if required:
                raise PatternError(f"cannot fetch pattern '{name}': {exc}") from exc
            return None

        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(resp.text, encoding="utf-8")
        return resp.text

    def warm(self, names: list[str]) -> dict[str, str]:
        """Pre-download patterns. Returns {name: 'ok' | error message}."""
        result = {}
        for n in dict.fromkeys(names):
            if not n:
                continue
            try:
                self.get(n)
                result[n] = "ok"
            except Exception as exc:  # noqa: BLE001 - surfaced to the CLI
                result[n] = str(exc)
        return result


# Patterns that make sense for a news board, grouped for the config comments.
CURATED = {
    "per-article": [
        "extract_wisdom", "extract_insights", "extract_ideas", "extract_main_idea",
        "extract_core_message", "extract_article_wisdom", "create_micro_summary",
        # create_5_sentence_summary is Fabric's "5 Levels" pattern (5 words down to
        # 1 word), not a five-sentence summary despite the name. Kept here since
        # it's a real, valid pattern, just not the default baseline anymore.
        "create_5_sentence_summary",
        "analyze_claims", "analyze_paper", "analyze_prose", "analyze_tech_impact",
        "extract_extraordinary_claims", "extract_controversial_ideas",
        "extract_business_ideas", "extract_book_ideas", "extract_book_recommendations",
        "find_hidden_message", "analyze_spiritual_text",
    ],
    "per-topic-digest": [
        "create_network_threat_landscape", "create_reading_plan",
        "create_micro_summary", "create_5_sentence_summary", "extract_insights",
        "extract_wisdom", "extract_business_ideas",
    ],
}
