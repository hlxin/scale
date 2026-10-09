"""`scale check`: every check of CI's `test` jobs, in one command, for contributors before a pull request."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

from . import layout
from .util import ScaleError, load_yaml

# a small set of invalid scale-graph documents, each rejected for a reason its index states
INVALID_FIXTURES = f"{layout.DOMAIN}/tests/fixtures/invalid"
INVALID_INDEX = "expect.yaml"


def invalid_fixtures(repo: Path) -> list[dict]:
    """The invalid fixtures and why each must be rejected (``expect.yaml``: file, error, reason). An
    index naming a missing file, or a document the index does not name, is an error: a fixture
    without a stated reason would test nothing."""
    d = Path(repo) / INVALID_FIXTURES
    if not (d / INVALID_INDEX).is_file():
        raise ScaleError(f"scale check: {INVALID_FIXTURES}/{INVALID_INDEX} does not exist under {repo}")
    entries = (load_yaml(d / INVALID_INDEX) or {}).get("fixtures") or []
    if not entries:
        raise ScaleError(f"scale check: {INVALID_FIXTURES}/{INVALID_INDEX} lists no fixtures")
    named = {e["file"] for e in entries}
    missing = sorted(f for f in named if not (d / f).is_file())
    unlisted = sorted(p.name for p in d.glob("*.json") if p.name not in named)
    if missing or unlisted:
        raise ScaleError(f"scale check: {INVALID_FIXTURES}: index names missing files {missing} or leaves out {unlisted}")
    for e in entries:
        if not e.get("error") or not e.get("reason"):
            raise ScaleError(f"scale check: {INVALID_FIXTURES}/{INVALID_INDEX}: {e['file']} needs an error and a reason")
    return [{**e, "path": str(d / e["file"])} for e in entries]


def reviewer_warnings(repo: Path) -> list[str]:
    """Reviewer seats still held by placeholders in the review policy: seats to fill with people, and until one is,
    no pull request of the owner's can get an approval from a reviewer other than its author (a warning, not a failure)."""
    from .policy import load_policy, placeholders
    n = len(placeholders(load_policy(repo)))
    return [f"reviewers: {n} placeholder{'s' if n != 1 else ''} to fill ({layout.REVIEW_POLICY})"] if n else []


# Prose that names the schema's one version. Each entry is a file and a pattern for the sentence; ``head`` is the
# catalysis manifest's version (the kernel's and the catalysis file's too: they carry none of their own). A warning,
# never a failure: the apply-proposals workflow raises the version and runs `scale check`, and a sentence left behind
# must not undo an approved apply. Change a sentence and its pattern together.
VERSION_TEXTS = (
    ("README.md", r"The schema is at \*\*(?P<head>\d+\.\d+\.\d+)\*\*"),
    ("docs/architecture.md", r"The schema is at (?P<head>\d+\.\d+\.\d+), kernel and catalysis together"),
    ("docs/implementation-status.yaml", r"one version for the kernel and the catalysis domain, at (?P<head>\d+\.\d+\.\d+)"),
    ("domain/README.md", r"\| schema version \| (?P<head>\d+\.\d+\.\d+) \(kernel and catalysis together\) \|"),
    ("core/README.md", r"the schema is at (?P<head>\d+\.\d+\.\d+) \(kernel and catalysis together\)"),
)


def stale_version_texts(texts: dict[str, str | None], versions: dict[str, str]) -> list[str]:
    """The sentences of :data:`VERSION_TEXTS` (``texts``: file -> its text, None when missing) that name another
    version than ``versions`` (head), or that are no longer found. Line breaks count as spaces."""
    out = []
    for rel, pattern in VERSION_TEXTS:
        text = texts.get(rel)
        m = re.search(pattern, re.sub(r"\s+", " ", text)) if text is not None else None
        if m is None:
            out.append(f"versions in prose: {rel} no longer has the sentence that names them (update devcheck.VERSION_TEXTS)")
            continue
        for k, v in m.groupdict().items():
            if v != versions.get(k):
                out.append(f"versions in prose: {rel} says {k} version {v}; it is {versions.get(k)}")
    return out


