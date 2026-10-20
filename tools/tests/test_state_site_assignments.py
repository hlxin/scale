"""Site populations of a catalyst state, site-normalized rates, activity assignments and operando pairings
(scale-catal 0.6.0 on). A site population is on the HAS_SITE from the state it was counted or observed in, and holds for
that state only; a turnover frequency names the site count it is divided by, and what that count counts decides which
rates compare; an assignment of activity is a Claim with named ABOUT roles and its own evidence; an observation the
source calls operando is kept as such, and its pairing with the performance is evaluated from what its DURING link
states. Exercised on the state-and-site example (domain/examples/scale-catal/state-site-examples/) and on variants of
it written in memory."""

import copy
import shutil
import subprocess
import sys

import pytest

from conftest import EXAMPLES, GRAPH_MANIFEST, HEAD_VERSION, REPO, spec_at, spec_of
from scale import pgraph, pgraph_migrate, pgraph_query, quantities
from scale.pgraph_profiles import conformance
from scale.schema_change import diff_specs
from scale.util import ScaleError, load_doc, write_canonical

SS = EXAMPLES / "scale-catal/state-site-examples"
DOC = SS / "sites-and-assignments.json"
P = "ex:ss"


@pytest.fixture
def doc():
    return load_doc(DOC)


@pytest.fixture(scope="module")
def spec():
    return pgraph.load_spec(GRAPH_MANIFEST)


def _link(d: dict, typ: str, source: str, target: str, n: int = 0) -> dict:
    return [e for e in d["links"] if e["type"] == typ and e["source"] == f"{P}/{source}" and e["target"] == f"{P}/{target}"][n]


def _node(d: dict, local: str) -> dict:
    return next(x for x in d["nodes"] if x["id"] == f"{P}/{local}")


def _entry(d: dict, test: str, rid: str) -> dict:
    return next(x for x in _node(d, test)["props"]["result_values"] if x["id"] == rid)


def _q(d: dict, spec: dict, plan: dict) -> dict:
    return pgraph_query.run(d, spec, plan)


def _vals(res: dict, key: str) -> list:
    return [r["values"].get(key) for r in res["rows"]]


# ---------------------------------------------------------------- the example
def test_the_example_is_built_reproducibly(tmp_path):
    work = tmp_path / "ss"
    shutil.copytree(SS, work)
    subprocess.run([sys.executable, str(work / "build_examples.py")], check=True, capture_output=True, cwd=REPO)
    d = load_doc(DOC)
    if d["graph"]["schema_version"] != HEAD_VERSION:              # the head moved on after it was built
        d = pgraph_migrate.raise_version(d, HEAD_VERSION, pgraph.load_spec(GRAPH_MANIFEST))[0]
    write_canonical(tmp_path / DOC.name, d)
    assert (work / DOC.name).read_bytes() == (tmp_path / DOC.name).read_bytes()


def test_the_example_is_valid_and_lacks_only_the_pairing_it_was_built_to_lack(doc):
    rep = pgraph.validate(doc, spec_of(doc))
    assert rep.errors == [] and rep.warnings == [], (rep.errors, rep.warnings)
    c = conformance(doc, spec_of(doc), by_record=True)["profiles"]["catalysis"]
    assert c["conformant"] and c["missing_evidence"] == {"paired_performance": 1, "benchmarked_performance": 1}
    missing = {r for r, x in c["records"].items() if any(not e["found"] for e in (x.get("evidence") or {}).values())}
    assert missing == {f"{P}/characterization/drifts"}


