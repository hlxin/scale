"""Computed energies and kinetic parameters, compared under explicit definitions (scale-catal 0.7.0 on).

A computed energy is a value of its kind (a total electronic energy, a reaction or adsorption energy, an enthalpy or a
free energy, an elementary activation energy or activation free energy, an apparent activation energy, a degree of rate
control). A scientific comparison keeps two values apart unless they are of one kind and agree on what their kind is
compared by: the reaction they are the energy change of (its participants are the reference states), the level of
theory and the charge treatment of the computation that produced them; it shows, never groups by, what that computation
states of its dispersion, +U, spin, solvation, temperature, pressure and potential. A reaction's or a step's
participants are checked for atom and charge balance, each check on its own and apart from what the source says; a
validation on the data a model was fitted to is reported; a state computed on a model needs no specimen. Exercised on the
computation example (domain/examples/scale-catal/computation-examples/), the nitrate example and variants written in
memory."""

import copy
import shutil
import subprocess
import sys

import pytest

from conftest import DRIVING_FORCE_EXAMPLES, EXAMPLES, GRAPH_MANIFEST, HEAD_VERSION, REPO, as_project_data, spec_of
from scale import pgraph, pgraph_migrate, pgraph_query, quantities, stoichiometry
from scale.pgraph_profiles import conformance
from scale.schema_change import diff_specs, tier
from scale.util import ScaleError, load_doc, write_canonical

CE = EXAMPLES / "scale-catal/computation-examples"
DOC = CE / "computed-energies.json"
ELECTRO = DRIVING_FORCE_EXAMPLES / "electro.json"
P = "ex:ce"
H2O_REF = f"{P}/reaction/o-adsorption-from-h2o"


@pytest.fixture
def doc():
    return load_doc(DOC)


@pytest.fixture(scope="module")
def spec():
    return pgraph.load_spec(GRAPH_MANIFEST)


def _node(d: dict, local: str) -> dict:
    return next(x for x in d["nodes"] if x["id"] == f"{P}/{local}")


def _links(d: dict, typ: str) -> list[dict]:
    return [e for e in d["links"] if e["type"] == typ]


def _entry(d: dict, rec: str, rid: str) -> dict:
    return next(x for x in _node(d, rec)["props"]["result_values"] if x["id"] == rid)


def _rank(d: dict, spec: dict, kinds, context: dict | None = None, label: str = "Computation") -> dict:
    """A scientific ranking of the energies the computations hold, optionally on stated contexts."""
    ob = {"var": "e", "prop": "value", **({"context": context} if context else {})}
    return pgraph_query.run(d, spec, {"comparison": "scientific", "match": {"label": label, "as": "comp"},
                                      "steps": [{"from": "comp", "entries": "result_values", "kind": kinds, "as": "e"}],
                                      "return": ["comp.name", "e"], "order_by": [ob]})


def _groups(res: dict) -> dict:
    """comp.name -> the comparison group its row is in."""
    return {r["values"]["comp.name"]: r["comparison_group"] for r in res["rows"]}


def _reasons(res: dict) -> dict:
    return {x["record"]: x["reason"] for x in res["excluded"]}


# ---------------------------------------------------------------- the example
def test_the_example_is_built_reproducibly(tmp_path):
    work = tmp_path / "ce"
    shutil.copytree(CE, work)
    subprocess.run([sys.executable, str(work / "build_examples.py")], check=True, capture_output=True, cwd=REPO)
    d = load_doc(DOC)
    if d["graph"]["schema_version"] != HEAD_VERSION:              # the head moved on after it was built
        d = pgraph_migrate.raise_version(d, HEAD_VERSION, pgraph.load_spec(GRAPH_MANIFEST))[0]
    write_canonical(tmp_path / DOC.name, d)
    assert (work / DOC.name).read_bytes() == (tmp_path / DOC.name).read_bytes()


def test_the_example_is_valid_and_lacks_only_what_it_was_built_to_lack(doc):
    rep = pgraph.validate(doc, spec_of(doc))
    assert rep.errors == [], rep.errors
    assert [w["message"].split(" (")[0] for w in rep.warnings] == [
        f"a validation of {P}/model/example-mlip on data it was fitted to"], rep.warnings
    c = conformance(doc, spec_of(doc), by_record=True)["profiles"]["catalysis"]
    assert c["conformant"] and c["missing_evidence"] == {}
    assert rep.balance["atoms"] == {"balanced": 6} and rep.balance["charge"] == {"balanced": 6}


