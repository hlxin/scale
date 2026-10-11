"""``scale ci spec-changes``: what a pull request may change, what a schema change must carry, and who reviews it.

CI runs this on every pull request (job ``specification-changes``). It compares the branch with the
merge base of ``<ref>`` (what GitHub shows as the pull request's diff) and fails when the branch

- modifies, deletes or adds files inside a release (``releases/<id>/``, a directory holding RELEASE.yaml at
  the merge base) or modifies or deletes a frozen schema file: the frozen kernels in ``core/graph/frozen/`` or
  the catalysis domain's frozen versions in ``domain/graph/frozen/`` (each SHA256SUMS may only gain lines). New
  releases and new frozen versions are additions and pass; README and CHANGELOG files directly under
  ``releases/`` may change;
- changes the specification (``core/graph/``, or the catalysis domain's ``domain/graph/`` files, its schema
  manifest ``graph/scale-catal.yaml`` included, unless the domain is experimental) without what a schema change
  must carry (:func:`scale.schema_change.check`: the version raised by the rule, the base frozen, the migration
  step, tests, a CHANGELOG line).

It also prints whose review the change needs according to ``.github/CODEOWNERS`` at the merge base
(GitHub reads the base branch's file), and the maintainers of the catalysis domain to consult when ``core/``
changes. The rules are path tests anchored at the repository root.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

from . import codeowners, layout
from .schema_change import check as schema_check
from .util import ScaleError, load_doc

ALLOWED_RELEASE_NOTES = re.compile(r"^releases/(README|CHANGELOG)(\.md)?$")
SPEC = [re.compile(r"^core/graph/")]
# additions only; SHA256SUMS append-only
FROZEN = re.compile(r"^(core/graph/frozen/|domain/graph/frozen/)")


def load_yaml_text(text: str):
    return yaml.safe_load(text)


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if res.returncode != 0:
        raise ScaleError(f"git {' '.join(args)}: {res.stderr.strip() or res.stdout.strip()}")
    return res.stdout


def changed_files(repo: Path, base: str, head: str = "HEAD") -> tuple[str, list[tuple[str, str]]]:
    """(merge base, [(status, path)]) for the branch ``head`` against ``base``; renames count as a
    deletion plus an addition, so moving a file out of a release is a deletion."""
    mb = _git(repo, "merge-base", base, head).strip()
    fields = _git(repo, "diff", "--name-status", "--no-renames", "-z", mb, head).split("\0")
    return mb, [(fields[i][0], fields[i + 1]) for i in range(0, len(fields) - 1, 2)]


def _blob(repo: Path, ref: str, path: str) -> str | None:
    res = subprocess.run(["git", "rev-parse", "--verify", "-q", f"{ref}:{path}"], cwd=repo, capture_output=True, text=True)
    return res.stdout.strip() if res.returncode == 0 else None


def _show(repo: Path, ref: str, path: str) -> str | None:
    res = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=repo, capture_output=True, text=True)
    return res.stdout if res.returncode == 0 else None


def _ls(repo: Path, ref: str, path: str) -> list[str]:
    return [f for f in _git(repo, "ls-tree", "-r", "-z", "--name-only", ref, "--", path).split("\0") if f]


def _release_dirs(repo: Path, ref: str) -> list[str]:
    """Archived release directories at ``ref``: those holding a RELEASE.yaml."""
    files = _ls(repo, ref, layout.RELEASES)
    return sorted({f.rsplit("/", 1)[0] for f in files if f.endswith("/RELEASE.yaml")})


def _domain_status(repo: Path, ref: str, decl: str) -> str | None:
    """The status a domain's DOMAIN.yaml (``decl``, repository-relative) states at ``ref``."""
    text = _show(repo, ref, decl)
    try:
        return (load_yaml_text(text) or {}).get("status") if text is not None else None
    except yaml.YAMLError:       # an unreadable DOMAIN.yaml is reported by `scale domains check`
        return None


