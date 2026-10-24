"""The static site (scale site build): the repository's graphs and their plans as data, and the scale package the
explorer runs in the browser, which works from its bundled data alone (no checkout), as a wheel does."""

import json
import subprocess
import sys
import zipfile

import pytest

from conftest import REPO
from scale import site
from scale.cli import main


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("site") / "_site"
    return out, site.build(REPO, out)


def test_the_site_lists_the_curated_graphs(built):
    out, res = built
    entries = json.loads((out / "data/graphs.json").read_text())["graphs"]
    ids = [e["id"] for e in entries]
    assert ids == res["graphs"] and len(set(ids)) == len(ids)
    # the curated graphs, built from their parts; a parts folder with no source yet is left out, examples are not offered
    assert ids == ["methanol-synthesis-pre1966"]
    for e in entries:
        doc = json.loads((out / e["path"]).read_text())
        assert (len(doc["nodes"]), len(doc["links"])) == (e["nodes"], e["links"]), e["id"]
    assert all(e["from"].startswith("graphs/") for e in entries)
    assert (out / "data/query-graph.md").read_text().lstrip().startswith("#")       # the skill, without its front matter
    for page in site.PAGES:
        assert (out / page).is_file(), page


def test_the_package_is_the_wheels_without_the_examples(built):
    out, res = built
    with zipfile.ZipFile(out / site.PACKAGE_ZIP) as z:
        names = set(z.namelist())
    assert {"scale/api.py", "scale/passages.py", "scale/_data/domain/graph/scale-catal.yaml",
            "scale/_data/core/graph/kernel.yaml", "scale/_data/skills/query-graph/SKILL.md"} <= names
    # what a wheel leaves out (layout.BUNDLE_IGNORE), and the real examples, which the page reads as data instead
    assert not any(n.startswith("scale/_data/examples/") or n.split("/")[-1].startswith("test_") or n.endswith(".pyc")
                   for n in names)
    assert res["package_bytes"] < 5_000_000


def test_the_package_runs_without_a_checkout(built, tmp_path):
    """Unpacked anywhere, it reads its schema from scale/_data and answers a plan, as the page does in Pyodide."""
    out, _ = built
    with zipfile.ZipFile(out / site.PACKAGE_ZIP) as z:
        z.extractall(tmp_path / "lib")
    work = tmp_path / "work"
    work.mkdir()
    graph = (out / "data/graphs/methanol-synthesis-pre1966.json").read_text()
    (work / "g.json").write_text(graph)
    sources = sum(n["label"] == "Source" for n in json.loads(graph)["nodes"])
    code = ("import json; from scale.api import ScaleToolkit; from scale import layout; "
            "k = ScaleToolkit(workspace='work'); "
            "r = k.call('query', {'path': 'g.json', 'plan': {'match': {'label': 'Source', 'as': 's'}, 'return': ['s.title']}}); "
            "print(json.dumps([r['status'], r['row_count'], str(layout.__file__)]))")
    proc = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, 'lib'); {code}"],
                          cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    status, rows, where = json.loads(proc.stdout)
    assert (status, rows) == ("answered", sources) and where.startswith(str(tmp_path / "lib"))


def test_the_cli_builds_the_site(tmp_path, capsys):
    assert main(["--repo", str(REPO), "site", "build", "--out", str(tmp_path / "s")]) == 0
    assert json.loads(capsys.readouterr().out)["graphs"]
    assert (tmp_path / "s/index.html").is_file() and (tmp_path / "s/.nojekyll").is_file()


def test_the_explorer_runs_scales_own_tools_and_the_readers_key_stays_in_the_browser():
    page = (REPO / "site/index.html").read_text()
    js = (REPO / "site/explorer.js").read_text()
    worker = (REPO / "site/worker.js").read_text()
    assert 'src="explorer.js"' in page and 'href="publication.html"' in page
    assert "py/scale-py.zip" in worker and "ScaleToolkit" in worker
    # every script comes from a pinned version
    assert "pyodide/v0.26.4/" in worker and "@anthropic-ai/sdk@0.133.0" in js and "d3/7.9.0/" in page
    assert "plotly.js-cartesian-dist-min@2.35.2/" in page
    # the key goes only to the API, from the reader's browser, and is never written into the page's data
    assert "dangerouslyAllowBrowser: true" in js and "sessionStorage" in js
    assert "query-graph.md" in js
