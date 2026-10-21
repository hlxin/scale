"""A graph kept as one part per source: split a scale-catal document into parts and build it back.

A graph that grows one publication at a time is kept in a folder as parts, so that a contribution adds or changes
one file and never collides with another (docs/graph-parts.md):

    <graph folder>/
    ├── <name>.graph.json          the built graph, what tools, queries and exports read
    └── parts/
        ├── header.json            the graph's own object (title, description, schema version, stewardship)
        ├── shared.json            the nodes several sources refer to (species, reactions, people, institutions)
        └── sources/<slug>.json    one source: its Source record, every record it alone states, and their links

A source's records are those whose id is its Source id (``<ns>/source/<slug>``) or starts with ``<ns>/<slug>/``;
every other node is shared. A link belongs to the source of its first endpoint that belongs to one; a link between
two shared nodes is shared. Every part states the schema version it follows, which must be the header's.

``build`` is deterministic: the nodes and the links of every part, sorted by id, under the header. Splitting a graph
and building it back gives the same document. ``subset`` keeps some sources and the shared records they reach, and
drops from shared records the evidence of the sources left out.
"""

from __future__ import annotations

import json
from pathlib import Path

from .util import ScaleError, dump_canonical, write_canonical

PARTS = "parts"
HEADER = "header.json"
SHARED = "shared.json"
SOURCES = "sources"


def _source_ids(doc: dict) -> dict[str, str]:
    """{source id: slug} for the Source records of a document (``<ns>/source/<slug>``)."""
    out = {}
    for n in doc.get("nodes") or []:
        if n.get("label") == "Source" and "/source/" in n["id"]:
            out[n["id"]] = n["id"].split("/source/", 1)[1]
    return out


def _owner_fn(source_ids: dict[str, str]):
    """A function giving the source id a record id belongs to, or None for a shared record."""
    prefixes = {sid.split("/source/", 1)[0] + "/" + slug + "/": sid for sid, slug in source_ids.items()}

    def owner(rid: str) -> str | None:
        if rid in source_ids:
            return rid
        ns_slug = rid.split("/", 2)
        if len(ns_slug) < 3:
            return None
        return prefixes.get(f"{ns_slug[0]}/{ns_slug[1]}/")
    return owner


def split(doc: dict) -> dict:
    """The parts of a document: {"header": ..., "shared": ..., "sources": {slug: part}}. A link between the records
    of two different sources has no part to go to and is refused."""
    sids = _source_ids(doc)
    if not sids:
        raise ScaleError("the document has no Source records (<ns>/source/<slug>) to split by")
    owner = _owner_fn(sids)
    version = (doc.get("graph") or {}).get("schema_version")
    parts = {sid: {"source": sid, "schema_version": version, "nodes": [], "links": []} for sid in sids}
    shared = {"schema_version": version, "nodes": [], "links": []}
    for n in doc.get("nodes") or []:
        (parts[o] if (o := owner(n["id"])) else shared)["nodes"].append(n)
    for lk in doc.get("links") or []:
        a, b = owner(lk["source"]), owner(lk["target"])
        if a and b and a != b:
            raise ScaleError(f"link {lk.get('id')} joins the records of two sources ({a}, {b}); "
                             "parts hold one source each")
        (parts[a or b] if (a or b) else shared)["links"].append(lk)
    header = {k: v for k, v in doc.items() if k not in ("nodes", "links")}
    return {"header": header, "shared": shared, "sources": {sids[s]: p for s, p in parts.items()}}


def write_parts(parts: dict, folder: str | Path) -> Path:
    """Write parts under ``<folder>/parts/``; sources not in ``parts`` are removed. Returns the parts folder."""
    root = Path(folder) / PARTS
    (root / SOURCES).mkdir(parents=True, exist_ok=True)
    write_canonical(root / HEADER, parts["header"])
    write_canonical(root / SHARED, _sorted(parts["shared"]))
    keep = set()
    for slug, part in parts["sources"].items():
        p = root / SOURCES / f"{slug}.json"
        write_canonical(p, _sorted(part))
        keep.add(p.name)
    for p in (root / SOURCES).glob("*.json"):
        if p.name not in keep:
            p.unlink()
    return root


