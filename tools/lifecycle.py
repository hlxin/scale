"""Source lifecycle: retractions, withdrawals, expressions of concern and corrections, and what rests on them.

A source's publication status is derived, never typed by hand: it follows from the notice links that reach
it, a ``RETRACTS`` link from a Source (a notice is authoritative) or an ``UPDATES`` link with its
``update_type`` (documents without it simply have none). The most serious one decides::

    retracted              RETRACTS, scope full (or none stated)
    withdrawn              UPDATES withdrawal or removal
    partially_retracted    RETRACTS, scope partial (the parts in scope_locators)
    expression_of_concern  UPDATES expression_of_concern
    corrected              UPDATES correction, erratum or corrigendum
    updated                UPDATES addendum, clarification, new_version or new_edition
    current_or_unknown     no notice recorded: the source is current, or nobody has looked

``status_check`` (``{checked_on, checked_via, result}``) records only that someone looked for notices, when and
how; it never sets the status. A retracted (or withdrawn) source does not make its claims false: the
validator flags the records that rest on it and query answers leave out, by default, the rows that rest only
on such sources; no tool rewrites or deletes a record (COPE's guidance on retractions).

A partial retraction can also be recorded as a Dataset that INCLUDES the affected records, which the notice
RETRACTS. The dataset withdraws only what came from its own sources (the Sources it is REPORTED_IN and those its
evidence cites; failing both, the one Source the same notice retracts in part, such as the paper of a retracted
table): an included record's evidence from those sources counts as retracted, its evidence from any other
source does not. A record whose evidence names none of them rests on the dataset itself, one item of support
among its others.

Every function here reads link types by name, so it runs on documents of any schema version and finds
nothing on a document that records no notice.
"""

from __future__ import annotations

from collections import defaultdict

STATUSES = ("retracted", "withdrawn", "partially_retracted", "expression_of_concern", "corrected", "updated",
            "current_or_unknown")                         # most serious first
UNKNOWN = "current_or_unknown"
RETRACTED = frozenset({"retracted", "withdrawn"})          # what flags and excludes: the source is no longer part of the record
UPDATE_STATUS = {"withdrawal": "withdrawn", "removal": "withdrawn", "expression_of_concern": "expression_of_concern",
                 "correction": "corrected", "erratum": "corrected", "corrigendum": "corrected", "addendum": "updated",
                 "clarification": "updated", "new_version": "updated", "new_edition": "updated"}
LIFECYCLE_EDGES = ("RETRACTS", "UPDATES")
NOTICE_TARGETS = ("Source", "Dataset")
# records whose evidence cites a source without resting on its findings (a species, a person, the source itself):
# never flagged; shared kinds as the query engine counts them, plus the labels that need no evidence
UNFLAGGED = frozenset({"ChemicalSpecies", "Reaction", "Material", "Person", "Institution", "Source", "Dataset", "Software",
                       "Project"})


def _kinds(doc: dict, spec: dict | None) -> dict[str, str]:
    """Node id -> its label, or the kernel label it is_a among Source, Dataset and the unflagged kinds (a catalysis
    TimeSeries is a Dataset), as far as the schema says."""
    defs = (spec or {}).get("nodes") or {}
    out = {}
    for n in doc.get("nodes") or []:
        if isinstance(n, dict):
            lab = n.get("label")
            anc = [lab] + list((defs.get(lab) or {}).get("ancestors") or [])
            out[n.get("id")] = next((a for a in anc if a in UNFLAGGED), lab)
    return out


def statuses(doc: dict, spec: dict | None = None) -> dict[str, dict]:
    """Every Source or Dataset that a notice reaches or that records a ``status_check``: ``{id: {"status",
    "notices": [link ids], "status_check"?}}``. A source missing from the map is current_or_unknown, never checked.
    With the schema, a label that is_a Dataset counts as one."""
    nodes = {n.get("id"): n for n in doc.get("nodes") or [] if isinstance(n, dict)}
    label = _kinds(doc, spec)
    out: dict[str, dict] = {}
    for e in doc.get("links") or []:
        if not isinstance(e, dict) or e.get("type") not in LIFECYCLE_EDGES:
            continue
        src, tgt, p = e.get("source"), e.get("target"), e.get("props") or {}
        if label.get(src) != "Source" or label.get(tgt) not in NOTICE_TARGETS:
            continue                                   # a claim retracting a claim says nothing about a source
        if e["type"] == "RETRACTS":
            st = "partially_retracted" if p.get("scope") == "partial" else "retracted"
        else:
            st = UPDATE_STATUS.get(p.get("update_type"))
            if st is None:                             # an unknown update_type is the type check's error
                continue
        rec = out.setdefault(tgt, {"status": UNKNOWN, "notices": []})
        rec["notices"].append(e.get("id"))
        if STATUSES.index(st) < STATUSES.index(rec["status"]):
            rec["status"] = st
    for nid, n in nodes.items():
        chk = (n.get("props") or {}).get("status_check")
        if label[nid] in NOTICE_TARGETS and isinstance(chk, dict):
            out.setdefault(nid, {"status": UNKNOWN, "notices": []})["status_check"] = chk
    for rec in out.values():
        rec["notices"].sort(key=str)
    return out


