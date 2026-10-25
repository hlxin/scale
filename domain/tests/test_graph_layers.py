"""The catalysis domain's graph schema: the science kernel (core) and the catalysis domain file, which carries the
domain's one checklist; one version for both, the manifest's; the loader's composition rules and their counterexamples
(further domain files are exercised on extra files; profile files are retired by design); documents that follow the checklist
(``follows_domains: ["catalysis"]``), checked under the version they pin. Labels and edge types name the file that
declares them in the effective schema's internal ``module`` key."""

import re

import pytest
import yaml

from conftest import GRAPH_MANIFEST, HEAD_VERSION, REPO, spec_of
from scale import layout, pgraph
from scale.util import ScaleError, load_doc, write_canonical

G = GRAPH_MANIFEST.parent                   # the catalysis domain's graph directory: its manifest and parts
X = REPO / "domain/examples/scale-catal"
DF = X / "driving-force-examples"


@pytest.fixture(scope="module")
def spec():
    """The schema the examples pin."""
    return spec_of(load_doc(DF / "electro.json"))


@pytest.fixture(scope="module")
def head():
    return pgraph.load_spec(G / "scale-catal.yaml")


def msgs(doc, spec, kind="errors"):
    return [m["message"] for m in getattr(pgraph.validate(doc, spec), kind)]


def manifest(tmp_path, extra_domains=(), extra_profiles=()):     # extra_profiles: only to show they are refused
    base = yaml.safe_load((G / "scale-catal.yaml").read_text())
    m = {"schema": "scale-catal", "version": base["version"], "status": "candidate",
         "kernel": str(layout.kernel_path(G, base["kernel"])),
         "domains": [str(G / p) for p in base["domains"]] + [str(x) for x in extra_domains]}
    if extra_profiles:
        m["profiles"] = [str(x) for x in extra_profiles]
    p = tmp_path / "scale-catal.yaml"
    p.write_text(yaml.safe_dump(m, sort_keys=False))
    return p


# ---------------------------------------------------------------- the kernel and the domain file with its checklist
def test_layers(head):
    spec = head
    assert spec["version"] == spec["kernel"]["version"] == HEAD_VERSION                 # one version for both layers
    assert {m["version"] for m in spec["modules"].values()} == {HEAD_VERSION}
    kinds = {n: m["kind"] for n, m in spec["modules"].items()}
    assert kinds == {"kernel": "kernel", "catalysis": "domain"}               # two layers: the kernel and the domain
    assert set(spec["domains"]) == {"catalysis"} and spec["profiles"]["catalysis"]["path"] == spec["modules"]["catalysis"]["path"]
    assert "Activity" not in spec["nodes"] and not spec["abstract"]


def test_operation_is_kernel_and_dynamic_is_not_a_driving_force(spec):
    assert spec["nodes"]["Operation"]["module"] == "kernel"
    assert spec["nodes"]["Operation"]["properties"]["operation_mode"]["values"] == ["static", "dynamic"]
    forces = spec["nodes"]["CatalyticTest"]["properties"]["driving_forces"]["items"]["values"]
    assert "dynamic" not in forces and {"thermo", "electrothermo", "electro", "photo", "plasma"} <= set(forces)


def test_no_catalysis_role_labels(spec):
    assert not {"Support", "Promoter", "Precursor", "Binder", "Inhibitor"} & set(spec["nodes"])
    roles = spec["edges"]["HAS_COMPONENT"]["properties"]["role"]["values"]
    assert {"support", "promoter", "binder", "active_phase", "precursor"} <= set(roles)
    assert set(spec["edges"]["INHIBITED_BY"]["to"]) >= {"ChemicalSpecies", "Material"}


def test_the_catalysis_domain_file_holds_catalysis_as_a_whole(spec):
    owned = {lab for lab, d in spec["nodes"].items() if d["module"] == "catalysis"}
    assert {"ChemicalSpecies", "Material", "Sample", "Reaction", "Reactor", "Characterization", "Computation", "Mechanism",
            "ElementaryStep", "Catalyst", "ActiveSite", "CatalystSample", "CatalyticTest"} <= owned


