"""Quantity contracts (scale-catal 0.3.0): a value's unit read for its kind's dimension, the contexts a scientific
comparison needs, the normalization reference, and what a change of a contract does to the schema's version.

The acceptance cases of the change, each a test below: RHE and SHE potentials stay retrievable but are never ranked
together without a common reference or an evidenced conversion; geometric-area and ECSA current densities stay apart
when no value states a basis; a basis that contradicts its record is diagnosed; a temperature in kg is flagged and mol/L
is a concentration, never a fraction; units and bases stated apart stay apart; a missing normalization stays unknown; a
normalization reference is validated and withheld with what it names; and a change of a contract's meaning is detected
by the schema diff. Every document here is a public synthetic example, or one built in memory from it."""

import copy

import pytest

from conftest import EXAMPLES, GRAPH_MANIFEST, HEAD_VERSION, spec_at, spec_of
from scale import pgraph, pgraph_migrate, pgraph_query, quantities, schema_change
from scale.util import ScaleError, load_doc

CMP = EXAMPLES / "scale-catal/comparison-examples/current-density-comparison.json"
ELECTRO = EXAMPLES / "scale-catal/driving-force-examples/electro.json"


def V(value, unit, **kw) -> dict:
    return {"status": "present", "value": value, "unit": unit, **kw}


@pytest.fixture(scope="module")
def spec():
    return pgraph.load_spec(GRAPH_MANIFEST)


@pytest.fixture(scope="module")
def qc(spec):
    return quantities.contracts(spec)


def _node(doc: dict, local: str) -> dict:
    return next(n for n in doc["nodes"] if n["id"].endswith("/" + local))


def _test(doc: dict) -> dict:
    return next(n for n in doc["nodes"] if n["label"] == "CatalyticTest")


def _errors(doc) -> list[str]:
    """The errors of a document under the version it pins (a later schema change leaves these tests meaningful)."""
    return [e["message"] for e in pgraph.validate(doc, spec_of(doc)).errors]


def _warnings(doc) -> list[str]:
    return [w["message"] for w in pgraph.validate(doc, spec_of(doc)).warnings]


def _run(doc, plan) -> dict:
    return pgraph_query.run(doc, spec_of(doc), plan)


# ------------------------------------------------------------------------------------------ the unit vocabulary
@pytest.mark.parametrize("unit, dimension", [
    ("K", "temperature"), ("°C", "temperature"), ("deg C", "temperature"), ("kg", "mass"),
    ("atm", "pressure"), ("kg/cm2", "pressure"), ("lb./sq. in.", "pressure"), ("mm Hg", "pressure"), ("MPa", "pressure"),
    ("lbf/in2 (gauge)", "pressure"), ("V", "electric_potential"), ("mA/cm2", "current_density"), ("mA cm⁻²", "current_density"),
    ("A/g", "specific_current"), ("%", "dimensionless"), ("mol %", "dimensionless"), ("atom per 100 atoms Cu", "dimensionless"),
    ("mol/L", "amount_concentration"), ("mM", "amount_concentration"), ("mg/cu.m", "mass_concentration"),
    ("L/h", "volumetric_flow"), ("lb mol/h", "molar_flow"), ("cu. m. per hour", "volumetric_flow"), ("Nm3/hr", "volumetric_flow"),
    ("1/h", "frequency"), ("mL/(g*h)", "volume_per_mass_time"), ("g/kWh", "mass_per_energy"), ("mg/cm2", "mass_per_area"),
])
def test_a_unit_is_read_for_its_dimension(qc, unit, dimension):
    r = qc.read_unit(unit, ("pressure_convention", "potential_reference", "current_normalization", "flow_reference"))
    assert r.read and qc.names[r.vector] == dimension, (unit, r)


@pytest.mark.parametrize("unit, context, value", [
    ("barg", "pressure_convention", "gauge"), ("psia", "pressure_convention", "absolute"), ("bar (g)", "pressure_convention", "gauge"),
    ("atm abs", "pressure_convention", "absolute"), ("V vs RHE", "potential_reference", "rhe"),
    ("V vs. Ag/AgCl", "potential_reference", "ag_agcl"), ("mA/cm2_ECSA", "current_normalization", "ecsa"),
    ("sccm", "flow_reference", "standard"), ("mL(STP)/min", "flow_reference", "stp"), ("wt.%", "fraction_basis", "mass"),
])
def test_a_unit_can_state_a_context(qc, unit, context, value):
    assert qc.read_unit(unit, (context,)).contexts.get(context) == value


