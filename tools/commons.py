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
4. **Parts, with repeats discarded.** The source becomes ``parts/sources/<slug>.json``. A shared record the folder
   holds already, by id or by identity (``_identity``: the same label and the same identifier, InChI, SMILES, ORCID
   or ROR, else the same name with no conflicting formula), is not added again: the contribution's references point
   to the folder's record, which gains the source's evidence items and the properties it did not state; a value
   equal to the one it holds is a repeat, and a different one is left out and reported (``conflicts``) for the
   reviewer. A link the folder holds already (the same ends and type), or one the contribution states twice, is a
   repeat too: dropped, its evidence added to the link kept. Repeats are never merged and never counted
   (``repeats``). The parts must build and the graph must validate, with every quote within the cap, or nothing is
   returned.
5. **Credit.** With a contributor (a GitHub login), the contribution is added to the folder's ``contributors.yaml``:
   who, which source, on which day, how many records and links, its evidence-backed triples (``triples``: the
   statements it adds) and how complete it is by the domain checklist (``completeness``). ``leaderboard`` scores and
   ranks the contributors from it, and from how often other people's questions use what they added (``SCORING``).

``scale graph contribute G --to graphs/catal-commons [--rights R] [--write]`` runs it; the web service opens the pull
request with the files it returns.
"""

from __future__ import annotations

import copy
import datetime as _dt
import math
import re
from pathlib import Path

from . import graphparts, pgraph, pgraph_profiles, rights
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


_IDENTIFYING = ("inchi", "smiles", "orcid", "ror")


def _identity(n: dict) -> list[tuple]:
    """What makes two shared records the same thing, strongest first: an external identifier, else the name."""
    p = n.get("props") or {}
    keys = [(n.get("label"), f"identifier:{k}", re.sub(r"\s+", "", str(v)).lower())
            for k, v in sorted((p.get("identifiers") or {}).items()) if v]
    keys += [(n.get("label"), k, re.sub(r"\s+", "", str(p[k])).lower()) for k in _IDENTIFYING if isinstance(p.get(k), str) and p[k]]
    if _norm_title(p.get("name")):
        keys.append((n.get("label"), "name", _norm_title(p.get("name"))))
    return keys


def _same(a: dict, b: dict) -> bool:
    """Two shared records are one when they share an identity key and state no different formula."""
    fa, fb = (a.get("props") or {}).get("formula"), (b.get("props") or {}).get("formula")
    return not (fa and fb and _norm_title(fa) != _norm_title(fb))


def _link_key(lk: dict) -> tuple:
    return (lk.get("source"), lk.get("type"), lk.get("target"))


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


LEDGER = "contributors.yaml"
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")      # a GitHub login


# What is not a statement of the source's science: a record's provenance and the curator's bookkeeping.
_NOT_STATED = frozenset({"evidence", "origin", "locators", "status", "note", "as_reported", "missing_reason"})


def _stated(v) -> bool:
    if isinstance(v, dict) and "status" in v:
        return v["status"] != "not_reported"
    return v not in (None, "", [], {})


def triples(nodes: list[dict], links: list[dict]) -> int:
    """The evidence-backed statements a contribution adds, each one subject-predicate-object: every link between two
    records (but the REPORTED_IN that ties each record to its source), and every value a record or a link states (but
    its evidence, provenance, notes and a value not reported), counted only when that link or record cites evidence.
    A Source's bibliographic properties are not counted."""
    n = 0
    for r in [*(x for x in nodes if x.get("label") != "Source"), *(lk for lk in links if lk.get("type") != "REPORTED_IN")]:
        p = r.get("props") or {}
        if not p.get("evidence"):
            continue
        n += ("type" in r) + sum(1 for k, v in p.items() if k not in _NOT_STATED and _stated(v))
    return n


def completeness(doc: dict, spec: dict) -> float | None:
    """How complete a one-source graph is by the checklists it follows: the should items filled and the evidence
    patterns found, of those its records call for (None when they call for none)."""
    done = want = 0
    for r in pgraph_profiles.conformance(doc, spec)["profiles"].values():
        done += r["recommended"]["filled"] + r["evidence"]["found"]
        want += r["recommended"]["expected"] + r["evidence"]["expected"]
    return round(done / want, 3) if want else None


