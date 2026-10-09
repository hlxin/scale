"""Review policy: two approving reviews from reviewers other than the author, for every pull request.

The policy lives in ``governance/review-policy.yaml`` (explained in governance/GOVERNANCE.md, policy
version 4). GitHub pull-request reviews are the approvals: ``scale proposal apply-merged`` turns the
reviews of a merged pull request into approval records and evaluates them here before it writes the
decision record and applies the proposal; ``scale review status`` evaluates the records a proposal
holds. Tiers are information in a proposal's reports, not approval classes.

Who counts: a reviewer listed in the policy who is not a placeholder (a seat not filled yet) and not the
author of the change. The latest review of each person counts; a reviewer whose latest review requests
changes blocks.
"""

from __future__ import annotations

from pathlib import Path

from . import layout
from .util import ScaleError, load_yaml

MATURITY = ("provisional", "stable", "deprecated")
DECISIONS = ("approve", "request_changes", "comment", "dismissed")


def load_policy(repo: Path) -> dict:
    """The review policy of the repository (the wheel bundles it too). A missing policy is an error,
    never a silent default: who must approve is a governance decision, not a fallback."""
    p = Path(repo) / layout.REVIEW_POLICY
    if not p.exists():
        raise ScaleError(f"no review policy: {p} is missing")
    pol = load_yaml(p) or {}
    if not isinstance((pol.get("reviewers") or {}).get("members"), list):
        raise ScaleError(f"{layout.REVIEW_POLICY}: reviewers.members must list the reviewers")
    return pol


def _norm(s: str | None) -> str:
    return (s or "").strip().lower().removeprefix("@")


def reviewers(policy: dict, placeholders: bool = False) -> list[dict]:
    """The reviewers the policy lists; without ``placeholders``, only the seats filled by a person."""
    return [m for m in (policy.get("reviewers") or {}).get("members") or []
            if isinstance(m, dict) and (placeholders or not m.get("placeholder"))]


def placeholders(policy: dict) -> list[dict]:
    """Reviewer seats not filled yet (``placeholder: true``): they never count as approvals."""
    return [m for m in reviewers(policy, placeholders=True) if m.get("placeholder")]


def required(policy: dict) -> int:
    n = (policy.get("approvals") or {}).get("required", 2)
    if not isinstance(n, int) or n < 1:
        raise ScaleError(f"{layout.REVIEW_POLICY}: approvals.required must be a positive number, got {n!r}")
    return n


def _reviewer(policy: dict, who: str | None) -> dict | None:
    """The listed reviewer a login or name belongs to (placeholders included), or None."""
    w = _norm(who)
    return next((m for m in reviewers(policy, placeholders=True)
                 if w and w in {_norm(m.get("github")), _norm(m.get("name"))} - {""}), None)


def latest(approvals: list[dict]) -> dict[str, dict]:
    """The latest decision of each person (by ``at``), keyed by the normalized handle. A comment does not
    change a person's state (as on GitHub, where commenting keeps an earlier approval)."""
    out: dict[str, dict] = {}
    for a in sorted(approvals, key=lambda a: a.get("at") or ""):
        if a.get("decision") == "comment":
            continue
        out[_norm(a.get("reviewer"))] = a
    return out


def evaluate(policy: dict, approvals: list[dict], author: str | None = None, tier: int | None = None) -> dict:
    """Whether the approvals satisfy the policy: at least ``approvals.required`` distinct reviewers, not the
    author and not placeholders, whose latest decision is ``approve``, and no reviewer whose latest
    decision is ``request_changes``. Returns {satisfied, missing, approved_by, counted, ignored, blocking, ...};
    ``counted`` holds the latest approving record of each reviewer in ``approved_by`` (what is recorded)."""
    need = required(policy)
    states = latest(approvals)
    approved, ignored, blocking, counted = [], [], [], []
    for who, a in states.items():
        m = _reviewer(policy, a.get("reviewer"))
        name = (m or {}).get("github") or a.get("reviewer")
        if a.get("decision") == "request_changes" and m and not m.get("placeholder"):
            blocking.append(name)
            continue
        if a.get("decision") != "approve":
            continue
        if m is None:
            ignored.append({"reviewer": a.get("reviewer"), "why": "not a reviewer in the review policy"})
        elif m.get("placeholder"):
            ignored.append({"reviewer": a.get("reviewer"), "why": "a placeholder seat, not a person"})
        elif author and _norm(author) in {who, _norm(m.get("github")), _norm(m.get("name"))}:
            ignored.append({"reviewer": a.get("reviewer"), "why": "the author of the change"})
        else:
            approved.append(name)
            counted.append(a)
    approved = sorted(set(approved))
    missing = []
    if len(approved) < need:
        missing.append(f"{need - len(approved)} more approving review(s) from reviewers other than the author "
                       f"(has {len(approved)} of {need})")
    if blocking:
        missing.append("changes requested by " + ", ".join(sorted(blocking)))
    filled = reviewers(policy)
    notes = []
    if len([m for m in filled if _norm(m.get("github")) != _norm(author)]) < need:
        notes.append(f"only {len(filled)} reviewer seat(s) are filled ({len(placeholders(policy))} placeholders in "
                     f"{layout.REVIEW_POLICY}); {need} approvals from reviewers other than the author cannot be given yet")
    return {"policy_version": policy.get("policy_version"), "tier": tier, "author": author,
            "required": f"{need} approving reviews from reviewers other than the author",
            "approved_by": approved, "counted": sorted(counted, key=lambda a: a.get("at") or ""), "ignored": ignored, "blocking": sorted(blocking), "notes": notes,
            "missing": missing, "satisfied": not missing}


def sample_records(doc: dict, fraction: float, seed: int, include_flagged: list[str] | None = None) -> list[dict]:
    """A reproducible sample of the records of a scale-graph document that state something from a
    source (they carry evidence), for a human to check against the source (Tier 1 records)."""
    import random
    nodes = {n["id"]: n for n in doc.get("nodes", [])}
    cands = sorted(n["id"] for n in nodes.values() if (n.get("props") or {}).get("evidence"))
    k = max(1, round(len(cands) * fraction)) if cands else 0
    chosen = set(random.Random(seed).sample(cands, k)) | set(include_flagged or [])
    out = []
    for rid in sorted(chosen):
        n = nodes.get(rid)
        if not n:
            continue
        props = n.get("props") or {}
        ev = [{"source": e.get("source"), "locator": e.get("locator"), "quote": e.get("quote")}
              for e in props.get("evidence") or [] if isinstance(e, dict)]
        values = {k: v for k, v in props.items() if isinstance(v, dict) and "status" in v}
        out.append({"id": rid, "label": n.get("label"), "name": props.get("name"), "values": values, "evidence": ev,
                    "flagged": rid in (include_flagged or []),
                    "check": "each value, unit, locator and quote matches the source"})
    return out


__all__ = ["load_policy", "evaluate", "reviewers", "placeholders", "required", "latest", "sample_records", "ScaleError"]