# ---------------------------------------------------------------- populations belong to their state
def test_one_specimen_has_separate_populations_in_its_prepared_and_working_states(doc, spec):
    reduced = _link(doc, "HAS_SITE", "state/reduced", "site/zn-decorated-step")
    working = _link(doc, "HAS_SITE", "state/working", "site/zn-decorated-step")
    for link, share, ev_id in ((reduced, 2, "t2_share_reduced"), (working, 9, "f5_share")):
        v = link["props"]["population_fraction"]
        assert v["value"] == share and v["unit"] == "%" and v["basis"] == "of the exposed Cu atoms"
        assert v["evidence_ids"] == [ev_id] and ev_id in {e.get("id") for e in link["props"]["evidence"]}
    assert {e["locator"] for e in reduced["props"]["evidence"]} != {e["locator"] for e in working["props"]["evidence"]}
    assert reduced["props"]["population_fraction"]["produced_by"] != working["props"]["population_fraction"]["produced_by"]
    # both states are of one specimen
    for st in ("state/reduced", "state/working"):
        assert _link(doc, "STATE_OF", st, "sample/batch-a-xas-cell")
    res = _q(doc, spec, {"match": {"label": "CatalystState", "as": "state"},
                         "steps": [{"from": "state", "edge": "STATE_OF", "to": "CatalystSample", "as": "s",
                                    "where": [{"prop": "id", "op": "eq", "value": f"{P}/sample/batch-a-xas-cell"}]},
                                   {"from": "state", "edge": "HAS_SITE", "to": "ActiveSite", "as": "site", "edge_as": "pop",
                                    "where": [{"prop": "id", "op": "eq", "value": f"{P}/site/zn-decorated-step"}]}],
                         "return": ["state.state_kind", "pop.population_fraction"], "evidence": True})
    shares = sorted((r["values"]["state.state_kind"], (r["values"]["pop.population_fraction"] or {}).get("value", -1))
                    for r in res["rows"])
    assert shares == [("pretreated", 2), ("working", -1), ("working", 9)]     # the titrated count states no share
    cited = {(e["record"], e["locator"]) for r in res["rows"] for e in r["evidence"] if e["var"] == "HAS_SITE"}
    assert (reduced["id"], "Table 2") in cited and (working["id"], "Figure 5") in cited


def test_a_population_of_one_state_is_not_inherited_by_another(doc, spec):
    plan = {"match": {"id": f"{P}/state/after-test", "as": "state"},
            "steps": [{"from": "state", "edge": "HAS_SITE", "to": "ActiveSite", "as": "site",
                       "where": [{"prop": "id", "op": "eq", "value": f"{P}/site/zn-decorated-step"}]}],
            "return": ["site.name"]}
    assert _q(doc, spec, plan)["status"] == "no_matching_record"
    # nor does the specimen hold what its states hold, or a state what the specimen holds
    plan = {"match": {"id": f"{P}/sample/batch-a-xas-cell", "as": "s"},
            "steps": [{"from": "s", "edge": "HAS_SITE", "to": "ActiveSite", "as": "site"}], "return": ["site.name"]}
    assert _q(doc, spec, plan)["status"] == "no_matching_record"
    d = copy.deepcopy(doc)
    d["links"].append({"id": f"{P}/link/sample-site", "type": "HAS_SITE", "source": f"{P}/sample/batch-a-xas-cell",
                       "target": f"{P}/site/cu-step", "props": {"origin": "synthetic", "status": "asserted"}})
    assert pgraph.validate(d, spec_of(d)).errors == []                          # a sample may still have a site
    plan = {"match": {"id": f"{P}/state/after-test", "as": "state"},
            "steps": [{"from": "state", "edge": "HAS_SITE", "to": "ActiveSite", "as": "site",
                       "where": [{"prop": "id", "op": "eq", "value": f"{P}/site/cu-step"}]}], "return": ["site.name"]}
    assert _q(d, spec, plan)["status"] == "no_matching_record"
    # the after-test state has its own count of the exposed Cu, apart from the one after reduction
    counts = {link["source"]: link["props"]["exposed_metal_count"]["value"] for link in doc["links"]
              if link["type"] == "HAS_SITE" and link["target"] == f"{P}/site/exposed-cu"}
    assert counts == {f"{P}/state/reduced": 310, f"{P}/state/after-test": 240, f"{P}/state/formulation-reduced": 300}


def test_a_population_on_a_test_or_a_share_in_a_count_unit_is_refused(doc):
    d = copy.deepcopy(doc)
    _link(d, "HAS_SITE", "state/reduced", "site/zn-decorated-step")["source"] = f"{P}/test/xas-cell"
    assert any("HAS_SITE source must be" in e["message"] for e in pgraph.validate(d, spec_of(d)).errors)
    d = copy.deepcopy(doc)
    _link(d, "HAS_SITE", "state/reduced", "site/zn-decorated-step")["props"]["population_fraction"]["unit"] = "µmol/g"
    assert any("not a dimension of site_fraction" in e["message"] for e in pgraph.validate(d, spec_of(d)).errors)


