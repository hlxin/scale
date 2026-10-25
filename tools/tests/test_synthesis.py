"""Syntheses of heterogeneous catalysts by any method (scale-catal 0.7.6): a preparation's method families, design aims
and strategy; the function each input serves (synthesis_function on HAS_INPUT); what drives a step (energy_input) and
a step repeated as one block (repetitions); stages that are preparations of their own; the structure obtained as a
catalyst state (particle_shape, architecture, exposed_facets); and the checklist items for them."""

import copy

import pytest

from conftest import EXAMPLES, spec_of
from scale import pgraph
from scale.pgraph_profiles import conformance
from scale.pgraph_query import run as run_plan
from scale.util import load_doc

SYNTHESES = EXAMPLES / "scale-catal/synthesis-examples/synthesis-strategies.json"
P = "ex:syn"


@pytest.fixture()
def doc():
    return copy.deepcopy(load_doc(SYNTHESES))


def node(d: dict, local: str) -> dict:
    return next(n for n in d["nodes"] if n["id"] == f"{P}/{local}")


def links(d: dict, typ: str, source: str | None = None, target: str | None = None) -> list[dict]:
    return [e for e in d["links"] if e["type"] == typ and (source is None or e["source"] == f"{P}/{source}")
            and (target is None or e["target"] == f"{P}/{target}")]


def catalysis(d: dict) -> dict:
    return conformance(d, spec_of(d), by_record=True)["profiles"]["catalysis"]


def evidence_missing(d: dict) -> dict:
    """{evidence item: [records it is missing for]} of the catalysis checklist."""
    out: dict = {}
    for rid, r in sorted(catalysis(d)["records"].items()):
        for name, found in (r.get("evidence") or {}).items():
            if not found["found"]:
                out.setdefault(name, []).append(rid)
    return out


def test_the_example_is_valid_with_no_warning_and_finds_every_piece_of_evidence(doc):
    rep = pgraph.validate(doc, spec_of(doc))
    assert rep.ok and rep.warnings == [], rep.warnings
    assert evidence_missing(doc) == {}
    assert {tuple(node(doc, f"preparation/{k}")["props"]["preparation_methods"]) for k in
            ("pd-cubes", "pt-ald", "fe-n-c", "pd-fsp")} == {
        ("colloidal_reduction", "colloidal_deposition"), ("atomic_layer_deposition",),
        ("solvothermal", "pyrolysis", "etching"), ("flame_spray_pyrolysis",)}


def test_one_input_serves_several_functions_and_the_kernel_role_stays(doc):
    pvp = links(doc, "HAS_INPUT", source="step/pd-cubes-1", target="species/pvp")[0]["props"]
    assert pvp["synthesis_function"] == ["capping_agent", "stabilizer"] and pvp["role"] == "reagent"
    linker = links(doc, "HAS_INPUT", source="step/zif-solutions", target="species/2-mim")[0]["props"]
    assert linker["synthesis_function"] == ["linker", "carbon_source", "nitrogen_source"]
    pvp["synthesis_function"] = ["capping"]
    rep = pgraph.validate(doc, spec_of(doc))
    assert not rep.ok and any("'capping' is not one of" in e["message"] for e in rep.errors)


def test_a_function_in_a_synthesis_is_only_an_inputs(doc):
    """synthesis_function is on HAS_INPUT, from a procedure or an experiment; a catalyst's component has a role in
    the catalyst instead."""
    comp = links(doc, "HAS_COMPONENT", source="catalyst/pd-cubes-alumina", target="material/gamma-alumina")[0]
    comp["props"]["synthesis_function"] = ["support"]
    rep = pgraph.validate(doc, spec_of(doc))
    assert any("'synthesis_function' is not declared for this type" in e["message"] for e in rep.errors)


def test_a_repeated_block_holds_its_sub_steps_in_order(doc):
    cycle = node(doc, "step/ald-cycle")["props"]
    assert cycle["repetitions"] == 10 and cycle["action"] == "deposit"
    subs = sorted(((e["props"]["order"], node(doc, e["source"].split("/", 1)[1])["props"]["action"])
                   for e in links(doc, "PART_OF", target="step/ald-cycle")))
    assert subs == [(1, "dose"), (2, "purge"), (3, "dose"), (4, "purge")]
    assert node(doc, "step/ald-purge-1")["props"]["duration"] == {"status": "not_reported",
                                                                  "missing_reason": "not_stated_in_source"}
    cycle["repetitions"] = "ten"
    assert not pgraph.validate(doc, spec_of(doc)).ok


