"""SQLite persistence. Keeps the board idempotent: re-running never re-summarizes."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id            TEXT PRIMARY KEY,
    url           TEXT NOT NULL,
    canonical_url TEXT,
    title         TEXT NOT NULL,
    source        TEXT NOT NULL,
    source_weight REAL DEFAULT 1.0,
    topic         TEXT NOT NULL,
    author        TEXT,
    published_at  TEXT,
    fetched_at    TEXT NOT NULL,
    blurb         TEXT,
    body          TEXT,
    word_count    INTEGER DEFAULT 0,
    score         REAL DEFAULT 0,
    score_parts   TEXT,
    cluster_id    TEXT,
    status        TEXT DEFAULT 'new',
    read_at       TEXT,
    saved         INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_articles_topic  ON articles(topic, score DESC);
CREATE INDEX IF NOT EXISTS idx_articles_pub    ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_cluster ON articles(cluster_id);

CREATE TABLE IF NOT EXISTS summaries (
    article_id  TEXT NOT NULL,
    pattern     TEXT NOT NULL,
    model       TEXT,
    output      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (article_id, pattern)
);

CREATE TABLE IF NOT EXISTS digests (
    edition     TEXT NOT NULL,
    topic       TEXT NOT NULL,
    pattern     TEXT,
    model       TEXT,
    output      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (edition, topic)
);

CREATE TABLE IF NOT EXISTS feed_state (
    url          TEXT PRIMARY KEY,
    etag         TEXT,
    last_modified TEXT,
    last_ok      TEXT,
    last_error   TEXT,
    error_count  INTEGER DEFAULT 0
);
"""


def article_id(url: str, title: str) -> str:
    return hashlib.sha1(f"{normalize_url(url)}|{title.strip().lower()}".encode()).hexdigest()[:16]


def normalize_url(url: str) -> str:
    """Strip tracking params so the same story from two feeds dedupes."""
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    parts = urlsplit(url.strip())
    drop = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "ref", "ref_src", "source", "mc_cid", "mc_eid", "fbclid", "gclid"}
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in drop])
    return urlunsplit((parts.scheme, parts.netloc.lower().replace("www.", ""),
                       parts.path.rstrip("/"), query, ""))


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
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

    def _exec(self, sql: str, args=()):
        with self._lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def _query(self, sql: str, args=()):
        with self._lock:
            return self.db.execute(sql, args).fetchall()

    # --- articles ---------------------------------------------------------
    def upsert_article(self, art: dict) -> bool:
        """Insert if new. Returns True when the row was newly created."""
        cols = ("id", "url", "canonical_url", "title", "source", "source_weight", "topic",
                "author", "published_at", "fetched_at", "blurb", "body", "word_count",
                "score", "score_parts", "cluster_id")
        row = {c: art.get(c) for c in cols}
        row["fetched_at"] = row["fetched_at"] or now()
        if isinstance(row.get("score_parts"), dict):
            row["score_parts"] = json.dumps(row["score_parts"])
        cur = self._exec(
            f"INSERT OR IGNORE INTO articles ({','.join(cols)}) "
            f"VALUES ({','.join(':' + c for c in cols)})", row)
        return cur.rowcount > 0

    def update(self, aid: str, **fields) -> None:
        if not fields:
            return
        if isinstance(fields.get("score_parts"), dict):
            fields["score_parts"] = json.dumps(fields["score_parts"])
        sets = ", ".join(f"{k}=:{k}" for k in fields)
        self._exec(f"UPDATE articles SET {sets} WHERE id=:id", {**fields, "id": aid})

    def recent(self, topic: str | None = None, hours: int = 96) -> list[sqlite3.Row]:
        # timespec="seconds" matches now()'s precision: stored timestamps
        # never carry microseconds, so the cutoff can't either, or a string
        # comparison against a stored value from the same second sorts wrong.
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        sql = ("SELECT * FROM articles WHERE COALESCE(published_at, fetched_at) >= ? "
               + ("AND topic = ? " if topic else "")
               + "ORDER BY score DESC, published_at DESC")
        args: tuple = (cutoff, topic) if topic else (cutoff,)
        return self._query(sql, args)

    def by_id(self, aid: str) -> sqlite3.Row | None:
        rows = self._query("SELECT * FROM articles WHERE id=?", (aid,))
        return rows[0] if rows else None

    # --- summaries --------------------------------------------------------
    def get_summary(self, aid: str, pattern: str) -> str | None:
        rows = self._query("SELECT output FROM summaries WHERE article_id=? AND pattern=?",
                           (aid, pattern))
        return rows[0]["output"] if rows else None

    def put_summary(self, aid: str, pattern: str, output: str, model: str) -> None:
        self._exec(
            "INSERT OR REPLACE INTO summaries (article_id, pattern, model, output, created_at) "
            "VALUES (?,?,?,?,?)", (aid, pattern, model, output, now()))

    def summaries_for(self, ids: Iterable[str]) -> dict[str, dict[str, str]]:
        ids = list(ids)
        if not ids:
            return {}
        q = ",".join("?" * len(ids))
        out: dict[str, dict[str, str]] = {}
        for r in self._query(f"SELECT * FROM summaries WHERE article_id IN ({q})", ids):
            out.setdefault(r["article_id"], {})[r["pattern"]] = r["output"]
        return out

    # --- digests ----------------------------------------------------------
    def get_digest(self, edition: str, topic: str) -> str | None:
        rows = self._query("SELECT output FROM digests WHERE edition=? AND topic=?",
                           (edition, topic))
        return rows[0]["output"] if rows else None

    def put_digest(self, edition: str, topic: str, pattern: str, output: str, model: str) -> None:
        self._exec(
            "INSERT OR REPLACE INTO digests (edition, topic, pattern, model, output, created_at) "
            "VALUES (?,?,?,?,?,?)", (edition, topic, pattern, model, output, now()))

    # --- feed state -------------------------------------------------------
    def feed_state(self, url: str) -> dict[str, Any]:
        rows = self._query("SELECT * FROM feed_state WHERE url=?", (url,))
        return dict(rows[0]) if rows else {}

    def save_feed_state(self, url: str, etag=None, last_modified=None, error=None) -> None:
        prev = self.feed_state(url)
        errors = (prev.get("error_count") or 0) + 1 if error else 0
        self._exec(
            "INSERT OR REPLACE INTO feed_state (url, etag, last_modified, last_ok, last_error, error_count)"
            " VALUES (?,?,?,?,?,?)",
            (url, etag or prev.get("etag"), last_modified or prev.get("last_modified"),
             prev.get("last_ok") if error else now(), error, errors))

    def prune(self, keep_days: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat(timespec="seconds")
        cur = self._exec(
            "DELETE FROM articles WHERE saved=0 AND COALESCE(published_at, fetched_at) < ?", (cutoff,))
        self._exec("DELETE FROM summaries WHERE article_id NOT IN (SELECT id FROM articles)")
        return cur.rowcount