# How the leaderboard scores (published with it, so that everyone can see what counts). Changing it is a pull request.
SCORING = {
    "score": "the sum, over a contributor's merged contributions, of its triples times its use weight",
    "triples": "evidence-backed statements: each link between two records and each value a record or link states, "
               "when it cites evidence, and only what the merge adds: a repeat of what catal-commons holds (a shared "
               "record, a value or a link it has already) is discarded on merge and never counted; evidence, notes, "
               "provenance, values not reported and a paper's bibliographic details do not count",
    "use_weight": "1 + log2(1 + reach): 1 when no one has used it yet, 2 at one use, 3 at three, 4 at seven, so that "
                  "use counts but never swamps the knowledge added",
    "reach": "the distinct (person, day) pairs in which a signed-in person other than its contributor asked a "
             "question, ran a query or searched and the answer used one of its records; counted by the web service, "
             "which keeps no question and only a keyed digest of the login",
    "completeness": "shown beside the score, never mixed into it: the checklist's should items and evidence patterns "
                    "filled, of those the paper's records call for, weighted by triples",
    "levels": "by score: Contributor (a merged contribution), Curator (1,000), Senior curator (10,000), Fellow "
              "(100,000)",
    "recent": "the last 90 days: contributions merged in that time",
}
LEVELS = ((100_000, "Fellow"), (10_000, "Senior curator"), (1_000, "Curator"), (0, "Contributor"))


def use_weight(reach: int) -> float:
    return 1 + math.log2(1 + max(0, int(reach)))


def level(score: int) -> dict:
    """The level a score reaches and the next one, with how far it is: ``{name, next, to_next}``."""
    i = next(i for i, (at, _) in enumerate(LEVELS) if score >= at)
    nxt = LEVELS[i - 1] if i else None
    return {"name": LEVELS[i][1], "next": nxt[1] if nxt else None, "to_next": nxt[0] - score if nxt else None}


def contributions(folder: str | Path) -> list[dict]:
    """The folder's contributions as ``contributors.yaml`` lists them (none when it has no ledger)."""
    p = Path(folder) / LEDGER
    return list((load_yaml(p) or {}).get("contributions") or []) if p.exists() else []


def leaderboard(folder: str | Path, reach: dict[str, int] | None = None, since: str | None = None) -> list[dict]:
    """The contributors scored by ``SCORING`` and ranked by score, then triples, then the earliest first contribution:
    ``[{rank, github, score, triples, reach, completeness, sources, records, links, first, last, level,
    contributions: [{source, added, triples, reach, score, completeness}]}]``. ``reach`` maps a source's slug to the
    uses of its records by others (the web service counts them; none here); ``since`` (a day) keeps only the
    contributions merged from that day on (the recent board)."""
    reach = reach or {}
    by: dict[str, dict] = {}
    for c in contributions(folder):
        if since and str(c["added"]) < since:
            continue
        g = by.setdefault(str(c["github"]).lower(), {"github": str(c["github"]), "score": 0.0, "triples": 0, "reach": 0,
                                                    "sources": 0, "records": 0, "links": 0, "_done": 0.0, "_of": 0,
                                                    "first": str(c["added"]), "last": str(c["added"]),
                                                    "contributions": []})
        t, r = int(c.get("triples") or 0), int(reach.get(str(c["source"]), 0))
        s = t * use_weight(r)
        g["contributions"].append({"source": str(c["source"]), "added": str(c["added"]), "triples": t, "reach": r,
                                   "score": round(s), "completeness": c.get("completeness")})
        g["score"] += s
        g["triples"] += t
        g["reach"] += r
        g["sources"] += 1
        g["records"] += int(c.get("records") or 0)
        g["links"] += int(c.get("links") or 0)
        if c.get("completeness") is not None:
            g["_done"] += float(c["completeness"]) * t
            g["_of"] += t
        g["first"], g["last"] = min(g["first"], str(c["added"])), max(g["last"], str(c["added"]))
    for g in by.values():
        g["score"] = round(g["score"])
        g["completeness"] = round(g.pop("_done") / g["_of"], 3) if g["_of"] else None
        g.pop("_of")
        g["level"] = level(g["score"])
        g["contributions"].sort(key=lambda x: (-x["score"], x["source"]))
    ranked = sorted(by.values(), key=lambda g: (-g["score"], -g["triples"], g["first"], g["github"].lower()))
    return [{"rank": i + 1, **g} for i, g in enumerate(ranked)]


def boards(folder: str | Path, reach: dict[str, int] | None = None, today: str | None = None) -> dict:
    """The leaderboard as the site and the service publish it: all time and the last 90 days, with ``SCORING``."""
    day = _dt.date.fromisoformat(today) if today else _dt.date.today()
    return {"scoring": SCORING, "levels": [{"at": at, "name": n} for at, n in reversed(LEVELS)],
            "with_reach": reach is not None, "contributors": leaderboard(folder, reach),
            "recent": leaderboard(folder, reach, since=(day - _dt.timedelta(days=90)).isoformat())}


