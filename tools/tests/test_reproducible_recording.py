"""Reproducible recording of a catalyst's preparation and characterization with the structures SCALE has (the recording
recipes, skills/curate-corpus/references/recipes.md). Two batches of one nominal formula stay two records with their
own lots, steps and treatments; a nominal and a measured composition stay two observations, each with its evidence; a
size from microscopy, diffraction or light scattering is its own measurand; a fitted coordination number keeps its
model, references and measurement conditions; what a source leaves unstated stays explicit. Exercised on the synthetic
preparation examples (domain/examples/scale-catal/preparation-examples/) and on variants of them written in memory."""

import copy
import re
import shutil
import subprocess
import sys

import pytest

from conftest import EXAMPLES, GRAPH_MANIFEST, HEAD_VERSION, REPO, spec_of
from scale import pgraph, pgraph_migrate, pgraph_query
from scale.pgraph_profiles import conformance
from scale.util import load_doc, write_canonical

PE = EXAMPLES / "scale-catal/preparation-examples"
FILES = ("impregnation.json", "coprecipitation.json", "high-entropy-alloy.json")


@pytest.fixture(scope="module")
def spec():
    return pgraph.load_spec(GRAPH_MANIFEST)


@pytest.fixture
def pi():
    return load_doc(PE / "impregnation.json")


@pytest.fixture
def cp():
    return load_doc(PE / "coprecipitation.json")


@pytest.fixture
def hea():
    return load_doc(PE / "high-entropy-alloy.json")


def _node(d: dict, nid: str) -> dict:
    return next(x for x in d["nodes"] if x["id"] == nid)


def _links(d: dict, typ: str, source: str | None = None, target: str | None = None) -> list:
    return [e for e in d["links"] if e["type"] == typ and (source is None or e["source"] == source)
            and (target is None or e["target"] == target)]


def _q(d: dict, spec: dict, plan: dict) -> dict:
    return pgraph_query.run(d, spec, plan)


def _vals(res: dict, key: str) -> list:
    return [r["values"].get(key) for r in res["rows"]]


def _entry(d: dict, nid: str, eid: str) -> dict:
    return next(x for x in _node(d, nid)["props"]["result_values"] if x["id"] == eid)


# ---------------------------------------------------------------- the examples
def test_the_examples_are_built_reproducibly(tmp_path):
    work = tmp_path / "pe"
    shutil.copytree(PE, work)
    subprocess.run([sys.executable, str(work / "build_examples.py")], check=True, capture_output=True, cwd=REPO)
    for name in FILES:
        d = load_doc(PE / name)
        if d["graph"]["schema_version"] != HEAD_VERSION:             # the head moved on after they were built
            d = pgraph_migrate.raise_version(d, HEAD_VERSION, pgraph.load_spec(GRAPH_MANIFEST))[0]
        write_canonical(tmp_path / name, d)
        assert (work / name).read_bytes() == (tmp_path / name).read_bytes(), name


@pytest.mark.parametrize("name", FILES)
def test_the_examples_are_valid_public_and_say_they_are_synthetic(name):
    d = load_doc(PE / name)
    rep = pgraph.validate(d, spec_of(d))
    assert rep.errors == [] and rep.warnings == [], (rep.errors, rep.warnings)
    assert d["graph"]["data_status"] == "synthetic_example" and d["graph"]["stewardship"]["access"] == "public"
    assert {n["props"]["origin"] for n in d["nodes"]} == {"synthetic"}
    assert conformance(d, spec_of(d))["profiles"]["catalysis"]["conformant"]


