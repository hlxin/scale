// The page of the SCALE web service: send a publication, follow the job, show the graph, ask it questions.
// Everything the page computes is display; validation, queries and search run in the service (scale-catal itself).
"use strict";

const SERVICE = (window.SCALE_SERVICE_URL || "").replace(/\/$/, "");
const $ = (id) => document.getElementById(id);
const store = {
  get(k) { try { return sessionStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v == null ? sessionStorage.removeItem(k) : sessionStorage.setItem(k, v); } catch { /* none */ } },
};
let token = store.get("scale-token");
let graph = null;
let receipt = null;   // the service's receipt for a graph it just curated for this user: only such a graph is contributed
let cy = null;

const PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22",
  "#17becf", "#393b79", "#637939", "#8c6d31", "#843c39", "#7b4173", "#3182bd"];
const colours = {};
const colour = (label) => colours[label] || (colours[label] = PALETTE[Object.keys(colours).length % PALETTE.length]);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ------------------------------------------------------------------------------------------- the service
async function call(method, path, body, headers = {}) {
  if (!SERVICE) throw new Error("the service is not configured (site/config.js)");
  const h = { ...headers };
  if (token) h.Authorization = `Bearer ${token}`;
  if (body !== undefined && !(body instanceof Blob)) { h["Content-Type"] = "application/json"; body = JSON.stringify(body); }
  const r = await fetch(SERVICE + path, { method, headers: h, body });
  const data = await r.json().catch(() => ({}));
  if (r.status === 401) { token = null; store.set("scale-token", null); account(); }
  if (!r.ok) throw new Error(data.error || `the service answered ${r.status}`);
  return data;
}

// ------------------------------------------------------------------------------------------- sign-in
function readFragment() {
  const p = new URLSearchParams(location.hash.slice(1));
  if (p.get("token")) { token = p.get("token"); store.set("scale-token", token); }
  if (p.get("signin") === "not-allowed") alert(`${p.get("login") || "This account"} is not on the service's allowlist. Ask a maintainer to add it.`);
  if (p.get("signin") === "failed") alert("GitHub sign-in failed; try again.");
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
}

async function account() {
  const el = $("account");
  if (!SERVICE) { el.innerHTML = `<span class="muted small">service not configured</span>`; return; }
  if (!token) {
    const back = location.origin + location.pathname;
    el.innerHTML = `<a class="button" href="${SERVICE}/auth/login?return=${encodeURIComponent(back)}">Sign in with GitHub</a>`;
    return;
  }
  try {
    const me = await call("GET", "/me");
    el.innerHTML = `<span class="small">${esc(me.login)}</span> <button id="signout">Sign out</button>`;
    $("signout").onclick = () => { token = null; store.set("scale-token", null); account(); };
  } catch { /* account() ran again on 401 */ }
}

// ------------------------------------------------------------------------------------------- input
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
  document.querySelectorAll(".tabpane").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== t.dataset.tab));
}));
const activeTab = () => document.querySelector(".tab.active").dataset.tab;

$("start").onclick = async () => {
  const job = $("job");
  job.classList.remove("hidden");
  try {
    if (!token) throw new Error("sign in with GitHub first");
    let res;
    if (activeTab() === "pdf") {
      const f = $("pdf").files[0];
      if (!f) throw new Error("choose a PDF");
      const q = new URLSearchParams({ filename: f.name });
      if ($("pdf-doi").value.trim()) q.set("doi", $("pdf-doi").value.trim());
      res = await call("POST", `/jobs?${q}`, f, { "Content-Type": "application/pdf" });
    } else if (activeTab() === "doi") {
      res = await call("POST", "/jobs", { doi: $("doi").value.trim() });
    } else {
      res = await call("POST", "/jobs", { url: $("url").value.trim() });
    }
    $("start").disabled = true;
    follow(res.job);
  } catch (e) {
    job.innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
};

async function follow(id) {
  const job = $("job");
  for (;;) {
    let j;
    try { j = await call("GET", `/jobs/${id}`); } catch (e) { job.innerHTML = `<span class="err">${esc(e.message)}</span>`; break; }
    const log = (j.log || []).slice(-12).map((l) => `<li>${esc(l.t)} s · ${esc(l.msg)}</li>`).join("");
    const src = j.source ? `<div class="small muted">${esc(j.source.pages)} pages · rights: ${esc(j.source.rights_class)} · schema ${esc(j.source.schema_version)}</div>` : "";
    job.innerHTML = `<div class="state">${esc(j.state)}</div>${src}<ol>${log}</ol>`;
    if (j.state === "done") {
      job.innerHTML += `<div class="small">${esc(j.summary || "")}</div>` +
        (j.withheld ? `<div class="small muted">${j.withheld} quotes withheld for the source's rights (sha256 kept).</div>` : "");
      show(j.graph, j.receipt);
      break;
    }
    if (j.state === "failed") {
      job.innerHTML += `<div class="err">${esc(j.error)}</div>`;
      if (j.check && j.check.errors) job.innerHTML += `<details><summary>check errors</summary><pre>${esc(JSON.stringify(j.check.errors, null, 1))}</pre></details>`;
      break;
    }
    await new Promise((r) => setTimeout(r, 3000));
  }
  $("start").disabled = false;
}

$("graph-file").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  try { show(JSON.parse(await f.text())); } catch (err) { alert(`not a graph: ${err.message}`); }
};
$("example").onclick = async () => {
  try { show(await call("GET", "/example")); } catch (e) { alert(e.message); }
};

// ------------------------------------------------------------------------------------------- the graph
function show(doc, signed = null) {
  if (!doc || !Array.isArray(doc.nodes) || !Array.isArray(doc.links)) { alert("not a scale-catal document"); return; }
  graph = doc;
  receipt = signed;
  $("contribute").classList.toggle("hidden", !receipt);
  $("contribution").classList.add("hidden");
  $("graph-title").textContent = `· ${doc.graph?.title || ""} (${doc.nodes.length} records, ${doc.links.length} links)`;
  $("download").disabled = false;
  const labels = [...new Set(doc.nodes.map((n) => n.label))].sort();
  $("label-filter").innerHTML = `<option value="">every label</option>` + labels.map((l) => `<option>${esc(l)}</option>`).join("");
  $("legend").innerHTML = labels.map((l) => `<span style="--c:${colour(l)}">${esc(l)}</span>`).join("");
  const ids = new Set(doc.nodes.map((n) => n.id));
  const elements = [
    ...doc.nodes.map((n) => ({ data: { id: n.id, name: n.props?.name || n.id.split("/").pop(), label: n.label, c: colour(n.label) } })),
    ...doc.links.filter((e) => ids.has(e.source) && ids.has(e.target))
      .map((e) => ({ data: { id: `link:${e.id}`, source: e.source, target: e.target, type: e.type } })),
  ];
  $("cy").innerHTML = "";
  cy = cytoscape({
    container: $("cy"), elements, wheelSensitivity: 0.2,
    style: [
      { selector: "node", style: { "background-color": "data(c)", label: "data(name)", "font-size": 8, color: getComputedStyle(document.body).color, "text-wrap": "ellipsis", "text-max-width": 90, width: 14, height: 14 } },
      { selector: "edge", style: { width: 1, "line-color": "#999", "target-arrow-color": "#999", "target-arrow-shape": "triangle", "arrow-scale": 0.6, "curve-style": "bezier", opacity: 0.6 } },
      { selector: ":selected", style: { "border-width": 3, "border-color": "#f5b400", "line-color": "#f5b400", "target-arrow-color": "#f5b400", opacity: 1 } },
      { selector: ".dim", style: { opacity: 0.08 } },
    ],
    layout: { name: doc.nodes.length > 800 ? "grid" : "cose", animate: false, nodeRepulsion: 6000, idealEdgeLength: 60 },
  });
  cy.on("tap", "node, edge", (ev) => details(ev.target.id()));
  $("details").innerHTML = "Click a record to see its values and evidence.";
}

function valueText(v) {
  if (v && typeof v === "object" && "status" in v) {
    if (v.status !== "present") return `<span class="muted">${esc(v.status)}${v.missing_reason ? ` (${esc(v.missing_reason)})` : ""}</span>`;
    const num = v.value ?? (v.lower != null || v.upper != null ? `${v.lower ?? ""}–${v.upper ?? ""}` : "");
    return `${esc(v.bound ? `${v.bound} ` : "")}${esc(num)} ${esc(v.unit === "1" ? "" : v.unit || "")}` +
      (v.as_reported ? `<div class="muted small">as reported: ${esc(v.as_reported)}</div>` : "") +
      (v.note ? `<div class="muted small">${esc(v.note)}</div>` : "");
  }
  if (v && typeof v === "object") return `<pre>${esc(JSON.stringify(v, null, 1))}</pre>`;
  return esc(v);
}

function details(id) {
  const rec = id.startsWith("link:") ? graph.links.find((e) => `link:${e.id}` === id) : graph.nodes.find((n) => n.id === id);
  if (!rec) return;
  const props = { ...(rec.props || {}) };
  const ev = props.evidence || [];
  delete props.evidence;
  const head = rec.label ? `<b>${esc(rec.label)}</b> ${esc(rec.id)}` : `<b>${esc(rec.type)}</b> ${esc(rec.source)} → ${esc(rec.target)}`;
  const rows = Object.entries(props).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${valueText(v)}</td></tr>`).join("");
  const quotes = ev.map((e) => {
    const where = `${esc(e.locator || "")} · ${esc(e.source || "")}`;
    if (e.quote) return `<blockquote>${esc(e.quote)}<div class="muted small">${where}</div></blockquote>`;
    return `<blockquote class="withheld">quote withheld for the source's rights<div class="muted small">${where}</div></blockquote>`;
  }).join("");
  $("details").innerHTML = `<div>${head}</div><table>${rows}</table>${ev.length ? `<h3>Evidence</h3>${quotes}` : ""}`;
  $("details").classList.remove("muted");
}

$("label-filter").onchange = (e) => {
  if (!cy) return;
  const l = e.target.value;
  cy.elements().removeClass("dim");
  if (l) cy.nodes().filter((n) => n.data("label") !== l).addClass("dim");
};
$("fit").onclick = () => cy && cy.fit();
$("download").onclick = () => {
  if (!graph) return;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(graph, null, 1)], { type: "application/json" }));
  const id = (graph.graph?.graph_id || "graph").split("/").pop();
  a.download = `${id}.graph.json`;
  a.click();
};

// ------------------------------------------------------------------------------------------- contributing
$("contribute").onclick = async () => {
  const box = $("contribution");
  box.classList.remove("hidden");
  box.innerHTML = `<span class="muted">Checking catal-commons on main and the open contributions…</span>`;
  try {
    const r = await call("POST", "/contribute/check", { graph, receipt });
    if (r.already) {
      box.innerHTML = `This source is already in catal-commons: ` + r.already.map((h) =>
        `<a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.source)}</a> (the same ${esc(h.by.join(", "))})`).join("; ") + ".";
      return;
    }
    if (r.proposed) {
      box.innerHTML = `This source is already proposed: <a href="${esc(r.proposed.url)}" target="_blank" rel="noopener">#${esc(r.proposed.number)} ${esc(r.proposed.title)}</a>.`;
      return;
    }
    const p = r.new;
    box.innerHTML = `<div class="state">Not in the commons yet</div>
      <div class="small">It would add <code>${esc(p.source)}</code>: ${esc(p.records.nodes)} records and ${esc(p.records.links)} links,
      ${esc(p.shared_added.length)} new shared records and new evidence on ${esc(p.shared_with_new_evidence.length)} shared ones.
      Rights: ${esc(p.class)}; quotes kept ${esc(p.quotes.kept)}, withheld ${esc(p.quotes.withheld)}
      (the commons quotes no text of a source in copyright).</div>
      <div class="small muted">Files: ${p.files.map(esc).join(", ")}</div>
      <p class="small">A pull request is opened by the SCALE bot and credits you; a reviewer checks it against the source
      before it is merged.</p>
      <button id="contribute-go" class="primary">Open the pull request</button>`;
    $("contribute-go").onclick = async () => {
      $("contribute-go").disabled = true;
      try {
        const o = await call("POST", "/contribute", { graph, receipt });
        box.innerHTML = `Opened <a href="${esc(o.pull_request.url)}" target="_blank" rel="noopener">pull request #${esc(o.pull_request.number)}</a>. Thank you.`;
        receipt = null;
        $("contribute").classList.add("hidden");
      } catch (e) {
        box.innerHTML += `<div class="err">${esc(e.message)}</div>`;
      }
    };
  } catch (e) {
    box.innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
};

function focus(id) {
  if (!cy) return;
  const el = cy.getElementById(id);
  if (el.nonempty()) { cy.elements().unselect(); el.select(); cy.animate({ center: { eles: el }, zoom: 1.6 }, { duration: 300 }); details(id); }
}

// ------------------------------------------------------------------------------------------- questions
$("ask-btn").onclick = async () => {
  const out = $("answer");
  if (!graph) { out.textContent = "Open or curate a graph first."; return; }
  const q = $("question").value.trim();
  if (!q) return;
  out.innerHTML = `<span class="muted">Working: writing and running query plans…</span>`;
  try {
    const r = await call("POST", "/ask", { graph, question: q });
    const plans = (r.plans || []).map((p, i) => `<details><summary>plan ${i + 1}: ${esc(p.status)}, ${esc(p.rows)} rows</summary><pre>${esc(JSON.stringify(p.plan, null, 1))}</pre></details>`).join("");
    out.innerHTML = DOMPurify.sanitize(marked.parse(r.answer || "")) + plans + (r.stopped ? `<p class="err">${esc(r.stopped)}</p>` : "");
  } catch (e) {
    out.innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
};

$("search-btn").onclick = async () => {
  const out = $("hits");
  if (!graph) { out.textContent = "Open or curate a graph first."; return; }
  try {
    const r = await call("POST", "/search", { graph, query: $("search").value.trim(), k: 10 });
    out.innerHTML = (r.hits || []).map((h) => `<div class="hit" data-id="${esc(h.record)}"><b>${esc(h.record_name || h.record)}</b>` +
      `<div>${esc(h.quote || h.text || "")}</div><div class="muted small">${esc(h.locator || "")} · ${esc(h.source || "")}</div></div>`).join("") || "no hits";
    out.querySelectorAll(".hit").forEach((el) => el.addEventListener("click", () => {
      const id = el.dataset.id;
      focus(graph.nodes.some((n) => n.id === id) ? id : `link:${id}`);
    }));
  } catch (e) {
    out.innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
};

readFragment();
account();
