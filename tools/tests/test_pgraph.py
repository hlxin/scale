"""scale-graph: labeled property graphs in node-link JSON — the validator against the catalysis domain's
schema (domain/graph/scale-graph.yaml: the science kernel plus the catalysis domain file with its
one checklist) and its worked example (domain/examples/scale-graph/example.json), which is checked under
the version it pins (a later proposal that raises the head leaves it valid under that version)."""

import copy
import json
import shutil
from pathlib import Path

import pytest

from conftest import GRAPH_MANIFEST, HEAD_VERSION, REPO, as_project_data, spec_of
from scale import pgraph
from scale.util import ScaleError, load_doc

EXAMPLES = REPO / "domain/examples/scale-graph"


@pytest.fixture(scope="module")
def spec():
    """The schema the worked example pins."""
    return spec_of(load_doc(EXAMPLES / "example.json"))


@pytest.fixture(scope="module")
def head():
    return pgraph.load_spec(GRAPH_MANIFEST)


@pytest.fixture()
def example():
    """The worked example as a project's research data (in memory; the committed document is synthetic and public)."""
    return as_project_data(load_doc(EXAMPLES / "example.json"))


def _reindex(doc):
    """Re-derive REPORTED_IN links after a test adds evidence."""
    doc["links"] = [l for l in doc["links"] if l["type"] != "REPORTED_IN"] + pgraph.derive_reported_in(doc)


def errors(doc, spec, texts=None):
    return [e["message"] for e in pgraph.validate(doc, spec, texts).errors]


def test_the_schema_reads_the_governance_registry(spec, tmp_path):
    assert "exmpl" in spec["extension_prefixes"]                 # governance/registry/extension-prefixes.yaml
    repo = tmp_path / "repo"                                     # inside a checkout, a missing registry is an error
    shutil.copytree(REPO / "core/graph", repo / "core/graph")
    shutil.copytree(GRAPH_MANIFEST.parent, repo / "domain/graph")
    shutil.copy2(REPO / "scale-release.yaml", repo / "scale-release.yaml")
    (repo / "releases").mkdir()
    with pytest.raises(ScaleError, match="no extension-prefix registry"):
        pgraph.load_spec(repo / "domain/graph/scale-graph.yaml")


def test_the_default_schema_is_the_catalysis_domains(tmp_path):
    assert pgraph.spec_path(REPO) == GRAPH_MANIFEST == REPO / "domain/graph/scale-graph.yaml"   # the one domain's schema
    assert pgraph.spec_for(REPO, HEAD_VERSION) == GRAPH_MANIFEST
    with pytest.raises(ScaleError, match="is not a version this repository holds"):
        pgraph.spec_for(REPO, "0.0.9")
    repo = tmp_path / "repo"
    repo.mkdir()
    doc = {"graph": {"follows_domains": ["catalysis"]}, "nodes": []}
    with pytest.raises(ScaleError, match=r"no scale-graph schema found: .* domain/DOMAIN.yaml \(pass --spec\)"):
        pgraph.spec_path(repo, doc=doc)                                   # no domain/: give the schema
    assert pgraph.spec_path(repo, "x/explicit.yaml", doc) == Path("x/explicit.yaml")


def test_candidate_spec_is_found_and_provisional(head):
    spec = head
    assert spec["schema"] == "scale-graph" and spec["status"] == "candidate" and spec["maturity"] == "provisional"
    assert spec["version"] == HEAD_VERSION
    # 0.1.0 has 55 labels and 97 edge types; later proposals only add (labels and edge types are deprecated, never deleted)
    assert len(spec["nodes"]) >= 55 and len(spec["edges"]) >= 97
    assert {"Person", "Institution", "CatalyticTest", "Characterization", "Instrument"} <= set(spec["nodes"])
    assert not {"Agent", "Run", "Study", "Observation", "Phase"} & set(spec["nodes"])
    assert {"Sample", "Material", "CatalystSample"} <= set(spec["nodes"])      # CatalystSample is_a Sample
    assert {"Catalyst", "ActiveSite", "StructureModel"} <= set(spec["nodes"])
    assert not {"Support", "Promoter", "Precursor", "Binder", "Inhibitor"} & set(spec["nodes"])   # roles are on edges
    for name, e in spec["edges"].items():
        assert set(e["from"]) <= set(spec["nodes"]) and set(e["to"]) <= set(spec["nodes"]), name


