"""Product measurements (scale-catal 0.4.0): results that the metric, the product, the assay, the phase and the interval
identify (Experiment.result_values), and queries that bind one result across every filter, returned value and its
evidence.

The acceptance cases of the change, each a test below: a yield threshold never passes on a selectivity; two assays never
satisfy two conditions meant for one bound result; the returned value, producer and evidence are the entry's that
satisfied the query; an ammonia query leaves out a hydrogen-only result and a source is never a product; repeated assays
stay distinct and an ambiguous repetition is diagnosed, never averaged; a reference keeps naming its result through
reordering and filtering, a withheld dependency included; native round trips keep every qualifier and lossy exports say
what they lose; and unidentified products, detection limits and a 103 % balance stay as reported. Every document here
is a public synthetic example, or one built in memory from it."""

import copy
import json

import pytest

from conftest import EXAMPLES, GRAPH_MANIFEST, spec_of
from scale import kgbundle, pgraph, pgraph_migrate, pgraph_query, quantities, results, schema_change
from scale.util import ScaleError, load_doc, write_canonical

PM = EXAMPLES / "scale-catal/product-measurement-examples/product-measurements.json"
ELECTRO = EXAMPLES / "scale-catal/driving-force-examples/electro.json"
P = "ex:pm"
METHANOL, CO2 = f"{P}/species/methanol", f"{P}/species/co2"
HYDRO, CO2RR, REPEAT = f"{P}/test/co2-hydrogenation", f"{P}/test/co2rr", f"{P}/test/co2rr-repeat"


def V(value, unit, **kw) -> dict:
    return {"status": "present", "value": value, "unit": unit, **kw}


@pytest.fixture(scope="module")
def spec():
    return pgraph.load_spec(GRAPH_MANIFEST)


def _node(doc: dict, nid: str) -> dict:
    return next(n for n in doc["nodes"] if n["id"] == nid)


def _entry(doc: dict, nid: str, rid: str) -> dict:
    return next(x for x in _node(doc, nid)["props"]["result_values"] if x.get("id") == rid)


def _errors(doc) -> list[str]:
    return [e["message"] for e in pgraph.validate(doc, spec_of(doc)).errors]


def _warnings(doc) -> list[str]:
    return [w["message"] for w in pgraph.validate(doc, spec_of(doc)).warnings]


def _run(doc, plan) -> dict:
    return pgraph_query.run(doc, spec_of(doc), plan)


def _shares(doc: dict, entries: list[dict]) -> dict:
    """``doc`` with the hydrogenation test's results replaced by ``entries`` (each citing an evidence item of its own),
    and without the test outcome that names a result it replaced (a reference to a result that is gone is an error)."""
    d = copy.deepcopy(doc)
    d["links"] = [e for e in d["links"] if e["type"] != "TESTS"]
    t = _node(d, HYDRO)["props"]
    t["evidence"] = [{"id": x["id"], "source": f"{P}/source/paper", "locator": "Table 2", "kind": "table"} for x in entries]
    t["result_values"] = [dict(x, evidence_ids=[x["id"]]) for x in entries]
    return d


def _of_kind(kind: str, formula: str = "CH3OH") -> list[dict]:
    """Steps binding one result of ``kind`` for the species of ``formula``, with its producer when it names one."""
    return [{"from": "test", "entries": "result_values", "kind": kind, "as": "r"},
            {"from": "r", "field": "target", "to": "ChemicalSpecies", "as": "product",
             "where": [{"prop": "formula", "op": "eq", "value": formula}]},
            {"from": "r", "field": "produced_by", "to": "Experiment", "as": "assay", "optional": True}]


def _at_least(x: float, var: str = "r") -> list[dict]:
    return [{"var": var, "prop": "value", "op": "ge", "value": x, "unit": "%", "basis": "carbon"}]


