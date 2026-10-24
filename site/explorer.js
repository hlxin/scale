// The graph explorer. Pick a graph of this repository (data/graphs.json, written by `scale site build`) or open a file:
// the whole graph is drawn by a force layout (circle area by connectivity, colour by label), its labels and
// relationship types filter it, and a node's properties, evidence and neighbours show on the right. "Search by asking"
// lists the evidence that matches, or, with the reader's own API key, answers in words by SCALE's query-graph skill.
// Search, query plans and descriptions run SCALE's own code in a worker (worker.js).
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const md = (s) => DOMPurify.sanitize(marked.parse(String(s || "")));
const SDK = "https://cdn.jsdelivr.net/npm/@anthropic-ai/sdk@0.133.0/+esm";
const RESULT_CHARS = 40000;       // the longest tool result handed back to the model (as the web service does)
const KIND_PALETTE = ["#5b8def", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4", "#f43f5e", "#84cc16", "#0ea5e9", "#d946ef", "#fbbf24", "#22c55e"];
const EDGE_PALETTE = ["#7c3aed", "#0891b2", "#ea580c", "#16a34a", "#db2777", "#0284c7", "#ca8a04", "#9333ea", "#0d9488", "#dc2626", "#65a30d", "#2563eb"];
const NODE_R_MIN = 7, NODE_R_MAX = 40;
const BIG_GRAPH = 400;            // past this, names and arrowheads hide when seen from far
const HUGE_GRAPH = 1000;          // past this, the layout runs in slices
const FAR_ZOOM = 0.6;
const LABELS_AUTO_MAX = 400;      // relationship names shown by default up to this many links
const PROVENANCE_KIND = "Source", PROVENANCE_EDGE = "REPORTED_IN";   // hidden until asked for, as the evidence is on each node

let G = null;                     // the graph: {entry, doc, byId, out, inn, labels, rels, sha, props}
let manifest = [], questions = [];
const kindColour = new Map(), edgeColour = new Map();
const S = {                       // what the canvas shows
  kind: null, rel: null, sources: false, hidden: new Set(), extra: new Set(), match: null,
  selected: null, layout: "force", linkLabels: "auto", viewMoved: false,
  sim: null, zoom: null, settleGen: 0, pos: new Map(), nodes: [], links: [], degree: new Map(), minDeg: 0, maxDeg: 0, draw: null,
};

// ------------------------------------------------------------------------------------------ the worker (SCALE)
const worker = new Worker("worker.js");
const pending = new Map();
let seq = 0, pythonReady = false;
worker.onmessage = (e) => {
  const m = e.data;
  if (m.status) {
    pythonReady = m.status === "ready";
    status(pythonReady ? (G && G.loaded ? ready() : "SCALE is ready in this browser.") : m.status);
    return;
  }
  const p = pending.get(m.id);
  if (!p) return;
  pending.delete(m.id);
  m.ok ? p.resolve(m.result) : p.reject(new Error(m.error));
};
const rpc = (msg) => new Promise((resolve, reject) => { const id = ++seq; pending.set(id, { resolve, reject }); worker.postMessage({ id, ...msg }); });
const scale = (tool, args) => rpc({ op: "call", tool, args: { ...args, ...(tool === "describe" ? {} : { path: G.file }) } });
const status = (t) => { $("status").textContent = t; };
const ready = () => "Search, queries and answers run in this browser.";

// ------------------------------------------------------------------------------------------ the graphs rail
const SCOPE = { graphs: ["curated", "var(--green)"], examples: ["example", "var(--blue)"], domain: ["synthetic", "var(--violet)"] };
const scopeOf = (e) => SCOPE[(e.from || "").split("/")[0]] || ["file", "var(--subtle)"];
const CARET = `<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6 L15 12 L9 18"/></svg>`;

async function start() {
  try { manifest = (await (await fetch("data/graphs.json")).json()).graphs || []; } catch { manifest = []; }
  renderGraphs();
  window.onhashchange = () => openFromHash();
  $("graph-file").onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try { questions = []; await openGraph({ id: f.name.replace(/\W+/g, "-"), title: f.name.replace(/\.json$/, ""), from: "" }, await f.text()); }
    catch (err) { alert(`not a graph: ${err.message}`); }
  };
  await openFromHash();
}

function renderGraphs() {
  const list = G && !manifest.includes(G.entry) ? [G.entry, ...manifest] : manifest;
  $("graphs").innerHTML = list.map((e) => {
    const [scope, c] = scopeOf(e), active = G && G.entry === e;
    return `<div role="listitem"><button class="gx-graph-item${active ? " is-active" : ""}" type="button" data-id="${esc(e.id)}" title="${esc(e.title)}"
        aria-expanded="${active}" style="--dot:${c}"><span class="gx-graph-caret">${CARET}</span><span class="gx-graph-dot"></span>
        <span class="gx-graph-title">${esc(e.title)}</span><span class="gx-graph-scope">${scope}</span></button>${active ? details() : ""}</div>`;
  }).join("") || `<p class="gx-muted">No graphs are listed: open a file.</p>`;
  $("graphs").querySelectorAll(".gx-graph-item").forEach((b) => (b.onclick = () => {
    const e = manifest.find((x) => x.id === b.dataset.id);
    if (e && !(G && G.entry === e)) location.hash = `g=${encodeURIComponent(e.id)}`;
  }));
}
function details() {
  const g = G.doc.graph || {}, e = G.entry, [scope] = scopeOf(e);
  const facts = [
    ["Type", `<span class="gx-type">Knowledge graph</span>${scope === "synthetic" ? ` <span class="gx-warn">synthetic example</span>` : ""}`],
    ["Size", `${G.doc.nodes.length.toLocaleString()} nodes · ${G.doc.links.length.toLocaleString()} rels · ${G.props.toLocaleString()} props`],
    g.version ? ["Release", esc(g.version)] : null,
    ["Visibility", esc(((g.stewardship || {}).access || "public").replace(/^./, (c) => c.toUpperCase()))],
    g.created || g.date ? ["Created", esc(g.created || g.date)] : null,
    ["Checksum", G.sha ? `<span class="gx-sha" title="sha256 ${esc(G.sha)}">${esc(G.sha.slice(0, 12))}…</span>` : "…"],
    ["Source", e.from ? `<a href="https://github.com/hlxin/scale/tree/main/${esc(e.from)}">${esc(e.from)}</a>` : "a file on this computer"],
    ["Schema", `<a href="https://github.com/hlxin/scale/tree/main/domain/graph">${esc(g.schema || "scale-catal")} v${esc(g.schema_version || "?")}</a><br>
      ${G.labels.size} labels · ${G.rels.size} rel types${questions.length ? ` · ${questions.length} saved questions` : ""}`],
  ].filter(Boolean);
  return `<div class="gx-graph-detail"><dl class="gx-facts">${facts.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl></div>`;
}

