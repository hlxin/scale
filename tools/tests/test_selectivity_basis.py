"""Selectivity basis (issue #82): what a selectivity counts (selectivity_count) and is a share of (selectivity_whole), and
the value field relative_to that names the pool of a share within one. Every document is the public synthetic example
selectivity-basis.json, or one built in memory from it.

Each case states its outcome. A scientific comparison keeps apart selectivities that count differently or are shares of
different wholes, and a value that states neither is its own group, never assumed to be one of the others; a share within
a pool is compared only with shares within the same pool; a within-pool text with no relative_to is left out as
missing_context; contradictory statements are warned about and left out; and a query that asks for results as reported
(no comparison) behaves as before."""

import copy

import pytest

from conftest import EXAMPLES, GRAPH_MANIFEST, spec_of
from scale import pgraph, pgraph_query, quantities
from scale.util import load_doc

EX = EXAMPLES / "scale-catal/product-measurement-examples/selectivity-basis.json"
P = "ex:sb"


@pytest.fixture(scope="module")
def doc() -> dict:
    return load_doc(EX)


def _value(d: dict, rid: str) -> dict:
    return next(x for n in d["nodes"] if n["label"] == "CatalyticTest" for x in n["props"].get("result_values", [])
                if x["id"] == rid)


def _plan(**kw) -> dict:
    return {"comparison": "scientific", "match": {"label": "CatalyticTest", "as": "t"},
            "steps": [{"from": "t", "entries": "result_values", "kind": "selectivity", "as": "r"}],
            "return": ["t.name", "r"], "order_by": [{"var": "r", "prop": "value"}], **kw}


def _run(d: dict, plan: dict) -> dict:
    return pgraph_query.run(d, spec_of(d), plan)


def _errors(d: dict) -> list[str]:
    return [e["message"] for e in pgraph.validate(d, spec_of(d)).errors]


def _warnings(d: dict) -> list[str]:
    return [w["message"] for w in pgraph.validate(d, spec_of(d)).warnings]


def _context_of(res: dict) -> dict:
    """result id -> (comparison group, the contexts the comparison read for it)."""
    return {r["values"]["r"]["id"]: (r["comparison_group"], r["compared"]["r.value"]["context"]) for r in res["rows"]}


def _left_out(res: dict) -> dict:
    return {e["entry"].rsplit("/", 1)[1]: e["reason"] for e in res["excluded"]}


# ------------------------------------------------------------------------------------------ the fixture
def test_the_example_is_valid_with_no_warning_and_uses_the_field_and_both_contexts(doc):
    """Expected: valid, no error and no warning. It holds a value with relative_to, one that states each whole
    (converted reactant with CO2, products without CO2), a count by carbon atoms and by mass, and one that states none."""
    assert _errors(doc) == [] and _warnings(doc) == []
    values = {x["id"]: x for n in doc["nodes"] if n["label"] == "CatalyticTest" for x in n["props"]["result_values"]}
    assert {i for i, x in values.items() if "relative_to" in x} == {"c5_olefins_in_olefins", "aldehydes_in_oxygenates"}
    assert values["plain_ch4"].keys().isdisjoint({"basis", "definition", "relative_to"})


def test_each_value_is_read_for_what_it_counts_and_is_a_share_of(doc):
    """Expected: Lyu-like CO2 is carbon atoms of the converted CO (CO2 included); the Lyu-like hydrocarbons are carbon
    atoms among the hydrocarbons (CO2 excluded); the Xie-like values are of the converted CO; the olefin share is within
    the olefins (the value's relative_to) by carbon atoms; the aldehyde share is within the oxygenates, counted by mass
    (its unit wt%); the value that states nothing reads as 'not stated' twice."""
    res = _run(doc, _plan(where=[{"var": "r", "prop": "value", "op": "ge", "value": 0, "unit": "%"}]))
    got = {i: (c["selectivity_count"], c["selectivity_whole"]) for i, (_, c) in _context_of(res).items()}
    assert got == {
        "lyu_co2": ("carbon_atoms", "converted_reactant_incl_co2"),
        "lyu_ch4": ("carbon_atoms", "products_excl_co2"), "lyu_c24": ("carbon_atoms", "products_excl_co2"),
        "lyu_c5": ("carbon_atoms", "products_excl_co2"),
        "xie_ch4": ("carbon_atoms", "converted_reactant_incl_co2"), "xie_c5": ("carbon_atoms", "converted_reactant_incl_co2"),
        "c5_olefins_in_olefins": ("carbon_atoms", f"within_lump:{P}/lump/olefins"),
        "plain_ch4": ("not stated", "not stated"),
    }
    assert "aldehydes_in_oxygenates" in _left_out(res)          # in wt%, a filter in % never reads it (unit, not count)