# ---------------------------------------------------------------- one kind, one reaction, one method, one ensemble
def test_an_electronic_and_a_free_adsorption_energy_never_share_a_group_though_both_are_in_ev(doc, spec):
    res = _rank(doc, spec, ["reaction_energy", "reaction_free_energy"])
    g = _groups(res)
    electronic, free = g["O on Pt(111), RPBE"], g["O on Pt(111), RPBE free energy at 298.15 K"]
    assert electronic != free
    on = {x["group"]: x["compared_on"]["e.value"] for x in res["comparison"]["groups"]}
    assert on[electronic]["unit"] == on[free]["unit"] == "eV"
    assert on[electronic]["context"] == on[free]["context"]          # same reaction, method and ensemble: kind alone
    assert (on[electronic]["kind"], on[free]["kind"]) == ("reaction_energy", "reaction_free_energy")
    # the descriptor: the four electronic energies relative to H2O and H2 form one group, ranked within it
    desc = [r["values"]["comp.name"] for r in res["rows"] if r["comparison_group"] == electronic]
    assert desc == ["O on Cu(111), RPBE", "O on Pt(111), RPBE", "O on Ag(111), RPBE", "O on Au(111), RPBE"]


def test_values_of_two_kinds_in_one_unit_are_never_grouped_even_without_contexts(spec):
    """The group key is the kind too: two kinds without contexts in one unit (a fraction and an efficiency, both %)
    used to share a group."""
    d = load_doc(ELECTRO)
    t = next(n for n in d["nodes"] if n["label"] == "CatalyticTest")
    for key, kind in (("fraction", "fraction"), ("efficiency", "efficiency")):
        d["nodes"].append({"id": f"ex:df-electro/variable/{key}", "label": "Variable",
                           "props": {"name": key, "scale": "quantitative", "quantity_kind": kind, "unit": "%",
                                     "origin": "synthetic"}})
    t["props"]["evidence"].append({"id": "x1", "source": "ex:df-electro/source/paper", "locator": "Table 2", "kind": "table"})
    t["props"]["result_values"] = [
        {"id": "a_fraction", "status": "present", "value": 40, "unit": "%", "variable": "ex:df-electro/variable/fraction",
         "evidence_ids": ["x1"]},
        {"id": "an_efficiency", "status": "present", "value": 60, "unit": "%",
         "variable": "ex:df-electro/variable/efficiency", "evidence_ids": ["x1"]}]
    res = pgraph_query.run(d, spec, {"comparison": "scientific", "match": {"label": "CatalyticTest", "as": "t"},
                                     "steps": [{"from": "t", "entries": "result_values", "as": "e"}],
                                     "return": ["e.id"], "order_by": [{"var": "e", "prop": "value"}]})
    assert len({r["comparison_group"] for r in res["rows"]}) == 2
    assert sorted(g["compared_on"]["e.value"]["kind"] for g in res["comparison"]["groups"]) == ["efficiency", "fraction"]


def test_two_molecular_reference_conventions_stay_distinguishable(doc, spec):
    res = _rank(doc, spec, ["reaction_energy"])
    rows = {(r["values"]["comp.name"], r["values"]["e"]["id"]): r for r in res["rows"]}
    h2o, o2 = rows[("O on Pt(111), RPBE", "o_adsorption_h2o")], rows[("O on Pt(111), RPBE", "o_adsorption_o2")]
    assert h2o["comparison_group"] != o2["comparison_group"]
    assert h2o["compared"]["e.value"]["context"]["process"] == H2O_REF
    assert o2["compared"]["e.value"]["context"]["process"] == f"{P}/reaction/o-adsorption-from-o2"
    # the reference states are the reaction's participants, with their coefficients
    parts = {(e["target"].rsplit("/", 1)[1], e["props"]["role"], e["props"]["coefficient"]) for e in _links(doc, "HAS_PARTICIPANT")
             if e["source"] == f"{P}/reaction/o-adsorption-from-o2"}
    assert parts == {("o2", "reactant", 0.5), ("o", "product", 1)}
    # a ranking stated on one reference leaves the other out as incompatible, never compares it
    res = _rank(doc, spec, ["reaction_energy"], {"process": H2O_REF})
    assert "incompatible_context" in _reasons(res)[f"{P}/computation/pt-111"]
    assert "O on Pt(111), RPBE" in _groups(res)            # its H2O-referenced energy stays