# ---------------------------------------------------------------- site-normalized rates
def test_a_site_normalized_rate_names_its_denominator_state_origin_and_evidence(doc, spec):
    res = _q(doc, spec, {"match": {"label": "CatalyticTest", "as": "test"},
                         "steps": [{"from": "test", "entries": "result_values", "kind": "turnover_frequency", "as": "tof"},
                                   {"from": "tof", "field": "normalized_by", "link": "HAS_SITE", "end": "source",
                                    "to": "CatalystState", "as": "counted_in", "edge_as": "count"},
                                   {"from": "tof", "field": "normalized_by", "link": "HAS_SITE", "end": "target",
                                    "to": "ActiveSite", "as": "site"},
                                   {"from": "test", "edge": "IN_STATE", "to": "CatalystState", "as": "measured_in"}],
                         "return": ["tof", "measured_in.state_kind", "counted_in.state_kind", "site.name",
                                    "count.exposed_metal_count", "count.site_inventory"], "evidence": True})
    assert res["status"] == "answered" and len(res["rows"]) == 3
    by = {r["values"]["tof"]["id"]: r for r in res["rows"]}
    step = by["tof_per_step_site"]
    assert step["values"]["counted_in.state_kind"] == "working" == step["values"]["measured_in.state_kind"]
    inv = step["values"]["count.site_inventory"]
    assert inv["value"] == 28 and inv["origin"] == "derived" and inv["produced_by"] == f"{P}/analysis/step-site-inventory"
    assert {e["locator"] for e in step["evidence"] if e["var"] == "HAS_SITE"} == {"Figure 5", "Table 2"}
    # the count per exposed atom was made after reduction, not in the state the rate was measured in, and says so
    exposed = by["tof_per_exposed_cu"]
    assert exposed["values"]["counted_in.state_kind"] == "pretreated" and exposed["values"]["measured_in.state_kind"] == "working"
    # the counting measurement and its assumptions: the count names its Analysis, which uses the counting model on the
    # frontal chromatography of the same specimen
    count = exposed["values"]["count.exposed_metal_count"]
    an = _node(doc, "analysis/rfc-reduced-count")
    assert count["produced_by"] == an["id"] and count["uncertainty"] == 15 and count["replicates"] == 3
    assert _link(doc, "USES_MODEL", "analysis/rfc-reduced-count", "model/n2o-counting")
    assert len(_node(doc, "model/n2o-counting")["props"]["assumptions"]) == 2
    assert _link(doc, "CHARACTERIZES", "characterization/rfc-reduced", "sample/batch-a-xas-cell")["props"]["state"] == "reduced"
    # the two rates that name no site count are left out of the step, never joined to another state's count
    left = next(s for s in res["coverage"]["steps"] if s.get("as") == "counted_in")["left_out_by_reason"]
    assert left == {"not_curated": 2}


def test_rates_per_exposed_atom_per_site_and_per_atom_are_never_compared(doc, spec):
    res = _q(doc, spec, {"comparison": "scientific", "match": {"label": "CatalyticTest", "as": "test"},
                         "steps": [{"from": "test", "entries": "result_values", "kind": "turnover_frequency", "as": "tof"}],
                         "where": [{"var": "tof", "prop": "value", "op": "gt", "value": 0, "unit": "s-1"}],
                         "return": ["tof"]})
    groups = {g["compared_on"]["tof.value"]["context"]["site_count_basis"]: g["rows"] for g in res["comparison"]["groups"]}
    assert groups == {"exposed_atoms": 1, "specific_sites": 2, "all_atoms": 1}
    assert [(e["record"], e["reason"].split(" ")[0]) for e in res["excluded"]] == [(f"{P}/test/xas-cell", "missing_context")]
    assert "site_count_basis" in res["excluded"][0]["reason"]
    # a bound is never ranked as its number: the rate per titrated site is at least 0.038 s-1
    ranked = _q(doc, spec, {"comparison": "scientific", "match": {"label": "CatalyticTest", "as": "test"},
                            "steps": [{"from": "test", "entries": "result_values", "kind": "turnover_frequency", "as": "tof"}],
                            "where": [{"var": "tof", "prop": "value", "op": "gt", "value": 0.03, "unit": "s-1"}],
                            "return": ["tof"]})
    assert sorted(r["values"]["tof"]["id"] for r in ranked["rows"]) == ["tof_per_step_site", "tof_per_titrated_site"]


