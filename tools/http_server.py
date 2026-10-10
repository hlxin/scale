"""A dependency-free local HTTP interface to the SCALE tools.

``scale serve`` listens on 127.0.0.1 by default:

* ``GET  /tools``          — tool definitions (JSON Schema)
* ``POST /tools/{name}``   — call a tool; JSON body = arguments; JSON response
* ``GET  /openapi.json``   — OpenAPI 3.1 description, for frameworks that import tools from OpenAPI
* ``GET  /health``         — liveness

Any system that can make an HTTP request can use SCALE this way. A tool that fails in a way it does not report as
an error of its own (a stored document it cannot read, such as one whose record ``props`` is not an object), or whose
result is not JSON (a stored document holding ``NaN``, a key that is not text), answers 503 with a generic error, and
a request whose ``Content-Length`` is not a length (ASCII digits only) answers 400: never a dropped connection, and
never the document's content or a traceback.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from .api import ScaleToolkit

MAX_BODY = 32 * 1024 * 1024
UNAVAILABLE = "the tool could not complete: a stored document or index it read is not in a form it can read"


def make_handler(toolkit: ScaleToolkit, base_url: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"scale/{__version__}"

        def _send(self, code: int, obj) -> None:
            try:            # strict JSON, made before anything is sent: a result that is not JSON is an error response
                body = json.dumps(obj, ensure_ascii=False, default=str, allow_nan=False).encode("utf-8")
            except (TypeError, ValueError, RecursionError) as exc:
                print(f"scale serve: {self.path}: the result is not JSON: {type(exc).__name__}", file=sys.stderr)
                code, body = 503, json.dumps({"error": UNAVAILABLE}).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path == "/tools":
                self._send(200, toolkit.schemas())
            elif self.path == "/openapi.json":
                self._send(200, toolkit.openapi(base_url))
            elif self.path == "/health":
                self._send(200, {"ok": True, "version": __version__, "workspace": str(toolkit.workspace)})
            else:
                self._send(404, {"error": f"not found: {self.path}"})

        def do_POST(self):  # noqa: N802
            if not self.path.startswith("/tools/"):
                self._send(404, {"error": f"not found: {self.path}"})
                return
            # a length is ASCII digits only (RFC 9110: 1*DIGIT): int() also reads "1_0", "+10" and other scripts'
            # digits, and the handler would wait for a body that never comes
            given = (self.headers.get("Content-Length") or "0").strip()
            digits = given.lstrip("0") or "0"   # int() refuses more than ~4300 digits; a length that long is too large anyway
            if not (given.isascii() and given.isdigit()):
                length = -1
            elif len(digits) > len(str(MAX_BODY)):
                length = MAX_BODY + 1
            else:
                length = int(digits)
            if length < 0:
                self._send(400, {"error": "Content-Length is not a length"})
                return
            if length > MAX_BODY:
                self._send(413, {"error": "request body too large"})
                return
            raw = self.rfile.read(length) if length else b"{}"
            try:
                args = json.loads(raw or b"{}")
                if not isinstance(args, dict):
                    raise ValueError("arguments must be a JSON object")
            except ValueError as exc:
                self._send(400, {"error": f"invalid JSON arguments: {exc}"})
                return
            try:
                result = toolkit.call(self.path[len("/tools/"):], args)
            except Exception as exc:  # never drop the connection; nothing of the document is sent
                print(f"scale serve: {self.path} failed: {type(exc).__name__}", file=sys.stderr)
                self._send(503, {"error": UNAVAILABLE})
                return
            self._send(200, result)

        def log_message(self, fmt, *args):  # keep stdout clean; log to stderr
            print(f"scale serve: {fmt % args}", file=sys.stderr)

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765, workspace: str | None = None) -> None:
    toolkit = ScaleToolkit(workspace=workspace)
    base = f"http://{host}:{port}"
    httpd = ThreadingHTTPServer((host, port), make_handler(toolkit, base))
    print(f"SCALE tools at {base}/tools (OpenAPI: {base}/openapi.json) — working directory {toolkit.workspace}", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
