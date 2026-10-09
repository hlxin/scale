"""Driving forces in the catalysis domain's one schema: the catalysis domain file holds the vocabulary of every driving
force, and its one checklist applies its items for a catalytic test by the driving forces the test lists (``when``
cases on ``driving_forces``). Documents follow it as ``follows_domains: ["catalysis"]``.

The examples are checked under the version they pin (a later proposal that raises the head leaves them valid under
it); the tests of the head's shape read the head manifest, and never spell its version."""

import copy

import pytest

from conftest import CATALYSIS, GRAPH_MANIFEST, HEAD_VERSION, REPO, spec_of
from scale import layout, pgraph
from scale.pgraph_profiles import domain_contract
from scale.util import load_doc, load_yaml

X = CATALYSIS / "examples/scale-graph"
EXAMPLES = [X / "example.json"] + sorted((X / "driving-force-examples").glob("*.json"))
assert len(EXAMPLES) == 10, f"driving-force examples are missing from {X}"
FORCES = {"thermo", "electrothermo", "electro", "photo", "plasma"}
EQUILIBRIUM = ["equilibrium_estimate", "equilibrium_measurement"]


@pytest.fixture(scope="module")
def spec():
    """The schema the examples pin (they all pin one version, checked below)."""
    return spec_of(_doc("example.json"))


@pytest.fixture(scope="module")
def head():
    return pgraph.load_spec(GRAPH_MANIFEST)


def _doc(name: str) -> dict:
    return load_doc(X / name if name == "example.json" else X / "driving-force-examples" / name)


def _node(doc: dict, local: str) -> dict:
    return next(n for n in doc["nodes"] if n["id"].endswith("/" + local))


def _violations(doc: dict, spec: dict) -> list[str]:
    rep = pgraph.validate(doc, spec)
    assert rep.errors == [], rep.errors                         # a checklist never makes a document invalid
    return [v["message"] for v in rep.conformance["profiles"]["catalysis"]["violations"]]


# ---------------------------------------------------------------- one domain file, one checklist
def test_the_schema_is_the_kernel_and_one_domain_file_with_its_checklist(head):
    spec = head
    man = load_yaml(GRAPH_MANIFEST)                                           # domain/graph/scale-graph.yaml
    assert spec["version"] == HEAD_VERSION and man["domains"] == ["catalysis.yaml"] and "modules" not in man
    assert layout.manifest_kernel(GRAPH_MANIFEST).resolve() == (REPO / "core/graph/kernel.yaml").resolve()
    assert "extensions" not in man and "profiles" not in man
    assert sorted(p.name for p in GRAPH_MANIFEST.parent.glob("*.yaml")) == ["catalysis.yaml", "scale-graph.yaml"]
    assert set(spec["domains"]) == set(spec["profiles"]) == {"catalysis"}     # the checklist is named after the domain
    c = spec["profiles"]["catalysis"]
    # one version: the checklist and the catalysis file report the manifest's; the file itself carries none
    assert c["driving_forces"] == [] and c["version"] == spec["modules"]["catalysis"]["version"] == HEAD_VERSION
    assert "version" not in load_yaml(GRAPH_MANIFEST.parent / "catalysis.yaml")
    assert load_yaml(CATALYSIS / "DOMAIN.yaml")["graph"] == {"manifest": "graph/scale-graph.yaml"}


def test_the_domain_file_holds_the_vocabulary_of_every_driving_force(head):
    """The catalysis file holds the terms of every driving force: its labels, each with its description, and the
    properties of a catalytic test that each force needs."""
    cat = load_yaml(GRAPH_MANIFEST.parent / "catalysis.yaml")
    assert all(v.get("description") for v in cat["nodes"].values())
    assert head["nodes"]["ElectricHeater"]["ancestors"][0] == "Heater"
    props = head["nodes"]["CatalyticTest"]["properties"]
    assert {props[k]["added_by"] for k in ("electrode_potential", "irradiance", "heating_power", "photocurrent_density",
                                           "light_induced_temperature_rise")} == {"catalysis"}
    assert set(props["driving_forces"]["items"]["values"]) >= FORCES


# ---------------------------------------------------------------- each driving force's items, enforced where it is listed
def _drop_prop(prop):
    return lambda doc, t: t["props"].pop(prop)


def _drop_edge(typ):
    def mutate(doc, t):
        doc["links"] = [e for e in doc["links"] if not (e["type"] == typ and e["source"] == t["id"])]
    return mutate