def test_worked_example_validates(spec, example):
    assert errors(example, spec) == []


MODULES = {"TimeSeries", "ProcedureStep", "ElementaryStep", "Mechanism", "Descriptor", "Process", "UnitOperation",
           "Stream", "Assessment", "Flow", "Scenario", "PriceQuote", "PolicyInstrument", "Campaign", "Objective",
           "Constraint", "Parameter", "Recommendation", "Command", "ControlLoop", "Intervention"}


def test_datetimes_and_recorded_origin(spec, example):
    test = _node(example, "ex:exmpl/thermo/test/zno-run-1")["props"]
    test["started_at"] = "2026-09-01 08:00"
    assert any("ISO 8601 date-time" in m for m in errors(example, spec))
    test["started_at"] = "2026-09-01T08:00:00Z"
    assert errors(example, spec) == []
    sp = _node(example, "ex:exmpl/thermo/species/zno")["props"]
    sp["origin"] = "recorded"
    assert any("a recorded record carries recorded_at" in m for m in errors(example, spec))
    sp["recorded_at"] = "2026-09-27T10:00:00Z"
    assert errors(example, spec) == []


def _node(doc, nid):
    return next(n for n in doc["nodes"] if n["id"] == nid)


def test_value_objects_follow_their_rules(spec, example):
    test = _node(example, "ex:exmpl/thermo/test/zno-run-1")["props"]
    test["temperature"] = {"status": "present", "value": 400}                                  # no unit
    test["pressure"] = {"status": "not_reported", "value": 180, "unit": "atm"}                 # missing but valued
    test["duration"] = {"status": "present", "lower": 5, "upper": 2, "unit": "h"}             # inverted range
    test["space_velocity"] = {"status": "present", "value": 1, "unit": "h-1", "precision": 2}  # unknown field
    msgs = errors(example, spec)
    assert any("temperature: a present number needs a unit" in m for m in msgs)
    assert any("pressure: status not_reported carries no value" in m for m in msgs)
    assert any("duration: lower exceeds upper" in m for m in msgs)
    assert any("unknown field 'precision'" in m for m in msgs)


def test_ranges_and_bounds_are_values(spec, example):
    test = _node(example, "ex:exmpl/thermo/test/zno-run-1")["props"]
    test["temperature"] = {"status": "present", "lower": 250, "upper": 260, "unit": "°C", "as_reported": "250–260°C"}
    test["results"]["co2_increase"] = {"status": "present", "value": 1, "unit": "%", "bound": "upper"}
    assert errors(example, spec) == []


def test_edges_are_typed_by_endpoints_and_properties(spec, example):
    bad = copy.deepcopy(example)
    link = next(l for l in bad["links"] if l["type"] == "USES_CATALYST")
    link["target"] = "ex:exmpl/thermo/catalyst/zno"                        # a test uses a CatalystSample, not a Catalyst
    link["props"]["state"] = "glowing"                             # not in the enumeration
    link["props"]["temperature"] = {"status": "present", "value": 1, "unit": "K"}   # not declared for this edge
    msgs = errors(bad, spec)
    assert any("USES_CATALYST target must be ['CatalystSample'], got Catalyst" in m for m in msgs)
    assert any("'glowing' is not one of" in m for m in msgs)
    assert any("property 'temperature' is not declared" in m for m in msgs)