@pytest.mark.parametrize("unit", ["L/h per 3 cc catalyst", "kmol/uur", "m3 gas/kg catalyst", "× equilibrium concentration", ""])
def test_a_word_the_vocabulary_does_not_hold_leaves_the_unit_unread(qc, unit):
    assert not qc.read_unit(unit).read                       # never guessed: catalyst, uur, exit gas


# ------------------------------------------------------------------------------------------ the loader
def test_the_contracts_are_the_kernels_compiled_by_the_loader_and_part_of_the_spec_document(spec):
    assert spec["version"] == HEAD_VERSION and isinstance(spec["quantities"], dict)
    assert "quantities" in pgraph.spec_document(spec)       # the spec digest names the contracts
    d = spec["nodes"]["CatalyticTest"]["properties"]
    assert d["temperature"]["quantity"] == "temperature" and d["electrode_potential"]["context"] == {
        "potential_reference": "reference_scale"}
    assert spec["edges"]["HAS_COMPONENT"]["properties"]["concentration"]["quantity"] == "concentration"
    assert spec["value"]["fields"]["normalized_by"]["type"] == "record_ref"


@pytest.mark.parametrize("change, error", [
    (lambda q: q["kinds"]["temperature"].__setitem__("dimensions", ["heat"]), "names the dimension 'heat'"),
    (lambda q: q["kinds"]["pressure"].__setitem__("compare_by", ["altitude"]), "names a declared context"),
    (lambda q: q["units"]["stating"]["barg"].__setitem__("pressure_convention", "relative"), "is not a value of a declared context"),
    (lambda q: q["units"]["prefixed"].__setitem__("°C", "temperature"), "declares the unit symbol '°C' twice"),
    (lambda q: q["dimensions"].__setitem__("speed", "L T-1 X"), "is not a dimension formula"),
])
def test_a_malformed_contract_never_loads(spec, change, error):
    block = copy.deepcopy(spec["quantities"])
    change(block)
    with pytest.raises(ScaleError, match=error):
        quantities.check_block(block)


@pytest.mark.parametrize("change, error", [
    (lambda s: s["nodes"]["CatalyticTest"]["properties"]["temperature"].__setitem__("quantity", "warmth"), "not a kind"),
    (lambda s: s["nodes"]["CatalyticTest"]["properties"]["test_label"].__setitem__("quantity", "temperature"), "binds a value"),
    (lambda s: s["nodes"]["CatalyticTest"]["properties"]["electrode_potential"].__setitem__(
        "context", {"potential_reference": "control_mode"}), "name no value of the context potential_reference"),
    (lambda s: s["nodes"]["CatalyticTest"]["properties"]["temperature"].__setitem__(
        "context", {"potential_reference": "reference_scale"}), "is not one temperature compares by"),
])
def test_a_binding_names_what_exists(spec, change, error):
    s = copy.deepcopy(spec)
    change(s)
    with pytest.raises(ScaleError, match=error):
        quantities.check_bindings(s)


def test_frozen_versions_carry_no_contracts_and_their_documents_read_as_before():
    old = _old_electrolyte()                                  # pins 0.2.1: its concentrations stored as fractions
    s = spec_of(old)
    assert "quantities" not in s and quantities.contracts(s) is None
    _test(old)["props"]["temperature"] = V(523, "kg")         # nothing reads it under the version the document pins
    assert pgraph.validate(old, s).errors == []


# ------------------------------------------------------------------------------------------ validation
def test_a_temperature_in_kg_is_flagged_and_mol_per_litre_is_a_concentration_never_a_fraction(spec):
    d = load_doc(ELECTRO)
    assert quantities.contracts(spec_of(d)) is not None and _errors(d) == []   # the corrected electrolyte
    conc = [e["props"]["concentration"] for e in d["links"] if e["type"] == "HAS_COMPONENT"]
    assert conc and all(c["unit"] == "mol/L" for c in conc)
    _test(d)["props"]["temperature"] = V(298, "kg")
    link = next(e for e in d["links"] if e["type"] == "HAS_COMPONENT")
    link["props"]["fraction"] = link["props"].pop("concentration")
    errs = _errors(d)
    assert any("temperature: unit 'kg' is mass (M), not a dimension of temperature" in m for m in errs), errs
    assert any("fraction: unit 'mol/L' is amount_concentration" in m and "composition_fraction" in m for m in errs), errs
    assert len(errs) == 2


