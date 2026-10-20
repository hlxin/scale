"""Build the synthetic preparation-and-characterization examples of the catalysis domain (all values invented): how a
catalyst was made, activated, stored and moved, and how it was characterized, recorded with the structures SCALE has
(the recording recipes, skills/curate-source/references/recipes.md).

    python build_examples.py

  impregnation.json
    Pt on gamma-alumina by incipient-wetness impregnation, from one invented paper
    two batches, one nominal formula  5 wt% Pt/gamma-Al2O3, from two lots of H2PtCl6·6H2O; batch 1 reduced at 573 K,
                                      batch 2 at 773 K and impregnated in two portions (a deviation from the protocol)
    nominal and measured loading      5 wt% nominal (from the precursor weighed) and 3.8 wt% by ICP-OES for batch 1
    activation, storage and transfer  batch 1: calcined, reduced, passivated, stored 14 days (atmosphere not stated),
                                      moved in air to the microscope, reduced again in the XAS cell, measured there in
                                      H2 and then tested in the same cell
    characterization                  ICP-OES; H2 chemisorption with the dispersion it gives (one H per surface Pt);
                                      HAADF-STEM size statistics (mean, standard deviation, particles counted); XRD
                                      (batch 1 below the detection limit of about 3 nm, a crystallite size for batch 2,
                                      broadening from a LaB6 standard); Pt L3 EXAFS with its fit, references and
                                      conditions; N2
                                      physisorption with the BET fit
    purchased samples                 two lots of a commercial 5 wt% Pt/Al2O3, one lot number not stated; each with its
                                      own loading and dispersion, one loading in "%" with no basis

  coprecipitation.json
    Cu/ZnO/Al2O3 by coprecipitation in two orders of addition, from one invented paper
    two batches, one nominal formula  Cu:Zn:Al = 60:30:10 (atomic); carbonate added to the nitrates (batch N) or the
                                      nitrates added to the carbonate (batch R); every other step the same
    solutions and amounts             the nitrate and carbonate solutions as samples with their concentrations
    stated and unstated               stirring rate not stated for either batch; addition rate not stated for batch R;
                                      batch R's storage atmosphere not stated; the XPS spectra not deposited
    composition                       nominal, bulk (XRF) and surface (XPS) metal fractions as separate observations

  high-entropy-alloy.json
    PtPdRhRuIr nanoparticles on carbon by a polyol synthesis, from one invented paper
    composition                       nominal equimolar; bulk by ICP-OES; surface as prepared by XPS; surface under CO
                                      oxidation conditions by near-ambient-pressure XPS, with the state it was observed in
    three sizes                       hydrodynamic size of the colloid (DLS), particle size (HAADF-STEM) and crystallite
                                      size (XRD), each its own variable
"""

from __future__ import annotations

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
NOT_STATED = {"status": "not_reported", "missing_reason": "not_stated_in_source"}


def V(value, unit, **kw) -> dict:
    return {"status": "present", "value": value, "unit": unit, **kw}


def T(text, **kw) -> dict:
    return {"status": "present", "text_value": text, **kw}


class Doc:
    """One synthetic document: its nodes, its links and the helpers that make them."""

    def __init__(self, prefix: str, title: str):
        self.p = prefix
        self.doc = {"directed": True, "multigraph": True,
                    "graph": {"schema": "scale-catal", "schema_version": HEAD_VERSION, "graph_id": f"{prefix}/graph",
                              "title": title, "data_status": "synthetic_example", "follows_domains": ["catalysis"],
                              "stewardship": {"access": "public"}},
                    "nodes": [], "links": []}
        self.n = 0
        self.paper = None

    def node(self, rid, label, name, **props):
        nid = f"{self.p}/{rid}"
        self.doc["nodes"].append({"id": nid, "label": label, "props": {"name": name, "origin": SYN, **props}})
        return nid

    def link(self, typ, s, t, **props):
        self.n += 1
        lid = f"{self.p}/link/{self.n}"
        self.doc["links"].append({"id": lid, "source": s, "target": t, "type": typ, "props": {"origin": SYN, **props}})
        return lid

    def ev(self, locator, kind="text", source=None, **kw):
        return {"source": source or self.paper, "locator": locator, "kind": kind, **kw}

    def species(self, key, formula, composition, name=None, **props):
        return self.node(f"species/{key}", "ChemicalSpecies", name or formula, formula=formula,
                         elemental_composition=composition, **props)

    def element(self, symbol, name):
        return self.node(f"species/{symbol.lower()}", "ChemicalSpecies", name, formula=symbol, species_kind="element",
                         elemental_composition={symbol: 1})

    def variable(self, key, name, kind, unit, definition, scale="quantitative"):
        return self.node(f"variable/{key}", "Variable", name, scale=scale, unit=unit, definition=definition,
                         **({"quantity_kind": kind} if kind else {}))

    def lot(self, key, name, chemical, batch_identifier=None, **props):
        """A purchased lot of a chemical or a material: a Sample with the lot number as stated (none when the source
        gives none) and the chemical it is a lot of."""
        lid = self.node(f"lot/{key}", "Sample", name, sample_kind="batch", preparation_status="purchased",
                        **({"batch_identifier": batch_identifier} if batch_identifier else {}), **props)
        self.link("HAS_COMPONENT", lid, chemical, role="precursor", evidence=props.get("evidence"))
        return lid

    def step(self, prep, order, key, name, action, inputs=(), outputs=(), **props):
        """A ProcedureStep PART_OF its preparation, in order, with what it takes in and gives out."""
        sid = self.node(f"step/{key}", "ProcedureStep", name, action=action, **props)
        self.link("PART_OF", sid, prep, order=order)
        for target, role, amount in inputs:
            self.link("HAS_INPUT", sid, target, role=role, **({"amount": amount} if amount else {}))
        for target in outputs:
            self.link("HAS_OUTPUT", sid, target)
        return sid

    def finish(self):
        for e in derive_reported_in(self.doc):
            e["props"]["origin"] = SYN
            self.doc["links"].append(e)
        return self.doc