# ---------------------------------------------------------------- two batches of one nominal formula
def test_two_batches_of_one_nominal_formula_differ_by_lot_and_reduction_and_stay_queryable(pi, spec):
    b1, b2, cat = "ex:pi/sample/batch-1", "ex:pi/sample/batch-2", "ex:pi/catalyst/pt-alumina"
    assert [e["target"] for e in _links(pi, "HAS_FORMULATION", b1)] == [cat] == [e["target"] for e in _links(pi, "HAS_FORMULATION", b2)]
    assert _node(pi, b1)["props"]["batch_identifier"] != _node(pi, b2)["props"]["batch_identifier"]
    plan = {"match": {"label": "CatalystSample", "as": "batch"},
            "steps": [{"from": "batch", "edge": "HAS_FORMULATION", "to": "Catalyst", "as": "f",
                       "where": [{"prop": "id", "op": "eq", "value": cat}]},
                      {"from": "batch", "edge": "HAS_OUTPUT", "direction": "in", "to": "Preparation", "as": "prep"},
                      {"from": "prep", "edge": "PART_OF", "direction": "in", "to": "ProcedureStep", "as": "s",
                       "where": [{"prop": "action", "op": "eq", "value": "dissolve"}]},
                      {"from": "s", "edge": "HAS_INPUT", "to": "Sample", "as": "lot"},
                      {"from": "batch", "edge": "TREATED_BY", "to": "Treatment", "as": "red",
                       "where": [{"prop": "treatment_kind", "op": "eq", "value": "reduction"}],
                       "edge_where": [{"prop": "order", "op": "eq", "value": 1}]}],
            "return": ["batch.batch_identifier", "lot.batch_identifier", "red.temperature"]}
    got = sorted((r["values"]["batch.batch_identifier"], r["values"]["lot.batch_identifier"],
                  r["values"]["red.temperature"]["value"]) for r in _q(pi, spec, plan)["rows"])
    assert got == [("1", "A-1172", 573), ("2", "B-2090", 773)]
    # one lot asked for: only its batch
    plan["steps"][3]["where"] = [{"prop": "batch_identifier", "op": "eq", "value": "B-2090"}]
    assert _vals(_q(pi, spec, plan), "batch.batch_identifier") == ["2"]
    # a step's order is its place in the preparation; batch 2 was impregnated in two portions, which its protocol link
    # states as a deviation
    for prep, n in (("ex:pi/preparation/batch-1", 5), ("ex:pi/preparation/batch-2", 7)):
        orders = sorted(e["props"]["order"] for e in _links(pi, "PART_OF", target=prep))
        assert orders == list(range(1, n + 1)), prep
    devs = {e["source"]: e["props"].get("deviations") for e in _links(pi, "FOLLOWS_PROTOCOL")}
    assert devs["ex:pi/preparation/batch-1"] is None and "two portions" in devs["ex:pi/preparation/batch-2"]


def test_two_coprecipitations_differ_only_in_which_solution_was_added_to_which(cp, spec):
    plan = {"match": {"label": "CatalystSample", "as": "batch"},
            "steps": [{"from": "batch", "edge": "HAS_OUTPUT", "direction": "in", "to": "Preparation", "as": "prep"},
                      {"from": "prep", "edge": "PART_OF", "direction": "in", "to": "ProcedureStep", "as": "p",
                       "where": [{"prop": "action", "op": "eq", "value": "precipitate"}]},
                      {"from": "p", "edge": "HAS_INPUT", "to": "Sample", "as": "added",
                       "edge_where": [{"prop": "role", "op": "eq", "value": "reagent"}]},
                      {"from": "p", "edge": "HAS_INPUT", "to": "Sample", "as": "into",
                       "edge_where": [{"prop": "role", "op": "eq", "value": "material"}]}],
            "return": ["batch.batch_identifier", "added.name", "into.name"]}
    rows = {r["values"]["batch.batch_identifier"]: (r["values"]["added.name"], r["values"]["into.name"])
            for r in _q(cp, spec, plan)["rows"]}
    assert rows == {"N": ("sodium carbonate solution, batch-n", "mixed nitrate solution, batch-n"),
                    "R": ("mixed nitrate solution, batch-r", "sodium carbonate solution, batch-r")}
    # every other step is the same: action, temperature, duration and atmosphere in the same order
    def steps(prep):
        out = []
        for e in sorted(_links(cp, "PART_OF", target=prep), key=lambda e: e["props"]["order"]):
            p = _node(cp, e["source"])["props"]
            out.append((p["action"], (p.get("temperature") or {}).get("value"), (p.get("duration") or {}).get("value"),
                        p.get("atmosphere")))
        return out
    assert steps("ex:cp/preparation/batch-n") == steps("ex:cp/preparation/batch-r")
    # the solutions are samples with their concentrations, and the amounts weighed are on the inputs
    conc = {(e["source"], e["target"]): e["props"]["concentration"]["value"] for e in _links(cp, "HAS_COMPONENT")
            if "concentration" in e["props"]}
    assert conc[("ex:cp/solution/batch-n-nitrates", "ex:cp/species/cu-nitrate")] == 0.60
    amounts = {e["target"]: e["props"]["amount"]["value"] for e in _links(cp, "HAS_INPUT", "ex:cp/step/batch-r-dissolve-nitrates")}
    assert amounts["ex:cp/species/zn-nitrate"] == 17.85