def test_a_percent_by_mass_unit_is_read_and_states_the_count_mass(doc):
    """Expected: wt% and mass% read as a dimensionless share by mass (selectivity_count mass), and the example's wt% value
    raises no 'unit the contracts cannot read' warning. (A context term equal to a unit symbol would be cut out of the unit
    text as an annotation and leave the unit unread; the term list holds none.)"""
    qc = quantities.contracts(pgraph.load_spec(GRAPH_MANIFEST))
    for u in ("wt%", "wt.%", "mass%"):
        r = qc.read_unit(u, ("fraction_basis", "selectivity_count"))
        assert r.read and r.contexts["selectivity_count"] == "mass", (u, r)
    res = _run(doc, _plan(where=[{"var": "r", "prop": "value", "op": "ge", "value": 0, "unit": "wt%"}]))
    assert [r["values"]["r"]["id"] for r in res["rows"]] == ["aldehydes_in_oxygenates"]
    assert _context_of(res)["aldehydes_in_oxygenates"][1] == {
        "selectivity_count": "mass", "selectivity_whole": f"within_lump:{P}/lump/oxygenates", "species": f"{P}/lump/aldehydes"}


# ------------------------------------------------------------------------------------------ comparison
def test_three_ch4_selectivities_of_different_wholes_are_three_groups_never_one(doc):
    """Expected: 2.6 % of the hydrocarbons (CO2 excluded), 9 % of the converted CO (CO2 included) and 12 % that states
    nothing are compared in three groups; none is ranked against another."""
    plan = _plan(where=[{"var": "r", "prop": "value", "op": "ge", "value": 0, "unit": "%"}])
    plan["steps"].append({"from": "r", "field": "target", "to": "ChemicalSpecies", "as": "sp",
                          "where": [{"prop": "formula", "op": "eq", "value": "CH4"}]})
    res = _run(doc, plan)
    groups = {i: g for i, (g, _) in _context_of(res).items()}
    assert set(groups) == {"lyu_ch4", "xie_ch4", "plain_ch4"} and len(set(groups.values())) == 3, groups


def test_a_context_asked_for_returns_only_the_values_that_state_it(doc):
    """Expected: ranked among shares of the converted CO (CO2 included), counted by carbon atoms, the Lyu-like CO2 selectivity
    and the two Xie-like values are compared (3 rows in one group); the hydrocarbons' shares, the olefin and aldehyde shares
    and the value that states nothing are incompatible_context, none is assumed. (excluded lists a record once per reason
    code, so the Lyu-like test's three left-out hydrocarbon shares show as one entry; the rows are the three compared.)"""
    ask = {"selectivity_whole": "converted_reactant_incl_co2", "selectivity_count": "carbon_atoms"}
    res = _run(doc, _plan(where=[{"var": "r", "prop": "value", "op": "ge", "value": 0, "unit": "%"}],
                          order_by=[{"var": "r", "prop": "value", "context": ask}]))
    # the species the plan leaves unrestricted separates the three; the whole and the count are what this case asks
    assert {i for i, _ in _context_of(res).items()} == {"lyu_co2", "xie_ch4", "xie_c5"}
    left = _left_out(res)
    assert {"plain_ch4", "c5_olefins_in_olefins", "aldehydes_in_oxygenates"} <= set(left) and "lyu_co2" not in left
    assert all(v.startswith("incompatible_") for v in left.values()), left
    assert res["row_count"] == 3 and _left_out(res)["plain_ch4"].endswith("compared on carbon_atoms)")


