"""Version numbers and release ids.

The schema has one version for the science kernel and the catalysis domain together (the catalysis
manifest's ``version``), a semantic version numbered from 0.1.0. Constraints such as
``>=0.1.0,<1.0.0`` are checked by :func:`satisfies`. A release is named ``vX.Y.Z``; its identity comes
from its manifest (``distribution: scale-catal`` and ``release``), never from its directory's name.
"""

from __future__ import annotations

import re

from .util import ScaleError

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
DISTRIBUTION = "scale-catal"                                  # written into the manifests of releases


def parse_version(v: str) -> tuple[int, int, int]:
    v = v.lstrip("v")
    m = SEMVER.match(v)
    if not m:
        raise ScaleError(f"Not a semantic version: {v!r}")
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


def satisfies(version: str, constraint: str) -> bool:
    """Check ``version`` against a comma-separated constraint such as ``>=0.1.0,<1.0.0``."""
    ver = parse_version(version)
    for part in [c.strip() for c in constraint.split(",") if c.strip()]:
        m = re.match(r"^(>=|<=|==|>|<)?\s*v?(\d+\.\d+\.\d+)$", part)
        if not m:
            raise ScaleError(f"Bad version constraint: {part!r}")
        op, target = m.group(1) or "==", parse_version(m.group(2))
        ok = {
            ">=": ver >= target, "<=": ver <= target, "==": ver == target,
            ">": ver > target, "<": ver < target,
        }[op]
        if not ok:
            return False
    return True


# ---------------------------------------------------------------- release ids

def normalize_release_id(rid: str) -> str:
    """``v0.1.0`` and ``0.1.0`` -> the canonical id ``v0.1.0``."""
    ver = str(rid).strip().strip("/")
    if "/" in ver:
        raise ScaleError(f"Not a release id: {rid!r} (expected vX.Y.Z)")
    ver = ver if ver.startswith("v") else "v" + ver
    parse_version(ver)
    return ver


def release_key(rid: str) -> tuple:
    """Order of release ids: by semantic version."""
    return parse_version(str(rid))


def release_id(manifest: dict) -> str | None:
    """The id of the release a manifest describes: its ``release``, when its ``distribution`` is this one's."""
    rel = manifest.get("release")
    if not rel or manifest.get("distribution") != DISTRIBUTION:
        return None
    return normalize_release_id(rel)
