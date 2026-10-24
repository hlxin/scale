// The graph explorer: pick a graph of this repository (data/graphs.json, written by `scale site build`) or open a file,
// see a map of its record types, step through records and their evidence, and search, query or ask it. Search, plans
// and descriptions run SCALE's own code in a worker (worker.js); a question runs the query-graph skill with the
// reader's own API key.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const md = (s) => DOMPurify.sanitize(marked.parse(String(s || "")));
const WHOLE_MAX = 400;            // a graph this small is drawn whole on request
const NEIGHBOURS_MAX = 80;        // the links drawn around a record
const LIST_MAX = 300;             // the records listed for a type
const RESULT_CHARS = 40000;       // the longest tool result handed back to the model (as the web service does)
const SDK = "https://cdn.jsdelivr.net/npm/@anthropic-ai/sdk@0.133.0/+esm";

let G = null;                     // {id, file, doc, byId, out, inn, labels}
let cy = null;
let manifest = [];
let questions = [];

// ------------------------------------------------------------------------------------------ the worker (SCALE)
const worker = new Worker("worker.js");
const pending = new Map();
let seq = 0;
let pythonReady = false;
worker.onmessage = (e) => {
  const m = e.data;
  if (m.status) {
    pythonReady = m.status === "ready";
    setStatus(pythonReady ? "SCALE is ready in this browser." : m.status);
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
function setStatus(text) { $("status").textContent = text; }

// ------------------------------------------------------------------------------------------ loading a graph
async function start() {
  try {
    manifest = (await (await fetch("data/graphs.json")).json()).graphs || [];
  } catch { manifest = []; }
  const sel = $("graph-select");
  sel.innerHTML = manifest.map((g) => `<option value="${esc(g.id)}">${esc(g.title)}${g.data_status === "synthetic_example" ? " (synthetic)" : ""} · ${g.nodes} records</option>`).join("")
    || `<option value="">No graphs listed: open a file</option>`;
  sel.onchange = () => { location.hash = `g=${encodeURIComponent(sel.value)}`; };
  window.onhashchange = () => openFromHash();
  $("graph-file").onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try { await openGraph({ id: f.name.replace(/\W+/g, "-"), title: f.name }, await f.text()); }
    catch (err) { alert(`not a graph: ${err.message}`); }
  };
  await openFromHash();
}

async function openFromHash() {
  const want = new URLSearchParams(location.hash.slice(1)).get("g");
  const entry = manifest.find((g) => g.id === want) || manifest[0];
  if (!entry || (G && G.id === entry.id)) return;
  $("graph-select").value = entry.id;
  setStatus(`Loading ${entry.title}…`);
  const text = await (await fetch(entry.path)).text();
  await openGraph(entry, text);
  try { questions = await (await fetch(`data/questions/${entry.id}.json`)).json(); } catch { questions = []; }
  fillPlans();
}

async function openGraph(entry, text) {
  const doc = JSON.parse(text);
  if (!Array.isArray(doc.nodes) || !Array.isArray(doc.links)) throw new Error("no nodes and links");
  const byId = new Map(doc.nodes.map((n) => [n.id, n]));
  const out = new Map(), inn = new Map(), labels = new Map();
  for (const n of doc.nodes) labels.set(n.label, (labels.get(n.label) || 0) + 1);
  for (const e of doc.links) {
    (out.get(e.source) || out.set(e.source, []).get(e.source)).push(e);
    (inn.get(e.target) || inn.set(e.target, []).get(e.target)).push(e);
  }
  G = { id: entry.id, file: `${entry.id}.json`, doc, byId, out, inn, labels, entry };
  if (!manifest.includes(entry)) { questions = []; fillPlans(); }
  await rpc({ op: "put", name: G.file, text }).catch((err) => setStatus(`SCALE could not load the graph: ${err.message}`));
  warm(G.id);
  showInfo();
  showLabels();
  showMap();
  $("details").innerHTML = "Select a record to see its properties and evidence.";
  if (pythonReady) setStatus(`${entry.title}: ${doc.nodes.length} records, ${doc.links.length} links.`);
}

// The first search of a graph builds its evidence index (seconds for thousands of quotes); build it now, while the
// reader looks at the map, so a search answers at once. The toolkit keeps it with the loaded graph.
async function warm(id) {
  if (!G.doc.nodes.some((n) => (n.props?.evidence || []).some((e) => e.quote))) return;
  const note = () => G && G.id === id && setStatus(`Indexing the evidence of ${G.entry.title}…`);
  if (pythonReady) note(); else setTimeout(note, 4000);
  try { await scale("search", { query: "catalyst", k: 1 }); } catch { /* reported when the reader searches */ }
  if (G && G.id === id) setStatus(`${G.entry.title}: ${G.doc.nodes.length} records, ${G.doc.links.length} links. Ready to search and query.`);
}

function showInfo() {
  const g = G.doc.graph || {}, e = G.entry;
  const synthetic = (g.data_status || e.data_status) === "synthetic_example";
  $("graph-info").innerHTML = `
    <p><strong>${esc(g.title || e.title)}</strong></p>
    ${synthetic ? `<p class="warn">Synthetic example: invented to show the schema, not evidence about the world.</p>` : ""}
    <p class="muted">${esc((g.description || "").slice(0, 600))}</p>
    <p class="muted">scale-catal ${esc(g.schema_version || "?")} · ${G.doc.nodes.length} records · ${G.doc.links.length} links
      ${e.from ? ` · <a href="https://github.com/hlxin/scale/tree/main/${esc(e.from)}">source</a>` : ""}
      · <a href="${esc(e.path || "#")}" download>download</a></p>`;
}

// ------------------------------------------------------------------------------------------ names and colours
const name = (n) => (n && (n.props?.name || n.props?.title || n.props?.formula || n.id.split("/").pop())) || "?";
function colour(label) {
  let h = 0;
  for (const c of String(label)) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h}, 55%, 52%)`;
}
function value(v) {
  if (v === null || v === undefined) return "";
  if (Array.isArray(v)) return v.map(value).join("; ");
  if (typeof v !== "object") return esc(v);
  if ("status" in v && (v.status !== "present" || "value" in v || "text_value" in v || "lower" in v || "upper" in v)) {
    if (v.status !== "present") return `<span class="muted">${esc(v.status)}${v.missing_reason ? ` (${esc(v.missing_reason)})` : ""}</span>`;
    const num = "value" in v ? v.value : "lower" in v || "upper" in v ? `${v.lower ?? ""}–${v.upper ?? ""}` : v.text_value ?? v.boolean_value;
    const shown = `${esc(num)}${v.unit && v.unit !== "1" ? ` ${esc(v.unit)}` : ""}`;
    return v.as_reported && String(v.as_reported) !== String(num) ? `${shown} <span class="muted">(as reported: ${esc(v.as_reported)})</span>` : shown;
  }
  return `<code>${esc(JSON.stringify(v))}</code>`;
}

// ------------------------------------------------------------------------------------------ the views
function draw(elements, layout) {
  $("cy-empty")?.remove();                                   // the placeholder, before the first drawing
  if (cy) cy.destroy();
  const css = getComputedStyle(document.documentElement);
  cy = cytoscape({
    container: $("cy"), elements, wheelSensitivity: 0.3, maxZoom: 1.4, minZoom: 0.05,
    style: [
      { selector: "node", style: { "background-color": "data(c)", label: "data(l)", "font-size": 10, color: css.getPropertyValue("--text"),
        "text-wrap": "ellipsis", "text-max-width": 120, width: "data(s)", height: "data(s)" } },
      { selector: "node.focus", style: { "border-width": 3, "border-color": css.getPropertyValue("--accent") } },
      { selector: "edge", style: { width: 1.2, "line-color": css.getPropertyValue("--line"), "target-arrow-shape": "triangle",
        "target-arrow-color": css.getPropertyValue("--line"), "curve-style": "bezier", label: "data(l)", "font-size": 8,
        color: css.getPropertyValue("--muted"), "text-rotation": "autorotate" } },
      // many links: their names only on the selected record type's links (a crowded map is unreadable otherwise)
      { selector: "edge.quiet", style: { "text-opacity": 0 } },
      { selector: "node:selected", style: { "border-width": 3, "border-color": css.getPropertyValue("--accent") } },
    ],
    layout,
  });
  return cy;
}

function showMap() {
  const pairs = new Map();
  for (const e of G.doc.links) {
    const a = G.byId.get(e.source)?.label, b = G.byId.get(e.target)?.label;
    if (!a || !b) continue;
    const k = `${a}\u0000${e.type}\u0000${b}`;
    pairs.set(k, (pairs.get(k) || 0) + 1);
  }
  const max = Math.max(...G.labels.values(), 1);
  const els = [...G.labels].map(([l, n]) => ({ data: { id: `L:${l}`, l: `${l} (${n})`, c: colour(l), s: 18 + 40 * Math.sqrt(n / max) } }));
  for (const [k, n] of pairs) {
    const [a, t, b] = k.split("\u0000");
    if (t === "REPORTED_IN" && a !== "Source") continue;      // every record is reported in its source: drawn, it hides the rest
    els.push({ data: { id: `E:${k}`, source: `L:${a}`, target: `L:${b}`, l: `${t} ${n}` } });
  }
  const c = draw(els, { name: "cose", animate: false, nodeRepulsion: 12000, idealEdgeLength: 140 });
  const quiet = c.edges().length > 24;
  if (quiet) c.edges().addClass("quiet");
  c.on("tap", "node", (ev) => {
    if (quiet) { c.edges().addClass("quiet"); ev.target.connectedEdges().removeClass("quiet"); }
    listRecords(ev.target.id().slice(2));
  });
  $("view-title").textContent = "Map of record types";
  $("to-map").classList.add("hidden");
  $("whole").classList.toggle("hidden", G.doc.nodes.length > WHOLE_MAX);
}

function showWhole() {
  const els = G.doc.nodes.map((n) => ({ data: { id: n.id, l: name(n), c: colour(n.label), s: 16 } }));
  for (const e of G.doc.links) {
    if (e.type !== "REPORTED_IN") els.push({ data: { id: `e:${e.id}`, source: e.source, target: e.target, l: "" } });
  }
  draw(els, { name: "cose", animate: false }).on("tap", "node", (ev) => openRecord(ev.target.id()));
  $("view-title").textContent = "Whole graph (links to sources hidden)";
  $("to-map").classList.remove("hidden");
}

function showLabels() {
  $("labels").innerHTML = [...G.labels].sort((a, b) => b[1] - a[1])
    .map(([l, n]) => `<button class="chip" data-l="${esc(l)}" style="--c:${colour(l)}">${esc(l)} <span class="muted">${n}</span></button>`).join(" ");
  $("labels").querySelectorAll(".chip").forEach((b) => (b.onclick = () => listRecords(b.dataset.l)));
  $("records").innerHTML = "";
}

function listRecords(label) {
  const all = G.doc.nodes.filter((n) => n.label === label);
  const render = (q) => {
    const shown = all.filter((n) => !q || `${name(n)} ${n.id}`.toLowerCase().includes(q)).slice(0, LIST_MAX);
    $("record-list").innerHTML = shown.map((n) => `<li><a href="#" data-id="${esc(n.id)}">${esc(name(n))}</a></li>`).join("")
      + (all.length > shown.length ? `<li class="muted">… type to narrow (${all.length} in all)</li>` : "");
    $("record-list").querySelectorAll("a").forEach((a) => (a.onclick = (e) => { e.preventDefault(); openRecord(a.dataset.id); }));
  };
  $("records").innerHTML = `<h3>${esc(label)} <span class="muted">(${all.length})</span></h3>
    <input type="text" id="record-filter" placeholder="filter by name"><ul id="record-list" class="list"></ul>`;
  $("record-filter").oninput = (e) => render(e.target.value.trim().toLowerCase());
  render("");
}

function openRecord(id) {
  const rec = G.byId.get(id) || G.doc.links.find((e) => e.id === id);
  if (!rec) return;
  showDetails(rec);
  if (!G.byId.has(id)) return;                                  // a link: its details only
  const links = [...(G.out.get(id) || []), ...(G.inn.get(id) || [])].filter((e) => e.type !== "REPORTED_IN" || e.source === id);
  const keep = links.slice(0, NEIGHBOURS_MAX);
  const ids = new Set([id, ...keep.flatMap((e) => [e.source, e.target])]);
  const els = [...ids].map((n) => G.byId.get(n)).filter(Boolean)
    .map((n) => ({ data: { id: n.id, l: name(n), c: colour(n.label), s: n.id === id ? 34 : 22 }, classes: n.id === id ? "focus" : "" }));
  for (const e of keep) els.push({ data: { id: `e:${e.id}`, source: e.source, target: e.target, l: e.type, link: e.id } });
  draw(els, { name: "concentric", animate: false, concentric: (n) => (n.id() === id ? 2 : 1), minNodeSpacing: 18 })
    .on("tap", "node", (ev) => openRecord(ev.target.id()))
    .on("tap", "edge", (ev) => showDetails(G.doc.links.find((e) => e.id === ev.target.data("link"))));
  $("view-title").textContent = `${G.byId.get(id).label}: ${name(G.byId.get(id))}`
    + (links.length > keep.length ? ` (${keep.length} of ${links.length} links)` : "");
  $("to-map").classList.remove("hidden");
}

function showDetails(rec) {
  const p = rec.props || {};
  const isLink = "source" in rec && "target" in rec;
  const head = isLink
    ? `<p><strong>${esc(rec.type)}</strong>: <a href="#" data-id="${esc(rec.source)}">${esc(name(G.byId.get(rec.source)))}</a> →
        <a href="#" data-id="${esc(rec.target)}">${esc(name(G.byId.get(rec.target)))}</a></p>`
    : `<p><strong>${esc(name(rec))}</strong> <span class="badge" style="--c:${colour(rec.label)}">${esc(rec.label)}</span></p>`;
  const rows = Object.entries(p).filter(([k]) => k !== "evidence" && k !== "name")
    .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${idLinks(value(v))}</td></tr>`).join("");
  const ev = (p.evidence || []).map((e) => {
    const src = G.byId.get(e.source);
    const where = [src ? name(src) : e.source, e.locator].filter(Boolean).map(esc).join(" · ");
    return e.quote ? `<blockquote>${esc(e.quote)}<br><span class="muted small">${where}</span></blockquote>`
      : `<p class="withheld">No quote kept (${where}).</p>`;
  }).join("");
  $("details").classList.remove("muted");
  $("details").innerHTML = `${head}<p class="muted"><code>${esc(rec.id)}</code></p>
    <table>${rows}</table>${ev ? `<h3>Evidence</h3>${ev}` : ""}`;
  $("details").querySelectorAll("a[data-id]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); openRecord(a.dataset.id); }));
}
// a record id inside a shown value becomes a link to the record
const idLinks = (html) => html.replace(/(?:&quot;|\b)((?:ex|scale|[a-z][a-z0-9-]*):[A-Za-z0-9_.\/-]+)/g,
  (m, id) => (G.byId.has(id) ? m.replace(id, `<a href="#" data-id="${esc(id)}">${esc(id)}</a>`) : m));

