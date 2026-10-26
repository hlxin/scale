"""How often what each contributor added is used: the reach the leaderboard weights a contribution by (commons.SCORING).

When a signed-in person asks a question, runs a query or searches, every catal-commons record the answer names (its
id, or the id of the source its evidence cites) is credited to the source that added it. A source's reach is the
number of distinct (person, day) pairs that used it, not counting its own contributor: asking the same thing a hundred
times in a day counts once, and nobody can raise their own score by querying their own records.

Nothing of the question or the answer is kept; only, per source, a keyed digest of the login (HMAC with the service
secret, so it cannot be turned back into a login) and the day. The file is ``SCALE_WEB_USAGE`` (JSON); without one the
counts live in memory until the service restarts.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import re
import threading
from pathlib import Path

_SLUG = re.compile(r"[a-z0-9][a-z0-9._-]*")


class Usage:
    def __init__(self, path: str | Path | None, secret: str, namespace: str):
        self.path = Path(path) if path else None
        self.secret, self.ns = secret.encode(), namespace
        self.lock = threading.Lock()
        self.seen: dict[str, set[str]] = {}
        if self.path and self.path.is_file():
            self.seen = {k: set(v) for k, v in json.loads(self.path.read_text(encoding="utf-8")).items()}

    def who(self, login: str) -> str:
        return hmac.new(self.secret, login.lower().encode(), hashlib.sha256).hexdigest()[:16]

    def sources_in(self, answer) -> set[str]:
        """The slugs of the commons sources an answer names: ``<ns>/source/<slug>`` or a record ``<ns>/<slug>/…``."""
        found: set[str] = set()
        head = self.ns + "/"

        def walk(v):
            if isinstance(v, str):
                if v.startswith(head):
                    rest = v[len(head):].split("/")
                    slug = (rest[1] if rest[0] == "source" and len(rest) > 1 else
                            rest[0] if len(rest) > 1 and rest[0] != "graph" else None)
                    if slug and _SLUG.fullmatch(slug):
                        found.add(slug)
            elif isinstance(v, dict):
                for x in v.values():
                    walk(x)
            elif isinstance(v, list):
                for x in v:
                    walk(x)
        walk(answer)
        return found

    def record(self, login: str | None, answer, day: str | None = None) -> set[str]:
        """Credit the sources an answer used to this person on this day (a signed-in person only)."""
        if not login:
            return set()
        slugs = self.sources_in(answer)
        if not slugs:
            return slugs
        key = f"{self.who(login)}|{day or _dt.date.today().isoformat()}"
        with self.lock:
            for s in slugs:
                self.seen.setdefault(s, set()).add(key)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps({k: sorted(v) for k, v in sorted(self.seen.items())}), encoding="utf-8")
                tmp.replace(self.path)
        return slugs

    def reach(self, contributor_of: dict[str, str]) -> dict[str, int]:
        """Per source, the distinct (person, day) uses by anyone but its contributor (``contributor_of``: slug to login)."""
        with self.lock:
            out = {}
            for slug, keys in self.seen.items():
                own = self.who(contributor_of[slug]) if slug in contributor_of else None
                out[slug] = sum(1 for k in keys if k.split("|", 1)[0] != own)
            return out