def test_estimated_and_bounded_inventories_are_recorded_and_missing_context_stops_a_comparison(doc, spec):
    origins = {e["props"][k].get("origin") for e in doc["links"] if e["type"] == "HAS_SITE"
               for k in ("population_fraction", "site_density", "exposed_metal_count", "site_inventory") if k in e["props"]}
    assert {"derived", "computed", "assumed"} <= origins
    bounded = _link(doc, "HAS_SITE", "state/working", "site/zn-decorated-step", 1)["props"]["site_inventory"]
    assert bounded["bound"] == "upper" and bounded["value"] == 30
    assert _entry(doc, "test/xas-cell", "tof_per_titrated_site")["bound"] == "lower"

    plan = {"comparison": "scientific", "match": {"label": "CatalyticTest", "as": "test"},
            "steps": [{"from": "test", "entries": "result_values", "kind": "turnover_frequency", "as": "tof"}],
            "where": [{"var": "tof", "prop": "value", "op": "gt", "value": 0, "unit": "s-1"}], "return": ["tof"]}
    # a rate divided by at most 30 sites that does not say it is at least its quotient: reported, and left out
    d = copy.deepcopy(doc)
    _entry(d, "test/xas-cell", "tof_per_titrated_site").pop("bound")
    rep = pgraph.validate(d, spec_of(d))
    assert rep.errors == [] and any("divided by a one-sided bound (at most 30 µmol/g)" in w["message"] and "lower bound" in
                                    w["message"] for w in rep.warnings), rep.warnings
    res = _q(d, spec, plan)
    assert any("one-sided bound" in e["reason"] for e in res["excluded"])
    assert "tof_per_titrated_site" not in [r["values"]["tof"]["id"] for r in res["rows"]]
    # a count not reported leaves the rate divided by it out, never compared on an assumed number
    d = copy.deepcopy(doc)
    _link(d, "HAS_SITE", "state/working", "site/zn-decorated-step")["props"]["site_inventory"] = {
        "status": "not_reported", "missing_reason": "not_stated_in_source"}
    res = _q(d, spec, plan)
    assert "tof_per_step_site" not in [r["values"]["tof"]["id"] for r in res["rows"]]
    assert any("normalized_by" in e["reason"] and "not_reported" in e["reason"] for e in res["excluded"])


def test_a_rate_per_site_is_divided_by_a_count_never_by_a_share(doc):
    d = copy.deepcopy(doc)
    _entry(d, "test/xas-cell", "tof_per_step_site")["normalized_by"]["path"] = "/population_fraction"
    msgs = [e["message"] for e in pgraph.validate(d, spec_of(d)).errors]
    assert any("is a site_fraction, not a denominator of turnover_frequency (a site_count or a site_density)" in m
               for m in msgs), msgs
    # a site density per area divides a rate per area; its unit is a count per area
    c = quantities.contracts(spec_of(doc))
    assert c.dimension_name(c.read_unit("sites/nm2").vector) == "number_per_area (L-2)"
    assert c.kinds["turnover_frequency"]["denominator_kinds"] == ["site_count", "site_density"]
    assert [x["context"] for x in c.kinds["turnover_frequency"]["compare_by"]] == ["species", "site_count_basis"]


# ---------------------------------------------------------------- identity: specimens, models, formulations
def test_a_model_only_state_needs_no_specimen_and_keeps_its_model(doc, spec):
    computed = _node(doc, "state/computed-zn-step")
    assert _link(doc, "STATE_OF", "state/computed-zn-step", "model/cu211-zn")
    assert not [e for e in doc["links"] if e["type"] == "STATE_OF" and e["source"] == computed["id"]
                and _node(doc, e["target"].removeprefix(f"{P}/"))["label"] == "CatalystSample"]
    pop = _link(doc, "HAS_SITE", "state/computed-zn-step", "site/zn-decorated-step")["props"]
    for k in ("population_fraction", "site_density"):
        assert pop[k]["origin"] == "computed" and pop[k]["produced_by"] == f"{P}/computation/zn-at-steps"
    assert _link(doc, "USES_MODEL", "computation/zn-at-steps", "model/cu211-zn")
    assert _link(doc, "PREDICTS", "computation/zn-at-steps", "state/computed-zn-step")["props"]["compared_with"] == f"{P}/state/working"
    d = copy.deepcopy(doc)
    _link(d, "HAS_SITE", "state/computed-zn-step", "site/zn-decorated-step")["props"]["population_fraction"].pop("produced_by")
    assert any("a computed value names the experiment that produced it" in e["message"]
               for e in pgraph.validate(d, spec_of(d)).errors)


