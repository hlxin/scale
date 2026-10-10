"""One checklist with cases: the catalysis domain file carries the domain's checklist, with `when` cases selected by a
record's driving_forces (and `unless` exemptions); a checklist belongs to a domain file only. Exercised on the head
schema and its public examples, and on variants of the head's checklist written outside the repository."""

import shutil

import pytest
import yaml

from conftest import EXAMPLES, GRAPH_MANIFEST, HEAD_VERSION, REPO, spec_of
from scale import layout, pgraph
from scale.schema_change import diff_specs
from scale.pgraph_profiles import conformance
from scale.util import ScaleError, load_doc

DF = EXAMPLES / "scale-graph/driving-force-examples"


@pytest.fixture(scope="module")
def cand():
    """The head schema (the name is kept from the tests' origin: the candidate that introduced the cases)."""
    return pgraph.load_spec(GRAPH_MANIFEST)


def _ex(name):
    return load_doc(EXAMPLES / "scale-graph/example.json" if name == "example.json" else DF / name)


def _test(doc, forces=None):
    return next(n for n in doc["nodes"] if n["label"] == "CatalyticTest"
                and (forces is None or n["props"].get("driving_forces") == forces))


def _conf(doc, spec):
    """The checklist conformance of a document, validated under the schema it pins (the head while it pins the head)."""
    if doc["graph"]["schema_version"] != spec["version"]:
        spec = spec_of(doc)
    rep = pgraph.validate(doc, spec)
    assert rep.errors == [], rep.errors
    return rep.conformance["profiles"]["catalysis"], rep


def _copy_head(tmp_path):
    """The head schema's files (the kernel, the catalysis manifest and file) in a tree outside the repository."""
    root = tmp_path / "cand"
    (root / "core/graph").mkdir(parents=True)
    shutil.copy2(REPO / layout.KERNEL, root / layout.KERNEL)
    shutil.copytree(GRAPH_MANIFEST.parent, root / "domain/graph", ignore=shutil.ignore_patterns("frozen"))
    return root / "domain/graph/scale-graph.yaml", root / "domain/graph/catalysis.yaml"


def _variant(tmp_path, mutate):
    """The head schema copied outside the repository, with its checklist changed by ``mutate``."""
    man, cat = _copy_head(tmp_path)
    m = yaml.safe_load(cat.read_text())
    mutate(m["checklist"])
    cat.write_text(yaml.safe_dump(m, sort_keys=False, allow_unicode=True))
    return man


# ------------------------------------------------------------------ the domain file carries the domain's checklist
def test_the_domain_file_carries_a_checklist_named_after_the_domain(cand):
    assert cand["version"] == HEAD_VERSION and set(cand["profiles"]) == {"catalysis"} and set(cand["domains"]) == {"catalysis"}
    c = cand["profiles"]["catalysis"]
    assert c["domain"] and c["driving_forces"] == [] and c["version"] == cand["modules"]["catalysis"]["version"] == HEAD_VERSION
    assert {n: m["kind"] for n, m in cand["modules"].items()} == {"kernel": "kernel", "catalysis": "domain"}   # no module
    man = yaml.safe_load(GRAPH_MANIFEST.read_text())
    assert man["domains"] == ["catalysis.yaml"] and "modules" not in man
    assert yaml.safe_load((GRAPH_MANIFEST.parent / "catalysis.yaml").read_text())["domain"] == "catalysis"
    added_by = {d.get("added_by") for d in cand["nodes"]["CatalyticTest"]["properties"].values()} - {None}
    assert added_by == {"catalysis"}


def test_a_module_cannot_carry_a_checklist(tmp_path):
    """Checklists come only from domain files: a vocabulary-only module with a checklist does not load."""
    man, cat = _copy_head(tmp_path)
    m = yaml.safe_load(cat.read_text())
    cat.write_text(yaml.safe_dump({"module": m.pop("domain"), **m}, sort_keys=False, allow_unicode=True))
    mm = yaml.safe_load(man.read_text())
    mm["modules"] = mm.pop("domains")
    man.write_text(yaml.safe_dump(mm, sort_keys=False, allow_unicode=True))
    with pytest.raises(ScaleError, match="a module file carries no checklist"):
        pgraph.load_spec(man)


