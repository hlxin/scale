"""SCALE's terms mapped to terms of other ontologies (docs/mappings.md).

A mapping says how a SCALE term relates to a term someone else defines: exact, close, broad (the other term is
broader), narrow or related. The mappings are kept beside the schema, one set per layer (core/mappings/kernel.yaml,
domain/mappings/catalysis.yaml), with the registry of the ontologies they cite (core/mappings/ontologies.yaml); they
change nothing SCALE validates or queries. Every mapping names a term of the head schema (a layer's labels and edge
types are its own) and a CURIE of a registered ontology in its pattern; ``describe`` shows a term's mappings; a layer's
set exports as SSSOM; the catalysis set records the fourteen subdomains of catalysis research of Ontologies4Cat
(Behr, Borgelt and Kockmann 2024) with the SCALE terms that record each and how the authors' collection rates the
ontologies it holds for each, as it gives them."""

import copy
import csv
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


def test_the_subdomains_are_the_fourteen_of_ontologies4cat_and_name_terms_of_the_schema(tmp_path, spec):
    rows = mappings.subdomains(REPO)
    assert [r["subdomain"] for r in rows] == list(mappings.SUBDOMAINS)
    bio = rows[0]
    assert bio["scale"] == [] and "enzyme" in bio["gap"] and bio["contained"] == ["SBO"]
    het = next(r for r in rows if r["subdomain"] == "heterogeneous_catalysis")
    assert "Catalyst" in het["scale"] and het["contained"] == [] and "ChEBI" in het["mapped"]
    char = next(r for r in rows if r["subdomain"] == "characterisation_data")
    assert "CHMO" in char["contained"] and "CHMO" in char["mapped"]
    cat = load_yaml(REPO / layout.DOMAIN_MAPPINGS)
    cat["subdomains"]["biocatalysis"]["scale"] = ["Enzyme"]
    cat["subdomains"]["catalyst_design"] = copy.deepcopy(cat["subdomains"]["biocatalysis"])
    cat["subdomains"]["photocatalysis"]["ontologies4cat"]["contained"] = ["AFO"]       # AFO is rated related too
    cat["subdomains"]["electrocatalysis"]["ontologies4cat"]["related"] = ["AFO"]       # the merged rating of before
    msgs = _messages(mappings.check(_tree(tmp_path, catalysis=cat), spec))
    assert any("subdomains.biocatalysis: Enzyme is no label or edge type of the schema" in x for x in msgs)
    assert any("subdomains: unknown subdomain 'catalyst_design'" in x for x in msgs)
    assert any("subdomains.photocatalysis.ontologies4cat: AFO is rated twice (contained and related_" in x for x in msgs)
    assert any("subdomains.electrocatalysis.ontologies4cat: unknown key 'related'" in x for x in msgs)
    kern = load_yaml(REPO / layout.KERNEL_MAPPINGS)
    kern["subdomains"] = {"biocatalysis": load_yaml(REPO / layout.DOMAIN_MAPPINGS)["subdomains"]["biocatalysis"]}
    msgs = _messages(mappings.check(_tree(tmp_path, kernel=kern), spec))
    assert any("subdomains are subdomains of catalysis research; they belong to the catalysis set" in x for x in msgs)


def test_the_ratings_are_the_collections_as_it_gives_them():
    """The collection rates each ontology contained, related: narrower, related: broader or missing, and its own
    tables count a rating that says contained as contained (SBO's "contained: broader" for material modelling).
    Its eNanoMapper entry repeats its RO entry; both are listed as given."""
    rows = {r["subdomain"]: r for r in mappings.subdomains(REPO)}
    for s in ("chemical_substance_modelling", "material_modelling", "process_modelling"):
        assert "SBO" in rows[s]["contained"], s
    bio = rows["biocatalysis"]
    assert bio["contained"] == ["SBO"] and bio["related_narrower"] == ["BAO", "EDAM", "OBI"]
    assert bio["related_broader"] == ["ChEBI", "CHEMINF", "eNanoMapper", "MS", "RO"]
    heat = rows["heat_transport_and_kinetic_data"]
    assert heat["contained"] == [] and heat["related_narrower"] == ["OntoCAPE"]
    energy = rows["process_design_energy_and_cost_data"]
    assert energy["contained"] == ["OEO", "OntoCAPE"]              # the paper (23 ontologies) found one; OEO came later
    for r in rows.values():
        named = [o for k in mappings.RATINGS for o in r[k]]
        assert len(named) == len(set(named)), r["subdomain"]


