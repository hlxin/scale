"""Tests driven by a program, the analyses of their responses, and kinetic constants fitted to them (scale-catal 0.7.3):
what a program states, the advisories on a dynamic operation and on a fitted value's interval and identifiability, and
the comparison that keeps constants fitted under two reactor treatments apart."""

import copy

import pytest

from conftest import EXAMPLES, spec_of
from scale import pgraph, pgraph_query
from scale.pgraph_profiles import conformance
from scale.util import load_doc

TRANSIENT = EXAMPLES / "scale-catal/transient-examples/transient-kinetics.json"
P = "ex:tk"


@pytest.fixture()
def doc():
    return copy.deepcopy(load_doc(TRANSIENT))


def node(d: dict, local: str) -> dict:
    return next(n for n in d["nodes"] if n["id"] == f"{P}/{local}")


def entry(d: dict, local: str, key: str) -> dict:
    return next(v for v in node(d, local)["props"]["result_values"] if v["id"] == key)


def warnings(d: dict) -> list[str]:
    return [w["message"] for w in pgraph.validate(d, spec_of(d)).warnings]


FITTED = {"match": {"label": "Analysis", "as": "fit",
                    "where": [{"prop": "analysis_kind", "op": "eq", "value": "kinetic_fit"}]},
          "steps": [{"from": "fit", "entries": "result_values", "kind": "activation_energy", "as": "ea"},
                    {"from": "ea", "field": "target", "to": "ElementaryStep", "as": "step"}],
          "return": ["fit.reactor_model", "step.name", "ea"], "order_by": [{"var": "ea", "prop": "value"}],
          "comparison": "scientific"}


def test_the_example_is_valid_with_no_warning(doc):
    rep = pgraph.validate(doc, spec_of(doc))
    assert rep.ok and rep.warnings == [], rep.warnings
    seq = node(doc, "operation/co2-sequence")["props"]
    assert seq["waveform"] == "pseudo_random_binary" and seq["sequence_length"] == 63 and seq["program_detail"] == "exact"
    assert [x["value"] for x in seq["levels"]] == [4, 8]


def test_a_dynamic_operation_says_how_it_varies(doc):
    seq = node(doc, "operation/co2-sequence")["props"]
    del seq["bit_duration"]
    assert any("a dynamic operation says how it varies" in w for w in warnings(doc))
    d = load_doc(TRANSIENT)
    del node(d, "operation/isotope-switch")["props"]["levels"]             # a step without its levels says nothing
    assert any("a step's levels" in w for w in warnings(d))


def test_the_checklist_asks_a_pseudo_random_program_for_its_sequence(doc):
    del node(doc, "operation/co2-sequence")["props"]["sequence_length"]
    missing = conformance(doc, spec_of(doc))["profiles"]["catalysis"]["missing_recommended"]
    assert missing.get("Operation.sequence_length") == 1


def test_an_interval_method_goes_with_an_interval_and_identifiability_with_a_fit(doc):
    v = entry(doc, "analysis/fit-differential", "ea_co2_dissociation")
    v.pop("uncertainty"), v.pop("uncertainty_kind")
    assert any("interval_method says how an uncertainty or an interval was obtained" in w for w in warnings(doc))
    d = load_doc(TRANSIENT)
    tau = entry(d, "analysis/ssitka-co2", "tau_co2")
    tau["identifiability"] = "identifiable"                                   # a measured residence time is not fitted
    assert any("identifiability is said of a fitted value" in w for w in warnings(d))


def test_a_comparison_shows_each_fitted_constants_reactor_treatment(doc):
    res = pgraph_query.run(doc, spec_of(doc), FITTED)
    groups = {g["compared_on"]["ea.value"]["context"]["process"]: g["rows"] for g in res["comparison"]["groups"]}
    assert groups == {f"{P}/step/co2-dissociation": 2, f"{P}/step/co-hydrogenation": 1}
    shown = {r["values"]["ea"]["value"]: r["compared"]["ea.value"]["shows"]["reactor_model"] for r in res["rows"]}
    assert shown == {92: "plug_flow", 78: "differential", 68: "plug_flow"}
    assert any("reactor_model: differential, plug_flow" in x for x in res["limitations"])
    # one treatment for both fits: nothing to name
    node(doc, "analysis/fit-differential")["props"]["reactor_model"] = "plug_flow"
    res = pgraph_query.run(doc, spec_of(doc), FITTED)
    assert not [x for x in res["limitations"] if "reactor_model" in x]