// ------------------------------------------------------------------------------------------ search, plans, questions
document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
  document.querySelectorAll(".tabpane").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== t.dataset.tab));
}));

async function search() {
  const q = $("search").value.trim();
  if (!q || !G) return;
  $("hits").innerHTML = `<p class="muted">Searching…</p>`;
  try {
    const r = await scale("search", { query: q, k: 20 });
    if (r.error) throw new Error(r.error);
    const hits = r.hits || [];
    $("hits").innerHTML = hits.length ? hits.map((h) => `<div class="hit" data-id="${esc(h.record)}">
        <div>${esc(h.text)}</div>
        <div class="muted small">${esc(h.label || "")}: ${esc(h.record_name || h.record)} · ${esc(name(G.byId.get(h.source)))}${h.source_year ? ` (${esc(h.source_year)})` : ""}, ${esc(h.locator || "")} · score ${Number(h.score || 0).toFixed(3)}</div></div>`).join("")
      : `<p class="muted">No evidence matches.</p>`;
    $("hits").querySelectorAll(".hit").forEach((el) => (el.onclick = () => openRecord(el.dataset.id)));
  } catch (err) { $("hits").innerHTML = `<p class="warn">${esc(err.message)}</p>`; }
}
$("search-go").onclick = search;
$("search").onkeydown = (e) => { if (e.key === "Enter") search(); };

function fillPlans() {
  $("plan-pick").innerHTML = `<option value="">${questions.length ? "Questions that run on this graph…" : "No saved questions for this graph"}</option>`
    + questions.map((q, i) => `<option value="${i}">${esc(q.id)}: ${esc(String(q.question || "").slice(0, 110))}</option>`).join("");
}
$("plan-pick").onchange = (e) => {
  const q = questions[Number(e.target.value)];
  if (q) $("plan").value = JSON.stringify(q.plan, null, 2);
};

function renderResult(r) {
  if (r.error) return `<p class="warn">${esc(r.error)}</p>`;
  const rows = r.rows || [];
  const cols = [...new Set(rows.flatMap((x) => Object.keys(x.values || {})))];
  const table = rows.length ? `<table class="grid"><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr>${rows.slice(0, 200).map((x) =>
    `<tr>${cols.map((c) => `<td>${idLinks(value(x.values?.[c]))}</td>`).join("")}</tr>`).join("")}</table>` : "";
  const lim = (r.limitations || []).map((l) => `<li>${esc(l)}</li>`).join("");
  return `<p><strong>${esc(r.status)}</strong> · ${r.row_count ?? rows.length} rows${(r.excluded || []).length ? ` · ${r.excluded.length} left out (see below)` : ""}</p>
    ${table}${lim ? `<details><summary>Limitations</summary><ul>${lim}</ul></details>` : ""}
    <details><summary>Full result</summary><pre>${esc(JSON.stringify(r, null, 1).slice(0, 60000))}</pre></details>`;
}
$("plan-go").onclick = async () => {
  if (!G) return;
  let plan;
  try { plan = JSON.parse($("plan").value); } catch (err) { $("rows").innerHTML = `<p class="warn">The plan is not JSON: ${esc(err.message)}</p>`; return; }
  $("rows").innerHTML = `<p class="muted">Running…</p>`;
  try {
    $("rows").innerHTML = renderResult(await scale("query", { plan }));
    $("rows").querySelectorAll("a[data-id]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); openRecord(a.dataset.id); }));
  } catch (err) { $("rows").innerHTML = `<p class="warn">${esc(err.message)}</p>`; }
};

// The API key stays in this browser: sessionStorage, or localStorage when the reader asks to remember it.
const store = { get(k) { try { return localStorage.getItem(k) || sessionStorage.getItem(k) || ""; } catch { return ""; } },
  set(k, v, keep) { try { (keep ? localStorage : sessionStorage).setItem(k, v); if (!keep) localStorage.removeItem(k); } catch { /* storage off */ } } };
$("api-key").value = store.get("scale-api-key");
$("remember-key").checked = (() => { try { return !!localStorage.getItem("scale-api-key"); } catch { return false; } })();

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

async function ask() {
  const key = $("api-key").value.trim(), question = $("question").value.trim(), model = $("model").value;
  if (!G || !question) return;
  if (!key) { $("answer").innerHTML = `<p class="warn">Paste an Anthropic API key first.</p>`; return; }
  store.set("scale-api-key", key, $("remember-key").checked);
  const out = $("answer"), log = [];
  const say = (line) => { log.push(line); out.innerHTML = `<div class="job">${log.map((l) => `<div>${esc(l)}</div>`).join("")}</div>`; };
  $("ask-go").disabled = true;
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
    const runs = plans.map((p, i) => `<details><summary>Plan ${i + 1}: ${esc(p.result?.status || p.result?.error || "?")}, ${p.result?.row_count ?? 0} rows</summary>
      <pre>${esc(JSON.stringify(p.plan, null, 1))}</pre></details>`).join("");
    out.innerHTML = `${md(answer || "No answer.")}${runs}<p class="muted small">${model} · about ${tokens.toLocaleString()} tokens</p>`;
  } catch (err) {
    out.innerHTML = `<p class="warn">${esc(err.message || err)}</p>`;
  } finally { $("ask-go").disabled = false; }
}
$("ask-go").onclick = ask;

$("to-map").onclick = () => showMap();
$("whole").onclick = () => showWhole();
start().catch((err) => setStatus(`Could not start: ${err.message}`));
