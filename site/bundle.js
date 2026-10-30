// A knowledge-graph bundle (docs/kg-bundle-format.md), the zip `scale graph export --to kg-bundle` makes, read in the
// browser and turned into a graph the explorer draws. The bundle's graph is node-link JSON like a scale-catal document;
// only its property names differ: evidence is `_evidence` (quote, locator object, source_id), a source is a
// `Publication:<id>` node, and a value is a quantity in one canonical unit. Display only: nothing is validated here.
//
// A bundle's graph can be larger than a browser holds as one text (the train split of a dataset can pass 900 MB), so
// the zip is read from the file a slice at a time and the graph a record at a time as it is decompressed. A graph with
// more records than the explorer draws at once is kept whole, each record as compact text (UTF-8, outside the
// script's memory), and drawn a window at a time: the sources in an order (by year, or around a source, those most like
// it first), as many records as the reader chooses, the windows one after the other covering the whole graph; search
// covers every record.

export const WHOLE_RECORDS = 60000;    // a larger graph is drawn a window at a time

// Read a stream to its end, a chunk at a time.
async function* chunksOf(stream) {
  const r = stream.getReader();
  for (;;) {
    const { done, value } = await r.read();
    if (done) return;
    yield value;
  }
}

// The files of a zip, by name: each { size, chunks(), text() }, read on demand from the file a slice at a time
// (stored or deflated entries; no zip64, no encryption).
async function unzip(file) {
  const blob = typeof file.slice === "function" ? file : new Blob([await file.arrayBuffer()]);
  const at = async (from, to) => new DataView(await blob.slice(from, to).arrayBuffer());
  const tail = await at(Math.max(0, blob.size - 22 - 65535), blob.size);
  let end = -1;
  for (let i = tail.byteLength - 22; i >= 0; i--) {
    if (tail.getUint32(i, true) === 0x06054b50) { end = i; break; }
  }
  if (end < 0) throw new Error("not a zip file");
  const count = tail.getUint16(end + 10, true), cdSize = tail.getUint32(end + 12, true), cdAt = tail.getUint32(end + 16, true);
  if (cdAt === 0xffffffff || count === 0xffff) throw new Error("a zip64 file: zip the bundle again with a standard zip");
  const v = await at(cdAt, cdAt + cdSize), u8 = new Uint8Array(v.buffer, v.byteOffset, v.byteLength);
  const utf8 = new TextDecoder();
  const files = new Map();
  for (let k = 0, p = 0; k < count; k++) {
    if (v.getUint32(p, true) !== 0x02014b50) throw new Error("a damaged zip file");
    const flags = v.getUint16(p + 8, true), method = v.getUint16(p + 10, true);
    const csize = v.getUint32(p + 20, true), size = v.getUint32(p + 24, true);
    const nlen = v.getUint16(p + 28, true), xlen = v.getUint16(p + 30, true), clen = v.getUint16(p + 32, true);
    const local = v.getUint32(p + 42, true), name = utf8.decode(u8.subarray(p + 46, p + 46 + nlen));
    p += 46 + nlen + xlen + clen;
    if (name.endsWith("/")) continue;
    const chunks = async () => {                     // the file's text, a piece at a time as it is decompressed
      if (flags & 1) throw new Error(`${name}: encrypted`);
      if (method !== 0 && method !== 8) throw new Error(`${name}: compressed in a way this page cannot read (method ${method})`);
      const h = await at(local, local + 30);
      const start = local + 30 + h.getUint16(26, true) + h.getUint16(28, true);
      let s = blob.slice(start, start + csize).stream();
      if (method === 8) s = s.pipeThrough(new DecompressionStream("deflate-raw"));
      return chunksOf(s.pipeThrough(new TextDecoderStream()));
    };
    files.set(name, { size, chunks, text: async () => { const t = []; for await (const c of await chunks()) t.push(c); return t.join(""); } });
  }
  return files;
}

