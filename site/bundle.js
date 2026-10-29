// A knowledge-graph bundle (docs/kg-bundle-format.md), the zip `scale graph export --to kg-bundle` makes, read in the
// browser and turned into a graph the explorer draws. The bundle's graph is node-link JSON like a scale-catal document;
// only its property names differ: evidence is `_evidence` (quote, locator object, source_id), a source is a
// `Publication:<id>` node, and a value is a quantity in one canonical unit. Display only: nothing is validated here.
//
// A bundle's graph can be larger than a browser holds as one text (the train split of a dataset can pass 900 MB), so
// the zip is read from the file a slice at a time and the graph a record at a time as it is decompressed. A graph with
// more records than the explorer draws at once opens in parts, by source: each part holds the records some of the
// bundle's sources report, and the records they link to.

export const WHOLE_RECORDS = 60000, PART_RECORDS = 40000;   // a larger graph opens in parts of about this many records

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
// to `each(key, element)`, so the graph is never one text; its other top-level values are returned.
async function scanGraph(pieces, each, progress = () => {}) {
  const top = {};
  let depth = 0, inStr = false, esc = false, afterColon = false, key = null, arr = null, cap = null, read = 0;
  for await (const s of pieces) {
    let from = 0;                                   // where the value being captured starts in this piece
    for (let i = 0; i < s.length; i++) {
      const c = s.charCodeAt(i);
      if (inStr) {
        if (esc) esc = false;
        else if (c === 92) esc = true;              // \
        else if (c === 34) {                        // the string ends; a key at the top level is kept
          inStr = false;
          if (cap?.kind === "key") { cap.text.push(s.slice(from, i + 1)); key = JSON.parse(cap.text.join("")); cap = null; }
        }
        continue;
      }
      if (c === 34) {                               // "
        inStr = true;
        if (depth === 1 && !afterColon) { cap = { kind: "key", text: [] }; from = i; }
      } else if (c === 123 || c === 91) {           // { [
        if (depth === 1 && c === 91 && afterColon && (key === "nodes" || key === "links")) arr = key;
        else if (depth === 2 && arr && c === 123) { cap = { kind: "item", text: [] }; from = i; }
        depth++;
      } else if (c === 125 || c === 93) {           // } ]
        depth--;
        if (cap?.kind === "item" && depth === 2) { cap.text.push(s.slice(from, i + 1)); each(arr, JSON.parse(cap.text.join(""))); cap = null; }
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

// The bundle in a zip file, for the explorer: { title, version, doc } (doc: nodes and links, a scale-catal document's
// shape), or, for a graph of more than WHOLE_RECORDS records, { title, version, records, sources, parts, part(i) }:
// the parts by source (each one's sources, records and years) and a function that reads one part as a doc.
export async function readBundle(file, say = () => {}, { whole = WHOLE_RECORDS, size = PART_RECORDS } = {}) {
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

  // Read once: each record's id and label, each link's ends, each source's year; the records themselves while few.
  const index = new Map(), labels = [], ends = [], reported = [], years = new Map(), named = new Map();
  let kept = { nodes: [], links: [] };
  const at = (id) => { let i = index.get(id); if (i === undefined) { i = labels.length; index.set(id, i); labels.push(null); } return i; };
  const top = await scanGraph(await entry.chunks(), (key, x) => {
    if (key === "nodes") {
      const i = at(x.id);
      labels[i] = named.get(x.label) || (named.set(x.label, x.label), x.label);
      if (x.label === "Publication") years.set(i, Number.parseInt(x.props?.year, 10) || null);
    } else { ends.push(at(x.source), at(x.target)); reported.push(x.type === "REPORTED_IN"); }
    if (kept) { kept[key].push(x); if (labels.length > whole) kept = null; }
  }, (n) => say(`Reading the bundle… ${mb(n)} of ${mb(entry.size)}`));
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
  const split = partsOf(labels, ends, reported, years, size);
  return { title, version: manifest.version, records: labels.length, sources: years.size,
    parts: split.map(({ mask, ...p }) => p),
    part: async (i, say2 = say) => {               // read again, keeping one part's records and the links among them
      const { mask } = split[i], nodes = [], links = [];
      await scanGraph(await entry.chunks(), (key, x) => {
        if (key === "nodes") { if (mask[index.get(x.id)]) nodes.push(x); }
        else if (mask[index.get(x.source)] && mask[index.get(x.target)]) links.push(x);
      }, (n) => say2(`Reading part ${i + 1} of ${split.length}… ${mb(n)} of ${mb(entry.size)}`));
      return toDoc(nodes, links, { title: `${title} · part ${i + 1} of ${split.length}` });
    } };
}

// A graph's parts by source: the sources in order (by year when they give one) taken in turn until a part's records
// reach about `size` (a little less: a part also holds what its records link to). A part holds its sources, the records they report, and every record one link
// away from the records only its sources report (the species, instruments and materials a recipe uses), so no link of
// a part's own records is cut; a record many sources report (a common species) brings in only itself, not every record
// that uses it. Records no part reaches make a part of their own.
function partsOf(labels, ends, reported, years, size) {
  const n = labels.length, pubOf = new Int32Array(n).fill(-1), more = new Map();
  for (let e = 0; e < reported.length; e++) {
    const a = ends[2 * e], b = ends[2 * e + 1];
    if (!reported[e] || labels[b] !== "Publication") continue;
    if (pubOf[a] < 0) pubOf[a] = b; else (more.get(a) || more.set(a, []).get(a)).push(b);
  }
  const pubsOf = (v) => (pubOf[v] < 0 ? [] : [pubOf[v], ...(more.get(v) || [])]);
  const count = new Map();
  for (let v = 0; v < n; v++) for (const b of pubsOf(v)) count.set(b, (count.get(b) || 0) + 1);
  const pubs = [...years.keys()].sort((x, y) => (years.get(x) ?? 9999) - (years.get(y) ?? 9999) || x - y);
  const partOf = new Map(), groups = [[]];
  let sum = 0;
  for (const v of pubs) {
    const c = (count.get(v) || 0) + 1;
    if (sum && sum + c > size * 0.95) { groups.push([]); sum = 0; }
    groups.at(-1).push(v); partOf.set(v, groups.length - 1); sum += c;
  }
  const core = groups.map(() => new Uint8Array(n));
  for (const v of pubs) core[partOf.get(v)][v] = 1;
  for (let v = 0; v < n; v++) for (const b of pubsOf(v)) core[partOf.get(b)][v] = 1;
  const masks = core.map((c) => c.slice());
  const own = (v) => pubOf[v] >= 0 && !more.has(v);    // reported by one source: that source's part alone holds it
  for (let e = 0; e < reported.length; e++) {
    if (reported[e]) continue;
    const a = ends[2 * e], b = ends[2 * e + 1];
    if (own(a)) masks[partOf.get(pubOf[a])][b] = 1;
    if (own(b)) masks[partOf.get(pubOf[b])][a] = 1;
  }
  const loose = new Uint8Array(n);
  let nLoose = 0;
  for (let v = 0; v < n; v++) if (!masks.some((m) => m[v])) { loose[v] = 1; nLoose++; }
  if (nLoose) { masks.push(loose); groups.push([]); }
  return masks.map((mask, p) => {
    const ys = groups[p].map((v) => years.get(v)).filter(Boolean);
    return { mask, sources: groups[p].length, records: mask.reduce((s, x) => s + x, 0),
      years: ys.length ? [Math.min(...ys), Math.max(...ys)] : null };
  });
}