async function openFromHash() {
  const want = new URLSearchParams(location.hash.slice(1)).get("g");
  const entry = manifest.find((g) => g.id === want) || manifest[0];
  if (!entry || (G && G.entry === entry)) return;
  status(`Loading ${entry.title}…`);
  $("empty").hidden = false;
  $("empty").innerHTML = `<p>Loading graph…</p>`;
  const text = await (await fetch(entry.path)).text();
  questions = [];
  if (entry.questions) try { questions = await (await fetch(`data/questions/${entry.id}.json`)).json(); } catch { /* none */ }
  await openGraph(entry, text);
}

async function openGraph(entry, text) {
  const doc = JSON.parse(text);
  if (!Array.isArray(doc.nodes) || !Array.isArray(doc.links)) throw new Error("no nodes and links");
  const byId = new Map(doc.nodes.map((n) => [n.id, n]));
  const out = new Map(), inn = new Map(), labels = new Map(), rels = new Map();
  let props = 0;
  for (const n of doc.nodes) { labels.set(n.label, (labels.get(n.label) || 0) + 1); props += Object.keys(n.props || {}).length; }
  for (const e of doc.links) {
    (out.get(e.source) || out.set(e.source, []).get(e.source)).push(e);
    (inn.get(e.target) || inn.set(e.target, []).get(e.target)).push(e);
    rels.set(e.type, (rels.get(e.type) || 0) + 1);
    props += Object.keys(e.props || {}).length;
  }
  kindColour.clear(); edgeColour.clear();
  [...labels].sort((a, b) => b[1] - a[1]).forEach(([l]) => colourForKind(l));
  [...rels].sort((a, b) => b[1] - a[1]).forEach(([t]) => colourForEdge(t));
  G = { entry, file: `${entry.id}.json`, doc, byId, out, inn, labels, rels, props, sha: "" };
  Object.assign(S, { kind: null, rel: null, sources: false, hidden: new Set(), extra: new Set(), match: null, selected: null, pos: new Map(), nodes: [] });
  $("card").hidden = true;
  renderGraphs();
  renderLegend();
  showLegend();
  draw();
  sha256(text).then((h) => { if (G && G.entry === entry) { G.sha = h; renderGraphs(); } });
  const g = G;
  await rpc({ op: "put", name: G.file, text }).then(() => { g.loaded = true; })
    .catch((err) => status(`SCALE could not load the graph: ${err.message}`));
  if (G !== g) return;
  status(ready());
  warm(g);
}
async function sha256(text) {
  try {
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
  } catch { return ""; }
}
// The first search of a graph builds its evidence index (seconds for thousands of quotes); build it now, while the
// reader looks at the graph. The toolkit keeps it with the loaded graph.
async function warm(g) {
  if (!g.doc.nodes.some((n) => (n.props?.evidence || []).some((e) => e.quote))) return;
  status("Indexing the evidence…");
  try { await scale("search", { query: "catalyst", k: 1 }); } catch { /* reported when the reader searches */ }
  if (G === g) status(ready());
}