def test_constant_charge_and_constant_potential_stay_apart_unless_converted_with_evidence(doc, spec):
    res = _rank(doc, spec, ["reaction_free_energy"])
    rows = {(r["values"]["comp.name"], r["values"]["e"]["id"]): r for r in res["rows"]}
    che = rows[("O electroadsorption on Pt(111), computational hydrogen electrode", "o_electroadsorption")]
    converted = rows[("O electroadsorption on Pt(111), computational hydrogen electrode",
                      "o_electroadsorption_constant_potential")]
    cip = rows[("O electroadsorption on Pt(111) at constant potential", "o_electroadsorption")]
    assert che["compared"]["e.value"]["context"]["charge_treatment"] == "constant_charge"
    assert cip["compared"]["e.value"]["context"]["charge_treatment"] == "constant_potential"
    assert che["comparison_group"] != cip["comparison_group"] == converted["comparison_group"]
    assert converted["compared"]["e.value"]["converted"] == ["charge_treatment"]
    # the rows show what the computations state of their solvation and potential, and the group says they differ
    assert cip["compared"]["e.value"]["shows"]["solvation"] == "implicit_and_explicit"
    assert converted["compared"]["e.value"]["shows"]["solvation"] == "none"
    assert any("solvation: implicit_and_explicit, none" in x for x in res["limitations"])
    # a conversion that names no analysis is not evidenced: its statements disagree, and it is left out
    d = copy.deepcopy(doc)
    x = _entry(d, "computation/pt-111-che", "o_electroadsorption_constant_potential")
    del x["produced_by"], x["origin"]
    res = _rank(d, spec, ["reaction_free_energy"])
    assert "incompatible_context" in _reasons(res)[f"{P}/computation/pt-111-che"]
    assert "charge_treatment" in _reasons(res)[f"{P}/computation/pt-111-che"]


def test_a_missing_method_or_reference_is_a_specific_comparison_context_diagnostic(doc, spec):
    res = _rank(doc, spec, ["reaction_energy"])
    why = _reasons(res)
    assert why[f"{P}/computation/pd-111"].startswith("missing_context (value level_of_theory: ")
    assert f"its producer {P}/computation/pd-111 states its level_of_theory as not reported (not_stated_in_source)" \
        in why[f"{P}/computation/pd-111"]
    assert why[f"{P}/computation/ni-111"].startswith("missing_context (value process: its unresolved_target")
    assert "the reference species are not stated" in why[f"{P}/computation/ni-111"]
    # a computation that states nothing about its level of theory, and a value nothing says the producer of
    d = copy.deepcopy(doc)
    del _node(d, "computation/cu-111")["props"]["level_of_theory"]
    assert f"its producer {P}/computation/cu-111 states no level_of_theory" in \
        _reasons(_rank(d, spec, ["reaction_energy"]))[f"{P}/computation/cu-111"]
    step = _node(d, "step/o2-dissociation")
    del step["props"]["activation_energy"]["produced_by"], step["props"]["activation_energy"]["origin"]
    res = pgraph_query.run(d, spec, {"comparison": "scientific", "match": {"label": "ElementaryStep", "as": "s"},
                                     "steps": [{"from": "s", "entries": "activation_energy", "as": "ea"}],
                                     "return": ["s.name"], "order_by": [{"var": "ea", "prop": "value"}]})
    assert "nothing names what produced it" in _reasons(res)[f"{P}/step/o2-dissociation"]
    assert [r["values"]["s.name"] for r in res["rows"]] == ["CO* + O* -> CO2(g)"]


def test_a_machine_learned_prediction_is_compared_apart_from_the_method_it_was_trained_on(doc, spec):
    g = _groups(_rank(doc, spec, ["reaction_energy"]))
    assert g["O on Pt3Ni(111), predicted by the machine-learned potential"] != g["O on Pt(111), RPBE"]


# ---------------------------------------------------------------- settings shown, conditions warned about
def test_settings_are_shown_with_each_row_never_grouped_by(doc, spec):
    d = copy.deepcopy(doc)
    _node(d, "computation/ag-111")["props"]["dispersion"] = {"status": "present", "text_value": "D3(BJ)"}
    res = _rank(d, spec, ["reaction_energy"], {"process": H2O_REF, "level_of_theory": "RPBE",
                                                "charge_treatment": "constant_charge"})
    assert len(res["rows"]) == 4 and len(res["comparison"]["groups"]) == 1
    shown = {r["values"]["comp.name"]: r["compared"]["e.value"]["shows"]["dispersion"] for r in res["rows"]}
    assert shown["O on Ag(111), RPBE"] == "D3(BJ)" and shown["O on Cu(111), RPBE"] == "none"
    assert any("dispersion: D3(BJ), none" in x for x in res["limitations"])


def test_a_free_energy_that_states_no_temperature_is_warned_about_and_kept(doc):
    d = copy.deepcopy(doc)
    del _node(d, "computation/pt-111-free-energy")["props"]["temperature"]
    rep = pgraph.validate(d, spec_of(d))
    assert rep.errors == []
    msgs = [w["message"] for w in rep.warnings if w["record"] == f"{P}/computation/pt-111-free-energy"]
    assert msgs == ["result_values.o_adsorption_free_h2o: this reaction_free_energy does not state the temperature it "
                    "holds at: the experiment that produced it (its produced_by, else the experiment that holds it) states "
                    "none; it stays as reported, and a scientific comparison shows it as not stated"]