def status_of(st: dict[str, dict], source: str | None) -> str:
    return (st.get(source) or {}).get("status", UNKNOWN)


def dataset_sources(doc: dict, st: dict[str, dict], spec: dict | None = None) -> dict[str, list[str]]:
    """Retracted (or withdrawn) Dataset id -> the Sources its data came from: the Sources it is REPORTED_IN and
    those its own evidence cites. Only when the graph names neither does a notice say it: the one Source that a
    notice retracting the dataset also retracts in part (the paper of a retracted table). A notice reaching
    several sources, or reaching a source only by UPDATES (a correction, an expression of concern), names
    none, and the dataset is then one item of support of its own: a retracted dataset never takes away the
    evidence of a source it cannot be traced to."""
    label = _kinds(doc, spec)
    gone = {d for d, r in st.items() if r["status"] in RETRACTED and label.get(d) == "Dataset"}
    out: dict[str, set[str]] = {d: set() for d in gone}
    links = [e for e in doc.get("links") or [] if isinstance(e, dict)]
    for e in links:
        if e.get("type") == "REPORTED_IN" and e.get("source") in gone and label.get(e.get("target")) == "Source":
            out[e["source"]].add(e["target"])
    for n in doc.get("nodes") or []:
        if isinstance(n, dict) and n.get("id") in gone:
            out[n["id"]] |= {x for x in _sources(n.get("props") or {}) if label.get(x) == "Source"}
    for d in gone:                                              # the dataset's own notice is not where its data came from
        out[d] -= {e.get("source") for e in links if e.get("target") == d and e.get("id") in st[d]["notices"]}
    partly: dict[str, set[str]] = defaultdict(set)              # notice Source -> the Sources it retracts in part
    for e in links:
        if (e.get("type") == "RETRACTS" and (e.get("props") or {}).get("scope") == "partial"
                and label.get(e.get("source")) == "Source" and label.get(e.get("target")) == "Source"):
            partly[e["source"]].add(e["target"])
    for d in gone:
        if not out[d]:
            named = set().union(*[partly.get(e.get("source"), set()) for e in links
                                  if e.get("target") == d and e.get("id") in st[d]["notices"]])
            if len(named) == 1:
                out[d] = named
    return {d: sorted(v, key=str) for d, v in out.items()}


def retracted_inclusions(doc: dict, st: dict[str, dict], spec: dict | None = None) -> dict[str, dict[str, list[str]]]:
    """Record id -> ``{retracted (or withdrawn) Dataset that INCLUDES it: [that dataset's own sources]}`` (the
    partial-retraction pattern). Each dataset retracts only the record's evidence from its own sources."""
    srcs = dataset_sources(doc, st, spec)
    out: dict[str, dict[str, list[str]]] = {}
    for e in doc.get("links") or []:
        if isinstance(e, dict) and e.get("type") == "INCLUDES" and e.get("source") in srcs:
            out.setdefault(e.get("target"), {})[e["source"]] = srcs[e["source"]]
    return {r: dict(sorted(by.items(), key=lambda kv: str(kv[0]))) for r, by in out.items()}


def retracted_by(st: dict[str, dict], incl: dict[str, dict], record: str | None, source: str | None) -> list[str]:
    """Why an evidence item (``record``'s evidence citing ``source``) no longer supports it: ``[source]`` when the
    source is retracted or withdrawn, else the retracted datasets that include the record and whose own sources
    hold that source; ``[]`` when it still stands."""
    if status_of(st, source) in RETRACTED:
        return [source]
    return [d for d, srcs in (incl.get(record) or {}).items() if source in srcs]


def unsourced_inclusions(incl: dict[str, dict], record: str | None, sources: set) -> list[str]:
    """The retracted datasets that include ``record`` although none of the sources its evidence cites is one of
    that dataset's own: the record then rests on that dataset itself, one item of support beside its evidence.
    Each dataset is judged by its own sources."""
    return [d for d, srcs in (incl.get(record) or {}).items() if not set(srcs) & set(sources)]


def _sources(props: dict) -> set[str]:
    return {ev.get("source") for ev in props.get("evidence") or [] if isinstance(ev, dict) and isinstance(ev.get("source"), str)}


