"""Small shared helpers: YAML/JSON I/O, digests, repository discovery, text matching."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml


class ScaleError(Exception):
    """A user-facing error raised by a SCALE tool."""


# ---------------------------------------------------------------- YAML / JSON

class _Dumper(yaml.SafeDumper):
    pass


_AMBIGUOUS = {"y", "Y", "yes", "Yes", "YES", "n", "N", "no", "No", "NO", "on", "On", "ON", "off", "Off", "OFF"}


def _str_presenter(dumper, data):
    # quote YAML 1.1 boolean look-alikes (docs/style.md) and every string of digits (a proposal id such as
    # '000008' must stay a string for any YAML reader: unquoted, 000007 is an octal 7 in YAML 1.1 and 000008 the
    # number 8 in YAML 1.2); literal block for multi-line text
    style = "|" if "\n" in data else ("'" if data in _AMBIGUOUS or (data.isascii() and data.isdigit()) else None)
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_presenter)


def load_yaml(path: str | os.PathLike) -> Any:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def dump_yaml(data: Any) -> str:
    return yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)


def write_yaml(path: str | os.PathLike, data: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(dump_yaml(data), encoding="utf-8")


def load_doc(path: str | os.PathLike) -> Any:
    p = Path(path)
    if p.suffix == ".json" or p.suffix == ".jsonld":
        return json.loads(p.read_text(encoding="utf-8"))
    return load_yaml(p)


def write_json(path: str | os.PathLike, data: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# Canonical JSON for machine-written documents (records, bundles, patches, gaps, logs):
# a fixed key order (identity first, then alphabetical), 2-space indent, UTF-8, trailing newline.
# Canonical output makes diffs and digests stable regardless of which tool or agent wrote the file.
KEY_ORDER = ["scale_graph", "id", "type", "predicate", "subject", "object", "label", "name", "kind", "status",
             "prefixes", "conforms_to", "collection", "curation", "nodes", "links"]


def canonical(obj: Any) -> Any:
    if isinstance(obj, dict):
        rank = {k: i for i, k in enumerate(KEY_ORDER)}
        keys = sorted(obj, key=lambda k: (rank.get(k, len(rank)), k))
        return {k: canonical(obj[k]) for k in keys}
    if isinstance(obj, list):
        return [canonical(x) for x in obj]
    return obj


def dump_canonical(data: Any) -> str:
    return json.dumps(canonical(data), indent=2, ensure_ascii=False) + "\n"


def write_canonical(path: str | os.PathLike, data: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(dump_canonical(data), encoding="utf-8")


DOC_GLOBS = ("*.json", "*.yaml", "*.yml")


def list_docs(directory: str | os.PathLike, pattern: str = "*") -> list[Path]:
    """Documents in a directory (JSON or YAML), sorted by name."""
    d = Path(directory)
    out: set[Path] = set()
    for g in DOC_GLOBS:
        out |= set(d.glob(pattern + g[1:] if pattern != "*" else g))
    return sorted(out)


def to_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------- digests

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike) -> str:
    return sha256_bytes(Path(path).read_bytes())


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def digest_tree(root: str | os.PathLike, exclude: tuple[str, ...] = ()) -> dict[str, str]:
    """sha256 of every file under root, keyed by POSIX relative path (sorted)."""
    root = Path(root)
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not any(part.startswith(".") or part == "__pycache__" for part in p.relative_to(root).parts):
            rel = p.relative_to(root).as_posix()
            if rel in exclude:
                continue
            out[rel] = sha256_file(p)
    return out


# ---------------------------------------------------------------- repository discovery

def find_repo_root(start: str | os.PathLike | None = None) -> Path:
    """Locate a SCALE repository checkout (contains scale-release.yaml and releases/)."""
    env = os.environ.get("SCALE_REPO")
    if env:
        p = Path(env).resolve()
        if (p / "scale-release.yaml").exists():
            return p
        raise ScaleError(f"SCALE_REPO={env} is not a SCALE repository (no scale-release.yaml)")
    candidates = [Path(start or os.getcwd()).resolve()]
    # also the checkout this package was imported from (editable installs)
    candidates.append(Path(__file__).resolve().parents[2])
    for c in candidates:
        for p in [c, *c.parents]:
            if (p / "scale-release.yaml").exists() and (p / "releases").is_dir():
                return p
    # installed wheel: releases, skills and examples are bundled as package data (see setup.py)
    bundled = Path(__file__).resolve().parent / "_data"
    if (bundled / "scale-release.yaml").exists():
        return bundled
    raise ScaleError("Could not find SCALE data. Reinstall the package, run inside a checkout, pass --repo, or set SCALE_REPO.")


# ---------------------------------------------------------------- text matching

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−‒﹣－"), "-")


def normalize_for_match(text: str) -> str:
    """Normalize text for verbatim-evidence matching.

    PDF/HTML text extraction splits tokens ("NH 3", "h −1") and varies dashes,
    so matching ignores whitespace, case, compatibility forms and dash variants.
    HTML entities must already be unescaped by the caller (see docs/curation.md).
    Quote digests of released records depend on it: do not change it.
    """
    t = unicodedata.normalize("NFKC", text).translate(_DASHES)
    t = re.sub(r"\s+", "", t)
    return t.lower()


def match_text(text: str) -> str:
    """Normalization for scale-graph quote checks: as normalize_for_match, and hyphens ignored too,
    since page texts break words at line ends ("hydrox-\nides") and a quote may or may not keep the break."""
    return normalize_for_match(text.replace("\u00ad", "")).replace("-", "")      # soft hyphens too