# ================================================================================== impregnation
def impregnation() -> dict:
    d = Doc("ex:pi", "Pt on gamma-alumina by incipient-wetness impregnation: two batches, their activation, storage and "
                     "transfer, and their characterization (synthetic)")
    d.paper = d.node("source/paper", "Source", "Invented paper", kind="article", year=2026,
                     title="Two batches of Pt/gamma-Al2O3 by incipient wetness, and what their histories did to them "
                           "(invented)")
    ev = d.ev

    # ---- chemicals, materials and the formulations
    precursor = d.species("h2ptcl6-6h2o", "H2PtCl6·6H2O", {"H": 14, "Cl": 6, "O": 6, "Pt": 1},
                          name="hexachloroplatinic acid hexahydrate", evidence=[ev("Methods")])
    water = d.species("water", "H2O", {"H": 2, "O": 1}, name="water")
    pt = d.element("Pt", "platinum")
    h2 = d.species("h2", "H2", {"H": 2}, name="hydrogen")
    n2 = d.species("n2", "N2", {"N": 2}, name="nitrogen")
    ethylene = d.species("ethylene", "C2H4", {"C": 2, "H": 4}, name="ethylene")
    ethane = d.species("ethane", "C2H6", {"C": 2, "H": 6}, name="ethane")
    alumina = d.node("material/gamma-alumina", "Material", "gamma-Al2O3", formula="Al2O3", polymorph="gamma",
                     material_family="oxide")
    pt_fcc = d.node("material/pt-fcc", "Material", "fcc Pt", formula="Pt", structure_type="fcc", material_family="metal")
    cat = d.node("catalyst/pt-alumina", "Catalyst", "5 wt% Pt/gamma-Al2O3 (nominal)", nominal_formula="Pt/gamma-Al2O3",
                 catalyst_family="metal", evidence=[ev("Methods")])
    d.link("HAS_COMPONENT", cat, pt_fcc, role="active_phase", loading_basis="mass",
           loading=V(5, "wt%", origin="assumed", definition="nominal: the Pt in the precursor weighed, per mass of "
                     "catalyst", evidence_ids=["m_nominal"]),
           evidence=[ev("Methods", id="m_nominal")])
    d.link("HAS_COMPONENT", cat, alumina, role="support", evidence=[ev("Methods")])

    # ---- the purchased lots the batches are made from
    lot_a = d.lot("h2ptcl6-a", "H2PtCl6·6H2O, lot A-1172", precursor, "A-1172", evidence=[ev("Methods")])
    lot_b = d.lot("h2ptcl6-b", "H2PtCl6·6H2O, lot B-2090", precursor, "B-2090", evidence=[ev("Methods")])
    support_lot = d.node("lot/alumina-s31", "Sample", "gamma-Al2O3 support, lot S-31", sample_kind="powder",
                         preparation_status="purchased", batch_identifier="S-31", evidence=[ev("Methods")])
    d.link("HAS_COMPONENT", support_lot, alumina, role="support", evidence=[ev("Methods")])
    protocol = d.node("protocol/iwi", "Protocol", "Incipient-wetness impregnation of Pt on gamma-Al2O3",
                      protocol_kind="synthesis",
                      steps=["measure the incipient volume of the support with water", "dissolve the precursor in that "
                             "volume", "add the solution dropwise with intermittent mixing", "dry at 393 K",
                             "calcine at 723 K in static air"], evidence=[ev("Methods")])

    def batch(key, name, ident):
        s = d.node(f"sample/{key}", "CatalystSample", name, sample_kind="batch", batch_identifier=ident,
                   preparation_status="prepared", evidence=[ev("Methods")])
        d.link("HAS_FORMULATION", s, cat)
        return s

    b1 = batch("batch-1", "5 wt% Pt/gamma-Al2O3, batch 1", "1")
    b2 = batch("batch-2", "5 wt% Pt/gamma-Al2O3, batch 2", "2")

    def preparation(key, sample, lot, grade, portions, deviation=None, ramp=None):
        prep = d.node(f"preparation/{key}", "Preparation", f"Incipient-wetness impregnation, {key.replace('-', ' ')}",
                      method="incipient-wetness impregnation", evidence=[ev("Methods")])
        d.link("HAS_OUTPUT", prep, sample)
        d.link("FOLLOWS_PROTOCOL", prep, protocol, **({"deviations": deviation} if deviation else {}),
               evidence=[ev("Methods")])
        d.link("PREPARED_FROM", sample, precursor, role="Pt precursor", amount=V(0.266, "g"), supplier="an invented supplier",
               grade=grade, evidence=[ev("Methods")])
        d.link("PREPARED_FROM", sample, alumina, role="support", amount=V(1.90, "g"), supplier="an invented supplier",
               evidence=[ev("Methods")])
        solution = d.node(f"solution/{key}", "Sample", f"aqueous H2PtCl6 solution, {key.replace('-', ' ')}",
                          sample_kind="other", preparation_status="prepared", evidence=[ev("Methods")])
        volume = 1.18 if portions == 1 else 1.50
        d.link("HAS_COMPONENT", solution, precursor, role="precursor",
               concentration=V(round(0.266 / 517.90 / volume * 1000, 3), "mol/L",
                               definition="from the precursor weighed and the volume of water", evidence_ids=["m_sol"]),
               evidence=[ev("Methods", id="m_sol")])
        d.step(prep, 1, f"{key}-incipient-volume", "Measure the incipient volume of the support", "other",
               inputs=[(support_lot, "material", V(1.00, "g")), (water, "reagent", None)],
               method="water added dropwise to the support until it was wet without excess liquid",
               conditions={"incipient_volume": V(0.62, "mL/g", evidence_ids=["m_iv"])},
               evidence=[ev("Methods", id="m_iv")])
        d.step(prep, 2, f"{key}-dissolve", "Dissolve the precursor", "dissolve",
               inputs=[(lot, "reagent", V(0.266, "g")), (water, "reagent", V(volume, "mL"))], outputs=[solution],
               evidence=[ev("Methods")])
        order = 3
        for i in range(portions):
            d.step(prep, order, f"{key}-impregnate-{i + 1}", f"Impregnate the support{f', portion {i + 1}' if portions > 1 else ''}",
                   "impregnate", inputs=[(solution, "reagent", None), (support_lot, "material", V(1.90, "g"))],
                   method="solution added dropwise with intermittent mixing by hand",
                   conditions={"temperature": V(298, "K", qualifier="approximate", as_reported="room temperature")},
                   evidence=[ev("Methods")])
            order += 1
            d.step(prep, order, f"{key}-dry-{i + 1}", f"Dry{f' after portion {i + 1}' if portions > 1 else ''}", "dry",
                   temperature=V(393, "K"), duration=V(12, "h"), atmosphere="static air", evidence=[ev("Methods")])
            order += 1
        d.step(prep, order, f"{key}-calcine", "Calcine", "calcine", temperature=V(723, "K"), duration=V(4, "h"),
               ramp_rate=ramp or dict(NOT_STATED), atmosphere="static air", evidence=[ev("Methods")])
        return prep

    p1 = preparation("batch-1", b1, lot_a, "≥99.9 % (trace metals basis), as the supplier states", 1, ramp=V(5, "K/min"))
    p2 = preparation("batch-2", b2, lot_b, "≥99.9 % (trace metals basis), as the supplier states", 2,
                     deviation="the precursor was dissolved in 1.50 mL, more than the incipient volume, so the solution "
                               "was added in two portions with drying in between")

    # ---- the activation, storage and transfer history of each batch, in order
    def treatment(key, name, kind, sample, order, after, **props):
        t = d.node(f"treatment/{key}", "Treatment", name, treatment_kind=kind, **props)
        d.link("TREATED_BY", sample, t, order=order)
        d.link("PRECEDES", after, t)
        return t

    r1 = treatment("batch-1-reduction", "Reduction of batch 1, 573 K", "reduction", b1, 1, p1, temperature=V(573, "K"),
                   duration=V(2, "h"), atmosphere="10 % H2 in Ar",
                   conditions={"flow_rate": V(50, "mL/min"), "ramp_rate": V(10, "K/min")}, evidence=[ev("Methods")])
    pa1 = treatment("batch-1-passivation", "Passivation of batch 1", "oxidation", b1, 2, r1, method="passivation",
                    temperature=V(298, "K", qualifier="approximate", as_reported="room temperature"), duration=V(1, "h"),
                    atmosphere="1 % O2 in N2", evidence=[ev("Methods")])
    st1 = treatment("batch-1-storage", "Storage of batch 1, 14 days", "exposure", b1, 3, pa1, method="storage in a closed "
                    "vial", duration=V(14, "d"), atmosphere="not stated", temperature=dict(NOT_STATED),
                    note="the paper says the vial was closed, not what gas it held", evidence=[ev("Methods")])
    rc1 = treatment("batch-1-cell-reduction", "Reduction of batch 1 in the XAS cell, 573 K", "reduction", b1, 4, st1,
                    temperature=V(573, "K"), duration=V(1, "h"), atmosphere="H2",
                    conditions={"flow_rate": dict(NOT_STATED)}, evidence=[ev("Methods")])
    r2 = treatment("batch-2-reduction", "Reduction of batch 2, 773 K", "reduction", b2, 1, p2, temperature=V(773, "K"),
                   duration=V(2, "h"), atmosphere="10 % H2 in Ar",
                   conditions={"flow_rate": V(50, "mL/min"), "ramp_rate": V(10, "K/min")}, evidence=[ev("Methods")])
    pa2 = treatment("batch-2-passivation", "Passivation of batch 2", "oxidation", b2, 2, r2, method="passivation",
                    temperature=V(298, "K", qualifier="approximate", as_reported="room temperature"), duration=V(1, "h"),
                    atmosphere="1 % O2 in N2", evidence=[ev("Methods")])

    def state(key, name, kind, sample, reached_by, timing="after", **props):
        s = d.node(f"state/{key}", "CatalystState", name, state_kind=kind, **props)
        d.link("STATE_OF", s, sample)
        d.link("REACHED_BY", s, reached_by, timing=timing)
        return s

    s1_calc = state("batch-1-calcined", "batch 1 as calcined", "as_prepared", b1, p1, evidence=[ev("Methods")])
    s1_red = state("batch-1-reduced", "batch 1 after reduction at 573 K", "pretreated", b1, r1, evidence=[ev("Methods")])
    s1_stored = state("batch-1-stored", "batch 1 passivated and stored 14 days", "other", b1, st1,
                      morphology="passivated, then stored in a closed vial", evidence=[ev("Methods")])
    s1_rered = state("batch-1-re-reduced", "batch 1 reduced again in the XAS cell", "pretreated", b1, rc1,
                     evidence=[ev("Methods")])
    s2_red = state("batch-2-reduced", "batch 2 after reduction at 773 K", "pretreated", b2, r2, evidence=[ev("Methods")])
    s2_pass = state("batch-2-passivated", "batch 2 passivated", "other", b2, pa2, morphology="passivated",
                    evidence=[ev("Methods")])

    # ---- the purchased commercial catalyst: two lots, no batch shared unless the paper says so
    supplier = d.node("institution/supplier", "Institution", "An invented supplier", institution_kind="company")
    commercial = d.node("catalyst/commercial-pt-alumina", "Catalyst", "commercial 5 wt% Pt on alumina (invented product)",
                        nominal_formula="Pt/Al2O3", catalyst_family="metal", evidence=[ev("Methods")])
    d.link("DEVELOPED_BY", commercial, supplier, role="supplier", evidence=[ev("Methods")])
    d.link("HAS_COMPONENT", commercial, pt_fcc, role="active_phase", loading_basis="mass",
           loading=V(5, "wt%", origin="assumed", definition="nominal, as the supplier states", evidence_ids=["m_comm"]),
           evidence=[ev("Methods", id="m_comm")])
    lot0417 = d.node("sample/commercial-lot-0417", "CatalystSample", "commercial Pt/Al2O3, lot 0417", sample_kind="powder",
                     preparation_status="purchased", batch_identifier="0417", evidence=[ev("Methods")])
    lot_other = d.node("sample/commercial-second-lot", "CatalystSample", "commercial Pt/Al2O3, a second lot",
                       sample_kind="powder", preparation_status="purchased",
                       note="bought a year later; the paper does not give its lot number", evidence=[ev("Methods")])
    for s in (lot0417, lot_other):
        d.link("HAS_FORMULATION", s, commercial)

    # ---- variables: one per measurand, so that a size from one technique never answers for another
    v_loading = d.variable("pt-loading-icp", "Pt loading by ICP-OES", "loading", "wt%",
                           "mass of Pt per mass of catalyst, by ICP-OES after acid digestion")
    v_uptake = d.variable("h2-uptake", "irreversible H2 uptake", "gas_uptake", "µmol/g",
                          "H2 adsorbed irreversibly at 308 K: the difference of the first and second isotherms, "
                          "extrapolated to zero pressure")
    v_dispersion = d.variable("pt-dispersion", "Pt dispersion", "site_fraction", "%",
                              "exposed Pt atoms as a share of all Pt atoms")
    v_dsize = d.variable("dispersion-size", "Pt particle size from the dispersion", "dispersion_equivalent_size", "nm",
                         "the diameter of hemispherical particles that would give the dispersion measured")
    v_tem_mean = d.variable("stem-mean-diameter", "mean Pt particle diameter (HAADF-STEM)", "particle_size", "nm",
                            "number-weighted mean of the projected-area-equivalent diameters of the particles counted")
    v_tem_sd = d.variable("stem-diameter-sd", "standard deviation of the Pt particle diameters (HAADF-STEM)",
                          "particle_size_spread", "nm",
                          "standard deviation of the number distribution of the diameters counted: the width of the "
                          "distribution, not an uncertainty of its mean")
    v_counted = d.variable("particles-counted", "particles counted", "count", "1",
                           "number of particles whose diameters make the distribution")
    v_xrd = d.variable("xrd-crystallite-size", "Pt crystallite size (XRD)", "crystallite_size", "nm",
                       "volume-weighted coherent-domain size from the width of the Pt(111) reflection, Scherrer "
                       "equation with K = 0.9, instrumental broadening subtracted")
    v_cn = d.variable("cn-pt-pt", "Pt-Pt coordination number (first shell, EXAFS)", "coordination_number", "1",
                      "the average number of Pt neighbours of a Pt atom in the first shell, fitted to the EXAFS")
    v_bet = d.variable("bet-area", "specific surface area (BET, N2)", "specific_surface_area", "m2/g",
                       "BET area from N2 adsorption at 77 K")
    v_pore = d.variable("pore-volume", "pore volume (N2)", "pore_volume", "cm3/g",
                        "N2 adsorbed at p/p0 = 0.99, as liquid")
    v_conv = d.variable("ethylene-conversion", "ethylene conversion", "conversion", "%", "ethylene converted per pass")

    # ---- instruments, standards and the software
    diffractometer = d.node("instrument/diffractometer", "Instrument", "Powder diffractometer", instrument_kind="X-ray "
                            "diffractometer", settings={"radiation": T("Cu K alpha"), "step": V(0.02, "°")},
                            evidence=[ev("Methods")])
    lab6 = d.node("sample/lab6-standard", "Sample", "LaB6 line-profile standard", sample_kind="powder",
                  preparation_status="purchased", evidence=[ev("Methods")])
    lab6_run = d.node("characterization/lab6-calibration", "Characterization", "Instrumental broadening from LaB6",
                      technique="powder X-ray diffraction", goal="calibrate", evidence=[ev("Methods")])
    d.link("HAS_INPUT", lab6_run, lab6, role="reference_standard")
    d.link("CALIBRATED_BY", diffractometer, lab6_run)
    foil = d.node("sample/pt-foil", "Sample", "Pt foil, 7.5 µm", sample_kind="film", preparation_status="purchased",
                  evidence=[ev("Methods")])
    d.link("HAS_COMPONENT", foil, pt, role="other", role_detail="reference foil for the energy calibration")
    fitter = d.node("software/fitter", "Software", "EXAFS fitting program (invented)", evidence=[ev("Methods")])

    def char(key, name, technique, sample, at_state, evidence, results=(), state_node=None, **props):
        x = d.node(f"characterization/{key}", "Characterization", name, technique=technique, experiment_kind="physical",
                   **({"result_values": list(results)} if results else {}), evidence=evidence, **props)
        d.link("CHARACTERIZES", x, sample, state=at_state)
        if state_node:
            d.link("DETERMINED_BY", state_node, x)
        return x

    # ---- loadings: nominal on the formulation, measured on each specimen
    icp = {}
    for s, key, value, unit, eid in ((b1, "batch-1", 3.8, "wt%", "t1_icp_1"), (b2, "batch-2", 4.6, "wt%", "t1_icp_2"),
                                     (lot0417, "commercial-0417", 4.9, "wt%", "t1_icp_c1"),
                                     (lot_other, "commercial-second", 4.7, "%", "t1_icp_c2")):
        extra = {"as_reported": "4.7 % Pt"} if unit == "%" else {}
        icp[key] = char(f"icp-{key}", f"ICP-OES of {key.replace('-', ' ')}", "ICP-OES after acid digestion", s,
                        "calcined" if key.startswith("batch") else "fresh", [ev("Table 1", "table", id=eid)],
                        results=[V(value, unit, id="pt_loading", variable=v_loading, target=pt, evidence_ids=[eid],
                                   **({"uncertainty": 0.1, "uncertainty_kind": "standard_deviation", "replicates": 3}
                                      if key == "batch-1" else {}), **extra)],
                        state_node=s1_calc if key == "batch-1" else None, information_depth="bulk", sampling="ensemble")

    # ---- H2 chemisorption and the dispersion it gives
    one_h = d.node("model/one-h-per-surface-pt", "Model", "One H atom per surface Pt atom", model_kind="adsorption "
                   "stoichiometry", assumptions=["one H atom per surface Pt atom (H/Pt = 1)",
                                                 "the Pt content is the one measured by ICP-OES, not the nominal one",
                                                 "hemispherical particles, 0.0807 nm2 per surface Pt atom, for the size "
                                                 "from the dispersion"], evidence=[ev("Methods")])
    exposed_pt = d.node("site/exposed-pt", "ActiveSite", "exposed Pt atoms", site_kind="metal_site", evidence=[ev("Methods")])
    d.link("LOCATED_ON", exposed_pt, pt_fcc)
    chem_states = {"batch-1": s1_red, "batch-2": s2_red}
    pretreat = {"batch-1": 573, "batch-2": 773, "commercial-0417": 573, "commercial-second": 573}
    for s, key, uptake, disp, size, eid in ((b1, "batch-1", 40.0, 41, 2.8, "t2_chem_1"), (b2, "batch-2", 20.0, 17, 6.6, "t2_chem_2"),
                                            (lot0417, "commercial-0417", 41.4, 33, 3.4, "t2_chem_c1"),
                                            (lot_other, "commercial-second", 28.9, 24, 4.7, "t2_chem_c2")):
        c = char(f"h2-chemisorption-{key}", f"H2 chemisorption of {key.replace('-', ' ')}", "H2 chemisorption, volumetric, "
                 "two isotherms", s, "reduced", [ev("Table 2", "table", id=eid)],
                 results=[V(uptake, "µmol/g", id="h2_uptake", variable=v_uptake, target=h2, evidence_ids=[eid],
                            **({"uncertainty": 1.5, "uncertainty_kind": "standard_deviation", "replicates": 3}
                               if key == "batch-1" else {}))],
                 temperature=V(308, "K"), observation_mode="in_situ",
                 conditions={"pretreatment": T(f"reduced in the cell in H2 at {pretreat[key]} K for 1 h, evacuated at "
                                               f"{pretreat[key]} K for 1 h")})
        aid = f"{d.p}/analysis/dispersion-{key}"
        a = d.node(f"analysis/dispersion-{key}", "Analysis", f"Pt dispersion of {key.replace('-', ' ')} from the H2 uptake",
                   analysis_kind="other", experiment_kind="computational",
                   method="dispersion from the irreversible H2 uptake and the Pt content measured by ICP-OES",
                   result_values=[V(disp, "%", id="dispersion", variable=v_dispersion, target=pt, origin="derived",
                                    produced_by=aid, basis="of all Pt atoms", evidence_ids=[eid]),
                                  V(size, "nm", id="size_from_dispersion", variable=v_dsize, target=pt_fcc,
                                    origin="derived", produced_by=aid, evidence_ids=[eid])],
                   evidence=[ev("Table 2", "table", id=eid)])
        d.link("HAS_INPUT", a, c, role="data")
        d.link("HAS_INPUT", a, icp[key], role="parameter")
        d.link("USES_MODEL", a, one_h)
        if key in chem_states:
            d.link("HAS_SITE", chem_states[key], exposed_pt, status="asserted",
                   population_fraction=V(disp, "%", basis="of all Pt atoms", origin="derived", produced_by=a,
                                         evidence_ids=[eid]),
                   note="measured after the chemisorption cell's own reduction, at the batch's reduction temperature",
                   evidence=[ev("Table 2", "table", id=eid)])

    # ---- HAADF-STEM size statistics, each statistic its own result
    def stem(key, s, at_state, mean, sd, counted, eid, state_node, transfer, images_available=True):
        x = char(f"stem-{key}", f"HAADF-STEM of {key.replace('-', ' ')}", "HAADF-STEM", s, at_state,
                 [ev("Figure 3", "figure", id=eid)],
                 results=[V(mean, "nm", id="mean_diameter", variable=v_tem_mean, target=pt_fcc, evidence_ids=[eid]),
                          V(sd, "nm", id="diameter_sd", variable=v_tem_sd, target=pt_fcc, evidence_ids=[eid]),
                          V(counted, "1", id="particles_counted", variable=v_counted, target=pt_fcc, evidence_ids=[eid])],
                 state_node=state_node, observation_mode="ex_situ", information_depth="projection",
                 sampling="single_particle", transfer=transfer,
                 conditions={"accelerating_voltage": V(200, "kV"), "regions_imaged": V(6, "1"),
                             "images": V(14, "1"),
                             "lower_size_limit": V(0.5, "nm", definition="the smallest particle this imaging mode and "
                                                   "magnification resolve, as the paper gives it"),
                             "electron_dose": {**NOT_STATED, "definition": "the total electron dose on the areas imaged"}})
        images = d.node(f"dataset/stem-images-{key}", "Dataset", f"HAADF-STEM images of {key.replace('-', ' ')}",
                        data_kind="image", availability="available" if images_available else "not_reported",
                        **({"uri": f"https://example.org/invented/stem-images-{key}"} if images_available else {}))
        d.link("HAS_OUTPUT", x, images)
        return x

    stem("batch-1", b1, "other", 2.1, 0.5, 312, "f3_b1", s1_stored, "mounted on the grid in air after storage")
    stem("batch-2", b2, "other", 5.8, 1.9, 280, "f3_b2", s2_pass, "mounted on the grid in air after passivation",
         images_available=False)

    # ---- XRD: no Pt reflection for batch 1; a crystallite size for batch 2
    xrd1 = char("xrd-batch-1", "XRD of batch 1, passivated", "powder X-ray diffraction", b1, "other",
                [ev("Figure 2", "figure", id="f2_b1")],
                results=[{"status": "below_detection_limit", "value": 3, "unit": "nm", "id": "pt_crystallite_size",
                          "variable": v_xrd, "target": pt_fcc, "evidence_ids": ["f2_b1"],
                          "definition": "no Pt(111) reflection above the background; the paper takes about 3 nm as "
                                        "the smallest Pt crystallite this measurement resolves"}],
                observation_mode="ex_situ", information_depth="bulk", sampling="ensemble")
    xrd2 = char("xrd-batch-2", "XRD of batch 2, passivated", "powder X-ray diffraction", b2, "other",
                [ev("Figure 2", "figure", id="f2_b2")],
                results=[V(6.5, "nm", id="pt_crystallite_size", variable=v_xrd, target=pt_fcc, evidence_ids=["f2_b2"],
                           calibration=lab6_run)],
                state_node=s2_pass, observation_mode="ex_situ", information_depth="bulk", sampling="ensemble")
    for x in (xrd1, xrd2):
        d.link("USES_INSTRUMENT", x, diffractometer, role="measurement")
    patterns = d.node("dataset/xrd-patterns", "Dataset", "XRD patterns of both batches", data_kind="raw",
                      availability="available", uri="https://example.org/invented/xrd-patterns")
    for x in (xrd1, xrd2):
        d.link("HAS_OUTPUT", x, patterns)

    # ---- Pt L3 XAS of batch 1, reduced again in the cell, and the fit of its EXAFS
    xas = char("xas-batch-1", "Pt L3-edge XAS of batch 1 in H2 after reduction in the cell", "Pt L3-edge XAS", b1,
               "reactivated", [ev("Methods"), ev("Figure 4", "figure")], state_node=s1_rered,
               observation_mode="in_situ", information_depth="bulk", sampling="ensemble",
               temperature=V(298, "K"), atmosphere="H2, after reduction in the cell at 573 K",
               conditions={"edge": T("Pt L3, 11564 eV"), "detection": T("transmission"),
                           "energy_calibration": T("Pt foil measured downstream at the same time; its first inflection "
                                                   "set to 11564 eV"),
                           "scans_averaged": V(3, "1")})
    d.link("HAS_INPUT", xas, foil, role="reference_standard")
    spectra = d.node("dataset/xas-batch-1", "Dataset", "Pt L3 XAS of batch 1 in H2", data_kind="spectrum",
                     availability="available", uri="https://example.org/invented/xas-batch-1")
    foil_spectrum = d.node("dataset/xas-pt-foil", "Dataset", "Pt L3 XAS of the Pt foil", data_kind="spectrum",
                           availability="available", uri="https://example.org/invented/xas-pt-foil")
    d.link("HAS_OUTPUT", xas, spectra)
    d.link("HAS_OUTPUT", xas, foil_spectrum)
    shell = d.node("model/pt-pt-shell", "Model", "One Pt-Pt single-scattering path from fcc Pt", model_kind="EXAFS shell "
                   "model", assumptions=["one Pt-Pt path from fcc Pt; no Pt-O or Pt-Cl path",
                                         "S0^2 = 0.84, from the fit of the Pt foil, held fixed"],
                   parameters={"s0_squared": V(0.84, "1"), "k_weight": V(2, "1")}, evidence=[ev("Table 3", "table")])
    fid = f"{d.p}/analysis/exafs-batch-1"
    fitted = {"origin": "fitted", "produced_by": fid, "uncertainty_kind": "standard_uncertainty", "evidence_ids": ["t3_fit"]}
    fit = d.node("analysis/exafs-batch-1", "Analysis", "First-shell fit of the Pt L3 EXAFS of batch 1",
                 analysis_kind="spectral_fit", experiment_kind="computational",
                 method="k2-weighted EXAFS, k 3.0-12.5 1/Å, R 1.6-3.1 Å; CN, R, sigma^2 and delta E0 fitted",
                 limitations="the coordination number averages over every Pt atom: uniform 2 nm particles and a mix of "
                             "larger particles with isolated atoms can give the same value; a Pt-Cl contribution from "
                             "fewer than about one Pt atom in ten would not be resolved",
                 result_values=[V(7.9, "1", id="cn_pt_pt", variable=v_cn, uncertainty=0.6, **fitted)],
                 results={"r_pt_pt": V(2.75, "Å", uncertainty=0.01, **fitted),
                          "sigma_squared": V(0.0060, "Å2", uncertainty=0.0008, **fitted),
                          "delta_e0": V(6.3, "eV", uncertainty=0.9, **fitted),
                          "r_factor": V(0.009, "1", evidence_ids=["t3_fit"]),
                          "independent_points": V(9.1, "1", evidence_ids=["t3_fit"]),
                          "fitted_parameters": V(4, "1", evidence_ids=["t3_fit"])},
                 evidence=[ev("Table 3", "table", id="t3_fit")])
    d.link("HAS_INPUT", fit, spectra, role="data")
    d.link("HAS_INPUT", fit, foil_spectrum, role="reference_standard")
    d.link("USES_MODEL", fit, shell)
    d.link("USES_SOFTWARE", fit, fitter, version="1.0")

    # ---- N2 physisorption of batch 1 and its BET fit
    phys = char("n2-physisorption-batch-1", "N2 physisorption of batch 1, calcined", "N2 physisorption at 77 K", b1,
                "calcined", [ev("Methods")], temperature=V(77, "K"),
                conditions={"degassing_temperature": V(573, "K"), "degassing_time": V(3, "h"),
                            "degassing_atmosphere": T("vacuum")})
    isotherm = d.node("dataset/isotherm-batch-1", "Dataset", "N2 isotherm of batch 1", data_kind="table",
                      availability="not_reported")
    d.link("HAS_OUTPUT", phys, isotherm)
    bet_model = d.node("model/bet", "Model", "BET equation", model_kind="adsorption isotherm",
                       assumptions=["multilayer adsorption without micropore filling",
                                    "0.162 nm2 per adsorbed N2 molecule"], evidence=[ev("Methods")])
    bid = f"{d.p}/analysis/bet-batch-1"
    bet = d.node("analysis/bet-batch-1", "Analysis", "BET analysis of batch 1", analysis_kind="other",
                 experiment_kind="computational", method="BET, p/p0 0.05-0.30, 6 points",
                 limitations="a C constant of 96 with no micropores: the BET range holds for this mesoporous solid",
                 result_values=[V(182, "m2/g", id="bet_area", variable=v_bet, origin="fitted", produced_by=bid,
                                  evidence_ids=["t1_bet"]),
                                V(0.47, "cm3/g", id="pore_volume", variable=v_pore, evidence_ids=["t1_bet"])],
                 results={"c_constant": V(96, "1", origin="fitted", produced_by=bid, evidence_ids=["t1_bet"])},
                 evidence=[ev("Table 1", "table", id="t1_bet")])
    d.link("HAS_INPUT", bet, phys, role="data")
    d.link("USES_MODEL", bet, bet_model)

    # ---- the reaction history: a test after the reduction in the cell, and the state it leaves
    rxn = d.node("reaction/ethylene-hydrogenation", "Reaction", "C2H4 + H2 -> C2H6", equation="C2H4 + H2 -> C2H6",
                 balance_status="balanced", direction="forward")
    for sp, role in ((ethylene, "reactant"), (h2, "reactant"), (ethane, "product")):
        d.link("HAS_PARTICIPANT", rxn, sp, role=role, coefficient=1)
    feed = d.node("feed/ethylene-h2", "Feed", "2 % C2H4, 20 % H2 in He", evidence=[ev("Methods")])
    d.link("HAS_COMPONENT", feed, ethylene, role="reactant", fraction=V(2, "mol%"))
    d.link("HAS_COMPONENT", feed, h2, role="reactant", fraction=V(20, "mol%"))
    test = d.node("test/batch-1-ethylene-hydrogenation", "CatalyticTest",
                  "Ethylene hydrogenation over batch 1 in the XAS cell, 298 K",
                  test_kind="activity", driving_forces=["thermo"], experiment_kind="physical",
                  temperature=V(298, "K"), pressure=V(1, "atm", basis="absolute"), temperature_measured_at="catalyst_bed",
                  flow_rate=V(50, "mL/min"), time_on_stream=V(2, "h"),
                  result_values=[V(12, "%", id="ethylene_conversion", variable=v_conv, target=ethylene,
                                   evidence_ids=["t4_conv"])],
                  evidence=[ev("Table 4", "table", id="t4_conv")])
    d.link("USES_CATALYST", test, b1, state="reactivated")
    d.link("FED_WITH", test, feed)
    d.link("OF_REACTION", test, rxn)
    d.link("PRECEDES", rc1, xas)
    d.link("PRECEDES", xas, test)
    state("batch-1-working", "batch 1 under ethylene hydrogenation", "working", b1, test, timing="during",
          evidence=[ev("Table 4", "table")])
    state("batch-1-after-test", "batch 1 after the test", "post_reaction", b1, test, evidence=[ev("Table 4", "table")])
    return d.finish()