def version_text_warnings(repo: Path) -> list[str]:
    """The schema's one version as the catalysis manifest says, against the prose that names it."""
    mans = layout.graph_manifests(repo)
    if "catalysis" not in mans:
        return []
    versions = {"head": str(load_yaml(mans["catalysis"]).get("version"))}
    texts = {rel: (Path(repo) / rel).read_text(encoding="utf-8") if (Path(repo) / rel).is_file() else None
             for rel, _ in VERSION_TEXTS}
    return stale_version_texts(texts, versions)


def check_steps(repo: Path, fast: bool = False) -> list[dict]:
    """The checks, in CI order. An ``expect_errors`` step passes when every command exits 1 (invalid, not
    a tool error) and reports the stated error; a ``warning`` step prints what it finds and never fails."""
    scale = [sys.executable, "-m", "scale.cli", "--repo", str(repo)]
    fixtures = invalid_fixtures(repo)
    steps = [
        {"name": "reviewers: every seat in the review policy is filled", "cmds": [], "warning": reviewer_warnings},
        {"name": "the documentation names the current schema version", "cmds": [], "warning": version_text_warnings},
        {"name": "unit tests", "cmds": [[sys.executable, "-m", "pytest", "-q"]], "slow": True},
        {"name": "releases are unchanged (digests)", "cmds": [scale + ["release", "verify"]]},
        {"name": "scale-graph schemas load (head and frozen)", "cmds": [scale + ["graph", "verify"]]},
        {"name": "domain and core manifests are complete, compatible and do not redefine identifiers",
         "cmds": [scale + ["domains", "check"]]},
        {"name": "competency questions answer as expected", "cmds": [scale + ["domains", "cq"]]},
        {"name": "style (YAML block style, naming, canonical JSON)", "cmds": [scale + ["lint"], scale + ["fmt", "--check"]]},
        {"name": "documentation links resolve", "cmds": [scale + ["links"]]},
        {"name": "every committed document is public (stewardship access)", "cmds": [scale + ["evidence", "access"]]},
        {"name": "quoted text respects the copyright cap", "cmds": [scale + ["evidence", "report", "--all"]]},
        # REUSE.toml gives every file a licence and LICENSES/ holds each licence it names (the dev extra installs
        # reuse; it reads the git checkout, so files git ignores are not checked)
        {"name": "licence annotations are complete (reuse lint)", "cmds": [[sys.executable, "-m", "reuse", "--root", str(repo), "lint"]]},
        {"name": "invalid scale-graph fixtures are rejected for their stated reasons",
         "cmds": [scale + ["graph", "validate", "--format", "json", f["path"]] for f in fixtures],
         "expect_errors": [f["error"] for f in fixtures]},
    ]
    return [s for s in steps if not (fast and s.get("slow"))]


def _rejected_for(res: subprocess.CompletedProcess, error: str) -> bool:
    """Exit 1 (invalid, not a tool error) with an error message containing ``error``."""
    if res.returncode != 1:
        return False
    try:
        rep = json.loads(res.stdout)
    except ValueError:
        return False
    return any(error in e.get("message", "") for e in rep.get("errors") or [])


def run_checks(repo: Path, fast: bool = False, out=None) -> bool:
    """Run every step (a failure does not stop the rest); print one line per step and the output of failures."""
    out = out or sys.stdout
    ok = True
    for step in check_steps(repo, fast):
        if "warning" in step:                       # reported, never failing
            msgs = step["warning"](repo)
            for m in msgs:
                print(f"warn {m}", file=out, flush=True)
            if not msgs:
                print(f"ok   {step['name']}", file=out, flush=True)
            continue
        t0, failures = time.monotonic(), []
        for i, cmd in enumerate(step["cmds"]):
            res = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
            if "expect_errors" in step:
                if not _rejected_for(res, step["expect_errors"][i]):
                    failures.append((cmd, res, f"expected exit 1 with an error containing {step['expect_errors'][i]!r}"))
            elif res.returncode != 0:
                failures.append((cmd, res, None))
        mark = "FAIL" if failures else "ok  "
        print(f"{mark} {step['name']} ({time.monotonic() - t0:.1f}s)", file=out, flush=True)
        for cmd, res, why in failures:
            ok = False
            shown = " ".join(cmd[2:] if cmd[1] == "-m" else cmd)
            print(f"     $ {shown}\n     exit {res.returncode}" + (f" ({why})" if why else ""), file=out)
            tail = (res.stdout + res.stderr).strip().splitlines()[-20:]
            print("\n".join("     " + line for line in tail), file=out)
    print("all checks passed" if ok else "some checks failed", file=out)
    return ok
