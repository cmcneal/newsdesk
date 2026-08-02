"""Local settings UI + a tiny JSON API for `newsdesk serve`.

Everything here is stdlib-only (http.server, socketserver, subprocess) to
match the project's no-framework posture. This is a single-user,
localhost-by-default tool -- see
docs/superpowers/specs/2026-08-01-sources-settings-ui-design.md for the
trust model.
"""
from __future__ import annotations

import http.server
import json
import subprocess
import threading
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config as config_mod
from . import state as state_mod

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
LOG_TAIL_CHARS = 4096


class RebuildJob:
    """Tracks at most one background `newsdesk build` subprocess at a time."""

    def __init__(self, command: list[str]):
        self.command = command
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._output = ""

    def start(self) -> str:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return "already-running"
            self._output = ""
            self._proc = subprocess.Popen(
                self.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1)
        threading.Thread(target=self._drain, args=(self._proc,), daemon=True).start()
        return "started"

    def _drain(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            with self._lock:
                self._output = (self._output + line)[-LOG_TAIL_CHARS:]
        proc.wait()

    def status(self) -> dict:
        with self._lock:
            if self._proc is None:
                return {"status": "idle", "log_tail": ""}
            code = self._proc.poll()
            st = "running" if code is None else ("done" if code == 0 else "error")
            return {"status": st, "log_tail": self._output}


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)),
                       autoescape=select_autoescape(["html"]), trim_blocks=True,
                       lstrip_blocks=True)


def render_settings_page(cfg_path: Path) -> str:
    """Reloads config.yaml/my.yaml fresh on every call. This is a low-traffic
    local tool and the whole point of /settings is to reflect hand-edits to
    the config made while `serve` is running -- caching a Config at server
    startup would mean a restart is needed to see topic/source changes,
    which defeats half the purpose."""
    cfg = config_mod.load(cfg_path)
    disabled = state_mod.load(state_mod.state_path(cfg_path))
    topics = []
    for topic in cfg.all_topics():
        topics.append({
            "slug": topic.slug,
            "name": topic.name,
            "enabled": topic.slug not in disabled["disabled_topics"],
            "sources": [{
                "name": s.name,
                "weight": s.weight,
                "key": state_mod.source_key(topic.slug, s.url),
                "enabled": state_mod.source_key(topic.slug, s.url) not in disabled["disabled_sources"],
            } for s in topic.sources],
        })
    template = _env().get_template("settings.html.j2")
    return template.render(title=cfg.output["title"], theme=cfg.output.get("theme", "auto"),
                           topics=topics)


def _state_payload(cfg_path: Path) -> dict:
    st = state_mod.load(state_mod.state_path(cfg_path))
    return {"disabled_topics": sorted(st["disabled_topics"]),
            "disabled_sources": sorted(st["disabled_sources"])}


def make_handler(cfg_path: Path, static_dir: Path, rebuild_job: RebuildJob):
    """Builds a request handler class serving `static_dir` for everything
    except the settings routes. One handler instance is created per request
    (stdlib http.server behavior); cfg_path/static_dir/rebuild_job are closed
    over. cfg_path (not a loaded Config) so every settings request re-reads
    config.yaml/my.yaml from disk -- see render_settings_page."""

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(static_dir), **kwargs)

        def log_message(self, fmt, *args):  # noqa: A002 - stdlib signature
            pass  # keep `serve` output to the one startup line

        def do_GET(self):
            if self.path == "/settings":
                self._settings_page()
            elif self.path == "/api/state":
                self._json(200, _state_payload(cfg_path))
            elif self.path == "/api/rebuild/status":
                self._json(200, rebuild_job.status())
            else:
                super().do_GET()

        def do_POST(self):
            if self.path == "/api/toggle":
                self._toggle()
            elif self.path == "/api/rebuild":
                self._json(200, {"status": rebuild_job.start()})
            else:
                self.send_error(404)

        def _settings_page(self) -> None:
            body = render_settings_page(cfg_path).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _toggle(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                kind, key, enabled = payload["type"], payload["id"], bool(payload["enabled"])
                if kind not in ("topic", "source"):
                    raise ValueError("type must be 'topic' or 'source'")
            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
                self._json(400, {"error": str(exc)})
                return
            new_state = state_mod.set_enabled(state_mod.state_path(cfg_path), kind, key, enabled)
            self._json(200, {"disabled_topics": sorted(new_state["disabled_topics"]),
                             "disabled_sources": sorted(new_state["disabled_sources"])})

        def _json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler
