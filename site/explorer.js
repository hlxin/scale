// The graph explorer. Pick a graph of this repository (data/graphs.json, written by `scale site build`) or open a file:
// the whole graph is drawn by a force layout (circle area by connectivity, colour by label), its labels and
// relationship types filter it, and a node's properties, evidence and neighbours show on the right. "Search by asking"
// lists the evidence that matches; signed in, the SCALE service answers in words by SCALE's query-graph skill. No reader
// ever gives a model key: the service curates, answers and contributes within its own budget.
// Search, query plans and descriptions run SCALE's own code in a worker (worker.js).
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const md = (s) => DOMPurify.sanitize(marked.parse(String(s || "")));
const KIND_PALETTE = ["#5b8def", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4", "#f43f5e", "#84cc16", "#0ea5e9", "#d946ef", "#fbbf24", "#22c55e"];
const EDGE_PALETTE = ["#7c3aed", "#0891b2", "#ea580c", "#16a34a", "#db2777", "#0284c7", "#ca8a04", "#9333ea", "#0d9488", "#dc2626", "#65a30d", "#2563eb"];
const NODE_R_MIN = 7, NODE_R_MAX = 40, NODE_R_STEP = 3.3;   // a node's radius from its own links only
const BIG_GRAPH = 400;            // past this, names hide when seen from far (arrowheads stay)
const HUGE_GRAPH = 1000;          // past this, the layout runs in slices
const FAR_ZOOM = 0.6;
const LABELS_AUTO_MAX = 400;      // relationship names shown by default up to this many links
const PROVENANCE_KIND = "Source", PROVENANCE_EDGE = "REPORTED_IN";   // hidden until asked for, as the evidence is on each node

let G = null;                     // the graph: {entry, doc, byId, out, inn, labels, rels, sha, props}
let manifest = [];
let folded = false;               // the open graph's facts are folded under its row (its caret)
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
const SCOPE = { service: ["new", "var(--select)"], graphs: ["curated", "var(--green)"], examples: ["example", "var(--blue)"], domain: ["synthetic", "var(--violet)"] };
const scopeOf = (e) => SCOPE[(e.from || "").split("/")[0]] || ["file", "var(--subtle)"];
const CARET = `<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6 L15 12 L9 18"/></svg>`;

// ------------------------------------------------------------------------------------------ curating a source
const SERVICE = (window.SCALE_SERVICE_URL || "").replace(/\/$/, "");
let token = "", login = "";
function readSignIn() {                          // the service returns from GitHub with #token=… (or why it did not)
  const p = new URLSearchParams(location.hash.slice(1));
  if (!p.has("token") && !p.has("signin")) return;
  if (p.get("token")) { token = p.get("token"); store.set("scale-token", token); }
  const why = p.get("signin");
  for (const k of ["token", "signin", "login"]) p.delete(k);
  const was = store.get("scale-signin-hash");     // the graph open before GitHub (#g=…), which the return drops
  store.set("scale-signin-hash", "");
  const hash = p.toString() || was;
  history.replaceState(null, "", location.pathname + location.search + (hash ? `#${hash}` : ""));
  const fromCurate = store.get("scale-signin-from") === "curate";
  store.set("scale-signin-from", "");
  const note = why === "not-allowed" ? "This GitHub account is not admitted by the service yet; ask a maintainer to add it."
    : why ? "GitHub sign-in failed; try again." : "";
  if (fromCurate) setTimeout(() => (why ? ($("curate-dialog").showModal(), curateAccount(note)) : openCurate()), 0);
  else if (why) setTimeout(() => accountMenu(note), 0);
}
// where GitHub sends the reader back to: this page, as it is now. The service puts its answer in the fragment, so
// the graph open (#g=…) is kept in this tab's storage when a sign-in link is followed, and readSignIn() restores it.
const signInUrl = () => `${SERVICE}/auth/login?return=${encodeURIComponent(location.origin + location.pathname + location.search)}`;
document.addEventListener("click", (e) => {
  if (SERVICE && e.target.closest?.(`a[href^="${SERVICE}/auth/login"]`)) store.set("scale-signin-hash", location.hash.slice(1));
});
function signOut() {
  token = ""; login = ""; store.set("scale-token", "");
  renderAccount();
  if ($("curate-dialog").open) curateAccount();
}
// The toolbar's account: "Sign in" with GitHub, or the reader's avatar and login with a menu (what the service allows
// today, sign out). Without a service the button says why sign-in is not available yet.
let me = null;
async function renderAccount() {
  const btn = $("account-btn"), label = $("account-label");
  btn.classList.remove("is-signed-in");
  btn.querySelector("img")?.remove();
  btn.querySelector("svg").removeAttribute("hidden");
  if (!SERVICE || !token) { me = null; label.textContent = "Sign in"; btn.title = SERVICE ? "Sign in with GitHub" : "Sign-in opens once the SCALE service is running"; return; }
  try { me = await call("GET", "/me"); } catch { return; }       // a 401 signs out in call()
  login = me.login;
  const img = Object.assign(document.createElement("img"), { src: `https://github.com/${encodeURIComponent(me.login)}.png?size=64`, alt: "", className: "gx-avatar" });
  img.onerror = () => img.remove();
  btn.querySelector("svg").setAttribute("hidden", "");
  btn.prepend(img);
  btn.classList.add("is-signed-in");
  label.textContent = me.login;
  btn.title = `Signed in with GitHub as ${me.login}`;
}
function accountMenu(note = "") {
  const box = $("account-menu"), warn = note ? `<p class="gx-account-note gx-err">${esc(note)}</p>` : "";
  const open = `<p class="gx-account-note gx-subtle">Viewing, filtering and searching the graphs need no account.</p>`;
  if (!SERVICE) box.innerHTML = `<p class="gx-account-note">Sign-in with GitHub opens once the SCALE service is running; curating will
    need it.</p>${open}`;
  else if (!me) box.innerHTML = `${warn}<p class="gx-account-note">Curating a source needs a GitHub sign-in, as do contributing it to
    catal-commons and having questions answered in words. Free: the service reads only your GitHub login, never your
    repositories.</p>${open}
    <a class="gx-btn gx-btn-primary gx-account-go" href="${esc(signInUrl())}">Continue with GitHub</a>`;
  else box.innerHTML = `${warn}<p class="gx-account-note">Signed in as <b>${esc(me.login)}</b><br><span class="gx-subtle">${
    me.tokens_left_today === 0 ? "The service's budget for today is spent." : "Curating and questions are open to you today."}</span></p>
    <a class="gx-menu-item" href="https://github.com/${encodeURIComponent(me.login)}" target="_blank" rel="noopener">Your GitHub profile</a>
    <button class="gx-menu-item" type="button" id="account-board">Contributors to catal-commons</button>
    <button class="gx-menu-item" type="button" id="account-signout">Sign out</button>`;
  $("account-signout")?.addEventListener("click", signOut);
  $("account-board")?.addEventListener("click", () => $("board-open")?.click());
  box.hidden = false;
  $("account-btn").setAttribute("aria-expanded", "true");
}
async function call(method, path, body, headers = {}) {
  if (!SERVICE) throw new Error("the curation service is not configured (site/config.js)");
  const h = { ...headers };
  if (token) h.Authorization = `Bearer ${token}`;
  if (body !== undefined && !(body instanceof Blob)) { h["Content-Type"] = "application/json"; body = JSON.stringify(body); }
  const r = await fetch(SERVICE + path, { method, headers: h, body });
  const data = await r.json().catch(() => ({}));
  if (r.status === 401) { signOut(); }
  if (!r.ok) throw new Error(data.error || `the service answered ${r.status}`);
  return data;
}
async function curateAccount(note = "") {
  const el = $("curate-account");
  const warn = note ? `<span class="gx-err">${esc(note)}</span>` : "";
  if (!SERVICE) {
    el.innerHTML = `<span class="gx-warn">The curation service is not deployed yet.</span>`;
    $("curate-start").disabled = true;
    return;
  }
  if (!token) {
    el.innerHTML = `<a class="gx-btn gx-btn-primary" id="curate-signin" href="${esc(signInUrl())}">Sign in with GitHub</a>
      <span class="gx-subtle">Free; the service needs only your login.</span>${warn}`;
    $("curate-signin").onclick = () => store.set("scale-signin-from", "curate", true);
    $("curate-start").disabled = true;
    return;
  }
  try {
    const me = await call("GET", "/me");
    login = me.login;
    el.innerHTML = `<span>Signed in as <b>${esc(me.login)}</b></span><span class="gx-subtle">· ${esc(me.model || "")}</span>`
      + `${me.tokens_left_today === 0 ? `<span class="gx-err">· the service's budget for today is spent</span>` : ""}`
      + `<button type="button" class="gx-btn gx-btn-tiny" id="curate-signout">Sign out</button>${warn}`;
    $("curate-signout").onclick = signOut;
    $("curate-start").disabled = false;
  } catch { /* curateAccount ran again on 401 */ }
}
async function openCurate() {
  $("curate-dialog").showModal();
  curateAccount();
  if (!SERVICE) { $("curate-schema").textContent = ""; return; }
  try {
    const h = await call("GET", "/health");
    $("curate-schema").textContent = `Curated under SCALE Catalysis, schema scale-catal v${h.schema_version} (scale-catal ${h.scale_catal}).`;
    $("curate-keep-row").hidden = !h.keeps_texts;
    if (h.contact) $("curate-contact").innerHTML = `A rights holder can ask for a source's records or kept copy to be removed: <a href="mailto:${esc(h.contact)}">${esc(h.contact)}</a>.`;
    if (h.keeps_texts && token) showKept();
  } catch (e) { $("curate-schema").innerHTML = `<span class="gx-err">The service did not answer: ${esc(e.message)}</span>`; }
}
$("curate-open").onclick = () => openCurate();
// The leaderboard: catal-commons' contributors scored by tools/commons.py (SCORING). The service's copy carries each
// paper's reach (how often it answered other people); the site's copy (data/leaderboard.json) is the same without it.
let boardData = null, boardTab = "contributors";
const BOARD_TOP = 20;
const pct = (x) => (x == null ? "–" : `${Math.round(x * 100)}%`);
function boardRow(r) {
  const lv = r.level || {};
  const next = lv.next ? `<div class="gx-subtle">${Number(lv.to_next).toLocaleString()} to ${esc(lv.next)}</div>` : "";
  const papers = (r.contributions || []).map((c) => `<tr><td>${esc(c.source)}</td><td>${esc(c.added)}</td><td>${Number(c.triples).toLocaleString()}</td>
    <td>${Number(c.reach).toLocaleString()}</td><td>${pct(c.completeness)}</td><td>${Number(c.score).toLocaleString()}</td></tr>`).join("");
  const mine = login && r.github.toLowerCase() === login.toLowerCase();
  return `<tr class="gx-board-row${mine ? " is-me" : ""}" tabindex="0"><td>${esc(r.rank)}</td>
    <td><a href="https://github.com/${esc(r.github)}" target="_blank" rel="noopener"><img src="https://github.com/${esc(r.github)}.png?size=40" alt="" loading="lazy">${esc(r.github)}</a>
      <span class="gx-level gx-level-${esc((lv.name || "").toLowerCase().replace(/ /g, "-"))}">${esc(lv.name || "")}</span>${mine ? ` <span class="gx-subtle">you</span>` : ""}</td>
    <td class="gx-num"><b>${Number(r.score).toLocaleString()}</b></td><td class="gx-num">${Number(r.triples).toLocaleString()}</td>
    <td class="gx-num">${boardData.with_reach ? Number(r.reach).toLocaleString() : "–"}</td><td class="gx-num">${pct(r.completeness)}</td><td class="gx-num">${esc(r.sources)}</td></tr>
    <tr class="gx-board-more" hidden><td></td><td colspan="6">${next}<table class="gx-board-papers"><tr><th>Source</th><th>Merged</th><th>Triples</th><th>Reach</th><th>Complete</th><th>Score</th></tr>${papers}</table></td></tr>`;
}
function drawBoard() {
  const rows = boardData[boardTab] || [];
  if (!rows.length) {
    $("board").innerHTML = `<p class="gx-muted">${boardTab === "recent" ? "Nothing merged in the last 90 days yet." : "No contributions are merged yet: the first source you contribute puts you at the top."}</p>`;
    return;
  }
  const top = rows.slice(0, BOARD_TOP);
  const me = login && rows.find((r, i) => i >= BOARD_TOP && r.github.toLowerCase() === login.toLowerCase());
  $("board").innerHTML = `<table class="gx-board-table"><tr><th>#</th><th>Contributor</th><th class="gx-num">Score</th><th class="gx-num">Triples</th>
    <th class="gx-num" title="Distinct people and days whose questions it answered">Reach</th><th class="gx-num" title="Checklist items and evidence found">Complete</th><th class="gx-num">Sources</th></tr>
    ${top.map(boardRow).join("")}${me ? `<tr class="gx-board-gap"><td colspan="7">…</td></tr>${boardRow(me)}` : ""}</table>`
    + (rows.length > BOARD_TOP && !me ? `<p class="gx-subtle">${rows.length - BOARD_TOP} more contributors.</p>` : "")
    + (boardData.with_reach ? "" : `<p class="gx-subtle">Reach is counted by the curation service; it shows here once the service is set up.</p>`);
  $("board").querySelectorAll(".gx-board-row").forEach((tr) => {
    const toggle = (e) => { if (e.target.closest("a")) return; tr.nextElementSibling.hidden = !tr.nextElementSibling.hidden; tr.classList.toggle("is-open"); };
    tr.onclick = toggle;
    tr.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(e); } };
  });
}
document.querySelectorAll(".gx-board-tab").forEach((b) => (b.onclick = () => {
  boardTab = b.dataset.board;
  document.querySelectorAll(".gx-board-tab").forEach((x) => x.classList.toggle("is-on", x === b));
  if (boardData) drawBoard();
}));
$("board-open").onclick = async () => {
  $("board-dialog").showModal();
  try {
    try { boardData = await call("GET", "/leaderboard"); } catch { boardData = await (await fetch("data/leaderboard.json")).json(); }
    const s = boardData.scoring || {};
    $("board-how").innerHTML = Object.entries(s).map(([k, v]) => `<dt>${esc(k.replace(/_/g, " "))}</dt><dd>${esc(v)}</dd>`).join("");
    drawBoard();
  } catch { $("board").innerHTML = `<p class="gx-muted">The leaderboard is published with the site.</p>`; }
};
$("board-curate").onclick = () => { $("board-dialog").close(); openCurate(); };
// The papers the service keeps because this reader agreed, each with a way to withdraw.
async function showKept() {
  try {
    const r = await call("GET", "/kept");
    $("curate-kept").innerHTML = (r.kept || []).length ? `<details><summary>Sources kept with your agreement (${r.kept.length})</summary><ul>${r.kept.map((k) =>
      `<li>${esc(k.title || k.doi || k.sha256.slice(0, 12))} <button type="button" class="gx-btn gx-btn-tiny" data-forget="${esc(k.sha256)}">Withdraw</button></li>`).join("")}</ul></details>` : "";
    $("curate-kept").querySelectorAll("[data-forget]").forEach((b) => (b.onclick = async () => {
      b.disabled = true;
      try { await call("POST", "/kept/forget", { sha256: b.dataset.forget }); showKept(); } catch (e) { b.disabled = false; alert(e.message); }
    }));
  } catch { $("curate-kept").innerHTML = ""; }
}
// One drop zone and one DOI field: a PDF (with or without its DOI), or a DOI alone.
const pdfName = () => { const f = $("curate-pdf").files[0]; $("curate-pdf-name").textContent = f ? f.name : "Drop a PDF here, or choose one"; $("curate-drop").classList.toggle("has-file", !!f); $("curate-attest-row").hidden = !f; };
$("curate-pdf").onchange = pdfName;
for (const ev of ["dragenter", "dragover"]) $("curate-drop").addEventListener(ev, (e) => { e.preventDefault(); $("curate-drop").classList.add("over"); });
for (const ev of ["dragleave", "drop"]) $("curate-drop").addEventListener(ev, () => $("curate-drop").classList.remove("over"));
$("curate-drop").addEventListener("drop", (e) => {
  e.preventDefault();
  const f = [...(e.dataTransfer?.files || [])].find((x) => x.type === "application/pdf" || /\.pdf$/i.test(x.name));
  if (f) { const dt = new DataTransfer(); dt.items.add(f); $("curate-pdf").files = dt.files; pdfName(); }
});
async function startCuration(again = false) {
  const job = $("curate-job");
  job.hidden = false;
  try {
    if (!token) throw new Error("sign in with GitHub first");
    const f = $("curate-pdf").files[0], doi = $("curate-doi").value.trim();
    if (!f && !doi) throw new Error("give a PDF, a DOI, or both");
    if (f && !$("curate-attest").checked) throw new Error("tick the statement that you have lawful access to this PDF");
    const keep = !$("curate-keep-row").hidden && $("curate-keep").checked;
    const q = new URLSearchParams({ ...(again ? { again: "1" } : {}), ...(keep ? { keep: "1" } : {}) });
    let res;
    if (f) {
      q.set("filename", f.name);
      q.set("attest", "1");
      if (doi) q.set("doi", doi);
      res = await call("POST", `/jobs?${q}`, f, { "Content-Type": "application/pdf" });
    } else res = await call("POST", `/jobs${again ? "?again=1" : ""}`, { doi, keep_text: keep });
    if (res.known) { showKnown(res.known); return; }
    $("curate-start").disabled = true;
    await followJob(res.job);
  } catch (e) { job.innerHTML = `<span class="gx-err">${esc(e.message)}</span>`; }
  $("curate-start").disabled = !token;
}
$("curate-start").onclick = () => startCuration();
// The commons holds the paper already, or an open contribution adds it: nothing was curated and nothing spent.
function showKnown(k) {
  const commons = manifest.find((e) => e.id === "catal-commons");
  $("curate-job").innerHTML = (k.in_commons
    ? `<div class="gx-state">Already in catal-commons</div><div>${k.in_commons.map((h) => `<a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.file)}</a>`).join(", ")}</div>`
    : `<div class="gx-state">Already proposed</div><div><a href="${esc(k.proposed.url)}" target="_blank" rel="noopener">#${esc(k.proposed.number)} ${esc(k.proposed.title)}</a>, waiting for review.</div>`)
    + `<div class="gx-subtle">Nothing was curated, so nothing was spent.</div><p>`
    + (commons && k.in_commons ? `<button type="button" class="gx-btn gx-btn-tiny gx-btn-primary" id="known-open">Open catal-commons</button> ` : "")
    + `<button type="button" class="gx-btn gx-btn-tiny" id="known-again">Curate it anyway</button></p>`;
  $("known-open")?.addEventListener("click", () => { $("curate-dialog").close(); location.hash = "g=catal-commons"; });
  $("known-again").onclick = () => startCuration(true);
}
async function followJob(id) {
  const job = $("curate-job");
  for (;;) {
    let j;
    try { j = await call("GET", `/jobs/${id}`); } catch (e) { job.innerHTML = `<span class="gx-err">${esc(e.message)}</span>`; return; }
    const log = (j.log || []).slice(-12).map((l) => `<li>${esc(l.t)} s · ${esc(l.msg)}</li>`).join("");
    const src = j.source ? `<div class="gx-subtle">${esc(j.source.pages)} pages · rights: ${esc(j.source.rights_class)} · schema ${esc(j.source.schema_version)}</div>` : "";
    job.innerHTML = `<div class="gx-state">${esc(j.state)}</div>${src}<ol>${log}</ol>`;
    if (j.state === "done") {
      job.innerHTML += `<div>${esc(j.summary || "")}</div>`
        + (j.withheld ? `<div class="gx-subtle">${esc(j.withheld)} quotes withheld for the source's rights (their sha256 kept).</div>` : "")
        + `<div class="gx-subtle">The graph is open on the canvas and private to you. Its card on the left downloads it or contributes it to catal-commons.</div>`;
      await openCurated(j.graph, j.receipt);
      return;
    }
    if (j.state === "failed") {
      job.innerHTML += `<div class="gx-err">${esc(j.error)}</div>`;
      return;
    }
    await new Promise((r) => setTimeout(r, 3000));
  }
}
// A graph the service just curated: opened like any other, with the service's receipt, which alone lets it be
// contributed (only that graph, unchanged, by the user it was curated for).
async function openCurated(doc, receipt) {
  if (!doc) return;
  const title = doc.graph?.title || "Curated source";
  const entry = { id: `curated-${title.toLowerCase().replace(/\W+/g, "-").slice(0, 40)}`, title, from: "service" };
  await openGraph(entry, JSON.stringify(doc));
  G.receipt = receipt || null;
  G.contrib = receipt ? `<span class="gx-subtle">Checking catal-commons…</span>` : "";
  renderGraphs();
  if (receipt) checkContribution();
}
function downloadGraph() {
  const B = G.base || G;
  download(`${B.entry.id}.json`, new Blob([JSON.stringify(B.doc, null, 1)], { type: "application/json" }));
}
// Contributing: what it would add is checked as soon as the graph arrives, so one click opens the pull request. What
// becomes public is said next to the button, before it is pressed.
function contribHtml() { return G?.contrib || ""; }
function setContrib(html) { const B = G.base || G; B.contrib = html; const box = $("contrib-box"); if (box) { box.innerHTML = html; wireContrib(); } }
function wireContrib() { $("contrib-go")?.addEventListener("click", contribute); }
async function checkContribution() {
  const B = G.base || G;
  try {
    const r = await call("POST", "/contribute/check", { graph: B.doc, receipt: B.receipt });
    if (r.already) {
      setContrib(`Already in catal-commons: ${r.already.map((h) => `<a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.source)}</a> (the same ${esc(h.by.join(", "))})`).join("; ")}.`);
      return;
    }
    if (r.proposed) {
      setContrib(`Already proposed: <a href="${esc(r.proposed.url)}" target="_blank" rel="noopener">#${esc(r.proposed.number)} ${esc(r.proposed.title)}</a>.`);
      return;
    }
    const p = r.new;
    setContrib(`<button type="button" class="gx-btn gx-btn-tiny gx-btn-primary" id="contrib-go">Contribute to catal-commons</button>
      <ul class="gx-contrib-terms"><li>Adds ${Number(p.records.triples).toLocaleString()} new triples (${esc(p.records.nodes)} records, ${esc(p.records.links)} links), your credit on the leaderboard</li>
        ${p.repeats && (p.repeats.records.length + p.repeats.links + p.repeats.values) ? `<li>${esc(p.repeats.records.length + p.repeats.links + p.repeats.values)} repeats of what catal-commons holds are discarded and not counted</li>` : ""}
        ${p.conflicts && p.conflicts.length ? `<li>${esc(p.conflicts.length)} values differ from catal-commons' records; the reviewer decides</li>` : ""}<li>A public pull request on GitHub, naming you</li>
        <li>Shared under CC BY 4.0; ${esc(p.quotes.kept)} quotes kept, ${esc(p.quotes.withheld)} withheld for the source's rights</li><li>Reviewed by a person before it is merged</li></ul>`);
  } catch (e) { setContrib(`<span class="gx-err">${esc(e.message)}</span>`); }
}
async function contribute() {
  const B = G.base || G;
  $("contrib-go").disabled = true;
  try {
    const o = await call("POST", "/contribute", { graph: B.doc, receipt: B.receipt });
    B.receipt = null;
    setContrib(o.pull_request ? `Opened <a href="${esc(o.pull_request.url)}" target="_blank" rel="noopener">pull request #${esc(o.pull_request.number)}</a>. Thank you.`
      : "It is in catal-commons already, or proposed.");
  } catch (e) { $("contrib-go").disabled = false; setContrib(contribHtml() + `<div class="gx-err">${esc(e.message)}</div>`); }
}