def test_precursor_hydration_purity_and_lots_are_recorded_as_the_source_states_them(pi, hea):
    assert _node(pi, "ex:pi/species/h2ptcl6-6h2o")["props"]["formula"] == "H2PtCl6·6H2O"
    # a hydrate whose water content the source does not give keeps it unstated
    rh = _node(hea, "ex:hea/species/rhcl3")["props"]
    assert rh["formula"] == "RhCl3·xH2O" and "without its water content" in rh["note"]
    grades = {e["source"]: e["props"].get("grade") for e in _links(pi, "PREPARED_FROM", target="ex:pi/species/h2ptcl6-6h2o")}
    assert all("≥99.9 %" in g for g in grades.values()) and len(grades) == 2
    lots = {e["source"]: e["target"] for e in _links(pi, "HAS_COMPONENT") if e["source"].startswith("ex:pi/lot/h2ptcl6")}
    assert set(lots.values()) == {"ex:pi/species/h2ptcl6-6h2o"}
    assert {_node(pi, x)["props"]["batch_identifier"] for x in lots} == {"A-1172", "B-2090"}


# ---------------------------------------------------------------- nominal and measured composition
def test_a_nominal_and_a_measured_loading_coexist_with_their_evidence(pi, spec):
    plan = {"match": {"id": "ex:pi/sample/batch-1", "as": "batch"},
            "steps": [{"from": "batch", "edge": "HAS_FORMULATION", "to": "Catalyst", "as": "f"},
                      {"from": "f", "edge": "HAS_COMPONENT", "to": "Material", "as": "pt", "edge_as": "nominal",
                       "edge_where": [{"prop": "role", "op": "eq", "value": "active_phase"}]},
                      {"from": "batch", "edge": "CHARACTERIZES", "direction": "in", "to": "Characterization", "as": "icp"},
                      {"from": "icp", "entries": "result_values", "kind": "loading", "as": "measured"}],
            "return": ["nominal.loading", "measured"], "evidence": True}
    res = _q(pi, spec, plan)
    assert len(res["rows"]) == 1
    row = res["rows"][0]
    nominal, measured = row["values"]["nominal.loading"], row["values"]["measured"]
    assert (nominal["value"], nominal["unit"], nominal["origin"]) == (5, "wt%", "assumed")
    assert (measured["value"], measured["unit"], measured.get("origin")) == (3.8, "wt%", None)   # measured: its record's
    cited = {e["locator"] for e in row["evidence"]}
    assert {"Methods", "Table 1"} <= cited
    # neither replaces the other: the formulation keeps the nominal value, the specimen's measurement the measured one
    assert not [x for x in _node(pi, "ex:pi/catalyst/pt-alumina")["props"].get("properties", {}).values()]