def test_references_and_evidence_resolve(spec, example):
    test = _node(example, "ex:exmpl/thermo/test/zno-run-1")["props"]
    test["evidence"].append({"source": "ex:nowhere", "locator": "p. 1", "kind": "text"})
    test["evidence"].append({"source": "ex:exmpl/thermo/source/invented-paper", "kind": "text"})
    msgs = errors(example, spec)
    assert any("reference 'ex:nowhere' does not resolve" in m for m in msgs)
    assert any("evidence needs locator" in m for m in msgs)


def test_quotes_are_checked_verbatim(spec, example):
    mat = _node(example, "ex:exmpl/thermo/catalyst/zno")["props"]
    mat["evidence"][0]["quote"] = "zinc oxide was prepared by precipitation"
    src = "ex:exmpl/thermo/source/invented-paper"
    assert errors(example, spec, {src: "…the zinc  oxide was prepared by\nprecipitation from…"}) == []
    assert any("not found verbatim" in m for m in errors(example, spec, {src: "an unrelated text"}))


def test_synthetic_records_stay_out_of_research_graphs(spec, example):
    _node(example, "ex:exmpl/thermo/catalyst/zno")["props"]["origin"] = "synthetic"
    assert any("synthetic record inside a research document" in m for m in errors(example, spec))


def test_flat_export_has_primitive_properties(example):
    lines = [json.loads(x) for x in pgraph.to_neo4j_jsonl(example).splitlines()]
    test = next(x for x in lines if x["id"] == "ex:exmpl/thermo/test/zno-run-1")
    assert test["properties"]["temperature_value"] == 380 and test["properties"]["temperature_unit"] == "°C"
    assert test["properties"]["results_methanol_production_value"] == 52
    rel = next(x for x in lines if x.get("label") == "USES_CATALYST")
    assert rel["properties"]["state"] == "fresh" and rel["properties"]["amount_value"] == 40
    for x in lines:          # Neo4j accepts primitives and lists of primitives
        for v in x["properties"].values():
            assert not isinstance(v, dict) and not (isinstance(v, list) and any(isinstance(i, (dict, list)) for i in v))


# ---------------------------------------------------------------- stewardship
LAB, OTHER, PROJ = "ex:exmpl/org/example-lab", "ex:exmpl/org/other", "ex:exmpl/project/examples"   # the example's


def _viewable(doc, viewer, date="2026-09-27"):
    return {n["id"] for n in pgraph.filter_for(doc, viewer, date)["nodes"]}


def test_research_graphs_declare_stewardship(spec, example):
    del example["graph"]["stewardship"]
    assert any("declares stewardship" in m for m in errors(example, spec))


def test_stewardship_is_inherited_and_overridden(spec, example):
    test = "ex:exmpl/thermo/test/zno-run-1"
    assert pgraph.effective_stewardship(example, _node(example, test))["access"] == "project"
    _node(example, test)["props"]["stewardship"] = {"access": "institution"}
    st = pgraph.effective_stewardship(example, _node(example, test))
    assert st["access"] == "institution" and st["project"] == PROJ           # other fields inherited
    assert errors(example, spec) == []


def test_viewers_see_by_project_institution_and_public(example):
    test = "ex:exmpl/thermo/test/zno-run-1"
    assert test in _viewable(example, [LAB])                                    # the lab participates in the project
    assert _viewable(example, []) == {"ex:exmpl/thermo/source/invented-paper"}             # the public: only the public source
    _node(example, test)["props"]["stewardship"] = {"access": "institution", "contributed_by": [OTHER]}
    assert test not in _viewable(example, [LAB])                                # another institution's record
    assert test in _viewable(example, [OTHER])
    kept = pgraph.filter_for(example, [], "2026-09-27")
    assert all(l["source"] in {n["id"] for n in kept["nodes"]} for l in kept["links"])


