"""Static HTML rendering. Output is one self-contained file per edition."""
from __future__ import annotations

import html
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

BULLET = re.compile(r"^\s*[-*\u2022]\s+")
HEADING = re.compile(r"^\s*(#{1,6})\s+(.*)$")
SECTION = re.compile(r"^\s*([A-Z][A-Z0-9 &/'\-]{2,40}):\s*$")
BOLD = re.compile(r"\*\*(.+?)\*\*")
ITALIC = re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)")
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def md_to_html(text: str) -> str:
    """Small markdown subset: headings, ALL-CAPS section labels, bullets, bold, links.

    Fabric patterns emit exactly this shape, so a full markdown dependency buys nothing.
    """
    if not text:
        return ""
    out: list[str] = []
    in_list = False

    def inline(s: str) -> str:
        s = html.escape(s)
        s = LINK.sub(r'<a href="\2" rel="noopener noreferrer" target="_blank">\1</a>', s)
        s = BOLD.sub(r"<strong>\1</strong>", s)
        s = ITALIC.sub(r"<em>\1</em>", s)
        return s

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            if in_list:
                out.append("</ul>")
                in_list = False
            continue

        h = HEADING.match(line)
        s = SECTION.match(line)
        b = BULLET.match(line)

        if b:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(BULLET.sub('', line))}</li>")
            continue

        if in_list:
            out.append("</ul>")
            in_list = False

        if h:
            out.append(f"<h4>{inline(h.group(2))}</h4>")
        elif s:
            out.append(f'<h4 class="label">{inline(s.group(1).title())}</h4>')
        else:
            out.append(f"<p>{inline(line)}</p>")

    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def relative_time(stamp: str | None) -> str:
    if not stamp:
        return "undated"
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return "undated"
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    mins = (datetime.now(timezone.utc) - then).total_seconds() / 60
    if mins < 60:
        return f"{int(mins)}m ago"
    if mins < 1440:
        return f"{int(mins // 60)}h ago"
    return f"{int(mins // 1440)}d ago"


def signal_blocks(score: float, ceiling: float, segments: int = 4) -> int:
    """How many of the signal meter's segments to light up.

    Relative to `ceiling` (the topic's own top score for this edition), not
    an absolute scale, so a quiet topic's best story still shows a full
    meter and a busy topic's stories spread across the full range instead
    of all clustering near empty.
    """
    if ceiling <= 0:
        return 1
    return max(1, min(segments, round(segments * (score / ceiling)) or 1))


def build_view(topic, ranked, store, cfg) -> dict:
    """Shape one topic's ranked items into template-ready data."""
    items = ranked[:topic.max_items]
    ceiling = max([i["score"] for i in items], default=1.0)
    cards = []
    for item in items:
        row, parts = item["row"], item["parts"]
        summary = store.get_summary(row["id"], topic.pattern)
        cards.append({
            "id": row["id"],
            "title": row["title"],
            "url": row["url"],
            "source": row["source"],
            "author": row["author"],
            "when": relative_time(row["published_at"] or row["fetched_at"]),
            "published_at": row["published_at"],
            "words": row["word_count"] or 0,
            "read_min": max(1, round((row["word_count"] or 0) / 230)) if row["word_count"] else None,
            "blurb": row["blurb"] or "",
            "summary_html": md_to_html(summary) if summary else "",
            "has_summary": bool(summary),
            "score": round(item["score"], 3),
            "blocks": signal_blocks(item["score"], ceiling),
            "parts": parts,
            "matched": parts.get("matched", []),
            "also": [{"source": a["row"]["source"], "url": a["row"]["url"],
                      "title": a["row"]["title"]} for a in item.get("also", [])],
        })
    return {
        "name": topic.name,
        "slug": topic.slug,
        "pattern": topic.pattern,
        "digest_pattern": topic.digest_pattern,
        "count": len(cards),
        "cards": cards,
    }


def render(views: list[dict], digests: dict[str, str], cfg, meta: dict,
           link_as_index: bool = True) -> Path:
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)),
                      autoescape=select_autoescape(["html"]), trim_blocks=True,
                      lstrip_blocks=True)
    env.filters["md"] = md_to_html
    template = env.get_template("dashboard.html.j2")

    out_dir = cfg.resolve(cfg.output["dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    edition = meta["edition"]

    html_text = template.render(
        title=cfg.output["title"],
        theme=cfg.output.get("theme", "auto"),
        edition=edition,
        views=views,
        digests={k: md_to_html(v) for k, v in digests.items()},
        meta=meta,
    )

    dated = out_dir / "editions" / f"{edition}.html"
    dated.parent.mkdir(parents=True, exist_ok=True)
    dated.write_text(html_text, encoding="utf-8")

    if link_as_index:
        index = out_dir / "index.html"
        shutil.copyfile(dated, index)
        return index

    return dated
