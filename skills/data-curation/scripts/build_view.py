"""Render a (sub)graph into a SELF-CONTAINED interactive HTML (a single shareable file).

Cytoscape.js is INLINED (from assets/cytoscape.min.js if vendored, else a CDN <script> with a
warning) and figures are BASE64-EMBEDDED, so the .html needs neither internet nor the figures/
folder. Share the one file and it just works.

Legibility:
  - node COLOUR encodes the type (label); the label (the entity NAME) appears as you zoom in; click
    a node for its full type + id + props + figure in the side panel.
  - edges are COLOURED by their relationship TYPE (the schema's edge types, e.g. HAS_METRIC, CATALYZES);
    the type also shows on hover, on the highlighted neighbourhood (click a node), and on deep zoom.
    Two legends: node types + relationship (edge) types.
  - a LIVE FILTER panel (checkboxes) shows/hides nodes by access (OA / Paywalled / ...), record_type
    (research / review / ...), and node type — right in the page, no re-render needed.

Modes:
  python build_view.py <kg>/graph.json --out v.html                      # whole graph (capped)
  python build_view.py --subgraph hits.json --out answer.html --kg-root <kg>   # ask-mode subgraph
  python build_view.py <kg>/graph.json --out schema.html --schema        # SCHEMA/meta-overview (Label->Label)
  python build_view.py <kg>/graph.json --out v.html --access OA          # (also pre-filterable via CLI)
"""
import argparse
import base64
import html
import json
import os
import sys
from collections import defaultdict, deque, Counter
from pathlib import Path

PALETTE = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948",
           "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac", "#86bcb6", "#d37295",
           "#8cd17d", "#b6992d", "#499894", "#d4a6c8", "#79706e", "#fabfd2"]
CDN = "https://cdn.jsdelivr.net/npm/cytoscape@3.30.2/dist/cytoscape.min.js"

# Edges are coloured by their ACTUAL edge TYPE (the schema's relationship types, e.g. HAS_METRIC,
# CATALYZES), assigned at render time from the types present — nothing domain-specific is hardcoded.
DEFAULT_EDGE_COLOR = "#c9ccd1"

TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><title>__TITLE__</title>
__LIB__
<style>
 body{margin:0;font-family:system-ui,Arial,sans-serif;display:flex;height:100vh}
 #cy{flex:1;height:100%;background:#fafafa}
 #side{width:370px;border-left:1px solid #ddd;padding:14px;overflow:auto;font-size:13px}
 #side h2{font-size:15px;margin:.2em 0} .leg{margin:.4em 0}
 .leg b{font-size:11px;color:#555;text-transform:uppercase;letter-spacing:.03em}
 .leg span{display:inline-block;margin:2px 8px 2px 0;white-space:nowrap;font-size:12px}
 .leg label{display:inline-block;margin:1px 8px 1px 0;font-size:12px;white-space:nowrap;cursor:pointer}
 .leg i{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:4px;vertical-align:middle}
 .leg i.bar{width:16px;height:3px;border-radius:2px}
 .flt{background:#f6f8f7;border:1px solid #e3e6e4;border-radius:8px;padding:8px 10px;margin:.5em 0}
 .flt .row{margin:.45em 0} .flt a{font-size:11px;color:#0b6e4f;cursor:pointer;margin-left:6px}
 .flt label{display:inline-block;white-space:nowrap;margin:1px 12px 2px 0;font-size:12px;cursor:pointer}
 .flt input{vertical-align:-1px;margin-right:3px}
 .k{color:#666} img{max-width:100%;border:1px solid #ccc;margin-top:6px;border-radius:4px}
 pre{white-space:pre-wrap;word-break:break-word;background:#f4f4f4;padding:8px;border-radius:6px;font-size:11px}
</style></head><body>
<div id="cy"></div>
<div id="side"><h2>__TITLE__</h2>
<div class="leg"><b>Node types</b><br>__LEGEND__</div>
<div class="leg"><b>Relationships</b><br>__EDGELEGEND__</div>
__FILTERS__
<p class="k">__SUBTITLE__ &middot; click a node to trace its links &middot; scroll to zoom (labels &amp; relationship names appear as you zoom in)</p>
<div id="info"><em>Click a node.</em></div></div>
<script>
const ELEMENTS=__ELEMENTS__;
const cy=cytoscape({container:document.getElementById('cy'),elements:ELEMENTS,minZoom:0.06,maxZoom:4.5,wheelSensitivity:0.25,
 style:[
  {selector:'node',style:{'background-color':'data(color)','label':'data(name)','font-size':10,'min-zoomed-font-size':__NMINZOOM__,'width':'data(sz)','height':'data(sz)','text-wrap':'wrap','text-max-width':120,'text-valign':'bottom','text-margin-y':2,'color':'#1a1a1a','text-background-color':'#fff','text-background-opacity':0.78,'text-background-shape':'roundrectangle','text-background-padding':2,'border-width':0.5,'border-color':'#fff'}},
  {selector:'edge',style:{'width':'data(ew)','line-color':'data(ecolor)','curve-style':'straight','opacity':0.5,'label':'data(label)','font-size':8,'min-zoomed-font-size':__EMINZOOM__,'color':'#777','text-rotation':'autorotate','text-background-color':'#fff','text-background-opacity':0.8,'text-background-padding':1}},
  {selector:'node:selected',style:{'border-width':3,'border-color':'#111','min-zoomed-font-size':0,'font-size':13,'z-index':9999}},
  {selector:'.faded',style:{'opacity':0.09,'text-opacity':0.04}},
  {selector:'.hiEdge',style:{'opacity':0.95,'width':2.2,'min-zoomed-font-size':0,'color':'#333','z-index':9000}}
 ],layout:{name:'cose',animate:false,randomize:true,nodeRepulsion:__REPULSION__,idealEdgeLength:__EDGELEN__,edgeElasticity:60,nodeOverlap:36,componentSpacing:160,gravity:0.05,numIter:2000,coolingFactor:0.98,fit:true,padding:26}});
function fitAll(){try{cy.fit(cy.nodes(':visible'),26);}catch(e){}}
cy.one('layoutstop',fitAll);setTimeout(fitAll,80);setTimeout(fitAll,400);window.addEventListener('resize',fitAll);
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function clearHi(){cy.elements().removeClass('faded').removeClass('hiEdge');}
cy.on('tap','node',e=>{const n=e.target,d=n.data();
 clearHi();cy.elements().addClass('faded');n.removeClass('faded');n.neighborhood().removeClass('faded');n.connectedEdges().removeClass('faded').addClass('hiEdge');
 let h=`<h2>${esc(d.name)}</h2><p class="k"><b>${esc(d.label)}</b> &middot; <code>${esc(d.id)}</code> &middot; ${n.degree()} links</p>`;
 if(d.figure)h+=`<img src="${d.figure}"/>`;
 h+=`<pre>${esc(JSON.stringify(d.props,null,2))}</pre>`;document.getElementById('info').innerHTML=h;});
cy.on('tap','edge',e=>{const d=e.target.data();document.getElementById('info').innerHTML=`<h2>${esc(d.label)}</h2><p class="k">relationship</p><pre>${esc(JSON.stringify(d.props,null,2))}</pre>`;});
cy.on('tap',e=>{if(e.target===cy){clearHi();document.getElementById('info').innerHTML='<em>Click a node.</em>';}});
// ---- live filters ----
function readSet(cls){return new Set([...document.querySelectorAll('input.'+cls+':checked')].map(x=>x.value));}
function applyFilter(){
 const A=readSet('fA'),R=readSet('fR'),T=readSet('fT');
 const useA=document.querySelectorAll('input.fA').length>0;
 const useR=document.querySelectorAll('input.fR').length>0;
 const useT=document.querySelectorAll('input.fT').length>0;
 const vis={};
 cy.batch(()=>{
  cy.nodes().forEach(n=>{const d=n.data();
   const acc=(d.acc&&d.acc.length)?d.acc:['n/a'], rt=(d.rt&&d.rt.length)?d.rt:['n/a'];
   const ok=(!useA||acc.some(a=>A.has(a)))&&(!useR||rt.some(r=>R.has(r)))&&(!useT||T.has(d.label));
   vis[d.id]=ok; n.style('display',ok?'element':'none');});
  cy.edges().forEach(e=>{const v=vis[e.data('source')]&&vis[e.data('target')];e.style('display',v?'element':'none');});
 });
 document.getElementById('viscount').textContent=Object.values(vis).filter(Boolean).length;
}
function setAll(cls,on){document.querySelectorAll('input.'+cls).forEach(x=>x.checked=on);applyFilter();}
document.querySelectorAll('input.fA,input.fR,input.fT').forEach(x=>x.addEventListener('change',applyFilter));
</script></body></html>"""


def load(path):
    d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(d, dict) and isinstance(d.get("subgraph"), dict):
        d = d["subgraph"]
    nodes = d.get("nodes", [])
    links = d.get("links")
    if links is None:
        links = d.get("edges", [])
    return nodes, links


def build_schema(nodes, links):
    """Meta-graph: one node per TYPE (label), edges aggregated per (srcLabel, tgtLabel) type-pair.
    Renders the whole KG's schema (how the types relate) on a few dozen nodes."""
    count = Counter(n.get("label", "Node") for n in nodes)
    id2lab = {n["id"]: n.get("label", "Node") for n in nodes}
    pair = defaultdict(Counter)
    for l in links:
        sl, tl, t = id2lab.get(l["source"]), id2lab.get(l["target"]), l.get("type")
        if sl and tl and t:
            pair[(sl, tl)][t] += 1
    mnodes = [{"id": "L:" + lab, "label": lab, "props": {"instances": c}} for lab, c in count.items()]
    mlinks = []
    for (sl, tl), types in pair.items():
        dominant, _ = types.most_common(1)[0]
        mlinks.append({"source": "L:" + sl, "target": "L:" + tl, "type": dominant,
                       "props": {"count": sum(types.values()), "n_types": len(types),
                                 "relationship_types": dict(types.most_common())}})
    return mnodes, mlinks


def bfs(adj, seeds, hops):
    seen = set(seeds)
    fr = deque((s, 0) for s in seeds)
    while fr:
        nid, dd = fr.popleft()
        if dd >= hops:
            continue
        for nb in adj.get(nid, ()):
            if nb not in seen:
                seen.add(nb)
                fr.append((nb, dd + 1))
    return seen


def select(nodes, links, a):
    adj = defaultdict(set)
    for l in links:
        adj[l["source"]].add(l["target"])
        adj[l["target"]].add(l["source"])
    ids = [n["id"] for n in nodes]
    if a.focus_node:
        keep = bfs(adj, [a.focus_node], a.neighbors)
    elif a.focus_label:
        keep = bfs(adj, [n["id"] for n in nodes if n.get("label") == a.focus_label], 1)
    elif a.query:
        q = a.query.lower()
        keep = bfs(adj, [n["id"] for n in nodes if q in json.dumps(n, ensure_ascii=False).lower()], 1)
    else:
        keep = set(ids)
    trunc = False
    if len(keep) > a.max_nodes:
        deg = {i: len(adj.get(i, ())) for i in keep}
        keep = set(sorted(keep, key=lambda x: deg.get(x, 0), reverse=True)[:a.max_nodes])
        trunc = True
    return keep, trunc


def datauri(p):
    try:
        return "data:image/png;base64," + base64.b64encode(Path(p).read_bytes()).decode()
    except Exception:
        return None


def _checks(cls, values):
    return " ".join(
        '<label><input type="checkbox" class="%s" value="%s" checked> %s</label>'
        % (cls, html.escape(str(v)), html.escape(str(v))) for v in values)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("graph", type=Path, nargs="?")
    ap.add_argument("--subgraph", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--title", default="Knowledge Graph")
    ap.add_argument("--focus-node", default=None)
    ap.add_argument("--focus-label", default=None)
    ap.add_argument("--query", default=None)
    ap.add_argument("--neighbors", type=int, default=2)
    ap.add_argument("--max-nodes", type=int, default=500)
    ap.add_argument("--kg-root", type=Path, default=None)
    ap.add_argument("--no-embed-figures", action="store_true")
    ap.add_argument("--schema", action="store_true", help="render the Label->Label schema meta-overview")
    ap.add_argument("--access", default=None, help="comma list; PRE-filter to entities from these access values")
    ap.add_argument("--record-type", default=None, help="comma list; PRE-filter to these record_types")
    ap.add_argument("--exclude-record-type", default=None, help="comma list; PRE-drop these record_types")
    args = ap.parse_args()

    src = args.subgraph or args.graph
    if not src:
        print("need graph.json positional or --subgraph", file=sys.stderr)
        return 2
    nodes, links = load(src)
    kg_root = args.kg_root or (args.graph.parent if args.graph else Path("."))
    schema_mode = args.schema

    # doi -> {access, record_type} from Publication nodes (for per-node filter tags + CLI pre-filter)
    pubmeta = {}
    for n in nodes:
        if n.get("label") == "Publication":
            p = n.get("props", {}) or {}
            pubmeta[str(p.get("doi") or n["id"].split(":", 1)[-1]).lower()] = p
    # A subgraph contains only a few Publication nodes, but its entities cite papers across the WHOLE
    # graph — so pull every Publication's access/record_type from the full graph.json to tag nodes.
    if args.subgraph and not schema_mode and kg_root:
        gj = kg_root / "graph.json"
        if gj.exists():
            try:
                for n in json.loads(gj.read_text(encoding="utf-8-sig")).get("nodes", []):
                    if n.get("label") == "Publication":
                        p = n.get("props", {}) or {}
                        pubmeta.setdefault(str(p.get("doi") or n["id"].split(":", 1)[-1]).lower(), p)
            except Exception:
                pass

    def node_acc_rt(n):
        p = n.get("props", {}) or {}
        if n.get("label") == "Publication":
            dois = [str(p.get("doi") or n["id"].split(":", 1)[-1])]
        else:
            dois = [str(d) for d in (p.get("source_paper_ids") or [])]
        acc, rt = set(), set()
        for d in dois:
            m = pubmeta.get(d.lower())
            if m:
                if m.get("access"):
                    acc.add(m["access"])
                if m.get("record_type"):
                    rt.add(m["record_type"])
        return sorted(acc), sorted(rt)

    # optional CLI pre-filter (interactive filter below is the usual path)
    _acc = {s.strip() for s in (args.access or "").split(",") if s.strip()} or None
    _rt = {s.strip() for s in (args.record_type or "").split(",") if s.strip()} or None
    _xrt = {s.strip() for s in (args.exclude_record_type or "").split(",") if s.strip()} or None
    if not schema_mode and (_acc or _rt or _xrt):
        def keepnode(n):
            a, r = node_acc_rt(n)
            if _acc and not (set(a) & _acc):
                return False
            if _rt and not (set(r) & _rt):
                return False
            if _xrt and r and set(r) <= _xrt:
                return False
            return True
        ks = {n["id"] for n in nodes if keepnode(n)}
        nodes = [n for n in nodes if n["id"] in ks]
        links = [l for l in links if l["source"] in ks and l["target"] in ks]

    if schema_mode:
        nodes, links = build_schema(nodes, links)
        keep, trunc = set(n["id"] for n in nodes), False
    elif args.subgraph:
        keep, trunc = set(n["id"] for n in nodes), False
    else:
        keep, trunc = select(nodes, links, args)

    deg = defaultdict(int)
    for l in links:
        if l["source"] in keep and l["target"] in keep:
            deg[l["source"]] += 1
            deg[l["target"]] += 1

    labels = sorted({n.get("label", "Node") for n in nodes if n["id"] in keep})
    color = {l: PALETTE[i % len(PALETTE)] for i, l in enumerate(labels)}
    maxinst = max((n.get("props", {}).get("instances", 1) for n in nodes if n["id"] in keep), default=1) if schema_mode else 1
    access_vals, rt_vals = set(), set()
    els = []
    for n in nodes:
        if n["id"] not in keep:
            continue
        p = n.get("props", {}) or {}
        lab = n.get("label", "Node")
        name = p.get("name") or p.get("title") or n["id"].split(":")[-1]
        if schema_mode:
            sz = round(24 + 46 * (p.get("instances", 1) / maxinst) ** 0.5, 1)
            name = "%s (%d)" % (lab, p.get("instances", 0))
            acc, rt = [], []
        else:
            sz = round(15 + min(42, 3.4 * (deg.get(n["id"], 0) ** 0.5)), 1)
            acc, rt = node_acc_rt(n)
            access_vals.update(acc or ["n/a"])
            rt_vals.update(rt or ["n/a"])
        d = {"id": n["id"], "label": lab, "name": str(name)[:70],
             "color": color.get(lab, "#999"), "sz": sz, "acc": acc, "rt": rt, "props": p}
        if lab == "Figure" and p.get("path"):
            if args.no_embed_figures:
                try:
                    d["figure"] = os.path.relpath((kg_root / p["path"]).resolve(), args.out.parent.resolve()).replace("\\", "/")
                except Exception:
                    d["figure"] = p["path"]
            else:
                uri = datauri((kg_root / p["path"]).resolve())
                if uri:
                    d["figure"] = uri
        els.append({"data": d})
    kept_links = [l for l in links if l["source"] in keep and l["target"] in keep]
    etype_freq = Counter(l.get("type", "") for l in kept_links if l.get("type"))
    ordered_types = [t for t, _ in etype_freq.most_common()]
    etype_color = {t: PALETTE[i % len(PALETTE)] for i, t in enumerate(ordered_types[:18])}
    ei = 0
    for l in kept_links:
        et = l.get("type", "")
        ew = round(0.6 + min(4.0, 0.5 * (l.get("props", {}).get("count", 1) ** 0.5)), 1) if schema_mode else 0.8
        els.append({"data": {"id": f"e{ei}", "source": l["source"], "target": l["target"], "ew": ew,
                             "ecolor": etype_color.get(et, DEFAULT_EDGE_COLOR), "label": et, "props": l.get("props", {})}})
        ei += 1

    libfile = Path(__file__).resolve().parent.parent / "assets" / "cytoscape.min.js"
    if libfile.exists():
        lib_tag = f"<script>{libfile.read_text(encoding='utf-8')}</script>"
        lib_note = "vendored (offline)"
    else:
        lib_tag = f'<script src="{CDN}"></script>'
        lib_note = "CDN (needs internet)"
        print(f"WARN: {libfile} not found; using CDN. Vendor it for a truly offline file.", file=sys.stderr)

    legend = " ".join(f'<span><i style="background:{c}"></i>{html.escape(l)}</span>' for l, c in color.items())
    _shown = ordered_types[:16]
    edgelegend = " ".join(f'<span><i class="bar" style="background:{etype_color.get(t, DEFAULT_EDGE_COLOR)}"></i>{html.escape(t)}</span>'
                          for t in _shown)
    if len(ordered_types) > 16:
        edgelegend += f'<span class="k">+{len(ordered_types) - 16} more (grey)</span>'
    if not edgelegend:
        edgelegend = '<span class="k">relationships</span>'

    def _order(vals, pref):
        present = set(vals)
        return [v for v in pref if v in present] + sorted(present - set(pref))
    if schema_mode:
        filters_html = ""
    else:
        acc_boxes = _checks("fA", _order(access_vals, ["OA", "OSTI-OA", "Paywalled", "n/a"]))
        rt_boxes = _checks("fR", _order(rt_vals, ["research", "computational", "review", "perspective", "editorial", "n/a"]))
        type_boxes = _checks("fT", labels)
        filters_html = (
            '<div class="flt"><b>FILTERS</b> <span id="vismsg" class="k">(<span id="viscount">%d</span> shown)</span>'
            '<div class="row"><b>access</b> <a onclick="setAll(\'fA\',true)">all</a><a onclick="setAll(\'fA\',false)">none</a><br>%s</div>'
            '<div class="row"><b>record type</b> <a onclick="setAll(\'fR\',true)">all</a><a onclick="setAll(\'fR\',false)">none</a><br>%s</div>'
            '<div class="row"><b>node type</b> <a onclick="setAll(\'fT\',true)">all</a><a onclick="setAll(\'fT\',false)">none</a><br>%s</div></div>'
            % (sum(1 for e in els if "source" not in e["data"]), acc_boxes, rt_boxes, type_boxes))

    n_nodes = sum(1 for e in els if "source" not in e["data"])
    n_edges = sum(1 for e in els if "source" in e["data"])
    subtitle = f"{n_nodes} node types &middot; {n_edges} type-to-type links" if schema_mode else \
               f"{n_nodes} nodes, {n_edges} edges" + (" (truncated, highest-degree)" if trunc else "")
    nminzoom = "0" if schema_mode else "14"
    eminzoom = "10" if schema_mode else "15"
    repulsion = "9000" if schema_mode else "70000"
    edgelen = "120" if schema_mode else "170"
    html_out = (TEMPLATE.replace("__LIB__", lib_tag).replace("__TITLE__", html.escape(args.title))
                .replace("__LEGEND__", legend).replace("__EDGELEGEND__", edgelegend)
                .replace("__FILTERS__", filters_html)
                .replace("__SUBTITLE__", subtitle).replace("__NMINZOOM__", nminzoom)
                .replace("__EMINZOOM__", eminzoom).replace("__REPULSION__", repulsion)
                .replace("__EDGELEN__", edgelen)
                .replace("__ELEMENTS__", json.dumps(els, ensure_ascii=False)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html_out, encoding="utf-8")
    print(f"wrote {args.out} ({subtitle}; cytoscape={lib_note}; figures={'relative' if args.no_embed_figures else 'base64-embedded'}{'; schema-overview' if schema_mode else ''})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