def test_a_formulation_level_count_adds_no_specimen(doc):
    f = _node(doc, "state/formulation-reduced")
    assert _link(doc, "STATE_OF", "state/formulation-reduced", "catalyst/cu-zno")
    count = _link(doc, "HAS_SITE", "state/formulation-reduced", "site/exposed-cu")["props"]["exposed_metal_count"]
    assert count["origin"] == "assumed" and count["qualifier"] == "approximate"
    assert {e["source"] for e in f["props"]["evidence"]} == {f"{P}/source/reply"}
    samples = [x for x in doc["nodes"] if x["label"] == "CatalystSample"]
    assert all(x["props"].get("batch_identifier") == "A" for x in samples)            # only the paper's batch A
    assert not [x for x in samples if any(e["source"] == f"{P}/source/reply" for e in x["props"].get("evidence") or [])]


# ---------------------------------------------------------------- assignments are claims
ASSIGNED = {"match": {"label": "Claim", "as": "claim"},
            "steps": [{"from": "claim", "edge": "ABOUT", "as": "component", "edge_as": "assigned",
                       "edge_where": [{"prop": "role", "op": "in", "value": ["active", "co_active"]}]}],
            "return": ["claim.name", "component.name", "assigned.role"]}


def _with_phase(dominance: str) -> dict:
    plan = copy.deepcopy(ASSIGNED)
    plan["steps"].append({"from": "component", "edge": "HAS_PHASE", "direction": "in", "to": "CatalystState", "as": "host",
                          "edge_as": "phase", "where": [{"prop": "id", "op": "eq", "value": f"{P}/state/working"}],
                          "edge_where": [{"prop": "dominance", "op": "eq", "value": dominance}]})
    return plan


def test_a_minority_phase_carries_an_assignment_and_abundance_brings_none(doc, spec):
    res = _q(doc, spec, _with_phase("minority"))
    assert _vals(res, "component.name") == ["ZnOx overlayer on Cu"]
    assert _q(doc, spec, _with_phase("majority"))["status"] == "no_matching_record"
    # the minority phase's assignment rests on evidence: what supports it names the results it rests on
    claim = f"{P}/claim/znox-steps-active"
    supports = [e for e in doc["links"] if e["type"] == "SUPPORTS" and e["target"] == claim]
    assert len(supports) == 2 and all(e["props"]["premise_refs"] and e["props"]["evidence"] for e in supports)
    refs = {(r["record"], r["path"]) for e in supports for r in e["props"]["premise_refs"]}
    assert (f"{P}/test/xas-cell", "/result_values/tof_per_step_site") in refs
    # bulk ZnO and Cu are the majority phases, and no claim calls them active
    majority = {e["target"] for e in doc["links"] if e["type"] == "HAS_PHASE" and e["source"] == f"{P}/state/working"
                and e["props"]["dominance"] == "majority"}
    active = {e["target"] for e in doc["links"] if e["type"] == "ABOUT" and e["props"]["role"] in ("active", "co_active")}
    assert majority == {f"{P}/material/cu", f"{P}/material/zno"} and not majority & active


def test_competing_assignments_and_a_spectator_stay_apart_citable_and_queryable(doc, spec):
    plan = copy.deepcopy(ASSIGNED)
    plan["steps"].append({"from": "claim", "edge": "CONTRADICTS", "direction": "in", "to": "Claim", "as": "rival",
                          "optional": True})
    plan["return"].append("rival.name")
    plan["evidence"] = True
    res = _q(doc, spec, plan)
    rows = {(r["values"]["claim.name"], r["values"]["component.name"]): r for r in res["rows"]}
    assert set(rows) == {("ZnOx overlayer and its Zn-decorated Cu steps active for methanol", "ZnOx overlayer on Cu"),
                         ("ZnOx overlayer and its Zn-decorated Cu steps active for methanol", "Zn-decorated Cu step site"),
                         ("Cu steps without Zn active for methanol (the reply)", "Cu step site without Zn")}
    assert {r["values"]["rival.name"] for r in res["rows"] if r["values"]["component.name"] != "Cu step site without Zn"} == \
        {"Cu steps without Zn active for methanol (the reply)"}
    for key, source in (("claim/cu-steps-active", "reply"), ("claim/znox-steps-active", "paper"),
                        ("claim/zno-spectator", "paper")):         # each claim cites its own passage
        assert {e["source"] for e in _node(doc, key)["props"]["evidence"]} == {f"{P}/source/{source}"}
    cited = {e["record"] for r in res["rows"] for e in r["evidence"]}
    assert {f"{P}/claim/cu-steps-active", f"{P}/claim/znox-steps-active"} <= cited
    spectator = copy.deepcopy(ASSIGNED)
    spectator["steps"][0]["edge_where"] = [{"prop": "role", "op": "eq", "value": "spectator"}]
    assert _vals(_q(doc, spec, spectator), "component.name") == ["wurtzite ZnO"]
    # the named roles say what each ABOUT target is to the claim
    roles = {e["props"]["role"] for e in doc["links"] if e["type"] == "ABOUT"}
    assert roles == {"active", "spectator", "state", "reaction", "product", "test"}