def test_contradictory_value_and_sibling_normalizations_are_diagnosed(spec):
    d = load_doc(ELECTRO)
    t = _test(d)
    t["props"]["current_density"] = V(-120, "mA/cm2", basis="ECSA")              # its record says geometric_area
    assert any("contradictory current_normalization" in m and "says ecsa" in m and "says geometric_area" in m
               for m in _warnings(d))
    t["props"]["current_density"] = V(-1.2, "A/g")                               # per mass, its record per area
    assert any("its unit (A/g, specific_current" in m and "says mass" in m and "says geometric_area" in m
               for m in _warnings(d))
    t["props"]["current_density"] = V(-120, "mA/cm2", basis="geometric area")
    t["props"]["electrode_potential"] = V(-0.3, "V vs SHE")                      # the unit's scale, not the record's
    assert any("contradictory potential_reference" in m for m in _warnings(d))


def test_an_evidenced_conversion_keeps_its_own_context_without_a_diagnostic(spec):
    d = load_doc(CMP)
    conv = _node(d, "test/agcl-converted")["props"]
    assert conv["reference_scale"] == "ag_agcl" and conv["electrode_potential"]["basis"] == "RHE"
    assert _errors(d) == [] and not [m for m in _warnings(d) if "potential_reference" in m]
    conv["electrode_potential"].pop("produced_by")
    conv["electrode_potential"]["origin"] = "reported"                         # no longer evidenced: two scales, one value
    assert any("contradictory potential_reference" in m for m in _warnings(d))


def test_a_unit_the_vocabulary_cannot_read_is_reported_once_per_property_and_unit(spec):
    d = load_doc(ELECTRO)
    for t in [_test(d), copy.deepcopy(_test(d))]:
        t["props"]["temperature"] = V(25, "degrees Réaumur")
    d["nodes"].append({**_test(d), "id": _test(d)["id"] + "-b", "props": {**_test(d)["props"]}})
    d["nodes"][-1]["props"].pop("evidence")
    w = [m for m in _warnings(d) if "Réaumur" in m]
    assert len(w) == 1 and "(2 values)" in w[0] and "not checked" in w[0]
    assert _errors(d) == []                               # reported, not rejected


def test_an_unusual_reported_percentage_is_advised_and_stays_as_reported(spec):
    d = load_doc(ELECTRO)
    fe = _test(d)["props"]["faradaic_efficiency"][0]
    fe["value"] = 104
    assert any("104 % is above 100 % for a faradaic_efficiency" in m for m in _warnings(d))
    assert _test(d)["props"]["faradaic_efficiency"][0]["value"] == 104
    p = load_doc(EXAMPLES / "scale-catal/example.json")         # relative molar parts in the unit 1 are not percentages
    assert pgraph.validate(p, spec_of(p)).warnings == []


def test_a_variable_brings_its_kinds_contract_to_its_unit_and_its_values(spec):
    d = load_doc(EXAMPLES / "scale-catal/driving-force-examples/photoelectro.json")
    var = next(n for n in d["nodes"] if n["label"] == "Variable" and n["props"].get("quantity_kind") == "electric_potential")
    var["props"]["unit"] = "mA"
    assert any("unit: 'mA' is electric_current" in m for m in _errors(d))
    var["props"]["unit"] = "V"
    _test(d)["props"].setdefault("results", {})["potential_held"] = V(1.2, "kg", variable=var["id"])
    assert any("results.potential_held: unit 'kg' is mass" in m for m in _errors(d))


def test_a_normalization_reference_is_validated(spec):
    d = load_doc(CMP)
    assert _errors(d) == []
    t = _node(d, "test/rhe-ecsa")["props"]["current_density"]
    assert t["normalized_by"]["path"] == "/electrochemically_active_area"
    t["normalized_by"]["path"] = "/ecsa"                                               # no such property
    assert any("normalized_by: ex:cmp/electrode/ag-on-cp/ecsa does not resolve to a property" in m for m in _errors(d))
    t["normalized_by"] = {"record": "ex:cmp/electrode/missing"}
    assert any("does not resolve to a node or link" in m for m in _errors(d))
    t["normalized_by"] = {"record": "ex:cmp/electrode/ag-on-cp", "path": "/substrate"}  # text, not a value
    assert any("is not a value object" in m for m in _errors(d))
    t["normalized_by"] = {"record": "ex:cmp/electrode/ag-on-cp", "path": "/geometric_area"}
    assert _errors(d) == []
    _node(d, "test/rhe-ecsa")["props"]["temperature"]["normalized_by"] = {"record": "ex:cmp/electrode/ag-on-cp"}
    assert any("temperature is not divided by one" in m for m in _errors(d))