async function start() {
  token = store.get("scale-token");
  readSignIn();
  renderAccount();
  try { manifest = (await (await fetch("data/graphs.json")).json()).graphs || []; } catch { manifest = []; }
  renderGraphs();
  window.onhashchange = () => openFromHash();
  $("graph-file").onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try { await openGraph({ id: f.name.replace(/\W+/g, "-"), title: f.name.replace(/\.json$/, ""), from: "" }, await f.text()); }
    catch (err) { alert(`not a graph: ${err.message}`); }
  };
  await openFromHash();
}

function renderGraphs() {
  const list = G && !manifest.includes(G.entry) ? [G.entry, ...manifest] : manifest;
  $("graphs").innerHTML = list.map((e) => {
    const [scope, c] = scopeOf(e), active = G && G.entry === e, open = active && !folded;
    return `<div role="listitem"><button class="gx-graph-item${active ? " is-active" : ""}" type="button" data-id="${esc(e.id)}" title="${esc(e.title)}"
        aria-expanded="${open}" style="--dot:${c}"><span class="gx-graph-caret">${CARET}</span><span class="gx-graph-dot"></span>
        <span class="gx-graph-title">${esc(e.title)}</span><span class="gx-graph-scope">${scope}</span></button>${open ? details() : ""}</div>`;
  }).join("") || `<p class="gx-muted">No graphs are listed: open a file.</p>`;
  const dl = $("curated-download");
  if (dl) dl.onclick = (ev) => { ev.preventDefault(); downloadGraph(); };
  wireContrib();
  const gs = $("graph-show");
  if (gs) gs.onclick = (ev) => { ev.preventDefault(); showGraph(); };
  const st = $("schema-toggle");
  if (st) st.onclick = (ev) => { ev.preventDefault(); G.base ? leaveSchema() : showSchema(); };
  $("graphs").querySelectorAll(".gx-graph-item").forEach((b) => (b.onclick = (ev) => {
    if (b.classList.contains("is-active")) {      // the open graph: its row folds and unfolds its facts (in the schema
      if (G.base && !ev.target.closest(".gx-graph-caret")) { leaveSchema(); return; }   // view, only its caret does)
      folded = !folded;
      renderGraphs();
      $("graphs").querySelector(".gx-graph-item.is-active")?.focus();
      return;
    }
    const e = manifest.find((x) => x.id === b.dataset.id);
    if (e) location.hash = `g=${encodeURIComponent(e.id)}`;
  }));
}
function details() {
  const B = G.base || G;                          // in the schema view, the facts are still the graph's
  const g = B.doc.graph || {}, e = B.entry, [scope] = scopeOf(e);
  const facts = [
    ["Type", `<a href="#" id="graph-show" title="Show the graph on the canvas">Knowledge graph</a>${G.base ? "" : ` <span class="gx-subtle">(shown)</span>`}${scope === "synthetic" ? ` <span class="gx-warn">synthetic example</span>` : ""}`],
    ["Size", `${B.doc.nodes.length.toLocaleString()} nodes · ${B.doc.links.length.toLocaleString()} rels · ${B.props.toLocaleString()} props`],
    g.version ? ["Release", esc(g.version)] : null,
    ["Visibility", e.from === "service" ? "Private to you, until you contribute it" : esc(((g.stewardship || {}).access || "public").replace(/^./, (c) => c.toUpperCase()))],
    g.created || g.date ? ["Created", esc(g.created || g.date)] : null,
    ["Checksum", B.sha ? `<span class="gx-sha" title="sha256 ${esc(B.sha)}">${esc(B.sha.slice(0, 12))}…</span>` : "…"],
    ["Source", e.from === "service" ? "curated by the service just now" : e.from ? `<a href="https://github.com/hlxin/scale/tree/main/${esc(e.from)}">${esc(e.from)}</a>` : "a file on this computer"],
    ["Schema", `<a href="#" id="schema-toggle" title="${G.base ? "Back to the graph" : "Show the schema on the canvas"}">${esc(g.schema || "scale-catal")} v${esc(g.schema_version || "?")}</a>${G.base ? ` <span class="gx-subtle">(shown)</span>` : ""}<br>
      ${B.labels.size} labels · ${B.rels.size} rel types · ${schemaPropCount(B).toLocaleString()} props`],
    e.from === "service" ? ["Graph", `<a href="#" id="curated-download">Download</a>`] : null,
  ].filter(Boolean);
  return `<div class="gx-graph-detail"><dl class="gx-facts">${facts.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`
    + (e.from === "service" ? `<div class="gx-contrib" id="contrib-box">${B.contrib || ""}</div>` : "") + `</div>`;
}