def _sorted(part: dict) -> dict:
    return {**part, "nodes": sorted(part["nodes"], key=lambda n: n["id"]),
            "links": sorted(part["links"], key=lambda lk: lk["id"])}


def read_parts(folder: str | Path) -> dict:
    root = Path(folder) / PARTS
    if not (root / HEADER).is_file():
        raise ScaleError(f"{root / HEADER}: missing (a graph kept as parts has parts/header.json)")
    load = lambda p: json.loads(p.read_text(encoding="utf-8"))
    return {"header": load(root / HEADER), "shared": load(root / SHARED) if (root / SHARED).is_file() else
            {"nodes": [], "links": []},
            "sources": {p.stem: load(p) for p in sorted((root / SOURCES).glob("*.json"))}}


def problems(parts: dict) -> list[str]:
    """What keeps the parts from building: a part at another schema version, a record in the wrong part, an id
    used twice, a link to a record no part holds."""
    out = []
    version = (parts["header"].get("graph") or {}).get("schema_version")
    sids = {p.get("source"): slug for slug, p in parts["sources"].items()}
    owner = _owner_fn({s: v for s, v in sids.items() if s})
    seen: dict[str, str] = {}
    named = [("shared.json", parts["shared"], None)] + [(f"sources/{slug}.json", p, p.get("source"))
                                                         for slug, p in parts["sources"].items()]
    for where, part, sid in named:
        if part.get("schema_version") != version:
            out.append(f"{where}: schema_version {part.get('schema_version')!r}, the header's is {version!r}")
        if sid is not None and (not sid or "/source/" not in sid or sid.split("/source/", 1)[1] != where[8:-5]):
            out.append(f"{where}: source {sid!r} is not <ns>/source/<the file's name>")
        for kind, recs in (("node", part.get("nodes") or []), ("link", part.get("links") or [])):
            for r in recs:
                rid = r.get("id")
                if rid in seen:
                    out.append(f"{where}: {kind} {rid} is also in {seen[rid]}")
                seen[rid] = where
                if kind == "node" and owner(rid) != sid:
                    out.append(f"{where}: node {rid} belongs in "
                               f"{'shared.json' if owner(rid) is None else 'sources/' + sids[owner(rid)] + '.json'}")
                if kind == "link":
                    ends = {owner(r.get("source")), owner(r.get("target"))} - {None}
                    if (sid is None and ends) or (sid is not None and ends != {sid}):
                        out.append(f"{where}: link {rid} joins {r.get('source')} and {r.get('target')}, "
                                   "which do not belong in this part")
    nodes = {n["id"] for _, p, _ in named for n in p.get("nodes") or []}
    for where, part, _ in named:
        for lk in part.get("links") or []:
            for end in (lk.get("source"), lk.get("target")):
                if end not in nodes:
                    out.append(f"{where}: link {lk.get('id')} refers to {end}, which no part holds")
    return out


def build(parts: dict) -> dict:
    """The graph the parts make: every node and link, sorted by id, under the header. Refuses parts with problems."""
    bad = problems(parts)
    if bad:
        raise ScaleError("the parts do not build:\n  " + "\n  ".join(bad[:20]) +
                         (f"\n  … and {len(bad) - 20} more" if len(bad) > 20 else ""))
    every = [parts["shared"]] + list(parts["sources"].values())
    return {**parts["header"],
            "nodes": sorted((n for p in every for n in p.get("nodes") or []), key=lambda n: n["id"]),
            "links": sorted((lk for p in every for lk in p.get("links") or []), key=lambda lk: lk["id"])}


def build_folder(folder: str | Path) -> dict:
    return build(read_parts(folder))


