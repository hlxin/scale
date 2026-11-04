"""A graph extracted into a curated dataset keeps its structure in a kg-bundle (format 1.2.0, GALAXY's §3.3.3).

The synthesis graph's export kept 2.62M of 4.56M links: the format's quote rule left out every link without a sentence
of a paper to quote. Two kinds are now carried, marked as what they are:

- a link with no evidence of its own joining two records of one source organizes that source's record (a step is
  PART_OF its preparation): a structural edge, with its values (the step's order) and the one source;
- a claim the dataset recorded from a source with no sentence of it to quote (a catalyst's metals): its dataset row,
  still naming the source; a claim quoted from the source needs no row.

A bundle that uses either says format 1.2.0; one that does not stays 1.1.0. A link with no evidence between the
records of two sources is still left out, and counted.
"""

import json

from conftest import HEAD_VERSION, spec_at
from scale.kgbundle import FORMAT_VERSION, ROW_FORMAT_VERSION, export

NS = "vt:t"
DS = f"{NS}/dataset/d1"
ROW = {"kind": "dataset_row", "locator": "v1.jsonl row 7, spec", "source": DS}


def _src(slug: str, doi: str) -> dict:
    return {"id": f"{NS}/source/{slug}", "label": "Source",
            "props": {"name": f"Paper {slug}", "title": f"Paper {slug}", "kind": "article", "doi": doi,
                      "licence": "CC-BY-4.0"}}


def _quote(slug: str, text: str) -> dict:
    return {"kind": "text", "locator": "main text", "quote": text, "source": f"{NS}/source/{slug}"}


def _unlocated(slug: str) -> dict:
    return {"kind": "text", "locator": "not located; stated in the dataset's spec", "source": f"{NS}/source/{slug}"}


def _doc(with_structure: bool = True) -> dict:
    p = f"{NS}/p1"
    nodes = [
        _src("p1", "10.1/p1"), _src("p2", "10.1/p2"),
        {"id": DS, "label": "Dataset", "props": {"name": "Recipes extraction"}},
        {"id": f"{p}/prep/1", "label": "Preparation",
         "props": {"name": "Preparation 1", "evidence": [_quote("p1", "Cu3Au nanorods were made by seeded growth.")]}},
        {"id": f"{p}/prep/1/step/1", "label": "ProcedureStep",
         "props": {"name": "Step 1: heat", "evidence": [_quote("p1", "The mixture was heated to 280 C.")]}},
        {"id": f"{p}/catalyst/1", "label": "Catalyst", "props": {"name": "Cu75Au25", "evidence": [ROW, _unlocated("p1")]}},
        {"id": f"{NS}/element/Cu", "label": "ChemicalSpecies", "props": {"name": "Cu", "formula": "Cu"}},
        {"id": f"{NS}/p2/prep/1", "label": "Preparation",
         "props": {"name": "Preparation 1", "evidence": [_quote("p2", "Pd cubes were made.")]}},
    ]
    links = [
        {"id": f"{p}/link/1", "type": "HAS_COMPONENT", "source": f"{p}/catalyst/1", "target": f"{NS}/element/Cu",
         "props": {"evidence": [ROW, _unlocated("p1")]}},
        # no evidence, and its ends belong to two sources' records: nothing says whose record it organizes
        {"id": f"{p}/link/3", "type": "VARIANT_OF", "source": f"{p}/prep/1", "target": f"{NS}/p2/prep/1", "props": {}},
    ]
    if with_structure:
        links.append({"id": f"{p}/link/2", "type": "PART_OF", "source": f"{p}/prep/1/step/1", "target": f"{p}/prep/1",
                      "props": {"order": 1, "origin": "reported"}})
    else:
        links = links[1:]      # only the cross-source link: neither structure nor a dataset row
        nodes[5]["props"]["evidence"] = [_quote("p1", "The catalyst was Cu75Au25.")]
    return {"directed": True, "graph": {"graph_id": f"{NS}/graph", "title": "Rows test", "schema_version": HEAD_VERSION},
            "nodes": nodes, "links": links}


def _export(tmp_path, doc):
    m = export(doc, spec_at(HEAD_VERSION), tmp_path / "b", "rows-test", "0.1.0", created="2026-11-04")
    graph = json.loads((tmp_path / "b" / "kg" / "graph.json").read_text())
    return m, graph


def test_a_records_structure_and_its_dataset_rows_are_exported(tmp_path):
    m, graph = _export(tmp_path, _doc())
    by_type = {}
    for e in graph["links"]:
        by_type.setdefault(e["type"], []).append(e)
    [part] = by_type["PART_OF"]
    assert part["props"]["_structural"] is True and part["props"]["source_paper_ids"] == ["10.1/p1"]
    assert "_evidence" not in part["props"] and part["props"]["order"] == 1     # the step's order is kept
    [comp] = by_type["HAS_COMPONENT"]
    assert comp["props"]["_evidence"] == [{"source_id": "10.1/p1",
                                           "dataset_row": {"dataset": "Recipes extraction", "row": "v1.jsonl row 7, spec"}}]
    assert m["format_version"] == ROW_FORMAT_VERSION
    assert m["counts"]["substantive_edges"] == 1                  # HAS_COMPONENT; PART_OF claims nothing
    report = m["export_report"]
    assert report["format_1_2"]["structural_edges"] == 1
    assert report["not_exported_links"] == {"VARIANT_OF": 1}     # two sources' records: left out, and said


def test_the_element_a_row_names_is_reported_in_its_source(tmp_path):
    _, graph = _export(tmp_path, _doc())
    cu = next(n for n in graph["nodes"] if n["label"] == "ChemicalSpecies")
    assert any(e["type"] == "REPORTED_IN" and e["source"] == cu["id"] for e in graph["links"])


def test_a_bundle_without_either_stays_1_1_0(tmp_path):
    m, graph = _export(tmp_path, _doc(with_structure=False))
    assert m["format_version"] == FORMAT_VERSION == "1.1.0"
    assert "format_1_2" not in m["export_report"]
