"""Deterministic merge: per-paper fragments -> canonical graph.json (NetworkX node-link JSON).

Why a script (not Claude inline): entity resolution + provenance accumulation must be
DETERMINISTIC and IDEMPOTENT, so a resumed or re-run build reproduces identical output. That
is what makes resume safe at the 1000-3000+ paper scale this skill targets.

Pipeline role:
  fragments/paper_*.json  --(this)-->  graph.json  +  manifest.json  +  alias_candidates.json

Entity resolution is two-stage:
  1. DETERMINISTIC (always): domain-entity node ids are GLOBAL ("Catalyst:co-zsm-5"); the same
     id from two papers is ONE node whose provenance lists both. Figure/Publication nodes are
     namespaced per paper. Every origin node gets a REPORTED_IN edge to its Publication, and
     in-corpus citations become CITES edges  ->  "citing is easy".
  2. ALIAS PASS (optional): pass --alias-map alias_map.json (produced by the Claude alias-review
     subagent, user-approved) to additionally collapse near-duplicate ids ("Catalyst:cozsm5" ->
     "Catalyst:co-zsm-5"). Applied deterministically -> re-running with the same map is idempotent.

After merging, candidate near-duplicate clusters are written to alias_candidates.json (blocked by
label + name prefix, scored by difflib) for the alias-review pass. At scale the reviewer only
looks at these clusters, never the whole node set.

The output graph.json is plain JSON your PI can read AND is loadable in one line:
  import json, networkx as nx;  G = nx.node_link_graph(json.load(open("graph.json")))

Usage (data-curation run: fragments in .scripts/<topic>/kg/<name>/, graph in publications/<topic>/kg/<name>/):
    python merge_graph.py --topic co2rr --name co2rr-catalysts [--alias-map]   # accepted papers only (accepted.txt)
Publications are enriched from publications/papers.db (title, year, venue, authors, access, license, doc type,
Topic A/B/C), so ask-mode and the viewer can filter by them. Also writes hubs.json (highest-degree nodes per label)
for the semantic alias pass.
Legacy:
    python merge_graph.py <kg_dir> [--alias-map <kg_dir>/alias_map.json]
    python merge_graph.py --fragments <dir> --out <kg_dir>
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

PROV_LIST_KEYS = {"_evidence", "_citation", "source_paper_ids", "source_figure", "name_variants"}
SIM_THRESHOLD = 0.84


def atomic_write(path: Path, text: str):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def norm_name(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def merge_props(dst: dict, src: dict, paper_id: str):
    for k, v in (src or {}).items():
        if k in PROV_LIST_KEYS or isinstance(v, list):
            cur = dst.get(k)
            cur = [] if cur is None else (cur if isinstance(cur, list) else [cur])
            for item in (v if isinstance(v, list) else [v]):
                if item not in cur:
                    cur.append(item)
            dst[k] = cur
        elif k not in dst or dst.get(k) in (None, ""):
            dst[k] = v
    if paper_id:
        spi = dst.setdefault("source_paper_ids", [])
        if paper_id not in spi:
            spi.append(paper_id)


def fig_id(nid, paper_id):
    """Namespace a Figure id under its paper: Figure:<oldns>:<short> -> Figure:<paper_id>:<short>.
    Re-namespaces (not just prepends) so a numeric-namespaced fragment id becomes DOI-namespaced."""
    if isinstance(nid, str) and nid.startswith("Figure:"):
        rest = nid[len("Figure:"):]
        short = rest.split(":", 1)[1] if ":" in rest else rest
        return f"Figure:{paper_id}:{short}"
    return nid


def normalize_doi(s):
    s = (s or "").strip().lower()
    for pre in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        if s.startswith(pre):
            s = s[len(pre):]
    return s.strip().strip("/")


def load_meta_map(path, key):
    """Load a list-of-dicts (or dict-of-dicts) JSON into {str(item[key]): item}."""
    if not path:
        return {}
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    items = raw.values() if isinstance(raw, dict) else raw
    out = {}
    for it in items:
        if isinstance(it, dict) and it.get(key) is not None:
            out[str(it[key])] = it
    return out


def load_alias_map(path):
    if not path:
        return {}
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    amap = {}
    if isinstance(raw, dict) and "merges" in raw:
        for m in raw["merges"]:
            canon = m.get("canonical")
            for a in m.get("aliases", []):
                if canon and a:
                    amap[a] = canon
    elif isinstance(raw, dict):
        amap = {k: v for k, v in raw.items() if isinstance(v, str)}

    def resolve(x):
        seen = set()
        while x in amap and x not in seen:
            seen.add(x)
            x = amap[x]
        return x

    return {k: resolve(k) for k in amap}


def paper_scoped(nid):
    """Entities that exist only inside one paper carry the paper id in the slug ('PerformanceMetric:55-fe-...'):
    distinct by construction, never alias candidates."""
    slug = str(nid).split(":", 1)[-1]
    return bool(re.match(r"^\d+-", slug))


def find_clusters(nodes):
    """Near-duplicate domain-entity ids, blocked by label + name prefix, scored by difflib."""
    buckets = defaultdict(list)
    for n in nodes.values():
        label = n["label"]
        if label in ("Figure", "Publication") or paper_scoped(n["id"]):
            continue
        nm = norm_name(n["props"].get("name") or n["id"].split(":")[-1])
        if not nm:
            continue
        buckets[(label, nm[:3])].append(
            (n["id"], nm, n["props"].get("name"), n["props"].get("source_paper_ids", []))
        )
    clusters = []
    for (label, _), items in buckets.items():
        if len(items) < 2:
            continue
        parent = list(range(len(items)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            parent[find(a)] = find(b)

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                ni, nj = items[i][1], items[j][1]
                if ni == nj or ((ni in nj or nj in ni) and min(len(ni), len(nj)) >= 4):
                    union(i, j)
                elif SequenceMatcher(None, ni, nj).ratio() >= SIM_THRESHOLD:
                    union(i, j)
        groups = defaultdict(list)
        for i in range(len(items)):
            groups[find(i)].append(items[i])
        for g in groups.values():
            if len(g) >= 2:
                clusters.append({
                    "label": label,
                    "members": [{"id": x[0], "name": x[2], "source_paper_ids": x[3]} for x in g],
                })
    clusters.sort(key=lambda c: (-len(c["members"]), c["label"]))
    return clusters


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kg_dir", type=Path, nargs="?")
    ap.add_argument("--fragments", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--alias-map", type=Path, nargs="?", const=None, default=None,
                    help="apply an approved alias map (run mode: .scripts/<topic>/kg/<name>/alias_map.json)")
    ap.add_argument("--id-map", type=Path, default=None,
                    help="JSON {paper_id -> {doi,...}} to backfill DOIs for fragments lacking paper.doi")
    ap.add_argument("--enrich", type=Path, default=None,
                    help="JSON {doi -> {access,record_type,journal,year,source,...}} to enrich Publications")
    ap.add_argument("--topic", default=None)
    ap.add_argument("--name", default=None)
    ap.add_argument("--project", default=None)
    ap.add_argument("--all-fragments", action="store_true", help="run mode: merge every valid fragment, not only accepted")
    args = ap.parse_args()

    run = None
    allowed = None
    work_dir = None
    db_meta = {}
    if args.topic and args.name:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from _kgcommon import Run, publication_meta
        run = Run(args.project, args.topic, args.name)
        kg_dir, frag_dir, work_dir = run.out, run.frag, run.work
        if run.accepted.exists() and not args.all_fragments:
            allowed = {x.strip() for x in run.accepted.read_text().split() if x.strip()}
        if args.alias_map is None and (run.work / "alias_map.json").exists() and "--alias-map" in sys.argv:
            args.alias_map = run.work / "alias_map.json"
        db_meta = publication_meta(run.root)
        if args.id_map is None:
            wl = {str(p["paper_id"]): p for p in run.papers().values()}
        else:
            wl = {}
    else:
        kg_dir = args.out or args.kg_dir
        frag_dir = args.fragments or (kg_dir / "fragments" if kg_dir else None)
        wl = {}
    if run is None:
        work_dir = kg_dir
    if not kg_dir or not frag_dir or not frag_dir.exists():
        print(f"FAIL: fragments dir not found ({frag_dir})", file=sys.stderr)
        return 2

    topic = ""
    sp = kg_dir / "schema.json"
    if sp.exists():
        try:
            topic = json.loads(sp.read_text(encoding="utf-8-sig")).get("topic", "")
        except Exception:
            pass

    amap = load_alias_map(args.alias_map)
    id_map = load_meta_map(args.id_map, "paper_id")                        # numeric paper_id -> {doi,...}
    enrich = {normalize_doi(k): v for k, v in load_meta_map(args.enrich, "doi").items()}  # doi -> metadata
    ENRICH_FIELDS = ("access", "record_type", "journal", "year", "source")

    def canon(x):
        return amap.get(x, x)

    nodes, edges = {}, {}
    doi_to_pub, pending_cites = {}, []

    def add_node(nid, label, props, pid):
        nid = canon(nid)
        if nid not in nodes:
            nodes[nid] = {"id": nid, "label": label, "props": {}}
        props = {k: v for k, v in (props or {}).items() if k != "source_paper_ids"}
        merge_props(nodes[nid]["props"], props, pid)

    def add_edge(et, s, t, props, pid):
        s, t = canon(s), canon(t)
        key = (et, s, t)
        if key not in edges:
            edges[key] = {"type": et, "source": s, "target": t, "props": {}}
        props = {k: v for k, v in (props or {}).items() if k != "source_paper_ids"}
        merge_props(edges[key]["props"], props, pid)

    frag_files = sorted(frag_dir.glob("paper_*.json"), key=lambda p: p.name)
    if allowed is not None:
        frag_files = [f for f in frag_files if f.stem.replace("paper_", "") in allowed]
    n_papers = 0
    for ff in frag_files:
        try:
            frag = json.loads(ff.read_text(encoding="utf-8-sig"))
        except Exception as e:
            print(f"WARN: skip unreadable {ff.name}: {e}", file=sys.stderr)
            continue
        pid = str(frag.get("paper_id") or ff.stem.replace("paper_", ""))
        n_papers += 1
        paper = frag.get("paper", {}) or {}
        # Canonical paper identity = DOI (from the fragment, else backfilled via --id-map);
        # fall back to a stable synthetic id only if a paper genuinely has no DOI.
        doi = normalize_doi(paper.get("doi") or (id_map.get(pid, {}) or {}).get("doi") or (wl.get(pid) or {}).get("doi") or "")
        pkey = doi or ("nodoi-" + pid)
        pub_id = f"Publication:{pkey}"
        pub_props = {k: paper[k] for k in ("title", "year", "journal", "venue", "authors") if k in paper}
        pub_props.pop("abstract", None)
        pub_props["paper_id"] = pkey
        if doi:
            pub_props["doi"] = doi
        if pkey != pid:
            pub_props["internal_id"] = pid          # numeric id (figure FILES are named by it)
        meta = enrich.get(doi) if doi else None
        if meta:
            for k in ENRICH_FIELDS:
                if meta.get(k) is not None:
                    pub_props.setdefault(k, meta[k])
        dbm = (db_meta.get(doi) if doi else None) or db_meta.get(pid)
        if dbm:   # the paper index is the authority for bibliographic data
            for k in ("title", "year", "journal", "venue", "authors", "record_type", "access", "license", "url",
                      "topics", "citations"):
                if dbm.get(k) not in (None, "", []):
                    pub_props[k] = dbm[k]
        add_node(pub_id, "Publication", pub_props, pkey)
        if doi:
            doi_to_pub[doi] = pub_id
        for cd in paper.get("cites_dois", []) or []:
            if isinstance(cd, str) and cd.strip():
                pending_cites.append((pub_id, normalize_doi(cd)))
        for n in frag.get("nodes", []) or []:
            nid, label = n.get("id"), n.get("label")
            if not nid or not label:
                continue
            if label == "Figure":
                nid = fig_id(nid, pkey)
            add_node(nid, label, n.get("props", {}) or {}, pkey)
            if label != "Publication":
                add_edge("REPORTED_IN", nid, pub_id, {}, pkey)
        for e in frag.get("edges", []) or []:
            et = e.get("type")
            s = e.get("source") or e.get("start")
            t = e.get("target") or e.get("end")
            if not et or not s or not t:
                continue
            s, t = fig_id(s, pkey), fig_id(t, pkey)
            add_edge(et, s, t, dict(e.get("props", {}) or {}), pkey)

    for src_pub, cited in pending_cites:
        tgt = doi_to_pub.get(cited)
        if tgt and tgt != src_pub:
            add_edge("CITES", src_pub, tgt, {"cited_doi": cited}, "")

    node_ids = set(nodes)
    kept, dropped = [], 0
    for e in edges.values():
        if e["source"] in node_ids and e["target"] in node_ids:
            kept.append(e)
        else:
            dropped += 1

    graph = {
        "directed": True,
        "multigraph": True,
        "graph": {"topic": topic, "n_papers": n_papers, "schema": "schema.json"},
        "nodes": [nodes[k] for k in sorted(nodes)],
        "links": sorted(kept, key=lambda e: (e["type"], e["source"], e["target"])),
    }
    atomic_write(kg_dir / "graph.json", json.dumps(graph, ensure_ascii=False, indent=2))

    by_label, by_type = {}, {}
    for n in graph["nodes"]:
        by_label[n["label"]] = by_label.get(n["label"], 0) + 1
    for e in graph["links"]:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    manifest = {
        "topic": topic, "n_papers": n_papers,
        "n_nodes": len(graph["nodes"]), "n_edges": len(graph["links"]),
        "nodes_by_label": dict(sorted(by_label.items())),
        "edges_by_type": dict(sorted(by_type.items())),
        "master_file": "graph.json", "format": "networkx node-link JSON",
        "alias_map_applied": bool(amap),
        "schema_version": (json.loads(sp.read_text(encoding="utf-8-sig")).get("version") if sp.exists() else None),
    }
    atomic_write(kg_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    clusters = find_clusters(nodes)
    atomic_write(work_dir / "alias_candidates.json",
                 json.dumps({"n_clusters": len(clusters), "clusters": clusters[:500]}, ensure_ascii=False, indent=2))
    deg = Counter()
    for e in graph["links"]:
        if e["type"] != "REPORTED_IN":
            deg[e["source"]] += 1
            deg[e["target"]] += 1
    hubs = defaultdict(list)
    for n in sorted(graph["nodes"], key=lambda n: -deg[n["id"]]):
        if n["label"] in ("Publication", "Figure") or paper_scoped(n["id"]) or len(hubs[n["label"]]) >= 25:
            continue
        hubs[n["label"]].append({"id": n["id"], "name": n["props"].get("name"), "degree": deg[n["id"]],
                                 "n_papers": len(n["props"].get("source_paper_ids") or [])})
    atomic_write(work_dir / "hubs.json", json.dumps(hubs, ensure_ascii=False, indent=2))

    print(f"merged {n_papers} fragments -> {len(graph['nodes'])} nodes, {len(graph['links'])} edges "
          f"({dropped} dangling dropped; alias_map={'yes' if amap else 'no'})")
    print(f"  nodes_by_label: {manifest['nodes_by_label']}")
    print(f"  edges_by_type:  {manifest['edges_by_type']}")
    print(f"  alias candidate clusters: {len(clusters)} (review alias_candidates.json + hubs.json)")
    print(f"wrote: {kg_dir / 'graph.json'} | {kg_dir / 'manifest.json'} | {work_dir / 'alias_candidates.json'} | "
          f"{work_dir / 'hubs.json'}")
    if run is not None:
        run.update_state(merged_at=__import__('_kgcommon').now_iso(), graph_counts={"nodes": len(graph["nodes"]),
                         "edges": len(graph["links"]), "papers": n_papers, "alias_map": bool(amap)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