# ------------------------------------------------------------------------------------------ queries
RANK = {"match": {"label": "CatalyticTest", "as": "test", "where": [{"prop": "current_density", "op": "exists"}]},
        "return": ["test.name", "test.reference_scale", "test.current_normalization"],
        "order_by": [{"var": "test", "prop": "electrode_potential"}]}


def _names(res) -> list[str]:
    return [r["values"]["test.name"] for r in res["rows"]]


def _left(res) -> dict:
    return {x["record"].rsplit("/", 1)[-1]: pgraph_query.reason_code(x["reason"]) for x in res["excluded"]}


def test_identical_rhe_and_she_potentials_stay_retrievable_but_are_never_ranked_together(spec):
    d = load_doc(CMP)
    ordinary = _run(d, RANK)
    assert len(ordinary["rows"]) == 8 and "comparison" not in ordinary                 # retrieved as reported
    assert any("electrode_potential was compared across contexts" in m and "potential_reference she" in m
               for m in ordinary["limitations"])
    sci = _run(d, {**RANK, "comparison": "scientific"})
    by = {r["values"]["test.name"]: r["comparison_group"] for r in sci["rows"]}
    rhe, she = by["Ag, -0.8 V vs RHE, per geometric area"], by["Ag, -0.8 V vs SHE, per geometric area (the same numbers on another scale)"]
    assert rhe != she                                                                    # two groups: no single ranking
    assert by["Ag, -1.2 V vs Ag/AgCl, converted to RHE"] == rhe                           # the evidenced conversion joins RHE
    assert _left(sci)["scale-unknown"] == "missing_context"
    common = _run(d, {**RANK, "comparison": "scientific",
                                        "order_by": [{"var": "test", "prop": "electrode_potential",
                                                      "context": {"potential_reference": "rhe"}}]})
    assert _left(common)["she-geo"] == "incompatible_context" and len({r["comparison_group"] for r in common["rows"]}) == 1
    assert "Ag, -1.2 V vs Ag/AgCl, converted to RHE" in _names(common)


def test_geometric_and_ecsa_current_densities_stay_apart_without_a_value_level_basis(spec):
    d = load_doc(CMP)
    for local in ("rhe-geo-1", "rhe-ecsa"):
        assert "basis" not in _node(d, f"test/{local}")["props"]["current_density"]
    plan = {**RANK, "comparison": "scientific", "order_by": [{"var": "test", "prop": "current_density"}]}
    res = _run(d, plan)
    groups = {g["group"]: g["compared_on"]["test.current_density"]["context"]["current_normalization"]
              for g in res["comparison"]["groups"]}
    assert set(groups.values()) == {"geometric_area", "ecsa"}
    where = {**plan, "order_by": [], "where": [{"var": "test", "prop": "current_density", "op": "le", "value": -2, "unit": "mA/cm2",
                                                "context": {"current_normalization": "geometric_area"}}]}
    res = _run(d, where)
    assert "Ag, -0.8 V vs RHE, per ECSA" not in _names(res) and _left(res)["rhe-ecsa"] == "incompatible_context"
    plain = {k: v for k, v in where["where"][0].items() if k != "context"}
    ordinary = _run(d, {**where, "comparison": "ordinary", "where": [plain]})
    assert {"Ag, -0.8 V vs RHE, per ECSA", "Ag, -0.8 V vs RHE, per geometric area"} <= set(_names(ordinary))   # as reported


def test_a_contradiction_or_a_missing_normalization_is_left_out_never_assumed(spec):
    d = load_doc(CMP)
    res = _run(d, {**RANK, "comparison": "scientific", "order_by": [{"var": "test", "prop": "current_density"}]})
    left = _left(res)
    assert left["contradictory"] == "incompatible_context" and left["normalization-unknown"] == "missing_context"
    why = next(x["reason"] for x in res["excluded"] if x["record"].endswith("/normalization-unknown"))
    assert "names no current_normalization" in why                         # not read as geometric
    only = copy.deepcopy(d)
    only["nodes"] = [n for n in only["nodes"] if n["label"] != "CatalyticTest"
                     or n["id"].endswith(("/normalization-unknown", "/contradictory"))]
    only["links"] = [e for e in only["links"] if e["source"] in {n["id"] for n in only["nodes"]}
                     and e["target"] in {n["id"] for n in only["nodes"]}]
    res = _run(only, {**RANK, "comparison": "scientific", "order_by": [{"var": "test", "prop": "current_density"}]})
    assert res["status"] == "missing_context" and res["rows"] == []