# ---------------------------------------------------------------- operando: an overlap is not a pairing
def test_an_overlap_alone_is_not_a_verified_pairing(doc):
    c = conformance(doc, spec_of(doc), by_record=True)["profiles"]["catalysis"]["records"]
    drifts, xas = c[f"{P}/characterization/drifts"], c[f"{P}/characterization/cu-k-xas"]
    assert drifts["evidence"]["working_test"]["found"]                          # it did overlap a run
    assert not drifts["evidence"]["paired_performance"]["found"] and not drifts["evidence"]["benchmarked_performance"]["found"]
    assert xas["evidence"]["paired_performance"]["found"] and xas["evidence"]["benchmarked_performance"]["found"]
    # the label stays as reported, whatever the checklist finds
    assert _node(doc, "characterization/drifts")["props"]["observation_mode"] == "operando"
    # a pairing stated in part (another specimen, or no measured performance) is no pairing
    for k, v in (("specimen", "same_batch"), ("timing", "sequential"), ("performance", "products_detected")):
        d = copy.deepcopy(doc)
        _link(d, "DURING", "characterization/cu-k-xas", "test/xas-cell")["props"][k] = v
        rec = conformance(d, spec_of(d), by_record=True)["profiles"]["catalysis"]["records"][f"{P}/characterization/cu-k-xas"]
        assert not rec["evidence"]["paired_performance"]["found"], k
    # a characterization during a treatment is not under working catalytic conditions
    d = copy.deepcopy(doc)
    _link(d, "DURING", "characterization/drifts", "test/drifts-cell")["target"] = f"{P}/treatment/reduction"
    rec = conformance(d, spec_of(d), by_record=True)["profiles"]["catalysis"]["records"][f"{P}/characterization/drifts"]
    assert not rec["evidence"]["working_test"]["found"]
    # an in-situ observation is asked for none of it
    assert not (c[f"{P}/characterization/co2-titration"].get("evidence") or {})


# ---------------------------------------------------------------- spectrum, fit and claim
def test_a_measured_spectrum_a_fitted_parameter_and_an_inferred_claim_stay_three_records(doc, spec):
    spectra, exafs, claim = _node(doc, "dataset/cu-k-spectra"), _node(doc, "analysis/exafs-first-shell"), \
        _node(doc, "claim/znox-steps-active")
    assert (spectra["label"], spectra["props"]["data_kind"]) == ("Dataset", "spectrum")
    assert (exafs["label"], exafs["props"]["analysis_kind"]) == ("Analysis", "spectral_fit")
    assert claim["label"] == "Claim" and claim["props"]["claim_status"] == "proposed"
    cn = exafs["props"]["results"]["cn_cu_zn"]
    assert cn["origin"] == "fitted" and cn["produced_by"] == exafs["id"] and cn["uncertainty"] == 0.4
    assert exafs["props"]["limitations"]
    support = _link(doc, "SUPPORTS", "analysis/exafs-first-shell", "claim/znox-steps-active")
    assert support["props"]["premise_refs"] == [{"record": exafs["id"], "path": "/results/cn_cu_zn"}]
    assert _link(doc, "HAS_OUTPUT", "characterization/cu-k-xas", "dataset/cu-k-spectra")
    # two fits of the one spectrum, each with its own limitations; the claim cites one
    fits = [e["source"] for e in doc["links"] if e["type"] == "HAS_INPUT" and e["target"] == spectra["id"]]
    assert sorted(fits) == [exafs["id"], f"{P}/analysis/xanes-lcf"]
    assert _node(doc, "analysis/xanes-lcf")["props"]["limitations"] != exafs["props"]["limitations"]
    # a fit without its method, results or limitations, or the data it fits, is reported by the checklist
    d = copy.deepcopy(doc)
    for k in ("method", "limitations"):
        _node(d, "analysis/xanes-lcf")["props"].pop(k)
    d["links"] = [e for e in d["links"] if not (e["type"] == "HAS_INPUT" and e["source"] == f"{P}/analysis/xanes-lcf")]
    rec = conformance(d, spec_of(d), by_record=True)["profiles"]["catalysis"]["records"][f"{P}/analysis/xanes-lcf"]
    assert not rec["evidence"]["fitted_data"]["found"]
    assert {"Analysis.method", "Analysis.limitations"} <= set(rec["missing"])


