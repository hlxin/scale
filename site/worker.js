// SCALE in the browser: Pyodide runs the scale package (py/scale-py.zip, built by `scale site build`), so a search, a
// query plan or a description here is the code of `scale graph search`, `scale graph query` and `scale describe`.
// Messages: {id, op: "put", name, text} stores a graph; {id, op: "call", tool, args} runs a tool on it.
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
importScripts(PYODIDE + "pyodide.js");

let call = null;
const ready = (async () => {
  postMessage({ status: "Loading Python (Pyodide)…" });
  const py = await loadPyodide({ indexURL: PYODIDE });
  postMessage({ status: "Loading SCALE…" });
  await py.loadPackage(["pyyaml", "numpy", "sqlite3", "jsonschema"]);
  const zip = await fetch("py/scale-py.zip");
  if (!zip.ok) throw new Error(`py/scale-py.zip: HTTP ${zip.status}`);
  py.unpackArchive(await zip.arrayBuffer(), "zip", { extractDir: "/lib/python3.12/site-packages" });
  py.FS.mkdirTree("/work");
  py.runPython(`
import json
from scale import pgraph
from scale.api import ScaleToolkit
from scale.util import load_doc

_kit = ScaleToolkit(workspace="/work")

def scale_call(tool, args_json):
    a = json.loads(args_json)
    if tool == "stats":                      # what the service's question loop gives as stats
        return json.dumps(pgraph.stats(load_doc("/work/" + a["path"])), default=str)
    return json.dumps(_kit.call(tool, a), default=str)
`);
  call = py.globals.get("scale_call");
  self.py = py;
  postMessage({ status: "ready" });
})();
ready.catch((err) => postMessage({ status: `SCALE could not start in this browser: ${(err && err.message) || err}` }));

onmessage = async (e) => {
  const { id, op } = e.data;
  try {
    await ready;
    if (op === "put") {
      self.py.FS.writeFile("/work/" + e.data.name, e.data.text);
      postMessage({ id, ok: true });
    } else if (op === "call") {
      postMessage({ id, ok: true, result: JSON.parse(call(e.data.tool, JSON.stringify(e.data.args || {}))) });
    } else {
      postMessage({ id, ok: false, error: `unknown op ${op}` });
    }
  } catch (err) {
    postMessage({ id, ok: false, error: String((err && err.message) || err).slice(-2000) });
  }
};