def test_an_activation_energy_in_kelvin_is_kept_and_compared_only_in_kelvin(doc, spec):
    d = copy.deepcopy(doc)
    ea = _node(d, "step/co-plus-o")["props"]["activation_energy"]
    ea.update(value=11370, unit="K", definition="Ea/R of the rate constant")
    assert pgraph.validate(d, spec_of(d)).errors == []
    res = pgraph_query.run(d, spec, {"comparison": "scientific", "match": {"label": "ElementaryStep", "as": "s"},
                                     "steps": [{"from": "s", "entries": "activation_energy", "as": "ea"}],
                                     "return": ["s.name"], "order_by": [{"var": "ea", "prop": "value"}]})
    assert len(res["comparison"]["groups"]) == 2
    assert {g["compared_on"]["ea.value"]["unit"] for g in res["comparison"]["groups"]} == {"eV", "K"}


def test_an_activation_energy_in_volts_is_an_error(doc):
    d = copy.deepcopy(doc)
    _node(d, "step/co-plus-o")["props"]["activation_energy"]["unit"] = "V"
    assert any("unit 'V' is electric_potential" in e["message"] and "not a dimension of activation_energy" in e["message"]
               for e in pgraph.validate(d, spec_of(d)).errors)


# ---------------------------------------------------------------- an apparent fit, a barrier, a rate-control sensitivity
def test_a_fitted_apparent_activation_energy_is_never_returned_as_a_transition_state_barrier(doc, spec):
    barriers = pgraph_query.run(doc, spec, {"match": {"label": "ElementaryStep", "as": "s"},
                                            "steps": [{"from": "s", "entries": "activation_energy", "kind": "activation_energy",
                                                       "as": "ea"},
                                                      {"from": "s", "edge": "TRANSITION_STATE", "to": "StructureModel",
                                                       "as": "ts"}],
                                            "return": ["s.name", "ea", "ts.name"]})
    assert sorted(r["values"]["ea"]["value"] for r in barriers["rows"]) == [0.62, 0.98]
    anywhere = pgraph_query.run(doc, spec, {"match": {"label": "Experiment", "as": "x"},
                                            "steps": [{"from": "x", "entries": "result_values", "kind": "activation_energy",
                                                       "as": "ea"}], "return": ["x.name"]})
    assert anywhere["status"] == "no_matching_record"
    fit = _entry(doc, "analysis/arrhenius-fit", "apparent_activation_energy")
    assert fit["value"] == 105 and fit["unit"] == "kJ/mol"
    assert _node(doc, f"variable/co2-apparent-activation-energy")["props"]["quantity_kind"] == "apparent_activation_energy"
    # the fit keeps the range it holds over, the rates it fits and its transport check
    assert _node(doc, "analysis/arrhenius-fit")["props"]["temperature"] == {"status": "present", "lower": 450, "upper": 510,
                                                                          "unit": "K"}


def test_a_degree_of_rate_control_belongs_to_the_conditions_of_its_run(doc, spec):
    res = pgraph_query.run(doc, spec, {"comparison": "scientific",
                                       "match": {"label": "Computation", "as": "run",
                                                 "where": [{"prop": "computation_kind", "op": "eq", "value": "microkinetic"}]},
                                       "steps": [{"from": "run", "edge": "RATE_CONTROL", "to": "ElementaryStep", "as": "step",
                                                  "edge_as": "rc"},
                                                 {"from": "run", "edge": "IN_STATE", "to": "CatalystState", "as": "state"}],
                                       "return": ["run.temperature", "step.name", "rc.degree_of_rate_control", "state.name"],
                                       "order_by": [{"var": "rc", "prop": "degree_of_rate_control", "desc": True}]})
    top = {r["compared"]["rc.degree_of_rate_control"]["shows"]["temperature"]: r["values"]["step.name"]
           for r in res["rows"] if r["values"]["rc.degree_of_rate_control"]["value"] > 0.5}
    assert top == {"450 K": "O2* -> 2 O*", "500 K": "CO* + O* -> CO2(g)"}
    assert len(res["comparison"]["groups"]) == 1
    assert any("temperature: 450 K, 500 K" in x for x in res["limitations"])
    assert {r["values"]["state.name"] for r in res["rows"]} == {"computed: Pt(111) with 0.25 ML O"}