# ------------------------------------------------------------------------------------------ metric identity
def test_a_yield_threshold_never_passes_on_a_selectivity():
    """Conversion 50 %, methanol yield 40 %, selectivity 80 %: a yield of at least 50 % fails, a selectivity of at least
    50 % passes; in a path that names only the product, the three shares stay one another's."""
    d = _shares(load_doc(PM), [
        V(50, "%", id="conversion", variable=f"{P}/variable/conversion", target=CO2, basis="carbon"),
        V(40, "%", id="yield", variable=f"{P}/variable/yield", target=METHANOL, basis="carbon"),
        V(80, "%", id="selectivity", variable=f"{P}/variable/selectivity", target=METHANOL, basis="carbon")])
    assert not _errors(d)
    base = {"match": {"label": "CatalyticTest", "as": "test"}, "return": ["r"]}
    for mode in ("ordinary", "scientific"):
        yields = _run(d, {**base, "comparison": mode, "steps": _of_kind("product_yield"), "where": _at_least(50)})
        assert yields["status"] == "no_matching_record" and yields["rows"] == [], mode
        sel = _run(d, {**base, "comparison": mode, "steps": _of_kind("selectivity"), "where": _at_least(50)})
        assert [r["values"]["r"]["value"] for r in sel["rows"]] == [80], mode
        conv = _run(d, {**base, "comparison": mode, "steps": _of_kind("conversion", "CO2"), "where": _at_least(50)})
        assert [r["values"]["r"]["value"] for r in conv["rows"]] == [50], mode
    # the Variable qualifier and the product qualifier together in one path, which a path could not combine before
    path = f"result_values.*[variable={P}/variable/yield][target={METHANOL}]"
    res = _run(d, {"match": {"label": "CatalyticTest", "as": "test"},
                   "where": [{"var": "test", "prop": path, "op": "ge", "value": 50, "unit": "%", "basis": "carbon"}]})
    assert res["rows"] == []
    assert pgraph_query.parse_path(path)[2] == (("variable", f"{P}/variable/yield"), ("target", METHANOL))


def test_the_scalar_shares_have_kinds_of_their_own(spec):
    c = quantities.contracts(spec)
    kinds = {p: spec["nodes"]["CatalyticTest"]["properties"][p]["quantity"] for p in ("conversion", "yield", "selectivity")}
    assert kinds == {"conversion": "conversion", "yield": "product_yield", "selectivity": "selectivity"}
    assert all(c.kinds[k]["share"] and c.kinds[k]["compare_by"][0]["context"] == "species" for k in kinds.values())
    assert c.kinds["production_rate"]["denominator"] and not c.kinds["production_rate"]["share"]
    assert c.kinds["balance"]["closure"] and not c.kinds["balance"]["share"]
    # a scalar yield and a result entry of kind product_yield are bound by one selector
    d = load_doc(PM)
    _node(d, HYDRO)["props"]["yield"] = V(41, "%", target=METHANOL, basis="carbon")
    res = _run(d, {"match": {"label": "CatalyticTest", "as": "test"},
                   "steps": [{"from": "test", "entries": ["result_values", "yield"], "kind": "product_yield", "as": "r"}],
                   "return": ["r"]})
    assert sorted(r["bound"]["r"]["path"] for r in res["rows"]) == ["/result_values/methanol_yield_gc",
                                                                   "/result_values/methanol_yield_nmr", "/yield"]