def test_explicitly_different_units_and_bases_stay_apart_in_both_modes(spec):
    d = load_doc(CMP)
    t = _node(d, "test/rhe-geo-2")["props"]
    t["current_density"] = V(-125, "A/m2")
    for mode in ("ordinary", "scientific"):
        res = _run(d, {**RANK, "comparison": mode, "order_by": [], "where": [
            {"var": "test", "prop": "current_density", "op": "le", "value": -1, "unit": "mA/cm2"}]})
        assert "Ag, -0.8 V vs RHE, per geometric area, second electrode" not in _names(res)
        assert _left(res)["rhe-geo-2"] == "incompatible_unit"
    p = load_doc(EXAMPLES / "scale-catal/driving-force-examples/photothermo.json")
    sel = next(n for n in p["nodes"] if n["label"] == "CatalyticTest" and "selectivity" in n["props"])
    sel["props"]["selectivity"]["basis"] = "carbon"
    for mode in ("ordinary", "scientific"):
        res = _run(p, {"comparison": mode, "match": {"label": "CatalyticTest", "as": "t"},
                                         "where": [{"var": "t", "prop": "selectivity", "op": "ge", "value": 50, "unit": "%"}],
                                         "return": ["t.name"]})
        assert _left(res)[sel["id"].rsplit("/", 1)[-1]] == "other_basis"          # carbon basis, the filter none


def test_a_fraction_compares_no_concentration_and_a_concentration_compares_in_its_unit(spec):
    d = load_doc(ELECTRO)
    plan = {"comparison": "scientific", "match": {"label": "Electrolyte", "as": "el"},
            "steps": [{"from": "el", "edge": "HAS_COMPONENT", "to": "ChemicalSpecies", "as": "sp", "edge_as": "c"}],
            "where": [{"var": "c", "prop": "fraction", "op": "ge", "value": 0.1, "unit": "mol/L"}], "return": ["sp.name"]}
    with pytest.raises(ScaleError, match="compares a composition_fraction in 'mol/L', which is amount_concentration"):
        _run(d, plan)
    res = _run(d, {**plan, "where": [{"var": "c", "prop": "concentration", "op": "ge", "value": 0.1, "unit": "mol/L"}]})
    assert res["status"] == "answered" and len(res["rows"]) == 2


def test_an_efficiency_is_ranked_for_the_species_it_counts(spec):
    d = load_doc(CMP)
    co = "ex:cmp/species/co"
    plan = {"comparison": "scientific", "match": {"label": "CatalyticTest", "as": "test",
                                                  "where": [{"prop": "faradaic_efficiency", "op": "exists"}]},
            "return": ["test.name"], "order_by": [{"var": "test", "prop": f"faradaic_efficiency.*[target={co}]", "desc": True}]}
    res = _run(d, plan)
    assert [r["compared"][f"test.faradaic_efficiency.*[target={co}]"]["context"] for r in res["rows"]] == [{"species": co}] * 3
    assert res["rows"][0]["values"]["test.name"] == "Ag, -0.8 V vs RHE, per geometric area, second electrode"   # 83 %
    t = _node(d, "test/rhe-geo-1")["props"]
    t["faradaic_efficiency"].append(V(12, "%", target="ex:cmp/species/water"))   # a second product: name the one ranked
    res = _run(d, {**plan, "order_by": [{"var": "test", "prop": "faradaic_efficiency.*", "desc": True}]})
    assert _left(res)["rhe-geo-1"] == "missing_context"


def test_a_normalization_reference_goes_with_the_value_it_names(spec):
    d = load_doc(CMP)
    plan = {**RANK, "comparison": "scientific", "order_by": [{"var": "test", "prop": "current_density"}]}
    res = _run(d, plan)
    row = next(r for r in res["rows"] if r["values"]["test.name"] == "Ag, -0.8 V vs RHE, per ECSA")
    assert row["compared"]["test.current_density"]["denominator"] == {
        "record": "ex:cmp/electrode/ag-on-cp", "path": "/electrochemically_active_area", "origin": "measured"}
    gone = copy.deepcopy(d)                                    # the denominator not reported: the value is not compared
    _node(gone, "electrode/ag-on-cp")["props"]["electrochemically_active_area"] = {"status": "not_reported",
                                                                                  "missing_reason": "not_stated_in_source"}
    res = _run(gone, plan)
    assert _left(res)["rhe-ecsa"] == "missing_context"
    assumed = copy.deepcopy(d)
    _node(assumed, "electrode/ag-on-cp")["props"]["electrochemically_active_area"]["origin"] = "assumed"
    res = _run(assumed, plan)
    assert any("assumed denominator" in m for m in res["limitations"])


