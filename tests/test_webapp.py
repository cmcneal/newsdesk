"""End-to-end test of the settings UI: real handler, real socket, real
requests. Same style as tests/test_pipeline.py -- no mocking framework,
just start it and hit it.
"""
from __future__ import annotations

import http.client
import json
import socketserver
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from newsdesk import config as config_mod  # noqa: E402
from newsdesk import state, webapp  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{'  ' + detail if detail else ''}")
    if not cond:
        FAILED.append(name)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="newsdesk-webapp-test-"))
    (tmp / "out").mkdir()
    (tmp / "out" / "index.html").write_text("<h1>board</h1>")
    # Forward slashes only: on Windows, tmp's backslashes would land inside a
    # double-quoted YAML string below and get parsed as escape sequences
    # (e.g. \U expects 8 hex digits), breaking the config load. See the same
    # fix already applied in tests/test_pipeline.py.
    tmp_posix = tmp.as_posix()

    cfg_text = f"""
output: {{dir: "{tmp_posix}/out", db: "{tmp_posix}/test.sqlite3", title: Newsdesk}}
topics:
  - name: Security
    slug: security
    sources:
      - {{url: "https://a.test/feed", name: A, weight: 1.0}}
"""
    cfg_path = tmp / "config.yaml"
    cfg_path.write_text(cfg_text)
    cfg = config_mod.load(cfg_path)

    job = webapp.RebuildJob([sys.executable, "-c", "print('build ok')"])
    handler = webapp.make_handler(cfg.path, cfg.resolve(cfg.output["dir"]), job)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def request(method: str, path: str, body: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        payload = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if payload else {}
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    # --- static board still works -------------------------------------------
    status, data = request("GET", "/index.html")
    check("static board still served", status == 200 and b"board" in data)

    # --- settings page ---------------------------------------------------------
    status, data = request("GET", "/settings")
    check("settings page renders", status == 200)
    check("settings page lists the source", b"A" in data and b"Security" in data)
    check("settings page includes the shared CSS", b"--paper" in data)

    # --- api/state ------------------------------------------------------------
    status, data = request("GET", "/api/state")
    body = json.loads(data)
    check("initial state has nothing disabled",
          body == {"disabled_topics": [], "disabled_sources": []}, str(body))

    # --- api/toggle -------------------------------------------------------------
    key = state.source_key("security", "https://a.test/feed")
    status, data = request("POST", "/api/toggle", {"type": "source", "id": key, "enabled": False})
    check("toggle source off succeeds", status == 200)
    status, data = request("GET", "/api/state")
    check("disabled source now shows in state", json.loads(data)["disabled_sources"] == [key])

    status, data = request("POST", "/api/toggle", {"type": "bogus", "id": "x", "enabled": False})
    check("toggle rejects an unknown type", status == 400)

    status, data = request("POST", "/api/toggle", 5)
    check("toggle rejects a non-dict JSON body (int)", status == 400, f"status={status}")

    status, data = request("POST", "/api/toggle", [1, 2, 3])
    check("toggle rejects a non-dict JSON body (list)", status == 400, f"status={status}")

    # --- api/rebuild ------------------------------------------------------------
    status, data = request("POST", "/api/rebuild")
    check("rebuild starts", status == 200 and json.loads(data)["status"] == "started")

    deadline = time.time() + 5
    final_status = None
    while time.time() < deadline:
        _, data = request("GET", "/api/rebuild/status")
        final_status = json.loads(data)
        if final_status["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    check("rebuild finishes", final_status is not None and final_status["status"] == "done",
          str(final_status))
    check("rebuild log captured", "build ok" in (final_status or {}).get("log_tail", ""))

    httpd.shutdown()
    print(f"\n{'-' * 60}")
    if FAILED:
        print(f"{len(FAILED)} FAILED: {', '.join(FAILED)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