# ------------------------------------------------------------------------------------------ one bound result
@pytest.mark.parametrize("mode", ["ordinary", "scientific"])
def test_two_assays_never_satisfy_conditions_meant_for_one_result(mode):
    """Yields of 40 % (GC) and 80 % (NMR): >= 70 and <= 50 are met by no one result, whether the result is bound by an
    entries step or selected by one path that both filters name."""
    d = _shares(load_doc(PM), [
        V(40, "%", id="yield_gc", variable=f"{P}/variable/yield", target=METHANOL, basis="carbon", produced_by=f"{P}/assay/gc-outlet"),
        V(80, "%", id="yield_nmr", variable=f"{P}/variable/yield", target=METHANOL, basis="carbon",
          produced_by=f"{P}/assay/nmr-condensate")])
    both = [{"var": "r", "prop": "value", "op": "ge", "value": 70, "unit": "%", "basis": "carbon"},
            {"var": "r", "prop": "value", "op": "le", "value": 50, "unit": "%", "basis": "carbon"}]
    bound = _run(d, {"comparison": mode, "match": {"label": "CatalyticTest", "as": "test"}, "steps": _of_kind("product_yield"),
                     "where": both})
    assert bound["rows"] == []
    path = f"result_values.*[variable={P}/variable/yield][target={METHANOL}]"
    by_path = _run(d, {"comparison": mode, "match": {"label": "CatalyticTest", "as": "test", "id": HYDRO},
                       "where": [dict(f, var="test", prop=path) for f in both]})
    assert by_path["rows"] == []
    one = _run(d, {"comparison": mode, "match": {"label": "CatalyticTest", "as": "test", "id": HYDRO},
                   "where": [dict(both[0], var="test", prop=path)], "return": [f"test.{path}"]})
    assert [x["value"] for x in one["rows"][0]["values"][f"test.{path}"]] == [80]   # the entry that passed, not both


def test_the_returned_value_producer_and_evidence_are_the_entry_that_matched():
    d = load_doc(PM)
    res = _run(d, {"match": {"label": "CatalyticTest", "as": "test"}, "steps": _of_kind("product_yield"),
                   "where": [{"var": "r", "prop": "phase", "op": "eq", "value": "liquid"}],
                   "return": ["r", "r.produced_by", "assay.name"], "evidence": True})
    (row,) = res["rows"]
    assert row["values"]["r"]["value"] == 38 and row["values"]["r.produced_by"] == f"{P}/assay/nmr-condensate"
    assert row["values"]["assay.name"].startswith("1H NMR of the condensate")
    assert row["bound"]["r"] == {"record": HYDRO, "path": "/result_values/methanol_yield_nmr", "kind": "product_yield"}
    ids = {(e["var"], e.get("id")) for e in row["evidence"] if e["record"] == HYDRO}
    assert ("r", "t2_yield_nmr") in ids and ("test", "methods") in ids    # the entry's own, and the record's general item
    cited_by_others = {"t2_yield_gc", "t2_conversion", "t2_selectivity", "t2_detection_limit", "t2_unidentified", "t2_balance"}
    assert not cited_by_others & {i for _, i in ids}                      # never another result's passage
    assert next(e for e in row["evidence"] if e.get("id") == "t2_yield_nmr")["entry"] == "/result_values/methanol_yield_nmr"
    assert any(e["record"] == f"{P}/assay/nmr-condensate" for e in row["evidence"])     # the producer's evidence


# ------------------------------------------------------------------------------------------ the product
def test_an_ammonia_query_leaves_out_a_hydrogen_only_result():
    import yaml
    cq = yaml.safe_load((GRAPH_MANIFEST.parent.parent / "competency/cq-01-faradaic-efficiency.yaml").read_text())
    d = load_doc(EXAMPLES / "scale-catal/driving-force-examples/electro-dynamic.json")
    blank = next(n for n in d["nodes"] if n["id"].endswith("/test/blank"))
    assert [x["target"] for x in blank["props"]["faradaic_efficiency"]] == ["ex:df-dynelectro/species/hydrogen"]
    res = _run(d, cq["plan"])
    assert sorted(r["bound"]["test"] for r in res["rows"]) == ["ex:df-dynelectro/test/pulsed", "ex:df-dynelectro/test/steady"]
    assert {r["values"]["product.formula"] for r in res["rows"]} == {"NH3"}
    assert sorted(r["values"]["fe"]["value"] for r in res["rows"]) == [57, 94]     # the efficiency that matched
    without = {**cq["plan"], "steps": [st for st in cq["plan"]["steps"] if st.get("as") != "product"]}
    assert "ex:df-dynelectro/test/blank" in [r["bound"]["test"] for r in _run(d, without)["rows"]]   # it is there


