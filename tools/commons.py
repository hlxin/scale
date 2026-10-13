"""One publication's graph into a graph kept as parts (catal-commons): is it there already, and the files that add it.

A graph of one source (``scale source start | check | finish``, or any scale-catal document with one Source record)
is contributed to a parts folder (docs/graph-parts.md) in four steps, all deterministic:

1. **Already there?** ``find`` compares its Source with every Source of the folder: the same DOI (normalized), the
   same identifier of another kind (a patent number), the same digest of the text it was read from, or the same title
   (letters and digits only, any case) and year. A match is the answer, and nothing is written.
2. **Ids.** The source's records move into the folder's namespace (``<ns>/source/<slug>``, ``<ns>/<slug>/…``), and
   every other record of its namespace too (shared records: species, reactions). The steward and project the one-source
   graph names are left out: the folder has its own. Every string equal to a moved id is rewritten, so references in
   properties and evidence follow.
3. **Rights.** The source's rights entry joins the folder's ``rights.yaml``, and its quotes are capped again under the
   folder's limits (``limits: 0`` in graphs/: no quoted text of a source in copyright, kept as sha256 and length).
4. **Parts.** The source becomes ``parts/sources/<slug>.json``; a shared record the folder already holds keeps its
   properties and gains the source's evidence items; a new one is added to ``parts/shared.json``. The parts must build
   and the graph must validate, with every quote within the cap, or nothing is returned.

``scale graph contribute G --to graphs/catal-commons [--rights R] [--write]`` runs it; the web service opens the pull
request with the files it returns.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

from . import graphparts, pgraph, rights
from .util import ScaleError, dump_canonical, dump_yaml, load_yaml


def _norm_doi(v) -> str | None:
    m = re.search(r"10\.\d{4,9}/\S+", str(v or ""))
    return m.group(0).lower().rstrip(".") if m else None


def _norm_title(v) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(v or "").lower())


def _keys(src: dict) -> dict[str, str]:
    """What identifies a Source: its DOI, other identifiers, the digest of its text, its title with its year."""
    p = src.get("props") or {}
    out = {}
    doi = _norm_doi(p.get("doi")) or _norm_doi((p.get("identifiers") or {}).get("doi"))
    if doi:
        out["doi"] = doi
    for kind, v in sorted((p.get("identifiers") or {}).items()):
        if kind != "doi" and v:
            out[f"identifier:{kind}"] = re.sub(r"[^A-Z0-9]+", "", str(v).upper())
    if p.get("text_sha256"):
        out["text_sha256"] = str(p["text_sha256"])
    if len(_norm_title(p.get("title") or p.get("name"))) >= 12:
        out["title_year"] = f"{_norm_title(p.get('title') or p.get('name'))}|{p.get('year') or ''}"
    return out


def sources_of(doc: dict) -> list[dict]:
    return [n for n in doc.get("nodes") or [] if n.get("label") == "Source"]


def find(doc: dict, parts: dict) -> list[dict]:
    """The folder's Sources that are the document's Source: ``[{source, file, by}]`` (empty: not there)."""
    mine = sources_of(doc)
    if len(mine) != 1:
        raise ScaleError(f"a contribution holds one Source record; this document has {len(mine)}")
    want = _keys(mine[0])
    hits = []
    for slug, part in sorted(parts["sources"].items()):
        for n in sources_of(part):
            have = _keys(n)
            by = sorted(k for k in want if k in have and have[k] == want[k])
            if by:
                hits.append({"source": n["id"], "file": f"parts/sources/{slug}.json", "by": by})
    return hits


def _rename(obj, ids: dict[str, str]):
    if isinstance(obj, str):
        return ids.get(obj, obj)
    if isinstance(obj, list):
        return [_rename(x, ids) for x in obj]
    if isinstance(obj, dict):
        return {k: _rename(v, ids) for k, v in obj.items()}
    return obj


def _namespace(parts: dict) -> str:
    gid = (parts["header"].get("graph") or {}).get("graph_id") or ""
    if "/graph/" not in gid:
        raise ScaleError("the folder's header names no graph_id <ns>/graph/<name>, so its namespace is unknown")
    return gid.split("/graph/", 1)[0]


def _rights_text(path: Path, sid: str, entry: dict) -> str:
    """The folder's rights.yaml with the source's entry added, its comments kept."""
    text = path.read_text(encoding="utf-8")
    block = dump_yaml({sid: entry}).rstrip("\n")
    block = "\n".join("  " + line for line in block.splitlines())
    if re.search(r"^sources: \{\}\s*$", text, re.M):
        return re.sub(r"^sources: \{\}\s*$", lambda m: "sources:\n" + block, text, count=1, flags=re.M).rstrip("\n") + "\n"
    tail = text.split("\nsources:\n", 1)
    if len(tail) == 2 and not re.search(r"^[^\s#]", tail[1], re.M):      # sources is the last key: append to it
        return text.rstrip("\n") + "\n" + block + "\n"
    data = load_yaml(path) or {}
    data.setdefault("sources", {})[sid] = entry
    return dump_yaml(data)


def _at_version(doc: dict, want: str | None, repo) -> dict:
    """The document at the folder's schema version: migrated up when it pins an older one; refused when it pins a
    newer one (moving the folder to it is a person's decision: scale graph migrate)."""
    from .pgraph_migrate import raise_version, route
    from .versions import parse_version
    have = (doc.get("graph") or {}).get("schema_version")
    if have == want or not want:
        return doc
    if have and parse_version(have) > parse_version(want):
        raise ScaleError(f"the graph pins scale-catal {have}, the folder {want}: the folder moves to {have} first "
                         f"(scale graph migrate), or curate the source under {want} (scale source start --version {want})")
    if route(have, want) is None:
        raise ScaleError(f"the graph pins scale-catal {have}; there is no migration path to the folder's {want}")
    spec = pgraph.load_spec(pgraph.spec_for(repo, want, None, None))
    return raise_version(doc, want, spec)[0]


def contribute(doc: dict, folder: str | Path, entry: dict, repo: str | Path | None = None) -> dict:
    """The files that add a one-source graph to a parts folder (module docstring), or the matches that show it is
    there already: ``{"already": [...]}`` or ``{"source": id, "slug": s, "files": {relative path: text}, ...}``."""
    folder = Path(folder)
    parts = graphparts.read_parts(folder)
    hits = find(doc, parts)
    if hits:
        return {"already": hits, "files": {}}
    if not isinstance(entry, dict) or entry.get("class") not in rights.CLASSES:
        raise ScaleError("give the source's rights entry (class, licence, basis), as its rights.yaml holds it")
    ns = _namespace(parts)
    doc = _at_version(doc, (parts["header"].get("graph") or {}).get("schema_version"), repo)
    src = sources_of(doc)[0]
    old_ns, slug = src["id"].split("/source/", 1)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", slug):
        raise ScaleError(f"the source's slug {slug!r} is not a file name (lower-case letters, digits, . _ -)")
    if slug in parts["sources"]:
        raise ScaleError(f"parts/sources/{slug}.json exists but holds another source; rename the contribution's slug")
    head = (doc.get("graph") or {}).get("stewardship") or {}
    drop = {head.get("project"), *(head.get("contributed_by") or [])} - {None}
    ids = {}
    for n in doc["nodes"]:
        if n["id"] in drop:
            continue
        if n["id"] == src["id"]:
            ids[n["id"]] = f"{ns}/source/{slug}"
        elif n["id"].startswith(old_ns + "/"):
            ids[n["id"]] = ns + n["id"][len(old_ns):]
    for lk in doc["links"]:
        if lk["id"].startswith(old_ns + "/"):
            ids[lk["id"]] = ns + lk["id"][len(old_ns):]
    moved = _rename({"nodes": [n for n in doc["nodes"] if n["id"] not in drop],
                     "links": [lk for lk in doc["links"] if lk["source"] not in drop and lk["target"] not in drop]}, ids)
    sid = ids[src["id"]]
    entry = {k: v for k, v in entry.items() if k in ("class", "licence", "basis", "text_chars")}
    rpath = folder / "rights.yaml"
    rights_text = _rights_text(rpath, sid, entry)
    data = load_yaml(rpath) or {}
    limits = data.get("limits") or {}
    every = {**rights.load_rights(rpath), sid: {**{k: v for k, v in limits.items()}, **entry}}
    header = parts["header"]
    capped, _ = rights.cap({**header, **moved}, every)
    one = graphparts.split(capped)
    new_part = one["sources"][slug]
    shared = copy.deepcopy(parts["shared"])
    have = {n["id"]: n for n in shared["nodes"]}
    have_links = {lk["id"] for lk in shared["links"]}
    gained = []
    for n in one["shared"]["nodes"]:
        if n["id"] in have:
            ev = have[n["id"]].setdefault("props", {}).setdefault("evidence", [])
            add = [e for e in (n.get("props") or {}).get("evidence") or [] if e not in ev]
            if add:
                ev.extend(add)
                gained.append(n["id"])
        else:
            shared["nodes"].append(n)
    shared["links"] += [lk for lk in one["shared"]["links"] if lk["id"] not in have_links]
    merged = {**parts, "shared": shared, "sources": {**parts["sources"], slug: new_part}}
    built = graphparts.build(merged)
    spec = pgraph.load_spec(pgraph.spec_for(repo, header["graph"].get("schema_version"), None, built))
    rep = pgraph.validate(built, spec)
    held = rights.report(built, every)
    if rep.errors or not held["ok"]:
        raise ScaleError("the commons would not validate with this source: "
                         + "; ".join(f"{e['record']}: {e['message']}" for e in rep.errors[:8])
                         + ("" if held["ok"] else f"; quotes beyond the cap: {held['violations'][:3]}"))
    added = [n["id"] for n in one["shared"]["nodes"] if n["id"] not in have]
    mine = [ev for _, _, _, ev in rights.items(built) if ev.get("source") == sid]     # the source's evidence, capped
    return {"source": sid, "slug": slug, "class": entry["class"],
            "files": {f"parts/sources/{slug}.json": dump_canonical(graphparts._sorted(new_part)),
                      "parts/shared.json": dump_canonical(graphparts._sorted(shared)),
                      "rights.yaml": rights_text},
            "records": {"nodes": len(new_part["nodes"]), "links": len(new_part["links"])},
            "shared_added": added, "shared_with_new_evidence": gained,
            "quotes": {"kept": sum(1 for ev in mine if any(isinstance(ev.get(f), str) and ev[f] for f in rights.TEXT_FIELDS)),
                       "withheld": sum(1 for ev in mine if rights.withheld(ev))},
            "warnings": len(rep.warnings)}


def write(result: dict, folder: str | Path) -> list[str]:
    folder = Path(folder)
    for rel, text in result["files"].items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text, encoding="utf-8")
    return sorted(result["files"])