def test_describe_shows_a_terms_mappings_and_those_of_its_values(spec):
    idx = mappings.index(REPO)
    d = pgraph.describe(spec, ["Treatment", "ReferenceElectrode", "HAS_INPUT", "Experiment"], None, idx)
    ref = d["labels"]["ReferenceElectrode"]["mappings"]
    assert ref == [{"match": "exact", "term": "CHMO:0002345", "label": "reference electrode",
                    "iri": "http://purl.obolibrary.org/obo/CHMO_0002345"}]
    calc = d["labels"]["Treatment"]["property_mappings"]["treatment_kind=calcination"]
    assert calc[0]["term"] == "CHMO:0001467" and calc[0]["match"] == "close"
    assert {m["term"] for m in d["edges"]["HAS_INPUT"]["mappings"]} == {"OBI:0000293", "prov:used"}
    # the kernel's maps_to names an obsolete OBI term in words; an experiment is COB's planned process, and only a
    # completed one is the completely executed planned process OBI points to
    exp = d["labels"]["Experiment"]
    assert "OBI planned process" in exp["maps_to"]
    assert any(m["term"] == "COB:0000082" and m["match"] == "broad" for m in exp["mappings"])
    assert not any(m["term"] == "COB:0000035" for m in exp["mappings"])
    assert exp["property_mappings"]["experiment_status=completed"][0]["term"] == "COB:0000035"
    # without mappings, describe is as it was
    plain = pgraph.describe(spec, ["Treatment"], None)
    assert "mappings" not in plain["labels"]["Treatment"] and "property_mappings" not in plain["labels"]["Treatment"]


def test_no_mapping_cites_an_obi_term_obi_made_obsolete():
    terms = {r["term"] for r in mappings.rows(REPO)}
    assert not terms & {"OBI:0000011", "OBI:0000968", "OBI:0000094"}


def _read_sssom(text):
    """An SSSOM TSV text as its metadata and its rows, read as the format says: the commented YAML block, then the
    table, cells unquoted."""
    lines = text.splitlines()
    meta = yaml.safe_load("\n".join(x[1:] for x in lines if x.startswith("#")))
    table = list(csv.reader([x for x in lines if not x.startswith("#")], delimiter="\t"))
    return meta, table[0], [dict(zip(table[0], r)) for r in table[1:]], table[1:]


def test_the_sssom_export_lists_every_mapping_with_its_skos_relation():
    meta, head, body, raw = _read_sssom(mappings.sssom(REPO, "catalysis", "0.7.0"))
    assert meta["mapping_set_id"].endswith("/domain/mappings/catalysis.yaml")
    assert meta["license"] == "https://creativecommons.org/licenses/by/4.0/"
    assert meta["subject_source_version"] == "0.7.0"
    assert head == ["subject_id", "subject_label", "predicate_id", "object_id", "object_label", "mapping_justification",
                    "comment"]
    assert len(body) == mappings.check(REPO)["counts"]["catalysis"]
    row = {(r["subject_id"], r["object_id"]): r for r in body}
    assert row[("scalecatal:ReferenceElectrode", "CHMO:0002345")]["predicate_id"] == "skos:exactMatch"
    assert row[("scalecatal:Treatment.treatment_kind=calcination", "CHMO:0001467")]["predicate_id"] == "skos:closeMatch"
    assert all(r["mapping_justification"] == "semapv:ManualMappingCuration" for r in body)
    assert all(len(r) == len(head) for r in raw)
    # every identifier (an entity reference, in SSSOM's words) is a CURIE of a prefix the curie_map declares,
    # the subject source included; an IRI there would make SSSOM readers reject the file
    refs = [meta["subject_source"], *(r[k] for r in body for k in ("subject_id", "predicate_id", "object_id",
                                                                  "mapping_justification"))]
    for ref in refs:
        assert not ref.startswith(("http://", "https://")) and ref.split(":", 1)[0] in meta["curie_map"], ref
    assert meta["subject_source"] == "scale:domain/graph/catalysis.yaml"
    assert meta["curie_map"]["scale"] + "domain/graph/catalysis.yaml" == meta["mapping_set_id"].replace(
        "domain/mappings/catalysis.yaml", "domain/graph/catalysis.yaml")


def test_the_sssom_export_quotes_what_a_reader_would_misread(tmp_path, spec):
    """A title with a colon stays one YAML value; a note with double quotes, a tab or a line break stays one cell."""
    cat = load_yaml(REPO / layout.DOMAIN_MAPPINGS)
    cat["title"] = 'SCALE: catalysis "terms"'
    cat["mappings"]["ReferenceElectrode"][0]["note"] = 'Said "the same"\tin\nCHMO.'
    tree = _tree(tmp_path, catalysis=cat)
    meta, head, body, raw = _read_sssom(mappings.sssom(tree, "catalysis"))
    assert meta["mapping_set_title"] == 'SCALE: catalysis "terms"'
    ref = next(r for r in body if r["subject_id"] == "scalecatal:ReferenceElectrode")
    assert ref["comment"] == 'Said "the same" in CHMO.'
    assert all(len(r) == len(head) for r in raw)


def test_the_command_checks_lists_and_exports_the_mappings():
    run = lambda *a: subprocess.run([sys.executable, "-c", RUN_SCALE, str(REPO / "tools"), "--repo", str(REPO),   # noqa: E731
                                     "schema", "mappings", *a], capture_output=True, text=True)
    r = run("--check")
    assert r.returncode == 0 and "every one on a term of the schema and of a registered ontology" in r.stdout, r.stderr
    r = run("--layer", "kernel")
    assert r.returncode == 0 and "COB:0000035" in r.stdout and "CHMO:" not in r.stdout
    r = run("--format", "sssom")
    assert r.returncode != 0 and "--layer kernel or --layer catalysis" in r.stderr
    r = run("--subdomains")
    assert r.returncode == 0 and "Biocatalysis" in r.stdout and "nothing yet" in r.stdout
    assert "related, narrower: BAO, EDAM, OBI" in r.stdout