// ------------------------------------------------------------------------------------------ the schema view
// The graph's schema as the graph uses it: a node per label, a link per label -> relationship type -> label, each with
// the properties its records carry and how many of them carry each. It is drawn on the canvas in place of the graph
// (G.base keeps the graph); search, questions and the tools still read the graph.
const SCHEMA = "schema:";
function schemaOf(B) {
  const nodes = new Map(), links = new Map();
  const tally = (into, props) => { for (const k of Object.keys(props || {})) into.set(k, (into.get(k) || 0) + 1); };
  for (const n of B.doc.nodes) {
    const s = nodes.get(n.label) || nodes.set(n.label, { n: 0, props: new Map() }).get(n.label);
    s.n += 1; tally(s.props, n.props);
  }
  for (const e of B.doc.links) {
    const a = B.byId.get(e.source)?.label ?? "?", b = B.byId.get(e.target)?.label ?? "?", key = `${a}|${e.type}|${b}`;
    const s = links.get(key) || links.set(key, { a, b, type: e.type, n: 0, props: new Map() }).get(key);
    s.n += 1; tally(s.props, e.props);
  }
  const props = (s, what) => Object.fromEntries([["records", `${s.n.toLocaleString()} ${what}`],
    ...[...s.props].sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0]))
      .map(([k, c]) => [k === "name" || k === "records" ? `${k} (property)` : k, `on ${c.toLocaleString()} of ${s.n.toLocaleString()}`])]);
  return {
    graph: { title: `Schema of ${B.doc.graph?.title || B.entry.title}` },
    nodes: [...nodes].map(([l, s]) => ({ id: `${SCHEMA}label/${l}`, label: l, props: { name: l, ...props(s, s.n === 1 ? "record" : "records") } })),
    links: [...links.values()].map((s) => ({ id: `${SCHEMA}rel/${s.a}/${s.type}/${s.b}`, type: s.type, source: `${SCHEMA}label/${s.a}`,
      target: `${SCHEMA}label/${s.b}`, props: props(s, s.n === 1 ? "link" : "links") })),
  };
}
function schemaPropCount(B) {
  const seen = new Set();
  for (const n of B.doc.nodes) for (const k of Object.keys(n.props || {})) seen.add(`${n.label}.${k}`);
  for (const e of B.doc.links) for (const k of Object.keys(e.props || {})) seen.add(`${e.type}.${k}`);
  return seen.size;
}
function showSchema() {
  if (!G || G.base) return;
  const B = G, doc = schemaOf(B);
  const byId = new Map(doc.nodes.map((n) => [n.id, n])), out = new Map(), inn = new Map();
  for (const e of doc.links) {
    (out.get(e.source) || out.set(e.source, []).get(e.source)).push(e);
    (inn.get(e.target) || inn.set(e.target, []).get(e.target)).push(e);
  }
  B.view = { kind: S.kind, rel: S.rel, sources: S.sources, hidden: S.hidden, extra: S.extra, pos: S.pos };
  G = { ...B, doc, byId, out, inn, base: B };
  Object.assign(S, { kind: null, rel: null, sources: true, hidden: new Set(), extra: new Set(), match: null, selected: null, pos: new Map(), nodes: [] });
  $("card").hidden = true;
  renderGraphs(); renderLegend(); showLegend(); draw();
  status(`The schema of ${B.entry.title}: ${doc.nodes.length} labels, ${doc.links.length} label-to-label relationships. Click Knowledge graph or its name on the left to go back.`);
}
function leaveSchema() {
  if (!G || !G.base) return;
  const B = G.base;
  G = B;
  Object.assign(S, { ...B.view, match: null, selected: null, nodes: [] });
  $("card").hidden = true;
  renderGraphs(); renderLegend(); showLegend(); draw();
  status(ready());
}

