"""The static site (GitHub Pages): browse, search and query the repository's graphs in a browser, with no server.

``scale site build --out DIR`` writes the site into DIR:

* the pages of ``site/``: ``index.html`` (the graph explorer) and ``publication.html`` (one publication into a graph,
  which needs the web service, service/README.md);
* ``data/graphs.json``, the graphs the explorer offers, and ``data/graphs/<id>.json``, each built from its parts
  (``graphs/*`` and ``examples/*``, as ``scale graph build``) or copied (the catalysis domain's synthetic examples);
* ``data/questions/<id>.json``, the query plans that run on each graph (its competency questions and saved queries);
* ``data/query-graph.md``, the query-graph skill, which a question asked in the page follows;
* ``py/scale-py.zip``, the ``scale`` package with the data a wheel bundles (``layout.BUNDLE``, without the repository's
  examples), which the page runs in Pyodide: a search, a plan or a description in the page is the same code as
  ``scale graph search``, ``scale graph query`` and ``scale graph describe``, and gives the same rows.

Nothing in DIR is committed; the pages workflow (.github/workflows/pages.yml) builds and publishes it.
"""

from __future__ import annotations

import fnmatch
import json
import re
import shutil
import zipfile
from pathlib import Path

from . import graphparts, layout
from .util import load_doc, load_yaml, write_canonical

SITE = "site"
PAGES = ("index.html", "publication.html", "explorer.js", "worker.js", "app.js", "config.js", "style.css")
PACKAGE_ZIP = "py/scale-py.zip"
#: The bundled items the page never reads (the real examples' parts, texts and PDFs are tens of MB; their graphs are
#: offered as data instead).
NOT_IN_PACKAGE = (layout.EXAMPLES,)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _entry(doc: dict, gid: str, origin: str) -> dict:
    g = doc.get("graph") or {}
    return {"id": gid, "title": g.get("title") or gid, "description": g.get("description") or "",
            "schema_version": g.get("schema_version"), "data_status": g.get("data_status") or "curated",
            "nodes": len(doc.get("nodes") or []), "links": len(doc.get("links") or []), "from": origin,
            "path": f"data/graphs/{gid}.json"}


def graphs(repo: Path) -> list[tuple[str, str, dict]]:
    """(id, origin, document) for every graph the site offers: the curated graphs first, then the real examples,
    then the catalysis domain's synthetic examples. A folder of parts with no source yet is left out."""
    out = []
    for base in (layout.GRAPHS, layout.EXAMPLES):
        for folder in sorted(p for p in (repo / base).glob("*") if (p / "parts" / "header.json").is_file()):
            if not any((folder / "parts" / "sources").glob("*.json")):
                continue
            out.append((folder.name, f"{base}/{folder.name}", graphparts.build_folder(folder)))
    decl = load_yaml(repo / layout.DOMAIN / "DOMAIN.yaml")
    patterns = (decl.get("example_documents") or {}).get("graph") or []
    seen: set[Path] = set()
    for pat in patterns:
        for path in sorted((repo / layout.DOMAIN).glob(pat)):
            if path in seen or path.name.startswith("_"):
                continue
            seen.add(path)
            rel = path.relative_to(repo / layout.DOMAIN).as_posix()
            out.append((_slug(rel.removeprefix("examples/scale-catal/").removesuffix(".json")),
                        f"{layout.DOMAIN}/{rel}", load_doc(path)))
    return out


def questions(repo: Path, origins: dict[str, str]) -> dict[str, list[dict]]:
    """Graph id -> the plans that run on it: the competency questions whose documents include it, and the saved
    queries beside a graph's parts (``queries/*.yaml``)."""
    by_doc = {v: k for k, v in origins.items()}
    out: dict[str, list[dict]] = {}
    for f in sorted((repo / layout.DOMAIN / "competency").glob("cq-*.yaml")):
        q = load_yaml(f)
        for d in q.get("documents") or []:
            gid = by_doc.get(f"{layout.DOMAIN}/{d}")
            if gid and q.get("plan"):
                out.setdefault(gid, []).append({"id": q.get("id"), "question": q.get("question"), "plan": q["plan"]})
    for gid, origin in origins.items():
        for f in sorted((repo / origin / "queries").glob("*.yaml")) if (repo / origin).is_dir() else []:
            plan = load_yaml(f)
            out.setdefault(gid, []).append({"id": f.stem, "question": plan.get("question") or f.stem, "plan": plan})
    return out


def package_zip(repo: Path, target: Path) -> int:
    """The ``scale`` package as a wheel lays it out (``scale/*.py`` and ``scale/_data/``), without tests and without
    NOT_IN_PACKAGE; returns the number of files."""
    ignore = layout.bundle_ignore(repo)
    n = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((repo / "tools").glob("*.py")):
            if not any(fnmatch.fnmatch(f.name, x) for x in layout.BUNDLE_IGNORE):
                z.write(f, f"scale/{f.name}")
                n += 1
        for item in layout.BUNDLE:
            if item in NOT_IN_PACKAGE:
                continue
            src = repo / item
            if src.is_file():
                z.write(src, f"scale/_data/{item}")
                n += 1
                continue
            for d, dirs, files in _walk(src, ignore):
                for name in files:
                    p = d / name
                    z.write(p, f"scale/_data/{p.relative_to(repo).as_posix()}")
                    n += 1
    return n


def _walk(top: Path, ignore):
    """os.walk with a copytree ignore callable applied to every folder."""
    stack = [top]
    while stack:
        d = stack.pop()
        names = sorted(p.name for p in d.iterdir())
        skip = ignore(str(d), names)
        dirs = [n for n in names if n not in skip and (d / n).is_dir()]
        files = [n for n in names if n not in skip and (d / n).is_file()]
        yield d, dirs, files
        stack.extend(d / n for n in reversed(dirs))


def _skill_body(repo: Path, name: str) -> str:
    text = (repo / layout.SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)


def build(repo: Path, out: Path) -> dict:
    """Write the site into ``out`` (emptied first); returns what was written."""
    repo, out = Path(repo), Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "data" / "graphs").mkdir(parents=True)
    for name in PAGES:
        shutil.copy2(repo / SITE / name, out / name)
    entries, origins = [], {}
    for gid, origin, doc in graphs(repo):
        write_canonical(out / "data" / "graphs" / f"{gid}.json", doc)
        entries.append(_entry(doc, gid, origin))
        origins[gid] = origin
    qs = questions(repo, origins)
    for e in entries:
        e["questions"] = len(qs.get(e["id"], []))
        if e["id"] in qs:
            write_canonical(out / "data" / "questions" / f"{e['id']}.json", qs[e["id"]])
    write_canonical(out / "data" / "graphs.json", {"graphs": entries})
    (out / "data" / "query-graph.md").write_text(_skill_body(repo, "query-graph"), encoding="utf-8")
    files = package_zip(repo, out / PACKAGE_ZIP)
    (out / ".nojekyll").write_text("")
    return {"out": str(out), "graphs": [e["id"] for e in entries],
            "questions": sum(len(v) for v in qs.values()), "package_files": files,
            "package_bytes": (out / PACKAGE_ZIP).stat().st_size}


