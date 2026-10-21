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
import yaml

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


def test_an_activity_per_time_per_mass_and_per_volume_are_three_quantities(doc):
    res = _rank(doc, "CatalyticTest", "enzyme_activity")
    units = sorted(g["unit"] for g in _groups(res))
    assert units == ["U", "U/mg", "mU/mL"] and len(res["rows"]) == 3
    qc = quantities.contracts(spec_of(doc))
    for unit, dim in (("U", "molar_flow"), ("mU", "molar_flow"), ("kU", "molar_flow"), ("nkat", "molar_flow"),
                      ("U/mg", "amount_per_mass_time"), ("U/mL", "amount_per_volume_time"),
                      ("mU/mL", "amount_per_volume_time")):
        r = qc.read_unit(unit)
        assert r.read and not r.unread and qc.dimension_name(r.vector).startswith(dim), unit


def test_the_enzyme_assay_adds_up(doc):
    """The activity of the charge is its enzyme (1 mg at 48 mg/g) times the specific activity, and per millilitre it is
    that over the 5 mL of the assay mixture."""
    assay = _node(doc, "test/adh-assay")["props"]
    got = {v["id"]: v for v in assay["result_values"]}
    charge = next(e for e in doc["links"] if e["type"] == "USES_CATALYST" and e["source"] == f"{P}/test/adh-assay")
    loading = next(e for e in doc["links"] if e["type"] == "HAS_COMPONENT"
                   and e["source"] == f"{P}/catalyst/adh-silica" and e["props"]["role"] == "active_component")
    assert charge["props"]["amount"]["unit"] == "mg" and loading["props"]["loading"]["unit"] == "mg/g"
    enzyme_mg = charge["props"]["amount"]["value"] * loading["props"]["loading"]["value"] / 1000
    assert got["specific_activity"]["value"] * enzyme_mg == pytest.approx(got["activity"]["value"])
    assert got["activity"]["value"] / 5 * 1000 == pytest.approx(got["volumetric_activity"]["value"])     # mU/mL


def test_an_activity_or_a_turnover_number_may_name_what_it_is_divided_by(doc):
    """A specific activity is divided by a mass, a volumetric one by a volume, a turnover number by an amount of catalyst
    or a count of sites: each may name it (normalized_by) or say it in words; a denominator of another dimension is an
    error."""
    d = copy.deepcopy(doc)
    assay = _node(d, "test/adh-assay")["props"]
    assay["conditions"]["enzyme_mass"] = {"status": "present", "value": 48, "unit": "µg",
                                          "definition": "ADH in the 1 mg charge, from its loading"}
    by = {v["id"]: v for v in assay["result_values"]}
    by["specific_activity"]["normalized_by"] = {"record": f"{P}/test/adh-assay", "path": "/conditions/enzyme_mass"}
    by["volumetric_activity"]["normalized_by"] = {"record": f"{P}/reactor/stirred-vial", "path": "/volume"}
    rh = _node(d, "test/rh-hydrogenation")["props"]
    rh["conditions"] = {"rh_amount": {"status": "present", "value": 2.5, "unit": "µmol", "definition": "Rh charged"}}
    rh["result_values"][0]["normalized_by"] = {"record": f"{P}/test/rh-hydrogenation", "path": "/conditions/rh_amount"}
    rep = pgraph.validate(d, spec_of(d))
    assert rep.errors == [], rep.errors
    by["specific_activity"]["normalized_by"] = {"record": f"{P}/test/adh-assay", "path": "/temperature"}
    msgs = [e["message"] for e in pgraph.validate(d, spec_of(d)).errors]
    assert any("not a denominator of enzyme_activity" in m for m in msgs), msgs


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


