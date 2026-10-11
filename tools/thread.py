"""``scale thread N``: the whole conversation of an issue or pull request, read-only.

``gh issue view`` and ``gh pr view --comments`` leave out the comments a reviewer writes on lines of a pull request,
so an agent asked to fix what a review says would miss most of it. This reads, with GET requests only (``gh api``
under the caller's token), the issue or pull request, its comments, and for a pull request its reviews and every
line comment (file, line, the code it is on, replies), and returns them in the order they were written.
"""

from __future__ import annotations

import json
import subprocess
from typing import Callable

from .util import ScaleError

Runner = Callable[[list[str]], str]


def _gh(args: list[str]) -> str:
    res = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
    if res.returncode:
        raise ScaleError(f"gh api {' '.join(args)}: {res.stderr.strip() or res.stdout.strip()}")
    return res.stdout


def _pages(run: Runner, path: str) -> list[dict]:
    """Every item of a list endpoint, page by page (GET; 100 a page)."""
    out, page = [], 1
    while True:
        items = json.loads(run([f"{path}?per_page=100&page={page}"]) or "[]")
        out += items
        if len(items) < 100:
            return out
        page += 1


def fetch(number: int, repo: str, run: Runner = _gh) -> dict:
    """The issue or pull request ``number`` of ``repo`` (owner/name) with everything said on it, oldest first."""
    base = f"repos/{repo}"
    item = json.loads(run([f"{base}/issues/{number}"]))
    who = lambda x: {"author": (x.get("user") or {}).get("login"), "association": x.get("author_association")}  # noqa: E731
    events = [{"kind": "comment", "at": c["created_at"], **who(c), "body": c.get("body") or ""}
              for c in _pages(run, f"{base}/issues/{number}/comments")]
    is_pr = "pull_request" in item
    if is_pr:
        events += [{"kind": "review", "at": r.get("submitted_at") or "", **who(r), "state": r.get("state"),
                    "body": r.get("body") or ""}
                   for r in _pages(run, f"{base}/pulls/{number}/reviews") if r.get("state") != "PENDING"]
        events += [{"kind": "line comment", "at": c["created_at"], **who(c), "path": c.get("path"),
                    "line": c.get("line") or c.get("original_line"), "code": "\n".join((c.get("diff_hunk") or "").splitlines()[-4:]),
                    "in_reply_to": c.get("in_reply_to_id"), "id": c.get("id"), "body": c.get("body") or ""}
                   for c in _pages(run, f"{base}/pulls/{number}/comments")]
    events.sort(key=lambda e: e["at"])
    return {"repo": repo, "number": number, "kind": "pull request" if is_pr else "issue", "title": item.get("title"),
            "state": item.get("state"), **who(item), "body": item.get("body") or "", "events": events}


def markdown(t: dict) -> str:
    L = [f"# {t['kind']} #{t['number']}: {t['title']} ({t['state']})", "",
         f"**{t['author']}** ({t['association']}):", "", t["body"].strip() or "(no description)", ""]
    for e in t["events"]:
        head = f"## {e['at']} · {e['kind']} by {e['author']} ({e['association']})"
        if e["kind"] == "review":
            head += f": {e['state']}"
        if e["kind"] == "line comment":
            head += f" on `{e['path']}` line {e['line']}" + (f" (reply to {e['in_reply_to']})" if e["in_reply_to"] else "")
        L += [head, ""]
        if e.get("code"):
            L += ["```diff", e["code"], "```", ""]
        L += [e["body"].strip() or "(no text)", ""]
    return "\n".join(L).rstrip() + "\n"