def test_a_source_never_qualifies_as_a_product():
    d = load_doc(PM)
    _entry(d, CO2RR, "h2_fe")["target"] = f"{P}/source/paper"
    errs = _errors(d)
    assert any("its target ex:pm/source/paper is a Source, but the species a faradaic_efficiency is counted for is a "
               "ChemicalSpecies" in e for e in errs)
    legacy = load_doc(ELECTRO)                                           # a per-product list is narrowed alike
    next(n for n in legacy["nodes"] if n["label"] == "CatalyticTest")["props"]["faradaic_efficiency"][0]["target"] = \
        "ex:df-electro/source/paper"
    assert any("is a Source, but the species a faradaic_efficiency" in e for e in _errors(legacy))
    res = _run(d, {"match": {"label": "CatalyticTest", "as": "test"},
                   "steps": [{"from": "test", "entries": "result_values", "kind": "faradaic_efficiency", "as": "fe"},
                             {"from": "fe", "field": "target", "to": "ChemicalSpecies", "as": "product"}],
                   "return": ["fe.id"]})
    assert "h2_fe" not in [r["values"]["fe.id"] for r in res["rows"]]     # the step binds species only


def test_an_unidentified_product_stays_explicit_and_out_of_product_comparisons():
    d = load_doc(PM)
    x = _entry(d, HYDRO, "unidentified_selectivity")
    assert x["unresolved_target"] == "unidentified oxygenates" and "target" not in x
    listing = _run(d, {"match": {"label": "CatalyticTest", "as": "test"},
                       "steps": [{"from": "test", "entries": "result_values", "kind": "selectivity", "as": "r"},
                                 {"from": "r", "field": "target", "to": "ChemicalSpecies", "as": "product", "optional": True}],
                       "return": ["r.id", "r.unresolved_target", "product.name"]})
    row = next(r for r in listing["rows"] if r["values"]["r.id"] == "unidentified_selectivity")
    assert row["values"]["product.name"] is None and row["values"]["r.unresolved_target"] == "unidentified oxygenates"
    per_product = _run(d, {"match": {"label": "CatalyticTest", "as": "test"},
                           "steps": [{"from": "test", "entries": "result_values", "kind": "selectivity", "as": "r"},
                                     {"from": "r", "field": "target", "to": "ChemicalSpecies", "as": "product"}],
                           "return": ["r.id"]})
    step = next(s for s in per_product["coverage"]["steps"] if s.get("as") == "product")
    assert step["left_out_by_reason"] == {"unresolved_target": 1}
    sci = _run(d, {"comparison": "scientific", "match": {"label": "CatalyticTest", "as": "test"},
                   "steps": [{"from": "test", "entries": "result_values", "kind": "selectivity", "as": "r"}],
                   "where": [{"var": "r", "prop": "value", "op": "ge", "value": 1, "unit": "%"}], "return": ["r.id"]})
    assert "unidentified_selectivity" not in [r["values"]["r.id"] for r in sci["rows"]]
    left = [x for x in sci["excluded"] if x.get("entry") == "/result_values/unidentified_selectivity"]
    assert left and left[0]["reason"].startswith("missing_context") and "unresolved_target" in left[0]["reason"]


def test_a_detection_limit_stays_a_limit():
    d = load_doc(PM)
    x = _entry(d, HYDRO, "ch4_selectivity")
    assert x["status"] == "below_detection_limit" and x["value"] == 0.1
    res = _run(d, {"match": {"label": "CatalyticTest", "as": "test"},
                   "steps": [{"from": "test", "entries": "result_values", "kind": "selectivity", "as": "r"}],
                   "where": [{"var": "r", "prop": "value", "op": "le", "value": 5, "unit": "%", "basis": "carbon"}],
                   "return": ["r.id"]})
    assert "ch4_selectivity" not in [r["values"]["r.id"] for r in res["rows"]]   # a limit is never read as the number
    assert any(x.get("entry") == "/result_values/ch4_selectivity" and x["reason"] == "below_detection_limit"
               for x in res["excluded"])