def test_a_mears_criterion_is_compared_only_with_one_judging_the_same_transport(doc):
    """Mears gave a criterion for external diffusion and one for heat transfer between the fluid and the particle, two
    formulas: a Mears value is grouped by the transport its definition names, and one that names none is left out."""
    d = copy.deepcopy(doc)
    check = _node(d, "analysis/transport-fine")["props"]
    var = check["result_values"][0]["variable"]
    for i, (value, said) in enumerate(((0.001, "Mears criterion for heat transfer between the fluid and the particle"),
                                       (0.05, "Mears criterion"))):
        check["result_values"].append({"status": "present", "value": value, "unit": "1", "id": f"mears_{i}",
                                       "variable": var, "definition": said, "evidence_ids": ["s4_fine"]})
    res = _rank(d, "Analysis", "transport_criterion")
    mears = sorted(g["context"].get("transport_mode", "") for g in _groups(res)
                   if g["context"]["transport_criterion"] == "mears")
    assert mears == ["external_heat_transfer", "external_mass_transfer"]
    heat = [r for r in res["rows"] if r["values"]["e"]["value"] == 0.001]
    mass = [r for r in res["rows"] if r["values"]["e"]["value"] in (0.002, 0.03)]
    assert len(heat) == 1 and len(mass) == 2 and heat[0]["comparison_group"] not in {r["comparison_group"] for r in mass}
    assert sorted(x["reason"].split()[0] for x in res["excluded"]) == ["missing_context", "missing_context"]
    assert any("transport_mode" in x["reason"] for x in res["excluded"])          # the unqualified Mears criterion
    # the Weisz-Prater values need no transport_mode: their criterion names what it judges
    assert all("transport_mode" not in g["context"] for g in _groups(res)
               if g["context"]["transport_criterion"] == "weisz_prater")


def test_an_effectiveness_factor_and_a_thiele_modulus_are_compared_within_their_convention(doc):
    eta = _rank(doc, "Analysis", "effectiveness_factor")
    phi = _rank(doc, "Analysis", "thiele_modulus")
    assert sorted(r["values"]["e"]["value"] for r in eta["rows"]) == [0.62, 0.99]
    assert sorted(r["values"]["e"]["value"] for r in phi["rows"]) == [0.2, 2.3]
    assert _groups(phi)[0]["context"] == {"characteristic_length": "volume_to_surface", "thiele_form": "generalized"}
    assert _groups(eta)[0]["context"] == {"effectiveness_basis": "internal"}
    # a first-order modulus with the particle radius is another quantity (three times larger for a sphere), an
    # overall effectiveness factor another than an internal one, and one that states no convention is left out
    d = copy.deepcopy(doc)
    check = _node(d, "analysis/transport-coarse")["props"]["result_values"]
    by = {v["id"]: v for v in check}
    by["thiele_modulus"]["definition"] = "first-order Thiele modulus with the particle radius"
    by["effectiveness_factor"]["definition"] = "overall effectiveness factor"
    fine = {v["id"]: v for v in _node(d, "analysis/transport-fine")["props"]["result_values"]}
    del fine["thiele_modulus"]["definition"]
    phi = _rank(d, "Analysis", "thiele_modulus")
    assert [r["values"]["e"]["value"] for r in phi["rows"]] == [2.3]
    assert _groups(phi)[0]["context"] == {"characteristic_length": "particle_radius", "thiele_form": "first_order"}
    assert [x["reason"].split()[0] for x in phi["excluded"]] == ["missing_context"]
    eta = _rank(d, "Analysis", "effectiveness_factor")
    assert len({r["comparison_group"] for r in eta["rows"]}) == 2


def test_energy_of_two_sources_or_two_boundaries_is_never_compared(doc):
    """The electrical energy into the cell and the energy of the whole plant, separation included, are two quantities;
    one that says neither which energy nor over what is left out."""
    d = copy.deepcopy(doc)
    plant = {v["id"]: v for v in _node(d, "test/co2-electrolysis-300")["props"]["result_values"]}
    plant["energy_per_mol"]["definition"] = "electrical energy into the whole plant, separation included, per mole of CO"
    cell = {v["id"]: v for v in _node(d, "test/co2-electrolysis-100")["props"]["result_values"]}
    del cell["energy_per_kg"]["definition"]
    res = _rank(d, "CatalyticTest", "energy_consumption")
    per_mol = [r for r in res["rows"] if r["values"]["e"]["unit"] == "kJ/mol"]
    assert len(per_mol) == 2 and len({r["comparison_group"] for r in per_mol}) == 2
    bounds = sorted(g["context"]["system_boundary"] for g in _groups(res) if g["unit"] == "kJ/mol")
    assert bounds == ["device", "process"]
    assert all(g["context"]["energy_input"] == "electrical" for g in _groups(res))
    assert [x["reason"].split()[0] for x in res["excluded"]] == ["missing_context"]


