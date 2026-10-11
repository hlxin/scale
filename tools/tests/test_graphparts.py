"""A graph kept as one part per source (scale.graphparts; docs/graph-parts.md): split and build give back the same
document, the parts refuse a record in the wrong place, and a subset keeps what its sources reach."""

import copy
import json

import pytest

from conftest import REPO
from scale import graphparts as gp
from scale.cli import main
from scale.util import ScaleError, dump_canonical, load_doc

METHANOL = REPO / "examples/methanol-synthesis-pre1966/methanol-synthesis.graph.json"


def tiny() -> dict:
    """Two sources sharing one species, a person who wrote one of them, and the graph's organisation."""
    n = lambda i, label, **p: {"id": i, "label": label, "props": p}
    lk = lambda i, t, s, d, **p: {"id": i, "type": t, "source": s, "target": d, "props": p}
    ev = lambda src: [{"source": src, "quote": "q", "locator": "p. 1"}]
    return {"directed": True, "multigraph": True,
            "graph": {"graph_id": "ex:t/graph", "schema_version": "0.2.0", "stewardship": {"contributed_by": ["ex:t/org/o"]}},
            "nodes": [n("ex:t/source/a", "Source"), n("ex:t/source/b", "Source"),
                      n("ex:t/a/catalyst/c1", "Catalyst"), n("ex:t/b/catalyst/c2", "Catalyst"),
                      n("ex:t/species/zno", "ChemicalSpecies", evidence=ev("ex:t/source/a") + ev("ex:t/source/b")),
                      n("ex:t/person/p", "Person"), n("ex:t/org/o", "Organization"), n("ex:t/species/cu", "ChemicalSpecies")],
            "links": [lk("ex:t/a/c1/zno", "HAS_COMPONENT", "ex:t/a/catalyst/c1", "ex:t/species/zno"),
                      lk("ex:t/b/c2/zno", "HAS_COMPONENT", "ex:t/b/catalyst/c2", "ex:t/species/zno"),
                      lk("ex:t/source/b/authored-by/1", "AUTHORED_BY", "ex:t/source/b", "ex:t/person/p"),
                      lk("ex:t/species/zno/near/cu", "RELATED_TO", "ex:t/species/zno", "ex:t/species/cu")]}


def test_a_graph_splits_into_one_part_per_source_and_builds_back():
    doc = tiny()
    parts = gp.split(doc)
    assert sorted(parts["sources"]) == ["a", "b"]
    assert [n["id"] for n in parts["sources"]["a"]["nodes"]] == ["ex:t/source/a", "ex:t/a/catalyst/c1"]
    assert [lk["id"] for lk in parts["sources"]["b"]["links"]] == ["ex:t/b/c2/zno", "ex:t/source/b/authored-by/1"]
    assert {n["id"] for n in parts["shared"]["nodes"]} == {"ex:t/species/zno", "ex:t/person/p", "ex:t/org/o", "ex:t/species/cu"}
    assert [lk["id"] for lk in parts["shared"]["links"]] == ["ex:t/species/zno/near/cu"]
    built = gp.build(parts)
    assert dump_canonical(built) == dump_canonical({**doc, "nodes": sorted(doc["nodes"], key=lambda n: n["id"]),
                                                    "links": sorted(doc["links"], key=lambda lk: lk["id"])})


def test_the_methanol_graph_builds_back_exactly_from_its_parts(tmp_path):
    parts = gp.split(load_doc(METHANOL))
    assert len(parts["sources"]) == 105 and len(parts["shared"]["nodes"]) == 261
    gp.write_parts(parts, tmp_path)
    assert gp.same(load_doc(tmp_path), METHANOL)                 # load_doc builds a folder kept as parts
    assert main(["graph", "build", str(tmp_path), "--check"]) == 0


def test_the_parts_refuse_a_record_in_the_wrong_place():
    parts = gp.split(tiny())
    bad = copy.deepcopy(parts)
    bad["sources"]["a"]["nodes"].append(bad["sources"]["b"]["nodes"].pop())          # b's catalyst in a's part
    assert any("node ex:t/b/catalyst/c2 belongs in sources/b.json" in p for p in gp.problems(bad))
    bad = copy.deepcopy(parts)
    bad["shared"]["nodes"].append({"id": "ex:t/a/catalyst/c1", "label": "Catalyst"})  # one id in two parts
    assert any("is also in" in p for p in gp.problems(bad))
    bad = copy.deepcopy(parts)
    bad["sources"]["a"]["schema_version"] = "0.1.0"
    assert any("sources/a.json: schema_version '0.1.0'" in p for p in gp.problems(bad))
    bad = copy.deepcopy(parts)
    bad["shared"]["nodes"] = [n for n in bad["shared"]["nodes"] if n["id"] != "ex:t/species/cu"]
    with pytest.raises(ScaleError, match="refers to ex:t/species/cu, which no part holds"):
        gp.build(bad)
    doc = tiny()
    doc["links"].append({"id": "ex:t/a/c1/same-as", "type": "SAME_AS", "source": "ex:t/a/catalyst/c1",
                         "target": "ex:t/b/catalyst/c2", "props": {}})
    with pytest.raises(ScaleError, match="joins the records of two sources"):
        gp.split(doc)


def test_a_subset_keeps_what_its_sources_reach_and_only_their_evidence():
    sub = gp.subset(gp.split(tiny()), ["a"], header={"graph_id": "ex:t/graph/a"})
    assert list(sub["sources"]) == ["a"] and sub["header"]["graph"]["graph_id"] == "ex:t/graph/a"
    shared = {n["id"]: n for n in sub["shared"]["nodes"]}
    # zno (a's catalyst), cu (through zno), the organisation the header names; not b's author
    assert set(shared) == {"ex:t/species/zno", "ex:t/species/cu", "ex:t/org/o"}
    assert [e["source"] for e in shared["ex:t/species/zno"]["props"]["evidence"]] == ["ex:t/source/a"]
    assert gp.build(sub)["graph"]["graph_id"] == "ex:t/graph/a"
    with pytest.raises(ScaleError, match="no such sources: z"):
        gp.subset(gp.split(tiny()), ["z"])


def test_build_writes_the_graph_and_check_finds_a_stale_copy(tmp_path, capsys):
    gp.write_parts(gp.split(tiny()), tmp_path)
    assert main(["graph", "build", str(tmp_path), "--check"]) == 0                  # no built copy: the parts build
    assert main(["graph", "build", str(tmp_path)]) == 0
    built = tmp_path / f"{tmp_path.name}.graph.json"
    assert json.loads(built.read_text())["graph"]["graph_id"] == "ex:t/graph"
    assert main(["graph", "build", str(tmp_path), "--check"]) == 0
    built.write_text("{}\n")
    assert main(["graph", "build", str(tmp_path), "--check"]) == 1
    assert "is not what its parts build" in capsys.readouterr().err
