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
        # the code and schemas stay small; the releases it bundles grow with every release, so they are not counted
        code = sum(i.compress_size for i in z.infolist() if not i.filename.startswith("scale/_data/releases/"))
    assert {"scale/api.py", "scale/passages.py", "scale/_data/domain/graph/scale-catal.yaml",
            "scale/_data/core/graph/kernel.yaml", "scale/_data/skills/query-graph/SKILL.md"} <= names
    # what a wheel leaves out (layout.BUNDLE_IGNORE), and the real examples, which the page reads as data instead
    assert not any(n.startswith("scale/_data/examples/") or n.split("/")[-1].startswith("test_") or n.endswith(".pyc")
                   for n in names)
    assert code < 5_000_000 and res["package_bytes"] > code


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


def test_the_explorer_runs_scales_own_tools_and_asks_no_reader_for_a_key():
    page = (REPO / "site/index.html").read_text()
    js = (REPO / "site/explorer.js").read_text()
    worker = (REPO / "site/worker.js").read_text()
    assert 'src="explorer.js"' in page and 'src="config.js"' in page
    assert "py/scale-py.zip" in worker and "ScaleToolkit" in worker
    # every script comes from a pinned version
    assert "pyodide/v0.26.4/" in worker and "d3/7.9.0/" in page
    # a question goes to the service, which holds the model's key; no reader is asked for one
    assert '"/ask"' in js and "apiKey" not in js and "@anthropic-ai/sdk" not in js
    # the graph's type in its card is a link back to the graph on the canvas, as its schema is a link to the schema
    # "Upload, curate, and explore" opens Curate, a toolbar button like the account's; the Visualization is gone
    assert 'id="curate-open"' in page and "Upload, curate, and explore" in page and "viz-btn" not in page and "plotly" not in page.lower() and "Plotly" not in js
    # the Curate dialog is about a source (a paper, patent or report) and says what happens in four short points
    assert "<h2>Curate a source</h2>" in page and "Curate a publication" not in page and "<summary>More details</summary>" in page
    # the one-source page says "source" too
    one = (REPO / "site/publication.html").read_text()
    assert "<title>SCALE One Source</title>" in one and "publication" not in one.replace("publication.html", "").lower()
    # GitHub sign-in sits in the toolbar for every reader; viewing never needs it
    assert 'id="account-btn"' in page and "function renderAccount()" in js and "/auth/login?return=" in js
    assert "need no account" in js
    # a sign-in is one transaction of the tab that starts it: one place builds the sign-in address, carrying the page's
    # own address (its open graph, #g=…, included) and a nonce; a token is taken only with that tab's nonce
    for page_js in (js, (REPO / "site/app.js").read_text()):
        assert page_js.count("/auth/login?return=") == 1 and "&nonce=${n}" in page_js and "crypto.getRandomValues" in page_js
        # the reader's own graph and a job under way are kept in the tab, so a sign-in or a reload loses neither; the
        # service forgets a job's result only when the page says it has it
        assert '"scale-own"' in page_js and '"scale-job"' in page_js and "/done`" in page_js
        assert "tx.n !==" in page_js and "scale-signin-hash" not in page_js and "scale-signin-from" not in page_js
    assert "location.search + location.hash" in js and all(f'data-signin="{w}"' in js for w in ("toolbar", "curate", "search"))
    assert 'id="graph-show"' in js and "function showGraph()" in js and 'id="schema-toggle"' in js
    # the open graph's caret folds and unfolds its facts; the caret turns with the row's aria-expanded
    css = (REPO / "site/explorer.css").read_text()
    assert "folded = !folded" in js and 'aria-expanded="${open}"' in js and '[aria-expanded="true"] .gx-graph-caret' in css


def test_the_site_publishes_the_leaderboard_with_how_it_scores(built):
    out, res = built
    board = json.loads((out / "data/leaderboard.json").read_text())
    assert board["commons"] == "graphs/catal-commons" and board["with_reach"] is False
    assert set(board) >= {"contributors", "recent", "scoring", "levels"} and res["contributors"] == len(board["contributors"])