# ---------------------------------------------------------------- fitted, predicted, validated
def test_fitting_data_are_never_counted_as_independent_validation(doc):
    rep = pgraph.validate(doc, spec_of(doc))
    flagged = {w["record"] for w in rep.warnings if "on data it was fitted to" in w["message"]}
    on_training = next(e["id"] for e in _links(doc, "EVALUATES") if e["source"] == f"{P}/experiment/mlip-validation-training-set")
    assert flagged == {on_training}
    # a held-out split that includes a record of the training data is not independent either
    d = copy.deepcopy(doc)
    d["nodes"].append({"id": f"{P}/dataset/a-training-structure", "label": "Dataset",
                       "props": {"name": "one training structure", "data_kind": "structure", "availability": "available",
                                 "origin": "synthetic"}})
    for src in ("adsorption-training-set", "adsorption-test-set"):
        d["links"].append({"id": f"{P}/link/includes-{src}", "type": "INCLUDES", "source": f"{P}/dataset/{src}",
                           "target": f"{P}/dataset/a-training-structure", "props": {"origin": "synthetic"}})
    flagged = {w["record"] for w in pgraph.validate(d, spec_of(d)).warnings if "on data it was fitted to" in w["message"]}
    assert len(flagged) == 2
    # a validation whose passing outcome rests on a fitted value
    d = copy.deepcopy(doc)
    _entry(d, "experiment/mlip-validation-held-out", "mae").update(origin="fitted", produced_by=f"{P}/experiment/mlip-training")
    msgs = [w["message"] for w in pgraph.validate(d, spec_of(d)).warnings]
    assert "a validation whose outcome rests on a fitted value: a fit does not validate its own data" in msgs


def test_a_model_fitted_to_measured_rates_is_not_validated_by_the_same_rates(doc):
    d = copy.deepcopy(doc)
    model, fit, check = f"{P}/model/arrhenius", f"{P}/analysis/arrhenius-fit", f"{P}/experiment/rate-law-check"
    d["links"].append({"id": f"{P}/link/fit-calibrates", "type": "EVALUATES", "source": fit, "target": model,
                       "props": {"evaluation_kind": "calibration", "origin": "synthetic"}})
    for e in d["links"]:
        if e["source"] == fit and e["type"] == "HAS_INPUT" and "/test/" in e["target"]:
            e["props"]["role"] = "training_data"
    d["nodes"].append({"id": check, "label": "Experiment", "props": {"name": "the rate law against the rates",
                                                                     "experiment_kind": "computational", "origin": "synthetic"}})
    d["links"] += [{"id": f"{P}/link/check-evaluates", "type": "EVALUATES", "source": check, "target": model,
                    "props": {"evaluation_kind": "validation", "outcome": "passes", "origin": "synthetic"}},
                   {"id": f"{P}/link/check-uses", "type": "HAS_INPUT", "source": check, "target": f"{P}/test/co-oxidation-480k",
                    "props": {"role": "test_data", "origin": "synthetic"}}]
    msgs = [w["message"] for w in pgraph.validate(d, spec_of(d)).warnings if w["record"] == f"{P}/link/check-evaluates"]
    assert msgs and f"({P}/test/co-oxidation-480k)" in msgs[0]


def test_a_predicted_value_names_what_predicted_it(doc):
    d = copy.deepcopy(doc)
    step = _node(d, "step/o2-dissociation")
    step["props"]["activation_energy"].update(origin="predicted")
    del step["props"]["activation_energy"]["produced_by"]
    msgs = [w["message"] for w in pgraph.validate(d, spec_of(d)).warnings if w["record"] == step["id"]]
    assert msgs == ["activation_energy: a predicted value names the experiment that predicted it (produced_by), whose model "
                    "and the data it was fitted to say what the prediction rests on"]
    # on the computation that predicted it, it needs none
    assert not [w for w in pgraph.validate(doc, spec_of(doc)).warnings if "predicted value" in w["message"]]


def test_a_machine_learned_prediction_names_its_checkpoint_and_the_data_it_was_fitted_to(doc):
    mlip = _node(doc, "model/example-mlip")["props"]
    assert mlip["version"] == "ckpt-0420"
    weights = next(n for n in doc["nodes"] if n["id"] == mlip["stored_in"])["props"]
    assert len(weights["sha256"]) == 64 and weights["version"] == "1"
    c = conformance(doc, spec_of(doc), by_record=True)["profiles"]["catalysis"]["records"][f"{P}/computation/mlip-pt3ni"]
    assert {k: v["found"] for k, v in c["evidence"].items()} == {"fitted_on": True, "validated_by": True}