def test_a_staged_synthesis_is_preparations_part_of_the_whole(doc):
    stages = sorted((e["props"]["order"], e["source"]) for e in links(doc, "PART_OF", target="preparation/cu-ssz13"))
    assert stages == [(1, f"{P}/preparation/ssz13"), (2, f"{P}/preparation/cu-exchange")]
    whole = catalysis(doc)["records"][f"{P}/preparation/cu-ssz13"]["evidence"]
    assert whole["steps"]["found"] and whole["precursors"]["found"]   # its stages count as its steps and precursors


def test_the_checklist_asks_a_preparation_for_its_methods_steps_and_precursors(doc):
    prep = node(doc, "preparation/pd-fsp")["props"]
    del prep["preparation_methods"]
    assert catalysis(doc)["missing_recommended"].get("Preparation.preparation_methods") == 1
    doc["links"] = [e for e in doc["links"] if not (e["type"] == "PART_OF" and e["target"] == f"{P}/preparation/pd-fsp")]
    assert set(evidence_missing(doc)) >= {"steps", "precursors"}


def test_a_colloid_and_an_ald_are_asked_what_controls_them(doc):
    """A colloidal synthesis is asked what controls the growth (a capping agent, stabilizer, surfactant or
    shape-directing agent of one of its steps); an atomic layer deposition its co-reactant."""
    for e in doc["links"]:
        f = (e["props"] or {}).get("synthesis_function")
        if f and e["source"].startswith(f"{P}/step/pd-cubes"):
            e["props"]["synthesis_function"] = [x for x in f if x not in (
                "capping_agent", "stabilizer", "surfactant", "shape_directing_agent")] or ["other"]
        if f == ["co_reactant"]:
            e["props"]["synthesis_function"] = ["other"]
    missing = evidence_missing(doc)
    assert missing.get("growth_control") == [f"{P}/preparation/pd-cubes"]
    assert missing.get("co_reactant") == [f"{P}/preparation/pt-ald"]


def test_an_aim_stated_is_not_a_structure_shown(doc):
    """A preparation with a structural design aim is asked for the structure it gave, as observed: a state it reaches
    that a characterization determines."""
    doc["links"] = [e for e in doc["links"] if not (e["type"] == "DETERMINED_BY"
                                                    and e["source"] == f"{P}/state/pt-ald")]
    assert evidence_missing(doc).get("structure_obtained") == [f"{P}/preparation/pt-ald"]


def test_a_heated_step_is_asked_its_temperature_time_gas_and_ramp(doc):
    s = node(doc, "step/ssz13-calcine")["props"]
    for k in ("temperature", "duration", "atmosphere", "ramp_rate"):
        del s[k]
    m = catalysis(doc)["missing_recommended"]
    assert all(m.get(f"ProcedureStep.{k}", 0) >= 1 for k in ("temperature", "duration", "atmosphere", "ramp_rate"))
    unheated = node(doc, "step/pd-cubes-3")["props"]                 # a centrifugation is asked none of them
    assert unheated["action"] == "centrifuge" and "temperature" not in unheated


def test_a_family_is_matched_exactly_by_its_entries():
    """preparation_methods.* with eq matches a family exactly; contains also matches a family whose name holds it."""
    d = load_doc(SYNTHESES)
    exact = run_plan(d, spec_of(d), {"match": {"label": "Preparation", "as": "p", "where": [
        {"prop": "preparation_methods.*", "op": "eq", "value": "pyrolysis"}]}, "return": ["p.name"]})
    loose = run_plan(d, spec_of(d), {"match": {"label": "Preparation", "as": "p", "where": [
        {"prop": "preparation_methods", "op": "contains", "value": "pyrolysis"}]}, "return": ["p.name"]})
    assert [r["values"]["p.name"] for r in exact["rows"]] == ["Fe-N-C by pyrolysis of Fe(acac)3@ZIF-8"]
    assert len(loose["rows"]) == 2


def test_the_structure_obtained_is_a_state_of_the_output(doc):
    st = node(doc, "state/pd-cubes")["props"]
    assert st["particle_shape"] == ["cube", "rod"] and st["exposed_facets"] == ["{100}"]
    assert st["architecture"] == ["nanoparticles"] and st["dimensionality"] == "zero_dimensional"
    assert links(doc, "REACHED_BY", source="state/pd-cubes")[0]["props"]["timing"] == "after"
    st["particle_shape"] = ["nanocube"]
    assert not pgraph.validate(doc, spec_of(doc)).ok