# ---------------------------------------------------------------- the schema change
def test_the_change_to_the_turnover_frequency_contract_is_breaking():
    old, new = spec_at("0.5.0"), pgraph.load_spec(GRAPH_MANIFEST)
    d = diff_specs(old, new)
    assert {"quantities.kinds.turnover_frequency is compared by site_count_basis",
            "quantities.kinds.turnover_frequency is compared by species",
            "quantities.kinds.turnover_frequency: its denominator names a site_count or a site_density only"} <= set(d["narrowed"])
    assert "edges.HAS_SITE.from + CatalystState" in d["loosened"]
    assert {"edges.HAS_SITE.population_fraction", "edges.HAS_SITE.site_inventory", "edges.DURING.performance",
            "quantities.kinds.site_count", "quantities.contexts.site_count_basis"} <= set(d["added"])
    # a denominator's kinds: a first list narrows, dropping it loosens, a kind more loosens and a kind less narrows
    out = {"added": [], "removed": [], "changed": [], "narrowed": [], "loosened": []}
    a, b = copy.deepcopy(new["quantities"]), copy.deepcopy(new["quantities"])
    b["kinds"]["turnover_frequency"]["denominator"]["kinds"] = ["site_count"]
    quantities.diff(a, b, out)
    assert out["narrowed"] == ["quantities.kinds.turnover_frequency: its denominator no longer names a site_density"]


def test_a_malformed_denominator_kind_never_loads():
    block = copy.deepcopy(pgraph.load_spec(GRAPH_MANIFEST)["quantities"])
    block["kinds"]["turnover_frequency"]["denominator"]["kinds"] = ["site_fraction"]
    with pytest.raises(ScaleError, match="a share is never a denominator"):
        quantities.Contracts(block)
    block["kinds"]["turnover_frequency"]["denominator"]["kinds"] = ["sites"]
    with pytest.raises(ScaleError, match="is not a declared kind"):
        quantities.Contracts(block)


def test_the_step_to_site_populations_rewrites_nothing_and_stops_on_what_it_cannot_map():
    old = load_doc(EXAMPLES / "scale-catal/driving-force-examples/electro.json")
    old["graph"]["schema_version"] = "0.5.0"
    new, log = pgraph_migrate.raise_version(old, "0.6.0", spec_at("0.6.0"))
    step = next(s for s in log["steps"] if s["from"] == "0.5.0")
    assert step["to"] == "0.6.0" and not step.get("changes")
    assert {k: v for k, v in new.items() if k != "graph"} == {k: v for k, v in old.items() if k != "graph"}
    # a turnover frequency divided by a share, valid by its dimension under 0.5.0, cannot be mapped
    bad = copy.deepcopy(old)
    t = next(x for x in bad["nodes"] if x["label"] == "CatalyticTest")
    bad["nodes"].append({"id": "ex:df-electro/variable/tof", "label": "Variable",
                         "props": {"name": "TOF", "scale": "quantitative", "quantity_kind": "turnover_frequency", "unit": "s-1",
                                   "origin": "synthetic"}})
    bad["links"].append({"id": "ex:df-electro/catalyst/cu/has-cu", "type": "HAS_COMPONENT", "source": "ex:df-electro/catalyst/cu",
                         "target": "ex:df-electro/species/ammonia", "props": {"origin": "synthetic", "role": "other",
                                                                             "fraction": {"status": "present", "value": 5, "unit": "%"}}})
    t["props"]["results"] = {"tof": {"status": "present", "value": 1, "unit": "s-1", "variable": "ex:df-electro/variable/tof",
                                     "target": "ex:df-electro/species/ammonia",
                                     "normalized_by": {"record": "ex:df-electro/catalyst/cu/has-cu", "path": "/fraction"}}}
    with pytest.raises(ScaleError, match="normalized_by names a composition_fraction"):
        pgraph_migrate.raise_version(bad, "0.6.0", spec_at("0.6.0"))