def _set(prop, value):
    return lambda doc, t: t["props"].__setitem__(prop, value)


CASES = [   # (example, test, its forces, mutation, the violation it causes)
    ("example.json", "test/zno-run-1", ["thermo"], _drop_prop("temperature"), "required CatalyticTest.temperature is missing"),
    ("example.json", "test/zno-run-1", ["thermo"], _drop_edge("FED_WITH"), "required edge FED_WITH is missing"),
    ("electrothermo.json", "test/joule", ["electrothermo"], _drop_prop("pressure"), "required CatalyticTest.pressure is missing"),
    ("electrothermo.json", "test/joule", ["electrothermo"], _drop_prop("heating_mode"), "required CatalyticTest.heating_mode is missing"),
    ("electrothermo.json", "test/joule", ["electrothermo"], _set("heating_mode", "external_furnace"),
     "heating_mode 'external_furnace' is not one of"),
    ("electro.json", "test/m03", ["electro"], _drop_prop("control_mode"), "required CatalyticTest.control_mode is missing"),
    ("electro.json", "test/m03", ["electro"], _drop_edge("IN_ELECTROLYTE"), "required edge IN_ELECTROLYTE is missing"),
    ("photo.json", "test/light", ["photo"], _drop_prop("illumination"), "required CatalyticTest.illumination is missing"),
    ("photo.json", "test/light", ["photo"], _drop_edge("ILLUMINATED_BY"), "required edge ILLUMINATED_BY is missing"),
    ("plasma.json", "test/plasma-catalyst", ["plasma"], _drop_edge("USES_PLASMA"), "required edge USES_PLASMA is missing"),
    ("photothermo.json", "test/light", ["photo", "thermo"], _drop_prop("temperature_measured_at"),
     "required CatalyticTest.temperature_measured_at is missing"),
    ("photoelectro.json", "test/light-1v23", ["photo", "electro"], _drop_prop("light_absorber"),
     "required CatalyticTest.light_absorber is missing"),
    ("electrophoto.json", "test/light", ["electro", "photo"], _set("light_absorber", "catalyst"),
     "light_absorber 'catalyst' is not one of"),
]


@pytest.mark.parametrize("name, test, forces, mutate, message", CASES,
                         ids=[f"{c[0].removesuffix('.json')}-{c[4].split()[-3] if 'missing' in c[4] else c[4].split()[0]}"
                              for c in CASES])
def test_each_driving_force_case_is_enforced_where_its_forces_are_listed(spec, name, test, forces, mutate, message):
    doc = _doc(name)
    t = _node(doc, test)
    assert t["props"]["driving_forces"] == forces and not [m for m in _violations(doc, spec) if message in m]
    mutate(doc, t)
    assert [m for m in _violations(doc, spec) if message in m], message      # non-conformant, still valid
    t["props"]["driving_forces"] = ["other"]                                  # the case no longer applies
    assert not [m for m in _violations(doc, spec) if message in m]


def test_combined_forces_get_every_items_of_each_and_single_forces_only_their_own(spec):
    doc = _doc("photoelectro.json")                                           # light+potential, potential alone, light alone
    main, dark, ocp = (_node(doc, x) for x in ("test/light-1v23", "test/dark-1v23", "test/light-ocp"))
    assert "light_absorber" not in dark["props"] and "light_absorber" not in ocp["props"] and _violations(doc, spec) == []
    main["props"].pop("control_mode"), main["props"].pop("illumination")
    v = _violations(doc, spec)
    assert "required CatalyticTest.control_mode is missing" in v and "required CatalyticTest.illumination is missing" in v
    doc = _doc("photothermo.json")
    _node(doc, "test/dark")["props"].pop("temperature_measured_at")         # thermo alone: a should item, not a must
    assert _violations(doc, spec) == []
    doc = _doc("electrothermo.json")                                          # electrothermal: the thermal items, not the electro ones
    joule = _node(doc, "test/joule")
    assert "control_mode" not in joule["props"] and _violations(doc, spec) == []


def test_records_without_driving_forces_have_their_own_items(spec):
    doc = _doc("plasma.json")
    src = next(n for n in doc["nodes"] if n["label"] == "PlasmaSource")
    src["props"].pop("discharge_kind")
    assert "required PlasmaSource.discharge_kind is missing" in _violations(doc, spec)
    doc = _doc("example.json")
    feed = next(n for n in doc["nodes"] if n["label"] == "Feed")
    doc["links"] = [e for e in doc["links"] if not (e["type"] == "HAS_COMPONENT" and e["source"] == feed["id"])]
    assert "required edge HAS_COMPONENT is missing" in _violations(doc, spec)


