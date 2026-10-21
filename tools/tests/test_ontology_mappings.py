"""SCALE's terms mapped to terms of other ontologies (docs/mappings.md).

A mapping says how a SCALE term relates to a term someone else defines: exact, close, broad (the other term is
broader), narrow or related. The mappings are kept beside the schema, one set per layer (core/mappings/kernel.yaml,
domain/mappings/catalysis.yaml), with the registry of the ontologies they cite (core/mappings/ontologies.yaml); they
change nothing SCALE validates or queries. Every mapping names a term of the head schema (a layer's labels and edge
types are its own) and a CURIE of a registered ontology in its pattern; ``describe`` shows a term's mappings; a layer's
set exports as SSSOM; the catalysis set records the fourteen areas of catalysis research of Ontologies4Cat (Behr,
Borgelt and Kockmann 2024) with the SCALE terms that record each."""

import copy
import subprocess
import sys

import pytest
import yaml

from conftest import REPO, RUN_SCALE
from scale import layout, mappings, pgraph
from scale.util import load_yaml


@pytest.fixture(scope="module")
def spec():
    return mappings.head_spec(REPO)


def _tree(tmp_path, kernel=None, catalysis=None, registry=None):
    """A copy of the registry and the two sets under ``tmp_path``, each replaced when given."""
    for rel, doc in ((layout.ONTOLOGY_REGISTRY, registry), (layout.KERNEL_MAPPINGS, kernel),
                     (layout.DOMAIN_MAPPINGS, catalysis)):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(doc if doc is not None else load_yaml(REPO / rel), sort_keys=False))
    return tmp_path


def _messages(res):
    return [e["message"] for e in res["errors"]]


def test_every_mapping_names_a_term_of_the_schema_and_a_registered_ontology(spec):
    res = mappings.check(REPO, spec)
    assert res["ok"], res["errors"]
    assert res["counts"]["kernel"] > 40 and res["counts"]["catalysis"] > 80
    assert not res["warnings"]


def test_every_registered_ontology_states_its_iri_pattern_and_the_release_checked():
    reg = mappings.registry(REPO)
    assert {"CHEBI", "CHMO", "OBI", "REX", "af-e", "prov"} <= set(reg)
    for prefix, e in reg.items():
        assert e["iri"].startswith(("http://", "https://")) and e["checked"] and e["name"], prefix
        assert e["pattern"].startswith(f"^{prefix}:") and e["pattern"].endswith("$"), prefix
    assert mappings.iri("CHMO:0001467", reg) == "http://purl.obolibrary.org/obo/CHMO_0001467"
    assert mappings.iri("af-e:AFE_0000153", reg) == "http://purl.allotrope.org/ontologies/equipment#AFE_0000153"
    assert mappings.iri("XYZ:1", reg) is None


def test_a_mapping_on_a_term_the_schema_lacks_or_an_unregistered_ontology_is_an_error(tmp_path, spec):
    cat = load_yaml(REPO / layout.DOMAIN_MAPPINGS)
    m = cat["mappings"]
    m["NoSuchLabel"] = [{"match": "close", "term": "CHEBI:23367", "label": "molecular entity"}]
    m["Catalyst.no_such_property"] = [{"match": "close", "term": "CHEBI:35223", "label": "catalyst"}]
    m["Treatment.treatment_kind=baking"] = [{"match": "close", "term": "CHMO:0001467", "label": "calcination"}]
    m["Catalyst.nominal_formula=x"] = [{"match": "close", "term": "CHEBI:35223", "label": "catalyst"}]
    m["Reactor"] = [{"match": "same", "term": "FOO:0000001", "label": "reactor"},
                    {"match": "close", "term": "CHMO:12", "label": "reactor"},
                    {"match": "close", "term": "reactor", "label": "reactor"},
                    {"match": "close", "term": "af-e:AFE_0000153", "label": "reactor"},
                    {"match": "broad", "term": "af-e:AFE_0000153", "label": "reactor"},
                    {"match": "close", "term": "OBI:0000070"}]
    m["Experiment"] = [{"match": "broad", "term": "OBI:0000070", "label": "assay"}]
    res = mappings.check(_tree(tmp_path, catalysis=cat), spec)
    msgs = _messages(res)
    assert not res["ok"]
    for expected in ("NoSuchLabel: no label or edge type NoSuchLabel",
                     "Catalyst.no_such_property: Catalyst has no property no_such_property",
                     "Treatment.treatment_kind=baking: Treatment.treatment_kind has no value 'baking'",
                     "Catalyst.nominal_formula=x: Catalyst.nominal_formula is not an enumeration",
                     "Reactor[0]: match 'same' is not one of exact, close, broad, narrow, related",
                     "Reactor[0]: FOO is not a registered ontology",
                     "Reactor[1]: CHMO:12 does not look like a CHMO term",
                     "Reactor[2]: term 'reactor' is not a CURIE (prefix:local)",
                     "Reactor[4]: af-e:AFE_0000153 is mapped twice for Reactor",
                     "Reactor[5]: label is required",
                     "Experiment: Experiment is declared by kernel, not by the catalysis layer"):
        assert any(expected in x for x in msgs), (expected, msgs)


