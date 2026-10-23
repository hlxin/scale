"""External identifiers on records, checked by what an identifier of their scheme looks like (docs/mappings.md).

Every node may carry ``identifiers``, a map from a scheme to an identifier ({"ec": "1.1.1.1"}). The schemes SCALE
knows are listed in ``core/mappings/identifiers.yaml``, each with its pattern (and, for a CAS Registry Number or an
ORCID iD, its check digit) and where an identifier resolves. Validation warns, never rejects: a listed scheme's
identifier that does not look like one is reported and kept as written; a scheme the registry does not list is kept,
unchecked. A technique's or a method's identifier (``technique_id``, ``method_id``) is an ontology term: a CURIE of
an ontology of ``core/mappings/ontologies.yaml`` in its pattern (CHMO:0000156 for X-ray diffraction), or an IRI.

The registries are the tools' own (the checkout these tools run from, or the installed package's data), never the
repository ``SCALE_REPO`` names, so a document is checked alike wherever it is validated; a registry is read again
when its file changes. An identifier matches its scheme's pattern as a whole: a trailing line break is not part of it.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from . import layout
from .util import load_yaml

SCHEME_KEYS = {"name": True, "pattern": True, "check_digit": False, "resolves": False, "example": False}
CHECK_DIGITS = ("cas", "iso7064_mod11_2")
# the properties that hold a technique's or a method's ontology term
TERM_PROPERTIES = ("technique_id", "method_id")
_CURIE = re.compile(r"(?P<prefix>[A-Za-z][A-Za-z0-9_-]*):(?P<local>\S+)")


def own_root() -> Path | None:
    """The tools' own data: the checkout this module runs from (scale-release.yaml and releases/ beside tools/), else
    the data an installed package bundles (scale/_data); never SCALE_REPO, so that one document is checked alike
    whichever repository a command works on."""
    here = Path(__file__).resolve().parent
    checkout = here.parent
    if (checkout / "scale-release.yaml").is_file() and (checkout / "releases").is_dir():
        return checkout
    bundled = here / "_data"
    return bundled if (bundled / "scale-release.yaml").is_file() else None


def _root(repo: Path | None = None) -> Path | None:
    return Path(repo) if repo is not None else own_root()


def _stamp(p: Path) -> tuple | None:
    """What says a file changed (its modification time and size); None for a file that is not there."""
    try:
        st = p.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


@lru_cache(maxsize=16)
def _section(path: str, key: str, stamp: tuple | None) -> tuple:
    """A registry's section as (key, entry) pairs, read again when the file's stamp changes (or it appears)."""
    if stamp is None:
        return ()
    doc = load_yaml(path)
    sec = doc.get(key) if isinstance(doc, dict) else None
    return tuple(sec.items()) if isinstance(sec, dict) else ()


def _registry(root: Path | None, rel: str, key: str) -> dict:
    if root is None:
        return {}
    p = Path(root) / rel
    return dict(_section(str(p), key, _stamp(p)))


def schemes(repo: Path | None = None) -> dict:
    """The identifier schemes by key (``core/mappings/identifiers.yaml``; {} where the registry is missing)."""
    return _registry(_root(repo), layout.IDENTIFIER_REGISTRY, "schemes")


def check_digit_ok(kind: str, value: str) -> bool:
    """Whether the check digit of a CAS Registry Number or an ORCID iD (ISO 7064 MOD 11-2) is right; False for a
    value that is not digits and hyphens (with a final X for an ORCID iD), never an error."""
    if kind not in CHECK_DIGITS:
        raise ValueError(f"unknown check digit {kind!r} ({', '.join(CHECK_DIGITS)})")
    digits = str(value).replace("-", "")
    if kind == "cas":
        if not re.fullmatch(r"[0-9]{2,}", digits):
            return False
        body, check = digits[:-1], int(digits[-1])
        return sum(int(d) * i for i, d in enumerate(reversed(body), start=1)) % 10 == check
    if not re.fullmatch(r"[0-9]+[0-9X]", digits):
        return False
    total = 0
    for d in digits[:-1]:
        total = (total + int(d)) * 2
    r = (12 - total % 11) % 11
    return digits[-1] == ("X" if r == 10 else str(r))


def _fullmatch(pattern, value: str) -> bool | None:
    """Whether the whole of ``value`` matches ``pattern``; None for a pattern that does not compile (the registry
    check reports it)."""
    try:
        return re.fullmatch(str(pattern), value) is not None
    except re.error:
        return None


def identifier_problem(scheme: dict, value) -> str | None:
    """Why ``value`` is no identifier of ``scheme`` (None when it looks like one): the whole value matches the
    scheme's pattern, and its check digit is right."""
    if not isinstance(value, str) or not value.strip():
        return "is not text"
    if _fullmatch(scheme["pattern"], value) is False:
        return f"does not match the pattern of its scheme ({scheme.get('name')}, {scheme['pattern']})"
    if scheme.get("check_digit") in CHECK_DIGITS and not check_digit_ok(scheme["check_digit"], value):
        return f"fails the check digit of its scheme ({scheme.get('name')})"
    return None


def _http_iri_problem(value: str) -> str | None:
    """Why an http(s) address is no usable IRI: a space or a control character in it, or no host."""
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return "is an http(s) IRI with a space or a control character in it"
    try:
        host = urlsplit(value).hostname
    except ValueError:
        host = None
    return None if host else "is an http(s) IRI without a host"


def term_problem(value, ontologies: dict) -> str | None:
    """Why ``value`` is no ontology term: a CURIE of a registered ontology in its pattern, or an http(s) IRI with a
    host (its scheme in any case)."""
    if not isinstance(value, str) or not value.strip():
        return "is not text"
    if re.match(r"(?i)https?://", value):
        return _http_iri_problem(value)
    m = _CURIE.fullmatch(value)
    if not m or m["prefix"] not in ontologies:
        return (f"is no ontology term: write a CURIE of an ontology of {layout.ONTOLOGY_REGISTRY} (such as "
                "CHMO:0000156 for X-ray diffraction) or an IRI, and the technique's name in words beside it")
    entry = ontologies[m["prefix"]] if isinstance(ontologies[m["prefix"]], dict) else {}
    if entry.get("pattern") and _fullmatch(entry["pattern"], value) is False:
        return f"does not match the pattern of {m['prefix']} terms ({entry['pattern']})"
    return None


def check_document(doc: dict, rep, repo: Path | None = None) -> None:
    """Warn about every identifier of a listed scheme that does not look like one, and every technique or method
    identifier that is no ontology term. Nothing is rejected or changed."""
    root = _root(repo)
    if root is None:                          # no registry to check against: nothing is reported
        return
    known = _registry(root, layout.IDENTIFIER_REGISTRY, "schemes")
    onts = _registry(root, layout.ONTOLOGY_REGISTRY, "ontologies")
    for rec in [*(doc.get("nodes") or []), *(doc.get("links") or [])]:
        p = rec.get("props") or {}
        rid = rec.get("id", "?")
        ids = p.get("identifiers")
        if isinstance(ids, dict):
            for key, value in ids.items():
                if isinstance(known.get(key), dict) and known[key].get("pattern"):
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
