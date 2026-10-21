"""Terms for the areas of catalysis research that SCALE lacked (scale-catal 0.7.1 on).

Ontologies4Cat (Behr, Borgelt and Kockmann 2024) classifies ontologies by fourteen areas of catalysis research; mapping
SCALE onto those areas (docs/mappings.md) showed four it did not cover: biocatalysis, the ligand and the turnover number
of homogeneous catalysis, the criteria of a transport check, and the energy a process takes. 0.7.1 adds them as
provisional terms: an enzyme or whole-cell catalyst, a macromolecule, the roles ligand, solvent, cocatalyst and
cofactor, a test's catalysis mode as its source describes it, and the kinds enzyme_activity (with the enzyme unit, U,
and the katal), michaelis_constant, turnover_number, transport_criterion (compared by the criterion its definition
names), effectiveness_factor, thiele_modulus and energy_consumption. Exercised on the area example
(domain/examples/scale-catal/area-examples/) and variants written in memory."""

import copy
import shutil
import subprocess
import sys

import pytest

from conftest import EXAMPLES, GRAPH_MANIFEST, HEAD_VERSION, REPO, spec_at, spec_of
from scale import mappings, pgraph, pgraph_migrate, pgraph_query, quantities
from scale.schema_change import diff_specs, tier
from scale.util import load_doc, write_canonical

AE = EXAMPLES / "scale-catal/area-examples"
DOC = AE / "catalysis-areas.json"
P = "ex:ca"


@pytest.fixture
def doc():
    return load_doc(DOC)


def _node(d: dict, local: str) -> dict:
    return next(x for x in d["nodes"] if x["id"] == f"{P}/{local}")


def _rank(d: dict, label: str, kinds, context: dict | None = None, where: list | None = None) -> dict:
    """A scientific ranking of the results of ``kinds`` that records of ``label`` hold."""
    ob = {"var": "e", "prop": "value", **({"context": context} if context else {})}
    match = {"label": label, "as": "rec", **({"where": where} if where else {})}
    return pgraph_query.run(d, spec_of(d), {"comparison": "scientific", "match": match,
                                            "steps": [{"from": "rec", "entries": "result_values", "kind": kinds, "as": "e"}],
                                            "return": ["rec.name", "e"], "order_by": [ob]})


def _groups(res: dict) -> list[dict]:
    return [g["compared_on"]["e.value"] for g in res["comparison"]["groups"]]


def test_the_example_is_built_reproducibly(tmp_path):
    work = tmp_path / "ae"
    shutil.copytree(AE, work)
    subprocess.run([sys.executable, str(work / "build_examples.py")], check=True, capture_output=True, cwd=REPO)
    d = load_doc(DOC)
    if d["graph"]["schema_version"] != HEAD_VERSION:              # the head moved on after it was built
        d = pgraph_migrate.raise_version(d, HEAD_VERSION, pgraph.load_spec(GRAPH_MANIFEST))[0]
    write_canonical(tmp_path / DOC.name, d)
    assert (work / DOC.name).read_bytes() == (tmp_path / DOC.name).read_bytes()


def test_the_example_is_valid_balanced_and_conformant(doc):
    rep = pgraph.validate(doc, spec_of(doc))
    assert rep.errors == [] and rep.warnings == [], (rep.errors, rep.warnings)
    assert rep.balance["records"] and all(r["atoms"]["status"] == "balanced" and r["charge"]["status"] == "balanced"
                                          for r in rep.balance["records"])


def test_an_enzyme_is_a_catalyst_of_its_family_with_its_cofactor_and_solvent_on_the_edge(doc):
    cat = _node(doc, "catalyst/adh-silica")["props"]
    assert cat["catalyst_family"] == "enzyme"
    enzyme = _node(doc, "species/adh")["props"]
    assert enzyme["species_kind"] == "macromolecule" and "formula" not in enzyme
    assert enzyme["identifiers"] == {"ec": "1.1.1.1"}
    roles = {(e["source"].split("/", 1)[1], e["props"]["role"]) for e in doc["links"] if e["type"] == "HAS_COMPONENT"}
    assert {("feed/assay-mixture", "cofactor"), ("feed/assay-mixture", "solvent"),
            ("catalyst/rh-pph3", "ligand"), ("catalyst/adh-silica", "support")} <= roles


def test_an_activity_per_time_and_one_per_mass_are_two_quantities(doc):
    res = _rank(doc, "CatalyticTest", "enzyme_activity")
    units = sorted(g["unit"] for g in _groups(res))
    assert units == ["U", "U/mg"] and len(res["rows"]) == 2
    qc = quantities.contracts(spec_of(doc))
    assert qc.dimension_name(qc.read_unit("U").vector).startswith("molar_flow")
    assert qc.dimension_name(qc.read_unit("U/mg").vector).startswith("amount_per_mass_time")
    assert qc.dimension_name(qc.read_unit("nkat").vector).startswith("molar_flow")


def test_a_michaelis_constant_is_a_concentration_of_one_substrate(doc):
    res = _rank(doc, "Analysis", "michaelis_constant")
    assert [r["values"]["e"]["value"] for r in res["rows"]] == [1.8]
    assert _groups(res)[0]["context"] == {"species": f"{P}/species/ethanol"}