def test_two_exact_matches_in_one_ontology_are_reported(tmp_path, spec):
    cat = load_yaml(REPO / layout.DOMAIN_MAPPINGS)
    cat["mappings"]["ReferenceElectrode"].append({"match": "exact", "term": "CHMO:0002344", "label": "electrode"})
    res = mappings.check(_tree(tmp_path, catalysis=cat), spec)
    assert res["ok"]
    assert any("two exact matches in CHMO" in w["message"] for w in res["warnings"])


def test_a_registry_entry_without_its_iri_or_with_a_loose_pattern_is_an_error(tmp_path, spec):
    reg = load_yaml(REPO / layout.ONTOLOGY_REGISTRY)
    reg["ontologies"]["CHMO"]["pattern"] = r"CHMO:\d+"
    del reg["ontologies"]["REX"]["iri"]
    reg["ontologies"]["OBI"]["url"] = "http://obi-ontology.org"
    msgs = _messages(mappings.check(_tree(tmp_path, registry=reg), spec))
    assert any("CHMO: pattern must match a whole CURIE" in x for x in msgs)
    assert any("REX: iri is required" in x for x in msgs)
    assert any("OBI: unknown key 'url'" in x for x in msgs)


def test_the_areas_are_the_fourteen_of_ontologies4cat_and_name_terms_of_the_schema(tmp_path, spec):
    rows = mappings.areas(REPO)
    assert [r["area"] for r in rows] == list(mappings.AREAS)
    bio = rows[0]
    assert bio["scale"] == [] and "enzyme" in bio["gap"] and bio["contained"] == ["SBO"]
    het = next(r for r in rows if r["area"] == "heterogeneous_catalysis")
    assert "Catalyst" in het["scale"] and het["contained"] == [] and "ChEBI" in het["mapped"]
    char = next(r for r in rows if r["area"] == "characterisation_data")
    assert "CHMO" in char["contained"] and "CHMO" in char["mapped"]
    cat = load_yaml(REPO / layout.DOMAIN_MAPPINGS)
    cat["areas"]["biocatalysis"]["scale"] = ["Enzyme"]
    cat["areas"]["catalyst_design"] = copy.deepcopy(cat["areas"]["biocatalysis"])
    msgs = _messages(mappings.check(_tree(tmp_path, catalysis=cat), spec))
    assert any("areas.biocatalysis: Enzyme is no label or edge type of the schema" in x for x in msgs)
    assert any("areas: unknown area 'catalyst_design'" in x for x in msgs)
    kern = load_yaml(REPO / layout.KERNEL_MAPPINGS)
    kern["areas"] = {"biocatalysis": load_yaml(REPO / layout.DOMAIN_MAPPINGS)["areas"]["biocatalysis"]}
    msgs = _messages(mappings.check(_tree(tmp_path, kernel=kern), spec))
    assert any("areas are areas of catalysis research; they belong to the catalysis set" in x for x in msgs)