# ------------------------------------------------------------------------------------------ repetition
def test_repeated_assays_stay_distinct_and_ambiguous_repetition_is_diagnosed():
    d = load_doc(PM)
    assert any("result_values.co_fe_a, result_values.co_fe_b: 2 results that nothing tells apart" in w for w in _warnings(d))
    plan = {"match": {"label": "CatalyticTest", "as": "test"},
            "steps": [{"from": "test", "entries": "result_values", "kind": "faradaic_efficiency", "as": "fe"},
                      {"from": "fe", "field": "target", "to": "ChemicalSpecies", "as": "product",
                       "where": [{"prop": "formula", "op": "eq", "value": "CO"}]}],
            "return": ["fe.id", "fe.value"]}
    ordinary = _run(d, plan)
    got = {r["values"]["fe.id"]: r.get("ambiguous_repetition") for r in ordinary["rows"]}
    assert got == {"co_fe_30min": None, "co_fe_60min": None, "co_fe_a": {"fe": ["/result_values/co_fe_b"]},
                   "co_fe_b": {"fe": ["/result_values/co_fe_a"]}}                   # two assays, two intervals: distinct
    assert any("ambiguous_repetition" in m for m in ordinary["limitations"])
    sci = _run(d, {**plan, "comparison": "scientific", "order_by": [{"var": "fe", "prop": "value", "desc": True}]})
    assert [r["values"]["fe.id"] for r in sci["rows"]] == ["co_fe_30min", "co_fe_60min"]     # ranked; never averaged
    assert sci["coverage"]["comparison"]["left_out"]["ambiguous_repetition"] == 2
    assert all(r["values"]["fe.value"]["value"] in (26, 24) for r in sci["rows"])


def test_a_per_product_list_that_repeats_a_product_is_diagnosed():
    d = load_doc(ELECTRO)
    t = next(n for n in d["nodes"] if n["label"] == "CatalyticTest")["props"]
    t["faradaic_efficiency"].append(copy.deepcopy(t["faradaic_efficiency"][0]) | {"value": 88})
    assert any("faradaic_efficiency.0, faradaic_efficiency.1: 2 entries for one product that nothing tells apart" in w
               for w in _warnings(d))
    t["faradaic_efficiency"][1]["phase"] = "liquid"                      # told apart by its phase: two results
    assert not any("nothing tells apart" in w for w in _warnings(d))


# ------------------------------------------------------------------------------------------ references
def test_a_reference_names_its_result_by_id_through_reordering():
    d = load_doc(PM)
    ref = next(e for e in d["links"] if e["type"] == "TESTS")["props"]["result_refs"][0]
    assert ref == {"record": HYDRO, "path": "/result_values/methanol_selectivity"}
    shuffled = copy.deepcopy(d)
    _node(shuffled, HYDRO)["props"]["result_values"].reverse()
    _node(shuffled, HYDRO)["props"]["result_values"].append(
        V(1, "%", id="formaldehyde_selectivity", variable=f"{P}/variable/selectivity", unresolved_target="formaldehyde (tentative)",
          basis="carbon", evidence_ids=["t2_unidentified"]))
    assert not _errors(shuffled)
    for doc in (d, shuffled):
        ok, x = results.resolve(_node(doc, HYDRO)["props"], ref["path"])
        assert ok and x["value"] == 80 and x["variable"] == f"{P}/variable/selectivity"
    by_position = copy.deepcopy(d)
    next(e for e in by_position["links"] if e["type"] == "TESTS")["props"]["result_refs"][0]["path"] = "/result_values/3"
    assert any("names a result by its position; name it by its id" in e for e in _errors(by_position))
    revised = copy.deepcopy(shuffled)                             # the record revised since the reference was made
    _node(revised, HYDRO)["props"]["record_version"] = 2
    next(e for e in revised["links"] if e["type"] == "TESTS")["props"]["result_refs"][0]["record_version"] = 1
    assert any(f"refers to {HYDRO} version 1; the graph holds version 2" in w for w in _warnings(revised))
    gone = copy.deepcopy(d)                                       # a result removed: the reference names nothing, said so
    _node(gone, HYDRO)["props"]["result_values"] = [x for x in _node(gone, HYDRO)["props"]["result_values"]
                                                    if x["id"] != "methanol_selectivity"]
    assert any("result_values/methanol_selectivity does not resolve to a property" in e for e in _errors(gone))