def test_a_query_keeps_only_the_constants_the_data_determine(doc):
    plan = {**FITTED, "where": [{"var": "ea", "prop": "identifiability", "op": "eq", "value": "identifiable"}]}
    res = pgraph_query.run(doc, spec_of(doc), plan)
    assert {r["values"]["step.name"] for r in res["rows"]} == {"CO2* + * -> CO* + O*"} and res["row_count"] == 2


def test_residence_times_and_delays_are_compared_by_their_species(doc):
    plan = {"match": {"label": "Analysis", "as": "a", "where": [{"prop": "analysis_kind", "op": "eq",
                                                                  "value": "modulation_excitation"}]},
            "steps": [{"from": "a", "entries": "result_values", "kind": "phase_delay", "as": "delay"}],
            "return": ["delay"], "order_by": [{"var": "delay", "prop": "value"}], "comparison": "scientific"}
    res = pgraph_query.run(doc, spec_of(doc), plan)
    species = {g["compared_on"]["delay.value"]["context"]["species"] for g in res["comparison"]["groups"]}
    assert species == {f"{P}/species/co-linear-pt", f"{P}/species/co2", f"{P}/species/carbonate-ceria"}


def test_phase_delays_are_compared_only_at_one_reference_period_and_harmonic(doc):
    """A lag behind the stimulus and a lag behind another species' response, or lags read at two modulation periods,
    are never one group; a delay whose analysis states no reference, or names no species for a response it is measured
    against, is left out, with the reason."""
    mes = node(doc, "analysis/phase-sensitive-detection")

    def clone(key: str, **props) -> dict:
        n = copy.deepcopy(mes)
        n["id"] = f"{P}/analysis/{key}"
        n["props"].update(props)
        doc["nodes"].append(n)
        return n
    clone("psd-30s", modulation_period={"status": "present", "value": 30, "unit": "s"})
    behind_co2 = clone("psd-behind-co2", phase_reference="species_response", phase_reference_species=f"{P}/species/co2")
    behind_co2["props"]["result_values"] = [dict(entry(doc, "analysis/phase-sensitive-detection", "delay_carbonate"),
                                                 value=12.1, definition="lag of the 1550 cm-1 band behind gas-phase CO2")]
    unstated = clone("psd-unstated")
    del unstated["props"]["phase_reference"]
    nameless = clone("psd-behind-nothing-named", phase_reference="species_response")      # names no species
    plan = {"match": {"label": "Analysis", "as": "a", "where": [{"prop": "analysis_kind", "op": "eq",
                                                                  "value": "modulation_excitation"}]},
            "steps": [{"from": "a", "entries": "result_values", "kind": "phase_delay", "as": "delay"}],
            "return": ["a.name", "delay"], "order_by": [{"var": "delay", "prop": "value"}], "comparison": "scientific"}
    res = pgraph_query.run(doc, spec_of(doc), plan)
    keys = ("phase_reference", "phase_reference_species", "modulation_period", "demodulation_harmonic")
    carbonate = sorted(tuple(g["compared_on"]["delay.value"]["context"].get(k) for k in keys)
                       for g in res["comparison"]["groups"]
                       if g["compared_on"]["delay.value"]["context"]["species"] == f"{P}/species/carbonate-ceria")
    assert carbonate == [("species_response", f"{P}/species/co2", "60 s", "1"),
                         ("stimulus", None, "30 s", "1"), ("stimulus", None, "60 s", "1")]
    assert sum(g["rows"] for g in res["comparison"]["groups"]) == 7       # 3 + 3 at 30 s + 1 behind CO2; not the 3 unstated
    left_out = {x["record"]: x["reason"] for x in res["excluded"]}
    assert "states no phase_reference" in left_out[unstated["id"]]
    assert "phase_reference_species" in left_out[nameless["id"]]