// the graph itself on the canvas: back from the schema, else fitted to the view
function showGraph() {
  if (!G) return;
  if (G.base) leaveSchema(); else fit();
}

async function openFromHash() {
  const want = new URLSearchParams(location.hash.slice(1)).get("g");
  const entry = manifest.find((g) => g.id === want) || manifest[0];
  if (!entry || (G && G.entry === entry)) return;
  status(`Loading ${entry.title}…`);
  $("empty").hidden = false;
  $("empty").innerHTML = `<p>Loading graph…</p>`;
  const text = await (await fetch(entry.path)).text();
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
  folded = false;
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
// one arrowhead per edge colour, filled with it, so a link's head is the colour of its line (an attribute, not a style,
// so that an exported SVG keeps it)
d3.select("#gx-defs").selectAll("marker").data(EDGE_PALETTE).join("marker")
  .attr("id", (_, i) => `gx-arrow-${i}`).attr("viewBox", "0 -5 10 10").attr("refX", 9).attr("refY", 0)
  .attr("markerWidth", 10).attr("markerHeight", 10).attr("orient", "auto").attr("markerUnits", "userSpaceOnUse")
  .append("path").attr("d", "M0,-5 L10,0 L0,5").attr("fill", (c) => c).attr("fill-opacity", 0.8);
const arrowFor = (t) => `url(#gx-arrow-${EDGE_PALETTE.indexOf(colourForEdge(t))})`;
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
// A node's radius depends on its own number of links, never on the rest of the graph, so a node and the arrowheads
// (a fixed size) keep their proportions however large the graph grows.
const radius = (id) => Math.min(NODE_R_MAX, NODE_R_MIN + NODE_R_STEP * Math.sqrt(Math.max((S.degree.get(id) || 0) - 1, 0)));
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
    g.append("path");
    g.append("text").attr("class", "gx-link-label").attr("dy", -3);
    return g;
  });
  link.select("path").attr("stroke", (d) => colourForEdge(d.type)).attr("stroke-opacity", 0.55)
    .attr("marker-end", (d) => arrowFor(d.type));
  // links are drawn as arcs: each bends to its left, so a link and its reverse part, and the links between one pair
  // of nodes fan out (the k-th of n bends further)
  const pairs = new Map();
  for (const e of S.links) {
    const a = e.source.id ?? e.source, b = e.target.id ?? e.target, key = a < b ? `${a}|${b}` : `${b}|${a}`;
    const list = pairs.get(key) || []; list.push(e); pairs.set(key, list);
  }
  for (const list of pairs.values()) list.forEach((e, i) => { e.bend = 0.16 + 0.14 * i; });
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
  const lines = link.select("path").nodes(), labels = link.select("text").nodes(), groups = node.nodes();
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
  for (const el of lines) {
    const d = el.__data__;
    const x1 = d.source.x, y1 = d.source.y, dx = d.target.x - x1, dy = d.target.y - y1, len = Math.hypot(dx, dy);
    if (d.source === d.target) {                               // a loop above the node, wider for each further one
      const r = radius(d.source.id), w = r + 10 + 14 * ((d.bend - 0.16) / 0.14), h = r + 26 + 16 * ((d.bend - 0.16) / 0.14);
      el.setAttribute("d", `M${x1 + r * 0.5},${y1 - r * 0.85} C${x1 + w},${y1 - h} ${x1 - w},${y1 - h} ${x1 - r * 0.5},${y1 - r * 0.85}`);
      d.mid = [x1, y1 - h * 0.78];
      continue;
    }
    if (!(len > 0)) { el.setAttribute("d", ""); continue; }
    const b = (d.bend ?? 0.16) * len;                          // the control point, off the chord to its left
    const cx = (x1 + d.target.x) / 2 + (dy / len) * b, cy = (y1 + d.target.y) / 2 - (dx / len) * b;
    let x2 = d.target.x, y2 = d.target.y;
    const tx = x2 - cx, ty = y2 - cy, tl = Math.hypot(tx, ty);   // end at the target's rim, so the arrowhead shows
    if (tl > 0) { const r = Math.min(tl - 1, radius(d.target.id) + 2); x2 -= (tx / tl) * r; y2 -= (ty / tl) * r; }
    el.setAttribute("d", `M${x1},${y1} Q${cx},${cy} ${x2},${y2}`);
    d.mid = [0.25 * x1 + 0.5 * cx + 0.25 * d.target.x, 0.25 * y1 + 0.5 * cy + 0.25 * d.target.y];
  }
  if (showLabels) for (const el of labels) {
    const d = el.__data__;
    const [mx, my] = d.mid || [(d.source.x + d.target.x) / 2, (d.source.y + d.target.y) / 2];
    el.setAttribute("x", mx); el.setAttribute("y", my);
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
  d3.selectAll("#links path").classed("dim", (d) => !!m && !(m.has(d.source.id ?? d.source) && m.has(d.target.id ?? d.target)));
}
$("card-close").onclick = () => { $("card").hidden = true; S.match = null; markMatches(); };
$("card-collapse").onclick = () => $("card").classList.toggle("collapsed");

