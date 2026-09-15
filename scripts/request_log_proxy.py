"""Local logging proxy (s02): what the CLI actually sends on each /v1/messages call.

    python scripts/request_log_proxy.py req.log
    ANTHROPIC_BASE_URL=http://127.0.0.1:8787 make smoke

One JSON line per request: the size of `system`, `tools` and `messages`, the
tool names, the `context_management` block. No headers or credentials are
logged, and the body is forwarded to the API unchanged. This is how the
27k-token connector prefix was found; keep it for the next "why is this
call so big".
"""

from __future__ import annotations

import http.server
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

UPSTREAM = "https://api.anthropic.com"
PORT = 8787
SKIP_REQ = {"host", "content-length", "accept-encoding"}
SKIP_RES = {"transfer-encoding", "content-encoding", "content-length", "connection"}


def record(path: str, body: bytes) -> dict[str, Any]:
    b = json.loads(body)
    system = b.get("system")
    system_text = system if isinstance(system, str) else json.dumps(system)
    tools = b.get("tools", [])
    return {
        "t": time.time(),
        "path": path,
        "model": b.get("model"),
        "system_chars": len(system_text or ""),
        "system": system,
        "tools": [{"name": t.get("name"), "chars": len(json.dumps(t))} for t in tools],
        "tools_chars": len(json.dumps(tools)),
        "messages_chars": len(json.dumps(b.get("messages", []))),
        "n_messages": len(b.get("messages", [])),
        "context_management": b.get("context_management"),
        "max_tokens": b.get("max_tokens"),
        "thinking": b.get("thinking"),
    }


class Handler(http.server.BaseHTTPRequestHandler):
    log_path = "req.log"

    def _log(self, rec: dict[str, Any]) -> None:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def _relay(self, req: urllib.request.Request) -> None:
        try:
            with urllib.request.urlopen(req) as r:  # noqa: S310 - fixed https upstream
                self.send_response(r.status)
                for k, v in r.getheaders():
                    if k.lower() not in SKIP_RES:
                        self.send_header(k, v)
                self.send_header("Connection", "close")
                self.end_headers()
                while chunk := r.read(1024):
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            self.wfile.write(e.read())

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        try:
            self._log(record(self.path, body))
        except Exception as e:  # noqa: BLE001 - a bad body is logged, not fatal
            self._log({"err": str(e), "path": self.path})
        headers = {k: v for k, v in self.headers.items() if k.lower() not in SKIP_REQ}
        self._relay(urllib.request.Request(UPSTREAM + self.path, body, headers, method="POST"))

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        headers = {k: v for k, v in self.headers.items() if k.lower() != "host"}
        self._relay(urllib.request.Request(UPSTREAM + self.path, headers=headers))

    def log_message(self, *args: Any) -> None:  # quiet
        return


if __name__ == "__main__":
    Handler.log_path = sys.argv[1] if len(sys.argv) > 1 else "req.log"
    print(f"logging to {Handler.log_path}; ANTHROPIC_BASE_URL=http://127.0.0.1:{PORT}")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