def test_a_catalyst_is_related_to_chebis_catalyst_role_and_only_completed_work_is_completely_executed():
    """A thing and the role it plays are related, never close (ChEBI's catalyst is a role); COB's completely executed
    terms name only a completed experiment or procedure, since SCALE records proposed, running and failed ones."""
    rows = mappings.rows(REPO)
    cat = next(r for r in rows if r["subject"] == "Catalyst" and r["term"] == "CHEBI:35223")
    assert cat["match"] == "related"
    done = {r["subject"] for r in rows if r["term"] in ("COB:0000035", "COB:0000110")}
    assert done == {"Experiment.experiment_status=completed", "Procedure.procedure_status=completed"}


def test_a_malformed_set_is_reported_and_leaves_the_rest_readable(tmp_path, spec):
    """A subject whose mappings are not a list, or a section that is not keyed by subject, is an error of the check;
    reading the mappings for describe skips it rather than failing every description."""
    cat = load_yaml(REPO / layout.DOMAIN_MAPPINGS)
    cat["mappings"]["Treatment"] = {"match": "close", "term": "CHMO:0001467", "label": "calcination"}
    cat["mappings"]["Reactor"] = ["CHMO:0000136"]
    tree = _tree(tmp_path, catalysis=cat)
    msgs = _messages(mappings.check(tree, spec))
    assert any("Treatment: a subject lists its mappings" in x for x in msgs), msgs
    assert any("Reactor[0]: a mapping is a mapping of match, term, label" in x for x in msgs), msgs
    idx = mappings.index(tree)
    assert "Treatment" not in idx and "Reactor" not in idx and idx["ReferenceElectrode"]
    d = pgraph.describe(spec, ["Catalyst"], None, idx)
    assert d["labels"]["Catalyst"]["mappings"]
    kern = load_yaml(REPO / layout.KERNEL_MAPPINGS)
    kern["mappings"] = [kern["mappings"]["Experiment"]]
    tree = _tree(tmp_path, kernel=kern)
    assert any("mappings is a mapping keyed by subject" in x for x in _messages(mappings.check(tree, spec)))
    assert "Experiment" not in mappings.index(tree)


def test_a_key_given_twice_is_an_error_not_a_silent_loss(tmp_path, spec):
    """YAML keeps the second of two equal keys and drops the first; a mapping file refuses it."""
    tree = _tree(tmp_path)
    p = tree / layout.DOMAIN_MAPPINGS
    p.write_text(p.read_text().replace("\nmappings:\n", "\nmappings:\n  Catalyst:\n  - match: close\n"
                                       "    term: CHEBI:35223\n    label: catalyst\n", 1))
    msgs = _messages(mappings.check(tree, spec))
    assert any(f"{layout.DOMAIN_MAPPINGS}: line" in x and "'Catalyst' is given twice" in x for x in msgs), msgs
    with pytest.raises(mappings.ScaleError, match="is given twice"):
        mappings.index(tree)
    r = tree / layout.ONTOLOGY_REGISTRY
    r.write_text(r.read_text().replace("ontologies:\n", "ontologies:\n  CHMO:\n    name: x\n", 1))
    assert any("'CHMO' is given twice" in x for x in _messages(mappings.check(tree, spec)))


def test_a_declared_set_or_the_registry_missing_is_an_error(tmp_path, spec):
    """CORE.yaml and DOMAIN.yaml declare the sets; one declared but missing, or the registry missing, fails the check
    instead of checking nothing."""
    tree = _tree(tmp_path)
    for rel in (layout.CORE_MANIFEST, layout.DOMAIN_DECLARATION):
        (tree / rel).write_text(yaml.safe_dump({"mappings": "mappings/x.yaml"}))
    assert mappings.declared(tree) == {"kernel": layout.CORE_MANIFEST, "catalysis": layout.DOMAIN_DECLARATION}
    assert mappings.check(tree, spec)["ok"]
    (tree / layout.KERNEL_MAPPINGS).unlink()
    msgs = _messages(mappings.check(tree, spec))
    assert any(f"is missing; {layout.CORE_MANIFEST} declares it" in x for x in msgs), msgs
    (tree / layout.ONTOLOGY_REGISTRY).unlink()
    msgs = _messages(mappings.check(tree, spec))
    assert any(f"{layout.ONTOLOGY_REGISTRY} is missing" in x for x in msgs), msgs
    # a repository that declares no set needs none
    (tree / layout.CORE_MANIFEST).write_text(yaml.safe_dump({"core": "x"}))
    (tree / layout.DOMAIN_DECLARATION).write_text(yaml.safe_dump({"domain": "x"}))
    assert mappings.declared(tree) == {}