def _produced_by(obj) -> set[str]:
    """The experiments named by ``produced_by`` in a props tree (value objects), evidence left out."""
    out: set[str] = set()
    if isinstance(obj, dict):
        if isinstance(obj.get("produced_by"), str) and "status" in obj:
            out.add(obj["produced_by"])
        for k, v in obj.items():
            if k != "evidence":
                out |= _produced_by(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _produced_by(v)
    return out


def input_edges(spec: dict | None) -> set[str]:
    """HAS_INPUT and the edge types that specialize it (FED_WITH, USES_ELECTRODE, …), as the schema declares them."""
    edges = (spec or {}).get("edges") or {}
    out = {"HAS_INPUT"}
    grew = True
    while grew:
        grew = False
        for name, d in edges.items():
            if name not in out and d.get("specializes") in out:
                out.add(name)
                grew = True
    return out


def resting(doc: dict, spec: dict | None = None, st: dict[str, dict] | None = None) -> dict[str, dict]:
    """The records that rest on retracted (or withdrawn) sources: ``{id: {"rests": "all" | "some", "sources":
    [retracted or withdrawn sources], "datasets": [retracted datasets], "dataset_sources": {retracted dataset:
    [the sources whose evidence of the record it retracts; empty when the record rests on the dataset itself]},
    "dataset_records": {retracted dataset: [the records it includes that this one rests on: itself, or the
    inputs and experiments it uses]}}}``.

    A record rests on the sources its own evidence cites and, one hop further, on those of the records it uses
    (HAS_INPUT and its specializations) and of the experiments its values name (``produced_by``). An evidence
    item counts as retracted when its source is retracted or withdrawn, or when a retracted dataset that
    includes its record comes from that source (each dataset retracts only its own sources' evidence); a record
    included in a retracted dataset none of whose sources its evidence cites rests on that dataset as one more
    item. Only the sources that are themselves retracted
    are named in ``sources``. Records that cite a source without resting on its findings (species, people,
    sources, datasets; links between them, such as a byline) are not flagged; nor are the notice links
    themselves."""
    st = statuses(doc, spec) if st is None else st
    if not any(r["status"] in RETRACTED for r in st.values()):
        return {}
    nodes = {n.get("id"): n for n in doc.get("nodes") or [] if isinstance(n, dict)}
    label = _kinds(doc, spec)
    links = [e for e in doc.get("links") or [] if isinstance(e, dict)]
    incl = retracted_inclusions(doc, st, spec)
    hop_types = input_edges(spec)
    hops: dict[str, set[str]] = defaultdict(set)
    for e in links:
        if e.get("type") in hop_types and label.get(e.get("target")) not in UNFLAGGED:
            hops[e.get("source")].add(e.get("target"))

    def atoms(rid: str, props: dict) -> set[tuple[str, str, str, str]]:
        """(source or dataset, how, dataset, record) per item of support: how is 'source' (a retracted source),
        'dataset' (retracted with a dataset that includes the record) or 'ok'; record is the record whose evidence
        it is (the record itself, or the input or experiment it uses)."""
        srcs = _sources(props)
        out = set()
        for s in srcs:
            why = retracted_by(st, incl, rid, s)
            if not why:
                out.add((s, "ok", "", rid))
            elif status_of(st, s) in RETRACTED:
                out.add((s, "source", "", rid))
            else:
                out |= {(s, "dataset", d, rid) for d in why}
        out |= {(d, "dataset", d, rid) for d in unsourced_inclusions(incl, rid, srcs)}
        return out

    own = {nid: atoms(nid, n.get("props") or {}) for nid, n in nodes.items()}
    out: dict[str, dict] = {}
    records = [(nid, n.get("props") or {}, label[nid] in UNFLAGGED) for nid, n in nodes.items()]
    records += [(e.get("id"), e.get("props") or {},
                 e.get("type") in LIFECYCLE_EDGES or e.get("type") == "REPORTED_IN"
                 or (label.get(e.get("source")) in UNFLAGGED and label.get(e.get("target")) in UNFLAGGED)) for e in links]
    for rid, props, skip in records:
        if skip or not isinstance(rid, str):
            continue
        a = set(own.get(rid) or atoms(rid, props))
        for other in hops.get(rid, set()) | _produced_by(props):
            if other in own and other != rid:
                a |= own[other]
        if not any(how != "ok" for _, how, _, _ in a):
            continue
        datasets = sorted({d for _, how, d, _ in a if how == "dataset"}, key=str)
        out[rid] = {"rests": "all" if all(how != "ok" for _, how, _, _ in a) else "some",
                    "sources": sorted({k for k, how, _, _ in a if how == "source"}, key=str),
                    "datasets": datasets,
                    "dataset_sources": {d: sorted({k for k, how, dd, _ in a if how == "dataset" and dd == d and k != d}, key=str)
                                        for d in datasets},
                    "dataset_records": {d: sorted({r for _, how, dd, r in a if how == "dataset" and dd == d}, key=str)
                                        for d in datasets}}
    return out


def summary(st: dict[str, dict], rest: dict[str, dict]) -> dict | None:
    """Counts for the validate and conformance summaries; None when the document records no notice and no check
    (so that the report of every such document stays as it was)."""
    if not st:
        return None
    by = {s: sum(1 for r in st.values() if r["status"] == s) for s in STATUSES if s != UNKNOWN}
    out = {"sources_by_status": {k: v for k, v in by.items() if v},
           "sources_checked": sum(1 for r in st.values() if "status_check" in r),
           "rests_on_retracted_source": sum(1 for r in rest.values() if r["rests"] == "all"),
           "partially_rests_on_retracted_source": sum(1 for r in rest.values() if r["rests"] == "some")}
    return out