# ---------------------------------------------------------------- a computed state, a model, its specimen
def test_a_computed_state_needs_no_specimen(doc):
    state = f"{P}/state/o-covered-pt111"
    of = [e["target"] for e in _links(doc, "STATE_OF") if e["source"] == state]
    assert of == [f"{P}/model/pt-111"]
    assert _node(doc, "model/pt-111")["label"] == "StructureModel"
    rep = next(e for e in _links(doc, "REPRESENTS") if e["source"] == f"{P}/model/pt-111")
    assert rep["target"] == f"{P}/sample/pt-al2o3-k" and "the alumina support is left out" in rep["props"]["assumptions"]
    # as research data, with the state's origin computed, it is valid and conformant without a specimen of its own
    d = copy.deepcopy(doc)
    d["nodes"] += [{"id": f"{P}/org/lab", "label": "Institution", "props": {"name": "A laboratory", "origin": "synthetic"}},
                   {"id": f"{P}/project/p", "label": "Project", "props": {"name": "A project", "origin": "synthetic"}}]
    d = as_project_data(d, project=f"{P}/project/p", contributed_by=[f"{P}/org/lab"])
    next(n for n in d["nodes"] if n["id"] == state)["props"]["origin"] = "computed"
    rep = pgraph.validate(d, spec_of(d))
    assert rep.errors == [], rep.errors
    assert rep.conformance["profiles"]["catalysis"]["conformant"]


def test_large_structures_and_settings_stay_in_checksummed_datasets(doc):
    comps = [n for n in doc["nodes"] if n["label"] == "Computation" and n["props"].get("computation_kind") == "electronic_structure"]
    assert comps and all("configuration" in n["props"] and "execution_environment" in n["props"] for n in comps)
    models = [n for n in doc["nodes"] if n["label"] == "StructureModel"]
    by_id = {n["id"]: n for n in doc["nodes"]}
    for m in models:
        ds = by_id[m["props"]["stored_in"]]["props"]
        assert ds["data_kind"] == "structure" and len(ds["sha256"]) == 64 and ds["version"]


# ---------------------------------------------------------------- atom and charge balance
def _participant(d: dict, species: str) -> dict:
    return next(e for e in d["links"] if e["type"] == "HAS_PARTICIPANT" and e["target"].endswith("/" + species))


def test_an_electron_coefficient_of_7_unbalances_charge_and_the_source_assertion_stays(spec):
    d = load_doc(ELECTRO)
    rec = pgraph.validate(d, spec_of(d)).balance["records"][0]
    assert (rec["atoms"]["status"], rec["charge"]["status"]) == ("balanced", "balanced")
    _participant(d, "electron")["props"]["coefficient"] = 7
    rep = pgraph.validate(d, spec_of(d))
    assert rep.errors == []
    rec = rep.balance["records"][0]
    assert rec["source_says"] == "balanced" and rec["atoms"] == {"status": "balanced"}
    assert rec["charge"] == {"status": "unbalanced", "reactants": -8, "products": -9}
    assert [w["message"] for w in rep.warnings] == [
        "charge balance: its recorded participants do not balance (charge -8 in the reactants and -9 in the products); "
        "the source says balanced (balance_status), which is kept; they stay as recorded"]
    assert next(n for n in d["nodes"] if n["label"] == "Reaction")["props"]["balance_status"] == "balanced"


def test_a_charge_not_stated_leaves_only_the_charge_balance_not_checkable(spec):
    d = load_doc(ELECTRO)
    del next(n for n in d["nodes"] if n["id"] == "ex:df-electro/species/water")["props"]["charge"]
    rep = pgraph.validate(d, spec_of(d))
    rec = rep.balance["records"][0]
    assert rec["atoms"] == {"status": "balanced"}
    assert rec["charge"] == {"status": "not_checkable", "missing": [
        "the charge of ex:df-electro/species/water is not stated (a species is never taken as neutral)"]}
    assert rep.warnings == [] and rep.errors == []
    # its formula H2O writes no charge, and no charge is assumed from it
    assert next(n for n in d["nodes"] if n["id"] == "ex:df-electro/species/water")["props"]["formula"] == "H2O"


def test_a_composition_not_known_leaves_only_the_atom_balance_not_checkable(spec):
    d = load_doc(ELECTRO)
    p = next(n for n in d["nodes"] if n["id"] == "ex:df-electro/species/nitrate")["props"]
    del p["elemental_composition"]
    rec = pgraph.validate(d, spec_of(d)).balance["records"][0]
    assert rec["atoms"]["status"] == "balanced"                      # its formula NO3- with its charge -1 reads as N O3
    p["formula"] = "nitrate"
    rec = pgraph.validate(d, spec_of(d)).balance["records"][0]
    assert rec["atoms"]["status"] == "not_checkable" and "nitrate" in rec["atoms"]["missing"][0]
    assert rec["charge"]["status"] == "balanced"