def test_documents_use_the_one_domain_schema_whatever_they_follow(tmp_path):
    """One domain beside the core: every document reads the catalysis domain's manifest, whether it follows its
    checklist (``catalysis``), a checklist it does not have, or nothing; which checklist applies is the version's
    business (``pgraph.pinned``), not a choice between schemas."""
    repo = tmp_path / "repo"
    d = repo / layout.DOMAIN
    (d / "graph").mkdir(parents=True)
    (d / layout.DOMAIN_MANIFEST).write_text("domain: catalysis\nstatus: stable\ngraph:\n  manifest: graph/scale-graph.yaml\n")
    (d / "graph/scale-graph.yaml").write_text("schema: scale-graph\nversion: 0.1.0\nkernel: k.yaml\ndomains:\n- catalysis.yaml\n")
    (d / "graph/catalysis.yaml").write_text("domain: catalysis\nchecklist:\n  labels: {}\n")
    doc = lambda *f: {"graph": {"follows_domains": list(f)}, "nodes": []}   # noqa: E731
    for follows in (("catalysis",), ("thermocatalysis@0.1.0",), ("optics",), ()):
        assert pgraph.spec_path(repo, doc=doc(*follows)) == d / "graph/scale-graph.yaml", follows
    (d / layout.DOMAIN_MANIFEST).write_text("domain: catalysis\nstatus: experimental\ngraph:\n  manifest: graph/scale-graph.yaml\n")
    with pytest.raises(ScaleError, match="no scale-graph schema found: no released domain declares graph.manifest in "
                                         "domain/DOMAIN.yaml"):
        pgraph.spec_path(repo, doc=doc("catalysis"))


# ------------------------------------------------------------------ cases
def test_cases_apply_by_driving_forces(cand):
    d = _ex("electro.json")
    c, _ = _conf(d, cand)
    assert c["conformant"]
    t = _test(d, ["electro"])["props"]
    t.pop("control_mode")
    assert "required CatalyticTest.control_mode is missing" in [v["message"] for v in _conf(d, cand)[0]["violations"]]
    t["driving_forces"] = ["thermo"]                                         # now the thermal items apply, not the electro ones
    v = [x["message"] for x in _conf(d, cand)[0]["violations"]]
    assert not any("control_mode" in m or "IN_ELECTROLYTE" in m for m in v)
    assert {"required CatalyticTest.pressure is missing", "required edge FED_WITH is missing"} <= set(v), v


def test_should_items_of_a_case_that_does_not_apply_do_not_count(cand):
    d = _ex("electro.json")
    tid = _test(d, ["electro"])["id"]
    rec = lambda doc: conformance(doc, cand, by_record=True)["profiles"]["catalysis"]["records"][tid]   # noqa: E731
    electro = rec(d)
    _test(d, ["electro"])["props"]["driving_forces"] = ["other"]
    other = rec(d)
    assert other["checked"] and other["expected"] < electro["expected"]
    assert not other["violations"] and not any(k.startswith("CatalyticTest.") for k in other["missing"])


def test_all_of_needs_every_listed_force(cand):
    d = _ex("photo.json")
    t = _test(d, ["photo"])["props"]
    assert "light_absorber" not in t and _conf(d, cand)[0]["conformant"]     # photo alone: no light absorber needed
    t["driving_forces"] = ["photo", "electro"]
    v = [x["message"] for x in _conf(d, cand)[0]["violations"]]
    assert "required CatalyticTest.light_absorber is missing" in v and "required CatalyticTest.control_mode is missing" in v


def test_unless_exempts_the_cases_too(cand):
    d = _ex("photothermo.json")
    t = next(n for n in d["nodes"] if n["label"] == "CatalyticTest" and n["props"].get("illumination") != "dark")
    assert t["props"]["driving_forces"] == ["photo", "thermo"]
    for k in ("temperature", "illumination", "temperature_measured_at"):
        t["props"].pop(k, None)
    d["links"] = [e for e in d["links"] if not (e["source"] == t["id"] and e["type"] == "ILLUMINATED_BY")]
    mine = lambda c: {v["message"] for v in c["violations"] if v["record"] == t["id"]}   # noqa: E731
    assert {"required CatalyticTest.temperature is missing", "required CatalyticTest.illumination is missing",
            "required CatalyticTest.temperature_measured_at is missing", "required edge ILLUMINATED_BY is missing"} <= \
        mine(_conf(d, cand)[0])
    t["props"]["test_kind"] = "equilibrium_measurement"                        # exempt: its cases too
    assert mine(_conf(d, cand)[0]) == set()


def test_an_edge_case_is_evaluated_on_the_edge_source(cand):
    """USES_CATALYST should state its state and amount for a thermally driven test only."""
    d = _ex("example.json")
    tid = _test(d, ["thermo"])["id"]
    rec = lambda doc: conformance(doc, cand, by_record=True)["profiles"]["catalysis"]["records"][tid]   # noqa: E731
    for e in d["links"]:
        if e["type"] == "USES_CATALYST":
            e["props"].pop("state", None)
    assert "USES_CATALYST.state" in rec(d)["missing"]
    _test(d, ["thermo"])["props"]["driving_forces"] = ["plasma"]
    assert "USES_CATALYST.state" not in rec(d)["missing"]


