"""Build the synthetic computation example of the catalysis domain (all values invented): computed energies recorded as
values of their kind, with the reaction they are the energy change of and the computation that states how they were
obtained; elementary barriers, an apparent activation energy from a fit of rates and degrees of rate control at two
temperatures; a machine-learned model with its checkpoint, the data it was fitted to and two validations; a computed
catalyst state on a structure model, with no specimen of its own.

    python build_examples.py

  computed-energies.json
    O adsorption on close-packed metals, four invented papers
    one descriptor, its references    O adsorption energies relative to H2O and H2 (RPBE, constant charge) on Cu(111),
                                      Pt(111), Ag(111) and Au(111), each computation stating its level of theory, charge
                                      treatment, dispersion, spin, solvation and numerical settings; the input files, the
                                      environment and every structure in a checksummed Dataset
    apart from it                     the O adsorption free energy on Pt(111) at 298.15 K (another kind); the O adsorption
                                      energy on Pt(111) relative to O2 (another reaction); an O adsorption energy on
                                      Pd(111) whose computation does not state its level of theory, and one on Ni(111)
                                      whose source does not say what it is relative to (both left out of a comparison, each
                                      with its reason); a prediction by a machine-learned model (another method)
    electrochemical O adsorption      at 0.9 V on Pt(111): a computational-hydrogen-electrode free energy (constant
                                      charge), a constant-potential one with implicit solvent, and the first converted to
                                      constant potential by an analysis (an evidenced conversion, compared with the second)
    total energies                    of the Pt(111) slab and of an H2O molecule (electronic_energy, each of its structure)
    barriers and rates                O2 dissociation and CO + O on Pt(111), each step's computed barrier with its
                                      transition-state structure; an apparent activation energy of CO2 formation from an
                                      Arrhenius fit of three measured rates (another kind, never a step's barrier); the
                                      degree of rate control of both steps at 450 K and 500 K, from two microkinetic runs
    a machine-learned model           its checkpoint (version, stored_in), the data it was fitted to, a validation on
                                      held-out data and one on its own training data (the validator reports the second)
    a computed state                  Pt(111) with 0.25 ML O, a state of the slab model with no specimen; the model
                                      REPRESENTS the Pt/Al2O3 batch with what that assumes
    balances                          every reaction and step lists its participants with coefficients, compositions and
                                      charges, and balances in atoms and in charge
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def _repo_root(*starts: Path) -> Path:
    """The SCALE checkout (scale-release.yaml and releases/), searched upward from each start in turn."""
    for p in (q for s in starts for q in (s, *s.parents)):
        if (p / "scale-release.yaml").exists() and (p / "releases").is_dir():
            return p
    raise SystemExit("run inside a SCALE repository checkout: no scale-release.yaml and releases/ above "
                     + ", ".join(map(str, starts)))


HERE = Path(__file__).resolve().parent
REPO = _repo_root(HERE, Path.cwd())
sys.path.insert(0, str(REPO / "tools"))
from scale import layout  # noqa: E402
from scale.pgraph import derive_reported_in  # noqa: E402
from scale.util import write_canonical  # noqa: E402

SYN = "synthetic"
_HEAD = REPO / layout.DOMAIN / layout.DOMAIN_GRAPH_MANIFEST
HEAD_VERSION = __import__("yaml").safe_load(_HEAD.read_text())["version"]


def V(value, unit, **kw) -> dict:
    return {"status": "present", "value": value, "unit": unit, **kw}


def T(text, **kw) -> dict:
    return {"status": "present", "text_value": text, **kw}


def sha(name: str) -> str:
    """An invented digest (the files are invented too), stable from build to build."""
    return hashlib.sha256(f"invented file: {name}".encode()).hexdigest()


def computed_energies() -> dict:
    p = "ex:ce"
    doc = {"directed": True, "multigraph": True,
           "graph": {"schema": "scale-catal", "schema_version": HEAD_VERSION, "graph_id": f"{p}/graph",
                     "title": "Computed energies, barriers, rate control and a machine-learned model, each with what makes "
                              "it comparable (synthetic)",
                     "data_status": "synthetic_example", "follows_domains": ["catalysis"],
                     "stewardship": {"access": "public"}},
           "nodes": [], "links": []}
    n = [0]

    def node(rid, label, name, **props):
        nid = f"{p}/{rid}"
        doc["nodes"].append({"id": nid, "label": label, "props": {"name": name, "origin": SYN, **props}})
        return nid

    def link(typ, s, t, **props):
        n[0] += 1
        lid = f"{p}/link/{n[0]}"
        doc["links"].append({"id": lid, "source": s, "target": t, "type": typ, "props": {"origin": SYN, **props}})
        return lid

    dft_paper = node("source/dft-paper", "Source", "Invented paper (descriptor)", kind="article", year=2026,
                     title="Oxygen adsorption on close-packed metal surfaces as an activity descriptor (invented)")
    cip_paper = node("source/cip-paper", "Source", "Invented paper (constant potential)", kind="article", year=2026,
                     title="Oxygen adsorption on Pt(111) at constant electrode potential (invented)")
    ml_paper = node("source/ml-paper", "Source", "Invented paper (machine learning)", kind="article", year=2026,
                    title="A machine-learned potential for oxygen on metal surfaces (invented)")
    kin_paper = node("source/kinetics-paper", "Source", "Invented paper (kinetics)", kind="article", year=2026,
                     title="CO oxidation kinetics over Pt/Al2O3, measured and modelled (invented)")

    def ev(locator, kind="table", source=dft_paper, **kw):
        return {"source": source, "locator": locator, "kind": kind, **kw}

    # ---- species, reactions and steps: the participants are the reference states, and they balance
    def species(key, formula, composition, charge, name=None, **props):
        return node(f"species/{key}", "ChemicalSpecies", name or formula, formula=formula, elemental_composition=composition,
                    charge=charge, **props)

    o2, h2o, h2 = species("o2", "O2", {"O": 2}, 0), species("h2o", "H2O", {"H": 2, "O": 1}, 0), species("h2", "H2", {"H": 2}, 0)
    o_ads = species("o", "O", {"O": 1}, 0, name="O (adsorbed)")
    proton = species("proton", "H+", {"H": 1}, 1, species_kind="ion")
    electron = species("electron", "e-", {}, -1, species_kind="other")
    co, co2 = species("co", "CO", {"C": 1, "O": 1}, 0), species("co2", "CO2", {"C": 1, "O": 2}, 0)

    def participants(rec, *items):
        for sp, role, coef, phase in items:
            link("HAS_PARTICIPANT", rec, sp, role=role, coefficient=coef, phase=phase)

    def reaction(key, equation, *items, source=dft_paper):
        r = node(f"reaction/{key}", "Reaction", equation, equation=equation, balance_status="balanced", direction="forward",
                 evidence=[ev("Methods, reference energies", "text", source=source)])
        participants(r, *items)
        return r

    ads_h2o = reaction("o-adsorption-from-h2o", "H2O(g) + * -> O* + H2(g)", (h2o, "reactant", 1, "gas"),
                       (o_ads, "product", 1, "adsorbed"), (h2, "product", 1, "gas"))
    ads_o2 = reaction("o-adsorption-from-o2", "1/2 O2(g) + * -> O*", (o2, "reactant", 0.5, "gas"),
                      (o_ads, "product", 1, "adsorbed"))
    ads_echem = reaction("o-electroadsorption", "H2O(l) + * -> O* + 2 H+ + 2 e-", (h2o, "reactant", 1, "liquid"),
                         (o_ads, "product", 1, "adsorbed"), (proton, "product", 2, "liquid"),
                         (electron, "product", 2, "not_reported"), source=cip_paper)
    co_ox = reaction("co-oxidation", "CO + 1/2 O2 -> CO2", (co, "reactant", 1, "gas"), (o2, "reactant", 0.5, "gas"),
                     (co2, "product", 1, "gas"), source=kin_paper)

    # ---- materials, structure models and the files they are kept in
    def material(key, formula):
        return node(f"material/{key}", "Material", f"fcc {formula}", formula=formula, structure_type="fcc",
                    material_family="metal")

    def dataset(key, name, kind, **props):
        return node(f"dataset/{key}", "Dataset", name, data_kind=kind, availability="available", version="1",
                    sha256=sha(key), uri=f"https://example.org/invented/{key}", **props)

    def slab(key, metal, lattice, src=dft_paper, layers=4):
        mat = material(key, metal)
        m = node(f"model/{key}-111", "StructureModel", f"{metal}(111) slab, p(2×2), {layers} layers",
                 representation="periodic_slab", composition=metal, facet="111",
                 stored_in=dataset(f"{key}-111-structure", f"{metal}(111) slab coordinates", "structure",
                                   media_type="chemical/x-cif"),
                 parameters={"supercell": T("p(2×2)"), "layers": V(layers, "1"), "fixed_layers": V(2, "1"),
                             "vacuum": V(15, "Å"), "lattice_constant": V(lattice, "Å", definition="optimized for the bulk "
                                                                                                    "metal at this level of theory"),
                             "boundary_conditions": T("periodic in three dimensions, vacuum along the surface normal"),
                             "relaxation": T("adsorbate and the top two layers relaxed")},
                 evidence=[ev("Computational methods", "text", source=src)])
        link("APPLIES_TO", m, mat)
        return m, mat

    (m_cu, _), (m_pt, pt), (m_ag, _), (m_au, _) = (slab("cu", "Cu", 3.71), slab("pt", "Pt", 3.99), slab("ag", "Ag", 4.22),
                                                   slab("au", "Au", 4.22))
    m_pd, _ = slab("pd", "Pd", 3.99)
    m_ni, _ = slab("ni", "Ni", 3.55)
    m_pt3ni = node("model/pt3ni-111", "StructureModel", "Pt3Ni(111) slab, p(2×2), 4 layers", representation="periodic_slab",
                   composition="Pt3Ni", facet="111",
                   stored_in=dataset("pt3ni-111-structure", "Pt3Ni(111) slab coordinates", "structure"),
                   evidence=[ev("Table 2", source=ml_paper)])
    m_h2o = node("model/h2o-molecule", "StructureModel", "H2O molecule in a 15 Å box", representation="molecule",
                 composition="H2O", stored_in=dataset("h2o-structure", "H2O molecule coordinates", "structure"),
                 evidence=[ev("Computational methods", "text")])
    m_ts_o2 = node("model/ts-o2-dissociation", "StructureModel", "transition state of O2 dissociation on Pt(111)",
                   representation="periodic_slab", composition="Pt + O2", facet="111",
                   stored_in=dataset("ts-o2-dissociation", "O2 dissociation transition state coordinates", "structure"),
                   evidence=[ev("Figure 3", "figure", source=kin_paper)])
    m_ts_co_o = node("model/ts-co-o", "StructureModel", "transition state of CO + O on Pt(111)", representation="periodic_slab",
                     composition="Pt + CO + O", facet="111",
                     stored_in=dataset("ts-co-o", "CO + O transition state coordinates", "structure"),
                     evidence=[ev("Figure 3", "figure", source=kin_paper)])

    vasp = node("software/plane-wave-code", "Software", "plane-wave DFT code (invented release)", software_kind="application",
                version="6.4.2")
    config = dataset("rpbe-inputs", "input files of the RPBE calculations", "configuration", media_type="application/zip")
    environment = dataset("rpbe-environment", "container image of the calculations", "environment")

    # ---- the computations: what they state is what a comparison reads (level_of_theory, charge_treatment) and shows
    def variable(key, name, kind, unit):
        return node(f"variable/{key}", "Variable", name, scale="quantitative", quantity_kind=kind, unit=unit)

    v_eads = variable("o-adsorption-energy", "O adsorption energy", "reaction_energy", "eV")
    v_gads = variable("o-adsorption-free-energy", "O adsorption free energy", "reaction_free_energy", "eV")
    v_etot = variable("total-energy", "total electronic energy", "electronic_energy", "eV")

    method = {"computation_kind": "electronic_structure", "level_of_theory": T("RPBE"), "dispersion": T("none"),
              "spin_treatment": "non_spin_polarized", "solvation": "none", "charge_treatment": "constant_charge",
              "settings": {"cutoff_energy": V(450, "eV"), "kpoints": T("4×4×1"),
                           "smearing": V(0.1, "eV", definition="Methfessel-Paxton, first order"),
                           "force_convergence": V(0.02, "eV/Å"), "pseudopotentials": T("PAW")},
              "configuration": config, "execution_environment": environment}
    study = node("computation/rpbe-study", "Computation", "RPBE study of O adsorption on close-packed metals",
                 method="DFT (RPBE), PAW, 450 eV", **method, evidence=[ev("Computational methods", "text")])
    link("USES_SOFTWARE", study, vasp, version="6.4.2")

    def computation(key, name, model, results, evidence, src=dft_paper, **props):
        c = node(f"computation/{key}", "Computation", name, **{**method, **props}, result_values=results, evidence=evidence)
        link("PART_OF", c, study) if src == dft_paper else None
        link("USES_SOFTWARE", c, vasp, version="6.4.2")
        if model:
            link("USES_MODEL", c, model)
        return c

    def e_ads(rid, value, ev_id, variable=v_eads, target=ads_h2o, **kw):
        return V(value, "eV", id=rid, variable=variable, target=target, evidence_ids=[ev_id], **kw)

    c_cu = computation("cu-111", "O on Cu(111), RPBE", m_cu, [e_ads("o_adsorption_h2o", 1.02, "t1_cu")], [ev("Table 1", id="t1_cu")])
    c_pt = computation("pt-111", "O on Pt(111), RPBE", m_pt,
                       [e_ads("o_adsorption_h2o", 1.55, "t1_pt"),
                        e_ads("o_adsorption_o2", -0.91, "t1_pt_o2", target=ads_o2),
                        V(-312.4561, "eV", id="slab_total_energy", variable=v_etot, target=m_pt, evidence_ids=["s2_slab"])],
                       [ev("Table 1", id="t1_pt"), ev("Table 1, last column", id="t1_pt_o2"),
                        ev("Supporting information, Table S2", id="s2_slab")])
    c_ag = computation("ag-111", "O on Ag(111), RPBE", m_ag, [e_ads("o_adsorption_h2o", 2.31, "t1_ag")], [ev("Table 1", id="t1_ag")])
    c_au = computation("au-111", "O on Au(111), RPBE", m_au, [e_ads("o_adsorption_h2o", 2.78, "t1_au")], [ev("Table 1", id="t1_au")])
    computation("h2o-molecule", "H2O molecule, RPBE", m_h2o,
                [V(-14.2217, "eV", id="h2o_total_energy", variable=v_etot, target=m_h2o, evidence_ids=["s2_h2o"])],
                [ev("Supporting information, Table S2", id="s2_h2o")])
    computation("pt-111-free-energy", "O on Pt(111), RPBE free energy at 298.15 K", m_pt,
                [V(1.62, "eV", id="o_adsorption_free_h2o", variable=v_gads, target=ads_h2o, evidence_ids=["t4_pt"])],
                [ev("Table 4", id="t4_pt")], temperature=V(298.15, "K"), pressure=V(1, "bar"),
                settings={**method["settings"], "thermochemistry": T("harmonic adsorbate, ideal-gas H2O and H2 at 1 bar")})
    # a computation that does not state its level of theory, and a value whose source does not say what it is relative to
    computation("pd-111", "O on Pd(111)", m_pd, [e_ads("o_adsorption_h2o", 1.35, "t1_pd")], [ev("Table 1", id="t1_pd")],
                level_of_theory={"status": "not_reported", "missing_reason": "not_stated_in_source"})
    del_target = e_ads("o_adsorption", 0.78, "t1_ni", target=None, unresolved_target="O adsorption energy; the reference "
                                                                                        "species are not stated")
    del del_target["target"]
    computation("ni-111", "O on Ni(111), RPBE", m_ni, [del_target], [ev("Table 1, footnote", id="t1_ni")],
                spin_treatment="spin_polarized",
                settings={**method["settings"], "initial_magnetic_moments": T("0.6 μB per Ni atom")})

    # ---- electrochemical O adsorption at 0.9 V: constant charge (computational hydrogen electrode), constant potential,
    # and the first converted to constant potential (an evidenced conversion)
    c_che = computation("pt-111-che", "O electroadsorption on Pt(111), computational hydrogen electrode", m_pt,
                        [V(-0.18, "eV", id="o_electroadsorption", variable=v_gads, target=ads_echem, evidence_ids=["t5_che"]),
                         V(-0.09, "eV", id="o_electroadsorption_constant_potential", variable=v_gads, target=ads_echem,
                           origin="derived", produced_by=f"{p}/analysis/charge-extrapolation",
                           definition="converted to constant potential by charge extrapolation, at 0.9 V vs SHE (pH 0)",
                           evidence_ids=["t5_converted"])],
                        [ev("Table 5", id="t5_che", source=cip_paper), ev("Table 5, converted", id="t5_converted",
                                                                            source=cip_paper)],
                        src=cip_paper, temperature=V(298.15, "K"), electrode_potential=V(0.9, "V vs RHE"),
                        reference_scale="rhe",
                        settings={**method["settings"], "thermochemistry": T("harmonic adsorbate"),
                                  "potential_method": T("computational hydrogen electrode, −eU per electron transferred")})
    conversion = node("analysis/charge-extrapolation", "Analysis", "charge extrapolation to constant potential",
                      analysis_kind="thermodynamic", method="charge extrapolation from constant-charge energies",
                      temperature=V(298.15, "K"), electrode_potential=V(0.9, "V vs SHE"), reference_scale="she",
                      evidence=[ev("Section 2.3", "text", source=cip_paper)])
    link("HAS_INPUT", conversion, c_che, role="data")
    computation("pt-111-constant-potential", "O electroadsorption on Pt(111) at constant potential", m_pt,
                [V(-0.05, "eV", id="o_electroadsorption", variable=v_gads, target=ads_echem,
                   definition="grand free energy at 0.9 V vs SHE (pH 0)", evidence_ids=["t5_cip"])],
                [ev("Table 5", id="t5_cip", source=cip_paper)], src=cip_paper, temperature=V(298.15, "K"),
                charge_treatment="constant_potential", solvation="implicit_and_explicit",
                electrode_potential=V(0.9, "V vs SHE"), reference_scale="she",
                settings={**method["settings"], "solvation_model": T("implicit continuum with one explicit water layer"),
                          "potential_method": T("constant inner potential, referred to SHE through the point of zero charge of the electrode")})

    # ---- elementary steps: computed barriers with their transition states
    mech = node("mechanism/co-oxidation-pt111", "Mechanism", "CO oxidation on Pt(111)", mechanism_format="other",
                mechanism_status="proposed", evidence=[ev("Scheme 1", "figure", source=kin_paper)])
    link("DESCRIBES_REACTION", mech, co_ox)
    link("APPLIES_TO", mech, pt)
    k_dft = computation("pt-111-barriers", "transition states on Pt(111), RPBE, CI-NEB", m_pt, [], [ev("Table 2", source=kin_paper)],
                        src=kin_paper, settings={**method["settings"], "transition_state_method": T("CI-NEB, 7 images")})

    def step(key, name, order, ts, items, ea, de, ev_ids):
        s = node(f"step/{key}", "ElementaryStep", name, equation=name, step_kind="surface_reaction", reversible=False,
                 activation_energy=V(ea, "eV", origin="computed", produced_by=k_dft, evidence_ids=[ev_ids[0]],
                                     definition="transition state above the initial state, electronic energies"),
                 reaction_energy=V(de, "eV", origin="computed", produced_by=k_dft, evidence_ids=[ev_ids[1]]),
                 evidence=[ev("Table 2", id=ev_ids[0], source=kin_paper), ev("Table 2", id=ev_ids[1], source=kin_paper)])
        participants(s, *items)
        link("HAS_ELEMENTARY_STEP", mech, s, order=order)
        link("TRANSITION_STATE", s, ts)
        return s

    s_o2 = step("o2-dissociation", "O2* -> 2 O*", 1, m_ts_o2, [(o2, "reactant", 1, "adsorbed"), (o_ads, "product", 2, "adsorbed")],
                0.62, -1.48, ["t2_ea_o2", "t2_de_o2"])
    s_co_o = step("co-plus-o", "CO* + O* -> CO2(g)", 2, m_ts_co_o, [(co, "reactant", 1, "adsorbed"), (o_ads, "reactant", 1, "adsorbed"),
                                                                     (co2, "product", 1, "gas")],
                  0.98, -0.35, ["t2_ea_coo", "t2_de_coo"])

    # ---- measured rates and their Arrhenius fit: an apparent activation energy, never a step's barrier
    cat = node("catalyst/pt-al2o3", "Catalyst", "Pt/Al2O3, 1 wt% Pt", nominal_formula="Pt/Al2O3", catalyst_family="metal",
               evidence=[ev("Experimental", "text", source=kin_paper)])
    batch = node("sample/pt-al2o3-k", "CatalystSample", "Pt/Al2O3 batch K", sample_kind="powder", batch_identifier="K",
                 evidence=[ev("Experimental", "text", source=kin_paper)])
    link("HAS_FORMULATION", batch, cat)
    feed = node("feed/co-o2", "Feed", "1 % CO, 1 % O2 in He", evidence=[ev("Experimental", "text", source=kin_paper)])
    link("HAS_COMPONENT", feed, co, role="reactant")
    link("HAS_COMPONENT", feed, o2, role="reactant")
    reactor = node("instrument/plug-flow", "Reactor", "quartz plug-flow reactor", reactor_kind="fixed_bed")
    v_rate = variable("co2-rate", "CO2 formation rate per catalyst mass", "production_rate", "µmol/(g s)")
    v_eapp = variable("co2-apparent-activation-energy", "apparent activation energy of CO2 formation",
                      "apparent_activation_energy", "kJ/mol")
    tests = []
    for kelvin, rate in ((450, 0.21), (480, 1.05), (510, 4.4)):
        t = node(f"test/co-oxidation-{kelvin}k", "CatalyticTest", f"CO oxidation at {kelvin} K", test_kind="kinetics",
                 driving_forces=["thermo"], interpretations=["intrinsic_kinetics"], experiment_kind="physical",
                 temperature=V(kelvin, "K"), pressure=V(1, "bar", basis="absolute"), temperature_measured_at="catalyst_bed",
                 result_values=[V(rate, "µmol/(g s)", id="co2_rate", variable=v_rate, target=co2, evidence_ids=["f2_rate"])],
                 evidence=[ev("Figure 2", "figure", source=kin_paper, id="f2_rate")])
        link("USES_CATALYST", t, batch, state="reduced")
        link("FED_WITH", t, feed)
        link("IN_REACTOR", t, reactor)
        link("OF_REACTION", t, co_ox)
        tests.append(t)
    arrhenius = node("model/arrhenius", "Model", "Arrhenius rate law", model_kind="rate law",
                     equations=["r = A exp(-Ea/(R T))"], evidence=[ev("Figure 2", "figure", source=kin_paper)])
    fit = node("analysis/arrhenius-fit", "Analysis", "Arrhenius fit of the CO2 formation rate, 450–510 K",
               analysis_kind="kinetic_fit", method="least-squares fit of ln r against 1/T",
               temperature={"status": "present", "lower": 450, "upper": 510, "unit": "K"},
               result_values=[V(105, "kJ/mol", id="apparent_activation_energy", variable=v_eapp, target=co2,
                                uncertainty=4, uncertainty_kind="standard_error", evidence_ids=["f2_fit"])],
               evidence=[ev("Figure 2, inset", "figure", source=kin_paper, id="f2_fit")])
    link("USES_MODEL", fit, arrhenius)
    link("OF_REACTION", fit, co_ox)
    transport = node("analysis/weisz-prater", "Analysis", "Weisz-Prater check at 510 K", analysis_kind="transport_check",
                     evaluation_basis="numerical", method="Weisz-Prater criterion from the rate at 510 K",
                     verdict="no internal diffusion limitation", temperature=V(510, "K"),
                     results={"weisz_prater_number": V(0.02, "1", evidence_ids=["s3_wp"])},
                     evidence=[ev("Supporting information, Section S3", "text", source=kin_paper, id="s3_wp")])
    for t in tests:
        link("HAS_INPUT", fit, t, role="data")
        link("HAS_INPUT", transport, t, role="data")

    # ---- the computed state: a state of the slab model, with no specimen; the model stands for the batch
    site = node("site/pt111-fcc", "ActiveSite", "fcc hollow site of Pt(111)", site_kind="metal_site")
    link("LOCATED_ON", site, pt)
    state = node("state/o-covered-pt111", "CatalystState", "computed: Pt(111) with 0.25 ML O", state_kind="working",
                 morphology="Pt(111) terrace, O in fcc hollow sites", evidence=[ev("Figure 3", "figure", source=kin_paper)])
    link("STATE_OF", state, m_pt)
    link("DETERMINED_BY", state, k_dft)
    link("HAS_COMPONENT", state, o_ads, role="adsorbate", bound_to=site,
         coverage=V(0.25, "ML", basis="O atoms per surface Pt atom"))
    link("REPRESENTS", m_pt, batch, aspect="the (111) terraces of its Pt particles",
         assumptions=["a clean Pt(111) terrace stands for the particles", "the alumina support is left out",
                      "0.25 ML O, the coverage of the microkinetic model at 450 K"],
         evidence=[ev("Section 4", "text", source=kin_paper)])

    # ---- the microkinetic model at two temperatures: degrees of rate control, at the conditions of each run
    mk = node("computation/microkinetic", "Computation", "microkinetic model of CO oxidation on Pt(111)",
              computation_kind="microkinetic", level_of_theory=T("RPBE"), method="mean-field microkinetic model",
              evidence=[ev("Section 4", "text", source=kin_paper)])
    link("HAS_INPUT", mk, mech, role="parameter")
    link("IN_STATE", mk, state)
    for kelvin, (x_o2, x_coo) in ((450, (0.82, 0.15)), (500, (0.31, 0.66))):
        run = node(f"computation/microkinetic-{kelvin}k", "Computation", f"microkinetic model at {kelvin} K",
                   computation_kind="microkinetic", level_of_theory=T("RPBE"), temperature=V(kelvin, "K"),
                   pressure=V(1, "bar"), conditions={"co_partial_pressure": V(0.01, "bar"), "o2_partial_pressure": V(0.01, "bar")},
                   evidence=[ev("Figure 5", "figure", source=kin_paper, id="f5")])
        link("PART_OF", run, mk)
        link("IN_STATE", run, state)
        for s, x in ((s_o2, x_o2), (s_co_o, x_coo)):
            link("RATE_CONTROL", run, s, degree_of_rate_control=V(x, "1", target=co2, evidence_ids=["f5_x"]),
                 rate_determining=x > 0.5, evidence=[ev("Figure 5", "figure", source=kin_paper, id="f5_x")])

    # ---- a machine-learned model: its checkpoint, the data it was fitted to, and two validations
    train = dataset("adsorption-training-set", "spin-polarized O adsorption energies, training split", "processed",
                    licence="CC-BY-4.0 (invented)")
    test_set = dataset("adsorption-test-set", "spin-polarized O adsorption energies, held-out split", "processed")
    weights = dataset("mlip-ckpt-0420", "model weights at checkpoint 0420", "other", media_type="application/octet-stream")
    mlip = node("model/example-mlip", "Model", "example machine-learned potential", model_kind="machine-learned interatomic potential",
                version="ckpt-0420", stored_in=weights,
                assumptions=["energies of the spin-polarized RPBE calculations it was fitted to"],
                evidence=[ev("Section 2", "text", source=ml_paper)])
    v_mae = variable("energy-mae", "mean absolute error of adsorption energies", "mean_absolute_error", "eV")
    fit_run = node("experiment/mlip-training", "Experiment", "fitting the potential", experiment_kind="computational",
                   goal="calibrate", evidence=[ev("Section 2", "text", source=ml_paper)])
    link("EVALUATES", fit_run, mlip, evaluation_kind="calibration")
    link("HAS_INPUT", fit_run, train, role="training_data")
    for key, data, role, mae, loc in (("held-out", test_set, "test_data", 0.07, "Table 1"),
                                      ("training-set", train, "validation_data", 0.03, "Table S1")):
        x = node(f"experiment/mlip-validation-{key}", "Experiment", f"validation of the potential on the {key} data",
                 experiment_kind="computational", goal="validate",
                 result_values=[V(mae, "eV", id="mae", variable=v_mae, evidence_ids=[f"mae_{key}"])],
                 evidence=[ev(loc, source=ml_paper, id=f"mae_{key}")])
        link("EVALUATES", x, mlip, evaluation_kind="validation", criterion="mean absolute error below 0.1 eV",
             outcome="passes", result_refs=[{"record": x, "path": "/result_values/mae"}],
             evidence=[ev(loc, source=ml_paper)])
        link("HAS_INPUT", x, data, role=role)
    ml = node("computation/mlip-pt3ni", "Computation", "O on Pt3Ni(111), predicted by the machine-learned potential",
              computation_kind="machine_learned", level_of_theory=T("example machine-learned potential, ckpt-0420"),
              charge_treatment="constant_charge",
              result_values=[V(1.71, "eV", id="o_adsorption_h2o", variable=v_eads, target=ads_h2o, origin="predicted",
                               evidence_ids=["t2_ml"])],
              evidence=[ev("Table 2", source=ml_paper, id="t2_ml")])
    link("USES_MODEL", ml, mlip)
    link("USES_MODEL", ml, m_pt3ni)

    for e in derive_reported_in(doc):
        e["props"]["origin"] = SYN
        doc["links"].append(e)
    return doc


if __name__ == "__main__":
    write_canonical(HERE / "computed-energies.json", computed_energies())
