"""A dependency-free Model Context Protocol (MCP) server over stdio.

``scale mcp`` exposes the :mod:`scale.api` tools to any host that speaks the open Model
Context Protocol, and the SCALE skills as MCP prompts. Messages are newline-delimited JSON-RPC 2.0 on stdin/stdout; logs go to stderr.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from . import __version__
from .api import TOOLS, ScaleToolkit

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "SCALE (Shared Concepts, Attributes, and Links with Evidence) curates scientific sources (catalysis, for now) "
    "into evidence-bearing scale-graph documents and answers questions with context, evidence and limitations. Call scale_status first, "
    "then scale_skills and scale_describe. Never invent missing values: declare them with a status and a reason. "
    "Never extend the schema during curation: put what it cannot express in a record's unmodeled list. Report "
    "typed absences (schema_gap, no_matching_record, missing_context) as answers. Approving and merging pull requests, "
    "releases and issue filing are human actions."
)


class MCPServer:
    def __init__(self, toolkit: ScaleToolkit | None = None):
        self.toolkit = toolkit or ScaleToolkit()

    # ------------------------------------------------------------ dispatch
    def handle(self, msg: dict) -> dict | None:
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:          # notification (e.g. notifications/initialized): no response
            return None
        try:
            result = self._dispatch(method, msg.get("params") or {})
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except _RPCError as exc:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": exc.code, "message": exc.message}}
        except Exception as exc:  # never crash the host connection
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"internal error: {exc}"}}

    def _dispatch(self, method: str, params: dict) -> Any:
        if method == "initialize":
            requested = params.get("protocolVersion")
            return {
                "protocolVersion": requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}, "prompts": {"listChanged": False}},
                "serverInfo": {"name": "scale", "title": "SCALE", "version": __version__},
                "instructions": INSTRUCTIONS,
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["input_schema"]}
                              for t in TOOLS]}
        if method == "tools/call":
            name = params.get("name")
            if name not in {t["name"] for t in TOOLS}:
                raise _RPCError(-32602, f"unknown tool {name!r}")
            result = self.toolkit.call(name, params.get("arguments") or {})
            is_error = isinstance(result, dict) and "error" in result
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=1, default=str)}],
                    "structuredContent": result, "isError": is_error}
        if method == "prompts/list":
            return {"prompts": [{"name": n, "title": f"SCALE skill: {n}",
                                 "description": s["description"] or f"Load the versioned SCALE procedure '{n}'."}
                                for n, s in self.toolkit._skills().items()]}
        if method == "prompts/get":
            name = params.get("name")
            skills = self.toolkit._skills()
            if name not in skills:
                raise _RPCError(-32602, f"unknown prompt {name!r}")
            return {"description": f"SCALE skill {name} {skills[name]['version']}",
                    "messages": [{"role": "user", "content": {"type": "text", "text": skills[name]["text"]}}]}
        raise _RPCError(-32601, f"method not found: {method}")

    # ------------------------------------------------------------ transport
    def serve(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        print(f"scale MCP server {__version__} — working directory {self.toolkit.workspace}", file=sys.stderr)
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self._send(stdout, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
                continue
            batch = msg if isinstance(msg, list) else [msg]
            for m in batch:
                resp = self.handle(m)
                if resp is not None:
                    self._send(stdout, resp)

    @staticmethod
    def _send(stdout: TextIO, obj: dict) -> None:
        stdout.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
        stdout.flush()


class _RPCError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def main(workspace: str | None = None) -> None:
    MCPServer(ScaleToolkit(workspace=workspace)).serve()