def _ledger_text(folder: Path, contributor: str, slug: str, on: str, records: dict) -> str:
    if not _LOGIN.match(contributor):
        raise ScaleError(f"{contributor!r} is not a GitHub login")
    rows = contributions(folder) + [{"github": contributor, "source": slug, "added": on,
                                     "records": records["nodes"], "links": records["links"],
                                     "triples": records["triples"], "completeness": records["completeness"]}]
    head = ("# Who contributed each source of this folder, one entry per contribution, added by the pull request that\n"
            "# adds the source (tools/commons.py). The site's leaderboard ranks contributors from it.\n")
    return head + dump_yaml({"contributions": rows})


def contribute(doc: dict, folder: str | Path, entry: dict, repo: str | Path | None = None,
               contributor: str | None = None, on: str | None = None) -> dict:
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
    shared = copy.deepcopy(parts["shared"])
    have = {n["id"]: n for n in shared["nodes"]}
    known = {}
    for n in shared["nodes"]:
        for k in _identity(n):
            known.setdefault(k, n)
    same = {}                                       # a new shared record that the folder holds under another id
    for n in one["shared"]["nodes"]:
        if n["id"] not in have:
            hit = next((known[k] for k in _identity(n) if k in known and _same(known[k], n)), None)
            if hit is not None:
                same[n["id"]] = hit["id"]
    one = _rename(one, same)                         # its references, and its own id, now name the folder's record
    new_part = one["sources"][slug]
    gained, conflicts, repeated_values, new_values = [], [], 0, []
    for n in one["shared"]["nodes"]:
        if n["id"] in have:
            held = have[n["id"]].setdefault("props", {})
            ev = held.setdefault("evidence", [])
            add = [e for e in (n.get("props") or {}).get("evidence") or [] if e not in ev]
            for k, v in (n.get("props") or {}).items():
                if k in _NOT_STATED or not _stated(v):
                    continue
                if k not in held or not _stated(held[k]):
                    held[k] = v
                    new_values.append(n["id"])
                elif held[k] == v:
                    repeated_values += 1
                else:
                    conflicts.append({"record": n["id"], "property": k, "held": held[k], "given": v})
            if add:
                ev.extend(add)
                gained.append(n["id"])
        else:
            shared["nodes"].append(n)
    held_links = {_link_key(lk): lk for lk in shared["links"]}
    repeated_links, part_links, new_shared_links = 0, {}, []

    def repeat(kept: dict, lk: dict) -> None:       # the same ends and type: its evidence goes to the link kept
        ev = kept.setdefault("props", {}).setdefault("evidence", [])
        ev.extend(e for e in (lk.get("props") or {}).get("evidence") or [] if e not in ev)
    for lk in one["shared"]["links"]:
        k = _link_key(lk)
        if k in held_links:
            repeat(held_links[k], lk)
            repeated_links += 1
        else:
            held_links[k] = lk
            shared["links"].append(lk)
            new_shared_links.append(lk)
    for lk in new_part["links"]:
        k = _link_key(lk)
        if k in part_links:
            repeat(part_links[k], lk)
            repeated_links += 1
        else:
            part_links[k] = lk
    new_part = {**new_part, "links": list(part_links.values())}
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
    new_shared = [n for n in one["shared"]["nodes"] if n["id"] not in have]
    records = {"nodes": len(new_part["nodes"]), "links": len(new_part["links"]),
               "triples": triples(new_part["nodes"] + new_shared, new_part["links"] + new_shared_links)
               + len(new_values),
               "completeness": completeness(doc, spec)}
    repeats = {"records": [{"given": a, "held": b} for a, b in sorted(same.items())], "links": repeated_links,
               "values": repeated_values}
    files = {f"parts/sources/{slug}.json": dump_canonical(graphparts._sorted(new_part)),
             "parts/shared.json": dump_canonical(graphparts._sorted(shared)),
             "rights.yaml": rights_text}
    if contributor:
        if not on:
            raise ScaleError("give the day of a credited contribution (on)")
        files[LEDGER] = _ledger_text(folder, contributor, slug, on, records)
    return {"source": sid, "slug": slug, "class": entry["class"], "files": files, "records": records,
            "shared_added": added, "shared_with_new_evidence": gained, "repeats": repeats, "conflicts": conflicts,
            "quotes": {"kept": sum(1 for ev in mine if any(isinstance(ev.get(f), str) and ev[f] for f in rights.TEXT_FIELDS)),
                       "withheld": sum(1 for ev in mine if rights.withheld(ev))},
            "warnings": len(rep.warnings)}


def write(result: dict, folder: str | Path) -> list[str]:
    folder = Path(folder)
    for rel, text in result["files"].items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text, encoding="utf-8")
    return sorted(result["files"])
