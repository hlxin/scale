"""Human review of schema change proposals: approvals from GitHub reviews, and the pull-request body.

People approve by reviewing the pull request on GitHub; there is no other way to approve. After the
pull request merges, ``scale proposal apply-merged`` records the reviews it counted in the proposal's
``approvals/`` (one file per review: reviewer, decision, time, pull request, review id) and evaluates
them with ``policy.evaluate``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .util import ScaleError, list_docs, load_doc, load_yaml, write_canonical

# GitHub review states and what they record (PENDING reviews are not submitted and are skipped)
GITHUB_STATES = {"APPROVED": "approve", "CHANGES_REQUESTED": "request_changes", "COMMENTED": "comment",
                 "DISMISSED": "dismissed"}


def from_github(reviews: list[dict], pr: int, author: str | None = None, head_sha: str | None = None) -> list[dict]:
    """Approval records from a pull request's reviews as the GitHub API returns them
    (``GET /repos/{owner}/{repo}/pulls/{n}/reviews``). An approval given on another commit than the
    merged head (``head_sha``) is stale: it is recorded as dismissed, as GitHub does when new commits
    arrive. Reviews without a user (a deleted account) or not submitted are skipped."""
    if not isinstance(reviews, list):
        raise ScaleError("reviews: expected the JSON list of a pull request's reviews (GitHub API)")
    out = []
    for r in reviews:
        login = ((r or {}).get("user") or {}).get("login")
        decision = GITHUB_STATES.get(str((r or {}).get("state") or "").upper())
        if not login or decision is None or not r.get("submitted_at"):
            continue
        rec = {"reviewer": login, "decision": decision, "at": r["submitted_at"], "pr": int(pr), "review_id": r.get("id"),
               "source": "github", **({"commit": r["commit_id"]} if r.get("commit_id") else {}),
               **({"pr_author": author} if author else {})}
        if decision == "approve" and head_sha and r.get("commit_id") and r["commit_id"] != head_sha:
            rec.update(decision="dismissed", note=f"approved {r['commit_id'][:12]}, not the merged head {head_sha[:12]}")
        out.append(rec)
    return out


def record(pdir: Path, recs: list[dict]) -> list[Path]:
    """Write approval records into ``<proposal>/approvals/`` (``github-<login>-<review id>.json``). A record that
    exists already is left as it is (re-running is a no-op)."""
    written = []
    for r in recs:
        path = Path(pdir) / "approvals" / f"github-{r['reviewer']}-{r.get('review_id') or r['at'].replace(':', '')}.json"
        if path.exists():
            continue
        write_canonical(path, {"proposal": load_yaml(Path(pdir) / "proposal.yaml")["id"], **r})
        written.append(path)
    return written


def approvals(pdir: Path) -> list[dict]:
    return [load_doc(p) for p in list_docs(pdir / "approvals")] if (pdir / "approvals").exists() else []


def proposal_pr_body(pdir: Path) -> str:
    """A proposal's pull-request body: the PR_BODY.md that ``scale proposal check`` wrote."""
    body = pdir / "PR_BODY.md"
    if not body.exists():
        raise ScaleError(f"{pdir.name} has no PR_BODY.md: run `scale proposal check {pdir.name}` first")
    return body.read_text()


def open_pr(pdir: Path, branch: str, base: str = "main", dry_run: bool = True) -> dict:
    """Open a pull request for a proposal with gh (dry-run by default)."""
    body = proposal_pr_body(pdir)
    title = load_yaml(pdir / "proposal.yaml")["title"]
    cmd = ["gh", "pr", "create", "--base", base, "--head", branch, "--title", title, "--body", body]
    if dry_run:
        return {"dry_run": True, "command": cmd[:-1] + ["<PR_BODY.md>"]}   # the gh command --submit runs, body elided
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ScaleError(proc.stderr.strip())
    return {"dry_run": False, "url": proc.stdout.strip()}