def test_describe_shows_a_terms_mappings_and_those_of_its_values(spec):
    idx = mappings.index(REPO)
    d = pgraph.describe(spec, ["Treatment", "ReferenceElectrode", "HAS_INPUT", "Experiment"], None, idx)
    ref = d["labels"]["ReferenceElectrode"]["mappings"]
    assert ref == [{"match": "exact", "term": "CHMO:0002345", "label": "reference electrode",
                    "iri": "http://purl.obolibrary.org/obo/CHMO_0002345"}]
    calc = d["labels"]["Treatment"]["property_mappings"]["treatment_kind=calcination"]
    assert calc[0]["term"] == "CHMO:0001467" and calc[0]["match"] == "close"
    assert {m["term"] for m in d["edges"]["HAS_INPUT"]["mappings"]} == {"OBI:0000293", "prov:used"}
    # the kernel's maps_to names an obsolete OBI term in words; its mapping is the term that replaced it
    exp = d["labels"]["Experiment"]
    assert "OBI planned process" in exp["maps_to"]
    assert any(m["term"] == "COB:0000035" and m["match"] == "broad" for m in exp["mappings"])
    # without mappings, describe is as it was
    plain = pgraph.describe(spec, ["Treatment"], None)
    assert "mappings" not in plain["labels"]["Treatment"] and "property_mappings" not in plain["labels"]["Treatment"]


def test_no_mapping_cites_an_obi_term_obi_made_obsolete():
    terms = {r["term"] for r in mappings.rows(REPO)}
    assert not terms & {"OBI:0000011", "OBI:0000968", "OBI:0000094"}


def test_the_sssom_export_lists_every_mapping_with_its_skos_relation():
    out = mappings.sssom(REPO, "catalysis", "0.7.0")
    lines = out.splitlines()
    meta = yaml.safe_load("\n".join(x[2:] for x in lines if x.startswith("# ")))
    assert meta["mapping_set_id"].endswith("/domain/mappings/catalysis.yaml")
    assert meta["license"] == "https://creativecommons.org/licenses/by/4.0/"
    assert meta["subject_source_version"] == "0.7.0"
    table = [x.split("\t") for x in lines if not x.startswith("#")]
    head, body = table[0], table[1:]
    assert head == ["subject_id", "subject_label", "predicate_id", "object_id", "object_label", "mapping_justification",
                    "comment"]
    assert len(body) == mappings.check(REPO)["counts"]["catalysis"]
    row = {(r[0], r[3]): r for r in body}
    assert row[("scalecatal:ReferenceElectrode", "CHMO:0002345")][2] == "skos:exactMatch"
    assert row[("scalecatal:Treatment.treatment_kind=calcination", "CHMO:0001467")][2] == "skos:closeMatch"
    assert all(r[5] == "semapv:ManualMappingCuration" for r in body)
    assert {r[3].split(":", 1)[0] for r in body} | {"scalecatal"} <= set(meta["curie_map"])
    assert all(len(r) == len(head) for r in body)


def test_the_command_checks_lists_and_exports_the_mappings():
    run = lambda *a: subprocess.run([sys.executable, "-c", RUN_SCALE, str(REPO / "tools"), "--repo", str(REPO),   # noqa: E731
                                     "schema", "mappings", *a], capture_output=True, text=True)
    r = run("--check")
    assert r.returncode == 0 and "every one on a term of the schema and of a registered ontology" in r.stdout, r.stderr
    r = run("--layer", "kernel")
    assert r.returncode == 0 and "COB:0000035" in r.stdout and "CHMO:" not in r.stdout
    r = run("--format", "sssom")
    assert r.returncode != 0 and "--layer kernel or --layer catalysis" in r.stderr
    r = run("--areas")
    assert r.returncode == 0 and "Biocatalysis" in r.stdout and "nothing yet" in r.stdout


# ---- quantity kinds and units (the kernel's set): QUDT, and SBO for an enzyme's turnover frequency