async function search(q) {
  leaveSchema();
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
      : `<p>No evidence matches “${esc(q)}”.</p>`) + (SERVICE && !token ? `<p class="gx-meta">These are the quotes that match, found in this browser.
        <a href="${esc(signInUrl())}">Sign in with GitHub</a> to have
        questions answered in words: free, no API key.</p>` : ""));
    $("card-body").querySelectorAll(".gx-hit").forEach((el) => (el.onclick = () => goTo(el.dataset.id)));
  } catch (err) { card("Matching evidence", `<p class="gx-card-warn">${esc(err.message)}</p>`); }
}
// ------------------------------------------------------------------------------------------ answers in words
// The page keeps the service's session token only (sessionStorage, or localStorage when it was saved before).
const store = { get(k) { try { return localStorage.getItem(k) || sessionStorage.getItem(k) || ""; } catch { return ""; } },
  set(k, v, keep) { try { (keep ? localStorage : sessionStorage).setItem(k, v); if (!keep) localStorage.removeItem(k); } catch { /* storage off */ } } };
// A question is answered by the service (the query-graph skill over this graph, within the service's budget) for a
// signed-in reader; anyone else sees the matching evidence, found in this browser.
async function ask(question) {
  leaveSchema();
  card("Answer", `<p class="gx-meta">Answering… the service runs query plans over this graph.</p>`);
  try {
    const r = await call("POST", "/ask", { graph: (G.base || G).doc, question });
    card("Answer", `${idLinks(md(r.answer || "No answer."))}
      ${(r.plans || []).length ? `<details><summary>How it was answered (${r.plans.length} plan${r.plans.length > 1 ? "s" : ""})</summary>${r.plans.map((p, i) =>
        `<p class="gx-meta">Plan ${i + 1}: ${esc(p.status || "?")}, ${p.rows ?? 0} rows</p><pre>${esc(JSON.stringify(p.plan, null, 1))}</pre>`).join("")}</details>` : ""}
      <p class="gx-meta">about ${Number(r.tokens || 0).toLocaleString()} tokens, from the service's budget</p>`);
  } catch (err) { card("Answer", `<p class="gx-card-warn">${esc(err.message || err)}</p>`); search(question); }
}