def test_members_inherit_their_institutions_access(example):
    example["nodes"].append({"id": "ex:exmpl/thermo/person/a", "label": "Person", "props": {"name": "A. Researcher",
                                                                                    "origin": "curated"}})
    example["links"].append({"id": "ex:exmpl/thermo/link/m", "source": "ex:exmpl/thermo/person/a", "target": LAB, "type": "MEMBER_OF",
                             "props": {"origin": "curated"}})
    assert "ex:exmpl/thermo/test/zno-run-1" in _viewable(example, ["ex:exmpl/thermo/person/a"])


def test_embargo_opens_on_its_date(spec, example):
    test = "ex:exmpl/thermo/test/zno-run-1"
    _node(example, test)["props"]["stewardship"] = {"access": "embargoed", "embargo_until": "2027-06-30",
                                                   "access_after_embargo": "public"}
    assert errors(example, spec) == []
    assert test not in _viewable(example, [], "2027-06-30") and test in _viewable(example, [LAB], "2027-06-30")
    assert test in _viewable(example, [], "2027-07-01")
    _node(example, test)["props"]["stewardship"] = {"access": "embargoed"}
    assert any("embargoed access needs embargo_until" in m for m in errors(example, spec))


def test_registry_supplies_institutions_software_and_projects():
    from scale.util import load_yaml
    reg = load_yaml(REPO / "governance/registry/stewardship.yaml")
    steward = "scale:org/scale-researchers"                               # the registry's own entry
    nodes, links = pgraph.registry_records(reg, {steward})
    assert [n["label"] for n in nodes if n["id"] == steward] == ["Institution"] and links == []
    # a project with its funder and participants (synthetic entries added to the registry's own)
    proj, funder = "scale:project/exmpl-project", "scale:org/exmpl-funder"
    reg = {**reg, "institutions": [*reg["institutions"], {"id": funder, "name": "Example funder",
                                                          "institution_kind": "funding_agency"}],
           "projects": [{"id": proj, "name": "Example project", "funded_by": funder,
                         "participants": [{"member": steward, "role": "data_provider"},
                                          {"member": funder, "role": "data_provider"}]}]}
    nodes, links = pgraph.registry_records(reg, {proj})
    ids = {n["id"] for n in nodes}
    assert {proj, steward, funder} <= ids
    assert {l["type"] for l in links} == {"FUNDED_BY", "PARTICIPATES_IN"}
    with pytest.raises(Exception, match="not in the stewardship registry"):
        pgraph.registry_records(reg, {"scale:org/unknown"})


def test_characterization_measures_a_sample_in_a_state(spec, example):
    example["nodes"].append({"id": "ex:exmpl/thermo/char/bet", "label": "Characterization", "props": {
        "name": "BET surface area of the ZnO charge", "technique": "BET", "origin": "reported",
        "results": {"specific_surface_area": {"status": "present", "value": 40, "unit": "m2/g"}},
        "evidence": [{"source": "ex:exmpl/thermo/source/invented-paper", "locator": "p. 3", "kind": "text"}]}})
    example["nodes"].append({"id": "ex:exmpl/thermo/instrument/sorption", "label": "Instrument", "props": {
        "name": "sorption apparatus", "instrument_kind": "volumetric sorption apparatus", "origin": "reported",
        "evidence": [{"source": "ex:exmpl/thermo/source/invented-paper", "locator": "p. 3", "kind": "text"}]}})
    example["links"] += [
        {"id": "ex:exmpl/thermo/link/c1", "source": "ex:exmpl/thermo/char/bet", "target": "ex:exmpl/thermo/catalyst-sample/zno-40cc", "type": "CHARACTERIZES",
         "props": {"state": "reduced", "origin": "reported"}},
        {"id": "ex:exmpl/thermo/link/c2", "source": "ex:exmpl/thermo/char/bet", "target": "ex:exmpl/thermo/instrument/sorption",
         "type": "USES_INSTRUMENT", "props": {"origin": "reported"}}]
    _reindex(example)
    assert errors(example, spec) == []
    bad = copy.deepcopy(example)
    next(l for l in bad["links"] if l["id"] == "ex:exmpl/thermo/link/c1")["target"] = "ex:exmpl/thermo/catalyst/zno"                 # characterizes a Sample, not a Catalyst
    del _node(bad, "ex:exmpl/thermo/char/bet")["props"]["technique"]
    msgs = errors(bad, spec)
    assert any("CHARACTERIZES target must be ['Sample', 'CatalystSample', 'Electrode', 'Photoelectrode', 'ActiveSite']" in m for m in msgs)
    assert any("missing required property 'technique'" in m for m in msgs)