def test_withholding_what_a_value_is_divided_by_withholds_the_value(spec):
    d = load_doc(CMP)
    electrode = _node(d, "electrode/ag-on-cp")
    electrode["props"]["stewardship"] = {"access": "institution", "contributed_by": ["ex:cmp/org/lab"]}
    view = pgraph.filter_for(d, [], "2026-10-18")             # the public: the electrode is withheld
    t = _node(view, "test/rhe-ecsa")["props"]["current_density"]
    assert t == {"status": "not_reported", "missing_reason": "withheld"}
    assert "ex:cmp/electrode/ag-on-cp" not in str(_node(view, "test/rhe-ecsa"))
    assert _node(view, "test/rhe-geo-1")["props"]["current_density"]["value"] == -10.2   # one that names nothing stays
    res = _run(view, {**RANK, "comparison": "scientific", "order_by": [{"var": "test", "prop": "current_density"}]})
    assert _left(res)["rhe-ecsa"] == "withheld"


def test_a_path_into_a_kept_record_follows_what_was_withheld_in_it():
    d = {"directed": True, "multigraph": True, "graph": {"graph_id": "ex:t/graph"}, "nodes": [
        {"id": "ex:t/src/a", "label": "Source", "props": {}}, {"id": "ex:t/src/b", "label": "Source", "props": {}},
        {"id": "ex:t/e", "label": "Electrode", "props": {"areas": [V(1, "cm2", evidence_ids=["a"]), V(4, "cm2", evidence_ids=["b"])],
                                                          "evidence": [{"id": "a", "source": "ex:t/src/a"}, {"id": "b", "source": "ex:t/src/b"}]}},
        {"id": "ex:t/t", "label": "CatalyticTest", "props": {
            "j": V(-2, "mA/cm2", normalized_by={"record": "ex:t/e", "path": "/areas/1"}, evidence_ids=["b"]),
            "k": V(-9, "mA/cm2", normalized_by={"record": "ex:t/e", "path": "/areas/0"}, evidence_ids=["b"]),
            "evidence": [{"id": "b", "source": "ex:t/src/b"}]}}], "links": []}
    nodes, _, _, _ = pgraph._subset(d, lambda r: r["id"] != "ex:t/src/a")   # source a out: the first area is withheld
    e = next(n for n in nodes if n["id"] == "ex:t/e")["props"]
    t = next(n for n in nodes if n["id"] == "ex:t/t")["props"]
    assert e["areas"][0] == {"status": "not_reported", "missing_reason": "withheld"} and e["areas"][1]["value"] == 4
    assert t["j"]["normalized_by"]["path"] == "/areas/1"                     # withheld in its place: nothing moved
    assert t["k"] == {"status": "not_reported", "missing_reason": "withheld"}   # what it named is withheld: so is it


def test_a_record_ref_inside_a_value_is_json_text_in_the_flat_export():
    import json
    rows = [json.loads(x) for x in pgraph.to_neo4j_jsonl(load_doc(CMP)).splitlines()]
    t = next(r for r in rows if r["id"] == "ex:cmp/test/rhe-ecsa")["properties"]
    assert json.loads(t["current_density_normalized_by"]) == {"path": "/electrochemically_active_area",
                                                               "record": "ex:cmp/electrode/ag-on-cp"}
    assert all(not isinstance(v, (dict,)) for r in rows for v in r["properties"].values())


def test_comparison_plan_errors(spec):
    d = load_doc(CMP)
    bad = [({**RANK, "comparison": "strict"}, "comparison is one of"),
           ({**RANK, "order_by": [{"var": "test", "prop": "electrode_potential", "context": {"potential_reference": "rhe"}}]},
            "only `comparison: scientific` reads"),
           ({**RANK, "comparison": "scientific", "order_by": [{"var": "test", "prop": "electrode_potential",
                                                              "context": {"potential_reference": "vs moon"}}]}, "is not one of its values"),
           ({**RANK, "comparison": "scientific", "order_by": [{"var": "test", "prop": "electrode_potential",
                                                              "context": {"elevation": "high"}}]}, "is not a context"),
           ({**RANK, "comparison": "scientific", "order_by": [], "where": [
               {"var": "test", "prop": "current_density", "op": "le", "value": -1, "unit": "mA/cm2", "basis": "geometric"}]},
            "state context instead"),
           ({**RANK, "comparison": "scientific", "order_by": [], "where": [
               {"var": "test", "prop": "temperature", "op": "le", "value": 400, "unit": "K", "context": {"potential_reference": "rhe"}}]},
            "which a temperature is not compared by"),
           ({**RANK, "comparison": "scientific", "order_by": [], "where": [
               {"var": "test", "prop": "temperature", "op": "le", "value": 400, "unit": "kg"}]}, "compares a temperature in 'kg'")]
    for plan, error in bad:
        with pytest.raises(ScaleError, match=error):
            _run(d, plan)
    old = _old_electrolyte()                                  # pins 0.2.1: no contracts
    with pytest.raises(ScaleError, match="does not have; migrate the document"):
        _run(old, {**RANK, "comparison": "scientific"})


