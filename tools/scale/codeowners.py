"""Who must review a change: a small evaluator of GitHub's ``.github/CODEOWNERS``.

GitHub routes each changed path to the owners of the LAST pattern that matches it; several owners
on one line means any one of them may approve. A pull request therefore needs, for every changed
path, one approval from that path's owner set. ``scale ci spec-changes`` prints that summary and
``scale domains check`` reads the file to see that every domain has its line. The evaluator follows
GitHub's documented pattern rules (gitignore-like): ``/x`` is anchored at the root, a pattern
without an inner ``/`` matches at any depth, a trailing ``/`` means everything below a directory,
``*`` stays within one path segment and ``**`` crosses segments.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import layout

CODEOWNERS = ".github/CODEOWNERS"


@dataclass(frozen=True)
class Rule:
    pattern: str
    owners: tuple[str, ...]
    line: int
    regex: re.Pattern = field(compare=False, repr=False)


def _regex(pattern: str) -> re.Pattern:
    body = pattern.strip("/")
    anchored = pattern.startswith("/") or "/" in body
    out, i = "", 0
    while i < len(body):
        if body.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif body.startswith("**", i):
            out, i = out + ".*", i + 2
        elif body[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif body[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(body[i]), i + 1
    last = body.rsplit("/", 1)[-1]
    if pattern.endswith("/"):
        tail = "/.*"                              # a directory: everything below it
    elif "*" in last and last != "**":
        tail = ""                                 # `docs/*` names the files directly in docs/, not nested ones
    else:
        tail = "(?:/.*)?"                         # a file, or a directory and everything below it
    return re.compile(("^" if anchored else "^(?:.*/)?") + out + tail + "$")


def parse(text: str) -> list[Rule]:
    """The rules of a CODEOWNERS file in order (comments and blank lines dropped)."""
    rules = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = re.sub(r"(^|\s)#.*$", "", raw).strip()
        if not line:
            continue
        pattern, *owners = line.split()
        rules.append(Rule(pattern, tuple(owners), n, _regex(pattern)))
    return rules


def load(repo: Path) -> list[Rule] | None:
    """The repository's rules, or None when it has no ``.github/CODEOWNERS``."""
    p = Path(repo) / CODEOWNERS
    return parse(p.read_text(encoding="utf-8")) if p.is_file() else None


def rule_for(rules: list[Rule], path: str) -> Rule | None:
    """The last matching rule (GitHub's precedence), or None when no rule matches."""
    path = path.lstrip("/")
    return next((r for r in reversed(rules) if r.regex.match(path)), None)


def owners_for(rules: list[Rule], path: str) -> tuple[str, ...]:
    r = rule_for(rules, path)
    return r.owners if r else ()


def lines_for(rules: list[Rule], pattern: str) -> list[Rule]:
    """The rules written with exactly this pattern (``/domain/``)."""
    return [r for r in rules if r.pattern == pattern]


def minimal_reviewers(owner_sets: list[tuple[str, ...]]) -> list[str]:
    """A smallest set of owners with one member in every owner set: the fewest approvals that satisfy
    code-owner review. Exact for the handful of teams a repository has; ties go to the sorted order."""
    sets = [set(s) for s in owner_sets if s]
    owners = sorted(set().union(*sets)) if sets else []
    for k in range(1, len(owners) + 1):
        for combo in itertools.combinations(owners, k):
            if all(s & set(combo) for s in sets):
                return list(combo)
    return []


def review_requirements(rules: list[Rule], paths: list[str]) -> dict:
    """For changed paths: each path's owners, the distinct owner sets (one approval from each is
    required), paths no rule owns, and a smallest set of owners that covers them all."""
    per_path = {p: list(owners_for(rules, p)) for p in paths}
    sets = sorted({tuple(sorted(o)) for o in per_path.values() if o})
    return {"paths": per_path, "owner_sets": [list(s) for s in sets],
            "unowned": sorted(p for p, o in per_path.items() if not o),
            "minimal_reviewers": minimal_reviewers(sets)}


def domain_line(name: str | None = None) -> str:
    """The CODEOWNERS pattern of the domain's folder, ``/domain/`` (one domain, whatever its name)."""
    return f"/{layout.DOMAIN}/"
