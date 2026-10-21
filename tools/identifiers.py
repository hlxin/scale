"""External identifiers on records, checked by what an identifier of their scheme looks like (docs/mappings.md).

Every node may carry ``identifiers``, a map from a scheme to an identifier ({"ec": "1.1.1.1"}). The schemes SCALE
knows are listed in ``core/mappings/identifiers.yaml``, each with its pattern (and, for a CAS Registry Number or an
ORCID iD, its check digit) and where an identifier resolves. Validation warns, never rejects: a listed scheme's
identifier that does not look like one is reported and kept as written; a scheme the registry does not list is kept,
unchecked. A technique's or a method's identifier (``technique_id``, ``method_id``) is an ontology term: a CURIE of
an ontology of ``core/mappings/ontologies.yaml`` in its pattern (CHMO:0000156 for X-ray diffraction), or an IRI.

The registries are the tools' own (the checkout or the installed package's data), so a document is checked alike
wherever it is validated.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from . import layout
from .util import ScaleError, find_repo_root, load_yaml

SCHEME_KEYS = {"name": True, "pattern": True, "check_digit": False, "resolves": False, "example": False}
CHECK_DIGITS = ("cas", "iso7064_mod11_2")
# the properties that hold a technique's or a method's ontology term
TERM_PROPERTIES = ("technique_id", "method_id")
_CURIE = re.compile(r"^(?P<prefix>[A-Za-z][A-Za-z0-9_-]*):(?P<local>\S+)$")


def _root(repo: Path | None = None) -> Path:
    return Path(repo) if repo is not None else find_repo_root(Path(__file__).resolve().parent)


def schemes(repo: Path | None = None) -> dict:
    """The identifier schemes by key (``core/mappings/identifiers.yaml``; {} where the registry is missing)."""
    return dict(_schemes(str(_root(repo))))


@lru_cache(maxsize=4)
def _schemes(root: str) -> tuple:
    p = Path(root) / layout.IDENTIFIER_REGISTRY
    return tuple(((load_yaml(p) or {}).get("schemes") or {}).items()) if p.is_file() else ()


@lru_cache(maxsize=4)
def _ontologies(root: str) -> tuple:
    p = Path(root) / layout.ONTOLOGY_REGISTRY
    return tuple(((load_yaml(p) or {}).get("ontologies") or {}).items()) if p.is_file() else ()


def check_digit_ok(kind: str, value: str) -> bool:
    """Whether the check digit of a CAS Registry Number or an ORCID iD (ISO 7064 MOD 11-2) is right."""
    if kind == "cas":
        digits = value.replace("-", "")
        body, check = digits[:-1], int(digits[-1])
        return sum(int(d) * i for i, d in enumerate(reversed(body), start=1)) % 10 == check
    if kind == "iso7064_mod11_2":
        digits = value.replace("-", "")
        total = 0
        for d in digits[:-1]:
            total = (total + int(d)) * 2
        r = (12 - total % 11) % 11
        return digits[-1] == ("X" if r == 10 else str(r))
    raise ScaleError(f"unknown check digit {kind!r} ({', '.join(CHECK_DIGITS)})")


def identifier_problem(scheme: dict, value) -> str | None:
    """Why ``value`` is no identifier of ``scheme`` (None when it looks like one)."""
    if not isinstance(value, str) or not value.strip():
        return "is not text"
    if not re.match(str(scheme["pattern"]), value):
        return f"does not match the pattern of its scheme ({scheme['name']}, {scheme['pattern']})"
    if scheme.get("check_digit") and not check_digit_ok(scheme["check_digit"], value):
        return f"fails the check digit of its scheme ({scheme['name']})"
    return None


def term_problem(value, ontologies: dict) -> str | None:
    """Why ``value`` is no ontology term: a CURIE of a registered ontology in its pattern, or an http(s) IRI."""
    if not isinstance(value, str) or not value.strip():
        return "is not text"
    if re.match(r"^https?://\S+$", value):
        return None
    m = _CURIE.match(value)
    if not m or m["prefix"] not in ontologies:
        return (f"is no ontology term: write a CURIE of an ontology of {layout.ONTOLOGY_REGISTRY} (such as "
                "CHMO:0000156 for X-ray diffraction) or an IRI, and the technique's name in words beside it")
    if not re.match(str(ontologies[m["prefix"]]["pattern"]), value):
        return f"does not match the pattern of {m['prefix']} terms ({ontologies[m['prefix']]['pattern']})"
    return None


def check_document(doc: dict, rep, repo: Path | None = None) -> None:
    """Warn about every identifier of a listed scheme that does not look like one, and every technique or method
    identifier that is no ontology term. Nothing is rejected or changed."""
    try:
        root = str(_root(repo))
    except ScaleError:                        # no registry to check against: nothing is reported
        return
    known, onts = dict(_schemes(root)), dict(_ontologies(root))
    for rec in [*(doc.get("nodes") or []), *(doc.get("links") or [])]:
        p = rec.get("props") or {}
        rid = rec.get("id", "?")
        ids = p.get("identifiers")
        if isinstance(ids, dict):
            for key, value in ids.items():
                if key in known:
                    why = identifier_problem(known[key], value)
                    if why:
                        rep.add("warning", rid, f"identifiers.{key}: {value!r} {why}; it stays as written")
        for prop in TERM_PROPERTIES:
            if prop in p and onts:
                why = term_problem(p[prop], onts)
                if why:
                    rep.add("warning", rid, f"{prop}: {p[prop]!r} {why}")


def check_registry(repo: Path) -> list[dict]:
    """The registry's own problems (``scale domains check``): every key known, a name and a pattern that compiles and
    matches a whole identifier, a known check digit, a resolver naming {id}, an example its scheme accepts."""
    out = []
    rel = layout.IDENTIFIER_REGISTRY
    p = Path(repo) / rel
    if not p.is_file():
        return out
    for key, s in ((load_yaml(p) or {}).get("schemes") or {}).items():
        if not isinstance(s, dict):
            out.append({"where": rel, "message": f"{key}: a scheme is a mapping of name, pattern, …"})
            continue
        for k in sorted(set(s) - set(SCHEME_KEYS)):
            out.append({"where": rel, "message": f"{key}: unknown key {k!r} ({', '.join(SCHEME_KEYS)})"})
        for k, req in SCHEME_KEYS.items():
            if req and not s.get(k):
                out.append({"where": rel, "message": f"{key}: {k} is required"})
        try:
            re.compile(str(s.get("pattern") or ""))
            if not str(s.get("pattern") or "").startswith("^") or not str(s.get("pattern") or "").endswith("$"):
                out.append({"where": rel, "message": f"{key}: pattern must match a whole identifier, ^…$"})
        except re.error as x:
            out.append({"where": rel, "message": f"{key}: pattern does not compile ({x})"})
            continue
        if s.get("check_digit") and s["check_digit"] not in CHECK_DIGITS:
            out.append({"where": rel, "message": f"{key}: check_digit {s['check_digit']!r} is not one of "
                                                  f"{', '.join(CHECK_DIGITS)}"})
            continue
        if s.get("resolves") and "{id}" not in str(s["resolves"]):
            out.append({"where": rel, "message": f"{key}: resolves must name {{id}}"})
        if s.get("example") is not None and s.get("name") and s.get("pattern"):
            why = identifier_problem(s, str(s["example"]))
            if why:
                out.append({"where": rel, "message": f"{key}: its example {s['example']!r} {why}"})
    return out