def test_measured_loadings_on_one_basis_compare_and_one_without_a_basis_is_missing_context(pi, spec):
    plan = {"comparison": "scientific", "match": {"label": "Characterization", "as": "m"},
            "steps": [{"from": "m", "entries": "result_values", "kind": "loading", "as": "x",
                       "where": [{"prop": "target", "op": "eq", "value": "ex:pi/species/pt"}]}],
            "order_by": [{"var": "x", "prop": "value", "desc": True}], "return": ["m.name", "x"]}
    res = _q(pi, spec, plan)
    assert [r["values"]["x"]["value"] for r in res["rows"]] == [4.9, 4.6, 3.8]
    assert [g["compared_on"]["x.value"]["context"] for g in res["comparison"]["groups"]] == [{"fraction_basis": "mass"}]
    assert [e["reason"].split(" ")[0] for e in res["excluded"]] == ["missing_context"]
    assert "fraction_basis" in res["excluded"][0]["reason"]
    # stated by mass, it joins the others
    d = copy.deepcopy(pi)
    _entry(d, "ex:pi/characterization/icp-commercial-second", "pt_loading")["unit"] = "wt%"
    assert len(_q(d, spec, plan)["rows"]) == 4


def test_nominal_bulk_surface_and_working_state_compositions_of_an_alloy_stay_four_observations(hea, spec):
    ru = "ex:hea/species/ru"
    nominal = [e for e in _links(hea, "HAS_COMPONENT", "ex:hea/material/ptpdrhruir")]
    assert {e["props"]["fraction"]["value"] for e in nominal} == {20} and len(nominal) == 5
    assert {e["props"]["fraction"]["origin"] for e in nominal} == {"assumed"}
    plan = {"match": {"label": "Characterization", "as": "m"},
            "steps": [{"from": "m", "edge": "CHARACTERIZES", "to": "Sample", "as": "s", "edge_as": "at"},
                      {"from": "m", "entries": "result_values", "kind": "composition_fraction", "as": "x",
                       "where": [{"prop": "target", "op": "eq", "value": ru}]}],
            "return": ["m.technique", "m.information_depth", "at.state", "x"]}
    rows = sorted((r["values"]["m.technique"], r["values"]["m.information_depth"], r["values"]["at.state"],
                   r["values"]["x"]["value"]) for r in _q(hea, spec, plan)["rows"])
    assert rows == [("ICP-OES after acid digestion", "bulk", "as_prepared", 15.8),
                    ("X-ray photoelectron spectroscopy", "surface", "as_prepared", 14.1),
                    ("near-ambient-pressure XPS", "surface", "operating", 31.5)]
    # each measured set adds up to 100 at% of the metals, and none sits on the material or the formulation
    for cid in ("ex:hea/characterization/icp", "ex:hea/characterization/xps", "ex:hea/characterization/nap-xps"):
        fr = [x["value"] for x in _node(hea, cid)["props"]["result_values"] if x["unit"] == "at%"]
        assert round(sum(fr), 1) == 100.0, cid
    # the state under reaction conditions is a CatalystState of the sample, established by the measurement, with the
    # phase the measurement shows at the surface
    working = "ex:hea/state/under-co-oxidation"
    assert [e["target"] for e in _links(hea, "DETERMINED_BY", working)] == ["ex:hea/characterization/nap-xps"]
    phases = {e["target"]: (e["props"]["location"], e["props"]["dominance"]) for e in _links(hea, "HAS_PHASE", working)}
    assert phases["ex:hea/material/ruox"] == ("surface", "minority")


def test_bulk_and_surface_fractions_stay_apart_by_their_variable(cp, spec):
    """A composition fraction from XRF and one from XPS share a kind and a basis, so a plan that asks for a measured
    surface composition names the surface variable (or the technique's information depth)."""
    plan = {"match": {"label": "Characterization", "as": "m"},
            "steps": [{"from": "m", "entries": "result_values", "kind": "composition_fraction", "as": "x",
                       "where": [{"prop": "target", "op": "eq", "value": "ex:cp/species/cu"},
                                 {"prop": "variable", "op": "eq", "value": "ex:cp/variable/xps-metal-fraction"}]}],
            "return": ["m.name", "x"]}
    assert sorted(r["values"]["x"]["value"] for r in _q(cp, spec, plan)["rows"]) == [44.1, 52.3]