def test_energy_per_mole_and_per_kilogram_of_product_stay_apart(doc):
    res = _rank(doc, "CatalyticTest", "energy_consumption")
    assert sorted(g["unit"] for g in _groups(res)) == ["kJ/mol", "kWh/kg"] and len(res["rows"]) == 4
    assert all(g["context"]["energy_input"] == "electrical" and g["context"]["system_boundary"] == "device"
               for g in _groups(res))
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
    assert {m["term"]: m["match"] for m in idx["kind:enzyme_activity"]} == {
        "SBO:0000559": "narrow", "SBO:0000558": "narrow", "quantitykind:CatalyticActivity": "related"}
    # QUDT's specific energy is any energy per mass, its catalytic activity that of any catalyst
    assert [m["match"] for m in idx["kind:energy_consumption"]] == ["related"]
    assert not any(f"kind:{k}" in idx for k in ("transport_criterion", "effectiveness_factor", "thiele_modulus"))
    subdomains = {a["subdomain"]: a for a in mappings.subdomains(REPO)}
    assert subdomains["biocatalysis"]["scale"] and "Catalyst" in subdomains["biocatalysis"]["scale"]


def test_the_photoelectrode_names_a_role_the_vocabulary_holds():
    spec = spec_at("0.7.1")
    assert "role cocatalyst" in spec["nodes"]["Photoelectrode"]["description"]
    assert "cocatalyst" in spec["edges"]["HAS_COMPONENT"]["properties"]["role"]["values"]


def test_the_change_is_additive():
    d = diff_specs(spec_at("0.7.0"), spec_at("0.7.1"))
    assert tier(d) == 2 and not d["removed"] and not d["changed"] and not d["narrowed"]
    assert {"quantities.kinds.turnover_number", "quantities.kinds.enzyme_activity", "quantities.kinds.transport_criterion",
            "nodes.CatalyticTest.catalysis_mode", "edges.HAS_COMPONENT.role = ligand", "quantities.contexts.transport_mode",
            "quantities.contexts.characteristic_length", "quantities.contexts.thiele_form",
            "quantities.contexts.effectiveness_basis", "quantities.contexts.energy_input",
            "quantities.contexts.system_boundary"} <= set(d["added"])
    assert {"quantities.units: U is read (molar_flow, prefixed)", "quantities.units: kat is read (molar_flow, prefixed)"} \
        <= set(d["loosened"])


def test_cq28_compares_the_turnover_number_and_each_activity_as_its_own_group():
    """CQ-28's comparison variant: four rows in four groups, a turnover number apart from the activities, and the
    activities per time, per mass and per volume apart by their units."""
    q = yaml.safe_load((REPO / "domain/competency/cq-28-homogeneous-and-enzyme-activity.yaml").read_text())
    variant = next(v for v in q["variants"] if v["plan"].get("comparison") == "scientific")
    d = load_doc(DOC)
    res = pgraph_query.run(d, spec_of(d), {**q["plan"], **variant["plan"]})
    groups = {g["group"]: (g["compared_on"]["result.value"]["kind"], g["compared_on"]["result.value"]["unit"])
              for g in res["comparison"]["groups"]}
    assert sorted(groups.values()) == [("enzyme_activity", "U"), ("enzyme_activity", "U/mg"),
                                       ("enzyme_activity", "mU/mL"), ("turnover_number", "1")]
    rows = {(groups[r["comparison_group"]], r["values"]["result"]["value"]) for r in res["rows"]}
    assert rows == {(("turnover_number", "1"), 950), (("enzyme_activity", "U"), 0.6),
                    (("enzyme_activity", "U/mg"), 12.5), (("enzyme_activity", "mU/mL"), 120)}
