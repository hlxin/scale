"""The graphs SCALE curates and shares (graphs/, graphs/README.md): every graph is a folder kept as parts that builds
and validates, quotes no text of a source in copyright and commits no source text; a bundle merges them into one."""

import json

import pytest

from conftest import REPO, spec_of
from scale import graphparts as gp
from scale import layout, pgraph, rights
from scale.cli import main
from scale.util import ScaleError, load_doc, load_yaml

GRAPHS = REPO / layout.GRAPHS
FOLDERS = sorted(p.parent.parent for p in GRAPHS.glob("*/parts/header.json"))
METHANOL = GRAPHS / "methanol-synthesis-pre1966"


def test_the_graphs_are_the_commons_and_the_methanol_graph():
    assert [f.name for f in FOLDERS] == ["catalysis-commons", "methanol-synthesis-pre1966"]
    assert sorted(p.name for p in (GRAPHS / "bundles").glob("*.yaml")) == ["catalysis.yaml"]


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


def test_the_catalysis_bundle_merges_the_graphs_into_one_valid_graph(tmp_path, capsys):
    assert main(["graph", "bundle", "graphs/bundles/catalysis.yaml", "--check"]) == 0
    assert "the graphs merge (105 sources" in capsys.readouterr().out
    assert main(["graph", "bundle", "graphs/bundles/catalysis.yaml", "--out", str(tmp_path / "b")]) == 0
    doc = load_doc(tmp_path / "b")
    assert doc["graph"]["graph_id"] == "scale:commons/graph/catalysis-bundle" and doc["graph"]["schema_version"] == "0.2.0"
    assert pgraph.validate(doc, spec_of(doc)).ok
    rr = rights.report(doc, rights.load_rights(tmp_path / "b/rights.yaml"))
    assert rr["ok"] and rr["unlisted"] == []
    # each source's records keep the stewardship of the graph they came from
    zno_test = next(n for n in doc["nodes"] if n["id"].startswith("ex:msyn/10.1021-ie50225a025/"))
    assert pgraph.effective_stewardship(doc, zno_test)["project"] == "scale:project/methanol-synthesis-pre1966"


def _graph(ns: str, project: str, slug: str = "a", shared_note: str = "a species", quote: str = "q",
           catalyst: str = "a catalyst") -> dict:
    """One source (``<ns>/source/<slug>``) whose catalyst holds a shared species."""
    n = lambda i, label, **p: {"id": i, "label": label, "props": p}
    ev = [{"source": f"{ns}/source/{slug}", "quote": quote, "locator": "p. 1"}]
    doc = {"directed": True, "multigraph": True,
           "graph": {"graph_id": f"{ns}/graph", "schema": "scale-catal", "schema_version": "0.2.0",
                     "stewardship": {"access": "public", "project": project}},
           "nodes": [n(f"{ns}/source/{slug}", "Source"), n(f"{ns}/{slug}/catalyst/c", "Catalyst", note=catalyst),
                     n("ex:shared/species/zno", "ChemicalSpecies", note=shared_note, evidence=ev)],
           "links": [{"id": f"{ns}/{slug}/c/zno", "type": "HAS_COMPONENT", "source": f"{ns}/{slug}/catalyst/c",
                      "target": "ex:shared/species/zno", "props": {}}]}
    return gp.split(doc)


def test_merge_pools_shared_evidence_and_keeps_each_graphs_stewardship():
    one, two = _graph("ex:one", "ex:project/one"), _graph("ex:two", "ex:project/two", slug="b", quote="r")
    bundle = {"graph_id": "ex:b/graph", "title": "b", "stewardship": {"access": "public", "project": "ex:project/one"}}
    doc = gp.build(gp.merge([("one", one), ("two", two)], bundle))
    zno = next(n for n in doc["nodes"] if n["id"] == "ex:shared/species/zno")
    assert [e["source"] for e in zno["props"]["evidence"]] == ["ex:one/source/a", "ex:two/source/b"]
    st = {n["id"]: pgraph.effective_stewardship(doc, n).get("project") for n in doc["nodes"]}
    assert st["ex:one/a/catalyst/c"] == "ex:project/one" and st["ex:two/b/catalyst/c"] == "ex:project/two"
    assert "stewardship" not in next(n for n in doc["nodes"] if n["id"] == "ex:one/a/catalyst/c")["props"]
    assert doc["graph"]["schema_version"] == "0.2.0" and doc["graph"]["schema"] == "scale-catal"
    # the same graph twice merges into itself
    assert gp.build(gp.merge([("one", one), ("again", one)], bundle)) == gp.build(gp.merge([("one", one)], bundle))


def test_merge_refuses_what_two_graphs_state_differently():
    one = _graph("ex:one", "ex:project/one")
    bundle = {"graph_id": "ex:b/graph", "stewardship": {"access": "public"}}
    with pytest.raises(ScaleError, match="shared node ex:shared/species/zno: two states it differently"):
        gp.merge([("one", one), ("two", _graph("ex:two", "ex:project/two", "b", shared_note="another note"))], bundle)
    for other in (_graph("ex:one", "ex:project/one", catalyst="another catalyst"),     # the same source, changed
                  _graph("ex:two", "ex:project/one")):                                 # a source curated twice
        with pytest.raises(ScaleError, match="source a: one and other hold it differently"):
            gp.merge([("one", one), ("other", other)], bundle)
    later = json.loads(json.dumps(one))
    later["header"]["graph"]["schema_version"] = "0.3.0"
    with pytest.raises(ScaleError, match="different schema versions"):
        gp.merge([("one", one), ("later", later)], bundle)
    with pytest.raises(ScaleError, match="ex:s: a and b give it different rights"):
        gp.merge_rights([("a", {"ex:s": {"class": "open"}}), ("b", {"ex:s": {"class": "in_copyright"}})])


def test_a_bundle_definition_is_checked(tmp_path):
    f = tmp_path / "b.yaml"
    for text, why in (("graphs: [graphs/catalysis-commons]\n", "holds graph"),
                      ("graph: {graph_id: x, title: t, description: d}\ngraphs: [graphs/catalysis-commons]\n",
                       "graph.stewardship is required"),
                      ("graph: {graph_id: x, title: t, description: d, stewardship: {access: public}}\ngraphs: [docs]\n",
                       "not a graph kept as parts")):
        f.write_text(text)
        with pytest.raises(ScaleError, match=why):
            gp.load_bundle(f, REPO)