# ---------------------------------------------------------------- sizes by technique
def test_a_microscopy_average_never_answers_for_an_xrd_crystallite_size(pi, spec):
    def sizes(sample, kind):
        plan = {"match": {"label": "Characterization", "as": "m"},
                "steps": [{"from": "m", "edge": "CHARACTERIZES", "to": "Sample", "as": "s",
                           "where": [{"prop": "id", "op": "eq", "value": sample}]},
                          {"from": "m", "entries": "result_values", "as": "x"},
                          {"from": "x", "field": "variable", "to": "Variable", "as": "v",
                           "where": [{"prop": "quantity_kind", "op": "eq", "value": kind}]}],
                "return": ["m.technique", "x"]}
        return [(r["values"]["m.technique"], r["values"]["x"]["status"], r["values"]["x"].get("value"))
                for r in _q(pi, spec, plan)["rows"]]
    assert sizes("ex:pi/sample/batch-1", "crystallite_size") == [("powder X-ray diffraction", "below_detection_limit", 3)]
    assert sizes("ex:pi/sample/batch-1", "microscopy_particle_size") == [("HAADF-STEM", "present", 2.1)]
    assert sizes("ex:pi/sample/batch-2", "crystallite_size") == [("powder X-ray diffraction", "present", 6.5)]
    # without its XRD result, batch 1 has no crystallite size at all, whatever microscopy gives
    d = copy.deepcopy(pi)
    d["nodes"] = [n for n in d["nodes"] if n["id"] != "ex:pi/characterization/xrd-batch-1"]
    d["links"] = [e for e in d["links"] if "ex:pi/characterization/xrd-batch-1" not in (e["source"], e["target"])]
    plan = {"match": {"label": "Characterization", "as": "m"},
            "steps": [{"from": "m", "edge": "CHARACTERIZES", "to": "Sample", "as": "s",
                       "where": [{"prop": "id", "op": "eq", "value": "ex:pi/sample/batch-1"}]},
                      {"from": "m", "entries": "result_values", "as": "x"},
                      {"from": "x", "field": "variable", "to": "Variable", "as": "v",
                       "where": [{"prop": "quantity_kind", "op": "eq", "value": "crystallite_size"}]}],
            "return": ["x"]}
    assert _q(d, spec, plan)["status"] == "no_matching_record"


def test_three_sizes_are_three_variables_and_a_distribution_keeps_its_statistics(pi, hea):
    kinds = {n["props"].get("quantity_kind") for n in hea["nodes"] if n["label"] == "Variable"}
    assert {"microscopy_particle_size", "crystallite_size", "hydrodynamic_size"} <= kinds
    stem = {x["id"]: x for x in _node(pi, "ex:pi/characterization/stem-batch-1")["props"]["result_values"]}
    assert (stem["mean_diameter"]["value"], stem["diameter_sd"]["value"], stem["particles_counted"]["value"]) == (2.1, 0.5, 312)
    # the width of the distribution is its own entry, never the uncertainty of the mean
    assert "uncertainty" not in stem["mean_diameter"]
    sd_var = _node(pi, stem["diameter_sd"]["variable"])["props"]
    assert sd_var["quantity_kind"] == "microscopy_particle_size_spread" and "not an uncertainty" in sd_var["definition"]
    # the hydrodynamic size is of the colloid, before deposition, not of the supported catalyst
    dls = _links(hea, "CHARACTERIZES", "ex:hea/characterization/dls")
    assert [e["target"] for e in dls] == ["ex:hea/sample/colloid"]