def spec_changes(repo: Path, base: str, head: str = "HEAD") -> dict:
    repo = Path(repo).resolve()
    mb, rows = changed_files(repo, base, head)
    releases = _release_dirs(repo, mb)
    violations: list[str] = []
    for status, path in rows:
        if FROZEN.match(path):
            if path.endswith(f"/{layout.FROZEN_SUMS}") and status == "M":
                old, new = _show(repo, mb, path) or "", _show(repo, head, path) or ""
                if not new.startswith(old):
                    violations.append(f"{path}: existing lines changed; SHA256SUMS may only gain lines")
            elif status != "A":
                violations.append(f"{path}: {'deletes' if status == 'D' else 'modifies'} a frozen schema file; frozen "
                                  "versions are additions only")
            continue
        if not path.startswith(f"{layout.RELEASES}/") or ALLOWED_RELEASE_NOTES.match(path):
            continue
        inside = next((d for d in releases if path.startswith(d + "/")), None)
        if inside:
            verb = {"M": "modifies a file of", "D": "deletes a file of", "A": "adds a file to"}.get(status, "changes a file of")
            violations.append(f"{path}: {verb} the release {inside}; releases are immutable (build a new one)")
        elif status != "A":
            violations.append(f"{path}: {'deletes' if status == 'D' else 'modifies'} a file under releases/; only "
                              "README and CHANGELOG files directly under releases/ may change")

    statuses: dict[str, str | None] = {}

    def spec_file(path: str) -> bool:
        if any(rx.match(path) for rx in SPEC):
            return True
        if not re.match(rf"^{layout.DOMAIN}/graph/", path):
            return False
        decl = layout.DOMAIN_DECLARATION
        if decl not in statuses:         # experimental only if experimental at both ends: a promotion PR (stable at
            # head) and a demotion PR (stable at the base) count as stable; an unknown status counts as stable
            known = {s for s in (_domain_status(repo, head, decl), _domain_status(repo, mb, decl)) if s is not None}
            statuses[decl] = "experimental" if known == {"experimental"} else "stable"
        return statuses[decl] != "experimental"

    spec = sorted(p for s, p in rows if spec_file(p) and not FROZEN.match(p))
    schema = None
    if spec:
        schema = schema_check(repo, base)
        violations += [f"schema change: {x}" for x in schema["problems"]]

    text = _show(repo, mb, layout.CODEOWNERS)
    source = f"{layout.CODEOWNERS} at the merge base"
    if text is None and (repo / layout.CODEOWNERS).is_file():
        text, source = (repo / layout.CODEOWNERS).read_text(encoding="utf-8"), f"{layout.CODEOWNERS} (working tree)"
    paths = [p for _, p in rows]
    owners = ({"source": source, **codeowners.review_requirements(codeowners.parse(text), paths)} if text is not None
              else {"source": None, "note": f"no {layout.CODEOWNERS}: review routing unknown"})
    core_touched = sorted(p for p in paths if p.startswith(f"{layout.CORE}/"))
    consult = None
    if core_touched:
        teams = []
        m = load_yaml_text(_show(repo, head, layout.DOMAIN_DECLARATION) or "") or {}
        team = (m.get("maintainers") or {}).get("team")
        if team:
            teams.append(team)
        consult = {"paths": core_touched, "domain_teams": teams,
                   "note": "core/ changed: the catalysis domain builds on the science kernel; say in the pull request how "
                           "the catalysis domain is affected (the reviewers review both)"}
    return {"base": base, "merge_base": mb, "head": head, "changed": [{"status": s, "path": p} for s, p in rows],
            "specification_files": spec, "schema": schema, "violations": violations,
            "owners": owners, "core_consultation": consult, "ok": not violations}


def spec_changes_text(res: dict) -> str:
    L = [f"{len(res['changed'])} changed files against {res['base']} (merge base {res['merge_base'][:12]})"]
    if res["schema"]:
        sc = res["schema"]
        L.append(f"schema change: {sc['kind'] or 'none'}, {sc['base_version']} -> {sc['head_version']} (needs {sc['needs_version']})")
    L += [f"FAIL {v}" for v in res["violations"]] or ["ok: no release or frozen version is modified; a schema change carries what it must"]
    L.append("approval: one approving review by a person, any listed reviewer (governance/review-policy.yaml)")
    o = res["owners"]
    if o.get("source"):
        L.append(f"review requested from (from {o['source']}; any one reviewer's approval is enough, a code owner's is not required):")
        L += [f"  - any of {' '.join(s)}" for s in o["owner_sets"]] or ["  - none"]
        if len(o["owner_sets"]) > 1:                    # with one set, "any of" already says it
            L.append(f"  fewest reviewers who own every changed path: {' + '.join(o['minimal_reviewers'])}")
        if o["unowned"]:
            L.append(f"  no owner: {', '.join(o['unowned'][:10])}")
    else:
        L.append(o["note"])
    if res["core_consultation"]:
        c = res["core_consultation"]
        L.append(f"{c['note']}; teams to consult: {', '.join(c['domain_teams']) or 'none declared'}")
    return "\n".join(L)

