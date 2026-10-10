"""Is a newer scale-catal tool published?

``tool_status`` compares the running tool with the newest release tag of the canonical repository
(``git ls-remote``, cached for a day in the working directory; off with ``SCALE_NO_UPDATE_CHECK=1``).
It never changes anything: a person updates the tool (``uvx --refresh scale-catal …``). Documents
pin their schema version themselves, so a newer tool never changes what an existing document means;
``scale graph migrate`` moves a document to a newer schema version when a person asks for it.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
from pathlib import Path

from . import __version__

REMOTE_URL = "https://github.com/hlxin/scale.git"
CHECK_TTL = _dt.timedelta(days=1)


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)


def _vkey(v: str) -> tuple:
    """Order of tool versions and tags."""
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def remote_latest(cache_dir: Path | None = None, url: str | None = None, timeout: float = 3.0) -> dict:
    """The newest published tool tag, from ``git ls-remote`` (cached for a day). Never raises."""
    if os.environ.get("SCALE_NO_UPDATE_CHECK"):
        return {"checked": False, "reason": "disabled by SCALE_NO_UPDATE_CHECK"}
    url = url or os.environ.get("SCALE_REPO_URL", REMOTE_URL)
    cache = (cache_dir / ".update-check.json") if cache_dir else None
    if cache and cache.exists():
        try:
            c = json.loads(cache.read_text(encoding="utf-8"))
            if _now() - _dt.datetime.fromisoformat(c["at"]) < CHECK_TTL and c.get("url") == url:
                return {**c, "cached": True}
        except (ValueError, KeyError):
            pass
    try:
        out = subprocess.run(["git", "ls-remote", "--tags", "--refs", url], capture_output=True, text=True,
                             timeout=timeout, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"checked": False, "reason": f"remote not reachable ({type(exc).__name__})"}
    if out.returncode != 0:
        return {"checked": False, "reason": "remote not reachable or not authorized"}
    tags = sorted({m for m in re.findall(r"refs/tags/(v\d+\.\d+\.\d+)$", out.stdout, re.M)}, key=_vkey)
    res = {"checked": True, "url": url, "at": _now().isoformat(), "latest_tag": tags[-1] if tags else None}
    if cache:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(res), encoding="utf-8")
        except OSError:
            pass
    return res


def tool_status(cache_dir: Path | None = None) -> dict:
    """The running tool's version and, when the remote is reachable, whether a newer one is published."""
    remote = remote_latest(cache_dir)
    out = {"tool_version": __version__, "remote": remote}
    tag = remote.get("latest_tag")
    if tag and _vkey(tag) > _vkey(__version__):
        out["notice"] = (f"scale-catal {tag} is published (running {__version__}). Tell the user; a person updates "
                         f"the tool with `uvx scale-catal@{tag.lstrip('v')} …` or `uvx --refresh scale-catal …`.")
    return out