def test_turnover_frequencies_that_state_no_product_or_denominator_are_no_longer_compared_after_migration():
    """The one committed document with turnover frequencies (the kernel's meta-analysis example, pinned 0.2.0) stays
    valid when moved to 0.6.0, and its pooled rates, which state no product and no denominator, leave a scientific
    comparison as missing_context, where under 0.5.0 they were compared; an ordinary comparison is unchanged."""
    meta = load_doc(REPO / "core/examples/science-examples/d-meta-analysis.json")
    new = pgraph_migrate.raise_version(meta, "0.6.0", spec_at("0.6.0"))[0]
    rep = pgraph.validate(new, spec_of(new))
    assert rep.errors == [] and rep.warnings == []
    old = copy.deepcopy(new)
    old["graph"]["schema_version"] = "0.5.0"
    plan = {"comparison": "scientific", "match": {"label": "Experiment", "as": "e"},
            "where": [{"var": "e", "prop": "results.*[variable=ex:sk-d/variable/tof]", "op": "gt", "value": 0,
                       "unit": "1/s"}], "return": ["e.name"]}
    before, after = pgraph_query.run(old, spec_of(old), plan), pgraph_query.run(new, spec_of(new), plan)
    assert (before["status"], len(before["rows"])) == ("answered", 4)
    assert (after["status"], len(after["rows"])) == ("missing_context", 0)
    assert all("species" in e["reason"] for e in after["excluded"])
    plan.pop("comparison")
    assert len(pgraph_query.run(new, spec_of(new), plan)["rows"]) == 4


# ---------------------------------------------------------------- a field step into a link
def test_a_field_step_follows_a_denominator_into_its_link_and_says_why_it_cannot(doc, spec):
    base = {"match": {"label": "CatalyticTest", "as": "test"},
            "steps": [{"from": "test", "entries": "result_values", "kind": "turnover_frequency", "as": "tof"}],
            "return": ["tof"]}

    def step(**kw):
        plan = copy.deepcopy(base)
        plan["steps"].append({"from": "tof", "field": "normalized_by", "as": "x", **kw})
        return plan
    for kw, match in (({"link": "HAS_SITE"}, "end says which of its ends it binds"),
                      ({"edge_as": "y"}, "edge_as, edge_where and end follow a link"),
                      ({"link": "HAS_SITE", "end": "source", "direction": "in"}, "takes no direction")):
        with pytest.raises(ScaleError, match=match):
            _q(doc, spec, step(**kw))
    plan = copy.deepcopy(base)
    plan["steps"].append({"from": "tof", "field": "target", "link": "HAS_SITE", "end": "source", "as": "x"})
    with pytest.raises(ScaleError, match="only normalized_by names a link"):
        _q(doc, spec, plan)
    assert _q(doc, spec, step(link="NO_SUCH_EDGE", end="source"))["status"] == "schema_gap"
    # a field step without link meets a link: it is left out, saying how to follow it
    res = _q(doc, spec, step(to="CatalystState"))
    assert res["status"] == "missing_context"                                 # not evaluated: never "no match"
    left = next(s for s in res["coverage"]["steps"] if s.get("as") == "x")["left_out_by_reason"]
    assert left == {"names_a_link": 3, "not_curated": 2}
    # a link of another type than the step names is left out as such
    res = _q(doc, spec, step(link="HAS_PHASE", end="source"))
    assert next(s for s in res["coverage"]["steps"] if s.get("as") == "x")["left_out_by_reason"]["names_another_link"] == 3
    # its edge_where filters the link, and the link is cited
    res = _q(doc, spec, step(link="HAS_SITE", end="source", edge_as="count",
                             edge_where=[{"prop": "status", "op": "eq", "value": "asserted"}]))
    assert [r["values"]["tof"]["id"] for r in res["rows"]] == ["tof_per_exposed_cu"]
    assert res["coverage"]["link_types"] == ["HAS_SITE"]


def test_describe_prints_a_denominators_kinds():
    out = pgraph.describe(pgraph.load_spec(GRAPH_MANIFEST), [], "catalysis")
    tof = out["quantity_kinds"]["turnover_frequency"]
    assert tof["denominator_kinds"] == ["site_count", "site_density"] and tof["compared_by"] == ["species", "site_count_basis"]
    has_site = pgraph.describe(pgraph.load_spec(GRAPH_MANIFEST), ["HAS_SITE"], "catalysis")
    assert "CatalystState" in str(has_site)
