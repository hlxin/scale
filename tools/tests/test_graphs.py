"""The graphs SCALE curates and shares (graphs/, graphs/README.md): every graph is a folder kept as parts that builds
and validates, quotes no text of a source in copyright and commits no source text."""

import pytest

from conftest import REPO, spec_of
from scale import graphparts as gp
from scale import layout, pgraph, rights
from scale.util import load_doc, load_yaml

GRAPHS = REPO / layout.GRAPHS
FOLDERS = sorted(p.parent.parent for p in GRAPHS.glob("*/parts/header.json"))
METHANOL = GRAPHS / "methanol-synthesis-pre1966"


def test_the_graphs_are_the_commons_and_the_methanol_graph():
    assert [f.name for f in FOLDERS] == ["catal-commons", "methanol-synthesis-pre1966"]


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda f: f.name)
def test_every_graph_builds_validates_and_respects_each_sources_rights(folder):
    for f in ("rights.yaml", "stewardship.yaml", "README.md"):
        assert (folder / f).is_file(), f
    assert not list(folder.rglob("*.pdf")) and not (folder / "texts").exists()       # no source text is committed
    raw = load_yaml(folder / "rights.yaml")
    assert raw["limits"] == {"quote_chars": 0, "source_chars": 0}                   # no text of a source in copyright
    doc = load_doc(folder)
    assert doc["graph"]["stewardship"]["access"] == "public" and doc["graph"]["data_status"] == "research_data"
    rep = pgraph.validate(doc, spec_of(doc))
    assert rep.ok, rep.errors[:5]
    rr = rights.report(doc, rights.load_rights(folder / "rights.yaml"))
    assert rr["ok"] and rr["unlisted"] == [], rr["violations"][:5]
    assert all(r["quoted_items"] == 0 for r in rr["sources"].values() if r["class"] in rights.CAPPED)


def test_the_methanol_graph_keeps_public_domain_quotes_and_withholds_the_rest():
    doc = load_doc(METHANOL)
    parts = gp.read_parts(METHANOL)
    assert (len(parts["sources"]), len(parts["shared"]["nodes"]), len(doc["nodes"]), len(doc["links"])) == \
           (105, 261, 4866, 16584)
    rep = rights.report(doc, rights.load_rights(METHANOL / "rights.yaml"))["sources"]
    by_class = {}
    for r in rep.values():
        row = by_class.setdefault(r["class"], [0, 0, 0])
        row[0] += 1; row[1] += r["quoted_items"]; row[2] += r["withheld_items"]
    assert by_class["public_domain"][0] == 55 and by_class["public_domain"][1] > 10000
    assert by_class["in_copyright"][0] == 50 and by_class["in_copyright"][1] == 0 and by_class["in_copyright"][2] > 10000
    corpus = load_doc(METHANOL / "sources.json")
    assert corpus["counts"]["in_scope"] == 105 and \
           {f"ex:msyn/source/{s['slug']}" for s in corpus["sources"] if s["status"] == "in_scope"} == \
           {p["source"] for p in parts["sources"].values()}