def test_values_of_a_case_narrow_only_where_it_applies(cand):
    d = _ex("electrothermo.json")
    t = next(n for n in d["nodes"] if n["label"] == "CatalyticTest" and "electrothermo" in n["props"]["driving_forces"])
    t["props"]["heating_mode"] = "external_furnace"
    assert any("heating_mode 'external_furnace' is not one of" in v["message"] for v in _conf(d, cand)[0]["violations"])
    t["props"]["driving_forces"] = ["thermo"]
    assert not any("heating_mode" in v["message"] for v in _conf(d, cand)[0]["violations"])


@pytest.mark.parametrize("mutate, match", [
    (lambda ck: ck["labels"]["CatalyticTest"]["when"].append({"temperature": {"any_of": ["x"]}, "must": ["pressure"]}),
     "tests 'temperature', which is not an enum or a list of enum"),
    (lambda ck: ck["labels"]["CatalyticTest"]["when"].append({"driving_forces": {"any_of": ["wind"]}, "must": ["pressure"]}),
     "must name values of its enum"),
    (lambda ck: ck["labels"]["CatalyticTest"]["when"].append({"driving_forces": {"some_of": ["thermo"]}}),
     "is not a condition"),
    (lambda ck: ck["labels"]["CatalyticTest"]["when"].append({"must": ["pressure"]}), "names no condition"),
    (lambda ck: ck["labels"]["CatalyticTest"]["when"].append(
        {"driving_forces": {"any_of": ["thermo"]}, "unless": {"test_kind": ["control"]}}), "is not a condition"),
    (lambda ck: ck["labels"]["CatalyticTest"]["when"].append(
        {"driving_forces": {"any_of": ["photo"]}, "values": {"light_absorber": ["catalyst"]}}), "have nothing in common"),
    (lambda ck: ck["labels"]["CatalyticTest"]["when"].append({"driving_forces": {"any_of": ["photo"]}, "must": ["colour"]}),
     "has no property 'colour'"),
    (lambda ck: ck["edges"]["USES_CATALYST"]["when"].append({"test_kind": {"any_of": ["nope"]}, "should": ["state"]}),
     "must name values of its enum"),
])
def test_malformed_cases_are_refused(tmp_path, mutate, match):
    with pytest.raises(ScaleError, match=match):
        pgraph.load_spec(_variant(tmp_path, mutate))


def test_describe_prints_the_cases_and_keeps_every_property(cand):
    out = pgraph.describe(cand, ["CatalyticTest"], "catalysis")
    assert out["domain"] == "catalysis"
    assert len(out["labels"]["CatalyticTest"]["properties"]) == len(cand["nodes"]["CatalyticTest"]["properties"])
    ck = out["checklist"]["labels"]["CatalyticTest"]
    assert ck["edges"]["must"] == ["USES_CATALYST", "OF_REACTION"] and ck["unless"]["test_kind"]
    electro = next(x for x in ck["when"] if x["driving_forces"] == {"any_of": ["electro"]})
    assert electro["must"] == ["control_mode"] and electro["edges"]["must"] == ["IN_ELECTROLYTE"]
    ep = next(x for x in ck["when"] if x["driving_forces"] == {"all_of": ["electro", "photo"]})
    assert set(ep["values"]["light_absorber"]) == {"photoelectrode", "molecular_photocatalyst", "photosensitizer"}
    assert out["checklist"]["edges"]["USES_CATALYST"]["when"][0]["should"] == ["state", "amount"]


def test_the_semantic_diff_compares_cases(tmp_path, cand):
    def tighten(ck):
        ck["labels"]["CatalyticTest"]["when"][2]["must"].append("electrode_potential")
        ck["labels"]["CatalyticTest"]["when"][6]["values"]["light_absorber"] = ["photoelectrode"]
    d = diff_specs(cand, pgraph.load_spec(_variant(tmp_path, tighten)))
    assert "profiles.catalysis CatalyticTest when driving_forces any_of [electro] requires electrode_potential" in d["narrowed"]
    assert any("when driving_forces all_of [electro, photo] light_absorber values" in x for x in d["narrowed"])
    assert not d["loosened"] and not d["removed"]
    assert diff_specs(cand, cand) == {"added": [], "removed": [], "changed": [], "narrowed": [], "loosened": []}


def test_no_driving_force_warnings_under_one_checklist(cand):
    d = _ex("photoelectro.json")
    rep = pgraph.validate(d, cand)
    assert not [w for w in rep.warnings if "driving force" in w["message"] or "does not list" in w["message"]]
    e = load_doc(DF / "electro.json")                                         # a head example listing a force it has no case for
    _test(e)["props"]["driving_forces"] = ["electro", "other"]
    assert not [w for w in pgraph.validate(e, cand).warnings if "driving force" in w["message"]]