# ================================================================================== coprecipitation
def coprecipitation() -> dict:
    d = Doc("ex:cp", "Cu/ZnO/Al2O3 by coprecipitation in two orders of addition, with its bulk and surface composition "
                     "and what the paper leaves unstated (synthetic)")
    d.paper = d.node("source/paper", "Source", "Invented paper", kind="article", year=2026,
                     title="Normal and reverse coprecipitation of a Cu/ZnO/Al2O3 catalyst (invented)")
    ev = d.ev
    cu_n = d.species("cu-nitrate", "Cu(NO3)2·3H2O", {"Cu": 1, "N": 2, "O": 9, "H": 6}, name="copper nitrate trihydrate")
    zn_n = d.species("zn-nitrate", "Zn(NO3)2·6H2O", {"Zn": 1, "N": 2, "O": 12, "H": 12}, name="zinc nitrate hexahydrate")
    al_n = d.species("al-nitrate", "Al(NO3)3·9H2O", {"Al": 1, "N": 3, "O": 18, "H": 18},
                     name="aluminium nitrate nonahydrate")
    carbonate = d.species("sodium-carbonate", "Na2CO3", {"Na": 2, "C": 1, "O": 3}, name="sodium carbonate")
    water = d.species("water", "H2O", {"H": 2, "O": 1}, name="water")
    cu, zn, al = d.element("Cu", "copper"), d.element("Zn", "zinc"), d.element("Al", "aluminium")
    cu_fcc = d.node("material/cu-fcc", "Material", "fcc Cu", formula="Cu", structure_type="fcc", material_family="metal")
    cat = d.node("catalyst/cu-zno-alumina", "Catalyst", "Cu/ZnO/Al2O3, Cu:Zn:Al = 60:30:10 (atomic, nominal)",
                 nominal_formula="Cu/ZnO/Al2O3", catalyst_family="metal", evidence=[ev("Methods")])
    for el, share in ((cu, 60), (zn, 30), (al, 10)):
        d.link("HAS_COMPONENT", cat, el, role="active_component" if el == cu else "promoter", fraction_basis="atom",
               fraction=V(share, "at%", origin="assumed", basis="metals only: Cu + Zn + Al", definition="nominal, from "
                          "the salts weighed", evidence_ids=["m_nominal"]),
               evidence=[ev("Methods", id="m_nominal")])

    v_bulk = d.variable("xrf-metal-fraction", "metal fraction in the bulk (XRF)", "composition_fraction", "at%",
                        "atom fraction of the metal among Cu, Zn and Al, by X-ray fluorescence of the calcined powder")
    v_surface = d.variable("xps-metal-fraction", "metal fraction at the surface (XPS)", "composition_fraction", "at%",
                           "atom fraction of the metal among Cu, Zn and Al, from the Cu 2p, Zn 2p and Al 2p peak areas "
                           "with the instrument's sensitivity factors")
    v_bet = d.variable("bet-area", "specific surface area (BET, N2)", "specific_surface_area", "m2/g",
                       "BET area from N2 adsorption at 77 K")
    v_cu_area = d.variable("cu-surface-area", "Cu surface area (N2O)", "metal_surface_area", "m2/g",
                           "from the N2O consumed by reactive frontal chromatography at 333 K")
    v_xrd = d.variable("xrd-crystallite-size", "Cu crystallite size (XRD)", "crystallite_size", "nm",
                       "coherent-domain size from the Cu(111) reflection, Scherrer equation with K = 0.9")
    two_cu = d.node("model/two-cu-per-o", "Model", "Two surface Cu atoms per O atom from N2O", model_kind="adsorption "
                    "stoichiometry", assumptions=["N2O oxidizes surface Cu only, one O atom per two Cu atoms",
                                                 "1.47e19 Cu atoms per m2 of Cu surface"], evidence=[ev("Methods")])

    def batch(key, name, order_text, carbonate_into_nitrates, addition_rate, final_ph, storage_atmosphere, storage_days,
              results):
        s = d.node(f"sample/{key}", "CatalystSample", name, sample_kind="batch", batch_identifier=key.split("-")[-1].upper(),
                   preparation_status="prepared", evidence=[ev("Methods")])
        d.link("HAS_FORMULATION", s, cat)
        prep = d.node(f"preparation/{key}", "Preparation", f"Coprecipitation, {order_text}", method=f"coprecipitation, "
                      f"{order_text}", evidence=[ev("Methods")])
        d.link("HAS_OUTPUT", prep, s)
        for salt, grams in ((cu_n, 28.99), (zn_n, 17.85), (al_n, 7.50), (carbonate, 31.80)):
            d.link("PREPARED_FROM", s, salt, role="precursor" if salt != carbonate else "precipitating agent",
                   amount=V(grams, "g"), evidence=[ev("Methods")])
        nitrates = d.node(f"solution/{key}-nitrates", "Sample", f"mixed nitrate solution, {key}", sample_kind="other",
                          preparation_status="prepared", evidence=[ev("Methods")])
        for salt, conc in ((cu_n, 0.60), (zn_n, 0.30), (al_n, 0.10)):
            d.link("HAS_COMPONENT", nitrates, salt, role="precursor", concentration=V(conc, "mol/L", evidence_ids=["m_sol"]),
                   evidence=[ev("Methods", id="m_sol")])
        carb = d.node(f"solution/{key}-carbonate", "Sample", f"sodium carbonate solution, {key}", sample_kind="other",
                      preparation_status="prepared", evidence=[ev("Methods")])
        d.link("HAS_COMPONENT", carb, carbonate, role="other", role_detail="precipitating agent",
               concentration=V(1.2, "mol/L", evidence_ids=["m_sol"]), evidence=[ev("Methods", id="m_sol")])
        d.step(prep, 1, f"{key}-dissolve-nitrates", "Dissolve the nitrates", "dissolve",
               inputs=[(cu_n, "reagent", V(28.99, "g")), (zn_n, "reagent", V(17.85, "g")), (al_n, "reagent", V(7.50, "g")),
                       (water, "reagent", V(200, "mL"))], outputs=[nitrates], evidence=[ev("Methods")])
        d.step(prep, 2, f"{key}-dissolve-carbonate", "Dissolve the carbonate", "dissolve",
               inputs=[(carbonate, "reagent", V(31.80, "g")), (water, "reagent", V(250, "mL"))], outputs=[carb],
               evidence=[ev("Methods")])
        added, receiving = (carb, nitrates) if carbonate_into_nitrates else (nitrates, carb)
        d.step(prep, 3, f"{key}-precipitate", "Add one solution to the other", "precipitate",
               inputs=[(added, "reagent", None), (receiving, "material", None)],
               method=("the carbonate solution added dropwise to the stirred nitrate solution" if carbonate_into_nitrates
                       else "the nitrate solution added to the stirred carbonate solution"),
               temperature=V(338, "K"),
               conditions={"addition_rate": {**addition_rate, "definition": "the rate the added solution was fed at"},
                           "stirring_rate": {**NOT_STATED, "definition": "the stirring rate of the receiving solution"},
                           "final_ph": V(final_ph, "1", definition="the pH of the slurry when the addition ended",
                                         evidence_ids=["m_ph"])},
               evidence=[ev("Methods", id="m_ph")])
        d.step(prep, 4, f"{key}-age", "Age in the mother liquor", "age", temperature=V(338, "K"), duration=V(1, "h"),
               evidence=[ev("Methods")])
        d.step(prep, 5, f"{key}-filter", "Filter", "filter", evidence=[ev("Methods")])
        d.step(prep, 6, f"{key}-wash", "Wash", "wash", inputs=[(water, "reagent", None)],
               conditions={"filtrate_conductivity": V(0.1, "mS/cm", bound="upper", definition="washed until the filtrate "
                                                      "conductivity was below this", evidence_ids=["m_wash"])},
               evidence=[ev("Methods", id="m_wash")])
        d.step(prep, 7, f"{key}-dry", "Dry", "dry", temperature=V(383, "K"), duration=V(12, "h"), atmosphere="air",
               evidence=[ev("Methods")])
        d.step(prep, 8, f"{key}-calcine", "Calcine", "calcine", temperature=V(623, "K"), duration=V(3, "h"),
               ramp_rate=V(2, "K/min"), atmosphere="static air", evidence=[ev("Methods")])
        storage = d.node(f"treatment/{key}-storage", "Treatment", f"Storage of {key}, {storage_days} days",
                         treatment_kind="exposure", method="storage of the calcined powder", duration=V(storage_days, "d"),
                         atmosphere=storage_atmosphere, evidence=[ev("Methods")])
        d.link("TREATED_BY", s, storage, order=1)
        d.link("PRECEDES", prep, storage)
        reduction = d.node(f"treatment/{key}-reduction", "Treatment", f"Reduction of {key} in the N2O unit, 513 K",
                           treatment_kind="reduction", temperature=V(513, "K"), duration=V(2, "h"), atmosphere="5 % H2 in Ar",
                           evidence=[ev("Methods")])
        d.link("TREATED_BY", s, reduction, order=2)
        d.link("PRECEDES", storage, reduction)

        def char(ckey, name, technique, at_state, eid, res, **props):
            x = d.node(f"characterization/{key}-{ckey}", "Characterization", name, technique=technique,
                       experiment_kind="physical", result_values=res, evidence=[ev("Table 1", "table", id=eid)], **props)
            d.link("CHARACTERIZES", x, s, state=at_state)
            return x

        bulk, surface, bet, n2o, xrd = results
        char("xrf", f"XRF of {key}, calcined", "X-ray fluorescence", "calcined", f"t1_xrf_{key}",
             [V(v, "at%", id=f"{el_key}_fraction", variable=v_bulk, target=el, basis="metals only: Cu + Zn + Al",
                evidence_ids=[f"t1_xrf_{key}"]) for (el_key, el), v in zip((("cu", cu), ("zn", zn), ("al", al)), bulk)],
             information_depth="bulk", sampling="ensemble")
        xps = char("xps", f"XPS of {key}, calcined", "X-ray photoelectron spectroscopy", "calcined", f"t1_xps_{key}",
                   [V(v, "at%", id=f"{el_key}_fraction", variable=v_surface, target=el, basis="metals only: Cu + Zn + Al",
                      evidence_ids=[f"t1_xps_{key}"]) for (el_key, el), v in zip((("cu", cu), ("zn", zn), ("al", al)), surface)],
                   information_depth="surface", sampling="ensemble", observation_mode="ex_situ",
                   transfer="transferred in air")
        xps_spectra = d.node(f"dataset/{key}-xps", "Dataset", f"XPS spectra of {key}", data_kind="spectrum",
                             availability="not_reported")
        d.link("HAS_OUTPUT", xps, xps_spectra)
        char("bet", f"N2 physisorption of {key}, calcined", "N2 physisorption at 77 K", "calcined", f"t1_bet_{key}",
             [V(bet, "m2/g", id="bet_area", variable=v_bet, definition="BET, p/p0 0.05-0.30",
                evidence_ids=[f"t1_bet_{key}"])],
             temperature=V(77, "K"), conditions={"degassing_temperature": V(423, "K"), "degassing_time": V(4, "h")})
        rfc = char("n2o", f"N2O frontal chromatography of {key}, reduced", "N2O reactive frontal chromatography", "reduced",
                   f"t1_n2o_{key}",
                   [V(n2o, "m2/g", id="cu_surface_area", variable=v_cu_area, target=cu_fcc, evidence_ids=[f"t1_n2o_{key}"])],
                   observation_mode="in_situ", temperature=V(333, "K"))
        a = d.node(f"analysis/{key}-cu-area", "Analysis", f"Cu surface area of {key} from the N2O consumed",
                   analysis_kind="other", experiment_kind="computational", method="two surface Cu atoms per O atom",
                   evidence=[ev("Methods")])
        d.link("HAS_INPUT", a, rfc, role="data")
        d.link("USES_MODEL", a, two_cu)
        char("xrd", f"XRD of {key}, reduced and passivated", "powder X-ray diffraction", "other", f"t1_xrd_{key}",
             [V(xrd, "nm", id="cu_crystallite_size", variable=v_xrd, target=cu_fcc, evidence_ids=[f"t1_xrd_{key}"])],
             information_depth="bulk", sampling="ensemble", observation_mode="ex_situ",
             note="reduced at 513 K, passivated in 1 % O2/N2 and measured in air")
        return s, prep

    batch("batch-n", "Cu/ZnO/Al2O3, batch N (carbonate added to the nitrates)", "carbonate added to the nitrates",
          True, V(3, "mL/min", evidence_ids=["m_ph"]), 7.0, "dry air, in a desiccator over silica gel", 21,
          ((58.6, 31.0, 10.4), (44.1, 45.2, 10.7), 98, 22, 7.2))
    batch("batch-r", "Cu/ZnO/Al2O3, batch R (nitrates added to the carbonate)", "nitrates added to the carbonate",
          False, dict(NOT_STATED), 8.1, "not stated", 30,
          ((61.9, 28.4, 9.7), (52.3, 37.5, 10.2), 76, 14, 9.8))
    return d.finish()