def test_computed_values_name_their_calculation(spec, example):
    example["nodes"].append({"id": "ex:exmpl/thermo/computation/eq", "label": "Computation", "props": {
        "name": "equilibrium screen", "task": "equilibrium yield", "origin": "computed"}})
    res = _node(example, "ex:exmpl/thermo/test/zno-run-1")["props"]["results"]
    res["equilibrium_carbon_yield"] = {"status": "present", "value": 13.9, "unit": "%", "origin": "computed",
                                       "produced_by": "ex:exmpl/thermo/computation/eq"}
    assert errors(example, spec) == []
    del res["equilibrium_carbon_yield"]["produced_by"]
    assert any("a computed value names the experiment that produced it" in m for m in errors(example, spec))


def test_reported_in_follows_evidence(spec, example):
    assert errors(example, spec) == []
    example["links"] = [l for l in example["links"] if not (l["type"] == "REPORTED_IN" and l["source"] == "ex:exmpl/thermo/catalyst-sample/zno-40cc")]
    assert any("no REPORTED_IN link" in m for m in errors(example, spec))
    _reindex(example)
    example["links"].append({"id": "ex:exmpl/thermo/link/x", "source": "ex:exmpl/thermo/feed/co-3h2", "target": "ex:exmpl/thermo/source/invented-paper",
                             "type": "REPORTED_IN", "props": {"origin": "curated"}})
    assert any("duplicate REPORTED_IN" in m or "not backed" in m for m in errors(example, spec))


def test_roles_are_on_edges_not_labels(spec, example):
    """A substance in a role (support, promoter) is HAS_COMPONENT with that role, not a role label."""
    example["links"].append({"id": "ex:exmpl/thermo/link/s1", "source": "ex:exmpl/thermo/catalyst/zno", "target": "ex:exmpl/thermo/species/zno",
                             "type": "HAS_COMPONENT", "props": {"role": "support", "origin": "curated"}})
    assert errors(example, spec) == []
    example["nodes"].append({"id": "ex:exmpl/thermo/support/zno", "label": "Support", "props": {"name": "ZnO support", "origin": "curated"}})
    assert any("unknown node label 'Support'" in m for m in errors(example, spec))


def test_material_is_the_solid_state_identity(spec, example):
    """One ChemicalSpecies (Al2O3), two Materials (alpha, gamma); a catalyst has a phase, XRD detects one."""
    example["nodes"] += [
        {"id": "ex:exmpl/thermo/material/al2o3-gamma", "label": "Material", "props": {"name": "gamma-alumina", "formula": "Al2O3",
                                                                        "polymorph": "gamma", "crystallinity": "crystalline",
                                                                        "origin": "curated"}},
        {"id": "ex:exmpl/thermo/material/al2o3-alpha", "label": "Material", "props": {"name": "alpha-alumina", "formula": "Al2O3",
                                                                        "polymorph": "alpha", "structure_type": "corundum",
                                                                        "identifiers": {"materials_project": "mp-1143"},
                                                                        "origin": "curated"}}]
    example["links"].append({"id": "ex:exmpl/thermo/link/p1", "source": "ex:exmpl/thermo/catalyst/zno", "target": "ex:exmpl/thermo/material/al2o3-gamma",
                             "type": "HAS_PHASE", "props": {"status": "hypothesized", "origin": "curated"}})
    assert errors(example, spec) == []
    example["links"].append({"id": "ex:exmpl/thermo/link/p2", "source": "ex:exmpl/thermo/catalyst/zno", "target": "ex:exmpl/thermo/species/zno",
                             "type": "HAS_PHASE", "props": {"origin": "curated"}})
    assert any("HAS_PHASE target must be ['Material']" in m for m in errors(example, spec))