// ------------------------------------------------------------------------------------------ controls
$("search-form").onsubmit = (e) => {
  e.preventDefault();
  const q = $("search-input").value.trim();
  if (!q || !G) return;
  if (SERVICE && token) ask(q); else search(q);
};
$("labels-btn").onclick = () => { S.linkLabels = linkLabelsShown() ? "off" : "on"; draw(); };
$("unhide-btn").onclick = () => { S.hidden.clear(); draw(); };
const menus = [[$("layout-btn"), $("layout-menu")], [$("export-btn"), $("export-menu")], [$("account-btn"), $("account-menu")]];
for (const [btn, box] of menus) btn.onclick = (e) => { e.stopPropagation(); for (const [, b] of menus) if (b !== box) b.hidden = true; box.hidden = !box.hidden; btn.setAttribute("aria-expanded", String(!box.hidden)); };
document.addEventListener("click", () => { for (const [, b] of menus) b.hidden = true; });
$("account-btn").onclick = (e) => {
  e.stopPropagation();
  for (const [, b] of menus) if (b !== $("account-menu")) b.hidden = true;
  if ($("account-menu").hidden) accountMenu();
  else { $("account-menu").hidden = true; $("account-btn").setAttribute("aria-expanded", "false"); }
};
$("account-menu").onclick = (e) => e.stopPropagation();
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
  clone.querySelectorAll("#links path").forEach((l) => { l.setAttribute("stroke-width", "1.6"); l.setAttribute("fill", "none"); });
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
  relayout();
}
// The canvas changed width: the graph re-centres once (not on every frame of a drag).
function relayout() {
  if (S.sim && !S.viewMoved) setTimeout(() => fit(), 50);
}
// The panels' widths are the reader's: a drag on a border (measured from the grid's edge), the arrow keys (Shift for
// bigger steps), double-click or Home for the default. Each is kept between its minimum and half the window, and
// remembered on this device.
function resizer(handle, prop, side, min, def) {
  const grid = $("grid"), key = `scale-explorer-${prop}`;
  const max = () => Math.max(min, Math.round(window.innerWidth * 0.5));
  let width = def;
  try { width = Number(localStorage.getItem(key)) || def; } catch { /* storage off */ }
  const paint = () => { const shown = Math.min(width, max()); grid.style.setProperty(`--${prop}`, `${shown}px`); handle.setAttribute("aria-valuenow", String(shown)); };
  const apply = (px) => { width = Math.round(Math.min(Math.max(px, min), max())); paint(); };
  const keep = () => { try { localStorage.setItem(key, String(width)); } catch { /* storage off */ } relayout(); };
  handle.setAttribute("aria-valuemin", String(min));
  apply(width);
  let dragging = false;
  handle.addEventListener("pointerdown", (e) => {
    dragging = true; handle.dataset.dragging = "true"; document.body.dataset.resizing = "true";
    try { handle.setPointerCapture(e.pointerId); } catch { /* unsupported */ }
    e.preventDefault();
  });
  handle.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const r = grid.getBoundingClientRect();
    apply(side === "left" ? e.clientX - r.left : r.right - e.clientX);
  });
  const end = (e) => {
    if (!dragging) return;
    dragging = false; delete handle.dataset.dragging; delete document.body.dataset.resizing;
    try { handle.releasePointerCapture(e.pointerId); } catch { /* released */ }
    keep();
  };
  handle.addEventListener("pointerup", end);
  handle.addEventListener("pointercancel", end);
  handle.addEventListener("dblclick", () => { apply(def); keep(); });
  handle.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 48 : 16, grow = side === "left" ? 1 : -1;
    let next = null;
    if (e.key === "ArrowLeft") next = width - step * grow;
    else if (e.key === "ArrowRight") next = width + step * grow;
    else if (e.key === "Home") next = def;
    if (next === null) return;
    e.preventDefault(); apply(next); keep();
  });
  window.addEventListener("resize", paint);                 // a narrower window shows less, the chosen width is kept
}
resizer($("rail-resizer"), "rail-w", "left", 200, 280);
resizer($("inspector-resizer"), "inspector-w", "right", 240, 300);
$("rail-collapse").onclick = () => panel("rail", false);
$("rail-show").onclick = () => panel("rail", true);
$("inspector-collapse").onclick = () => panel("inspector", false);
$("inspector-show").onclick = () => panel("inspector", true);
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", (e) => { document.documentElement.dataset.theme = e.matches ? "dark" : "light"; });

start().catch((err) => status(`Could not start: ${err.message}`));