def test_the_domain_file_holds_every_driving_forces_vocabulary(spec):
    props = spec["nodes"]["CatalyticTest"]["properties"]
    for k in ("electrode_potential", "irradiance", "heating_power", "photocurrent_density", "light_induced_temperature_rise",
              "discharge_power"):
        assert props[k]["added_by"] == "catalysis", k
    assert {"Electrode", "ReferenceElectrode", "Electrolyte", "LightSource", "PlasmaSource", "Heater", "TemperatureProbe"} <= set(spec["nodes"])
    assert all(spec["nodes"][n]["module"] == "catalysis" for n in ("Electrode", "LightSource", "PlasmaSource", "Heater"))


def test_the_checklist_is_named_after_the_domain_and_narrows_by_case(spec):
    c = spec["profiles"]["catalysis"]
    assert c["driving_forces"] == [] and c["version"] == spec["version"]
    cases = {tuple(sorted((k, op, tuple(v)) for k, cond in w["if"].items() for op, v in cond.items())): w
             for w in c["effective"]["constraints"]["CatalyticTest"]["when"]}
    ep = cases[(("driving_forces", "all_of", ("electro", "photo")),)]
    et = cases[(("driving_forces", "all_of", ("electrothermo",)),)]
    assert set(ep["values"]["light_absorber"]) == {"photoelectrode", "molecular_photocatalyst", "photosensitizer"}
    assert set(et["values"]["heating_mode"]) == {"resistive", "inductive", "microwave"}
    assert cases[(("driving_forces", "any_of", ("thermo", "electrothermo")),)]["required"] == ["temperature", "pressure"]
    keyed = [k[0][0] for k in cases]               # the driving-force cases, and the readings' (0.5.0 on, provisional)
    assert keyed.count("driving_forces") == 8 and keyed.count("interpretations") == 7 and len(cases) == 15


def test_domain_edges_specialize_kernel_edges(spec):
    e = spec["edges"]
    assert e["USES_CATALYST"]["specializes"] == "EXAMINES" and e["IN_REACTOR"]["specializes"] == "USES_INSTRUMENT"
    assert e["USES_ELECTRODE"]["specializes"] == "HAS_INPUT" and e["ILLUMINATED_BY"]["specializes"] == "USES_INSTRUMENT"


# ---------------------------------------------------------------- loader counterexamples
def _dom(tmp_path, name, body):
    p = tmp_path / f"{name}.yaml"
    p.write_text(yaml.safe_dump({"domain": name, "driving_forces": ["other"],
                                 "imports": [{"domain": "catalysis"}], **body}, sort_keys=False))
    return p


def test_a_domain_cannot_redeclare_a_property(tmp_path):
    bad = _dom(tmp_path, "clash", {"adds_properties": {"Experiment": {"irradiance": {"type": "value"}}}})
    with pytest.raises(ScaleError, match="already declared"):
        pgraph.load_spec(manifest(tmp_path, extra_domains=[bad]))


def test_a_domain_adds_properties_to_a_kernel_edge_it_sees(head, tmp_path):
    """adds_properties names an edge type as it names a label (the function an input serves in a synthesis, on the
    kernel's HAS_INPUT); the property says which file added it, and redeclaring it, or adding to an edge type no
    loaded file declares, does not load."""
    d = head["edges"]["HAS_INPUT"]["properties"]["synthesis_function"]
    assert d["added_by"] == "catalysis" and "capping_agent" in d["items"]["values"]
    assert "role" in head["edges"]["HAS_INPUT"]["properties"]                    # the kernel's own stay
    again = _dom(tmp_path, "again", {"adds_properties": {"HAS_INPUT": {"synthesis_function": {"type": "text"}}}})
    with pytest.raises(ScaleError, match="HAS_INPUT.synthesis_function, which is already declared"):
        pgraph.load_spec(manifest(tmp_path, extra_domains=[again]))
    nowhere = _dom(tmp_path, "nowhere", {"adds_properties": {"MAKES": {"yield": {"type": "value"}}}})
    with pytest.raises(ScaleError, match="adds properties to MAKES, which is not visible to it"):
        pgraph.load_spec(manifest(tmp_path, extra_domains=[nowhere]))


def test_a_specialization_stays_inside_its_general_edge(tmp_path):
    bad = _dom(tmp_path, "wrong", {"edges": {"MEASURES_SOURCE": {"specializes": "EXAMINES", "from": ["Experiment"], "to": ["Source"]}}})
    with pytest.raises(ScaleError, match="outside EXAMINES"):
        pgraph.load_spec(manifest(tmp_path, extra_domains=[bad]))


