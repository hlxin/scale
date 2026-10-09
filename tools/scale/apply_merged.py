"""Apply a schema proposal after its pull request merged: the automatic version bump.

    scale proposal apply-merged 000001 --pr 42 --reviews reviews.json --author alice --head-sha <sha>

The apply-proposals workflow (.github/workflows/apply-proposals.yml), which a person starts on main with the
proposal's id and its merged pull request's number, runs this for a proposal whose status is ``proposed``
(merged, not applied). It reads the merged pull request's reviews from the GitHub API and hands them over as
JSON; everything else happens here, so that it is tested offline with recorded reviews:

1. a proposal whose status is ``applied`` is left alone (re-running is a no-op);
2. a proposal whose ``approvals/`` already holds files is refused: approvals come only from GitHub reviews,
   so a file the pull request committed there never stands in for a reviewer (``scale ci proposal-check``
   fails such a pull request before it merges);
3. the GitHub reviews alone are evaluated against governance/review-policy.yaml: two approving reviewers
   other than the author, placeholders never counted, the latest review of each person, approvals of an
   older commit than the merged head not counted; nothing is written when the policy is not satisfied;
4. the counted reviews are recorded in ``approvals/``, the decision record is written from them (``scale
   proposal decide``, with the pull-request link) and the proposal is applied (``scale proposal apply
   --confirm``: freeze, install, version bump, gap register, ``status: applied``);
5. the full ``scale check`` runs on the result, the unit tests included: a version bump must not break them
   (a test that assumed the head version, or a document validated against the head instead of the version it
   pins, fails here and not on main). If any step fails, every file is put back as it was and the error is
   raised: the workflow then pushes nothing, and its run fails with the error.

Only people approve; this records what they decided on GitHub and never approves by itself.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Callable

from . import layout
from .util import ScaleError, load_doc, load_yaml

# directories a snapshot leaves out: version control, environments, caches and local, git-ignored work
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "node_modules",
             "work", "scratchpad", "build", "dist"}


def _files(repo: Path) -> dict[str, Path]:
    out = {}
    stack = [Path(repo)]
    while stack:
        d = stack.pop()
        for p in d.iterdir():
            if p.is_dir() and not p.is_symlink():
                if p.name not in SKIP_DIRS and not p.name.endswith(".egg-info"):
                    stack.append(p)
            elif p.is_file():
                out[p.relative_to(repo).as_posix()] = p
    return out


class Snapshot:
    """The repository's files as they were (contents in memory), to put everything back when a step fails."""

    def __init__(self, repo: Path):
        self.repo = Path(repo)
        self.files = {rel: p.read_bytes() for rel, p in _files(self.repo).items()}
        self.dirs = {p.parent.relative_to(self.repo).as_posix() for p in _files(self.repo).values()}

    def restore(self) -> list[str]:
        """Remove files that appeared, rewrite files that changed, recreate files that went; return what was put back."""
        now, touched = _files(self.repo), []
        for rel, p in now.items():
            if rel not in self.files:
                p.unlink()
                touched.append(rel)
        for rel, data in self.files.items():
            p = self.repo / rel
            if not p.is_file() or p.read_bytes() != data:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
                touched.append(rel)
        for rel in sorted({Path(r).parent.as_posix() for r in touched}, key=len, reverse=True):
            d = self.repo / rel
            while d != self.repo and d.is_dir() and not any(d.iterdir()) and d.relative_to(self.repo).as_posix() not in self.dirs:
                d.rmdir()
                d = d.parent
        return sorted(touched)


def owner(repo: Path, cs: Path) -> str:
    """The folder a proposal is in, for the commit message: ``core`` or the domain's name (catalysis, for
    ``domain/proposals/``). The version it raises is the whole schema's either way."""
    rel = Path(cs).resolve().relative_to(Path(repo).resolve()).parts
    return "core" if rel[0] == layout.CORE else layout.domain_name(Path(repo) / rel[0])


def full_check(repo: Path) -> tuple[bool, str]:
    """The full ``scale check`` on the repository: every check of CI's ``test`` jobs, the unit tests included
    (they run in a subprocess on the applied tree, so the bump is tested before anything is committed)."""
    from .devcheck import run_checks
    buf = io.StringIO()
    ok = run_checks(repo, fast=False, out=buf)
    return ok, buf.getvalue()


def apply_merged(repo: Path, cs: Path, pr: int, reviews: list[dict], author: str | None = None,
                 head_sha: str | None = None, pr_url: str | None = None,
                 check: Callable[[Path], tuple[bool, str]] | None = full_check) -> dict:
    """Record the reviews of the merged pull request ``pr``, decide and apply proposal ``cs``; see the module
    docstring. ``check`` runs after the apply (None skips it, for tests of the steps before it)."""
    from .pgraph_proposal import apply, decide, load_proposal
    from .policy import evaluate, load_policy
    from .review import approvals, from_github, record
    repo = Path(repo).resolve()
    p = load_proposal(cs)
    pid = p["id"]
    if p.get("status") == "applied":
        return {"proposal": pid, "status": "already applied", "changed": False}
    if p.get("status") != "proposed":
        raise ScaleError(f"{pid} has status {p.get('status')!r}; only a merged proposal with status 'proposed' is applied")
    if not (cs / "validation_report.json").is_file():
        raise ScaleError(f"{pid} has no validation_report.json: its pull request did not run `scale proposal check {pid}`")
    held = approvals(cs)
    if held:
        raise ScaleError(f"{pid}: approvals/ already holds {len(held)} file(s) although the proposal is not applied; "
                         "approvals come only from the pull request's GitHub reviews, so files committed there are "
                         "not counted: remove them in a pull request (with two approvals) and re-run")
    recs = from_github(reviews, pr, author, head_sha)
    val = load_doc(cs / "validation_report.json")
    st = evaluate(load_policy(repo), recs, author=author, tier=val.get("tier"))
    if not st["satisfied"]:
        raise ScaleError(f"{pid}: pull request #{pr} does not satisfy {layout.REVIEW_POLICY}: " + "; ".join(st["missing"])
                         + "".join(f"; not counted: {x['reviewer']} ({x['why']})" for x in st["ignored"]))
    snap = Snapshot(repo)
    try:
        # only the approvals the policy counted are recorded (never the author's, a placeholder's or an
        # outsider's); the decision record lists those and names the reviews it did not count
        record(cs, st["counted"])
        rec = decide(cs, repo, pr=pr, pr_url=pr_url, author=author, records=recs)
        plan = apply(cs, repo, confirm=True)
        if check is not None:
            ok, out = check(repo)
            if not ok:
                raise ScaleError(f"{pid}: `scale check` failed after the apply:\n"
                                 + "\n".join(out.strip().splitlines()[-40:]))
    except BaseException:
        snap.restore()
        raise
    new = load_yaml(cs / "proposal.yaml")
    # the version is the whole schema's (kernel and catalysis); the folder the proposal is in follows in parentheses
    title = f"Apply proposal {pid} ({owner(repo, cs)}): schema {p['base']['version']} → {p['target_version']} (PR #{pr})"
    return {"proposal": pid, "status": "applied", "changed": True, "pr": pr, "approved_by": st["approved_by"],
            "decision_record": rec.relative_to(repo).as_posix(), "plan": plan, "proposal_status": new.get("status"),
            "commit_message": title}