def test_a_reference_survives_filtering_and_goes_with_a_withheld_dependency():
    d = load_doc(PM)
    nmr = _node(d, f"{P}/assay/nmr-condensate")
    nmr["props"]["stewardship"] = {"access": "institution", "contributed_by": ["ex:pm/org/lab"]}
    tests = next(e for e in d["links"] if e["type"] == "TESTS")
    tests["props"]["result_refs"].append({"record": HYDRO, "path": "/result_values/methanol_yield_nmr"})
    view = pgraph.filter_for(d, [], "2026-10-18")                 # the public: the NMR assay is withheld
    t = _node(view, HYDRO)["props"]["result_values"]
    held = next(x for x in t if x.get("id") == "methanol_yield_nmr")
    assert held == {"status": "not_reported", "missing_reason": "withheld", "id": "methanol_yield_nmr",
                    "target": METHANOL, "variable": f"{P}/variable/yield"}          # withheld in its place, its id kept
    assert [x.get("id") for x in t] == [x.get("id") for x in _node(d, HYDRO)["props"]["result_values"]]
    refs = next(e for e in view["links"] if e["type"] == "TESTS")["props"]["result_refs"]
    assert refs == [{"record": HYDRO, "path": "/result_values/methanol_selectivity"}]   # the withheld one goes, not moves
    ok, x = results.resolve(_node(view, HYDRO)["props"], refs[0]["path"])
    assert ok and x["value"] == 80
    assert not [e for e in pgraph.validate(view, spec_of(view)).errors if "result" in e["message"]]
    gone = pgraph._moved(_node(d, HYDRO)["props"], "/result_values/methanol_yield_nmr",
                         {("held", "/result_values/2")})
    assert gone is None                                            # a path to an entry withheld in its place goes


def test_an_id_is_snake_case_and_names_one_value():
    d = load_doc(PM)
    _entry(d, HYDRO, "co_selectivity")["id"] = "3"
    assert any("id '3' is not snake_case" in e for e in _errors(d))


# ------------------------------------------------------------------------------------------ round trips and exports
def test_a_native_round_trip_keeps_every_qualifier(tmp_path):
    d = load_doc(PM)
    write_canonical(tmp_path / "copy.json", d)
    again = load_doc(tmp_path / "copy.json")
    assert again == d
    view = pgraph.filter_for(d, [], "2026-10-18")                 # a public view of a public graph keeps them all
    for nid in (HYDRO, CO2RR):
        assert _node(view, nid)["props"]["result_values"] == _node(d, nid)["props"]["result_values"]
    old = copy.deepcopy(d)                                         # a 0.3.0 document moves on with nothing rewritten
    old["graph"]["schema_version"] = "0.3.0"
    for n in old["nodes"]:
        n["props"].pop("result_values", None)
    new, log = pgraph_migrate.raise_version(old, spec_of(d)["version"], spec_of(d))
    assert next(s for s in log["steps"] if s["from"] == "0.3.0")["changes"] == []
    assert new["nodes"] == old["nodes"]


