"""External identifiers on records (docs/mappings.md).

A record's ``identifiers`` map a scheme to an identifier. A scheme of core/mappings/identifiers.yaml is checked by its
pattern (and the check digit of a CAS Registry Number or an ORCID iD): an identifier that does not look like one is a
warning and stays as written; a scheme the registry does not list is kept, unchecked. A technique's or a method's
identifier is an ontology term: a CURIE of an ontology of core/mappings/ontologies.yaml in its pattern, or an IRI."""

import copy

import yaml

from conftest import EXAMPLES, REPO, spec_of
from scale import identifiers, layout, pgraph
from scale.util import load_doc, load_yaml

AREAS = EXAMPLES / "scale-catal/area-examples/catalysis-areas.json"
EXAMPLE = EXAMPLES / "scale-catal/example.json"


def _warnings(doc: dict) -> list[str]:
    rep = pgraph.validate(doc, spec_of(doc))
    assert rep.errors == [], rep.errors                    # a warning never makes a document invalid
    return [w["message"] for w in rep.warnings]


def test_every_scheme_is_well_formed_and_its_example_is_one_of_it():
    assert identifiers.check_registry(REPO) == []
    s = identifiers.schemes(REPO)
    assert {"doi", "orcid", "ror", "inchikey", "pubchem_cid", "chebi", "cas", "ec", "uniprot", "mp", "patent"} <= set(s)
    for key, scheme in s.items():
        if scheme.get("example") is not None:
            assert identifiers.identifier_problem(scheme, str(scheme["example"])) is None, key


def test_check_digits_of_a_cas_number_and_an_orcid():
    assert identifiers.check_digit_ok("cas", "7732-18-5")              # water
    assert not identifiers.check_digit_ok("cas", "7732-18-4")
    assert identifiers.check_digit_ok("iso7064_mod11_2", "0000-0002-1825-0097")
    assert not identifiers.check_digit_ok("iso7064_mod11_2", "0000-0002-1825-0098")
    assert identifiers.check_digit_ok("iso7064_mod11_2", "0000-0002-9079-593X")


def test_an_identifier_that_does_not_look_like_its_scheme_is_a_warning_and_stays():
    doc = load_doc(AREAS)
    assert _warnings(doc) == []                            # the EC number 1.1.1.1 is one
    d = copy.deepcopy(doc)
    species = next(n for n in d["nodes"] if n["id"] == "ex:ca/species/ethanol")
    species["props"]["identifiers"] = {"cas": "64-17-6", "inchikey": "LFQSCWFLJHTTHZ", "chebi": "16236",
                                       "doi": "doi:10.1021/ja000001", "nist_webbook": "C64175"}
    enzyme = next(n for n in d["nodes"] if n["id"] == "ex:ca/species/adh")
    enzyme["props"]["identifiers"]["ec"] = "1.1.1"
    msgs = _warnings(d)
    assert any("identifiers.cas: '64-17-6' fails the check digit of its scheme (CAS Registry Number)" in m for m in msgs)
    for key, value, name in (("inchikey", "LFQSCWFLJHTTHZ", "Standard InChIKey"), ("chebi", "16236", "ChEBI identifier"),
                             ("doi", "doi:10.1021/ja000001", "Digital Object Identifier"),
                             ("ec", "1.1.1", "Enzyme Commission number")):
        assert any(f"identifiers.{key}: '{value}' does not match the pattern of its scheme ({name}," in m for m in msgs), key
    assert not any("nist_webbook" in m for m in msgs)       # a scheme the registry does not list is not checked
    assert all(m.endswith("it stays as written") for m in msgs if m.startswith("identifiers."))
    species["props"]["identifiers"] = {"cas": "64-17-5", "inchikey": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N", "chebi": "CHEBI:16236"}
    enzyme["props"]["identifiers"]["ec"] = "1.1.1.1"
    assert _warnings(d) == []                              # ethanol's CAS number, InChIKey and ChEBI id


def test_a_technique_or_method_identifier_is_an_ontology_term():
    doc = load_doc(EXAMPLE)
    d = copy.deepcopy(doc)
    d["nodes"].append({"id": "ex:exmpl/thermo/characterization/xrd", "label": "Characterization",
                       "props": {"name": "XRD of the fresh catalyst", "technique": "X-ray diffraction",
                                 "technique_id": "XRD", "origin": "synthetic"}})
    test = next(n for n in d["nodes"] if n["label"] == "CatalyticTest")
    test["props"]["method_id"] = "CHMO:156"
    msgs = [m for m in _warnings_or_errors(d) if "technique_id" in m or "method_id" in m]
    assert any("technique_id: 'XRD' is no ontology term" in m for m in msgs), msgs
    assert any("method_id: 'CHMO:156' does not match the pattern of CHMO terms" in m for m in msgs), msgs
    xrd = next(n for n in d["nodes"] if n["id"] == "ex:exmpl/thermo/characterization/xrd")
    xrd["props"]["technique_id"] = "CHMO:0000156"
    test["props"]["method_id"] = "http://purl.obolibrary.org/obo/CHMO_0000158"
    assert not [m for m in _warnings_or_errors(d) if "technique_id" in m or "method_id" in m]


def _warnings_or_errors(doc: dict) -> list[str]:
    rep = pgraph.validate(doc, spec_of(doc))
    return [x["message"] for x in [*rep.errors, *rep.warnings]]


def test_a_registry_entry_with_a_loose_pattern_or_an_example_it_rejects_is_an_error(tmp_path):
    reg = load_yaml(REPO / layout.IDENTIFIER_REGISTRY)
    reg["schemes"]["ec"]["pattern"] = r"\d+\.\d+"
    reg["schemes"]["cas"]["example"] = "7732-18-4"
    reg["schemes"]["doi"]["resolves"] = "https://doi.org/"
    reg["schemes"]["mp"]["check_digit"] = "luhn"
    p = tmp_path / layout.IDENTIFIER_REGISTRY
    p.parent.mkdir(parents=True)
    p.write_text(yaml.safe_dump(reg, sort_keys=False, allow_unicode=True))
    msgs = [e["message"] for e in identifiers.check_registry(tmp_path)]
    assert any("ec: pattern must match a whole identifier" in m for m in msgs), msgs
    assert any("cas: its example '7732-18-4' fails the check digit" in m for m in msgs), msgs
    assert any("doi: resolves must name {id}" in m for m in msgs), msgs
    assert any("mp: check_digit 'luhn' is not one of" in m for m in msgs), msgs
