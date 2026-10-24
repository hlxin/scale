// The graph explorer: pick a graph of this repository (data/graphs.json, written by `scale site build`) or open a file;
// see it, its record types and the neighbourhood of any record, with each record's properties and verbatim evidence;
// search its evidence, run query plans or ask a question. Search, plans and descriptions run SCALE's own code in a
// worker (worker.js); a question runs the query-graph skill with the reader's own API key.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const md = (s) => DOMPurify.sanitize(marked.parse(String(s || "")));
const WHOLE_MAX = 400;            // a graph this small opens whole; a larger one on its map of record types
const VIEW_MAX = 160;             // the links drawn for a link type
const TYPE_MAX = 60;              // the records of a type drawn, each with its own links
const CROWDED = 30;               // more links than this: their names show only around the selected record
const NEIGHBOURS_MAX = 80;        // the links drawn around a record
const RESULT_CHARS = 40000;       // the longest tool result handed back to the model (as the web service does)
const SDK = "https://cdn.jsdelivr.net/npm/@anthropic-ai/sdk@0.133.0/+esm";
const PALETTE = ["#4e9de8", "#f28e2b", "#e15759", "#59a14f", "#b07aa1", "#edc948", "#76b7b2", "#ff9da7", "#9c755f",
  "#8cd17d", "#d37295", "#a0cbe8", "#f1ce63", "#86bcb6", "#bab0ac", "#d4a6c8", "#fabfd2", "#b6992d", "#499894", "#e19d9a"];

let G = null;                     // {id, file, doc, byId, out, inn, labels, rels, colour, entry}
let cy = null;
let manifest = [];
let questions = [];
let view = { kind: "map" };       // what the canvas shows: map | type | rel | focus | whole
let layoutName = "force";
let showLabels = true;
let selected = null;
let mode = "search";

// ------------------------------------------------------------------------------------------ the worker (SCALE)
const worker = new Worker("worker.js");
const pending = new Map();
let seq = 0;
let pythonReady = false;
worker.onmessage = (e) => {
  const m = e.data;
  if (m.status) {
    pythonReady = m.status === "ready";
    setStatus(pythonReady ? (G && G.loaded ? graphStatus() : "SCALE is ready in this browser.") : m.status);
    return;
  }
  const p = pending.get(m.id);
  if (!p) return;
  pending.delete(m.id);
  m.ok ? p.resolve(m.result) : p.reject(new Error(m.error));
};
function rpc(msg) {
  const id = ++seq;
  return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); worker.postMessage({ id, ...msg }); });
}
const scale = (tool, args) => rpc({ op: "call", tool, args: { ...args, ...(tool === "describe" ? {} : { path: G.file }) } });
const setStatus = (text) => { $("status").textContent = text; };
const graphStatus = () => `${G.entry.title}: ${G.doc.nodes.length} records, ${G.doc.links.length} links. Ready to search and query.`;

// ------------------------------------------------------------------------------------------ the graphs rail
const KIND = { graphs: ["curated", "var(--ok)"], examples: ["example", "var(--brand)"], domain: ["synthetic", "var(--synthetic)"] };
const kindOf = (e) => KIND[(e.from || "").split("/")[0]] || ["file", "var(--fg-muted)"];

async function start() {
  try { manifest = (await (await fetch("data/graphs.json")).json()).graphs || []; } catch { manifest = []; }
  renderGraphs();
  window.onhashchange = () => openFromHash();
  $("graph-file").onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try { await openGraph({ id: f.name.replace(/\W+/g, "-"), title: f.name, from: "" }, await f.text()); questions = []; renderGraphs(); }
    catch (err) { alert(`not a graph: ${err.message}`); }
  };
  await openFromHash();
}