def test_the_value_that_states_nothing_is_never_grouped_with_one_that_states_a_basis(doc):
    """Expected: a second selectivity without a basis (of C5+) is in a group of its own as it has another target, and both
    read 'not stated' for the count and the whole, never the value of another test; with the same target as the first
    value they would be an ambiguous repetition, not a pair."""
    d = copy.deepcopy(doc)
    t = next(n for n in d["nodes"] if n["id"] == f"{P}/test/unstated")
    plain = copy.deepcopy(_value(d, "plain_ch4"))
    plain.update(id="plain_c5_plus", value=15, target=f"{P}/lump/c5-plus")
    t["props"]["result_values"].append(plain)
    res = _run(d, _plan(where=[{"var": "r", "prop": "value", "op": "ge", "value": 0, "unit": "%"}]))
    ctx = _context_of(res)
    for rid in ("plain_ch4", "plain_c5_plus"):
        assert ctx[rid][1]["selectivity_count"] == ctx[rid][1]["selectivity_whole"] == "not stated", rid
    others = {g for i, (g, _) in ctx.items() if not i.startswith("plain")}
    assert not ({ctx["plain_ch4"][0], ctx["plain_c5_plus"][0]} & others)
    # the C5+ that states nothing is not the Xie-like C5+ that states its whole
    assert ctx["plain_c5_plus"][0] != ctx["xie_c5"][0]


def test_shares_within_two_pools_are_two_groups(doc):
    """Expected: the same share (same target) within the olefins and within the oxygenates are two groups; the whole is
    named 'within_lump:<the pool's id>' from the value's own relative_to."""
    d = copy.deepcopy(doc)
    t = next(n for n in d["nodes"] if n["id"] == f"{P}/test/within-pool")
    other = copy.deepcopy(_value(d, "c5_olefins_in_olefins"))
    other.update(id="c5_olefins_in_oxygenates", relative_to=f"{P}/lump/oxygenates", value=3)
    t["props"]["result_values"].append(other)
    assert _errors(d) == []
    res = _run(d, _plan(where=[{"var": "r", "prop": "value", "op": "ge", "value": 0, "unit": "%"}]))
    ctx = _context_of(res)
    assert ctx["c5_olefins_in_olefins"][0] != ctx["c5_olefins_in_oxygenates"][0]
    assert ctx["c5_olefins_in_olefins"][1]["selectivity_whole"] == f"within_lump:{P}/lump/olefins"
    assert ctx["c5_olefins_in_oxygenates"][1]["selectivity_whole"] == f"within_lump:{P}/lump/oxygenates"


def test_two_results_that_differ_only_in_relative_to_are_not_an_ambiguous_repetition(doc):
    """Expected: a copy of a within-pool value with another pool raises no warning (relative_to tells results apart); a
    copy with the same pool is reported as an ambiguous repetition."""
    for pool, repeated in ((f"{P}/lump/oxygenates", False), (f"{P}/lump/olefins", True)):
        d = copy.deepcopy(doc)
        t = next(n for n in d["nodes"] if n["id"] == f"{P}/test/within-pool")
        x = copy.deepcopy(_value(d, "c5_olefins_in_olefins"))
        x.update(id="copy", relative_to=pool, value=70)
        t["props"]["result_values"].append(x)
        assert any("ambiguous repetition" in w for w in _warnings(d)) is repeated, pool


def test_a_query_step_follows_relative_to_to_the_pool(doc):
    """Expected: following relative_to from the olefin share reaches the 'olefins' ProductLump, and nothing else."""
    plan = {"match": {"label": "CatalyticTest", "as": "t"},
            "steps": [{"from": "t", "entries": "result_values", "kind": "selectivity", "as": "r"},
                      {"from": "r", "field": "relative_to", "to": "ProductLump", "as": "pool"}],
            "return": ["r", "pool.name"]}
    res = _run(doc, plan)
    assert sorted(r["values"]["pool.name"] for r in res["rows"]) == ["olefins", "oxygenates"]


