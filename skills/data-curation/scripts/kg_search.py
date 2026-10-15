"""KG retrieval index + query: DeepAsk for ask-mode at scale.

The #1 production worry is that the index returns the wrong slice and the answer is built on
thin context. DeepAsk is built for recall, provenance, and auditable ranking:

  1. Lexical node pass: SQLite FTS5 over node text + incident evidence.
  2. Lexical edge pass: SQLite FTS5 over edge evidence, returning both endpoints.
  3. Structural/numeric pass: label boosts and metric/property bounds over typed node props.
  4. Automatic broadening: token-level LIKE passes when initial coverage is thin or --broaden is set.
  5. Reciprocal Rank Fusion: multiple pass rankings are fused instead of trusting one route.
  6. Graph expansion: fused seeds expand to their k-hop neighborhood.
  7. Evidence reranking: evidence, citations, source papers, figures, and numeric props lift nodes.

`query` returns a relevant SUBGRAPH ({nodes, links}) plus coverage, pass, ranking, and evidence
metadata. Claude reads that and writes the answer with citations + figures. SQLite = "find fast
and wide"; DeepAsk = "fuse and rerank"; the graph = "reason over"; Claude = "write".
index.sqlite is a derived cache, regenerable from graph.json; it is never the source of truth.

Usage:
    python kg_search.py index <kg_dir>/graph.json --db <kg_dir>/index.sqlite
    python kg_search.py query --db <kg_dir>/index.sqlite \
        --terms "zeolite,ZSM-5,C5+ selectivity" --labels "Catalyst,PerformanceMetric" \
        --hops 1 --limit 80 [--metric selectivity --min-value 70] [--broaden] [--out hits.json]
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict, deque
from pathlib import Path


def load_graph(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    nodes = data.get("nodes", [])
    links = data.get("links")
    if links is None:
        links = data.get("edges", [])
    return nodes, links


def _fts_available(conn):
    try:
        conn.execute("CREATE VIRTUAL TABLE _fts_probe USING fts5(x)")
        conn.execute("DROP TABLE _fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


def _fts_query(terms):
    """Tokenize terms into alphanumeric words, OR them with prefix matching (high recall)."""
    toks = set()
    for t in terms:
        for w in re.split(r"[^A-Za-z0-9]+", t):
            if len(w) >= 2:
                toks.add(w.lower())
    return " OR ".join(f"{w}*" for w in sorted(toks))


def _node_text(n, incident_evidence):
    props = n.get("props", {}) or {}
    parts = [str(n.get("id", "")), str(n.get("label", "")), str(props.get("name", ""))]
    for k, v in props.items():
        if k.startswith("_"):
            if k == "_evidence":
                parts.append(" ".join(map(str, v)) if isinstance(v, list) else str(v))
            continue
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            parts.append(" ".join(str(x) for x in v if isinstance(x, (str, int, float))))
    parts.extend(incident_evidence)
    return " ".join(p for p in parts if p)


def cmd_index(args):
    nodes, links = load_graph(args.graph)
    db = Path(args.db)
    if db.exists():
        db.unlink()
    conn = sqlite3.connect(str(db))
    fts = _fts_available(conn)
    conn.executescript("""
      CREATE TABLE nodes(id TEXT PRIMARY KEY, label TEXT, name TEXT, props TEXT, degree INT);
      CREATE INDEX idx_nodes_label ON nodes(label);
      CREATE TABLE edges(id INTEGER PRIMARY KEY, type TEXT, source TEXT, target TEXT, evidence TEXT, props TEXT);
      CREATE INDEX idx_edges_src ON edges(source);
      CREATE INDEX idx_edges_tgt ON edges(target);
      CREATE INDEX idx_edges_type ON edges(type);
      CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
    """)
    inc, deg = defaultdict(list), defaultdict(int)
    for e in links:
        s, t = e.get("source"), e.get("target")
        deg[s] += 1
        deg[t] += 1
        ev = e.get("props", {}).get("_evidence")
        if ev:
            ev = " ".join(ev) if isinstance(ev, list) else str(ev)
            inc[s].append(ev)
            inc[t].append(ev)
    for n in nodes:
        nid = n.get("id")
        props = n.get("props", {}) or {}
        conn.execute("INSERT OR REPLACE INTO nodes VALUES(?,?,?,?,?)",
                     (nid, n.get("label"), str(props.get("name", "")),
                      json.dumps(props, ensure_ascii=False), deg.get(nid, 0)))
    for i, e in enumerate(links):
        ev = e.get("props", {}).get("_evidence")
        ev = " ".join(ev) if isinstance(ev, list) else (ev or "")
        conn.execute("INSERT INTO edges VALUES(?,?,?,?,?,?)",
                     (i, e.get("type"), e.get("source"), e.get("target"), ev,
                      json.dumps(e.get("props", {}), ensure_ascii=False)))
    if fts:
        conn.execute("CREATE VIRTUAL TABLE node_fts USING fts5(id UNINDEXED, text)")
        conn.execute("CREATE VIRTUAL TABLE edge_fts USING fts5(eid UNINDEXED, text)")
        for n in nodes:
            nid = n.get("id")
            conn.execute("INSERT INTO node_fts VALUES(?,?)", (nid, _node_text(n, inc.get(nid, []))))
        for i, e in enumerate(links):
            ev = e.get("props", {}).get("_evidence")
            ev = " ".join(ev) if isinstance(ev, list) else (ev or "")
            conn.execute("INSERT INTO edge_fts VALUES(?,?)", (i, f"{e.get('type', '')} {ev}"))
    conn.execute("INSERT OR REPLACE INTO meta VALUES('fts', ?)", ("1" if fts else "0",))
    conn.execute("INSERT OR REPLACE INTO meta VALUES('n_nodes', ?)", (str(len(nodes)),))
    conn.execute("INSERT OR REPLACE INTO meta VALUES('n_edges', ?)", (str(len(links)),))
    conn.commit()
    conn.close()
    print(json.dumps({"db": str(db), "fts5": fts, "n_nodes": len(nodes), "n_edges": len(links)}, indent=2))
    return 0


def _seeds_fts(conn, terms, table, idcol):
    q = _fts_query(terms)
    if not q:
        return []
    try:
        rows = conn.execute(f"SELECT {idcol} FROM {table} WHERE {table} MATCH ? LIMIT 3000", (q,)).fetchall()
        return [r[0] for r in rows]
    except sqlite3.OperationalError:
        return []


def _seeds_like(conn, terms, limit=3000):
    ids = set()
    for t in terms:
        t = t.strip()
        if not t:
            continue
        for (nid,) in conn.execute(
            "SELECT id FROM nodes WHERE name LIKE ? OR props LIKE ? LIMIT ?",
            (f"%{t}%", f"%{t}%", limit),
        ):
            ids.add(nid)
    return list(ids)


def _ordered_unique(items):
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _term_tokens(terms):
    toks = []
    for t in terms:
        for w in re.split(r"[^A-Za-z0-9]+", t):
            if len(w) >= 2:
                toks.append(w.lower())
    return _ordered_unique(toks)


def _node_row(conn, nid):
    r = conn.execute("SELECT id,label,props,degree FROM nodes WHERE id=?", (nid,)).fetchone()
    if not r:
        return None
    return {"id": r[0], "label": r[1], "props": json.loads(r[2]), "degree": r[3] or 0}


def _node_degree(conn, nid):
    r = conn.execute("SELECT degree FROM nodes WHERE id=?", (nid,)).fetchone()
    return r[0] if r else 0


def _node_label(conn, nid):
    r = conn.execute("SELECT label FROM nodes WHERE id=?", (nid,)).fetchone()
    return r[0] if r else None


def _seeds_edge_like(conn, terms, limit=3000):
    ids = []
    for t in terms:
        t = t.strip()
        if not t:
            continue
        rows = conn.execute(
            "SELECT source,target FROM edges WHERE evidence LIKE ? OR props LIKE ? OR type LIKE ? LIMIT ?",
            (f"%{t}%", f"%{t}%", f"%{t}%", limit),
        ).fetchall()
        for src, tgt in rows:
            ids.extend([src, tgt])
    return _ordered_unique(ids)


def _nodes_by_labels(conn, labels, limit=3000):
    if not labels:
        return []
    qm = ",".join("?" * len(labels))
    rows = conn.execute(
        f"SELECT id FROM nodes WHERE label IN ({qm}) ORDER BY degree DESC, id LIMIT ?",
        [*labels, limit],
    ).fetchall()
    return [r[0] for r in rows]


def _metric_nodes(conn, metric, min_value, max_value, labels=None, limit=3000):
    label_set = set(labels or [])
    metric_l = (metric or "").lower()
    hits = []
    for nid, label, props_s, degree in conn.execute("SELECT id,label,props,degree FROM nodes"):
        if label_set and label not in label_set:
            continue
        try:
            props = json.loads(props_s)
        except json.JSONDecodeError:
            continue
        metric_text = " ".join(
            str(props.get(k, "")) for k in ("metric", "name", "type", "unit")
        ).lower()
        if metric_l and metric_l not in metric_text:
            continue
        val = props.get("value")
        if min_value is not None or max_value is not None:
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                continue
            if min_value is not None and val < min_value:
                continue
            if max_value is not None and val > max_value:
                continue
        rank_val = val if isinstance(val, (int, float)) and not isinstance(val, bool) else 0
        hits.append((nid, rank_val, degree or 0))
    hits.sort(key=lambda x: (x[1], x[2], x[0]), reverse=True)
    return [nid for nid, _, _ in hits[:limit]]


def _add_pass(passes, name, strategy, nodes):
    ranked = _ordered_unique(nodes)
    if ranked:
        passes.append({"name": name, "strategy": strategy, "nodes": ranked})


def _rrf_scores(passes, k=60):
    scores = defaultdict(float)
    contributors = defaultdict(list)
    for p in passes:
        for rank, nid in enumerate(p["nodes"], 1):
            inc = 1.0 / (k + rank)
            scores[nid] += inc
            if len(contributors[nid]) < 5:
                contributors[nid].append({"pass": p["name"], "rank": rank})
    return scores, contributors


def _edge_props(raw):
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


def _source_paper_ids(props):
    vals = props.get("source_paper_ids") or props.get("source_paper_id") or []
    if isinstance(vals, str):
        return [vals]
    if isinstance(vals, list):
        return [str(v) for v in vals if v]
    return []


def _edge_text_value(props, key):
    v = props.get(key)
    if isinstance(v, list):
        return " ".join(str(x) for x in v if x)
    return str(v or "")


def _evidence_score(conn, nid, labels=None, metric=None):
    node = _node_row(conn, nid)
    if not node:
        return {"score": 0.0, "source_papers": [], "has_evidence": False, "has_citation": False,
                "publication_links": 0, "figure_links": 0, "numeric_props": 0}
    label_set = set(labels or [])
    score = 0.0
    source_papers = set()
    has_evidence = False
    has_citation = False
    publication_links = 0
    figure_links = 0
    numeric_props = 0

    if label_set and node["label"] in label_set:
        score += 0.35
    props = node["props"]
    if any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in props.values()):
        numeric_props += 1
        score += 0.30
    if metric and metric.lower() in " ".join(str(props.get(k, "")) for k in ("metric", "name", "type")).lower():
        score += 0.35

    rows = conn.execute(
        "SELECT type,source,target,evidence,props FROM edges WHERE source=? OR target=?",
        (nid, nid),
    ).fetchall()
    for etype, src, tgt, evidence, props_s in rows:
        eprops = _edge_props(props_s)
        evidence_text = evidence or _edge_text_value(eprops, "_evidence")
        citation_text = _edge_text_value(eprops, "_citation")
        if evidence_text:
            has_evidence = True
            score += 0.45
        if citation_text:
            has_citation = True
            score += 0.45
        for pid in _source_paper_ids(eprops):
            source_papers.add(pid)
        nb = tgt if src == nid else src
        nb_label = _node_label(conn, nb)
        if etype == "REPORTED_IN" or nb_label == "Publication":
            publication_links += 1
            score += 0.30
        if etype == "DEPICTS" or nb_label == "Figure":
            figure_links += 1
            score += 0.20
    if source_papers:
        score += min(0.80, 0.12 * len(source_papers))

    return {
        "score": score,
        "source_papers": sorted(source_papers),
        "has_evidence": has_evidence,
        "has_citation": has_citation,
        "publication_links": publication_links,
        "figure_links": figure_links,
        "numeric_props": numeric_props,
    }


def _expand_with_scores(conn, seed_scores, hops):
    keep = dict(seed_scores)
    distance = {nid: 0 for nid in seed_scores}
    frontier = deque((nid, 0) for nid in seed_scores)
    while frontier:
        nid, d = frontier.popleft()
        if d >= hops:
            continue
        for src, tgt in conn.execute("SELECT source,target FROM edges WHERE source=? OR target=?", (nid, nid)):
            for nb in (src, tgt):
                if nb == nid:
                    continue
                propagated = keep[nid] * (0.55 ** (d + 1))
                if propagated > keep.get(nb, 0.0):
                    keep[nb] = propagated
                if nb not in distance or d + 1 < distance[nb]:
                    distance[nb] = d + 1
                    frontier.append((nb, d + 1))
    return keep, distance


def _collect_subgraph(conn, ranked_rows):
    keep = {r["id"] for r in ranked_rows}
    out_nodes = []
    for r in ranked_rows:
        node = _node_row(conn, r["id"])
        if node:
            out_nodes.append({"id": node["id"], "label": node["label"], "props": node["props"]})
    out_edges = []
    for etype, src, tgt, props_s in conn.execute("SELECT type,source,target,props FROM edges"):
        if src in keep and tgt in keep:
            out_edges.append({"type": etype, "source": src, "target": tgt, "props": _edge_props(props_s)})
    return out_nodes, out_edges


def _summarize_evidence(rows):
    source_papers = set()
    for r in rows:
        source_papers.update(r["evidence"].get("source_papers", []))
    return {
        "nodes_with_evidence": sum(1 for r in rows if r["evidence"].get("has_evidence")),
        "nodes_with_citation": sum(1 for r in rows if r["evidence"].get("has_citation")),
        "publication_links": sum(r["evidence"].get("publication_links", 0) for r in rows),
        "figure_links": sum(r["evidence"].get("figure_links", 0) for r in rows),
        "numeric_nodes": sum(1 for r in rows if r["evidence"].get("numeric_props", 0)),
        "source_papers": sorted(source_papers),
    }


def cmd_query(args):
    conn = sqlite3.connect(str(args.db))
    row = conn.execute("SELECT v FROM meta WHERE k='fts'").fetchone()
    fts = bool(row and row[0] == "1")
    n_total = int((conn.execute("SELECT v FROM meta WHERE k='n_nodes'").fetchone() or ["0"])[0])
    terms = [t.strip() for t in (args.terms or "").split(",") if t.strip()]
    labels = [l.strip() for l in (args.labels or "").split(",") if l.strip()]
    notes = []
    passes = []

    if terms:
        if fts:
            _add_pass(passes, "lexical_nodes", "FTS5 over node text and incident evidence",
                      _seeds_fts(conn, terms, "node_fts", "id"))
            edge_nodes = []
            for eid in _seeds_fts(conn, terms, "edge_fts", "eid"):
                r = conn.execute("SELECT source,target FROM edges WHERE id=?", (eid,)).fetchone()
                if r:
                    edge_nodes.extend([r[0], r[1]])
            _add_pass(passes, "lexical_edge_evidence", "FTS5 over edge evidence", edge_nodes)
        else:
            notes.append("fts5 unavailable in this sqlite build; used LIKE fallback")
            _add_pass(passes, "lexical_like_nodes", "LIKE over node name and props",
                      _seeds_like(conn, terms))
            _add_pass(passes, "lexical_like_edges", "LIKE over edge evidence and props",
                      _seeds_edge_like(conn, terms))

    if args.metric:
        metric_nodes = _metric_nodes(conn, args.metric, args.min_value, args.max_value, labels)
        _add_pass(passes, "numeric_metric", "metric/property bounds over typed node props", metric_nodes)
        notes.append(f"numeric metric pass metric~'{args.metric}' "
                     f"[{args.min_value}, {args.max_value}] -> {len(metric_nodes)} seeds")

    if labels and not terms and not args.metric:
        _add_pass(passes, "structural_labels", "label-only structural retrieval",
                  _nodes_by_labels(conn, labels))
    elif labels:
        notes.append("labels used as ranking evidence; label-only flood pass skipped because terms/metric were present")

    seed_count = len({nid for p in passes for nid in p["nodes"]})
    broadened = False
    if terms and (args.broaden or seed_count < 3):
        broadened = True
        tokens = _term_tokens(terms)
        _add_pass(passes, "broadened_like_nodes", "token-level LIKE broadening over node props",
                  _seeds_like(conn, tokens))
        _add_pass(passes, "broadened_like_edges", "token-level LIKE broadening over edge evidence",
                  _seeds_edge_like(conn, tokens))
        notes.append("DeepAsk broadened retrieval with token-level LIKE because coverage was thin or --broaden was set")

    rrf_scores, contributors = _rrf_scores(passes)
    seeds = set(rrf_scores)
    expanded_scores, distances = _expand_with_scores(conn, rrf_scores, args.hops)

    ranked_rows = []
    for nid, retrieval_score in expanded_scores.items():
        evidence = _evidence_score(conn, nid, labels, args.metric)
        degree = _node_degree(conn, nid)
        final_score = retrieval_score + (0.03 * evidence["score"]) + min(degree, 100) * 0.0001
        ranked_rows.append({
            "id": nid,
            "score": final_score,
            "retrieval_score": retrieval_score,
            "evidence_score": evidence["score"],
            "degree": degree,
            "distance": distances.get(nid, 0),
            "contributors": contributors.get(nid, []),
            "evidence": evidence,
        })
    ranked_rows.sort(key=lambda r: (r["score"], r["retrieval_score"], r["evidence_score"], r["id"]), reverse=True)

    # --- provenance filters: keep only entities supported by a Publication matching access / type / year / journal ---
    access_set = {s.strip() for s in (args.access or "").split(",") if s.strip()} or None
    rt_set = {s.strip() for s in (args.record_type or "").split(",") if s.strip()} or None
    excl_rt = {s.strip() for s in (args.exclude_record_type or "").split(",") if s.strip()} or None
    jrn = [s.strip().lower() for s in (args.journal or "").split(",") if s.strip()] or None
    if access_set or rt_set or excl_rt or jrn or args.year_min is not None or args.year_max is not None:
        pub_meta = {}
        for pid, props_s in conn.execute("SELECT id,props FROM nodes WHERE label='Publication'"):
            p = _edge_props(props_s)
            doi = str(p.get("doi") or (pid.split(":", 1)[1] if ":" in pid else pid)).lower()
            pub_meta[doi] = p

        def paper_ok(doi):
            m = pub_meta.get(str(doi).lower())
            if not m:
                return False
            if access_set and m.get("access") not in access_set:
                return False
            if rt_set and m.get("record_type") not in rt_set:
                return False
            if excl_rt and m.get("record_type") in excl_rt:
                return False
            y = m.get("year")
            if args.year_min is not None and (not isinstance(y, int) or y < args.year_min):
                return False
            if args.year_max is not None and (not isinstance(y, int) or y > args.year_max):
                return False
            if jrn and not any(j in str(m.get("journal") or "").lower() for j in jrn):
                return False
            return True

        before = len(ranked_rows)
        ranked_rows = [r for r in ranked_rows if any(paper_ok(d) for d in r["evidence"].get("source_papers", []))]
        notes.append("provenance filter [access=%s record_type=%s exclude=%s year=[%s,%s] journal=%s] kept %d/%d nodes"
                     % (sorted(access_set) if access_set else None, sorted(rt_set) if rt_set else None,
                        sorted(excl_rt) if excl_rt else None, args.year_min, args.year_max, jrn,
                        len(ranked_rows), before))

    truncated = False
    if len(ranked_rows) > args.limit:
        ranked_rows = ranked_rows[:args.limit]
        truncated = True
        notes.append(f"DeepAsk ranked subgraph capped to {args.limit}; raise --limit to widen")

    out_nodes, out_edges = _collect_subgraph(conn, ranked_rows)
    conn.close()

    if not seeds:
        notes.append("no seeds matched - try different --terms, --labels, --metric, or --broaden")

    pass_summaries = [
        {"name": p["name"], "strategy": p["strategy"], "seeds": len(p["nodes"])}
        for p in passes
    ]
    ranking = [
        {k: r[k] for k in ("id", "score", "retrieval_score", "evidence_score", "degree", "distance", "contributors")}
        for r in ranked_rows[:25]
    ]

    result = {
        "algorithm": "DeepAsk/v1",
        "query_terms": terms,
        "labels": labels,
        "fts5": fts,
        "passes": pass_summaries,
        "ranking": ranking,
        "coverage": {
            "seeds": len(seeds),
            "subgraph_nodes": len(out_nodes),
            "subgraph_edges": len(out_edges),
            "graph_nodes_total": n_total,
            "hops": args.hops,
            "truncated": truncated,
            "broadened": broadened,
        },
        "evidence_summary": _summarize_evidence(ranked_rows),
        "notes": notes,
        "subgraph": {"nodes": out_nodes, "links": out_edges},
    }
    out = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"wrote {args.out} (seeds={len(seeds)}, nodes={len(out_nodes)}, edges={len(out_edges)}, fts5={fts})")
    else:
        print(out)
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("index")
    pi.add_argument("graph", type=Path)
    pi.add_argument("--db", required=True)
    pq = sub.add_parser("query")
    pq.add_argument("--db", required=True)
    pq.add_argument("--terms", default="")
    pq.add_argument("--labels", default="")
    pq.add_argument("--hops", type=int, default=1)
    pq.add_argument("--limit", type=int, default=80)
    pq.add_argument("--metric", default=None)
    pq.add_argument("--min-value", type=float, default=None)
    pq.add_argument("--max-value", type=float, default=None)
    pq.add_argument("--broaden", action="store_true")
    pq.add_argument("--out", default=None)
    pq.add_argument("--access", default=None, help="comma list; keep only entities from Publications with these access types (OA,OA+ND,Free-to-read,Paywalled)")
    pq.add_argument("--record-type", default=None, help="comma list; keep only these document types (article,preprint,conference-paper,thesis,report,review)")
    pq.add_argument("--exclude-record-type", default=None, help="comma list; drop these document types (e.g. review,editorial)")
    pq.add_argument("--year-min", type=int, default=None)
    pq.add_argument("--year-max", type=int, default=None)
    pq.add_argument("--journal", default=None, help="comma list; keep only Publications whose journal contains one of these (substring)")
    args = ap.parse_args()
    if args.cmd == "index":
        return cmd_index(args)
    if args.cmd == "query":
        return cmd_query(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
