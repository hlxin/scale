"""Review policy: who may approve a pull request, and how many records of an agent's curation a person checks.

The policy lives in ``governance/review-policy.yaml`` (explained in governance/GOVERNANCE.md). GitHub pull-request
reviews are the approvals, and GitHub's ruleset on ``main`` enforces them; the tools only read the reviewers
(``scale domains check`` routes CODEOWNERS to them, ``scale check`` warns about placeholder entries) and the
sampling rule for curated records (``scale review sample``).
"""

from __future__ import annotations

from pathlib import Path

from . import layout
from .util import ScaleError, load_yaml

MATURITY = ("provisional", "stable", "deprecated")


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
    """The reviewers the policy lists; without ``placeholders``, only real people."""
    return [m for m in (policy.get("reviewers") or {}).get("members") or []
            if isinstance(m, dict) and (placeholders or not m.get("placeholder"))]


def placeholders(policy: dict) -> list[dict]:
    """Placeholder entries (``placeholder: true``): they are nobody and never count as approvals."""
    return [m for m in reviewers(policy, placeholders=True) if m.get("placeholder")]


def sample_records(doc: dict, fraction: float, seed: int, include_flagged: list[str] | None = None) -> list[dict]:
    """A reproducible sample of the records of a scale-catal document that state something from a
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


__all__ = ["load_policy", "reviewers", "placeholders", "sample_records", "ScaleError"]