def test_a_turnover_number_is_never_compared_with_a_turnover_frequency(doc):
    d = copy.deepcopy(doc)
    t = _node(d, "test/rh-hydrogenation")["props"]
    d["nodes"].append({"id": f"{P}/variable/tof-octane", "label": "Variable",
                       "props": {"name": "turnover frequency to octane", "scale": "quantitative",
                                 "quantity_kind": "turnover_frequency", "unit": "s-1", "origin": "synthetic"}})
    t["result_values"].append({"status": "present", "value": 0.13, "unit": "s-1", "id": "tof",
                               "variable": f"{P}/variable/tof-octane", "target": f"{P}/species/octane",
                               "normalized_by": {"status": "present", "value": 1, "unit": "1",
                                                 "definition": "per Rh atom charged"},
                               "evidence_ids": ["t2"]})
    res = _rank(d, "CatalyticTest", ["turnover_number", "turnover_frequency"])
    assert {g["kind"] for g in _groups(res)} == {"turnover_number", "turnover_frequency"}
    assert len({r["comparison_group"] for r in res["rows"]}) == 2


def test_transport_criteria_are_compared_by_the_criterion_their_definition_names(doc):
    res = _rank(doc, "Analysis", "transport_criterion")
    by = {g["context"]["transport_criterion"] for g in _groups(res)}
    assert by == {"weisz_prater", "mears"} and len(res["rows"]) == 4
    assert [x["reason"].split()[0] for x in res["excluded"]] == ["missing_context"]   # the criterion not named
    wp = _rank(doc, "Analysis", "transport_criterion", context={"transport_criterion": "weisz_prater"})
    assert [r["values"]["e"]["value"] for r in wp["rows"]] == [0.04, 2.6]
    assert sorted(x["reason"].split()[0] for x in wp["excluded"]) == ["incompatible_context", "incompatible_context",
                                                                      "missing_context"]


def test_an_effectiveness_factor_and_a_thiele_modulus_are_their_own_kinds(doc):
    eta = _rank(doc, "Analysis", "effectiveness_factor")
    phi = _rank(doc, "Analysis", "thiele_modulus")
    assert sorted(r["values"]["e"]["value"] for r in eta["rows"]) == [0.62, 0.99]
    assert sorted(r["values"]["e"]["value"] for r in phi["rows"]) == [0.2, 2.3]


def test_energy_per_mole_and_per_kilogram_of_product_stay_apart(doc):
    res = _rank(doc, "CatalyticTest", "energy_consumption")
    assert sorted(g["unit"] for g in _groups(res)) == ["kJ/mol", "kWh/kg"] and len(res["rows"]) == 4
    qc = quantities.contracts(spec_of(doc))
    assert qc.dimension_name(qc.read_unit("kWh/kg").vector).startswith("specific_energy")


def test_the_catalysis_mode_is_the_sources_words_from_a_closed_list(doc):
    modes = {n["props"]["name"]: n["props"]["catalysis_mode"] for n in doc["nodes"] if n["label"] == "CatalyticTest"}
    assert set(modes.values()) == {"biocatalytic", "homogeneous", "heterogeneous"}
    d = copy.deepcopy(doc)
    _node(d, "test/rh-hydrogenation")["props"]["catalysis_mode"] = "molecular"
    rep = pgraph.validate(d, spec_of(d))
    assert any("catalysis_mode: 'molecular' is not one of" in e["message"] for e in rep.errors)


def test_an_activity_or_a_turnover_number_in_a_unit_of_another_dimension_is_an_error(doc):
    d = copy.deepcopy(doc)
    _node(d, "test/adh-assay")["props"]["result_values"][0]["unit"] = "kJ"
    _node(d, "test/rh-hydrogenation")["props"]["result_values"][0]["unit"] = "s-1"
    msgs = [e["message"] for e in pgraph.validate(d, spec_of(d)).errors]
    assert any("not a dimension of enzyme_activity" in m for m in msgs)
    assert any("not a dimension of turnover_number" in m for m in msgs)


def test_the_new_terms_are_mapped_and_the_transport_kinds_have_no_ontology_term():
    idx = mappings.index(REPO)
    assert idx["CatalyticTest.catalysis_mode=homogeneous"][0]["term"] == "REX:0000082"
    assert idx["Catalyst.catalyst_family=enzyme"][0]["term"] == "SBO:0000014"
    assert idx["HAS_COMPONENT.role=ligand"][0]["term"] == "CHEBI:52214"
    assert idx["unit:U"][0]["term"] == "unit:ENZ"          # never QUDT's unit:U, the unified atomic mass unit
    assert {m["term"] for m in idx["kind:enzyme_activity"]} == {"SBO:0000559", "SBO:0000558",
                                                               "quantitykind:CatalyticActivity"}
    assert not any(f"kind:{k}" in idx for k in ("transport_criterion", "effectiveness_factor", "thiele_modulus"))
    areas = {a["area"]: a for a in mappings.areas(REPO)}
    assert areas["biocatalysis"]["scale"] and "Catalyst" in areas["biocatalysis"]["scale"]


def test_the_photoelectrode_names_a_role_the_vocabulary_holds():
    spec = spec_at("0.7.1")
    assert "role cocatalyst" in spec["nodes"]["Photoelectrode"]["description"]
    assert "cocatalyst" in spec["edges"]["HAS_COMPONENT"]["properties"]["role"]["values"]


def test_the_change_is_additive():
    d = diff_specs(spec_at("0.7.0"), spec_at("0.7.1"))
    assert tier(d) == 2 and not d["removed"] and not d["changed"] and not d["narrowed"]
    assert {"quantities.kinds.turnover_number", "quantities.kinds.enzyme_activity", "quantities.kinds.transport_criterion",
            "nodes.CatalyticTest.catalysis_mode", "edges.HAS_COMPONENT.role = ligand"} <= set(d["added"])
    assert {"quantities.units: U is read (molar_flow)", "quantities.units: kat is read (molar_flow, prefixed)"} \
        <= set(d["loosened"])