# ------------------------------------------------------------------------------------------ what is refused or left out
def test_a_within_pool_text_without_relative_to_is_missing_context_not_a_guess(doc):
    """Expected: valid, but a scientific comparison on 'within_lump' leaves the value out as missing_context ('within_lump
    names no relative_to'); it is not placed with the values that state no whole."""
    d = copy.deepcopy(doc)
    del _value(d, "c5_olefins_in_olefins")["relative_to"]       # its definition still says "within the olefins"
    assert _errors(d) == []
    res = _run(d, _plan(order_by=[{"var": "r", "prop": "value", "context": {"selectivity_whole": "within_lump"}}]))
    reason = _left_out(res)["c5_olefins_in_olefins"]
    assert reason.startswith("missing_context") and "within_lump names no relative_to" in reason, reason
    assert _left_out(res)["plain_ch4"].startswith("incompatible_context")


def test_a_unit_that_says_mass_and_a_basis_that_says_carbon_contradict_and_the_value_is_left_out(doc):
    """Expected: valid (it stays as reported) with one warning naming 'contradictory selectivity_count' (unit wt% says mass,
    basis says carbon_atoms); a scientific comparison leaves it out as incompatible_context 'contradictory'."""
    d = copy.deepcopy(doc)
    _value(d, "aldehydes_in_oxygenates")["basis"] = "carbon basis"
    assert _errors(d) == []
    w = [m for m in _warnings(d) if "contradictory selectivity_count" in m]
    assert len(w) == 1 and "wt%" in w[0] and "carbon_atoms" in w[0] and "stays as reported" in w[0]
    res = _run(d, _plan(where=[{"var": "r", "prop": "value", "op": "ge", "value": 0, "unit": "wt%"}]))
    assert res["status"] == "no_matching_record" or "aldehydes_in_oxygenates" not in _context_of(res)
    assert "contradictory" in _left_out(res)["aldehydes_in_oxygenates"]


def test_a_definition_naming_two_wholes_contradicts_itself(doc):
    """Expected: warning 'contradictory selectivity_whole' for a value that says both 'of the converted CO' and 'excluding
    CO2'; a scientific comparison leaves it out; no whole is picked."""
    d = copy.deepcopy(doc)
    _value(d, "lyu_ch4")["definition"] = "share of the converted CO, excluding CO2"
    assert any("contradictory selectivity_whole" in m for m in _warnings(d))
    res = _run(d, _plan(where=[{"var": "r", "prop": "value", "op": "ge", "value": 0, "unit": "%"}]))
    assert "contradictory" in _left_out(res)["lyu_ch4"] and "lyu_ch4" not in _context_of(res)


def test_a_relative_to_that_names_no_record_is_an_error(doc):
    """Expected: invalid, one error: the reference does not resolve (the fixture selectivity-relative-to-unresolved.json
    states the same)."""
    d = copy.deepcopy(doc)
    _value(d, "c5_olefins_in_olefins")["relative_to"] = f"{P}/lump/missing"
    errs = _errors(d)
    assert len(errs) == 1 and "relative_to" in errs[0] and "does not resolve" in errs[0], errs


# ------------------------------------------------------------------------------------------ as reported is unchanged
def test_an_as_reported_query_still_compares_the_basis_as_text(doc):
    """Expected: without comparison: scientific, a filter on basis 'carbon' returns the values that state it and leaves out,
    as before, the value that states no basis (other_basis) and the wt% value (incompatible_unit); no comparison block, no
    group, and the new contexts never filter it."""
    plan = {"match": {"label": "CatalyticTest", "as": "t"},
            "steps": [{"from": "t", "entries": "result_values", "kind": "selectivity", "as": "r"}],
            "where": [{"var": "r", "prop": "value", "op": "ge", "value": 0, "unit": "%", "basis": "carbon"}],
            "return": ["t.name", "r"]}
    res = _run(doc, plan)
    assert res["status"] == "answered" and res["row_count"] == 7 and res.get("comparison") is None
    assert _left_out(res)["plain_ch4"].startswith("other_basis")
    assert _left_out(res)["aldehydes_in_oxygenates"].startswith("incompatible_unit")
    assert all("comparison_group" not in r for r in res["rows"])