function renderGraphs() {
  const list = [...manifest];
  if (G && !manifest.includes(G.entry)) list.unshift(G.entry);
  $("graphs").innerHTML = list.map((e) => {
    const [k, c] = kindOf(e), active = G && G.entry === e;
    const details = active ? `<div class="sx-graph-details">
        ${k === "synthetic" ? `<p class="sx-warn">Synthetic example: invented to show the schema, not evidence about the world.</p>` : ""}
        <p>${esc(((G.doc.graph || {}).description || e.description || "").slice(0, 420))}</p>
        <dl><dt>Records</dt><dd>${G.doc.nodes.length.toLocaleString()}</dd><dt>Links</dt><dd>${G.doc.links.length.toLocaleString()}</dd>
          <dt>Schema</dt><dd>scale-catal ${esc((G.doc.graph || {}).schema_version || "?")}</dd>
          <dt>Questions</dt><dd>${questions.length}</dd>
          ${e.from ? `<dt>Source</dt><dd><a href="https://github.com/hlxin/scale/tree/main/${esc(e.from)}">${esc(e.from)}</a></dd>` : ""}</dl>
      </div>` : "";
    return `<div class="sx-graph${active ? " active" : ""}" role="listitem">
      <button class="sx-graph-row" type="button" data-id="${esc(e.id)}" title="${esc(e.title)}">
        <span class="sx-graph-name">${esc(e.title)}</span><span class="sx-badge" style="--badge:${c}">${k}</span></button>${details}</div>`;
  }).join("") || `<p class="sx-muted">No graphs are listed: open a file.</p>`;
  $("graphs").querySelectorAll(".sx-graph-row").forEach((b) => (b.onclick = () => {
    const e = manifest.find((x) => x.id === b.dataset.id);
    if (e) location.hash = `g=${encodeURIComponent(e.id)}`;
  }));
}

async function openFromHash() {
  const want = new URLSearchParams(location.hash.slice(1)).get("g");
  const entry = manifest.find((g) => g.id === want) || manifest[0];
  if (!entry || (G && G.entry === entry)) return;
  setStatus(`Loading ${entry.title}…`);
  $("empty").hidden = false;
  $("empty").innerHTML = `<p>Loading ${esc(entry.title)}…</p>`;
  const text = await (await fetch(entry.path)).text();
  try { questions = await (await fetch(`data/questions/${entry.id}.json`)).json(); } catch { questions = []; }
  await openGraph(entry, text);
  renderGraphs();
}

async function openGraph(entry, text) {
  const doc = JSON.parse(text);
  if (!Array.isArray(doc.nodes) || !Array.isArray(doc.links)) throw new Error("no nodes and links");
  const byId = new Map(doc.nodes.map((n) => [n.id, n]));
  const out = new Map(), inn = new Map(), labels = new Map(), rels = new Map();
  for (const n of doc.nodes) labels.set(n.label, (labels.get(n.label) || 0) + 1);
  for (const e of doc.links) {
    (out.get(e.source) || out.set(e.source, []).get(e.source)).push(e);
    (inn.get(e.target) || inn.set(e.target, []).get(e.target)).push(e);
    rels.set(e.type, (rels.get(e.type) || 0) + 1);
  }
  const order = [...labels].sort((a, b) => b[1] - a[1]).map(([l]) => l);
  const colour = new Map(order.map((l, i) => [l, PALETTE[i % PALETTE.length]]));
  G = { id: entry.id, file: `${entry.id}.json`, doc, byId, out, inn, labels, rels, colour, entry };
  selected = null;
  renderLegend();
  showLegend();
  if (doc.nodes.length <= WHOLE_MAX) showWhole(); else showMap();      // drawing needs no Python: at once
  const g = G;
  await rpc({ op: "put", name: G.file, text }).then(() => { g.loaded = true; })
    .catch((err) => setStatus(`SCALE could not load the graph: ${err.message}`));
  if (G !== g) return;                                                  // another graph was opened meanwhile
  setStatus(graphStatus());
  warm(entry);
}

// The first search of a graph builds its evidence index (seconds for thousands of quotes); build it now, while the
// reader looks at the graph, so a search answers at once. The toolkit keeps it with the loaded graph.
async function warm(entry) {
  if (!G.doc.nodes.some((n) => (n.props?.evidence || []).some((e) => e.quote))) return;
  const note = () => G && G.entry === entry && setStatus(`Indexing the evidence of ${entry.title}…`);
  if (pythonReady) note(); else setTimeout(note, 4000);
  try { await scale("search", { query: "catalyst", k: 1 }); } catch { /* reported when the reader searches */ }
  if (G && G.entry === entry) setStatus(graphStatus());
}