def test_quantity_kinds_and_units_map_to_qudt_and_keep_what_scale_leaves_open(spec):
    idx = mappings.index(REPO)
    assert idx["kind:temperature"][0]["term"] == "quantitykind:Temperature"
    assert {m["term"]: m["match"] for m in idx["kind:flow_rate"]} == {
        "quantitykind:VolumeFlowRate": "narrow", "quantitykind:MolarFlowRate": "narrow",
        "quantitykind:MassFlowRate": "narrow"}
    assert any(m["term"] == "SBO:0000025" and m["match"] == "narrow" for m in idx["kind:turnover_frequency"])
    assert idx["unit:°C"] == [{"match": "exact", "term": "unit:DEG_C", "label": "Degree Celsius",
                               "iri": "http://qudt.org/vocab/unit/DEG_C"}]
    assert idx["unit:mL/min"][0]["term"] == "unit:MilliL-PER-MIN"
    # a gallon or a calorie is whichever the source printed: each of QUDT's definitions is narrower
    assert {m["term"]: m["match"] for m in idx["unit:gal"]} == {"unit:GAL_US": "narrow", "unit:GAL_UK": "narrow"}
    assert {m["match"] for m in idx["unit:cal"]} == {"narrow"}
    # the reference conditions of a normal volume are not fixed by SCALE
    assert idx["unit:Nm3"][0]["match"] == "close"
    # every unit mapped is one SCALE reads, and every kind one its contracts declare
    from scale.quantities import contracts
    qc = contracts(spec)
    for subject in idx:
        if subject.startswith("unit:"):
            r = qc.read_unit(subject[5:])
            assert r.read and not r.unread, subject
        elif subject.startswith("kind:"):
            assert subject[5:] in qc.kinds, subject


def test_a_unit_scale_does_not_read_or_an_unknown_kind_is_an_error(tmp_path, spec):
    kern = load_yaml(REPO / layout.KERNEL_MAPPINGS)
    kern["units"]["furlong"] = [{"match": "exact", "term": "unit:FUR", "label": "Furlong"}]
    kern["kinds"]["turnover_rate"] = [{"match": "close", "term": "quantitykind:Frequency", "label": "Frequency"}]
    cat = load_yaml(REPO / layout.DOMAIN_MAPPINGS)
    cat["units"] = {"kPa": [{"match": "exact", "term": "unit:KiloPA", "label": "Kilopascal"}]}
    msgs = _messages(mappings.check(_tree(tmp_path, kernel=kern, catalysis=cat), spec))
    assert any("unit:furlong: the unit vocabulary does not read 'furlong'" in x for x in msgs), msgs
    assert any("kind:turnover_rate: no quantity kind 'turnover_rate'" in x for x in msgs), msgs
    assert any("unit:kPa: quantity kinds and units are the kernel's" in x for x in msgs), msgs


def test_describe_shows_a_quantity_kinds_mappings(spec):
    d = pgraph.describe(spec, None, None, mappings.index(REPO))
    temp = d["quantity_kinds"]["temperature"]["mappings"]
    assert temp[0]["term"] == "quantitykind:Temperature" and temp[0]["iri"] == "http://qudt.org/vocab/quantitykind/Temperature"
    assert "mappings" not in d["quantity_kinds"]["activation_energy"]      # QUDT has no activation energy


def test_the_kernels_sssom_export_names_kinds_and_units_by_their_section():
    lines = mappings.sssom(REPO, "kernel", "0.7.0").splitlines()
    meta = yaml.safe_load("\n".join(x[2:] for x in lines if x.startswith("# ")))
    assert {"unit", "quantitykind", "SBO", "scalekernel"} <= set(meta["curie_map"])
    body = [x.split("\t") for x in lines if not x.startswith("#")][1:]
    row = {(r[0], r[3]): r for r in body}
    assert row[("scalekernel:unit/°C", "unit:DEG_C")][2] == "skos:exactMatch"
    assert row[("scalekernel:kind/temperature", "quantitykind:Temperature")][1] == "temperature"
    assert len(body) == mappings.check(REPO)["counts"]["kernel"]