# ---------------------------------------------------------------- an XAS fit keeps what it rests on
def test_an_xas_coordination_number_keeps_its_model_references_and_measurement_conditions(pi, spec):
    fit = "ex:pi/analysis/exafs-batch-1"
    cn = _entry(pi, fit, "cn_pt_pt")
    assert (cn["value"], cn["origin"], cn["produced_by"], cn["uncertainty"]) == (7.9, "fitted", fit, 0.6)
    plan = {"match": {"id": fit, "as": "fit"},
            "steps": [{"from": "fit", "edge": "USES_MODEL", "to": "Model", "as": "model"},
                      {"from": "fit", "edge": "HAS_INPUT", "to": "Dataset", "as": "ref",
                       "edge_where": [{"prop": "role", "op": "eq", "value": "reference_standard"}]},
                      {"from": "fit", "edge": "HAS_INPUT", "to": "Dataset", "as": "data",
                       "edge_where": [{"prop": "role", "op": "eq", "value": "data"}]},
                      {"from": "data", "edge": "HAS_OUTPUT", "direction": "in", "to": "Characterization", "as": "xas"},
                      {"from": "xas", "edge": "CHARACTERIZES", "to": "CatalystSample", "as": "s", "edge_as": "at"}],
            "return": ["model.assumptions", "ref.name", "xas.temperature", "xas.atmosphere", "xas.observation_mode",
                       "xas.conditions.energy_calibration", "at.state", "fit.limitations", "fit.method"]}
    res = _q(pi, spec, plan)
    assert len(res["rows"]) == 1
    v = res["rows"][0]["values"]
    assert any("S0^2 = 0.84" in a and "held fixed" in a for a in v["model.assumptions"])
    assert v["ref.name"] == "Pt L3 XAS of the Pt foil" and v["at.state"] == "reactivated"
    assert (v["xas.temperature"]["value"], v["xas.observation_mode"]) == (298, "in_situ") and "H2" in v["xas.atmosphere"]
    assert "Pt foil" in v["xas.conditions.energy_calibration"]["text_value"]
    assert "k 3.0-12.5" in v["fit.method"] and v["fit.limitations"]
    # the state measured is the one reached by the reduction in the cell, after storage
    assert [e["target"] for e in _links(pi, "DETERMINED_BY", "ex:pi/state/batch-1-re-reduced")] == \
        ["ex:pi/characterization/xas-batch-1"]
    rec = conformance(pi, spec_of(pi), by_record=True)["profiles"]["catalysis"]["records"][fit]
    assert rec["evidence"]["fitted_data"]["found"]


# ---------------------------------------------------------------- what the source leaves unstated
def test_an_unstated_mixing_rate_storage_atmosphere_and_raw_data_stay_explicit(pi, cp, spec):
    for key in ("batch-n", "batch-r"):
        stirring = _node(cp, f"ex:cp/step/{key}-precipitate")["props"]["conditions"]["stirring_rate"]
        assert (stirring["status"], stirring["missing_reason"]) == ("not_reported", "not_stated_in_source")
    assert _node(cp, "ex:cp/step/batch-r-precipitate")["props"]["conditions"]["addition_rate"]["status"] == "not_reported"
    assert _node(cp, "ex:cp/step/batch-n-precipitate")["props"]["conditions"]["addition_rate"]["value"] == 3
    atmospheres = {n["id"]: n["props"]["atmosphere"] for d in (pi, cp) for n in d["nodes"]
                   if n["label"] == "Treatment" and n["props"]["treatment_kind"] == "exposure"}
    assert atmospheres == {"ex:pi/treatment/batch-1-storage": "not stated", "ex:cp/treatment/batch-n-storage":
                           "dry air, in a desiccator over silica gel", "ex:cp/treatment/batch-r-storage": "not stated"}
    unavailable = sorted(n["props"]["name"] for d in (pi, cp) for n in d["nodes"]
                         if n["label"] == "Dataset" and n["props"]["availability"] == "not_reported")
    assert unavailable == ["HAADF-STEM images of batch 2", "N2 isotherm of batch 1", "XPS spectra of batch-n",
                           "XPS spectra of batch-r"]
    # a filter on an unstated rate never passes as a number, and the step is not left out as uncurated
    plan = {"match": {"label": "ProcedureStep", "as": "s", "where": [{"prop": "action", "op": "eq", "value": "precipitate"}]},
            "where": [{"var": "s", "prop": "conditions.addition_rate", "op": "gt", "value": 0, "unit": "mL/min"}],
            "return": ["s.id"]}
    res = _q(cp, spec, plan)
    assert _vals(res, "s.id") == ["ex:cp/step/batch-n-precipitate"]
    assert [e["record"] for e in res["excluded"]] == ["ex:cp/step/batch-r-precipitate"]


