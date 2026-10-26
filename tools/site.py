"""The static site (GitHub Pages): browse, search and query the repository's graphs in a browser, with no server.

``scale site build --out DIR`` writes the site into DIR:

* the pages of ``site/``: ``index.html`` (the graph explorer) and ``publication.html`` (one publication into a graph,
  which needs the web service, service/README.md);
* ``data/graphs.json``, the graphs the explorer offers, and ``data/graphs/<id>.json``: the curated graphs
  (``graphs/*``), each built from its parts as ``scale graph build`` does (the examples are not offered);
* ``data/query-graph.md``, the query-graph skill, which a question asked in the page follows;
* ``data/leaderboard.json``, the contributors of catal-commons scored and ranked from its ``contributors.yaml``
  (``commons.boards``: all time and the last 90 days, with how scoring works; the reach of each paper is the web
  service's to count, so the page asks the service for it when one is set up);
* ``py/scale-py.zip``, the ``scale`` package with the data a wheel bundles (``layout.BUNDLE``, without the repository's
  examples), which the page runs in Pyodide: a search, a plan or a description in the page is the same code as
  ``scale graph search``, ``scale graph query`` and ``scale graph describe``, and gives the same rows.

Nothing in DIR is committed; the pages workflow (.github/workflows/pages.yml) builds and publishes it.
"""

from __future__ import annotations

import fnmatch
import re
import shutil
import zipfile
from pathlib import Path

from . import commons, graphparts, layout
from .util import write_canonical

SITE = "site"
PAGES = ("index.html", "explorer.css", "explorer.js", "worker.js", "publication.html", "app.js", "config.js", "style.css")
PACKAGE_ZIP = "py/scale-py.zip"
#: The bundled items the page never reads (the real examples' parts, texts and PDFs are tens of MB; their graphs are
#: offered as data instead).
NOT_IN_PACKAGE = (layout.EXAMPLES,)


def _entry(doc: dict, gid: str, origin: str) -> dict:
    g = doc.get("graph") or {}
    return {"id": gid, "title": g.get("title") or gid, "description": g.get("description") or "",
            "schema_version": g.get("schema_version"), "data_status": g.get("data_status") or "curated",
            "nodes": len(doc.get("nodes") or []), "links": len(doc.get("links") or []), "from": origin,
            "path": f"data/graphs/{gid}.json"}


def graphs(repo: Path) -> list[tuple[str, str, dict]]:
    """(id, origin, document) for every graph the site offers: the curated graphs (``graphs/*``), each built from its
    parts. A folder of parts with no source yet is left out; the examples (``examples/``, the domain's synthetic ones)
    are not offered."""
    out = []
    for folder in sorted(p for p in (repo / layout.GRAPHS).glob("*") if (p / "parts" / "header.json").is_file()):
        if any((folder / "parts" / "sources").glob("*.json")):
            out.append((folder.name, f"{layout.GRAPHS}/{folder.name}", graphparts.build_folder(folder)))
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
    entries = []
    for gid, origin, doc in graphs(repo):
        write_canonical(out / "data" / "graphs" / f"{gid}.json", doc)
        entries.append(_entry(doc, gid, origin))
    write_canonical(out / "data" / "graphs.json", {"graphs": entries})
    (out / "data" / "query-graph.md").write_text(_skill_body(repo, "query-graph"), encoding="utf-8")
    boards = commons.boards(repo / layout.GRAPHS / "catal-commons")
    board = boards["contributors"]
    write_canonical(out / "data" / "leaderboard.json", {"commons": f"{layout.GRAPHS}/catal-commons", **boards})
    files = package_zip(repo, out / PACKAGE_ZIP)
    (out / ".nojekyll").write_text("")
    return {"out": str(out), "graphs": [e["id"] for e in entries], "contributors": len(board), "package_files": files,
            "package_bytes": (out / PACKAGE_ZIP).stat().st_size}