def test_lossy_exports_say_what_they_lose(tmp_path):
    d = load_doc(PM)
    losses = pgraph.neo4j_losses(d)
    assert losses and "19 result entries (result_values) are carried as JSON text" in losses[0]
    rows = [json.loads(x) for x in pgraph.to_neo4j_jsonl(d).splitlines()]
    t = next(r for r in rows if r["id"] == HYDRO)["properties"]
    assert {x["id"] for x in json.loads(t["result_values"])} >= {"methanol_yield_gc", "carbon_balance"}   # kept as text
    m = kgbundle.export(d, spec_of(d), tmp_path / "bundle", "pm")
    rep = m["export_report"]
    assert rep["result_entries_as_text"] == {"CatalyticTest": 19}
    assert "cannot bind a result to its product, assay and evidence" in rep["result_entries_note"]
    assert not pgraph.neo4j_losses(load_doc(ELECTRO))             # a document without result entries loses none


# ------------------------------------------------------------------------------------------ balances and limits
def test_a_balance_above_100_percent_is_kept_with_its_uncertainty_and_flagged():
    d = load_doc(PM)
    x = _entry(d, HYDRO, "carbon_balance")
    assert (x["value"], x["uncertainty"], x["uncertainty_kind"]) == (103, 4, "standard_deviation")
    assert any("carbon_balance: a balance of 103 % is above 100 %; 100 % lies within its stated uncertainty" in w
               for w in _warnings(d))
    x.update(value=110, uncertainty=2)
    assert any("above 100 % beyond its stated uncertainty" in w for w in _warnings(d))
    x.pop("uncertainty"), x.pop("uncertainty_kind")
    assert any("is above 100 % and states no uncertainty" in w for w in _warnings(d))
    x["value"] = 96
    assert not any("balance of" in w for w in _warnings(d))
    res = _run(load_doc(PM), {"match": {"label": "CatalyticTest", "as": "test"},
                              "steps": [{"from": "test", "entries": "result_values", "kind": "balance", "as": "b"}],
                              "return": ["b.value", "b.basis", "b.produced_by"]})
    got = {r["values"]["b.basis"]: r["values"]["b.value"]["value"] for r in res["rows"]}
    assert got == {"carbon": 103, "charge": 97}                     # kept as reported, never capped
    assert all(r["values"]["b.produced_by"].startswith(f"{P}/analysis/") for r in res["rows"])


def test_a_result_entry_states_what_identifies_it():
    d = load_doc(PM)
    x = _entry(d, CO2RR, "formate_fe")
    for field, error in (("variable", "a result entry names its variable"), ("evidence_ids", "names the evidence items"),
                         ("target", "a faradaic_efficiency is counted for a species")):
        bad = copy.deepcopy(d)
        _entry(bad, CO2RR, "formate_fe").pop(field)
        assert any(error in e for e in _errors(bad)), field
    both = copy.deepcopy(d)
    _entry(both, CO2RR, "formate_fe")["unresolved_target"] = "formate or formic acid"
    assert any("target and unresolved_target do not go together" in e for e in _errors(both))
    assert x["phase"] == "liquid" and x["stream"] == "catholyte"


# ------------------------------------------------------------------------------------------ plans, migration, the diff
def test_entry_plan_errors():
    d = load_doc(PM)
    base = {"match": {"label": "CatalyticTest", "as": "test"}}
    bad = [({**base, "steps": [{"from": "test", "entries": "result_values", "kind": "speed", "as": "r"}]}, "is not a quantity kind"),
           ({**base, "steps": [{"from": "test", "field": "target", "as": "x"}]}, "follows a field of a value entry"),
           ({**base, "steps": [{"from": "test", "entries": "result_values", "as": "r"},
                               {"from": "r", "edge": "OF_REACTION", "to": "Reaction", "as": "x"}]}, "has no links"),
           ({**base, "steps": [{"from": "test", "entries": "result_values", "as": "r"},
                               {"from": "r", "field": "phase", "as": "x"}]}, "a field that names a record is one of"),
           ({**base, "steps": [{"from": "test", "entries": "name", "as": "r"}]}, "holds no values"),
           ({**base, "steps": [{"from": "test", "edge": "OF_REACTION", "entries": "result_values", "as": "r"}]}, "not \\['edge', 'entries'\\]"),
           ({**base, "where": [{"var": "test", "prop": "result_values.*[colour=red]", "op": "exists"}]}, "a qualifier is one of"),
           ({**base, "steps": [{"from": "test", "edge": "OF_REACTION", "to": "Reaction", "as": "rxn", "edge_as": "of"},
                               {"from": "of", "entries": "result_values", "as": "r"}]}, "of a node variable")]
    for plan, error in bad:
        with pytest.raises(ScaleError, match=error):
            _run(d, plan)
    gap = _run(d, {**base, "steps": [{"from": "test", "entries": "result_values", "as": "r"}],
                   "where": [{"var": "r", "prop": "colour", "op": "eq", "value": "red"}]})
    assert gap["status"] == "schema_gap" and gap["schema_gaps"] == ["a value entry.colour is not declared"]
    # exists on a path that selects no entry fails, as it did before filters on one path were held by one entry
    none = _run(d, {**base, "where": [{"var": "test", "prop": "result_values.*[target=ex:pm/species/water]", "op": "exists"}]})
    assert none["status"] == "no_matching_record" and none["coverage"]["excluded"]["total"] == 0