def test_storage_and_transfer_are_steps_of_the_history_in_order(pi):
    order = sorted((e["props"]["order"], _node(pi, e["target"])["props"]["treatment_kind"])
                   for e in _links(pi, "TREATED_BY", "ex:pi/sample/batch-1"))
    assert order == [(1, "reduction"), (2, "oxidation"), (3, "exposure"), (4, "reduction")]
    stem = _node(pi, "ex:pi/characterization/stem-batch-1")["props"]
    assert stem["observation_mode"] == "ex_situ" and "in air" in stem["transfer"]
    assert [e["target"] for e in _links(pi, "DETERMINED_BY", "ex:pi/state/batch-1-stored")] == \
        ["ex:pi/characterization/stem-batch-1"]


# ---------------------------------------------------------------- purchased samples
def test_purchased_lots_of_one_product_share_neither_a_batch_nor_a_surface_state(pi, spec):
    lots = [n for n in pi["nodes"] if n["label"] == "CatalystSample" and n["props"]["preparation_status"] == "purchased"]
    assert len(lots) == 2
    assert {e["target"] for lot in lots for e in _links(pi, "HAS_FORMULATION", lot["id"])} == \
        {"ex:pi/catalyst/commercial-pt-alumina"}
    assert [lot["props"].get("batch_identifier") for lot in sorted(lots, key=lambda n: n["id"])] == ["0417", None]
    ids = {lot["id"] for lot in lots}
    assert not [e for e in pi["links"] if e["source"] in ids and e["target"] in ids]        # nothing joins them
    plan = {"match": {"label": "CatalystSample", "as": "lot",
                      "where": [{"prop": "preparation_status", "op": "eq", "value": "purchased"}]},
            "steps": [{"from": "lot", "edge": "CHARACTERIZES", "direction": "in", "to": "Characterization", "as": "c"},
                      {"from": "c", "edge": "HAS_INPUT", "direction": "in", "to": "Analysis", "as": "a",
                       "edge_where": [{"prop": "role", "op": "eq", "value": "data"}]},
                      {"from": "a", "entries": "result_values", "kind": "site_fraction", "as": "dispersion"}],
            "return": ["lot.id", "dispersion"]}
    got = sorted((r["values"]["lot.id"], r["values"]["dispersion"]["value"]) for r in _q(pi, spec, plan)["rows"])
    assert got == [("ex:pi/sample/commercial-lot-0417", 33), ("ex:pi/sample/commercial-second-lot", 24)]
    # asked for lot 0417, the second lot does not answer, though it has the same formulation
    plan["match"]["where"].append({"prop": "batch_identifier", "op": "eq", "value": "0417"})
    res = _q(pi, spec, plan)
    assert _vals(res, "lot.id") == ["ex:pi/sample/commercial-lot-0417"]


# ---------------------------------------------------------------- the recipes name what the schema has
RECIPE = REPO / "skills/curate-corpus/references/recipes.md"


def test_the_recording_recipes_name_only_labels_links_and_properties_the_schema_declares(spec):
    """Every `Label.property` and every link type the recipe sections on preparation and characterization name in
    code is declared by the schema the examples pin."""
    text = RECIPE.read_text(encoding="utf-8")
    start, end = text.index("## Preparation recipes"), text.index("## Digitizing a figure")
    section = text[start:end]
    nodes, edges = spec["nodes"], spec["edges"]

    def props_of(label):
        out, todo = set(), [label]
        while todo:
            x = nodes.get(todo.pop()) or {}
            out |= set(x.get("properties") or {})
            todo += x.get("is_a") or []
        return out
    named = set(re.findall(r"`([A-Z][A-Za-z]+)\.([a-z_]+)", section))
    assert named, "the section names no Label.property"
    for label, prop in sorted(named):
        if label in nodes:
            assert prop in props_of(label), f"{label}.{prop}"
        else:
            assert label in edges and prop in (edges[label].get("properties") or {}), f"{label}.{prop}"
    links = set(re.findall(r"`([A-Z][A-Z_]{3,})`", section))
    assert links and not sorted(x for x in links if x not in edges), sorted(x for x in links if x not in edges)