def test_a_free_site_or_a_coverage_not_recorded_does_not_block_a_balance(doc, spec):
    rec = {r["record"]: r for r in pgraph.validate(doc, spec_of(doc)).balance["records"]}
    step = rec[f"{P}/step/o2-dissociation"]                    # O2* -> 2 O*: no free site listed, no coverage needed
    assert step["atoms"]["status"] == step["charge"]["status"] == "balanced"
    d = copy.deepcopy(doc)                                      # a free site listed as a species with no atoms
    d["nodes"].append({"id": f"{P}/species/site", "label": "ChemicalSpecies",
                       "props": {"name": "free site", "formula": "*", "charge": 0, "origin": "synthetic"}})
    d["links"].append({"id": f"{P}/link/site", "type": "HAS_PARTICIPANT", "source": f"{P}/reaction/o-adsorption-from-o2",
                       "target": f"{P}/species/site", "props": {"role": "reactant", "coefficient": 1, "origin": "synthetic"}})
    rec = {r["record"]: r for r in pgraph.validate(d, spec_of(d)).balance["records"]}
    assert rec[f"{P}/reaction/o-adsorption-from-o2"]["atoms"]["status"] == "balanced"


def test_two_statements_of_one_coefficient_that_disagree_are_not_checkable(spec):
    d = load_doc(ELECTRO)
    e = copy.deepcopy(_participant(d, "water"))
    e["id"], e["props"]["coefficient"] = "ex:df-electro/link/water-again", 5
    d["links"].append(e)
    rec = pgraph.validate(d, spec_of(d)).balance["records"][0]
    assert rec["atoms"]["status"] == rec["charge"]["status"] == "not_checkable"
    assert "ex:df-electro/species/water has 2 coefficients among the reactants (5, 6)" in rec["atoms"]["missing"]


@pytest.mark.parametrize("formula, charge, comp", [
    ("H2O", None, {"H": 2, "O": 1}), ("H2O(g)", 0, {"H": 2, "O": 1}), ("*OH", None, {"H": 1, "O": 1}),
    ("OH-", None, {"H": 1, "O": 1}), ("NO3-", -1, {"N": 1, "O": 3}), ("NO3-", None, None), ("SO4^2-", None, {"S": 1, "O": 4}),
    ("SO4(2-)", -2, {"S": 1, "O": 4}), ("Cu2+", 2, {"Cu": 1}), ("Cu2+", 1, {"Cu": 2}), ("H2+", 1, {"H": 2}),
    ("Fe(OH)3", 0, {"Fe": 1, "O": 3, "H": 3}), ("CuSO4·5H2O", 0, {"Cu": 1, "S": 1, "O": 9, "H": 10}), ("e-", -1, {}),
    ("*", 0, {}), ("Xy2", 0, None), ("NO3-", 0, None), ("SO4^2-", -1, None)])
def test_a_formula_is_read_only_where_it_says_one_thing(formula, charge, comp):
    assert stoichiometry.parse_formula(formula, charge)[0] == comp


def test_a_formula_that_contradicts_the_stated_composition_is_reported(spec):
    d = load_doc(ELECTRO)
    next(n for n in d["nodes"] if n["id"] == "ex:df-electro/species/ammonia")["props"]["elemental_composition"] = {"N": 1, "H": 2}
    rep = pgraph.validate(d, spec_of(d))
    msgs = [w["message"] for w in rep.warnings]
    assert "its formula 'NH3' reads as H3 N, but its elemental_composition is H2 N; a balance uses the elemental_composition" in msgs
    assert any(m.startswith("atom balance: its recorded participants do not balance (H 12 in the reactants and 11 in the "
                            "products)") for m in msgs)


# ---------------------------------------------------------------- the contracts, the schema and the migration
def test_the_contracts_say_what_each_energy_is_compared_by_and_shows(spec):
    c = quantities.contracts(spec)
    for kind in ("reaction_energy", "reaction_enthalpy", "reaction_free_energy", "activation_energy", "activation_free_energy"):
        assert [x["context"] for x in c.kinds[kind]["compare_by"]] == ["process", "level_of_theory", "charge_treatment"]
    assert [x["context"] for x in c.kinds["electronic_energy"]["compare_by"]] == ["structure", "level_of_theory", "charge_treatment"]
    assert [x["context"] for x in c.kinds["apparent_activation_energy"]["compare_by"]] == ["species"]
    assert c.warned("reaction_free_energy") == {"temperature"} and c.warned("reaction_energy") == set()
    assert c.contexts["charge_treatment"]["unstated"] == "group" and c.contexts["level_of_theory"]["unstated"] == "exclude"
    assert spec["context_targets"]["process"]["targets"] == ["Reaction", "ElementaryStep"]
    step = spec["nodes"]["ElementaryStep"]["properties"]
    assert (step["activation_energy"]["quantity"], step["reaction_energy"]["quantity"]) == ("activation_energy", "reaction_energy")
    assert spec["edges"]["RATE_CONTROL"]["properties"]["degree_of_rate_control"]["quantity"] == "degree_of_rate_control"
    d = quantities.describe_binding(c, step["activation_energy"])
    assert "compared by process, level_of_theory, charge_treatment" in d and "shows its producer's electrode_potential" in d