@pytest.mark.parametrize("forces", [["thermo"], ["electro"], ["photo"], ["plasma"], ["photo", "thermo"], ["electro", "photo"]])
@pytest.mark.parametrize("kind", EQUILIBRIUM)
def test_equilibrium_tests_are_exempt_under_every_driving_force(spec, forces, kind):
    doc = _doc("example.json")
    t = _node(doc, "test/zno-run-1")
    doc["links"] = [e for e in doc["links"] if e["source"] != t["id"] or e["type"] in ("REPORTED_IN",)]
    t["props"] = {k: v for k, v in t["props"].items() if k in ("name", "origin", "evidence", "experiment_kind")}
    t["props"].update(driving_forces=forces, test_kind="activity")
    assert any(m.startswith("required edge USES_CATALYST") for m in _violations(doc, spec))
    t["props"]["test_kind"] = kind
    rec = pgraph.validate(doc, spec).conformance["profiles"]["catalysis"]
    assert not [v for v in rec["violations"] if v["record"] == t["id"]]


def test_a_missing_must_is_non_conformant_not_invalid(spec):
    doc = _doc("example.json")
    del _node(doc, "test/zno-run-1")["props"]["pressure"]
    rep = pgraph.validate(doc, spec)
    c = rep.conformance["profiles"]["catalysis"]
    assert rep.errors == [] and not c["conformant"]
    assert any("pressure is missing" in v["message"] for v in c["violations"])


# ---------------------------------------------------------------- documents
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_examples_are_valid_and_follow_the_catalysis_checklist(path, spec):
    doc = load_doc(path)
    assert doc["graph"]["schema_version"] == spec["version"] and "conforms_to" not in doc["graph"]
    assert doc["graph"]["follows_domains"] == ["catalysis"]
    assert not [n["id"] for n in doc["nodes"] if "follows_domains" in n["props"]]   # one declaration, on the graph
    rep = pgraph.validate(doc, spec)
    assert rep.errors == [] and rep.warnings == [], (rep.errors, rep.warnings)
    assert set(rep.conformance["profiles"]) == {"catalysis"} and rep.conformance["profiles"]["catalysis"]["conformant"]


def test_every_driving_force_and_combination_has_an_example():
    listed = {tuple(sorted(n["props"]["driving_forces"])) for p in EXAMPLES for n in load_doc(p)["nodes"]
              if n["label"] == "CatalyticTest"}
    assert {(f,) for f in FORCES} | {("photo", "thermo"), ("electro", "photo")} <= listed


def test_an_unknown_checklist_name_or_version_is_an_error(spec):
    doc = copy.deepcopy(_doc("electro.json"))
    doc["graph"]["follows_domains"] = ["electrocatalysis@0.1.0"]                # not a checklist of this schema
    assert any("unknown domain 'electrocatalysis@0.1.0'" in e["message"] for e in pgraph.validate(doc, spec).errors)
    doc["graph"]["follows_domains"] = [f"catalysis@{spec['version']}"]           # name@version: the one version
    assert pgraph.validate(doc, spec).errors == []
    doc["graph"]["follows_domains"] = ["catalysis@9.9.9"]
    assert any(f"domain catalysis 9.9.9 is declared; this schema carries {spec['version']}" in e["message"]
               for e in pgraph.validate(doc, spec).errors)


def test_domain_contract_translates_must_and_should():
    """The checklist machinery: must, should, edges, unless and includes (another domain file's checklist)."""
    dom = {"domain": "x", "version": "0.1.0", "checklist": {
        "includes": [{"domain": "thermocatalysis", "version": ">=0.1.0,<1.0.0"}],
        "labels": {"CatalyticTest": {"must": ["temperature"], "should": ["pressure"], "edges": {"must": ["FED_WITH"]},
                                     "unless": {"test_kind": ["equilibrium_estimate"]}}}}}
    c = domain_contract(dom, "graph/x.yaml")
    t = c["constraints"]["CatalyticTest"]
    assert t["required"] == ["temperature"] and t["recommended"] == ["pressure"] and t["edges"] == {"required": ["FED_WITH"]}
    assert t["unless"] == {"test_kind": ["equilibrium_estimate"]} and c["_domain"]
    assert {"profile": "thermocatalysis", "version": ">=0.1.0,<1.0.0"} in c["profile_of"]