def test_cq32_answers_with_the_timing_that_rebuilds_each_program(doc):
    """CQ-32 asks whether a program can be rebuilt: its answer keeps the timing of each, the square wave's period and
    duty cycle, the sequence's bits and the loop's labelled segments with their durations."""
    from conftest import REPO
    from scale.util import load_yaml
    cq = load_yaml(REPO / "domain/competency/cq-32-driving-programs.yaml")
    rows = {r["values"]["test.name"]: r["values"] for r in pgraph_query.run(doc, spec_of(doc), cq["plan"])["rows"]}
    square = next(v for v in rows.values() if v["program.waveform"] == "square")
    assert square["program.period"]["value"] == 60 and square["program.duty_cycle"]["value"] == 50
    loop = next(v for v in rows.values() if v.get("program.segments"))
    assert [(s["label"]["text_value"], s["duration"]["value"]) for s in loop["program.segments"]] == [
        ("reduction (5 % CH4 in Ar)", 60), ("purge (Ar)", 30), ("reoxidation (air)", 45), ("purge (Ar)", 30)]


def test_a_phase_delay_is_compared_by_its_exact_period_and_harmonic_and_never_without_an_analysis(doc):
    """Two harmonics, or two periods that differ past six digits, are two groups; a harmonic not stated is compared only
    with others not stated; a period not measured, or a delay recorded on the test with no analysis that says what it
    was measured against, is left out."""
    mes = node(doc, "analysis/phase-sensitive-detection")

    def clone(key: str, **props) -> dict:
        n = copy.deepcopy(mes)
        n["id"] = f"{P}/analysis/{key}"
        n["props"].update(props)
        n["props"]["result_values"] = [entry(doc, "analysis/phase-sensitive-detection", "delay_carbonate")]
        doc["nodes"].append(n)
        return n
    clone("psd-second-harmonic", demodulation_harmonic=2)
    no_k = clone("psd-no-harmonic")
    del no_k["props"]["demodulation_harmonic"]
    clone("psd-period-a", modulation_period={"status": "present", "value": 60.00001, "unit": "s"})
    clone("psd-period-b", modulation_period={"status": "present", "value": 60.00002, "unit": "s"})
    unmeasured = clone("psd-period-unmeasured", modulation_period={"status": "not_measured"})
    plan = {"match": {"label": "Analysis", "as": "a", "where": [{"prop": "analysis_kind", "op": "eq",
                                                                  "value": "modulation_excitation"}]},
            "steps": [{"from": "a", "entries": "result_values", "kind": "phase_delay", "as": "delay"}],
            "return": ["a.name", "delay"], "order_by": [{"var": "delay", "prop": "value"}], "comparison": "scientific"}
    res = pgraph_query.run(doc, spec_of(doc), plan)
    carbonate = sorted((c.get("modulation_period"), c.get("demodulation_harmonic"))
                       for c in (g["compared_on"]["delay.value"]["context"] for g in res["comparison"]["groups"])
                       if c["species"] == f"{P}/species/carbonate-ceria")
    assert carbonate == [("60 s", "1"), ("60 s", "2"), ("60 s", "not stated"), ("60.00001 s", "1"), ("60.00002 s", "1")]
    left_out = {x["record"]: x["reason"] for x in res["excluded"]}
    assert "modulation_period as not measured" in left_out[unmeasured["id"]]
    # a delay recorded on the test itself: no analysis says what it was measured against
    test = node(doc, "test/modulation-250c")
    test["props"]["result_values"] = [entry(doc, "analysis/phase-sensitive-detection", "delay_co2")]
    on_test = pgraph_query.run(doc, spec_of(doc), {**plan, "match": {"label": "CatalyticTest", "as": "a"}})
    reasons = [x["reason"] for x in on_test["excluded"]]
    assert on_test["comparison"]["groups"] == [] and reasons
    assert all("a CatalyticTest, has no phase_reference" in r for r in reasons), reasons