def test_authors_have_order_and_role(spec, example):
    example["nodes"].append({"id": "ex:exmpl/thermo/person/doe-j-q", "label": "Person", "props": {
        "name": "Jane Q. Doe", "surname": "Doe", "given_names": "Jane Q.", "name_variants": ["J. Q. Doe", "Jane Q. Doe"],
        "origin": "reported", "evidence": [{"source": "ex:exmpl/thermo/source/invented-paper", "locator": "PDF page 1 (byline)", "kind": "text"}]}})
    example["links"].append({"id": "ex:exmpl/thermo/link/a1", "source": "ex:exmpl/thermo/source/invented-paper", "target": "ex:exmpl/thermo/person/doe-j-q",
                             "type": "AUTHORED_BY", "props": {"role": "author", "position": 1, "origin": "reported"}})
    _reindex(example)
    assert errors(example, spec) == []
    next(l for l in example["links"] if l["id"] == "ex:exmpl/thermo/link/a1")["props"]["position"] = "first"
    assert any("position: expected an integer" in m for m in errors(example, spec))


# ------------------------------------------------------------------ conformance and extension keys
def _conf(doc, spec, ref="catalysis"):
    rep = pgraph.validate(doc, spec)
    return rep, (rep.conformance or {}).get("profiles", {}).get(ref)


def test_conformance_is_reported_apart_from_validity(spec, example):
    rep, c = _conf(example, spec)
    assert rep.errors == [] and c["conformant"] and c["nodes_checked"] == 2
    assert "CatalyticTest -IN_REACTOR->" in c["missing_recommended"]
    test = _node(example, "ex:exmpl/thermo/test/zno-run-1")["props"]
    test["pressure"] = {"status": "not_reported"}
    rep, c = _conf(example, spec)
    assert rep.errors == [] and not c["conformant"]                      # valid, but not conformant
    assert any("pressure is declared not_reported" in v["message"] for v in c["violations"])
    del test["pressure"]
    assert any("pressure is missing" in v["message"] for v in _conf(example, spec)[1]["violations"])


def test_extension_keys_follow_optimade_style(spec, example):
    test = _node(example, "ex:exmpl/thermo/test/zno-run-1")["props"]
    test["_exmpl_run_sheet"] = "p. 12"
    assert errors(example, spec) == []
    test["_zz_run_sheet"] = "p. 12"
    assert errors(example, spec) == []
    assert any("unregistered prefix 'zz'" in w["message"] for w in pgraph.validate(example, spec).warnings)
    test["_bad"] = 1
    assert any("must be _<prefix>_<name>" in m for m in errors(example, spec))


def test_required_link_properties_are_enforced():
    """An edge type's required properties are checked on every link of that type (SAME_WORK_AS needs its relation)."""
    doc = load_doc(REPO / "tools/tests/fixtures/source-lifecycle/pass-preprint-of.json")
    head = spec_of(doc)                                     # the schema the fixture pins
    assert pgraph.validate(doc, head).errors == []
    links = [e for e in doc["links"] if e["type"] == "SAME_WORK_AS"]
    assert links and head["edges"]["SAME_WORK_AS"]["required"] == ["relation"]
    for e in links:
        del e["props"]["relation"]
    assert any("missing required property 'relation'" in e["message"] for e in pgraph.validate(doc, head).errors)