def test_migration_refuses_a_product_that_is_no_species():
    d = load_doc(ELECTRO)
    old = copy.deepcopy(d)
    old["graph"]["schema_version"] = "0.3.0"
    next(n for n in old["nodes"] if n["label"] == "CatalyticTest")["props"]["faradaic_efficiency"][0]["target"] = \
        "ex:df-electro/source/paper"
    with pytest.raises(ScaleError, match="cannot map values whose product or reactant is not a chemical species"):
        pgraph_migrate.raise_version(old, spec_of(d)["version"], spec_of(d))


def test_the_schema_diff_detects_a_narrowed_species_and_a_changed_kind(spec):
    a = copy.deepcopy(spec)
    a.pop("context_targets")
    d = schema_change.diff_specs(a, spec)
    assert d["narrowed"] == ["context_targets.species: a value's target read as its species names a ChemicalSpecies"]
    assert schema_change.tier(d) == 3
    b = copy.deepcopy(spec)
    b["context_targets"]["species"]["targets"] = ["ChemicalSpecies", "Material"]
    assert schema_change.diff_specs(spec, b)["loosened"] == ["context_targets.species + Material"]
    c = copy.deepcopy(spec)
    c["quantities"]["kinds"]["balance"]["closure"] = False
    assert "quantities.kinds.balance: closure True -> False" in schema_change.diff_specs(spec, c)["changed"]
    e = copy.deepcopy(spec)
    e["nodes"]["CatalyticTest"]["properties"]["yield"]["quantity"] = "selectivity"
    assert any("CatalyticTest.yield: quantity product_yield -> selectivity" in x for x in schema_change.diff_specs(spec, e)["changed"])


def test_the_loader_refuses_a_malformed_narrowing(tmp_path):
    from scale import pgraph_schema
    import shutil
    root = tmp_path / "repo"
    shutil.copytree(GRAPH_MANIFEST.parent.parent.parent / "core", root / "core")     # a scratch copy: no registry needed
    (root / "domain/graph").mkdir(parents=True)
    for f in ("scale-catal.yaml", "catalysis.yaml"):
        shutil.copy(GRAPH_MANIFEST.parent / f, root / "domain/graph" / f)
    cat = root / "domain/graph/catalysis.yaml"
    text = cat.read_text()
    for bad, error in (("    - ChemicalSpecies\nchecklist:", "names \\['Molecule'\\]"),
                       ("  species:\n    maturity", "names no context")):
        broken = text.replace("    targets:\n    - ChemicalSpecies\nchecklist:", "    targets:\n    - Molecule\nchecklist:") \
            if "ChemicalSpecies" in bad else text.replace("context_targets:\n  species:", "context_targets:\n  colour:")
        cat.write_text(broken)
        with pytest.raises(ScaleError, match=error):
            pgraph_schema.assemble(root / "domain/graph/scale-catal.yaml")