// A graph's text, read a piece at a time: each element of its "nodes" and "links" arrays is parsed alone and handed
// to `each(key, element, text)`, so the graph is never one text; its other top-level values are returned.
const QUOTE = /["\\]/g;
async function scanGraph(pieces, each, progress = () => {}) {
  const top = {};
  let depth = 0, inStr = false, esc = false, afterColon = false, key = null, arr = null, cap = null, read = 0;
  for await (const s of pieces) {
    let from = 0;                                   // where the value being captured starts in this piece
    for (let i = 0; i < s.length; i++) {
      if (inStr) {                                  // a string's text is skipped at once, to its next quote or backslash
        if (esc) { esc = false; continue; }
        QUOTE.lastIndex = i;
        const m = QUOTE.exec(s);
        if (!m) break;                              // the string goes on in the next piece
        i = m.index;
        if (s.charCodeAt(i) === 92) { esc = true; continue; }   // \
        inStr = false;                              // the string ends; a key at the top level is kept
        if (cap?.kind === "key") { cap.text.push(s.slice(from, i + 1)); key = JSON.parse(cap.text.join("")); cap = null; }
        continue;
      }
      const c = s.charCodeAt(i);
      if (c === 34) {                               // "
        inStr = true;
        if (depth === 1 && !afterColon) { cap = { kind: "key", text: [] }; from = i; }
      } else if (c === 123 || c === 91) {           // { [
        if (depth === 1 && c === 91 && afterColon && (key === "nodes" || key === "links")) arr = key;
        else if (depth === 2 && arr && c === 123) { cap = { kind: "item", text: [] }; from = i; }
        depth++;
      } else if (c === 125 || c === 93) {           // } ]
        depth--;
        if (cap?.kind === "item" && depth === 2) { cap.text.push(s.slice(from, i + 1)); const t = cap.text.join(""); each(arr, JSON.parse(t), t); cap = null; }
        else if (depth === 1 && c === 93 && arr) arr = null;
        else if (depth === 0 && cap?.kind === "value") { cap.text.push(s.slice(from, i)); top[key] = JSON.parse(cap.text.join("")); cap = null; }
      } else if (depth === 1 && c === 58) {         // : a top-level value starts (the two arrays are read element by element)
        afterColon = true;
        if (key !== "nodes" && key !== "links") { cap = { kind: "value", text: [] }; from = i + 1; }
      } else if (depth === 1 && c === 44) {         // , the top-level value ends
        if (cap?.kind === "value") { cap.text.push(s.slice(from, i)); top[key] = JSON.parse(cap.text.join("")); cap = null; }
        afterColon = false;
      }
    }
    if (cap) cap.text.push(s.slice(from));
    progress((read += s.length));
  }
  return top;
}

const LOCATOR_ORDER = ["page", "section", "figure", "table", "equation", "paragraph", "line"];
function locatorText(loc) {
  if (!loc || typeof loc !== "object") return loc || "";
  const seen = new Set();                            // a section named after its figure ("Figure 3") is said once
  const keys = [...LOCATOR_ORDER.filter((k) => k in loc), ...Object.keys(loc).filter((k) => !LOCATOR_ORDER.includes(k))]
    .filter((k) => !seen.has(String(loc[k])) && seen.add(String(loc[k])));
  return keys.map((k) => (k === "page" ? `p. ${loc[k]}` : String(loc[k]).toLowerCase().startsWith(k) ? loc[k] : `${k} ${loc[k]}`)).join(", ");
}
function evidence(list, sourceOf) {
  return list.map((e) => ({
    quote: e.quote ?? (e.quote_withheld ? `Quote withheld (copyright, ${e.quote_withheld.chars} characters).` : ""),
    locator: locatorText(e.locator), source: sourceOf(e.source_id), ...(e.reading ? { reading: e.reading } : {}),
  }));
}
// A quantity ({value, unit, as_reported, uncertainty}) reads as a value the source reports; a typed absence
// (`_value_status`) comes back as the property's own value object; a map or list of values, which a bundle keeps as
// JSON text, is read back.
function props(p, sourceOf) {
  const out = {};
  for (const [k, v] of Object.entries(p || {})) {
    if (k === "_evidence") out.evidence = evidence(v, sourceOf);
    else if (k === "_value_status" && v && typeof v === "object") Object.assign(out, Object.fromEntries(Object.entries(v).filter(([n]) => !(n in p))));
    else if (v && typeof v === "object" && !Array.isArray(v) && "value" in v && !("status" in v)) out[k] = { status: "present", ...v };
    else if (typeof v === "string" && /^[[{]/.test(v)) { try { out[k] = JSON.parse(v); } catch { out[k] = v; } }
    else out[k] = v;
  }
  return out;
}

// Texts kept as UTF-8 in large blocks, each found again by its block, bytes and characters: a record decodes alone,
// and a search reads a whole block as one text, where each record's characters lie at a known place.
class Texts {
  constructor(block = 64 << 20) { this.block = block; this.blocks = []; this.used = []; this.chars = []; this.at = []; this.enc = new TextEncoder(); this.dec = new TextDecoder(); }
  put(text) {                                       // its number
    let b = this.blocks.length - 1;
    if (b < 0 || this.used[b] + text.length * 3 > this.blocks[b].length) {   // at most three bytes for each character
      this.blocks.push(new Uint8Array(Math.max(this.block, text.length * 3))); this.used.push(0); this.chars.push(0); b++;
    }
    const { written } = this.enc.encodeInto(text, this.blocks[b].subarray(this.used[b]));
    this.at.push(b, this.used[b], written, this.chars[b], text.length);
    this.used[b] += written; this.chars[b] += text.length;
    return this.at.length / 5 - 1;
  }
  get(k) { const a = this.at, b = a[5 * k]; return this.dec.decode(this.blocks[b].subarray(a[5 * k + 1], a[5 * k + 1] + a[5 * k + 2])); }
}

// The bundle in a zip file, for the explorer: { title, version, doc } (doc: nodes and links, a scale-catal document's
// shape), or, for a graph of more than WHOLE_RECORDS records, the whole graph to draw around one source at a time:
// { title, version, records, sources (each { title, year, records }), years, start, view(centre, from, width),
// around(centre, width), startOf(year), search(query, k), sourceOf(id), mainOf(year) }.
export async function readBundle(file, say = () => {}, { whole = WHOLE_RECORDS } = {}) {
  const files = await unzip(file);
  const names = [...files.keys()].filter((n) => !n.startsWith("__MACOSX/"));
  const manifestName = names.filter((n) => /^([^/]+\/)?bundle\.json$/.test(n)).sort((a, b) => a.length - b.length)[0];
  if (!manifestName) throw new Error("no bundle.json: this zip is not a knowledge-graph bundle");
  const dir = manifestName.slice(0, -"bundle.json".length);
  const manifest = JSON.parse(await files.get(manifestName).text());
  const graphName = dir + (manifest.graph_file || "kg/graph.json");
  const entry = files.get(graphName);
  if (!entry) throw new Error(`the bundle has no ${graphName}`);
  const mb = (n) => `${Math.round(n / 1e6).toLocaleString()} MB`;
  let told = 0;                                     // the progress is told a few times a second, not for every piece
  const progress = (n) => { const now = Date.now(); if (now - told > 250) { told = now; say(`Reading the bundle… ${mb(n)} of ${mb(entry.size)}`); } };

  // Read once: each record's id, label and text, each link's ends and text, each source's title and year; the
  // records themselves too while they are few enough to draw whole.
  const index = new Map(), labels = [], ends = [], reported = [], pubs = new Map(), named = new Map();
  const texts = new Texts(), nodeText = [], linkText = [];
  let kept = { nodes: [], links: [] };
  const at = (id) => { let i = index.get(id); if (i === undefined) { i = labels.length; index.set(id, i); labels.push(null); } return i; };
  const top = await scanGraph(await entry.chunks(), (key, x, text) => {
    if (key === "nodes") {
      const i = at(x.id);
      labels[i] = named.get(x.label) || (named.set(x.label, x.label), x.label);
      if (x.label === "Publication") pubs.set(i, { title: String(x.props?.title || x.id), year: Number.parseInt(x.props?.year, 10) || null });
      nodeText[i] = texts.put(text);
    } else { ends.push(at(x.source), at(x.target)); reported.push(x.type === "REPORTED_IN" ? 1 : 0); linkText.push(texts.put(text)); }
    if (kept) { kept[key].push(x); if (labels.length > whole) kept = null; }
  }, progress);
  const title = manifest.topic || top.graph?.topic || manifest.bundle_id || file.name;
  const toDoc = (nodes, links, extra = {}) => {
    const sourceOf = (sid) => (index.has(`Publication:${sid}`) ? `Publication:${sid}` : sid);
    return {
      directed: true, multigraph: true,
      graph: { ...(top.graph || {}), title, ...extra,
        bundle: { id: manifest.bundle_id, version: manifest.version, format: manifest.format, format_version: manifest.format_version } },
      // a Publication is the bundle's name for a source: shown, and hidden until asked for, like a graph's sources
      nodes: nodes.map((n) => ({ id: n.id, label: n.label === "Publication" ? "Source" : n.label, props: props(n.props, sourceOf) })),
      links: links.map((e) => ({ id: e.id, source: e.source, target: e.target, type: e.type, props: props(e.props, sourceOf) })),
    };
  };
  if (kept) {
    if (!kept.nodes.length && !kept.links.length) throw new Error(`${graphName} has no nodes and links`);
    return { title, version: manifest.version, doc: toDoc(kept.nodes, kept.links) };
  }
  say("Indexing the bundle…");
  return { title, version: manifest.version,
    ...wholeGraph({ labels, ends, reported, pubs, index, texts, nodeText, linkText, toDoc }) };
}

// The whole graph of a large bundle, drawn a window at a time. A source's records are those it reports; records only
// one source reports are its own, and what they link to that other sources report too (a species, an instrument, a
// material) is what sources share. Sources like a source are those that share the most with it (a thing few sources
// share counts more; one that most share, like water, not at all). A window brings each of its sources' records and
// what their own records link to, so no link of a drawn source's own records is cut.
function wholeGraph({ labels, ends, reported, pubs, index, texts, nodeText, linkText, toDoc }) {
  const n = labels.length, nLinks = reported.length, ids = [...index.keys()];
  const pubOf = new Int32Array(n).fill(-1), more = new Map();
  for (let e = 0; e < nLinks; e++) {
    const a = ends[2 * e], b = ends[2 * e + 1];
    if (!reported[e] || !pubs.has(b)) continue;
    if (pubOf[a] < 0) pubOf[a] = b; else (more.get(a) || more.set(a, []).get(a)).push(b);
  }
  const own = (v) => pubOf[v] >= 0 && !more.has(v);
  // each record's links (both ends), as one list per record
  const start = new Int32Array(n + 1);
  for (let e = 0; e < nLinks; e++) { start[ends[2 * e] + 1]++; start[ends[2 * e + 1] + 1]++; }
  for (let v = 0; v < n; v++) start[v + 1] += start[v];
  const adj = new Int32Array(2 * nLinks), fill = start.slice(0, n);
  for (let e = 0; e < nLinks; e++) { adj[fill[ends[2 * e]]++] = e; adj[fill[ends[2 * e + 1]]++] = e; }
  // each source's records, and what its own records share with other sources
  const src = [...pubs.keys()], number = new Map(src.map((v, s) => [v, s])), S = src.length;
  const recs = Array.from({ length: S }, () => []), shared = Array.from({ length: S }, () => []);
  for (let v = 0; v < n; v++) {
    if (pubOf[v] < 0) continue;
    recs[number.get(pubOf[v])].push(v);
    for (const b of more.get(v) || []) recs[number.get(b)].push(v);
  }
  const stamp = new Int32Array(n).fill(-1), df = new Int32Array(n);
  for (let s = 0; s < S; s++) for (const v of recs[s]) {
    if (!own(v)) continue;
    for (let k = start[v]; k < start[v + 1]; k++) {
      const e = adj[k];
      if (reported[e]) continue;
      const u = ends[2 * e] === v ? ends[2 * e + 1] : ends[2 * e];
      if (own(u) || pubs.has(u) || stamp[u] === s) continue;
      stamp[u] = s; shared[s].push(u); df[u]++;
    }
  }
  const postStart = new Int32Array(n + 1);
  for (let u = 0; u < n; u++) postStart[u + 1] = postStart[u] + df[u];
  const post = new Int32Array(postStart[n]), pfill = postStart.slice(0, n);
  for (let s = 0; s < S; s++) for (const u of shared[s]) post[pfill[u]++] = s;
  const common = Math.max(25, Math.ceil(S * 0.02));  // shared by more sources than this: says nothing about likeness
  const sources = src.map((v, s) => ({ ...pubs.get(v), records: recs[s].length }));
  const years = [...new Set(sources.map((x) => x.year).filter(Boolean))].sort((a, b) => a - b);
  const richest = (keep) => { let best = -1; for (let s = 0; s < S; s++) if (keep(s) && (best < 0 || recs[s].length > recs[best].length)) best = s; return best; };

  const mask = new Uint8Array(n), linkMark = new Uint8Array(nLinks), score = new Float64Array(S);
  // a source's records, and what its own records link to, added to the records drawn (each once)
  const addSource = (s, nodes) => {
    const add = (v) => { if (!mask[v]) { mask[v] = 1; nodes.push(v); } };
    add(src[s]);
    for (const v of recs[s]) {
      add(v);
      if (!own(v)) continue;
      for (let k = start[v]; k < start[v + 1]; k++) { const e = adj[k]; add(ends[2 * e] === v ? ends[2 * e + 1] : ends[2 * e]); }
    }
  };
  // The sources in an order: by year, the oldest first (centre null), or around a source: it, those sharing the most
  // with it, then the nearest in year. Each order keeps, for each place, the records drawn up to it, so that a window
  // of the order is a range of records, and windows one after the other cover the whole graph.
  const orders = new Map();
  function orderOf(centre) {
    const key = centre ?? "year";
    if (orders.has(key)) return orders.get(key);
    const year = (s) => sources[s].year ?? 3000, all = Array.from({ length: S }, (_, s) => s);
    let order;
    if (centre == null) order = all.sort((a, b) => year(a) - year(b) || a - b);
    else {
      for (const u of shared[centre]) {
        if (df[u] > common) continue;
        const w = 1 / Math.log2(1 + df[u]);
        for (let k = postStart[u]; k < postStart[u + 1]; k++) score[post[k]] += w;
      }
      score[centre] = Infinity;
      const y0 = year(centre);
      order = all.sort((a, b) => score[b] - score[a] || Math.abs(year(a) - y0) - Math.abs(year(b) - y0) || a - b);
      score.fill(0);
    }
    const upTo = new Int32Array(S), seen = [];
    order.forEach((s, k) => { addSource(s, seen); upTo[k] = seen.length; });
    for (const v of seen) mask[v] = 0;
    if (orders.size >= 8) orders.clear();
    const o = { order, upTo };
    orders.set(key, o);
    return o;
  }
  // The window of an order that starts at record `from` (the source holding it) and holds sources while the records
  // stay within `width`: its doc, and where it lies ({ from, to, total }, in records of the order).
  function view(centre, from, width) {
    const { order, upTo } = orderOf(centre), total = upTo[S - 1];
    let k0 = 0, hi = S - 1;                              // the first source whose records reach past `from`
    from = Math.max(0, Math.min(from, total - 1));
    while (k0 < hi) { const mid = (k0 + hi) >> 1; if (upTo[mid] > from) hi = mid; else k0 = mid + 1; }
    const nodes = [], drawn = [];
    for (let k = k0; k < S; k++) {
      const before = nodes.length;
      addSource(order[k], nodes);
      if (nodes.length > width && drawn.length) {       // this source would pass the width: it stays out
        for (const v of nodes.splice(before)) mask[v] = 0;
        break;
      }
      drawn.push(order[k]);
    }
    const links = [];
    for (const v of nodes) for (let k = start[v]; k < start[v + 1]; k++) {
      const e = adj[k];
      if (!linkMark[e] && mask[ends[2 * e]] && mask[ends[2 * e + 1]]) { linkMark[e] = 1; links.push(e); }
    }
    for (const v of nodes) mask[v] = 0;
    for (const e of links) linkMark[e] = 0;
    const ys = drawn.map((s) => sources[s].year).filter(Boolean), c = centre == null ? null : sources[centre];
    const where = { order: centre == null ? "year" : "around", from: k0 ? upTo[k0 - 1] : 0, to: upTo[k0 + drawn.length - 1], total,
      sources: drawn.length, records: nodes.length, years: ys.length ? [Math.min(...ys), Math.max(...ys)] : null,
      ...(c ? { source: ids[src[centre]], title: c.title, year: c.year } : {}) };
    const doc = toDoc(nodes.map((v) => JSON.parse(texts.get(nodeText[v]))), links.map((e) => JSON.parse(texts.get(linkText[e]))), { window: where });
    return { doc, centre, ...where };
  }
  // where a year's sources begin in the order by year
  const startOf = (y) => { const { order, upTo } = orderOf(null), k = order.findIndex((s) => (sources[s].year ?? 3000) >= y); return k > 0 ? upTo[k - 1] : 0; };

  // A search of every record and link, the terms in any case: each text block is read whole and searched for the
  // first term, each record it is found in checked for the others. A link's match is told as its own record's. The
  // records whose name has the terms come first.
  let owner = null;                                    // each text's record (>= 0) or link (-1 - its number)
  function search(query, k = 50) {
    const terms = query.toLowerCase().split(/\s+/).filter((w) => w.length > 1).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    if (!terms.length) return [];
    if (!owner) { owner = new Int32Array(texts.at.length / 5); nodeText.forEach((t, v) => { owner[t] = v; }); linkText.forEach((t, e) => { owner[t] = -1 - e; }); }
    const first = new RegExp(terms[0], "gi"), rest = terms.slice(1).map((w) => new RegExp(w, "i")), all = new RegExp(terms.join("|"), "i");
    const at = texts.at, count = at.length / 5, hits = [], seen = new Set();
    for (let lo = 0; lo < count && hits.length < 4 * k;) {
      let hi = lo + 1;                                     // a piece: texts of one block, about 4 MB
      while (hi < count && at[5 * hi] === at[5 * lo] && at[5 * hi + 1] - at[5 * lo + 1] < 4 << 20) hi++;
      const b0 = at[5 * lo + 1], c00 = at[5 * lo + 3], last = hi - 1;
      const piece = texts.dec.decode(texts.blocks[at[5 * lo]].subarray(b0, at[5 * last + 1] + at[5 * last + 2]));
      first.lastIndex = 0;
      for (let m = first.exec(piece); m && hits.length < 4 * k; m = first.exec(piece)) {
        let a = lo, z = last;                              // the text the match lies in
        while (a < z) { const mid = (a + z + 1) >> 1; if (at[5 * mid + 3] - c00 <= m.index) a = mid; else z = mid - 1; }
        const c0 = at[5 * a + 3] - c00, text = piece.slice(c0, c0 + at[5 * a + 4]);
        first.lastIndex = c0 + text.length;
        const o = owner[a], v = o >= 0 ? o : ends[2 * (-1 - o)];
        if (seen.has(v) || !rest.every((r) => r.test(text))) continue;
        seen.add(v);
        hits.push({ v, x: JSON.parse(text), o });
      }
      lo = hi;
    }
    const nameOf = (x) => String(x.props?.name || x.props?.title || x.props?.formula || "");
    const named = (h) => (h.o >= 0 && [new RegExp(terms[0], "i"), ...rest].every((r) => r.test(nameOf(h.x))) ? 0 : 1);
    return hits.sort((a, b) => named(a) - named(b)).slice(0, k).map(({ v, x, o }) => {
      const quotes = (x.props?._evidence || []).map((e) => e.quote).filter(Boolean);
      const words = [];                                  // the record's own words that match: a quote, else a value
      (function walk(o, depth) {
        if (words.length || depth > 4 || !o) return;
        if (typeof o === "string") { if (all.test(o) && !/^[A-Za-z]+:/.test(o)) words.push(o); return; }
        if (typeof o === "object") for (const [key, val] of Object.entries(o)) if (key !== "scale_id" && key !== "source_paper_ids") walk(val, depth + 1);
      })({ q: quotes, ...x.props }, 0);
      const s = pubs.has(v) ? number.get(v) : pubOf[v] >= 0 ? number.get(pubOf[v]) : null;
      return { record: ids[v], label: labels[v] === "Publication" ? "Source" : labels[v],
        name: o >= 0 ? nameOf(x) || ids[v] : ids[v],
        text: words[0] || (o >= 0 ? nameOf(x) || quotes[0] : `${x.type.replace(/_/g, " ").toLowerCase()} → ${x.target}`) || ids[v],
        source: s, sourceTitle: s == null ? "" : sources[s].title, year: s == null ? null : sources[s].year };
    });
  }

  return {
    records: n, sources, years, start: richest(() => true),
    view, around: (centre, width) => view(centre, 0, width), startOf, search,
    sourceOf: (id) => { const v = index.get(id); if (v === undefined) return null; const p = pubs.has(v) ? v : pubOf[v]; return p >= 0 ? number.get(p) : null; },
    mainOf: (year) => richest((s) => sources[s].year === year),
  };
}
