"""Ranking. Deterministic and explainable: every story shows why it placed where it did.

score = source_weight
      x recency_decay          (exponential, configurable half life)
      x (1 + keyword_weight * keyword_hits)
      x (1 + corroboration_bonus * (cluster_size - 1))
      x depth_factor           (mild preference for substantial pieces)
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime, timezone

from .config import Topic
from .store import Store

STOP = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "for", "on", "with", "as",
    "is", "are", "was", "were", "be", "by", "at", "from", "that", "this", "it", "its",
    "new", "says", "said", "how", "why", "what", "after", "over", "into", "amid",
}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", text.lower()) if w not in STOP}


def _age_hours(row) -> float:
    stamp = row["published_at"] or row["fetched_at"]
    try:
        then = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return 0.0
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - then).total_seconds() / 3600)


def keyword_hits(row, topic: Topic, title_multiplier: float) -> tuple[float, list[str]]:
    """Weighted keyword matches. Title matches count more than body matches."""
    title = (row["title"] or "").lower()
    body = f"{row['blurb'] or ''} {(row['body'] or '')[:4000]}".lower()
    total, matched = 0.0, []
    for kw in list(topic.include) + list(topic.boost):
        k = kw.lower()
        if k in title:
            total += title_multiplier
            matched.append(kw)
        elif k in body:
            total += 1.0
            matched.append(kw)
    return total, matched


def excluded(row, topic: Topic) -> bool:
    blob = f"{row['title']} {row['blurb'] or ''}".lower()
    return any(x.lower() in blob for x in topic.exclude)


def cluster(rows, threshold: float = 0.40, min_shared: int = 3) -> dict[str, list[str]]:
    """Group near-duplicate stories by title-token containment.

    Two outlets covering the same breach write headlines of very different lengths,
    so Jaccard under-reports. Containment (shared / smaller headline) plus a floor on
    absolute shared tokens matches real coverage without collapsing unrelated stories.
    Landing in one cluster is the strongest available signal that a story matters.
    """
    clusters: dict[str, list[str]] = {}
    reps: list[tuple[str, set[str]]] = []
    for row in rows:
        toks = _tokens(row["title"])
        if not toks:
            clusters.setdefault(row["id"], []).append(row["id"])
            continue
        placed = False
        for cid, ctoks in reps:
            shared = len(toks & ctoks)
            if shared >= min_shared and shared / min(len(toks), len(ctoks)) >= threshold:
                clusters[cid].append(row["id"])
                placed = True
                break
        if not placed:
            clusters[row["id"]] = [row["id"]]
            reps.append((row["id"], toks))
    return clusters


def rank(store: Store, topic: Topic, cfg_scoring: dict) -> list[dict]:
    """Score every recent article in a topic. Writes scores back to the store."""
    half_life = cfg_scoring["half_life_hours"]
    rows = [r for r in store.recent(topic.slug, hours=cfg_scoring["max_age_hours"])
            if not excluded(r, topic)]

    groups = cluster(rows,
                     threshold=cfg_scoring.get("cluster_threshold", 0.40),
                     min_shared=int(cfg_scoring.get("cluster_min_shared", 3)))
    member_of = {aid: cid for cid, members in groups.items() for aid in members}
    sizes = {cid: len(m) for cid, m in groups.items()}

    ranked = []
    for row in rows:
        hits, matched = keyword_hits(row, topic, cfg_scoring["title_multiplier"])
        if topic.require_match and topic.include and hits == 0:
            continue

        recency = 0.5 ** (_age_hours(row) / half_life)
        keyword = 1 + cfg_scoring["keyword_weight"] * hits
        cid = member_of.get(row["id"], row["id"])
        corroboration = 1 + cfg_scoring["corroboration_bonus"] * (sizes.get(cid, 1) - 1)
        words = row["word_count"] or 0
        depth = 1 + 0.15 * math.tanh(words / 900) if words else 1.0

        score = (row["source_weight"] or 1.0) * recency * keyword * corroboration * depth
        parts = {
            "source_weight": round(row["source_weight"] or 1.0, 3),
            "recency": round(recency, 3),
            "keywords": round(keyword, 3),
            "matched": matched[:8],
            "corroboration": round(corroboration, 3),
            "cluster_size": sizes.get(cid, 1),
            "depth": round(depth, 3),
        }
        store.update(row["id"], score=score, score_parts=parts, cluster_id=cid)
        if score >= topic.min_score:
            ranked.append({"row": row, "score": score, "parts": parts, "cluster_id": cid})

    ranked.sort(key=lambda r: r["score"], reverse=True)

    # One entry per cluster in the lead positions; siblings ride along as "also covered".
    lead, seen = [], set()
    siblings: dict[str, list[dict]] = defaultdict(list)
    for item in ranked:
        cid = item["cluster_id"]
        if cid in seen:
            siblings[cid].append(item)
            continue
        seen.add(cid)
        lead.append(item)
    for item in lead:
        item["also"] = siblings.get(item["cluster_id"], [])
    return lead
