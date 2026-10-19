"""The rename of the schema scale-graph to scale-catal (0.1.0 -> 0.2.0, a breaking change): documents pin the new name
at 0.2.0; 0.1.0 stays frozen as it was and documents that pin it validate against it; the migration step rewrites the
pin and nothing else; a head document that still says scale-graph is refused with a pointer to the migration."""

import copy

import pytest

from conftest import GRAPH_FROZEN, GRAPH_MANIFEST, HEAD_VERSION, REPO
from scale import pgraph, pgraph_migrate, schema_change
from scale.kg import update
from scale.util import load_doc, load_yaml, write_canonical

# an example written only in vocabulary 0.1.0 already had (the electrolyte example records its salts' concentrations,
# new in 0.3.0), so that a 0.1.0 copy of it validates and its migration rewrites the pin and nothing else
EXAMPLE = REPO / "domain/examples/scale-catal/driving-force-examples/plasma.json"


def _old(doc):
    """The example as a 0.1.0 document was written: the old name and version."""
    old = copy.deepcopy(doc)
    old["graph"].update(schema="scale-graph", schema_version="0.1.0")
    return old


@pytest.fixture(scope="module")
def head_doc():
    doc = load_doc(EXAMPLE)
    doc["graph"]["schema_version"] = HEAD_VERSION        # the example is at the version it was last migrated to
    return doc


def test_the_schema_and_its_kernel_carry_the_new_names_and_0_1_0_is_frozen_as_it_was():
    spec = pgraph.load_spec(GRAPH_MANIFEST)
    assert spec["schema"] == "scale-catal" and spec["kernel"]["name"] == "scale-kernel"
    frozen = pgraph.load_spec(GRAPH_FROZEN / "scale-catal-0.1.0.yaml")
    assert frozen["schema"] == "scale-graph" and frozen["kernel"]["name"] == "scale-graph-kernel"
    assert pgraph.spec_sha256(frozen) == "3c2fa7205a7bae5e0bbfa7d87826ff7ab7803e78536129064101c7d5a2c02006"
    assert pgraph.spec_sha256(frozen) != pgraph.spec_sha256(spec)


def test_a_document_pinning_scale_graph_0_1_0_validates_against_its_frozen_copy(head_doc):
    old = _old(head_doc)
    spec = pgraph.load_spec(pgraph.spec_for(REPO, "0.1.0", doc=old))
    assert spec["schema"] == "scale-graph" and spec["version"] == "0.1.0"
    rep = pgraph.validate(old, spec)
    assert rep.ok, rep.errors


def test_a_head_document_still_naming_scale_graph_is_refused_with_a_pointer_to_the_migration(head_doc):
    stale = copy.deepcopy(head_doc)
    stale["graph"]["schema"] = "scale-graph"
    rep = pgraph.validate(stale, pgraph.load_spec(GRAPH_MANIFEST))
    assert not rep.ok
    assert any("scale graph migrate" in e["message"] and "scale-graph" in e["message"] for e in rep.errors), rep.errors
    other = copy.deepcopy(head_doc)
    other["graph"]["schema"] = "something-else"                      # any other name is refused too, without the pointer
    rep = pgraph.validate(other, pgraph.load_spec(GRAPH_MANIFEST))
    assert any("'something-else'" in e["message"] for e in rep.errors)


def test_the_migration_step_rewrites_the_pin_and_nothing_else(head_doc):
    assert pgraph_migrate.STEPS["0.1.0"][0] == "0.2.0" and "0.1.0" in pgraph_migrate.STEP_RULES
    old = _old(head_doc)
    new, rep = pgraph_migrate.raise_version(old, HEAD_VERSION, pgraph.load_spec(GRAPH_MANIFEST))
    assert rep["steps"][0]["changes"] == ["graph.schema: scale-graph -> scale-catal"]
    assert new == head_doc and new["nodes"] == old["nodes"] and new["links"] == old["links"]
    assert pgraph.validate(new, pgraph.load_spec(GRAPH_MANIFEST)).ok
    again, rep = pgraph_migrate.raise_version(new, HEAD_VERSION)      # a current document has no step
    assert rep["steps"] == [] and again == new


def test_kg_update_moves_a_scale_graph_document_and_keeps_a_copy_pinned_by_its_name(tmp_path, head_doc):
    data = tmp_path / "data"
    data.mkdir()
    write_canonical(data / "a.graph.json", _old(head_doc))
    write_canonical(data / "a.scale-graph-0.1.0.graph.json", _old(head_doc))      # a deliberate copy at 0.1.0
    res = update(REPO, data)
    by = {r["document"].rsplit("/", 1)[-1]: r["status"] for r in res["documents"]}
    assert by == {"a.graph.json": "updated", "a.scale-graph-0.1.0.graph.json": "kept"}
    moved = load_doc(data / "a.graph.json")
    assert moved["graph"]["schema"] == "scale-catal" and moved["graph"]["schema_version"] == HEAD_VERSION
    assert load_doc(data / "a.scale-graph-0.1.0.graph.json")["graph"]["schema"] == "scale-graph"


def test_scale_schema_diff_reads_a_rename_as_breaking():
    a = pgraph.load_spec(GRAPH_FROZEN / "scale-catal-0.1.0.yaml")
    b = pgraph.load_spec(GRAPH_MANIFEST)
    d = schema_change.diff_specs(a, b)
    assert d["changed"] == ["schema name: scale-graph -> scale-catal", "kernel name: scale-graph-kernel -> scale-kernel"]
    assert schema_change.tier(d) == 3 and schema_change.next_version("0.1.0", 3) == "0.2.0"
    assert schema_change.diff_specs(b, copy.deepcopy(b))["changed"] == []


def test_the_bundle_schema_and_what_it_extends_share_a_name_and_are_told_apart_by_digest(tmp_path, head_doc):
    import json
    from scale import kgbundle
    kgbundle.export(head_doc, pgraph.load_spec(GRAPH_MANIFEST), tmp_path / "b", "rename-check", created="2026-10-06T00:00:00Z")
    schema = json.loads((tmp_path / "b/kg/schema.json").read_text())
    assert schema["schema_id"] == schema["extends"]["schema_id"] == "scale-catal"
    assert schema["extends"]["sha256"] == pgraph.spec_sha256(pgraph.load_spec(GRAPH_MANIFEST))
    assert "different things" in schema["scope"]