// ------------------------------------------------------------------------------------------ names and values
const name = (n) => (n && (n.props?.name || n.props?.title || n.props?.formula || n.id.split("/").pop())) || "?";
const colourOf = (label) => (G && G.colour.get(label)) || "#9aa1ad";
const degree = (id) => (G.out.get(id)?.length || 0) + (G.inn.get(id)?.length || 0);
function value(v) {
  if (v === null || v === undefined) return "";
  if (Array.isArray(v)) return v.map(value).join("; ");
  if (typeof v !== "object") return esc(v);
  if ("status" in v && (v.status !== "present" || "value" in v || "text_value" in v || "lower" in v || "upper" in v || "boolean_value" in v)) {
    if (v.status !== "present") return `<span class="sx-subtle">${esc(v.status)}${v.missing_reason ? ` (${esc(v.missing_reason)})` : ""}</span>`;
    const num = "value" in v ? v.value : "lower" in v || "upper" in v ? `${v.lower ?? ""}–${v.upper ?? ""}` : v.text_value ?? v.boolean_value;
    const shown = `${esc(num)}${v.unit && v.unit !== "1" ? ` ${esc(v.unit)}` : ""}`;
    return v.as_reported && String(v.as_reported) !== String(num) ? `${shown} <span class="sx-subtle">(as reported: ${esc(v.as_reported)})</span>` : shown;
  }
  return `<code>${esc(JSON.stringify(v))}</code>`;
}
// a record id inside a shown value becomes a link to the record
const idLinks = (html) => html.replace(/((?:ex|scale|[a-z][a-z0-9-]*):[A-Za-z0-9_.\/#-]+)/g,
  (m, id) => (G && G.byId.has(id) ? `<a href="#" data-id="${esc(id)}">${esc(id)}</a>` : m));
const wireIds = (root) => root.querySelectorAll("a[data-id]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); focus(a.dataset.id); }));

// ------------------------------------------------------------------------------------------ the canvas
function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function cyStyle() {
  return [
    { selector: "node", style: { "background-color": "data(c)", label: "data(l)", width: "data(s)", height: "data(s)",
      "font-size": 10, "font-family": "Inter, system-ui, sans-serif", color: css("--fg-muted"), "text-valign": "bottom",
      "text-margin-y": 4, "text-wrap": "ellipsis", "text-max-width": 130, "border-width": 0, "min-zoomed-font-size": 6 } },
    { selector: "node.type", style: { "font-size": 13, "min-zoomed-font-size": 0, color: css("--fg"), "text-max-width": 180 } },
    { selector: "node:selected, node.focus", style: { "border-width": 3, "border-color": css("--brand"), color: css("--fg") } },
    { selector: "edge", style: { width: 1.2, "line-color": css("--edge"), "target-arrow-shape": "triangle", "target-arrow-color": css("--edge"),
      "arrow-scale": 0.8, "curve-style": "bezier", label: showLabels ? "data(l)" : "", "font-size": 8, color: css("--edge-label"),
      "text-rotation": "autorotate", "text-background-color": css("--bg"), "text-background-opacity": 0.7, "text-background-padding": 1,
      "min-zoomed-font-size": 7 } },
    { selector: "edge.dim", style: { "text-opacity": 0 } },
    { selector: "edge:selected", style: { "line-color": css("--brand"), "target-arrow-color": css("--brand"), width: 2 } },
  ];
}
function layoutFor(name, focusId) {
  if (name === "hierarchical") return { name: "breadthfirst", directed: true, spacingFactor: 1.1, animate: false };
  if (name === "radial") return { name: "concentric", animate: false, minNodeSpacing: 14,
    concentric: (n) => (focusId ? (n.id() === focusId ? 100 : 1) : n.degree()), levelWidth: () => (focusId ? 1 : 2) };
  if (name === "map") return { name: "cose", animate: false, nodeRepulsion: 160000, idealEdgeLength: 150, nodeOverlap: 60,
    componentSpacing: 100, gravity: 0.3, numIter: 1500 };
  return { name: "cose", animate: false, nodeRepulsion: 40000, idealEdgeLength: 110, nodeOverlap: 16, componentSpacing: 80,
    gravity: 0.2, numIter: 1500 };
}
function draw(elements, hint) {
  $("empty").hidden = true;
  if (cy) cy.destroy();
  cy = cytoscape({ container: $("cy"), elements, style: cyStyle(), wheelSensitivity: 0.3, maxZoom: 2.2, minZoom: 0.04,
    layout: layoutFor(view.kind === "map" && layoutName === "force" ? "map" : layoutName, view.kind === "focus" ? view.id : null) });
  dimLabels();
  cy.on("tap", "node", (ev) => {
    const id = ev.target.id();
    if (id.startsWith("L:")) return showType(id.slice(2));
    select(id);
  });
  cy.on("dbltap", "node", (ev) => { if (!ev.target.id().startsWith("L:")) expand(ev.target.id()); });
  cy.on("tap", "edge", (ev) => { const l = ev.target.data("link"); if (l) showDetails(G.doc.links.find((e) => e.id === l)); });
  if (selected && cy.getElementById(selected).length) cy.getElementById(selected).select();
  $("hint").textContent = hint || "Circle size grows with links · drag to rearrange · scroll to zoom · double-click a record to expand its neighbourhood";
  $("locate").disabled = !selected;
  summary();
}
// crowded: link names only on the selected record's links
function dimLabels() {
  if (!cy) return;
  const crowded = cy.edges().length > CROWDED;
  cy.edges().toggleClass("dim", crowded);
  if (crowded && selected && cy.getElementById(selected).length) cy.getElementById(selected).connectedEdges().removeClass("dim");
}
function summary() {
  const n = cy ? cy.nodes().length : 0, m = cy ? cy.edges().length : 0;
  $("summary").textContent = view.kind === "map" ? `Displaying ${n} record types and ${m} link patterns.`
    : `Displaying ${n.toLocaleString()} records, ${m.toLocaleString()} links (of ${G.doc.nodes.length.toLocaleString()} and ${G.doc.links.length.toLocaleString()}).`;
}
const nodeEl = (n, focusId) => ({ data: { id: n.id, l: name(n), c: colourOf(n.label), s: 14 + Math.min(30, 4 * Math.sqrt(degree(n.id))) },
  classes: n.id === focusId ? "focus" : "" });
const linkEl = (e) => ({ data: { id: `e:${e.id}`, source: e.source, target: e.target, l: e.type, link: e.id } });
// links to a Source from every record (REPORTED_IN) would bury the rest: drawn only from the source's own view
const drawn = (e, keepReported) => e.type !== "REPORTED_IN" || keepReported;

function showMap() {
  view = { kind: "map" };
  const pairs = new Map();
  for (const e of G.doc.links) {
    const a = G.byId.get(e.source)?.label, b = G.byId.get(e.target)?.label;
    if (!a || !b || !drawn(e)) continue;
    const k = `${a}\u0000${e.type}\u0000${b}`;
    pairs.set(k, (pairs.get(k) || 0) + 1);
  }
  const max = Math.max(...G.labels.values(), 1);
  const els = [...G.labels].map(([l, n]) => ({ data: { id: `L:${l}`, l: `${l} (${n})`, c: colourOf(l), s: 18 + 44 * Math.sqrt(n / max) }, classes: "type" }));
  for (const [k, n] of pairs) {
    const [a, t, b] = k.split("\u0000");
    els.push({ data: { id: `E:${k}`, source: `L:${a}`, target: `L:${b}`, l: `${t} ${n}` } });
  }
  draw(els, "The record types and how they link · click a type to see its records");
}
function showWhole() {
  view = { kind: "whole" };
  draw([...G.doc.nodes.map((n) => nodeEl(n)), ...G.doc.links.filter((e) => drawn(e)).map(linkEl)]);
}
function showSubset(ids, links, v, hint) {
  view = v;
  const els = [...ids].map((id) => G.byId.get(id)).filter(Boolean).map((n) => nodeEl(n, v.id));
  draw([...els, ...links.map(linkEl)], hint);
}
function showType(label) {
  const all = G.doc.nodes.filter((n) => n.label === label);
  const own = all.slice(0, TYPE_MAX);
  const links = own.flatMap((n) => [...(G.out.get(n.id) || []), ...(G.inn.get(n.id) || [])].filter((e) => drawn(e)).slice(0, 12));
  const ids = new Set([...own.map((n) => n.id), ...links.flatMap((e) => [e.source, e.target])]);
  showSubset(ids, [...new Map(links.map((e) => [e.id, e])).values()], { kind: "type", label },
    `${label}: ${own.length} of ${all.length} records, with what they link to · click one for its details`);
  markPills(label, null);
  listType(label, all);
}
function showRel(type) {
  const links = G.doc.links.filter((e) => e.type === type).slice(0, VIEW_MAX);
  const ids = new Set(links.flatMap((e) => [e.source, e.target]));
  showSubset(ids, links, { kind: "rel", type }, `${type}: ${links.length} of ${G.rels.get(type)} links`);
  markPills(null, type);
}
function focus(id) {
  if (!G.byId.has(id)) { const l = G.doc.links.find((e) => e.id === id); if (l) showDetails(l); return; }
  const links = [...(G.out.get(id) || []), ...(G.inn.get(id) || [])].filter((e) => drawn(e, G.byId.get(id).label === "Source"));
  const keep = links.slice(0, NEIGHBOURS_MAX);
  selected = id;
  showSubset(new Set([id, ...keep.flatMap((e) => [e.source, e.target])]), keep, { kind: "focus", id },
    `${name(G.byId.get(id))}: ${keep.length}${links.length > keep.length ? ` of ${links.length}` : ""} links · double-click a record to expand`);
  select(id);
}
function expand(id) {
  if (!cy) return;
  const links = [...(G.out.get(id) || []), ...(G.inn.get(id) || [])].filter((e) => drawn(e)).slice(0, NEIGHBOURS_MAX);
  const add = [];
  for (const e of links) {
    for (const n of [e.source, e.target]) if (!cy.getElementById(n).length && G.byId.has(n)) { add.push(nodeEl(G.byId.get(n))); cy.add(add[add.length - 1]); }
    if (!cy.getElementById(`e:${e.id}`).length) cy.add(linkEl(e));
  }
  cy.layout(layoutFor(layoutName, id)).run();
  summary();
  select(id);
}
function select(id) {
  selected = id;
  if (cy) { cy.elements().unselect(); cy.getElementById(id).select(); dimLabels(); }
  $("locate").disabled = false;
  showDetails(G.byId.get(id));
}

// ------------------------------------------------------------------------------------------ the details panel
function renderLegend() {
  $("kinds").innerHTML = [...G.labels].sort((a, b) => b[1] - a[1]).map(([l, n]) =>
    `<button class="sx-pill" data-l="${esc(l)}" style="--pill:${colourOf(l)}">${esc(l)} <span class="n">${n}</span></button>`).join("");
  $("rels").innerHTML = [...G.rels].sort((a, b) => b[1] - a[1]).map(([t, n]) =>
    `<button class="sx-pill" data-t="${esc(t)}">${esc(t)} <span class="n">${n}</span></button>`).join("");
  $("kinds").querySelectorAll(".sx-pill").forEach((b) => (b.onclick = () => showType(b.dataset.l)));
  $("rels").querySelectorAll(".sx-pill").forEach((b) => (b.onclick = () => showRel(b.dataset.t)));
  $("type-list")?.remove();
}
function markPills(label, type) {
  $("kinds").querySelectorAll(".sx-pill").forEach((b) => b.classList.toggle("active", b.dataset.l === label));
  $("rels").querySelectorAll(".sx-pill").forEach((b) => b.classList.toggle("active", b.dataset.t === type));
  if (!label) $("type-list")?.remove();
  showLegend();
}
function listType(label, all) {
  $("type-list")?.remove();
  const box = document.createElement("div");
  box.id = "type-list";
  box.innerHTML = `<h3 class="sx-section-title">${esc(label)} records</h3><input class="sx-filter" placeholder="Filter by name"><ul class="sx-list"></ul>`;
  $("legend").appendChild(box);
  const render = (q) => {
    const shown = all.filter((n) => !q || `${name(n)} ${n.id}`.toLowerCase().includes(q)).slice(0, 300);
    box.querySelector("ul").innerHTML = shown.map((n) => `<li><a href="#" data-id="${esc(n.id)}">${esc(name(n))}</a></li>`).join("")
      + (all.length > shown.length ? `<li class="sx-muted">… type to narrow (${all.length} in all)</li>` : "");
    wireIds(box);
  };
  box.querySelector("input").oninput = (e) => render(e.target.value.trim().toLowerCase());
  render("");
}
function showLegend() {
  $("legend").hidden = false;
  $("record").hidden = true;
  $("inspector-back").hidden = true;
  $("inspector-title").textContent = "Record types & links";
}
function showDetails(rec) {
  if (!rec) return;
  const p = rec.props || {};
  const isLink = "source" in rec && "target" in rec;
  const head = isLink
    ? `<div class="sx-record-head"><span class="sx-pill" style="--pill:var(--brand)">${esc(rec.type)}</span></div>
       <p><a href="#" data-id="${esc(rec.source)}">${esc(name(G.byId.get(rec.source)))}</a> → <a href="#" data-id="${esc(rec.target)}">${esc(name(G.byId.get(rec.target)))}</a></p>`
    : `<div class="sx-record-head"><span class="sx-pill" style="--pill:${colourOf(rec.label)}">${esc(rec.label)}</span>
         <span class="sx-record-name">${esc(name(rec))}</span></div>`;
  const rows = Object.entries(p).filter(([k]) => k !== "evidence")
    .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${idLinks(value(v))}</td></tr>`).join("");
  const ev = (p.evidence || []).map((e) => {
    const src = G.byId.get(e.source);
    const where = [src ? name(src) : e.source, src?.props?.year, e.locator].filter(Boolean).map(esc).join(" · ");
    return `<blockquote class="sx-evidence">${e.quote ? esc(e.quote) : `<span class="sx-subtle">No quote kept.</span>`}<div class="sx-meta">${where}</div></blockquote>`;
  }).join("");
  let neighbours = "";
  if (!isLink) {
    const groups = new Map();
    for (const e of G.out.get(rec.id) || []) (groups.get(`→ ${e.type}`) || groups.set(`→ ${e.type}`, []).get(`→ ${e.type}`)).push(e.target);
    for (const e of G.inn.get(rec.id) || []) (groups.get(`← ${e.type}`) || groups.set(`← ${e.type}`, []).get(`← ${e.type}`)).push(e.source);
    const total = [...groups.values()].reduce((a, v) => a + v.length, 0);
    neighbours = `<section class="sx-section"><h3>Neighbours <span class="sx-count">${total}</span></h3><ul class="sx-neighbours">${
      [...groups].map(([g, ids]) => ids.slice(0, 40).map((id) => `<li><span class="sx-rel">${esc(g)}</span><a href="#" data-id="${esc(id)}">${esc(name(G.byId.get(id)))}</a></li>`).join("")
        + (ids.length > 40 ? `<li class="sx-muted">… ${ids.length - 40} more ${esc(g)}</li>` : "")).join("")}</ul></section>`;
  }
  $("record").innerHTML = `${head}<div class="sx-id">${esc(rec.id)}</div>
    <table class="sx-props"><thead><tr><th>Key</th><th>Value</th></tr></thead><tbody>${rows}</tbody></table>
    ${ev ? `<section class="sx-section"><h3>Evidence <span class="sx-count">${(p.evidence || []).length}</span></h3>${ev}</section>` : ""}
    ${neighbours}
    ${isLink ? "" : `<div class="sx-record-actions"><button class="sx-btn sx-btn-tiny" id="act-expand">Expand neighbourhood</button>
      <button class="sx-btn sx-btn-tiny" id="act-focus">Focus</button><button class="sx-btn sx-btn-tiny" id="act-copy">Copy JSON</button></div>`}`;
  wireIds($("record"));
  if (!isLink) {
    $("act-expand").onclick = () => expand(rec.id);
    $("act-focus").onclick = () => focus(rec.id);
    $("act-copy").onclick = () => navigator.clipboard?.writeText(JSON.stringify(rec, null, 1));
  }
  $("legend").hidden = true;
  $("record").hidden = false;
  $("inspector-back").hidden = false;
  $("inspector-title").textContent = isLink ? "Link details" : "Record details";
  if (document.querySelector(".sx-grid").classList.contains("inspector-off")) togglePanel("inspector", true);
}
$("inspector-back").onclick = () => showLegend();

// ------------------------------------------------------------------------------------------ the results card
function card(title, html) {
  $("card-title").textContent = title;
  $("card-body").innerHTML = html;
  $("card").hidden = false;
  $("card").classList.remove("collapsed");
  wireIds($("card-body"));
}
$("card-close").onclick = () => { $("card").hidden = true; };
$("card-collapse").onclick = () => $("card").classList.toggle("collapsed");

async function search(q) {
  card("Evidence search", `<p class="sx-meta">Searching…</p>`);
  try {
    const r = await scale("search", { query: q, k: 25 });
    if (r.error) throw new Error(r.error);
    const hits = r.hits || [];
    card(`Evidence search · ${hits.length} hits`, hits.length ? hits.map((h) => `<div class="sx-hit" data-id="${esc(h.record)}">
        <div class="sx-quote">“${esc(h.text)}”</div>
        <div class="sx-meta">${esc(h.label || "")}: ${esc(h.record_name || h.record)} · ${esc(name(G.byId.get(h.source)))}${h.source_year ? ` (${esc(h.source_year)})` : ""}, ${esc(h.locator || "")} · ${Number(h.score || 0).toFixed(3)}</div></div>`).join("")
      : `<p>No evidence matches “${esc(q)}”.</p>`);
    $("card-body").querySelectorAll(".sx-hit").forEach((el) => (el.onclick = () => focus(el.dataset.id)));
  } catch (err) { card("Evidence search", `<p class="sx-card-warn">${esc(err.message)}</p>`); }
}

function resultHtml(r) {
  if (r.error) return `<p class="sx-card-warn">${esc(r.error)}</p>`;
  const rows = r.rows || [];
  const cols = [...new Set(rows.flatMap((x) => Object.keys(x.values || {})))];
  const table = rows.length ? `<table class="sx-rows"><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr>${rows.slice(0, 200).map((x) =>
    `<tr>${cols.map((c) => `<td>${idLinks(value(x.values?.[c]))}</td>`).join("")}</tr>`).join("")}</table>` : "";
  const lim = (r.limitations || []).map((l) => `<li>${esc(l)}</li>`).join("");
  return `<p><strong>${esc(r.status)}</strong> · ${r.row_count ?? rows.length} rows${(r.excluded || []).length ? ` · ${r.excluded.length} left out` : ""}</p>
    ${table}${lim ? `<details><summary>Limitations</summary><ul>${lim}</ul></details>` : ""}
    <details><summary>Full result</summary><pre>${esc(JSON.stringify(r, null, 1).slice(0, 60000))}</pre></details>`;
}
function queryCard(planText) {
  const opts = `<option value="">${questions.length ? "Questions that run on this graph…" : "No saved questions for this graph"}</option>`
    + questions.map((q, i) => `<option value="${i}">${esc(q.id)}: ${esc(String(q.question || "").slice(0, 100))}</option>`).join("");
  card("Query plan", `<select id="plan-pick">${opts}</select>
    <textarea id="plan" rows="9" spellcheck="false" placeholder='{"match": {"label": "CatalyticTest", "as": "t"}, "return": ["t.name"], "limit": 10}'>${esc(planText || "")}</textarea>
    <p><button class="sx-btn sx-btn-primary" id="plan-go" type="button">Run</button>
      <span class="sx-meta">match, steps, where, return, evidence, limit · <a href="https://github.com/hlxin/scale/blob/main/docs/querying.md">docs/querying.md</a></span></p>
    <div id="plan-out"></div>`);
  $("plan-pick").onchange = (e) => { const q = questions[Number(e.target.value)]; if (q) $("plan").value = JSON.stringify(q.plan, null, 2); };
  $("plan-go").onclick = async () => {
    let plan;
    try { plan = JSON.parse($("plan").value); } catch (err) { $("plan-out").innerHTML = `<p class="sx-card-warn">The plan is not JSON: ${esc(err.message)}</p>`; return; }
    $("plan-out").innerHTML = `<p class="sx-meta">Running…</p>`;
    try { $("plan-out").innerHTML = resultHtml(await scale("query", { plan })); wireIds($("plan-out")); }
    catch (err) { $("plan-out").innerHTML = `<p class="sx-card-warn">${esc(err.message)}</p>`; }
  };
}

// ------------------------------------------------------------------------------------------ asking a question
// The API key stays in this browser: sessionStorage, or localStorage when the reader asks to remember it.
const store = { get(k) { try { return localStorage.getItem(k) || sessionStorage.getItem(k) || ""; } catch { return ""; } },
  set(k, v, keep) { try { (keep ? localStorage : sessionStorage).setItem(k, v); if (!keep) localStorage.removeItem(k); } catch { /* storage off */ } } };
$("api-key").value = store.get("scale-api-key");
$("model").value = store.get("scale-model") || "claude-opus-5-5";
$("remember-key").checked = (() => { try { return !!localStorage.getItem("scale-api-key"); } catch { return false; } })();
$("settings").onclick = () => $("key-dialog").showModal();
$("key-save").onclick = () => {
  store.set("scale-api-key", $("api-key").value.trim(), $("remember-key").checked);
  store.set("scale-model", $("model").value, true);
};

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
  const key = $("api-key").value.trim() || store.get("scale-api-key"), model = $("model").value;
  if (!key) { $("key-dialog").showModal(); return; }
  const log = [];
  const say = (line) => { log.push(line); card("Answer", `<p class="sx-meta">${log.map(esc).join("<br>")}</p>`); };
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
    card("Answer", `${idLinks(md(answer || "No answer."))}
      ${last ? `<details><summary>Data (${last.result?.row_count ?? 0} rows)</summary>${resultHtml(last.result || {})}</details>` : ""}
      ${plans.length ? `<details><summary>How it was answered (${plans.length} plan${plans.length > 1 ? "s" : ""})</summary>${plans.map((p, i) =>
        `<p class="sx-meta">Plan ${i + 1}: ${esc(p.result?.status || p.result?.error || "?")}, ${p.result?.row_count ?? 0} rows</p><pre>${esc(JSON.stringify(p.plan, null, 1))}</pre>`).join("")}</details>` : ""}
      <p class="sx-meta">${esc(model)} · about ${tokens.toLocaleString()} tokens</p>`);
  } catch (err) {
    card("Answer", `<p class="sx-card-warn">${esc(err.message || err)}</p>`);
  }
}

// ------------------------------------------------------------------------------------------ toolbar and controls
document.querySelectorAll(".sx-mode-btn").forEach((b) => (b.onclick = () => {
  mode = b.dataset.mode;
  document.querySelectorAll(".sx-mode-btn").forEach((x) => x.classList.toggle("active", x === b));
  $("search-input").placeholder = mode === "ask" ? "Ask a question of this graph, e.g. Which catalysts were tested below 250 °C?"
    : "Search the evidence, e.g. copper zinc catalyst";
  $("search-input").focus();
}));
$("search-form").onsubmit = (e) => {
  e.preventDefault();
  const q = $("search-input").value.trim();
  if (!q || !G) return;
  mode === "ask" ? ask(q) : search(q);
};
$("map-btn").onclick = () => { selected = null; markPills(null, null); showMap(); };
$("query-btn").onclick = () => queryCard($("plan")?.value);
$("labels-btn").onclick = () => {
  showLabels = !showLabels;
  $("labels-btn").setAttribute("aria-pressed", String(showLabels));
  if (cy) cy.style(cyStyle());
};
function menu(btn, box) {
  btn.onclick = (e) => { e.stopPropagation(); box.hidden = !box.hidden; btn.setAttribute("aria-expanded", String(!box.hidden)); };
}
menu($("layout-btn"), $("layout-menu"));
menu($("export-btn"), $("export-menu"));
document.addEventListener("click", () => { $("layout-menu").hidden = true; $("export-menu").hidden = true; });
$("layout-menu").querySelectorAll("[data-layout]").forEach((b) => (b.onclick = () => {
  layoutName = b.dataset.layout;
  $("layout-label").textContent = { force: "Force", hierarchical: "Hierarchical", radial: "Radial" }[layoutName];
  $("layout-menu").querySelectorAll("[data-layout]").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
  if (cy) cy.layout(layoutFor(layoutName, selected)).run();
}));
$("zoom-in").onclick = () => cy && cy.zoom({ level: cy.zoom() * 1.25, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
$("zoom-out").onclick = () => cy && cy.zoom({ level: cy.zoom() / 1.25, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
$("fit").onclick = () => cy && cy.fit(undefined, 30);
$("locate").onclick = () => { if (cy && selected && cy.getElementById(selected).length) cy.animate({ center: { eles: cy.getElementById(selected) }, zoom: Math.max(cy.zoom(), 1) }, { duration: 250 }); };
function download(name, blob) { const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; a.click(); }
$("export-menu").querySelectorAll("[data-export]").forEach((b) => (b.onclick = () => {
  if (!G) return;
  if (b.dataset.export === "png" && cy) download(`${G.id}.png`, cy.png({ output: "blob", full: true, scale: 2, bg: css("--bg") }));
  if (b.dataset.export === "graph") download(`${G.id}.json`, new Blob([JSON.stringify(G.doc)], { type: "application/json" }));
}));
$("theme").onclick = () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("scale-theme", next); } catch { /* storage off */ }
  if (cy) cy.style(cyStyle());
};
function togglePanel(which, on) {
  const grid = document.querySelector(".sx-grid"), cls = `${which}-off`;
  grid.classList.toggle(cls, !on);
  $(`${which}-show`).hidden = on;
  setTimeout(() => cy && cy.resize(), 0);
}
$("rail-collapse").onclick = () => togglePanel("rail", false);
$("rail-show").onclick = () => togglePanel("rail", true);
$("inspector-collapse").onclick = () => togglePanel("inspector", false);
$("inspector-show").onclick = () => togglePanel("inspector", true);

start().catch((err) => setStatus(`Could not start: ${err.message}`));