def test_a_query_returns_the_properties_of_a_bound_link(head):
    """A step's edge_as binds the link it follows, and return reads that link's properties (the role an electrode plays)."""
    from scale import pgraph_query
    doc = load_doc(EXAMPLES / "driving-force-examples/electro.json")
    plan = {"match": {"label": "CatalyticTest", "as": "t"},
            "steps": [{"from": "t", "edge": "USES_ELECTRODE", "to": "Electrode", "as": "e", "edge_as": "u"}],
            "return": ["t.name", "e.name", "u.role"]}
    res = pgraph_query.run(doc, head, plan)
    roles = {r["values"]["u.role"] for r in res["rows"]}
    assert res["status"] == "answered" and {"working", "counter"} <= roles, res
    gap = pgraph_query.run(doc, head, {**plan, "return": ["u.no_such"]})
    assert gap["status"] == "schema_gap" and "USES_ELECTRODE.no_such is not declared" in gap["schema_gaps"]


def test_reported_in_links_of_sources_ending_alike_get_distinct_ids():
    """A record citing ex:a/paper and ex:b/paper gets two REPORTED_IN links with distinct ids (the sources' whole ids);
    one citing a single source keeps the short id."""
    ev = lambda src: {"source": src, "locator": "p. 1", "kind": "text", "quote": "q"}          # noqa: E731
    doc = {"nodes": [{"id": "ex:t/claim/1", "label": "Claim", "props": {"evidence": [ev("ex:a/paper"), ev("ex:b/paper")]}},
                     {"id": "ex:t/claim/2", "label": "Claim", "props": {"evidence": [ev("ex:a/paper")]}}], "links": []}
    links = pgraph.derive_reported_in(doc)
    ids = [x["id"] for x in links]
    assert len(ids) == len(set(ids)) == 3
    assert set(ids) == {"ex:t/claim/1/reported-in/ex:a/paper", "ex:t/claim/1/reported-in/ex:b/paper",
                        "ex:t/claim/2/reported-in/paper"}


def test_a_long_chain_is_checked_for_cycles_without_recursion():
    """The cycle check of PART_OF, PRECEDES, HAS_PART and REVISES follows a chain of thousands of links (it recursed,
    and a valid chain of about a thousand failed), and still names a cycle by its path."""
    import sys
    from scale.pgraph_science import _cyclic
    n = sys.getrecursionlimit() * 3
    chain = [(f"ex:t/step/{i}", f"ex:t/step/{i + 1}") for i in range(n)]
    assert _cyclic(chain) == []
    back = _cyclic(chain + [(f"ex:t/step/{n}", "ex:t/step/0")])
    assert len(back) == 1 and back[0].startswith("ex:t/step/0 -> ex:t/step/1 -> ") and back[0].endswith(" -> ex:t/step/0")


def test_a_value_that_is_not_a_finite_number_is_an_error():
    """NaN and infinity (which Python's JSON reader and YAML accept) are no numbers a source reports: a valid test
    whose temperature is made NaN, or infinite, fails validation, naming the path."""
    import copy
    from conftest import EXAMPLES, GRAPH_MANIFEST
    spec = pgraph.load_spec(GRAPH_MANIFEST)
    doc = load_doc(EXAMPLES / "scale-graph/example.json")
    assert pgraph.validate(doc, spec).errors == []
    test = next(n for n in doc["nodes"] if n["label"] == "CatalyticTest")
    for bad in (float("nan"), float("inf"), float("-inf")):
        d = copy.deepcopy(doc)
        t = next(n for n in d["nodes"] if n["id"] == test["id"])
        t["props"]["temperature"] = {**t["props"]["temperature"], "value": bad}
        msgs = [(e["record"], e["message"]) for e in pgraph.validate(d, spec).errors]
        assert (test["id"], "props.temperature.value is not a finite number (NaN or infinity): a value is a number "
                            "the source states, or a status") in msgs, bad