def test_a_schemas_contracts_are_compiled_once_and_a_changed_copy_gets_its_own(spec, monkeypatch):
    """A loaded schema's contracts are hashed once, not on every query; a changed copy of the schema (a new object)
    is read afresh, and an equal copy shares the compiled contracts."""
    first = quantities.contracts(spec)
    calls, sha256 = [], quantities.hashlib.sha256
    monkeypatch.setattr(quantities.hashlib, "sha256", lambda b: calls.append(b) or sha256(b))
    assert quantities.contracts(spec) is first and not calls
    same = copy.deepcopy(spec)
    assert quantities.contracts(same) is first and len(calls) == 1
    changed = copy.deepcopy(spec)
    changed["quantities"]["kinds"]["temperature"]["dimensions"] = ["temperature", "energy"]
    other = quantities.contracts(changed)
    assert other is not first and quantities.contracts(spec) is first


# ------------------------------------------------------------------------------------------ the schema diff
def _diff(spec, change) -> dict:
    b = copy.deepcopy(spec)
    change(b)
    return schema_change.diff_specs(spec, b)


@pytest.mark.parametrize("change, key, words, tier", [
    (lambda s: s["quantities"]["kinds"]["temperature"].__setitem__("dimensions", ["temperature", "energy"]),
     "loosened", "quantities.kinds.temperature takes energy", 2),
    (lambda s: s["quantities"]["kinds"]["concentration"]["dimensions"].remove("amount_per_mass"),
     "narrowed", "quantities.kinds.concentration no longer takes amount_per_mass", 3),
    (lambda s: s["quantities"]["kinds"]["temperature"].__setitem__("compare_by", ["pressure_convention"]),
     "narrowed", "quantities.kinds.temperature is compared by pressure_convention", 3),
    (lambda s: s["quantities"]["kinds"]["pressure"].__setitem__("compare_by", []),
     "loosened", "quantities.kinds.pressure is no longer compared by pressure_convention", 2),
    (lambda s: s["quantities"]["contexts"]["potential_reference"]["values"]["she"]["terms"].append("RHE"),
     "changed", "'RHE' names rhe -> she", 3),
    (lambda s: s["quantities"]["units"]["unprefixed"].__setitem__("at", "temperature"),
     "changed", "quantities.units: at pressure -> temperature", 3),
    (lambda s: s["quantities"]["kinds"]["current_density"]["denominator"].__setitem__("dimensions", ["volume"]),
     "changed", "quantities.kinds.current_density: denominator", 3),
    (lambda s: s["nodes"]["CatalyticTest"]["properties"]["pressure"].pop("quantity"),
     "loosened", "nodes.CatalyticTest.pressure no longer holds a quantity contract (pressure)", 2),
    (lambda s: s["nodes"]["CatalyticTest"]["properties"]["duration"].__setitem__("quantity", "temperature"),
     "narrowed", "nodes.CatalyticTest.duration holds quantity temperature", 3),
    (lambda s: s["nodes"]["CatalyticTest"]["properties"]["temperature"].__setitem__("quantity", "pressure"),
     "changed", "nodes.CatalyticTest.temperature: quantity temperature -> pressure", 3),
])
def test_changing_a_contracts_meaning_is_detected_by_the_schema_diff(spec, change, key, words, tier):
    d = _diff(spec, change)
    assert any(words in x for x in d[key]), d
    assert schema_change.tier(d) == tier


def test_the_change_to_contracts_is_breaking_and_raises_the_second_number():
    before = spec_at("0.2.1")                                 # frozen, as the change found it
    after = spec_at("0.3.0")                                  # the head while it is at 0.3.0, else its frozen copy
    d = schema_change.diff_specs(before, after)
    assert "quantities" in d["added"] and "edges.HAS_COMPONENT.concentration" in d["added"] and "value.normalized_by" in d["added"]
    assert schema_change.tier(d) == 3 and schema_change.next_version("0.2.1", 3) == "0.3.0" == after["version"]
    assert pgraph.spec_sha256(before) != pgraph.spec_sha256(after)