def test_a_malformed_producer_context_or_shown_property_never_loads():
    block = copy.deepcopy(pgraph.load_spec(GRAPH_MANIFEST)["quantities"])
    bad = copy.deepcopy(block)
    del bad["contexts"]["level_of_theory"]["property"]
    with pytest.raises(ScaleError, match="names the property of the producer it reads"):
        quantities.Contracts(bad)
    bad = copy.deepcopy(block)
    bad["contexts"]["charge_treatment"]["unstated"] = "assume"
    with pytest.raises(ScaleError, match="unstated is exclude or group"):
        quantities.Contracts(bad)
    bad = copy.deepcopy(block)
    bad["kinds"]["reaction_free_energy"]["shows"] = [{"property": "temperature", "warn": "yes"}]
    with pytest.raises(ScaleError, match="shows\\[0\\]"):
        quantities.Contracts(bad)
    bad = copy.deepcopy(block)
    bad["contexts"]["process"]["read_from"] = ["basis"]
    with pytest.raises(ScaleError, match="an open context reads target, record, producer only"):
        quantities.Contracts(bad)


def test_an_enum_a_context_is_read_from_names_its_values(spec):
    s = copy.deepcopy(spec)
    s["nodes"]["Computation"]["properties"]["charge_treatment"]["values"].append("fixed_fermi_level")
    with pytest.raises(ScaleError, match="fixed_fermi_level"):
        quantities.check_bindings(s)


def test_the_change_is_breaking_and_says_why(spec):
    from conftest import spec_at
    base = spec_at("0.6.0")
    d = diff_specs(base, spec)
    assert tier(d) == 3
    assert any("ElementaryStep.activation_energy holds quantity activation_energy" in x for x in d["narrowed"])
    assert any(x.startswith("context_targets.process") for x in d["narrowed"])
    assert {"quantities.kinds.reaction_energy", "quantities.contexts.level_of_theory"} <= set(d["added"])


def test_migration_rewrites_nothing_and_stops_on_a_value_it_cannot_map(spec):
    d = load_doc(ELECTRO)
    old = copy.deepcopy(d)
    old["graph"]["schema_version"] = "0.6.0"
    new, report = pgraph_migrate.raise_version(old, spec["version"], spec)
    step = next(s for s in report["steps"] if s["from"] == "0.6.0")
    assert new["nodes"] == d["nodes"] and new["links"] == d["links"] and step["changes"] == []
    old["nodes"].append({"id": "ex:df-electro/step/x", "label": "ElementaryStep",
                         "props": {"name": "x", "origin": "synthetic",
                                   "activation_energy": {"status": "present", "value": 0.7, "unit": "V"}}})
    with pytest.raises(ScaleError, match="ex:df-electro/step/x.activation_energy: 'V' is electric_potential"):
        pgraph_migrate.raise_version(old, spec["version"], spec)


def test_the_computational_recipe_names_only_labels_links_and_properties_the_schema_declares(spec):
    """The links and the Computation and StructureModel properties the recipe on computational details names in code are
    declared by the schema the example pins."""
    import re
    text = (REPO / "skills/curate-corpus/references/recipes.md").read_text(encoding="utf-8")
    section = text[text.index("## Computational details"):text.index("## Reactor, bed and catalyst-body keys")]
    links = set(re.findall(r"`([A-Z][A-Z_]{3,})`", section)) - {"RPBE"}           # a functional's name is a value
    assert links and not sorted(x for x in links if x not in spec["edges"])
    props = set(spec["nodes"]["Computation"]["properties"]) | set(spec["nodes"]["StructureModel"]["properties"]) \
        | set(spec["nodes"]["CatalystState"]["properties"]) | set(spec["edges"]["REPRESENTS"]["properties"]) \
        | set(spec["value"]["fields"])
    for p in ("computation_kind", "level_of_theory", "charge_treatment", "dispersion", "hubbard_u", "spin_treatment",
              "solvation", "settings", "configuration", "execution_environment", "stored_in", "representation", "aspect",
              "assumptions", "unresolved_target", "produced_by"):
        assert p in props and f"`{p}`" in section, p