def test_a_part_carries_no_version_and_imports_name_no_version(tmp_path):
    """One version for the schema: a domain file that states a version of its own, or an import that asks for one,
    does not load."""
    with pytest.raises(ScaleError, match="carries no version of its own"):
        pgraph.load_spec(manifest(tmp_path, extra_domains=[_dom(tmp_path, "versioned", {"version": "0.3.0"})]))
    pinned = _dom(tmp_path, "pinned", {"imports": [{"domain": "catalysis", "version": ">=0.1.0"}]})
    with pytest.raises(ScaleError, match="an import names a file only"):
        pgraph.load_spec(manifest(tmp_path, extra_domains=[pinned]))
    k = tmp_path / "kernel.yaml"
    k.write_text((REPO / "core/graph/kernel.yaml").read_text().replace("kernel: scale-kernel\n",
                                                                         "kernel: scale-kernel\nversion: 0.2.0\n", 1))
    m = yaml.safe_load(manifest(tmp_path).read_text())
    m["kernel"] = str(k)
    (tmp_path / "m.yaml").write_text(yaml.safe_dump(m))
    with pytest.raises(ScaleError, match="the kernel carries no version of its own"):
        pgraph.load_spec(tmp_path / "m.yaml")


# instructions to give a part file (the kernel, a domain file) a version of its own, as the earlier procedure gave them
PART_VERSION_ADVICE = re.compile(
    r"\b(?:raise|bump|set|increase|add)s?\b[^.;]{0,40}\bversion of (?:every|each|the|a) (?:part|kernel|catalysis|domain)"
    r"|(?:kernel|catalysis)\.yaml'?s version|\b(?:raise|bump|set)s? the kernel'?s version|one kernel per version"
    r"|freezes the new kernel version", re.I)


def _advice_texts() -> list:
    """The live texts that tell people and agents how to change the schema: Markdown (skills, docs, governance,
    READMEs, .github) and the YAML beside it (the inventory, the declarations, the workflows)."""
    from scale.style import markdown_files
    files = markdown_files(REPO) + sorted((REPO / "docs").rglob("*.yaml")) + sorted((REPO / ".github").rglob("*.yml"))
    return files + [REPO / layout.CORE_MANIFEST, REPO / layout.DOMAIN_DECLARATION]


def test_no_text_tells_anyone_to_version_a_part_file():
    """One version for the schema, the manifest's: no skill or document asks for a version on the kernel or a domain
    file (such a part does not load; test_a_part_carries_no_version_and_imports_name_no_version)."""
    old = ("Raise the `version` of every part file whose content changes. For the kernel `apply` refuses until the bump "
           "is there, because the core freezes one kernel per version (add an operation that sets\n   "
           "`core/graph/kernel.yaml`'s `version`); `apply` also freezes the new kernel version.")
    flat = lambda s: " ".join(s.replace("`", "").split())                      # noqa: E731 (wrapped lines joined)
    assert len(PART_VERSION_ADVICE.findall(flat(old))) == 4                     # the earlier procedure's sentences
    assert not PART_VERSION_ADVICE.search(flat("The part files (core/graph/kernel.yaml, domain/graph/catalysis.yaml) "
                                               "carry no version, so never add or set one. apply raises the version "
                                               "of the manifest and freezes the kernel of the base version."))
    files = _advice_texts()
    assert REPO / "skills/evolve-schema/SKILL.md" in files and REPO / "AGENTS.md" in files
    hits = [f"{f.relative_to(REPO)}: {m.group(0)}" for f in files
            for m in PART_VERSION_ADVICE.finditer(flat(f.read_text(errors="ignore")))]
    assert hits == []


def test_a_file_must_say_what_it_is(tmp_path):
    p = tmp_path / "mislabelled.yaml"                                        # a module listed among the domain files
    p.write_text(yaml.safe_dump({"module": "mislabelled"}))
    with pytest.raises(ScaleError, match="names itself"):
        pgraph.load_spec(manifest(tmp_path, extra_domains=[p]))


def test_fixed_values_are_checked(tmp_path, spec):
    bad = _dom(tmp_path, "fixer", {"nodes": {"OddSample": {"is_a": "Sample", "fixed": {"object_kind": "phenomenon"}}}})
    with pytest.raises(ScaleError, match="ancestor fixes it"):
        pgraph.load_spec(manifest(tmp_path, extra_domains=[bad]))
    d = load_doc(X / "example.json")
    s = next(n for n in d["nodes"] if n["label"] == "CatalystSample")
    s["props"]["object_kind"] = "phenomenon"
    assert any("fixes object_kind" in m for m in msgs(d, spec))


