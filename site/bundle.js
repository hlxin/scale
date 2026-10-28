// A knowledge-graph bundle (docs/kg-bundle-format.md), the zip `scale graph export --to kg-bundle` makes, read in the
// browser and turned into a graph the explorer draws. The bundle's graph is node-link JSON like a scale-catal document;
// only its property names differ: evidence is `_evidence` (quote, locator object, source_id), a source is a
// `Publication:<id>` node, and a value is a quantity in one canonical unit. Display only: nothing is validated here.

// The files of a zip, by name, each read on demand (stored or deflated entries; no zip64, no encryption).
async function unzip(buf) {
  const v = new DataView(buf), u8 = new Uint8Array(buf);
  let end = -1;
  for (let i = buf.byteLength - 22; i >= Math.max(0, buf.byteLength - 22 - 65535); i--) {
    if (v.getUint32(i, true) === 0x06054b50) { end = i; break; }
  }
  if (end < 0) throw new Error("not a zip file");
  const count = v.getUint16(end + 10, true);
  let p = v.getUint32(end + 16, true);
  if (p === 0xffffffff || count === 0xffff) throw new Error("a zip64 file: zip the bundle again with a standard zip");
  const utf8 = new TextDecoder();
  const files = new Map();
  for (let k = 0; k < count; k++) {
    if (v.getUint32(p, true) !== 0x02014b50) throw new Error("a damaged zip file");
    const flags = v.getUint16(p + 8, true), method = v.getUint16(p + 10, true), size = v.getUint32(p + 20, true);
    const nlen = v.getUint16(p + 28, true), xlen = v.getUint16(p + 30, true), clen = v.getUint16(p + 32, true);
    const local = v.getUint32(p + 42, true), name = utf8.decode(u8.subarray(p + 46, p + 46 + nlen));
    p += 46 + nlen + xlen + clen;
    if (name.endsWith("/")) continue;
    files.set(name, async () => {
      if (flags & 1) throw new Error(`${name}: encrypted`);
      const start = local + 30 + v.getUint16(local + 26, true) + v.getUint16(local + 28, true);
      const raw = u8.subarray(start, start + size);
      if (method === 0) return utf8.decode(raw);
      if (method !== 8) throw new Error(`${name}: compressed in a way this page cannot read (method ${method})`);
      return new Response(new Blob([raw]).stream().pipeThrough(new DecompressionStream("deflate-raw"))).text();
    });
  }
  return files;
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

// The bundle in a zip file, as { title, doc } for the explorer (doc: nodes and links, a scale-catal document's shape).
export async function readBundle(file) {
  const files = await unzip(await file.arrayBuffer());
  const names = [...files.keys()].filter((n) => !n.startsWith("__MACOSX/"));
  const manifestName = names.filter((n) => /^([^/]+\/)?bundle\.json$/.test(n)).sort((a, b) => a.length - b.length)[0];
  if (!manifestName) throw new Error("no bundle.json: this zip is not a knowledge-graph bundle");
  const dir = manifestName.slice(0, -"bundle.json".length);
  const manifest = JSON.parse(await files.get(manifestName)());
  const graphName = dir + (manifest.graph_file || "kg/graph.json");
  if (!files.has(graphName)) throw new Error(`the bundle has no ${graphName}`);
  const g = JSON.parse(await files.get(graphName)());
  if (!Array.isArray(g.nodes) || !Array.isArray(g.links)) throw new Error(`${graphName} has no nodes and links`);
  const ids = new Set(g.nodes.map((n) => n.id));
  const sourceOf = (sid) => (ids.has(`Publication:${sid}`) ? `Publication:${sid}` : sid);
  const doc = {
    directed: true, multigraph: true,
    graph: { ...(g.graph || {}), title: manifest.topic || g.graph?.topic || manifest.bundle_id || file.name,
      bundle: { id: manifest.bundle_id, version: manifest.version, format: manifest.format, format_version: manifest.format_version } },
    // a Publication is the bundle's name for a source: shown, and hidden until asked for, like a graph's sources
    nodes: g.nodes.map((n) => ({ id: n.id, label: n.label === "Publication" ? "Source" : n.label, props: props(n.props, sourceOf) })),
    links: g.links.map((e) => ({ id: e.id, source: e.source, target: e.target, type: e.type, props: props(e.props, sourceOf) })),
  };
  return { title: doc.graph.title, version: manifest.version, doc };
}