// ------------------------------------------------------------------------------------------ colours, names, values
function colourForKind(k) { if (!kindColour.has(k)) kindColour.set(k, KIND_PALETTE[kindColour.size % KIND_PALETTE.length]); return kindColour.get(k); }
function colourForEdge(t) { if (!edgeColour.has(t)) edgeColour.set(t, EDGE_PALETTE[edgeColour.size % EDGE_PALETTE.length]); return edgeColour.get(t); }
const name = (n) => (n && (n.props?.name || n.props?.title || n.props?.formula || n.id.split("/").pop())) || "?";
const trunc = (s, n) => (String(s).length > n ? `${String(s).slice(0, n - 1)}…` : String(s));
function value(v) {
  if (v === null || v === undefined) return "";
  if (Array.isArray(v)) return v.map(value).join("; ");
  if (typeof v !== "object") return esc(v);
  if ("status" in v && (v.status !== "present" || "value" in v || "text_value" in v || "lower" in v || "upper" in v || "boolean_value" in v)) {
    if (v.status !== "present") return `<span class="gx-subtle">${esc(v.status)}${v.missing_reason ? ` (${esc(v.missing_reason)})` : ""}</span>`;
    const num = "value" in v ? v.value : "lower" in v || "upper" in v ? `${v.lower ?? ""}–${v.upper ?? ""}` : v.text_value ?? v.boolean_value;
    const shown = `${esc(num)}${v.unit && v.unit !== "1" ? ` ${esc(v.unit)}` : ""}`;
    return v.as_reported && String(v.as_reported) !== String(num) ? `${shown} <span class="gx-subtle">(as reported: ${esc(v.as_reported)})</span>` : shown;
  }
  return `<code>${esc(JSON.stringify(v))}</code>`;
}
const idLinks = (html) => html.replace(/((?:ex|scale|[a-z][a-z0-9-]*):[A-Za-z0-9_.\/#-]+)/g,
  (m, id) => (G && G.byId.has(id) ? `<a href="#" data-id="${esc(id)}">${esc(id)}</a>` : m));
const wireIds = (root) => root.querySelectorAll("a[data-id]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); goTo(a.dataset.id); }));

// ------------------------------------------------------------------------------------------ what is drawn
function visible() {
  const showNode = (n) => !S.hidden.has(n.id) && (S.extra.has(n.id) || ((S.sources || n.label !== PROVENANCE_KIND) && (!S.kind || n.label === S.kind)));
  const nodes = G.doc.nodes.filter(showNode);
  const ids = new Set(nodes.map((n) => n.id));
  let crossing = 0;
  const links = [];
  for (const e of G.doc.links) {
    const a = ids.has(e.source), b = ids.has(e.target);
    if (a !== b) crossing += 1;
    if (a && b && (!S.rel || e.type === S.rel)) links.push(e);
  }
  return { nodes, links, crossing };
}
const radius = (id) => {
  const deg = S.degree.get(id) || 0;
  if (!deg || !S.maxDeg) return NODE_R_MIN;
  const t = S.maxDeg > S.minDeg ? (deg - S.minDeg) / (S.maxDeg - S.minDeg) : 1;
  return NODE_R_MIN + (NODE_R_MAX - NODE_R_MIN) * Math.sqrt(t);
};
const linkLabelsShown = () => (S.linkLabels === "on" ? true : S.linkLabels === "off" ? false : S.links.length <= LABELS_AUTO_MAX);

const svg = d3.select("#svg"), zoomLayer = d3.select("#zoom-layer");
function size() { const r = $("canvas").getBoundingClientRect(); return [Math.max(r.width, 320), Math.max(r.height, 320)]; }

function draw() {
  for (const n of S.nodes) S.pos.set(n.id, n);                     // keep where nodes were across redraws
  const { nodes, links, crossing } = visible();
  S.nodes = nodes.map((n) => { const p = S.pos.get(n.id); return { id: n.id, label: n.label, name: name(n), ...(p ? { x: p.x, y: p.y, fx: p.pinned ? p.fx : null, fy: p.pinned ? p.fy : null, pinned: p.pinned } : {}) }; });
  S.links = links.map((e) => ({ id: e.id, type: e.type, source: e.source, target: e.target }));
  $("summary").textContent = `Displaying ${nodes.length} nodes, ${links.length} relationships.`
    + (S.kind && crossing ? ` ${crossing} more connect them to other labels.` : "");
  $("unhide-btn").hidden = !S.hidden.size;
  $("unhide-label").textContent = `Show hidden (${S.hidden.size})`;
  $("labels-btn").setAttribute("aria-pressed", String(linkLabelsShown()));
  if (!nodes.length) {
    $("empty").hidden = false;
    $("empty").innerHTML = `<p>Nothing to show: pick another label or relationship type.</p>`;
    d3.select("#nodes").selectAll("*").remove(); d3.select("#links").selectAll("*").remove();
    return;
  }
  $("empty").hidden = true;
  const [W, H] = size();
  svg.attr("viewBox", `0 0 ${W} ${H}`);
  if (!S.zoom) {
    S.zoom = d3.zoom().scaleExtent([0.05, 4]).on("zoom", (ev) => {
      zoomLayer.attr("transform", ev.transform);
      if (ev.sourceEvent) S.viewMoved = true;
      syncFar(ev.transform.k);
    });
    svg.call(S.zoom).on("dblclick.zoom", null);
    svg.on("click.inspector", (ev) => { if (ev.target === svg.node()) clearSelection(); });
  }
  // degree, for the radius and the repulsion
  S.degree = new Map();
  for (const e of S.links) { S.degree.set(e.source, (S.degree.get(e.source) || 0) + 1); S.degree.set(e.target, (S.degree.get(e.target) || 0) + 1); }
  const degs = [...S.degree.values()];
  S.maxDeg = degs.length ? Math.max(...degs) : 0;
  S.minDeg = degs.length ? Math.min(...degs) : 0;

  const showLabels = linkLabelsShown();
  const link = d3.select("#links").selectAll("g").data(S.links, (d) => d.id).join((enter) => {
    const g = enter.append("g");
    g.append("line").attr("marker-end", "url(#gx-arrow)");
    g.append("text").attr("class", "gx-link-label").attr("dy", -3);
    return g;
  });
  link.select("line").attr("stroke", (d) => colourForEdge(d.type)).attr("stroke-opacity", 0.55);
  link.select("text").text((d) => (showLabels ? d.type : "")).attr("fill", (d) => colourForEdge(d.type));
  link.on("click", (ev, d) => { ev.stopPropagation(); showDetails(G.doc.links.find((e) => e.id === d.id)); });

  const node = d3.select("#nodes").selectAll("g").data(S.nodes, (d) => d.id).join((enter) => {
    const g = enter.append("g").attr("class", "gx-node");
    g.append("circle");
    g.append("text").attr("dy", "0.32em");
    return g;
  });
  node.call(drag());
  node.on("dblclick", (ev, d) => { ev.stopPropagation(); expand(d.id); });
  node.classed("selected", (d) => d.id === S.selected);
  node.select("circle").attr("r", (d) => radius(d.id)).attr("fill", (d) => colourForKind(d.label));
  node.select("text").text((d) => trunc(d.name, 22));
  markMatches();

  // the layout: as the graph grows, shorter links, weaker repulsion and less padding keep its clusters on screen
  const linkCount = S.links.length;
  let hubId = null, hubDeg = 0;
  for (const [id, d] of S.degree) if (d > hubDeg) { hubId = id; hubDeg = d; }
  const isStar = linkCount > 0 && hubDeg >= linkCount * 0.5;
  const isBig = S.nodes.length > BIG_GRAPH;
  const linkDistance = isStar ? 180 : isBig ? 55 : 130;
  const charge = isStar ? -520 : isBig ? -110 : -320;
  const pad = isBig ? 6 : 24;
  const lines = link.select("line").nodes(), labels = link.select("text").nodes(), groups = node.nodes();
  S.draw = () => tick(lines, labels, groups, showLabels);
  S.viewMoved = false;
  syncFar(d3.zoomTransform(svg.node()).k);
  if (S.sim) S.sim.stop();
  S.sim = d3.forceSimulation(S.nodes)
    .force("link", d3.forceLink(S.links).id((d) => d.id).distance(linkDistance).strength(isStar ? 0.55 : 0.7))
    .force("charge", d3.forceManyBody().strength((d) => charge - (S.degree.get(d.id) || 1) * 8))
    .force("center", d3.forceCenter(W / 2, H / 2))
    .force("collide", d3.forceCollide().radius((d) => radius(d.id) + pad))
    .force("x", d3.forceX(W / 2).strength((d) => (S.degree.get(d.id) ? 0.04 : 0.2)))
    .force("y", d3.forceY(H / 2).strength((d) => (S.degree.get(d.id) ? 0.04 : 0.2)))
    .on("tick", () => {
      S.draw();
      const now = performance.now();
      if (!S.viewMoved && now - (S.lastFit || 0) > 400) { S.lastFit = now; fit(true); }
    })
    .on("end", () => { if (!S.viewMoved) fit(); });
  if (isStar && hubId) { const hub = S.nodes.find((n) => n.id === hubId); if (hub && !hub.pinned) { hub.fx = W / 2; hub.fy = H / 2; } }
  if (S.layout !== "force") applyLayout(S.layout, false);
  else if (S.nodes.length > HUGE_GRAPH) settle();
  else S.sim.alpha(0.9).restart();
}
function tick(lines, labels, groups, showLabels) {
  const far = svg.classed("far");
  for (const el of lines) {
    const d = el.__data__;
    let x2 = d.target.x, y2 = d.target.y;
    if (!far) {                                    // end at the target's rim, so the arrowhead shows
      const dx = x2 - d.source.x, dy = y2 - d.source.y, len = Math.hypot(dx, dy);
      if (len > 0) { const r = Math.min(len - 1, radius(d.target.id) + 2); x2 -= (dx / len) * r; y2 -= (dy / len) * r; }
    }
    el.setAttribute("x1", d.source.x); el.setAttribute("y1", d.source.y); el.setAttribute("x2", x2); el.setAttribute("y2", y2);
  }
  if (showLabels) for (const el of labels) {
    const d = el.__data__;
    el.setAttribute("x", (d.source.x + d.target.x) / 2); el.setAttribute("y", (d.source.y + d.target.y) / 2);
  }
  for (const el of groups) { const d = el.__data__; el.setAttribute("transform", `translate(${d.x},${d.y})`); }
}
// A big graph is laid out in slices of 40 ms, so the page stays responsive; the view follows it as it spreads.
function settle() {
  const gen = ++S.settleGen, sim = S.sim;
  sim.stop(); sim.alpha(0.9);
  let drawnAt = 0;
  const slice = () => {
    if (gen !== S.settleGen || sim !== S.sim) return;
    const t0 = performance.now();
    while (sim.alpha() >= sim.alphaMin() && performance.now() - t0 < 40) sim.tick();
    const done = sim.alpha() < sim.alphaMin();
    if (done || t0 - drawnAt > 400) { S.draw(); if (!done && !S.viewMoved) fit(true); drawnAt = performance.now(); }
    if (!done) setTimeout(slice, 0); else if (!S.viewMoved) fit();
  };
  setTimeout(slice, 0);
}
function syncFar(k) { svg.classed("far", S.nodes.length > BIG_GRAPH && k < FAR_ZOOM); }
function fit(instant = false, nodes = S.nodes) {
  const run = () => {
    const pts = nodes.map((n) => [n.fx ?? n.x, n.fy ?? n.y]).filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
    if (!pts.length) return;
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const [W, H] = size(), PAD = 70;
    const k = Math.min(2, Math.max(0.05, Math.min(W / (maxX - minX + PAD * 2 || 1), H / (maxY - minY + PAD * 2 || 1))));
    const to = d3.zoomIdentity.translate(W / 2 - ((minX + maxX) / 2) * k, H / 2 - ((minY + maxY) / 2) * k).scale(k);
    instant ? svg.call(S.zoom.transform, to) : svg.transition().duration(450).call(S.zoom.transform, to);
  };
  instant ? run() : requestAnimationFrame(() => requestAnimationFrame(run));
}
// a click is a press with no movement; a drag pins the node where it is dropped
function drag() {
  return d3.drag()
    .on("start", (ev, d) => { d.fx = d.x; d.fy = d.y; d._sx = ev.x; d._sy = ev.y; d._moved = false; d._heated = false; })
    .on("drag", (ev, d) => {
      d.fx = ev.x; d.fy = ev.y;
      if (!d._moved && Math.hypot(ev.x - d._sx, ev.y - d._sy) > 3) d._moved = true;
      if (d._moved && !d._heated) { S.settleGen += 1; S.viewMoved = true; S.sim.alphaTarget(S.nodes.length > BIG_GRAPH ? 0.08 : 0.3).restart(); d._heated = true; }
    })
    .on("end", (ev, d) => {
      if (d._heated && !ev.active) S.sim.alphaTarget(0);
      if (d._moved) { d.pinned = true; d.fx = ev.x; d.fy = ev.y; }
      else { if (!d.pinned) { d.fx = null; d.fy = null; } select(d.id); }
    });
}

// ------------------------------------------------------------------------------------------ layouts
function adjacency() {
  const out = new Map(S.nodes.map((n) => [n.id, []])), inn = new Map(S.nodes.map((n) => [n.id, []])), und = new Map(S.nodes.map((n) => [n.id, []]));
  for (const e of S.links) {
    const s = e.source.id ?? e.source, t = e.target.id ?? e.target;
    out.get(s)?.push(t); inn.get(t)?.push(s); und.get(s)?.push(t); und.get(t)?.push(s);
  }
  return { out, inn, und };
}
function hierarchical() {
  const { out, inn } = adjacency(), [W, H] = size();
  const level = new Map(), queue = [];
  const order = [...S.nodes].sort((a, b) => (out.get(b.id).length - inn.get(b.id).length) - (out.get(a.id).length - inn.get(a.id).length));
  const seed = (id) => { if (!level.has(id)) { level.set(id, 0); queue.push(id); } };
  const drain = () => { while (queue.length) { const id = queue.shift(); for (const t of out.get(id)) if (!level.has(t)) { level.set(t, level.get(id) + 1); queue.push(t); } } };
  order.filter((n) => !inn.get(n.id).length).forEach((n) => seed(n.id)); drain();
  for (const n of order) if (!level.has(n.id)) { seed(n.id); drain(); }
  const layers = new Map();
  for (const [id, l] of level) (layers.get(l) || layers.set(l, []).get(l)).push(id);
  const pos = new Map(), perRow = Math.max(12, Math.ceil(Math.sqrt(S.nodes.length) * 2)), dx = 110;
  let y = 0;
  [...layers.keys()].sort((a, b) => a - b).forEach((l) => {
    const ids = layers.get(l);
    if (l > 0) { const bary = (id) => { const xs = inn.get(id).map((p) => pos.get(p)).filter(Boolean).map((p) => p[0]); return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0; }; ids.sort((a, b) => bary(a) - bary(b)); }
    for (let r = 0; r * perRow < ids.length; r++) {
      const row = ids.slice(r * perRow, (r + 1) * perRow), left = W / 2 - ((row.length - 1) * dx) / 2 + (r % 2 ? dx / 2 : 0);
      row.forEach((id, i) => pos.set(id, [left + i * dx, y]));
      y += 70;
    }
    y += 80;
  });
  for (const p of pos.values()) p[1] += H / 2 - y / 2;
  return pos;
}
function radial() {
  const { und } = adjacency(), [W, H] = size();
  const root = S.selected && und.has(S.selected) ? S.selected : [...S.nodes].sort((a, b) => und.get(b.id).length - und.get(a.id).length)[0].id;
  const depth = new Map([[root, 0]]), parent = new Map(), queue = [root];
  while (queue.length) { const id = queue.shift(); for (const t of und.get(id)) if (!depth.has(t)) { depth.set(t, depth.get(id) + 1); parent.set(t, id); queue.push(t); } }
  const outer = Math.max(0, ...depth.values()) + 1;
  for (const n of S.nodes) if (!depth.has(n.id)) depth.set(n.id, outer);
  const rings = new Map();
  for (const [id, d] of depth) (rings.get(d) || rings.set(d, []).get(d)).push(id);
  const pos = new Map([[root, [W / 2, H / 2]]]), angle = new Map([[root, 0]]);
  [...rings.keys()].sort((a, b) => a - b).forEach((d) => {
    if (!d) return;
    const ids = rings.get(d).sort((a, b) => (angle.get(parent.get(a)) ?? 0) - (angle.get(parent.get(b)) ?? 0));
    const r = Math.max(d * 150, (ids.length * 34) / (2 * Math.PI));
    ids.forEach((id, i) => { const a = (2 * Math.PI * i) / ids.length; angle.set(id, a); pos.set(id, [W / 2 + r * Math.cos(a), H / 2 + r * Math.sin(a)]); });
  });
  return pos;
}
function applyLayout(kind, refit = true) {
  if (!S.nodes.length || !S.sim) return;
  S.settleGen += 1;
  if (kind === "force") {
    for (const n of S.nodes) if (!n.pinned) { n.fx = null; n.fy = null; }
    S.viewMoved = !refit;
    if (S.nodes.length > HUGE_GRAPH) settle(); else { S.sim.alpha(0.9).restart(); if (refit) setTimeout(() => fit(), 900); }
    return;
  }
  const pos = kind === "hierarchical" ? hierarchical() : radial();
  S.sim.stop();
  for (const n of S.nodes) { const p = pos.get(n.id); if (p) { n.pinned = false; n.fx = n.x = p[0]; n.fy = n.y = p[1]; n.vx = n.vy = 0; } }
  S.draw();
  if (refit) fit();
}

// ------------------------------------------------------------------------------------------ labels, types and the node
function renderLegend() {
  const pill = (attr, key, label, count, colour, pressed, neutral) =>
    `<button class="gx-pill" type="button" ${attr}="${esc(key)}" ${neutral ? 'data-tone="neutral"' : `style="--pill:${colour}"`} aria-pressed="${pressed}">${esc(label)} <span class="gx-pill-count">(${count.toLocaleString()})</span></button>`;
  $("kinds").innerHTML = pill("data-l", "*", "*", G.doc.nodes.length, "", !S.kind, true)
    + [...G.labels].sort((a, b) => b[1] - a[1]).map(([l, n]) => pill("data-l", l, l, n, colourForKind(l), S.kind === l)).join("");
  $("rels").innerHTML = pill("data-t", "*", "*", G.doc.links.length, "", !S.rel, true)
    + [...G.rels].sort((a, b) => b[1] - a[1]).map(([t, n]) => pill("data-t", t, t, n, colourForEdge(t), S.rel === t)).join("");
  $("kinds").querySelectorAll(".gx-pill").forEach((b) => (b.onclick = () => {
    const l = b.dataset.l === "*" ? null : b.dataset.l;
    S.kind = S.kind === l ? null : l;
    S.sources = S.kind === PROVENANCE_KIND;          // the sources show when asked for by their label
    S.extra.clear();
    renderLegend(); draw();
  }));
  $("rels").querySelectorAll(".gx-pill").forEach((b) => (b.onclick = () => {
    const t = b.dataset.t === "*" ? null : b.dataset.t;
    S.rel = S.rel === t ? null : t;
    if (S.rel === PROVENANCE_EDGE) S.sources = true;
    renderLegend(); draw();
  }));
}
function showLegend() {
  $("legend").hidden = false; $("record").hidden = true; $("inspector-back").hidden = true;
  $("inspector-title").textContent = "Labels, types & props";
}
function clearSelection() {
  S.selected = null;
  d3.selectAll(".gx-node").classed("selected", false);
  $("locate").disabled = true;
  showLegend();
}
function select(id) {
  S.selected = id;
  d3.selectAll(".gx-node").classed("selected", (d) => d.id === id);
  $("locate").disabled = false;
  showDetails(G.byId.get(id));
}
// a node not on the canvas (a source, a node of another label) is brought onto it
function goTo(id) {
  if (!G.byId.has(id)) { const l = G.doc.links.find((e) => e.id === id); if (l) showDetails(l); return; }
  if (!S.nodes.some((n) => n.id === id)) { S.hidden.delete(id); S.extra.add(id); draw(); }
  select(id);
  const n = S.nodes.find((x) => x.id === id);
  setTimeout(() => { if (n && Number.isFinite(n.x)) { S.viewMoved = true; svg.transition().duration(450).call(S.zoom.translateTo, n.x, n.y); } }, S.sim && S.sim.alpha() > 0.1 ? 900 : 0);
}
function expand(id) {
  const near = [...(G.out.get(id) || []), ...(G.inn.get(id) || [])].slice(0, 50);
  for (const e of near) for (const n of [e.source, e.target]) { S.hidden.delete(n); S.extra.add(n); }
  S.extra.add(id);
  draw();
  select(id);
}
const COPY = `<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8 V5 a1 1 0 0 0 -1 -1 H5 a1 1 0 0 0 -1 1 V15 a1 1 0 0 0 1 1 H8"/></svg>`;
function showDetails(rec) {
  if (!rec) return;
  const p = rec.props || {};
  const isLink = "source" in rec && "target" in rec;
  const head = isLink
    ? `<div class="gx-record-head"><span class="gx-pill" style="--pill:${colourForEdge(rec.type)}">${esc(rec.type)}</span></div>
       <p><a href="#" data-id="${esc(rec.source)}">${esc(name(G.byId.get(rec.source)))}</a> → <a href="#" data-id="${esc(rec.target)}">${esc(name(G.byId.get(rec.target)))}</a></p>`
    : `<div class="gx-record-head"><span class="gx-pill" style="--pill:${colourForKind(rec.label)}">${esc(rec.label)}</span><span class="gx-record-label">${esc(name(rec))}</span></div>`;
  const entries = [["id", rec.id], ...Object.entries(p).filter(([k]) => k !== "evidence")];
  const rows = entries.map(([k, v], i) => `<tr><td>${esc(k)}</td><td>${idLinks(value(v))}</td><td class="act"><button class="gx-copy" data-i="${i}" title="Copy">${COPY}</button></td></tr>`).join("");
  const ev = (p.evidence || []).map((e) => {
    const src = G.byId.get(e.source);
    const where = [src ? name(src) : e.source, src?.props?.year, e.locator].filter(Boolean).map(esc).join(" · ");
    return `<blockquote class="gx-quote-block">${e.quote ? esc(e.quote) : `<span class="gx-subtle">No quote kept.</span>`}<div class="gx-meta">${src ? `<a href="#" data-id="${esc(src.id)}">${where}</a>` : where}</div></blockquote>`;
  }).join("");
  let neighbours = "";
  if (!isLink) {
    const items = [...(G.out.get(rec.id) || []).map((e) => [`${e.type} →`, e.target]), ...(G.inn.get(rec.id) || []).map((e) => [`← ${e.type}`, e.source])];
    neighbours = `<section class="gx-inspector-section"><h3>Neighbours <span class="gx-count">${items.length}</span></h3><ul class="gx-neighbours">${
      items.slice(0, 120).map(([rel, id]) => { const n = G.byId.get(id); return `<li><span class="dot" style="background:${colourForKind(n?.label)}"></span><a href="#" data-id="${esc(id)}">${esc(trunc(name(n), 60))}</a><span class="gx-rel">${esc(rel)}</span></li>`; }).join("")}
      ${items.length > 120 ? `<li class="gx-muted">… ${items.length - 120} more</li>` : ""}</ul></section>`;
  }
  const node = S.nodes.find((n) => n.id === rec.id);
  $("record").innerHTML = `${head}
    <table class="gx-props"><thead><tr><th>Key</th><th>Value</th><th></th></tr></thead><tbody>${rows}</tbody></table>
    ${ev ? `<section class="gx-inspector-section"><h3>Provenance <span class="gx-count">${(p.evidence || []).length}</span></h3>${ev}</section>` : ""}
    ${neighbours}
    ${isLink ? "" : `<footer class="gx-inspector-actions"><button class="gx-btn gx-btn-tiny" id="act-expand">Expand neighbourhood</button>
      <button class="gx-btn gx-btn-tiny" id="act-focus">Focus</button><button class="gx-btn gx-btn-tiny" id="act-pin" aria-pressed="${!!node?.pinned}">${node?.pinned ? "Unpin" : "Pin"}</button>
      <button class="gx-btn gx-btn-tiny" id="act-hide" title="Remove from this view (the graph is not changed)">Hide</button></footer>`}`;
  wireIds($("record"));
  $("record").querySelectorAll(".gx-copy").forEach((b) => (b.onclick = () => { const v = entries[Number(b.dataset.i)][1]; navigator.clipboard?.writeText(typeof v === "string" ? v : JSON.stringify(v)); }));
  if (!isLink) {
    $("act-expand").onclick = () => expand(rec.id);
    $("act-focus").onclick = () => focus(rec.id);
    $("act-pin").onclick = () => { const n = S.nodes.find((x) => x.id === rec.id); if (n) { n.pinned = !n.pinned; if (n.pinned) { n.fx = n.x; n.fy = n.y; } else { n.fx = n.fy = null; } showDetails(rec); } };
    $("act-hide").onclick = () => { S.hidden.add(rec.id); S.extra.delete(rec.id); clearSelection(); draw(); };
  }
  $("legend").hidden = true; $("record").hidden = false; $("inspector-back").hidden = false;
  $("inspector-title").textContent = isLink ? "Relationship details" : "Node details";
  if ($("grid").classList.contains("inspector-off")) panel("inspector", true);
}
function focus(id) {
  const ids = new Set([id, ...[...(G.out.get(id) || []), ...(G.inn.get(id) || [])].flatMap((e) => [e.source, e.target])]);
  S.viewMoved = true;
  fit(false, S.nodes.filter((n) => ids.has(n.id)));
}
$("inspector-back").onclick = () => clearSelection();

// ------------------------------------------------------------------------------------------ the answer card
function card(title, html) {
  $("card-title").textContent = title;
  $("card-body").innerHTML = html;
  $("card").hidden = false;
  $("card").classList.remove("collapsed");
  wireIds($("card-body"));
}
function markMatches() {
  const m = S.match;
  d3.selectAll(".gx-node").classed("match", (d) => !!m && m.has(d.id)).classed("dim", (d) => !!m && !m.has(d.id));
  d3.selectAll("#links line").classed("dim", (d) => !!m && !(m.has(d.source.id ?? d.source) && m.has(d.target.id ?? d.target)));
}
$("card-close").onclick = () => { $("card").hidden = true; S.match = null; markMatches(); };
$("card-collapse").onclick = () => $("card").classList.toggle("collapsed");

async function search(q) {
  card("Matching evidence", `<p class="gx-meta">Searching…</p>`);
  try {
    const r = await scale("search", { query: q, k: 25 });
    if (r.error) throw new Error(r.error);
    const hits = r.hits || [];
    S.match = new Set(hits.map((h) => h.record));
    const missing = [...S.match].filter((id) => G.byId.has(id) && !S.nodes.some((n) => n.id === id));
    if (missing.length) { missing.forEach((id) => S.extra.add(id)); draw(); } else markMatches();
    const shown = S.nodes.filter((n) => S.match.has(n.id));               // the view goes to what matched
    if (shown.length) setTimeout(() => { S.viewMoved = true; fit(false, shown); }, missing.length ? 900 : 0);
    card(`Matching evidence · ${hits.length}`, (hits.length ? hits.map((h) => `<div class="gx-hit" data-id="${esc(h.record)}">
        <div class="gx-quote">“${esc(h.text)}”</div>
        <div class="gx-meta">${esc(h.label || "")}: ${esc(h.record_name || h.record)} · ${esc(name(G.byId.get(h.source)))}${h.source_year ? ` (${esc(h.source_year)})` : ""}, ${esc(h.locator || "")} · ${Number(h.score || 0).toFixed(3)}</div></div>`).join("")
      : `<p>No evidence matches “${esc(q)}”.</p>`) + (store.get("scale-api-key") ? "" : `<p class="gx-meta">Add your API key (the key in the search bar) for an answer in words.</p>`));
    $("card-body").querySelectorAll(".gx-hit").forEach((el) => (el.onclick = () => goTo(el.dataset.id)));
  } catch (err) { card("Matching evidence", `<p class="gx-card-warn">${esc(err.message)}</p>`); }
}
function resultHtml(r) {
  if (r.error) return `<p class="gx-card-warn">${esc(r.error)}</p>`;
  const rows = r.rows || [];
  const cols = [...new Set(rows.flatMap((x) => Object.keys(x.values || {})))];
  const table = rows.length ? `<table class="gx-rows"><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr>${rows.slice(0, 200).map((x) =>
    `<tr>${cols.map((c) => `<td>${idLinks(value(x.values?.[c]))}</td>`).join("")}</tr>`).join("")}</table>` : "";
  const lim = (r.limitations || []).map((l) => `<li>${esc(l)}</li>`).join("");
  return `<p><strong>${esc(r.status)}</strong> · ${r.row_count ?? rows.length} rows${(r.excluded || []).length ? ` · ${r.excluded.length} left out` : ""}</p>
    ${table}${lim ? `<details><summary>Limitations</summary><ul>${lim}</ul></details>` : ""}
    <details><summary>Full result</summary><pre>${esc(JSON.stringify(r, null, 1).slice(0, 60000))}</pre></details>`;
}
function rowsMatch(r) {
  S.match = new Set((r.rows || []).flatMap((x) => Object.values(x.bound || {})).filter((id) => G.byId.has(id)));
  markMatches();
}
function queryCard() {
  const opts = `<option value="">${questions.length ? "Questions that run on this graph…" : "No saved questions for this graph"}</option>`
    + questions.map((q, i) => `<option value="${i}">${esc(q.id)}: ${esc(String(q.question || "").slice(0, 100))}</option>`).join("");
  card("Query plan", `<select id="plan-pick">${opts}</select>
    <textarea id="plan" rows="9" spellcheck="false" placeholder='{"match": {"label": "CatalyticTest", "as": "t"}, "return": ["t.name"], "limit": 10}'></textarea>
    <p><button class="gx-btn gx-btn-primary" id="plan-go" type="button">Run</button>
      <span class="gx-meta">match, steps, where, return, evidence, limit · <a href="https://github.com/hlxin/scale/blob/main/docs/querying.md">docs/querying.md</a></span></p>
    <div id="plan-out"></div>`);
  $("plan-pick").onchange = (e) => { const q = questions[Number(e.target.value)]; if (q) $("plan").value = JSON.stringify(q.plan, null, 2); };
  $("plan-go").onclick = async () => {
    let plan;
    try { plan = JSON.parse($("plan").value); } catch (err) { $("plan-out").innerHTML = `<p class="gx-card-warn">The plan is not JSON: ${esc(err.message)}</p>`; return; }
    $("plan-out").innerHTML = `<p class="gx-meta">Running…</p>`;
    try { const r = await scale("query", { plan }); $("plan-out").innerHTML = resultHtml(r); wireIds($("plan-out")); rowsMatch(r); }
    catch (err) { $("plan-out").innerHTML = `<p class="gx-card-warn">${esc(err.message)}</p>`; }
  };
}

// ------------------------------------------------------------------------------------------ answers in words
// The API key stays in this browser: sessionStorage, or localStorage when the reader asks to remember it.
const store = { get(k) { try { return localStorage.getItem(k) || sessionStorage.getItem(k) || ""; } catch { return ""; } },
  set(k, v, keep) { try { (keep ? localStorage : sessionStorage).setItem(k, v); if (!keep) localStorage.removeItem(k); } catch { /* storage off */ } } };
const keyState = () => $("settings").classList.toggle("on", !!store.get("scale-api-key"));
$("api-key").value = store.get("scale-api-key");
$("model").value = store.get("scale-model") || "claude-opus-5-5";
$("remember-key").checked = (() => { try { return !!localStorage.getItem("scale-api-key"); } catch { return false; } })();
$("settings").onclick = () => $("key-dialog").showModal();
$("key-save").onclick = () => { store.set("scale-api-key", $("api-key").value.trim(), $("remember-key").checked); store.set("scale-model", $("model").value, true); keyState(); };
keyState();

const TOOLS = [
  { name: "describe", description: "The schema: labels and edge types with their properties (scale describe).",
    input_schema: { type: "object", properties: { names: { type: "array", items: { type: "string" } } }, required: [] } },
  { name: "stats", description: "The graph's units in use per property and its link patterns (scale graph stats).",
    input_schema: { type: "object", properties: {}, required: [] } },
  { name: "search", description: "Search the graph's evidence by words and meaning (scale graph search); hits lead to the records that cite them.",
    input_schema: { type: "object", properties: { query: { type: "string" }, k: { type: "integer" }, published_before: { type: "string" } }, required: ["query"] } },
  { name: "query", description: "Run a graph query plan (scale graph query): match, steps, where, return, evidence, order_by, limit, text, published_before. Returns rows, the kind of answer and the coverage.",
    input_schema: { type: "object", properties: { plan: { type: "object" } }, required: ["plan"] } },
];
const clip = (o) => { const s = typeof o === "string" ? o : JSON.stringify(o); return s.length <= RESULT_CHARS ? s : `${s.slice(0, RESULT_CHARS)}\n… (${s.length - RESULT_CHARS} more characters cut)`; };
async function runTool(block, plans) {
  const a = block.input || {};
  if (block.name === "describe") return scale("describe", { names: Array.isArray(a.names) ? a.names : [], domain: "catalysis" });
  if (block.name === "stats") return scale("stats", {});
  if (block.name === "search") {
    if (typeof a.query !== "string" || !a.query) throw new Error("search needs a query string");
    return scale("search", { query: a.query, k: Number(a.k) || 10, ...(a.published_before ? { published_before: String(a.published_before) } : {}) });
  }
  if (block.name === "query") {
    if (!a.plan || typeof a.plan !== "object") throw new Error("query needs a plan object");
    const r = await scale("query", { plan: a.plan });
    plans.push({ plan: a.plan, result: r });
    return r;
  }
  throw new Error(`no tool ${block.name}`);
}
async function ask(question) {
  const key = store.get("scale-api-key"), model = $("model").value;
  const log = [];
  const say = (line) => { log.push(line); card("Answer", `<p class="gx-meta">${log.map(esc).join("<br>")}</p>`); };
  try {
    const { default: Anthropic } = await import(SDK);
    const client = new Anthropic({ apiKey: key, dangerouslyAllowBrowser: true });
    const skill = await (await fetch("data/query-graph.md")).text();
    const system = [{ type: "text", cache_control: { type: "ephemeral" }, text: skill + "\n\n# Working here\n\nYou answer in a web page, "
      + "through the tools given (no shell). The graph is the one the user is viewing. Write the answer in Markdown: every factual "
      + "sentence from returned rows, citing record ids and evidence locators in brackets, then a **Limits** line. Keep your own "
      + "extrapolations in a separate, labelled paragraph." }];
    const messages = [{ role: "user", content: question }];
    const plans = [];
    let tokens = 0, answer = "";
    for (let turn = 0; turn < 16; turn++) {
      say(turn ? `Turn ${turn + 1}…` : "Asking the model…");
      const r = await client.beta.messages.create({
        model, max_tokens: 16000, system, tools: TOOLS, messages,
        ...(model === "claude-haiku-5-5" ? {} : { betas: ["server-side-fallback-2026-07-01"], fallbacks: "default" }),
        output_config: { effort: "medium" },
      });
      tokens += (r.usage?.input_tokens || 0) + (r.usage?.output_tokens || 0) + (r.usage?.cache_creation_input_tokens || 0);
      messages.push({ role: "assistant", content: r.content });
      answer = r.content.filter((b) => b.type === "text").map((b) => b.text).join("\n").trim() || answer;
      if (r.stop_reason === "refusal") { answer = answer || "The model declined to answer this question."; break; }
      if (r.stop_reason === "pause_turn") continue;
      const uses = r.content.filter((b) => b.type === "tool_use");
      if (!uses.length || r.stop_reason !== "tool_use") break;
      const results = [];
      for (const b of uses) {
        say(`${b.name}${b.name === "search" ? `: ${b.input?.query || ""}` : ""}`);
        try { results.push({ type: "tool_result", tool_use_id: b.id, content: clip(await runTool(b, plans)) }); }
        catch (err) { results.push({ type: "tool_result", tool_use_id: b.id, content: String(err.message), is_error: true }); }
      }
      messages.push({ role: "user", content: results });
    }
    const last = plans[plans.length - 1];
    if (last?.result) rowsMatch(last.result);
    card("Answer", `${idLinks(md(answer || "No answer."))}
      ${last ? `<details><summary>Data (${last.result?.row_count ?? 0} rows)</summary>${resultHtml(last.result || {})}</details>` : ""}
      ${plans.length ? `<details><summary>How it was answered (${plans.length} plan${plans.length > 1 ? "s" : ""})</summary>${plans.map((p, i) =>
        `<p class="gx-meta">Plan ${i + 1}: ${esc(p.result?.status || p.result?.error || "?")}, ${p.result?.row_count ?? 0} rows</p><pre>${esc(JSON.stringify(p.plan, null, 1))}</pre>`).join("")}</details>` : ""}
      <p class="gx-meta">${esc(model)} · about ${tokens.toLocaleString()} tokens</p>`);
  } catch (err) { card("Answer", `<p class="gx-card-warn">${esc(err.message || err)}</p>`); }
}

// ------------------------------------------------------------------------------------------ controls
$("search-form").onsubmit = (e) => {
  e.preventDefault();
  const q = $("search-input").value.trim();
  if (!q || !G) return;
  store.get("scale-api-key") ? ask(q) : search(q);
};
$("query-btn").onclick = () => G && queryCard();
$("labels-btn").onclick = () => { S.linkLabels = linkLabelsShown() ? "off" : "on"; draw(); };
$("unhide-btn").onclick = () => { S.hidden.clear(); draw(); };
const menus = [[$("layout-btn"), $("layout-menu")], [$("export-btn"), $("export-menu")]];
for (const [btn, box] of menus) btn.onclick = (e) => { e.stopPropagation(); for (const [, b] of menus) if (b !== box) b.hidden = true; box.hidden = !box.hidden; btn.setAttribute("aria-expanded", String(!box.hidden)); };
document.addEventListener("click", () => { for (const [, b] of menus) b.hidden = true; });
$("layout-menu").querySelectorAll("[data-layout]").forEach((b) => (b.onclick = () => {
  S.layout = b.dataset.layout;
  $("layout-label").textContent = { force: "Force", hierarchical: "Hierarchical", radial: "Radial" }[S.layout];
  $("layout-menu").querySelectorAll("[data-layout]").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
  applyLayout(S.layout);
}));
$("zoom-in").onclick = () => S.zoom && svg.transition().duration(200).call(S.zoom.scaleBy, 1.3);
$("zoom-out").onclick = () => S.zoom && svg.transition().duration(200).call(S.zoom.scaleBy, 1 / 1.3);
$("fit").onclick = () => fit();
$("locate").onclick = () => { const n = S.nodes.find((x) => x.id === S.selected); if (n) { S.viewMoved = true; svg.transition().duration(450).call(S.zoom.translateTo, n.x, n.y); } };
$("refresh").onclick = () => { if (!G) return; S.pos.clear(); S.nodes = []; draw(); };
function download(file, blob) { const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = file; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); }
function svgText() {
  const clone = svg.node().cloneNode(true), cs = getComputedStyle(document.documentElement);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.querySelectorAll(".gx-node circle").forEach((c) => { c.setAttribute("stroke", cs.getPropertyValue("--node-stroke")); c.setAttribute("stroke-width", "1.5"); });
  clone.querySelectorAll(".gx-node text").forEach((t) => { t.setAttribute("font-size", "11"); t.setAttribute("text-anchor", "middle"); t.setAttribute("fill", cs.getPropertyValue("--fg")); t.setAttribute("font-family", "Inter, sans-serif"); });
  clone.querySelectorAll("#links line").forEach((l) => l.setAttribute("stroke-width", "1.6"));
  return new XMLSerializer().serializeToString(clone);
}
$("export-menu").querySelectorAll("[data-export]").forEach((b) => (b.onclick = () => {
  if (!G) return;
  const kind = b.dataset.export, csv = (rows) => rows.map((r) => r.map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  if (kind === "svg") download(`${G.entry.id}.svg`, new Blob([svgText()], { type: "image/svg+xml" }));
  if (kind === "nodes-csv") download(`${G.entry.id}-nodes.csv`, new Blob([csv([["id", "label", "name"], ...S.nodes.map((n) => [n.id, n.label, n.name])])], { type: "text/csv" }));
  if (kind === "edges-csv") download(`${G.entry.id}-relationships.csv`, new Blob([csv([["id", "type", "source", "target"], ...S.links.map((e) => [e.id, e.type, e.source.id ?? e.source, e.target.id ?? e.target])])], { type: "text/csv" }));
  if (kind === "graph") download(`${G.entry.id}.json`, new Blob([JSON.stringify(G.doc)], { type: "application/json" }));
  if (kind === "png") {
    const [W, H] = size(), img = new Image(), url = URL.createObjectURL(new Blob([svgText()], { type: "image/svg+xml" }));
    img.onload = () => {
      const c = document.createElement("canvas"); c.width = W * 2; c.height = H * 2;
      const ctx = c.getContext("2d"); ctx.fillStyle = getComputedStyle(document.body).backgroundColor; ctx.fillRect(0, 0, c.width, c.height);
      ctx.drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(url);
      c.toBlob((blob) => download(`${G.entry.id}.png`, blob));
    };
    img.src = url;
  }
}));
function panel(which, on) {
  $("grid").classList.toggle(`${which}-off`, !on);
  $(`${which}-show`).hidden = on;
}
$("rail-collapse").onclick = () => panel("rail", false);
$("rail-show").onclick = () => panel("rail", true);
$("inspector-collapse").onclick = () => panel("inspector", false);
$("inspector-show").onclick = () => panel("inspector", true);
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", (e) => { document.documentElement.dataset.theme = e.matches ? "dark" : "light"; });

start().catch((err) => status(`Could not start: ${err.message}`));