# ------------------------------------------------------------------------------------------ migration
def _old_electrolyte() -> dict:
    """The electrolyte example as 0.2.1 wrote it: its components' concentrations stored as fractions."""
    d = load_doc(ELECTRO)
    d["graph"]["schema_version"] = "0.2.1"
    for e in d["links"]:
        if e["type"] == "HAS_COMPONENT":
            e["props"]["fraction"] = e["props"].pop("concentration")
            e["props"]["fraction_basis"] = "not_reported"
    return d


def test_migration_moves_component_concentrations_and_amounts_out_of_fraction(spec):
    old = _old_electrolyte()
    feed = next(e for e in old["links"] if e["type"] == "HAS_COMPONENT")
    new, rep = pgraph_migrate.raise_version(old, HEAD_VERSION, spec)
    changes = next(st for st in rep["steps"] if st["from"] == "0.2.1")["changes"]
    assert len(changes) == 2 and all("-> concentration" in c and "fraction_basis not_reported dropped" in c for c in changes)
    moved = next(e for e in new["links"] if e["id"] == feed["id"])["props"]
    assert "fraction" not in moved and "fraction_basis" not in moved
    assert moved["concentration"] == feed["props"]["fraction"]                                    # the value object whole
    assert new == load_doc(ELECTRO) | {"graph": {**load_doc(ELECTRO)["graph"], "schema_version": HEAD_VERSION}}
    assert pgraph.validate(new, spec_of(new)).errors == []
    old = _old_electrolyte()
    link = next(e for e in old["links"] if e["type"] == "HAS_COMPONENT")
    link["props"]["fraction"] = V(5, "g")
    new, rep = pgraph_migrate.raise_version(old, HEAD_VERSION, spec)
    assert next(e for e in new["links"] if e["id"] == link["id"])["props"]["amount"] == V(5, "g")


def test_migration_stops_where_it_cannot_map_a_value(spec):
    old = _old_electrolyte()
    link = next(e for e in old["links"] if e["type"] == "HAS_COMPONENT")
    link["props"]["concentration"] = V(0.2, "mol/L")              # a concentration curated already beside the fraction
    with pytest.raises(ScaleError, match="holds concentration already: the step cannot move it there"):
        pgraph_migrate.raise_version(old, HEAD_VERSION, spec)
    old = _old_electrolyte()
    _test(old)["props"]["temperature"] = V(298, "kg")
    with pytest.raises(ScaleError, match=r"cannot map values .*temperature: 'kg' is mass"):
        pgraph_migrate.raise_version(old, HEAD_VERSION, spec)
    with pytest.raises(ScaleError, match="needs the target schema"):
        pgraph_migrate.raise_version(_old_electrolyte(), HEAD_VERSION)


def test_describe_shows_each_propertys_contract_and_the_kinds(spec):
    out = pgraph.describe(spec, ["CatalyticTest", "HAS_COMPONENT"])
    assert "quantity current_density [current_density, specific_current]; compared by current_normalization" in \
        out["labels"]["CatalyticTest"]["properties"]["current_density"]
    assert "quantity concentration" in out["edges"]["HAS_COMPONENT"]["properties"]["concentration"]
    full = pgraph.describe(spec)
    assert full["quantity_kinds"]["electrode_potential"] == {"dimensions": ["electric_potential"],
                                                            "compared_by": ["potential_reference"]}


def test_the_comparison_example_is_built_reproducibly(tmp_path):
    """The builder writes the example for the head version; the committed one, moved to the head along the registered
    steps (nothing, while it pins it), is what it writes."""
    import shutil
    import subprocess
    import sys
    from conftest import REPO
    from scale.util import write_canonical
    work = tmp_path / "cmp"
    shutil.copytree(CMP.parent, work)
    subprocess.run([sys.executable, str(work / "build_examples.py")], check=True, capture_output=True, cwd=REPO)
    doc = load_doc(CMP)
    if doc["graph"]["schema_version"] != HEAD_VERSION:
        doc = pgraph_migrate.raise_version(doc, HEAD_VERSION, pgraph.load_spec(GRAPH_MANIFEST))[0]
    write_canonical(tmp_path / "want.json", doc)
    assert (work / CMP.name).read_bytes() == (tmp_path / "want.json").read_bytes()