def same(doc: dict, path: str | Path) -> bool:
    """Whether a committed graph file is exactly what the parts build (canonical JSON)."""
    p = Path(path)
    return p.is_file() and p.read_text(encoding="utf-8") == dump_canonical(doc)


def _strings(v) -> set[str]:
    if isinstance(v, str):
        return {v}
    if isinstance(v, dict):
        return set().union(*(_strings(x) for x in v.values())) if v else set()
    if isinstance(v, list):
        return set().union(*(_strings(x) for x in v)) if v else set()
    return set()


def subset(parts: dict, slugs: list[str], header: dict | None = None) -> dict:
    """The parts of a graph of some of the sources: those sources, the shared records they reach (through their own
    links, then through links between shared records) and those the graph's own object names (its stewardship's
    organisation and project), and in shared records only the evidence of those sources. The graph's checks
    (``record_check``) keep the records the subset holds, with their checkers; a check with none of them goes.
    ``header`` replaces keys of the graph's own object (a new id, title, description)."""
    from .recordchecks import checks_of, prune, records_of
    missing = sorted(set(slugs) - set(parts["sources"]))
    if missing:
        raise ScaleError(f"no such sources: {', '.join(missing)}")
    chosen = {s: parts["sources"][s] for s in sorted(slugs)}
    keep_sources = {p["source"] for p in chosen.values()}
    shared_ids = {n["id"] for n in parts["shared"]["nodes"]}
    reach = {e for p in chosen.values() for lk in p["links"] for e in (lk["source"], lk["target"]) if e in shared_ids}
    graph = parts["header"].get("graph") or {}
    named = {**parts["header"], "graph": {k: v for k, v in graph.items() if k != "checks"}}
    reach |= {s for s in _strings(named) if s in shared_ids}    # what the graph's own object names, its checks apart
    own = {r["id"] for p in chosen.values() for r in [*p.get("nodes", []), *p.get("links", [])]}

    def expand() -> None:
        while True:
            more = {e for lk in parts["shared"]["links"] if lk["source"] in reach for e in (lk["target"],)} - reach
            if not more:
                break
            reach.update(more)

    def shared_links() -> set:
        return {lk["id"] for lk in parts["shared"]["links"] if lk["source"] in reach and lk["target"] in reach}
    # a check that keeps a record (a node, or a shared link between kept nodes) keeps the person who made it, who may
    # bring more shared records in turn: repeat until nothing new is reached
    while True:
        expand()
        held = own | reach | shared_links()
        checkers = {c.get("checked_by") for c in checks_of(graph) if set(records_of(c)) & held}
        more = {x for x in checkers if x in shared_ids} - reach
        if not more:
            break
        reach |= more

    def only_kept(rec: dict) -> dict:
        ev = (rec.get("props") or {}).get("evidence")
        if not ev:
            return rec
        props = {k: v for k, v in rec["props"].items() if k != "evidence"}
        kept = [e for e in ev if e.get("source") in keep_sources]
        return {**rec, "props": {**props, "evidence": kept} if kept else props}
    nodes = [only_kept(n) for n in parts["shared"]["nodes"] if n["id"] in reach]
    links = [only_kept(lk) for lk in parts["shared"]["links"] if lk["source"] in reach and lk["target"] in reach]
    head = dict(parts["header"])
    if checks_of(graph):
        every = {r["id"] for p in [parts["shared"], *parts["sources"].values()]
                 for r in [*p.get("nodes", []), *p.get("links", [])]}
        present = own | {r["id"] for r in nodes + links}
        head["graph"], _ = prune(dict(graph), present, every - present)
    if header:
        head["graph"] = {**head.get("graph", {}), **header}
    return {"header": head, "shared": {**parts["shared"], "nodes": nodes, "links": links}, "sources": chosen}


__all__ = ["split", "write_parts", "read_parts", "problems", "build", "build_folder", "same", "subset"]