def test_conflicting_checklists_are_rejected(tmp_path):
    """A checklist that includes two others narrowing one enum to values with nothing in common is refused."""
    files = [_dom(tmp_path, name, {"checklist": {"labels": {"ElectrochemicalCell": {"values": {"cell_kind": vals}}}}})
             for name, vals in (("pa", ["h_cell"]), ("pb", ["flow_cell"]))]
    files.append(_dom(tmp_path, "pc", {"imports": [{"domain": "catalysis"}, {"domain": "pa"}, {"domain": "pb"}],
                                       "checklist": {"includes": [{"domain": "pa"}, {"domain": "pb"}]}}))
    with pytest.raises(ScaleError, match="nothing in common"):
        pgraph.load_spec(manifest(tmp_path, extra_domains=files))


def test_profile_files_are_retired(tmp_path):
    """There are no profile files by design: a manifest that lists `profiles:` is refused with the reason."""
    p = tmp_path / "old.yaml"
    p.write_text(yaml.safe_dump({"profile": "old", "version": "0.1.0", "constraints": {}}))
    with pytest.raises(ScaleError, match="retired by design"):
        pgraph.load_spec(manifest(tmp_path, extra_profiles=[p]))


# ---------------------------------------------------------------- documents
def test_dynamic_operation_follows_the_same_checklist():
    d = load_doc(DF / "electro-dynamic.json")
    assert d["graph"]["follows_domains"] == ["catalysis"]
    assert {n["props"]["operation_mode"] for n in d["nodes"] if n["label"] == "Operation"} == {"static", "dynamic"}
    assert {tuple(n["props"]["driving_forces"]) for n in d["nodes"] if n["label"] == "CatalyticTest"} == {("electro",)}


def test_driving_forces_select_the_checklist_items(spec):
    """One checklist: the forces a test lists choose its items, so there is nothing to mismatch and no warning."""
    d = load_doc(DF / "electro.json")
    t = next(n for n in d["nodes"] if n["label"] == "CatalyticTest")
    t["props"]["driving_forces"] = ["electro", "photo"]
    assert msgs(d, spec, "warnings") == [] and msgs(d, spec) == []
    v = [x["message"] for x in pgraph.validate(d, spec).conformance["profiles"]["catalysis"]["violations"]]
    assert "required CatalyticTest.illumination is missing" in v and "required CatalyticTest.light_absorber is missing" in v


def test_checklists_catch_missing_driving_force_detail(spec):
    d = load_doc(DF / "electro.json")
    t = next(n for n in d["nodes"] if n["label"] == "CatalyticTest")
    t["props"].pop("control_mode")
    d["links"] = [e for e in d["links"] if e["type"] != "IN_ELECTROLYTE"]
    conf = pgraph.validate(d, spec).conformance["profiles"]
    v = [x["message"] for c in conf.values() for x in c["violations"]]
    assert any("control_mode" in m for m in v) and any("IN_ELECTROLYTE" in m for m in v)


def test_extension_keys(spec):
    d = load_doc(X / "example.json")
    t = next(n for n in d["nodes"] if n["label"] == "CatalyticTest")
    t["props"]["_nobody_reactor_serial"] = "R-1"
    assert any("unregistered prefix" in m for m in msgs(d, spec, "warnings"))
    t["props"]["_Bad-Key"] = 1
    assert any("extension key" in m for m in msgs(d, spec))


def test_driving_force_examples_are_built_reproducibly(tmp_path):
    """The builder writes the examples for the head version; the committed examples, moved to the head along the
    registered steps (nothing, while they pin it; `scale graph migrate` moves them only when asked), are what it writes."""
    import shutil
    import subprocess
    import sys
    from scale.pgraph_migrate import raise_version
    work = tmp_path / "df"
    shutil.copytree(DF, work)
    subprocess.run([sys.executable, str(work / "build_examples.py")], check=True, capture_output=True, cwd=REPO)
    head = pgraph.load_spec(GRAPH_MANIFEST)
    for p in sorted(DF.glob("*.json")):
        doc = load_doc(p)
        if doc["graph"]["schema_version"] != HEAD_VERSION:
            doc = raise_version(doc, HEAD_VERSION, head)[0]
        write_canonical(tmp_path / "want.json", doc)
        assert (work / p.name).read_bytes() == (tmp_path / "want.json").read_bytes(), p.name