# ================================================================================== high-entropy alloy
def high_entropy_alloy() -> dict:
    d = Doc("ex:hea", "PtPdRhRuIr high-entropy-alloy nanoparticles on carbon: nominal, bulk, surface and working-state "
                      "compositions, and three sizes (synthetic)")
    d.paper = d.node("source/paper", "Source", "Invented paper", kind="article", year=2026,
                     title="What is at the surface of a five-metal alloy catalyst under CO oxidation (invented)")
    ev = d.ev
    metals = [("Pt", "platinum"), ("Pd", "palladium"), ("Rh", "rhodium"), ("Ru", "ruthenium"), ("Ir", "iridium")]
    el = {sym: d.element(sym, name) for sym, name in metals}
    carbon = d.node("material/carbon-black", "Material", "carbon black support", formula="C", material_family="carbon",
                    crystallinity="amorphous")
    hea = d.node("material/ptpdrhruir", "Material", "PtPdRhRuIr alloy, nominally equimolar",
                 nominal_formula="Pt0.2Pd0.2Rh0.2Ru0.2Ir0.2", structure_type="fcc", material_family="alloy",
                 evidence=[ev("Methods")])
    for sym, _ in metals:
        d.link("HAS_COMPONENT", hea, el[sym], role="active_component", fraction_basis="atom",
               fraction=V(20, "at%", origin="assumed", basis="metals only", definition="nominal: equal amounts of the "
                          "five salts", evidence_ids=["m_nominal"]),
               evidence=[ev("Methods", id="m_nominal")])
    ruox = d.node("material/ruox", "Material", "RuOx at the surface", formula="RuOx", material_family="oxide",
                  crystallinity="not_reported")
    cat = d.node("catalyst/hea-carbon", "Catalyst", "PtPdRhRuIr/C, 20 wt% metal (nominal)", nominal_formula="PtPdRhRuIr/C",
                 catalyst_family="alloy", evidence=[ev("Methods")])
    d.link("HAS_COMPONENT", cat, hea, role="active_phase", loading_basis="mass",
           loading=V(20, "wt%", origin="assumed", definition="nominal metal loading", evidence_ids=["m_nominal"]),
           evidence=[ev("Methods", id="m_nominal")])
    d.link("HAS_COMPONENT", cat, carbon, role="support", evidence=[ev("Methods")])
    sample = d.node("sample/hea-c", "CatalystSample", "PtPdRhRuIr/C", sample_kind="powder", preparation_status="prepared",
                    evidence=[ev("Methods")])
    d.link("HAS_FORMULATION", sample, cat)
    colloid = d.node("sample/colloid", "Sample", "PtPdRhRuIr colloid in ethylene glycol, before deposition",
                     sample_kind="other", preparation_status="prepared", evidence=[ev("Methods")])

    salts = []
    for key, formula, comp, name, hydration_stated in (
            ("h2ptcl6", "H2PtCl6·6H2O", {"H": 14, "Pt": 1, "Cl": 6, "O": 6}, "hexachloroplatinic acid hexahydrate", True),
            ("na2pdcl4", "Na2PdCl4", {"Na": 2, "Pd": 1, "Cl": 4}, "sodium tetrachloropalladate", True),
            ("rhcl3", "RhCl3·xH2O", {"Rh": 1, "Cl": 3}, "rhodium chloride hydrate", False),
            ("rucl3", "RuCl3·xH2O", {"Ru": 1, "Cl": 3}, "ruthenium chloride hydrate", False),
            ("h2ircl6", "H2IrCl6·xH2O", {"H": 2, "Ir": 1, "Cl": 6}, "hexachloroiridic acid hydrate", False)):
        salts.append(d.species(key, formula, comp, name=name, **({} if hydration_stated else {
            "note": "the paper gives the salt as a hydrate without its water content"})))
    prep = d.node("preparation/polyol", "Preparation", "Polyol synthesis of the colloid and deposition on carbon",
                  method="polyol reduction in ethylene glycol with PVP, then deposition on carbon", evidence=[ev("Methods")])
    d.link("HAS_OUTPUT", prep, sample)
    for s in salts:
        d.link("PREPARED_FROM", sample, s, role="metal precursor", amount=V(0.10, "mmol"), evidence=[ev("Methods")])
    d.step(prep, 1, "dissolve", "Dissolve the five salts in ethylene glycol with PVP", "dissolve",
           inputs=[(s, "reagent", V(0.10, "mmol")) for s in salts], evidence=[ev("Methods")])
    d.step(prep, 2, "reduce", "Heat to reduce the metals", "heat", outputs=[colloid], temperature=V(473, "K"),
           duration=V(2, "h"), ramp_rate=V(10, "K/min"), atmosphere="N2",
           conditions={"stirring_rate": V(400, "rpm")}, evidence=[ev("Methods")])
    d.step(prep, 3, "deposit", "Deposit the colloid on the carbon", "mix", inputs=[(colloid, "material", None),
           (carbon, "material", V(0.40, "g"))], duration=V(12, "h"), conditions={"stirring_rate": V(400, "rpm")},
           evidence=[ev("Methods")])
    d.step(prep, 4, "wash", "Wash with ethanol", "wash", evidence=[ev("Methods")])
    d.step(prep, 5, "dry", "Dry under vacuum", "dry", temperature=V(333, "K"), duration=V(12, "h"), atmosphere="vacuum",
           evidence=[ev("Methods")])

    v_bulk = d.variable("icp-metal-fraction", "metal fraction in the bulk (ICP-OES)", "composition_fraction", "at%",
                        "atom fraction of the metal among the five, by ICP-OES after digestion")
    v_surface = d.variable("xps-metal-fraction", "metal fraction at the surface (XPS)", "composition_fraction", "at%",
                           "atom fraction of the metal among the five, from the XPS peak areas")
    v_loading = d.variable("metal-loading-icp", "metal loading (ICP-OES)", "loading", "wt%",
                           "mass of the five metals per mass of catalyst, by ICP-OES")
    v_dls = d.variable("dls-hydrodynamic-size", "hydrodynamic diameter of the colloid (DLS, Z-average)",
                       "hydrodynamic_size", "nm",
                       "intensity-weighted harmonic mean diameter of the particles with their PVP shell in the liquid, "
                       "from the cumulant fit of the autocorrelation")
    v_pdi = d.variable("dls-pdi", "polydispersity index (DLS)", "polydispersity_index", "1",
                       "the second cumulant over the first squared")
    v_tem_mean = d.variable("stem-mean-diameter", "mean particle diameter (HAADF-STEM)", "particle_size", "nm",
                            "number-weighted mean of the projected-area-equivalent diameters of the metal cores counted")
    v_tem_sd = d.variable("stem-diameter-sd", "standard deviation of the particle diameters (HAADF-STEM)",
                          "particle_size_spread", "nm", "standard deviation of the number distribution of the diameters")
    v_counted = d.variable("particles-counted", "particles counted", "count", "1",
                           "number of particles whose diameters make the distribution")
    v_xrd = d.variable("xrd-crystallite-size", "crystallite size (XRD)", "crystallite_size", "nm",
                       "coherent-domain size from the fcc (111) reflection, Scherrer equation with K = 0.9")

    def char(key, name, technique, target_sample, at_state, eid, res, **props):
        x = d.node(f"characterization/{key}", "Characterization", name, technique=technique, experiment_kind="physical",
                   result_values=res, evidence=[ev("Table 1", "table", id=eid)], **props)
        d.link("CHARACTERIZES", x, target_sample, state=at_state)
        return x

    def fractions(values, variable, eid, **kw):
        return [V(v, "at%", id=f"{sym.lower()}_fraction", variable=variable, target=el[sym], basis="metals only",
                  evidence_ids=[eid], **kw) for (sym, _), v in zip(metals, values)]

    char("icp", "ICP-OES of the catalyst", "ICP-OES after acid digestion", sample, "as_prepared", "t1_icp",
         fractions((22.4, 24.1, 18.3, 15.8, 19.4), v_bulk, "t1_icp")
         + [V(17.6, "wt%", id="metal_loading", variable=v_loading, target=hea, evidence_ids=["t1_icp"])],
         information_depth="bulk", sampling="ensemble")
    char("xps", "XPS of the catalyst as prepared", "X-ray photoelectron spectroscopy", sample, "as_prepared", "t1_xps",
         fractions((18.9, 33.6, 16.2, 14.1, 17.2), v_surface, "t1_xps"), information_depth="surface", sampling="ensemble",
         observation_mode="ex_situ", transfer="transferred in air")
    working = d.node("state/under-co-oxidation", "CatalystState", "the catalyst under CO oxidation conditions, 473 K",
                     state_kind="working", conditions={"temperature": V(473, "K"), "total_pressure": V(1, "mbar"),
                                                       "co_to_o2": V(1, "1", basis="molar ratio")},
                     evidence=[ev("Figure 5", "figure")])
    d.link("STATE_OF", working, sample)
    nap = char("nap-xps", "Near-ambient-pressure XPS in 1 mbar CO + O2 at 473 K", "near-ambient-pressure XPS", sample,
               "operating", "t1_nap", fractions((15.2, 27.0, 13.3, 31.5, 13.0), v_surface, "t1_nap"),
               information_depth="surface", sampling="ensemble", observation_mode="in_situ", temperature=V(473, "K"),
               atmosphere="1 mbar CO + O2 (1:1)",
               note="the products were not measured during the spectra, so the paper calls it in situ")
    d.link("DETERMINED_BY", working, nap)
    d.link("HAS_PHASE", working, ruox, location="surface", dominance="minority", evidence=[ev("Figure 5", "figure")])
    d.link("HAS_PHASE", working, hea, location="bulk", dominance="majority", evidence=[ev("Figure 5", "figure")])

    # ---- three sizes, three variables: the colloid in the liquid, the metal cores imaged, the coherent domains
    char("dls", "DLS of the colloid", "dynamic light scattering", colloid, "as_prepared", "t2_dls",
         [V(9.4, "nm", id="hydrodynamic_diameter", variable=v_dls, target=hea, evidence_ids=["t2_dls"]),
          V(0.18, "1", id="polydispersity_index", variable=v_pdi, target=hea, evidence_ids=["t2_dls"])],
         temperature=V(298, "K"), conditions={"dispersant": T("ethanol, after a 100-fold dilution")})
    char("stem", "HAADF-STEM of the catalyst", "HAADF-STEM", sample, "as_prepared", "t2_stem",
         [V(3.1, "nm", id="mean_diameter", variable=v_tem_mean, target=hea, evidence_ids=["t2_stem"]),
          V(0.6, "nm", id="diameter_sd", variable=v_tem_sd, target=hea, evidence_ids=["t2_stem"]),
          V(350, "1", id="particles_counted", variable=v_counted, target=hea, evidence_ids=["t2_stem"])],
         observation_mode="ex_situ", information_depth="projection", sampling="single_particle")
    char("xrd", "XRD of the catalyst", "powder X-ray diffraction", sample, "as_prepared", "t2_xrd",
         [V(2.6, "nm", id="crystallite_size", variable=v_xrd, target=hea, evidence_ids=["t2_xrd"])],
         information_depth="bulk", sampling="ensemble")
    return d.finish()


if __name__ == "__main__":
    write_canonical(HERE / "impregnation.json", impregnation())
    write_canonical(HERE / "coprecipitation.json", coprecipitation())
    write_canonical(HERE / "high-entropy-alloy.json", high_entropy_alloy())
