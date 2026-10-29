"""Build the synthetic example of syntheses of heterogeneous catalysts by any method (all values invented): what a
preparation is made by (its method families), what it is designed to control and with what strategy, the function
each input serves (synthesis_function), what drives each step (energy_input), steps repeated as one block
(repetitions), stages that are preparations of their own, and the structure obtained (particle shape, architecture,
exposed facets) as a catalyst state the preparation reaches and a characterization determines.

    python build_examples.py

  synthesis-strategies.json   six syntheses, each from its own invented paper
    Pd nanocubes on alumina       colloidal_reduction then colloidal_deposition: Na2PdCl4 reduced by ascorbic acid with
                                  PVP (capping_agent) and KBr (shape_directing_agent); aims particle_shape and
                                  exposed_facets; the colloid's state: cubes, {100}, edge length by TEM; the authors'
                                  claim that Br- on {100} gives the cubes
    Pt on alumina by ALD          atomic_layer_deposition: one block of 10 cycles (repetitions), each a dose of
                                  MeCpPtMe3, a purge, a dose of O2 (co_reactant) and a purge, in order; the purge time not
                                  stated; the platinum deposited per cycle as an outcome
    Cu-SSZ-13                     two stages, each a Preparation PART_OF the whole: hydrothermal crystallization in an
                                  autoclave with TMAdaOH (structure_directing_agent) and NaOH (mineralizer), calcined to
                                  remove it; then two ion exchanges (NH4+, then Cu2+); aims atomic_dispersion and
                                  acid_base_sites
    Fe-N-C single atoms           solvothermal ZIF-8 with Fe(acac)3 inside, 2-methylimidazole as linker, carbon and
                                  nitrogen source, dispersed by ultrasound; pyrolysed, acid leached (etchant) and
                                  pyrolysed again; the authors' claim of FeN4 sites, which two characterizations support
    Ni exsolved from a perovskite solid_state_reaction after milling (mechanical) and exsolution by reduction; aims
                                  metal_support_interaction and stability; particles socketed in the oxide
    Pd/CeO2 by flame spray        flame_spray_pyrolysis: a precursor solution that is solvent and fuel, sprayed into a
                                  flame (energy_input flame) with O2 as dispersion gas; a batch scale stated

  staged-colloid.json         PtCo nanocubes made in one stage and loaded on carbon in another (scale-catal 0.7.7)

  synthesis-conditions.json   the conditions of a step and the quantities of its inputs (scale-catal 0.7.8)
    Pt/SiO2 by SEA at pH 11       strong_electrostatic_adsorption: the stock and the slurry concentration of the Pt
                                  complex, the pH before and after the silica, stirring at 300 rpm; a reduction in
                                  flowing 10 % H2/Ar at 50 sccm (each gas an input, its fraction and its flow), cooled
                                  naturally
    Pt/SiO2 by SEA at pH 9        the same preparation at pH 9, VARIANT_OF the first, varied ph
    CeO2 nanorods                 hydrothermal: NaOH at 6 mol/L and 60 times the Ce by mole (ratio), an autoclave
                                  filled to 80 % and sealed, cooled naturally, washed in ethanol and water 1:1 by
                                  volume, calcined in static air
    CeO2 nanocubes                another paper's recipe "with modifications", crystallized at 453 K: VARIANT_OF the
                                  nanorods' preparation, varied crystallize.temperature
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

    def __init__(self, prefix: str, title: str, version: str = HEAD_VERSION):
        self.p = prefix
        self.doc = {"directed": True, "multigraph": True,
                    "graph": {"schema": "scale-catal", "schema_version": version, "graph_id": f"{prefix}/graph",
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

    def ev(self, locator, kind="text", **kw):
        return {"source": self.paper, "locator": locator, "kind": kind, **kw}

    def source(self, key, title):
        self.paper = self.node(f"source/{key}", "Source", f"Invented paper: {title}", kind="article", year=2026,
                               title=f"{title} (invented)")
        return self.paper

    def species(self, key, formula, composition, name=None, **props):
        return self.node(f"species/{key}", "ChemicalSpecies", name or formula, formula=formula,
                         elemental_composition=composition, **props)

    def material(self, key, name, **props):
        return self.node(f"material/{key}", "Material", name, **props)

    def preparation(self, key, name, methods, method, **props):
        return self.node(f"preparation/{key}", "Preparation", name, preparation_methods=methods, method=method,
                         evidence=[self.ev("Experimental, Synthesis")], **props)

    def step(self, parent, order, key, name, action, inputs=(), outputs=(), **props):
        """A ProcedureStep PART_OF its preparation (or of the step it is a sub-step of), in order, with what it takes
        in and gives out. An input is (target, role, amount, functions[, quantities]): its kernel role, its amount as
        printed, the function it serves in the synthesis, as the source states it, and any of its concentration,
        stock_concentration, fraction, ratio and flow_rate."""
        sid = self.node(f"step/{key}", "ProcedureStep", name, action=action,
                        evidence=props.pop("evidence", None) or [self.ev("Experimental, Synthesis")], **props)
        self.link("PART_OF", sid, parent, order=order)
        for target, role, amount, functions, *more in inputs:
            self.link("HAS_INPUT", sid, target, role=role, **({"amount": amount} if amount else {}),
                      **({"synthesis_function": functions} if functions else {}), **(more[0] if more else {}),
                      evidence=[self.ev("Experimental, Synthesis")])
        for target in outputs:
            self.link("HAS_OUTPUT", sid, target)
        return sid

    def sample(self, key, name, label="Sample", sample_kind="other", **props):
        return self.node(f"sample/{key}", label, name, sample_kind=sample_kind, preparation_status="prepared",
                         evidence=[self.ev("Experimental, Synthesis")], **props)

    def variable(self, key, name, kind, unit, definition):
        return self.node(f"variable/{key}", "Variable", name, scale="quantitative", unit=unit, definition=definition,
                         quantity_kind=kind)

    def characterization(self, key, name, technique, specimen, state, locator, results=(), eid=None, **props):
        x = self.node(f"characterization/{key}", "Characterization", name, technique=technique,
                      experiment_kind="physical", **({"result_values": list(results)} if results else {}),
                      evidence=[self.ev(locator, "figure", **({"id": eid} if eid else {}))], **props)
        self.link("CHARACTERIZES", x, specimen, state=state)
        return x

    def state(self, key, name, of, reached_by, determined_by, locator, eid=None, **props):
        """The structure a preparation gave, as observed: a CatalystState of its output, REACHED_BY the preparation
        (after it) and DETERMINED_BY the characterizations that show it."""
        sid = self.node(f"state/{key}", "CatalystState", name, state_kind="as_prepared",
                        evidence=[self.ev(locator, "figure", **({"id": eid} if eid else {}))], **props)
        self.link("STATE_OF", sid, of)
        self.link("REACHED_BY", sid, reached_by, timing="after")
        for x in determined_by:
            self.link("DETERMINED_BY", sid, x)
        return sid

    def claim(self, key, statement, kind, about, locator, supported_by=()):
        """The authors' reading, never a property of the preparation: a Claim ABOUT it (and the state it concerns),
        which the characterizations it rests on SUPPORT."""
        cid = self.node(f"claim/{key}", "Claim", statement[:60], statement=statement, claim_kind=kind,
                        claim_status="proposed", evidence=[self.ev(locator)])
        for target, role in about:
            self.link("ABOUT", cid, target, role=role)
        for x in supported_by:
            self.link("SUPPORTS", x, cid, evidence=[self.ev(locator)])
        return cid

    def finish(self):
        for e in derive_reported_in(self.doc):
            e["props"]["origin"] = SYN
            self.doc["links"].append(e)
        return self.doc


# ======================================================================================= the six syntheses
def pd_nanocubes(d: Doc) -> None:
    d.source("pd-cubes", "Palladium nanocubes enclosed by {100} facets on alumina for selective hydrogenation")
    pd = d.material("pd-fcc", "fcc palladium", formula="Pd", structure_type="fcc", material_family="metal",
                    crystallinity="crystalline", evidence=[d.ev("Results, XRD")])
    alumina = d.material("gamma-alumina", "gamma-alumina", formula="Al2O3", polymorph="gamma",
                         material_family="oxide", evidence=[d.ev("Experimental, Materials")])
    na2pdcl4 = d.species("na2pdcl4", "Na2PdCl4", {"Na": 2, "Pd": 1, "Cl": 4}, "sodium tetrachloropalladate")
    aa = d.species("ascorbic-acid", "C6H8O6", {"C": 6, "H": 8, "O": 6}, "L-ascorbic acid")
    pvp = d.species("pvp", "(C6H9NO)n", {"C": 6, "H": 9, "N": 1, "O": 1}, "poly(vinylpyrrolidone), Mw 55 000",
                    species_kind="other")
    kbr = d.species("kbr", "KBr", {"K": 1, "Br": 1}, "potassium bromide")
    water = d.species("water", "H2O", {"H": 2, "O": 1}, "water")
    cat = d.node("catalyst/pd-cubes-alumina", "Catalyst", "Pd nanocubes/gamma-Al2O3, 1 wt% Pd (nominal)",
                 catalyst_family="metal", nominal_formula="Pd/Al2O3", evidence=[d.ev("Experimental, Synthesis")])
    d.link("HAS_COMPONENT", cat, pd, role="active_phase", evidence=[d.ev("Experimental, Synthesis")])
    d.link("HAS_COMPONENT", cat, alumina, role="support", evidence=[d.ev("Experimental, Synthesis")])
    batch = d.sample("pd-cubes-alumina", "Pd cubes/Al2O3, batch 1", label="CatalystSample", sample_kind="batch")
    d.link("HAS_FORMULATION", batch, cat)
    colloid = d.sample("pd-cube-colloid", "aqueous colloid of Pd nanocubes")

    prep = d.preparation("pd-cubes", "Pd nanocubes by reduction in water with Br-, deposited on alumina",
                         ["colloidal_reduction", "colloidal_deposition"],
                         "aqueous reduction of Na2PdCl4 by ascorbic acid with PVP and KBr, then deposition on alumina",
                         design_aims=["particle_shape", "exposed_facets", "particle_size"],
                         strategy=("Br- chemisorbed on the growing particles caps the {100} facets, so the particles "
                                    "grow into cubes; PVP keeps the colloid dispersed"),
                         batch_scale=V(11, "mL", definition="volume of colloid made in one run"))
    d.link("HAS_OUTPUT", prep, batch)
    d.step(prep, 1, "pd-cubes-1", "Heat PVP, ascorbic acid and KBr in water", "heat",
           inputs=[(water, "material", V(8, "mL"), ["solvent"]),
                   (pvp, "reagent", V(105, "mg"), ["capping_agent", "stabilizer"]),
                   (aa, "reagent", V(60, "mg"), ["reducing_agent"]),
                   (kbr, "reagent", V(300, "mg"), ["shape_directing_agent"])],
           temperature=V(353, "K"), duration=V(10, "min"), energy_input=["thermal"],
           conditions={"stirring_rate": V(600, "rpm")}, method="in a 20 mL vial in an oil bath, magnetically stirred")
    d.step(prep, 2, "pd-cubes-2", "Add the palladium salt and react", "add",
           inputs=[(na2pdcl4, "reagent", V(57, "mg"), ["metal_precursor"])], outputs=[colloid],
           temperature=V(353, "K"), duration=V(3, "h"), energy_input=["thermal"], atmosphere="air",
           method="3 mL of aqueous Na2PdCl4 added at once")
    d.step(prep, 3, "pd-cubes-3", "Collect by centrifugation and wash", "centrifuge",
           conditions={"centrifugal_speed": V(12000, "rpm"), "washes": V(3, "1")}, duration=V(20, "min"),
           energy_input=["none"])
    d.step(prep, 4, "pd-cubes-4", "Deposit the cubes on the alumina", "deposit",
           inputs=[(colloid, "material", None, None), (alumina, "material", V(0.5, "g"), ["support"])],
           duration=V(12, "h"), temperature=V(298, "K"), energy_input=["none"],
           method="the colloid in ethanol stirred with the support, then filtered")
    d.step(prep, 5, "pd-cubes-5", "Dry", "dry", temperature=V(333, "K"), duration=V(12, "h"), atmosphere="vacuum",
           energy_input=["thermal"])

    edge = d.variable("pd-cube-edge", "edge length of the Pd cubes (TEM)", "particle_edge_length", "nm",
                      "number mean of the edge lengths of the cubes counted")
    edge_sd = d.variable("pd-cube-edge-sd", "standard deviation of the edge lengths (TEM)",
                         "particle_edge_length_spread", "nm", "standard deviation of the number distribution")
    counted = d.variable("pd-cubes-counted", "particles counted (TEM)", "count", "1",
                         "particles whose edge lengths make the distribution")
    tem = d.characterization("pd-cubes-tem", "TEM of the colloid", "transmission electron microscopy", colloid,
                             "as_prepared", "Figure 1a",
                             [V(10.2, "nm", id="edge_length", variable=edge, target=pd, evidence_ids=["f1a"]),
                              V(1.1, "nm", id="edge_length_sd", variable=edge_sd, target=pd, evidence_ids=["f1a"]),
                              V(200, "1", id="counted", variable=counted, target=pd, evidence_ids=["f1a"])],
                             eid="f1a", observation_mode="ex_situ")
    hrtem = d.characterization("pd-cubes-hrtem", "HRTEM of one cube", "high-resolution TEM", colloid, "as_prepared",
                               "Figure 1c", observation_mode="ex_situ", sampling="single_particle")
    st = d.state("pd-cubes", "the colloid as made: Pd cubes bounded by {100}", colloid, prep, [tem, hrtem],
                 "Figure 1", eid="f1a", particle_shape=["cube", "rod"], architecture=["nanoparticles"],
                 exposed_facets=["{100}"], dimensionality="zero_dimensional",
                 morphology="cubes with slightly truncated corners, a few rods",
                 properties={"shape_fraction": V(92, "%", target=pd, definition="share of the particles counted that "
                                                 "are cubes", evidence_ids=["f1a"])})
    d.link("HAS_PHASE", st, pd, location="whole_particle", dominance="majority", evidence=[d.ev("Figure 1c", "figure")])
    d.claim("pd-cubes-br", "Br- adsorbed on {100} lowers its surface energy below that of {111}, so the particles grow as "
            "cubes; without KBr the same synthesis gives cuboctahedra", "mechanism",
            [(prep, "preparation"), (st, "state"), (kbr, "agent")], "Results, Figure 2", supported_by=[tem])


def pt_ald(d: Doc) -> None:
    d.source("pt-ald", "Subnanometre Pt on alumina by a few cycles of atomic layer deposition")
    pt = d.material("pt-fcc", "fcc platinum", formula="Pt", structure_type="fcc", material_family="metal",
                    evidence=[d.ev("Results")])
    alumina = d.material("alumina-ald", "gamma-alumina powder, 150 m2/g", formula="Al2O3", polymorph="gamma",
                         material_family="oxide", evidence=[d.ev("Experimental")])
    mecp = d.species("mecpptme3", "C9H16Pt", {"C": 9, "H": 16, "Pt": 1},
                     "trimethyl(methylcyclopentadienyl)platinum(IV)")
    o2 = d.species("o2", "O2", {"O": 2}, "oxygen")
    n2 = d.species("n2", "N2", {"N": 2}, "nitrogen")
    cat = d.node("catalyst/pt-ald", "Catalyst", "Pt/Al2O3 by 10 ALD cycles", catalyst_family="metal",
                 nominal_formula="Pt/Al2O3", evidence=[d.ev("Experimental")])
    d.link("HAS_COMPONENT", cat, pt, role="active_phase", evidence=[d.ev("Experimental")])
    d.link("HAS_COMPONENT", cat, alumina, role="support", evidence=[d.ev("Experimental")])
    batch = d.sample("pt-ald", "Pt/Al2O3, 10 cycles", label="CatalystSample", sample_kind="powder")
    d.link("HAS_FORMULATION", batch, cat)
    reactor = d.node("instrument/ald-reactor", "Instrument", "viscous-flow ALD reactor with a powder holder",
                     instrument_kind="atomic layer deposition reactor", evidence=[d.ev("Experimental")])

    prep = d.preparation("pt-ald", "Pt by ten ALD cycles on alumina powder", ["atomic_layer_deposition"],
                         "ALD of MeCpPtMe3 and O2 at 573 K",
                         design_aims=["particle_size", "size_distribution"],
                         strategy=("few cycles, so that the Pt nucleates as subnanometre particles before they "
                                    "coalesce"),
                         outcomes={"loading_per_cycle": V(0.35, "wt%", definition="Pt loading by ICP-OES divided by "
                                                          "the number of cycles")})
    d.link("HAS_OUTPUT", prep, batch)
    d.link("USES_INSTRUMENT", prep, reactor, role="actuator")
    d.step(prep, 1, "ald-degas", "Degas the support in the reactor", "heat",
           inputs=[(alumina, "material", V(0.5, "g"), ["support", "substrate"])],
           temperature=V(573, "K"), duration=V(1, "h"), atmosphere="flowing N2", ramp_rate=NOT_STATED,
           energy_input=["thermal"])
    # the block takes in what its cycle uses, with the function each serves; its sub-steps, in order, say what each
    # dose, purge and dose does
    cycle = d.step(prep, 2, "ald-cycle", "One ALD cycle, repeated 10 times", "deposit", repetitions=10,
                   inputs=[(mecp, "reagent", None, ["metal_precursor"]), (o2, "reagent", None, ["co_reactant"])],
                   temperature=V(573, "K"), pressure=V(1, "Torr"), energy_input=["thermal"])
    d.step(cycle, 1, "ald-dose-pt", "Dose MeCpPtMe3", "dose",
           inputs=[(mecp, "reagent", None, ["metal_precursor"])], duration=V(60, "s"),
           conditions={"precursor_temperature": V(343, "K", definition="temperature of the precursor bubbler")})
    d.step(cycle, 2, "ald-purge-1", "Purge", "purge", inputs=[(n2, "reagent", None, ["carrier_gas"])],
           duration=NOT_STATED)
    d.step(cycle, 3, "ald-dose-o2", "Dose O2", "dose", inputs=[(o2, "reagent", None, ["co_reactant"])],
           duration=V(60, "s"))
    d.step(cycle, 4, "ald-purge-2", "Purge", "purge", inputs=[(n2, "reagent", None, ["carrier_gas"])],
           duration=NOT_STATED)

    size = d.variable("pt-ald-size", "mean Pt particle diameter (HAADF-STEM)", "microscopy_particle_size", "nm",
                      "number mean of the projected-area-equivalent diameters")
    stem = d.characterization("pt-ald-stem", "HAADF-STEM after 10 cycles", "HAADF-STEM", batch, "as_prepared",
                              "Figure 2", [V(0.9, "nm", id="mean_diameter", variable=size, target=pt,
                                             evidence_ids=["f2"])], eid="f2", observation_mode="ex_situ")
    d.state("pt-ald", "Pt/Al2O3 after 10 cycles", batch, prep, [stem], "Figure 2",
            architecture=["clusters", "nanoparticles", "supported"], particle_shape=["not_reported"],
            dimensionality="zero_dimensional")


def cu_ssz13(d: Doc) -> None:
    d.source("cu-ssz13", "Isolated Cu2+ ions in SSZ-13 from a direct OSDA route and two ion exchanges")
    cha = d.material("ssz13", "SSZ-13 (CHA), Si/Al 12", formula="SiO2·Al2O3", framework_code="CHA",
                     material_family="zeolite", crystallinity="crystalline", evidence=[d.ev("Results, XRD")])
    silica = d.species("fumed-silica", "SiO2", {"Si": 1, "O": 2}, "fumed silica")
    aloh3 = d.species("aloh3", "Al(OH)3", {"Al": 1, "O": 3, "H": 3}, "aluminium hydroxide")
    tmada = d.species("tmadaoh", "C13H25NO", {"C": 13, "H": 25, "N": 1, "O": 1},
                      "N,N,N-trimethyl-1-adamantylammonium hydroxide (25 wt% in water)")
    naoh = d.species("naoh", "NaOH", {"Na": 1, "O": 1, "H": 1}, "sodium hydroxide")
    water = d.species("water-z", "H2O", {"H": 2, "O": 1}, "water")
    nh4no3 = d.species("nh4no3", "NH4NO3", {"N": 2, "H": 4, "O": 3}, "ammonium nitrate")
    cuno3 = d.species("cuno3", "Cu(NO3)2·3H2O", {"Cu": 1, "N": 2, "O": 9, "H": 6}, "copper(II) nitrate trihydrate")
    cu = d.species("cu", "Cu", {"Cu": 1}, "copper", species_kind="element")
    cat = d.node("catalyst/cu-ssz13", "Catalyst", "Cu-SSZ-13, Cu/Al 0.2 (nominal)", catalyst_family="zeolite",
                 nominal_formula="Cu-SSZ-13", evidence=[d.ev("Experimental")])
    d.link("HAS_COMPONENT", cat, cha, role="support", evidence=[d.ev("Experimental")])
    d.link("HAS_COMPONENT", cat, cu, role="active_component", evidence=[d.ev("Experimental")])
    batch = d.sample("cu-ssz13", "Cu-SSZ-13", label="CatalystSample", sample_kind="powder")
    d.link("HAS_FORMULATION", batch, cat)
    gel = d.sample("ssz13-gel", "synthesis gel, 1 SiO2 : 0.042 Al2O3 : 0.2 TMAdaOH : 0.1 NaOH : 44 H2O")
    na_ssz13 = d.sample("na-ssz13", "Na-SSZ-13 as synthesized, then calcined")
    nh4_ssz13 = d.sample("nh4-ssz13", "NH4-SSZ-13")
    autoclave = d.node("instrument/autoclave", "Instrument", "Teflon-lined stainless-steel autoclave, 45 mL",
                       instrument_kind="autoclave", settings={"volume": V(45, "mL")}, evidence=[d.ev("Experimental")])

    whole = d.preparation("cu-ssz13", "Cu-SSZ-13: hydrothermal synthesis, then two ion exchanges",
                          ["hydrothermal", "ion_exchange"], "direct OSDA synthesis of SSZ-13, NH4+ then Cu2+ exchange",
                          design_aims=["atomic_dispersion", "acid_base_sites"],
                          strategy=("a low Cu loading exchanged into paired Al sites, so that Cu stays as isolated "
                                     "Cu2+ ions"))
    d.link("HAS_OUTPUT", whole, batch)
    zeo = d.preparation("ssz13", "Hydrothermal crystallization of SSZ-13 and removal of the OSDA", ["hydrothermal"],
                        "hydrothermal synthesis with TMAdaOH, then calcination")
    d.link("PART_OF", zeo, whole, order=1)
    d.link("HAS_OUTPUT", zeo, na_ssz13)
    d.link("USES_INSTRUMENT", zeo, autoclave, role="actuator")
    d.step(zeo, 1, "ssz13-gel", "Make the gel", "mix",
           inputs=[(water, "material", V(12, "g"), ["solvent"]), (naoh, "reagent", V(0.6, "g"), ["mineralizer"]),
                   (tmada, "reagent", V(25, "g"), ["structure_directing_agent"]),
                   (aloh3, "reagent", V(0.98, "g"), ["support_precursor"]),
                   (silica, "reagent", V(9, "g"), ["support_precursor"])],
           outputs=[gel], duration=V(2, "h"), temperature=V(298, "K"), energy_input=["none"])
    d.step(zeo, 2, "ssz13-crystallize", "Crystallize in the autoclave", "crystallize",
           inputs=[(gel, "material", None, None)], temperature=V(433, "K"), duration=V(4, "d"),
           pressure=NOT_STATED, energy_input=["thermal"],
           conditions={"fill_fraction": V(70, "%", definition="gel volume over the liner's volume"),
                       "rotation_rate": V(40, "rpm", definition="tumbling of the autoclave in the oven")},
           method="static oven with a tumbling rotisserie; autogenous pressure")
    d.step(zeo, 3, "ssz13-recover", "Filter, wash and dry", "filter", duration=V(12, "h"), temperature=V(373, "K"),
           energy_input=["thermal"])
    d.step(zeo, 4, "ssz13-calcine", "Calcine to remove the OSDA", "calcine", outputs=[na_ssz13],
           temperature=V(823, "K"), duration=V(8, "h"), ramp_rate=V(1, "K/min"), atmosphere="flowing air",
           energy_input=["thermal"])
    exch = d.preparation("cu-exchange", "NH4+ and then Cu2+ ion exchange", ["ion_exchange"],
                         "aqueous ion exchange at 353 K")
    d.link("PART_OF", exch, whole, order=2)
    d.link("HAS_OUTPUT", exch, batch)
    d.step(exch, 1, "nh4-exchange", "Exchange with NH4NO3, twice", "exchange", repetitions=2,
           inputs=[(na_ssz13, "material", V(2, "g"), ["support"]),
                   (nh4no3, "reagent", V(1, "mol/L", definition="concentration of the 100 mL solution"), None)],
           outputs=[nh4_ssz13], temperature=V(353, "K"), duration=V(2, "h"), energy_input=["thermal"])
    d.step(exch, 2, "cu-exchange", "Exchange with Cu(NO3)2", "exchange",
           inputs=[(nh4_ssz13, "material", V(1, "g"), ["support"]),
                   (cuno3, "reagent", V(0.01, "mol/L"), ["metal_precursor"])],
           temperature=V(353, "K"), duration=V(1, "h"), conditions={"ph": V(4.5, "1", definition="pH of the slurry "
                                                                            "during the exchange")},
           energy_input=["thermal"])
    d.step(exch, 3, "cu-calcine", "Calcine", "calcine", temperature=V(823, "K"), duration=V(4, "h"),
           ramp_rate=V(2, "K/min"), atmosphere="static air", energy_input=["thermal"])
    xrd = d.characterization("ssz13-xrd", "XRD of Cu-SSZ-13", "powder X-ray diffraction", batch, "calcined",
                             "Figure 1", information_depth="bulk", sampling="ensemble")
    epr = d.characterization("cu-epr", "EPR of the hydrated catalyst", "electron paramagnetic resonance", batch,
                             "as_prepared", "Figure 3", sampling="ensemble")
    st = d.state("cu-ssz13", "Cu-SSZ-13 as made", batch, whole, [xrd, epr], "Figures 1 and 3",
                 architecture=["framework", "single_atoms"], dimensionality="three_dimensional")
    d.link("HAS_PHASE", st, cha, location="whole_particle", dominance="majority", evidence=[d.ev("Figure 1", "figure")])
    d.claim("cu-isolated", "Cu is present as isolated Cu2+ ions at paired Al sites of the six-membered rings",
            "finding", [(whole, "preparation"), (st, "state")], "Results, Figure 3", supported_by=[epr])


def fe_n_c(d: Doc) -> None:
    d.source("fe-n-c", "Atomically dispersed Fe-N-C from Fe-encapsulating ZIF-8 for oxygen reduction")
    znno3 = d.species("znno3", "Zn(NO3)2·6H2O", {"Zn": 1, "N": 2, "O": 12, "H": 12}, "zinc nitrate hexahydrate")
    mim = d.species("2-mim", "C4H6N2", {"C": 4, "H": 6, "N": 2}, "2-methylimidazole")
    feacac = d.species("feacac3", "Fe(C5H7O2)3", {"Fe": 1, "C": 15, "H": 21, "O": 6}, "iron(III) acetylacetonate")
    meoh = d.species("methanol", "CH3OH", {"C": 1, "H": 4, "O": 1}, "methanol")
    h2so4 = d.species("h2so4", "H2SO4", {"H": 2, "S": 1, "O": 4}, "sulfuric acid")
    zif8 = d.material("zif-8", "ZIF-8 with encapsulated Fe(acac)3", material_family="other", crystallinity="crystalline",
                      evidence=[d.ev("Results, XRD")])
    carbon = d.material("n-carbon", "N-doped carbon", material_family="carbon", crystallinity="amorphous",
                        evidence=[d.ev("Results")])
    fe = d.species("fe", "Fe", {"Fe": 1}, "iron", species_kind="element")
    cat = d.node("catalyst/fe-n-c", "Catalyst", "Fe-N-C, 1.5 wt% Fe (measured)", catalyst_family="carbon",
                 nominal_formula="Fe-N-C", evidence=[d.ev("Experimental")])
    d.link("HAS_COMPONENT", cat, carbon, role="support", evidence=[d.ev("Experimental")])
    d.link("HAS_COMPONENT", cat, fe, role="active_component", evidence=[d.ev("Experimental")])
    batch = d.sample("fe-n-c", "Fe-N-C", label="CatalystSample", sample_kind="powder")
    d.link("HAS_FORMULATION", batch, cat)
    precursor = d.sample("fe-zif8", "Fe(acac)3@ZIF-8 powder")
    d.link("HAS_COMPONENT", precursor, zif8, role="precursor", evidence=[d.ev("Experimental")])
    pyrolysed = d.sample("fe-n-c-1", "Fe-N-C after the first pyrolysis")

    prep = d.preparation("fe-n-c", "Fe-N-C by pyrolysis of Fe(acac)3@ZIF-8", ["solvothermal", "pyrolysis", "etching"],
                         "Fe(acac)3 encapsulated during ZIF-8 growth, pyrolysed, acid leached, pyrolysed again",
                         design_aims=["atomic_dispersion", "porosity"],
                         strategy=("each Fe(acac)3 confined in a ZIF-8 cage, so that on pyrolysis Fe binds N of "
                                    "the carbonizing linker before it can cluster; Zn evaporates and leaves micropores"))
    d.link("HAS_OUTPUT", prep, batch)
    d.step(prep, 1, "zif-solutions", "Dissolve the zinc salt with Fe(acac)3, and the linker, in methanol", "dissolve",
           inputs=[(meoh, "material", V(80, "mL"), ["solvent"]),
                   (znno3, "reagent", V(1.69, "g"), ["support_precursor"]),
                   (feacac, "reagent", V(60, "mg"), ["metal_precursor"]),
                   (mim, "reagent", V(1.97, "g"), ["linker", "carbon_source", "nitrogen_source"])],
           energy_input=["ultrasound"], duration=V(10, "min"),
           conditions={"ultrasound_power": V(100, "W", definition="nominal power of the bath")})
    d.step(prep, 2, "zif-grow", "Grow ZIF-8 around Fe(acac)3", "crystallize", outputs=[precursor],
           temperature=V(333, "K"), duration=V(24, "h"), energy_input=["thermal"])
    d.step(prep, 3, "pyrolysis-1", "Pyrolyse", "pyrolyze", inputs=[(precursor, "material", V(0.5, "g"), None)],
           outputs=[pyrolysed], temperature=V(1173, "K"), duration=V(1, "h"), ramp_rate=V(5, "K/min"),
           atmosphere="flowing Ar", energy_input=["thermal"])
    d.step(prep, 4, "leach", "Leach in acid", "leach",
           inputs=[(pyrolysed, "material", None, None),
                   (h2so4, "reagent", V(0.5, "mol/L"), ["etchant"])],
           temperature=V(353, "K"), duration=V(8, "h"), energy_input=["thermal"])
    d.step(prep, 5, "pyrolysis-2", "Pyrolyse again", "pyrolyze", temperature=V(1173, "K"), duration=V(3, "h"),
           ramp_rate=V(5, "K/min"), atmosphere="flowing Ar", energy_input=["thermal"])
    stem = d.characterization("fe-stem", "Aberration-corrected HAADF-STEM", "HAADF-STEM", batch, "as_prepared",
                              "Figure 2", observation_mode="ex_situ", sampling="single_particle")
    xas = d.characterization("fe-xas", "Fe K-edge EXAFS", "X-ray absorption spectroscopy", batch, "as_prepared",
                             "Figure 3", information_depth="bulk", sampling="ensemble")
    st = d.state("fe-n-c", "Fe-N-C as made", batch, prep, [stem, xas], "Figures 2 and 3",
                 architecture=["single_atoms", "supported"], morphology="polyhedral porous carbon keeping the "
                 "rhombic dodecahedral shape of the ZIF-8 crystals", particle_shape=["rhombic_dodecahedron"])
    d.link("HAS_PHASE", st, carbon, location="whole_particle", dominance="majority", evidence=[d.ev("Figure 2", "figure")])
    d.claim("fe-n4", "Fe is atomically dispersed as FeN4 sites; no Fe-Fe scattering and no Fe particles are seen",
            "finding", [(prep, "preparation"), (st, "state")], "Results, Figures 2 and 3", supported_by=[stem, xas])


def ni_exsolution(d: Doc) -> None:
    d.source("ni-exsolution", "Socketed Ni particles exsolved from a titanate perovskite resist sintering")
    la2o3 = d.species("la2o3", "La2O3", {"La": 2, "O": 3}, "lanthanum oxide")
    srco3 = d.species("srco3", "SrCO3", {"Sr": 1, "C": 1, "O": 3}, "strontium carbonate")
    tio2 = d.species("tio2", "TiO2", {"Ti": 1, "O": 2}, "titanium dioxide")
    nio = d.species("nio", "NiO", {"Ni": 1, "O": 1}, "nickel oxide")
    etoh = d.species("ethanol", "C2H5OH", {"C": 2, "H": 6, "O": 1}, "ethanol")
    perov = d.material("lstn", "La0.4Sr0.4Ti0.94Ni0.06O3", nominal_formula="La0.4Sr0.4Ti0.94Ni0.06O3",
                       structure_type="perovskite", material_family="mixed_oxide", crystallinity="crystalline",
                       evidence=[d.ev("Results, XRD")])
    ni = d.material("ni-fcc", "fcc nickel", formula="Ni", structure_type="fcc", material_family="metal",
                    evidence=[d.ev("Results")])
    cat = d.node("catalyst/ni-lstn", "Catalyst", "Ni exsolved from La0.4Sr0.4Ti0.94Ni0.06O3", catalyst_family="mixed_oxide",
                 nominal_formula="Ni/La0.4Sr0.4Ti0.94Ni0.06O3-d", evidence=[d.ev("Experimental")])
    d.link("HAS_COMPONENT", cat, perov, role="support", evidence=[d.ev("Experimental")])
    d.link("HAS_COMPONENT", cat, ni, role="active_phase", evidence=[d.ev("Experimental")])
    batch = d.sample("ni-lstn", "Ni-exsolved LSTN", label="CatalystSample", sample_kind="powder")
    d.link("HAS_FORMULATION", batch, cat)
    oxide = d.sample("lstn-oxide", "La0.4Sr0.4Ti0.94Ni0.06O3 powder before reduction")

    prep = d.preparation("ni-exsolution", "Perovskite by solid-state reaction, then Ni exsolved by reduction",
                         ["solid_state_reaction", "exsolution"],
                         "ball-milled oxides and carbonate, calcined, then reduced in H2",
                         design_aims=["metal_support_interaction", "stability", "particle_size"],
                         strategy=("A-site deficiency drives Ni out of the B site on reduction, and the particles "
                                    "nucleate in the oxide surface, socketed in it"))
    d.link("HAS_OUTPUT", prep, batch)
    d.step(prep, 1, "mill", "Mill the oxides and carbonate in ethanol", "mill",
           inputs=[(la2o3, "reagent", V(2.17, "g"), ["support_precursor"]),
                   (srco3, "reagent", V(1.97, "g"), ["support_precursor"]),
                   (tio2, "reagent", V(2.50, "g"), ["support_precursor"]),
                   (nio, "reagent", V(0.15, "g"), ["metal_precursor", "dopant_source"]),
                   (etoh, "material", V(20, "mL"), ["solvent"])],
           duration=V(6, "h"), energy_input=["mechanical"],
           conditions={"milling_frequency": V(300, "rpm"), "ball_to_powder_ratio": V(10, "1", basis="mass")},
           method="planetary mill, zirconia jar and balls")
    d.step(prep, 2, "calcine", "Calcine", "calcine", outputs=[oxide], temperature=V(1373, "K"), duration=V(12, "h"),
           ramp_rate=V(5, "K/min"), atmosphere="static air", energy_input=["thermal"])
    d.step(prep, 3, "exsolve", "Reduce to exsolve Ni", "reduce", inputs=[(oxide, "material", V(0.2, "g"), None)],
           temperature=V(1173, "K"), duration=V(10, "h"), ramp_rate=V(5, "K/min"), atmosphere="5 % H2 in Ar, 50 mL/min",
           energy_input=["thermal"])
    size = d.variable("ni-exsolved-size", "mean Ni particle diameter (SEM)", "microscopy_particle_size", "nm",
                      "number mean of the diameters of the surface particles counted")
    sem = d.characterization("ni-sem", "SEM of the reduced surface", "scanning electron microscopy", batch,
                             "reduced", "Figure 2",
                             [V(27, "nm", id="mean_diameter", variable=size, target=ni, evidence_ids=["f2"])],
                             eid="f2", observation_mode="ex_situ")
    st = d.state("ni-lstn", "LSTN after reduction, with exsolved Ni", batch, prep, [sem], "Figure 2",
                 architecture=["nanoparticles", "supported"], particle_shape=["sphere"],
                 morphology="Ni particles partly embedded (socketed) in the perovskite surface")
    d.link("HAS_PHASE", st, ni, location="surface", dominance="minority", evidence=[d.ev("Figure 2", "figure")])
    d.link("HAS_PHASE", st, perov, location="bulk", dominance="majority", evidence=[d.ev("Figure 2", "figure")])
    d.claim("ni-socket", "The socketed Ni particles do not sinter in 100 h at 1073 K, unlike Ni impregnated on the same "
            "oxide", "comparison", [(prep, "preparation"), (st, "state")], "Results, Figure 5", supported_by=[sem])


def pd_ceo2_fsp(d: Doc) -> None:
    d.source("pd-fsp", "Pd/CeO2 in one step by flame spray pyrolysis")
    ce = d.species("ce-ehex", "Ce(C8H15O2)3", {"Ce": 1, "C": 24, "H": 45, "O": 6}, "cerium(III) 2-ethylhexanoate")
    pdacac = d.species("pdacac2", "Pd(C5H7O2)2", {"Pd": 1, "C": 10, "H": 14, "O": 4}, "palladium(II) acetylacetonate")
    xylene = d.species("xylene", "C8H10", {"C": 8, "H": 10}, "xylene")
    o2 = d.species("o2-fsp", "O2", {"O": 2}, "oxygen")
    ceo2 = d.material("ceo2", "fluorite CeO2", formula="CeO2", structure_type="fluorite", material_family="oxide",
                      evidence=[d.ev("Results, XRD")])
    pd = d.species("pd", "Pd", {"Pd": 1}, "palladium", species_kind="element")
    cat = d.node("catalyst/pd-ceo2", "Catalyst", "1 wt% Pd/CeO2 (nominal)", catalyst_family="oxide",
                 nominal_formula="Pd/CeO2", evidence=[d.ev("Experimental")])
    d.link("HAS_COMPONENT", cat, ceo2, role="support", evidence=[d.ev("Experimental")])
    d.link("HAS_COMPONENT", cat, pd, role="active_component", evidence=[d.ev("Experimental")])
    batch = d.sample("pd-ceo2", "Pd/CeO2 (FSP)", label="CatalystSample", sample_kind="powder")
    d.link("HAS_FORMULATION", batch, cat)
    solution = d.sample("fsp-solution", "precursor solution, 0.5 mol/L Ce in xylene")

    prep = d.preparation("pd-fsp", "Pd/CeO2 by flame spray pyrolysis", ["flame_spray_pyrolysis"],
                         "flame spray pyrolysis of Ce and Pd organometallics in xylene",
                         design_aims=["dispersion", "metal_support_interaction"],
                         strategy=("Pd and Ce leave the flame together, so Pd ends up dispersed on and in the ceria"),
                         batch_scale=V(5, "g", definition="powder collected on the filter in one run"))
    d.link("HAS_OUTPUT", prep, batch)
    d.step(prep, 1, "fsp-solution", "Dissolve the precursors in xylene", "dissolve",
           inputs=[(ce, "reagent", V(0.5, "mol/L"), ["support_precursor"]),
                   (pdacac, "reagent", None, ["metal_precursor"]),
                   (xylene, "material", V(100, "mL"), ["solvent", "fuel"])], outputs=[solution],
           energy_input=["none"])
    d.step(prep, 2, "fsp-spray", "Spray into the flame", "spray",
           inputs=[(solution, "material", None, None),
                   (o2, "reagent", V(5, "L/min", definition="dispersion gas flow"), ["oxidizing_agent", "carrier_gas"])],
           energy_input=["flame"],
           conditions={"liquid_feed_rate": V(5, "mL/min"),
                       "pressure_drop": V(1.5, "bar", definition="across the nozzle tip"),
                       "pilot_flame": T("CH4/O2 1.5/3.2 L/min")},
           method="liquid fed through a capillary, dispersed by O2 and ignited by a premixed pilot flame; particles "
                  "collected on a glass-fibre filter")
    xrd = d.characterization("fsp-xrd", "XRD of Pd/CeO2", "powder X-ray diffraction", batch, "as_prepared",
                             "Figure 1", information_depth="bulk", sampling="ensemble")
    d.state("pd-ceo2", "Pd/CeO2 as collected", batch, prep, [xrd], "Figure 1", architecture=["supported"],
            particle_shape=["irregular"], morphology="CeO2 crystals of 5-10 nm with no Pd reflections")


def synthesis_strategies() -> dict:
    d = Doc("ex:syn", version="0.7.6", title="Syntheses of heterogeneous catalysts by any method: methods, aims, the functions of the inputs, "
                      "what drives each step and the structure obtained (synthetic)")
    for build in (pd_nanocubes, pt_ald, cu_ssz13, fe_n_c, ni_exsolution, pd_ceo2_fsp):
        build(d)
    return d.finish()


def staged_colloid() -> dict:
    """A colloid made in one stage and put on carbon in a second, whose ligands are removed (scale-catal 0.7.7): the
    whole lists both stages' families, the colloidal stage holds the surfactant, a step that keeps a temperature
    already reached is a hold, and the ligands come off in a step of their own with the agent that removes them."""
    d = Doc("ex:stg", "A colloid made in one stage and loaded on carbon in another, its ligands removed (synthetic)",
            version="0.7.7")
    d.source("ptco-cubes", "Ordered PtCo nanocubes on carbon from a one-pot colloidal synthesis")
    ptco = d.material("ptco-l10", "ordered L1_0 PtCo", formula="PtCo", structure_type="L1_0", material_family="alloy",
                      crystallinity="crystalline", evidence=[d.ev("Results, XRD")])
    carbon = d.material("carbon-black", "carbon black", formula="C", material_family="carbon",
                        evidence=[d.ev("Experimental")])
    ptacac = d.species("ptacac2", "Pt(C5H7O2)2", {"Pt": 1, "C": 10, "H": 14, "O": 4}, "platinum(II) acetylacetonate")
    coacac = d.species("coacac2", "Co(C5H7O2)2", {"Co": 1, "C": 10, "H": 14, "O": 4}, "cobalt(II) acetylacetonate")
    oam = d.species("oleylamine", "C18H37N", {"C": 18, "H": 37, "N": 1}, "oleylamine")
    top = d.species("top", "C24H51P", {"C": 24, "H": 51, "P": 1}, "trioctylphosphine")
    acetic = d.species("acetic-acid", "C2H4O2", {"C": 2, "H": 4, "O": 2}, "acetic acid")
    ethanol = d.species("ethanol", "C2H6O", {"C": 2, "H": 6, "O": 1}, "ethanol")
    cat = d.node("catalyst/ptco-c", "Catalyst", "PtCo nanocubes/C", catalyst_family="alloy", nominal_formula="PtCo/C",
                 evidence=[d.ev("Experimental")])
    d.link("HAS_COMPONENT", cat, ptco, role="active_phase", evidence=[d.ev("Experimental")])
    d.link("HAS_COMPONENT", cat, carbon, role="support", evidence=[d.ev("Experimental")])
    batch = d.sample("ptco-c", "PtCo/C", label="CatalystSample", sample_kind="powder")
    d.link("HAS_FORMULATION", batch, cat)
    colloid = d.sample("ptco-colloid", "PtCo nanocubes in hexane")

    whole = d.preparation("ptco-c", "PtCo/C: nanocubes made, then loaded on carbon and freed of ligands",
                          ["thermal_decomposition", "colloidal_reduction", "colloidal_deposition"],
                          "one-pot colloidal synthesis, then loading on carbon and ligand removal")
    d.link("HAS_OUTPUT", whole, batch)
    nc = d.preparation("ptco-nanocubes", "PtCo nanocubes in oleylamine", ["thermal_decomposition", "colloidal_reduction"],
                       "decomposition and reduction of the acetylacetonates in oleylamine with TOP",
                       design_aims=["atomic_ordering", "particle_shape"])
    d.link("PART_OF", nc, whole, order=1)
    d.link("HAS_OUTPUT", nc, colloid)
    d.step(nc, 1, "ptco-mix", "Mix the precursors in oleylamine", "mix",
           inputs=[(ptacac, "reagent", V(0.1, "mmol"), ["metal_precursor"]),
                   (coacac, "reagent", V(0.1, "mmol"), ["metal_precursor"]),
                   (oam, "material", V(10, "mL"), ["solvent", "reducing_agent"])], energy_input=["none"])
    d.step(nc, 2, "ptco-top", "Inject TOP", "inject", inputs=[(top, "reagent", V(0.5, "mL"), ["surfactant"])],
           temperature=V(353, "K"))
    d.step(nc, 3, "ptco-heat", "Heat to 523 K", "heat", temperature=V(523, "K"), duration=V(10, "min"),
           ramp_rate=V(10, "K/min"), atmosphere="N2", energy_input=["thermal"])
    d.step(nc, 4, "ptco-hold", "Hold at 523 K", "hold", outputs=[colloid], temperature=V(523, "K"),
           duration=V(30, "min"), atmosphere="N2", energy_input=["thermal"])
    load = d.preparation("ptco-on-carbon", "Loading on carbon and ligand removal", ["colloidal_deposition"],
                         "sonication with carbon, then an acetic-acid soak", design_aims=["surface_ligands"])
    d.link("PART_OF", load, whole, order=2)
    d.link("HAS_OUTPUT", load, batch)
    d.step(load, 1, "ptco-load", "Sonicate with carbon black", "sonicate",
           inputs=[(colloid, "material", V(10, "mg"), None), (carbon, "material", V(40, "mg"), ["support"])],
           duration=V(2, "h"), energy_input=["ultrasound"])
    d.step(load, 2, "ptco-strip", "Soak in acetic acid and ethanol to remove the ligands", "remove_ligands",
           inputs=[(acetic, "reagent", V(10, "mL"), ["ligand_removal_agent"]), (ethanol, "reagent", V(10, "mL"),
                                                                                ["solvent"])],
           temperature=V(343, "K"), duration=V(10, "h"), method="immersion", energy_input=["thermal"])

    xrd = d.characterization("ptco-xrd", "XRD of the nanocubes", "powder X-ray diffraction", colloid, "as_prepared",
                             "Figure 1", information_depth="bulk", sampling="ensemble")
    xas = d.characterization("ptco-xas", "Pt L3-edge EXAFS", "X-ray absorption spectroscopy", colloid, "as_prepared",
                             "Figure 2", information_depth="bulk", sampling="ensemble")
    bond = d.variable("pt-co-bond", "Pt–Co distance (EXAFS fit)", "bond_length", "Å",
                      "first-shell Pt–Co distance from the fit of the Pt L3-edge EXAFS")
    fit = d.node("analysis/ptco-exafs-fit", "Analysis", "Fit of the Pt L3-edge EXAFS", analysis_kind="spectral_fit",
                 method="first-shell fit in R space", limitations="a single Pt–Co path; Pt–Pt held at the foil's value",
                 result_values=[V(2.68, "Å", id="pt_co", variable=bond, target=ptco, origin="fitted",
                                  produced_by="ex:stg/analysis/ptco-exafs-fit", evidence_ids=["t1"])],
                 evidence=[d.ev("Table 1", "table", id="t1")])
    d.link("HAS_INPUT", fit, xas, role="data")
    d.state("ptco", "PtCo nanocubes as made", colloid, nc, [xrd, xas], "Figures 1 and 2", particle_shape=["cube"],
            architecture=["nanoparticles", "intermetallic"], exposed_facets=["{100}"])
    ftir = d.characterization("ptco-ftir", "FTIR before and after the acid soak", "Fourier-transform infrared spectroscopy",
                              batch, "as_prepared", "Figure S3", sampling="ensemble",
                              note="the C-H stretches of oleylamine are gone after the soak")
    d.state("ptco-c", "PtCo/C after the ligands were removed", batch, load, [ftir], "Figure S3",
            architecture=["nanoparticles", "intermetallic", "supported"], particle_shape=["cube"])
    return d.finish()


# ======================================================================================= conditions and quantities
def pt_sea(d: Doc, silica: str, pta: str, nh4oh: str, water: str, h2: str, ar: str, ph: float, key: str) -> str:
    """One Pt/SiO2 preparation by strong electrostatic adsorption at the given pH: the Pt complex as a stock solution
    and at its slurry concentration, the pH set by NH4OH before the silica and read again after, stirred; then dried and
    reduced in flowing H2/Ar, each gas an input with its share and its flow, and cooled naturally under Ar."""
    batch = d.sample(key, f"Pt/SiO2, SEA at pH {ph:g}", label="CatalystSample", sample_kind="powder")
    d.link("HAS_FORMULATION", batch, f"{d.p}/catalyst/pt-silica")
    prep = d.preparation(key, f"Pt/SiO2 by strong electrostatic adsorption at pH {ph:g}",
                         ["strong_electrostatic_adsorption"], f"SEA of Pt(NH3)4 2+ on silica at pH {ph:g}")
    d.link("HAS_OUTPUT", prep, batch)
    d.step(prep, 1, f"{key}-solution", f"Set the water to pH {ph:g} and add the Pt complex", "mix",
           inputs=[(water, "material", V(50, "mL"), ["solvent"]), (nh4oh, "reagent", NOT_STATED, ["ph_modifier"]),
                   (pta, "reagent", V(2.5, "mL"), ["metal_precursor"],
                    {"stock_concentration": V(10, "mM"), "concentration": V(0.5, "mM")})],
           ph=V(ph, "1", definition="pH of the solution before the silica was added"), temperature=V(298, "K"),
           energy_input=["none"])
    d.step(prep, 2, f"{key}-adsorb", "Add the silica and stir", "mix",
           inputs=[(silica, "material", V(1, "g"), ["support"])],
           ph=V(round(ph - 0.2, 1), "1", definition="final pH of the slurry"), agitation="stirred",
           stirring_rate=V(300, "rpm"), duration=V(1, "h"), temperature=V(298, "K"), energy_input=["none"])
    d.step(prep, 3, f"{key}-filter", "Filter", "filter")
    d.step(prep, 4, f"{key}-dry", "Dry", "dry", temperature=V(373, "K"), duration=V(12, "h"), energy_input=["thermal"])
    d.step(prep, 5, f"{key}-reduce", "Reduce in flowing 10 % H2/Ar", "reduce",
           inputs=[(h2, "reagent", None, ["reducing_agent"], {"fraction": V(10, "%", basis="by volume"),
                                                              "flow_rate": V(50, "sccm")}),
                   (ar, "reagent", None, None, {"fraction": V(90, "%", basis="by volume")})],
           temperature=V(573, "K"), ramp_rate=V(5, "K/min"), duration=V(1, "h"), atmosphere="flowing 10% H2/Ar",
           gas_flow_mode="flowing", energy_input=["thermal"])
    d.step(prep, 6, f"{key}-cool", "Cool under Ar", "cool", outputs=[batch],
           inputs=[(ar, "reagent", None, ["protective_gas"])], atmosphere="Ar", gas_flow_mode="flowing",
           cooling_mode="natural", temperature=V(298, "K", definition="the temperature it was cooled to"))
    return prep


def ceo2_hydrothermal(d: Doc, key: str, name: str, temperature: float) -> str:
    """CeO2 by a hydrothermal route: NaOH at its concentration and as a ratio to the Ce, an autoclave filled to 80 % and
    sealed, cooled naturally, washed in ethanol and water mixed by volume, calcined in static air."""
    ce = f"{d.p}/species/ce-nitrate"
    naoh, water, ethanol = f"{d.p}/species/naoh", f"{d.p}/species/water", f"{d.p}/species/ethanol"
    product = d.sample(key, name, sample_kind="powder")
    prep = d.preparation(key, f"{name} by hydrothermal synthesis at {temperature:g} K", ["hydrothermal"],
                         "hydrothermal precipitation in concentrated NaOH, then calcination")
    d.link("HAS_OUTPUT", prep, product)
    d.link("USES_INSTRUMENT", prep, f"{d.p}/instrument/autoclave", role="actuator")
    d.step(prep, 1, f"{key}-mix", "Mix the cerium nitrate and NaOH solutions", "mix",
           inputs=[(ce, "reagent", V(1.96, "g"), ["support_precursor"]),
                   (naoh, "reagent", V(16.8, "g"), ["precipitating_agent"],
                    {"concentration": V(6, "mol/L", definition="NaOH in the mixture"),
                     "ratio": [V(60, "1", target=ce, basis="by mole")]}),
                   (water, "material", V(70, "mL"), ["solvent"])],
           agitation="stirred", stirring_rate=V(500, "rpm"), duration=V(30, "min"), temperature=V(298, "K"),
           energy_input=["none"])
    d.step(prep, 2, f"{key}-crystallize", f"Keep the sealed autoclave at {temperature:g} K", "crystallize",
           temperature=V(temperature, "K"), duration=V(24, "h"), pressure=NOT_STATED,
           fill_fraction=V(80, "%", definition="the mixture's volume over the liner's"), gas_flow_mode="sealed",
           agitation="static", energy_input=["thermal"])
    d.step(prep, 3, f"{key}-cool", "Cool to room temperature", "cool", cooling_mode="natural",
           temperature=V(298, "K", definition="the temperature it was cooled to"))
    d.step(prep, 4, f"{key}-wash", "Wash with ethanol and water, 1:1 by volume", "wash", repetitions=3,
           inputs=[(ethanol, "reagent", None, ["solvent"], {"ratio": [V(1, "1", target=water, basis="by volume")]}),
                   (water, "reagent", None, ["solvent"])])
    d.step(prep, 5, f"{key}-dry", "Dry", "dry", temperature=V(333, "K"), duration=V(12, "h"), energy_input=["thermal"])
    d.step(prep, 6, f"{key}-calcine", "Calcine in static air", "calcine", outputs=[product], temperature=V(773, "K"),
           duration=V(4, "h"), ramp_rate=V(2, "K/min"), atmosphere="static air", gas_flow_mode="static",
           energy_input=["thermal"])
    return prep


def synthesis_conditions() -> dict:
    """The conditions of a step and the quantities of its inputs (scale-catal 0.7.8): pH, stirring, how full a closed
    vessel was, whether the gas flowed, how a step cooled; an input's concentration (in the mixture and as a stock),
    its share of a gas, its ratio to another input and its flow; and a preparation carried out as another with one
    thing changed (VARIANT_OF), within a paper and from another paper's recipe."""
    d = Doc("ex:cnd", "The conditions of a step and the quantities of its inputs, and preparations varied from others "
                      "(synthetic)", version="0.7.8")
    d.source("pt-sea", "Pt on silica by strong electrostatic adsorption: uptake and dispersion against the pH")
    silica = d.material("silica", "amorphous silica, 200 m2/g", formula="SiO2", material_family="oxide",
                        evidence=[d.ev("Experimental")])
    pta = d.species("pta", "Pt(NH3)4(NO3)2", {"Pt": 1, "N": 6, "H": 12, "O": 6}, "tetraammineplatinum(II) nitrate")
    nh4oh = d.species("nh4oh", "NH4OH", {"N": 1, "H": 5, "O": 1}, "ammonium hydroxide")
    water = d.species("water", "H2O", {"H": 2, "O": 1}, "water")
    h2 = d.species("h2", "H2", {"H": 2}, "hydrogen")
    ar = d.species("ar", "Ar", {"Ar": 1}, "argon", species_kind="element")
    pt = d.species("pt", "Pt", {"Pt": 1}, "platinum", species_kind="element")
    cat = d.node("catalyst/pt-silica", "Catalyst", "Pt/SiO2 (nominal 1 wt%)", catalyst_family="metal",
                 nominal_formula="Pt/SiO2", evidence=[d.ev("Experimental")])
    d.link("HAS_COMPONENT", cat, silica, role="support", fraction=V(99, "%", basis="by mass"),
           evidence=[d.ev("Experimental")])
    d.link("HAS_COMPONENT", cat, pt, role="active_component", fraction=V(1, "%", basis="by mass", qualifier="exact"),
           evidence=[d.ev("Experimental")])
    at11 = pt_sea(d, silica, pta, nh4oh, water, h2, ar, 11.0, "pt-sea-11")
    at9 = pt_sea(d, silica, pta, nh4oh, water, h2, ar, 9.0, "pt-sea-9")
    d.link("VARIANT_OF", at9, at11, varied=["ph"], changed="the solution set to pH 9 instead of 11",
           evidence=[d.ev("Experimental, Synthesis")])

    d.source("ceo2-rods", "CeO2 nanorods from a hydrothermal route in concentrated NaOH")
    d.species("ce-nitrate", "Ce(NO3)3·6H2O", {"Ce": 1, "N": 3, "O": 15, "H": 12}, "cerium(III) nitrate hexahydrate")
    d.species("naoh", "NaOH", {"Na": 1, "O": 1, "H": 1}, "sodium hydroxide")
    d.species("ethanol", "C2H6O", {"C": 2, "H": 6, "O": 1}, "ethanol")
    d.node("instrument/autoclave", "Instrument", "Teflon-lined stainless-steel autoclave, 100 mL",
           instrument_kind="autoclave", settings={"volume": V(100, "mL")}, evidence=[d.ev("Experimental")])
    rods = ceo2_hydrothermal(d, "ceo2-rods", "CeO2 nanorods", 373)
    d.source("ceo2-cubes", "CeO2 nanocubes by the nanorod route at a higher temperature")
    cubes = ceo2_hydrothermal(d, "ceo2-cubes", "CeO2 nanocubes", 453)
    d.link("VARIANT_OF", cubes, rods, varied=["crystallize.temperature"],
           changed="prepared as reported for the nanorods, with the hydrothermal temperature raised to 453 K",
           evidence=[d.ev("Experimental, Synthesis")])
    return d.finish()


# ======================================================================================= an anneal in a salt matrix
def salt_matrix_anneal() -> dict:
    """What curating nanoparticle-synthesis recipes asked for (scale-catal 0.7.9): a colloid made with one precursor
    added dropwise and the reductant at once, precipitated with an antisolvent and kept as a dispersion, carried into
    water by a phase-transfer agent, dried in a salt that keeps the particles apart while they are annealed into the
    ordered phase, the salt then washed out, and the powder annealed again as a treatment before it is examined."""
    d = Doc("ex:anl", "A colloid annealed in a salt matrix: dropwise and one-shot additions, an antisolvent, a phase "
                      "transfer and an anneal (synthetic)")
    d.source("ptfe-salt", "Ordered PtFe nanoparticles by annealing colloidal particles in a NaCl matrix")
    ptfe = d.material("ptfe-l10", "ordered L1_0 PtFe", formula="PtFe", structure_type="L1_0", material_family="alloy",
                      crystallinity="crystalline", evidence=[d.ev("Results, XRD")])
    ptacac = d.species("ptacac2", "Pt(C5H7O2)2", {"Pt": 1, "C": 10, "H": 14, "O": 4}, "platinum(II) acetylacetonate")
    feacac = d.species("feacac3", "Fe(C5H7O2)3", {"Fe": 1, "C": 15, "H": 21, "O": 6}, "iron(III) acetylacetonate")
    oam = d.species("oleylamine", "C18H37N", {"C": 18, "H": 37, "N": 1}, "oleylamine")
    hdd = d.species("hdd", "C16H34O2", {"C": 16, "H": 34, "O": 2}, "1,2-hexadecanediol")
    ethanol = d.species("ethanol", "C2H6O", {"C": 2, "H": 6, "O": 1}, "ethanol")
    hexane = d.species("hexane", "C6H14", {"C": 6, "H": 14}, "hexane")
    tmah = d.species("tmah", "C4H13NO", {"C": 4, "H": 13, "N": 1, "O": 1}, "tetramethylammonium hydroxide")
    water = d.species("water", "H2O", {"H": 2, "O": 1}, "water")
    nacl = d.species("nacl", "NaCl", {"Na": 1, "Cl": 1}, "sodium chloride")
    h2 = d.species("h2", "H2", {"H": 2}, "hydrogen")
    ar = d.species("ar", "Ar", {"Ar": 1}, "argon", species_kind="element")
    cat = d.node("catalyst/ptfe", "Catalyst", "PtFe nanoparticles", catalyst_family="alloy", nominal_formula="PtFe",
                 evidence=[d.ev("Experimental")])
    d.link("HAS_COMPONENT", cat, ptfe, role="active_phase", fraction=V(100, "%", basis="by mass"),
           evidence=[d.ev("Experimental")])
    powder = d.sample("ptfe", "PtFe nanoparticles, annealed and washed", label="CatalystSample", sample_kind="powder")
    d.link("HAS_FORMULATION", powder, cat)
    crude = d.sample("ptfe-crude", "PtFe colloid in oleylamine", sample_kind="dispersion")
    in_hexane = d.sample("ptfe-hexane", "PtFe nanoparticles in hexane", sample_kind="dispersion")
    in_water = d.sample("ptfe-water", "PtFe nanoparticles in water", sample_kind="dispersion")
    in_salt = d.sample("ptfe-salt", "PtFe nanoparticles dried in NaCl", sample_kind="powder")
    annealed = d.sample("ptfe-annealed", "PtFe nanoparticles annealed in NaCl", sample_kind="powder")

    whole = d.preparation("ptfe", "PtFe: colloidal particles, then annealed in a salt matrix",
                          ["colloidal_reduction", "other"],
                          "colloidal co-reduction in oleylamine, then an anneal in NaCl and the salt washed out")
    d.link("HAS_OUTPUT", whole, powder)
    colloid = d.preparation("ptfe-colloid", "PtFe nanoparticles in hexane", ["colloidal_reduction"],
                            "reduction of the acetylacetonates by the diol in oleylamine",
                            design_aims=["particle_size", "composition"])
    d.link("PART_OF", colloid, whole, order=1)
    d.link("HAS_OUTPUT", colloid, in_hexane)
    d.step(colloid, 1, "ptfe-mix", "Mix Pt(acac)2 and the diol in oleylamine", "mix",
           inputs=[(ptacac, "reagent", V(0.5, "mmol"), ["metal_precursor"]),
                   (hdd, "reagent", V(2.0, "mmol"), ["reducing_agent"], {"addition_mode": "all_at_once"}),
                   (oam, "material", V(20, "mL"), ["solvent", "capping_agent"])], energy_input=["none"])
    d.step(colloid, 2, "ptfe-add-fe", "Add the Fe(acac)3 solution dropwise at 393 K", "add",
           inputs=[(feacac, "reagent", V(0.5, "mmol"), ["metal_precursor"], {"addition_mode": "dropwise"}),
                   (oam, "material", V(5, "mL"), ["solvent"])], temperature=V(393, "K"))
    d.step(colloid, 3, "ptfe-heat", "Heat to 573 K", "heat", temperature=V(573, "K"), duration=V(36, "min"),
           ramp_rate=V(5, "K/min"), atmosphere="N2", energy_input=["thermal"])
    d.step(colloid, 4, "ptfe-hold", "Hold at 573 K", "hold", outputs=[crude], temperature=V(573, "K"),
           duration=V(1, "h"), atmosphere="N2", energy_input=["thermal"])
    d.step(colloid, 5, "ptfe-precipitate", "Precipitate the particles with ethanol", "precipitate",
           inputs=[(crude, "material", None, None),
                   (ethanol, "reagent", V(40, "mL"), ["antisolvent"], {"addition_mode": "all_at_once"})])
    d.step(colloid, 6, "ptfe-redisperse", "Disperse the particles in hexane", "disperse", outputs=[in_hexane],
           inputs=[(hexane, "material", V(10, "mL"), ["solvent"])])
    size = d.variable("ptfe-size", "mean PtFe particle diameter (TEM)", "microscopy_particle_size", "nm",
                      "number mean of the projected-area-equivalent diameters of 200 particles")
    tem = d.characterization("ptfe-tem", "TEM of the particles in hexane", "transmission electron microscopy",
                             in_hexane, "as_prepared", "Figure 1",
                             [V(4.2, "nm", id="mean_diameter", variable=size, target=ptfe, evidence_ids=["f1"])],
                             eid="f1", observation_mode="ex_situ", sampling="ensemble")
    d.state("ptfe-colloid", "PtFe nanoparticles as made", in_hexane, colloid, [tem], "Figure 1",
            architecture=["nanoparticles", "alloy"], particle_shape=["sphere"])
    anneal = d.preparation("ptfe-salt-anneal", "Annealing the particles in a NaCl matrix", ["other"],
                           "phase transfer into water, drying in NaCl, an anneal under H2/Ar and the salt washed out",
                           design_aims=["atomic_ordering", "particle_size"])
    d.link("PART_OF", anneal, whole, order=2)
    d.link("HAS_INPUT", anneal, in_hexane, role="material", evidence=[d.ev("Experimental, Synthesis")])
    d.link("HAS_OUTPUT", anneal, powder)
    d.step(anneal, 1, "ptfe-transfer", "Carry the particles into water with TMAH", "mix", outputs=[in_water],
           inputs=[(in_hexane, "material", V(10, "mL"), None),
                   (tmah, "reagent", V(1, "mL"), ["phase_transfer_agent"], {"addition_mode": "all_at_once"}),
                   (water, "material", V(10, "mL"), ["solvent"])], method="stirred until the hexane phase is clear")
    d.step(anneal, 2, "ptfe-salt-mix", "Mix the aqueous particles with NaCl", "mix",
           inputs=[(in_water, "material", V(10, "mL"), None),
                   (nacl, "reagent", V(5, "g"), ["isolating_medium"], {"addition_mode": "portionwise"})])
    d.step(anneal, 3, "ptfe-salt-dry", "Dry the mixture", "dry", outputs=[in_salt], temperature=V(353, "K"),
           duration=V(12, "h"))
    d.step(anneal, 4, "ptfe-anneal", "Anneal at 973 K under 5% H2 in Ar", "anneal", outputs=[annealed],
           inputs=[(in_salt, "material", None, None),
                   (h2, "reagent", None, ["reducing_agent"], {"fraction": V(5, "%", basis="by volume")}),
                   (ar, "material", None, ["protective_gas"])],
           temperature=V(973, "K"), duration=V(6, "h"), ramp_rate=V(10, "K/min"), atmosphere="5% H2 in Ar",
           gas_flow_mode="flowing", energy_input=["thermal"])
    d.step(anneal, 5, "ptfe-wash", "Wash out the NaCl with water", "wash",
           inputs=[(annealed, "material", None, None), (water, "material", V(50, "mL"), ["solvent"])])
    d.step(anneal, 6, "ptfe-dry", "Dry the washed particles", "dry", outputs=[powder], temperature=V(333, "K"),
           duration=V(12, "h"))

    treat = d.node("treatment/ptfe-anneal-again", "Treatment", "Annealed again under Ar before examination",
                   treatment_kind="annealing", temperature=V(773, "K"), duration=V(1, "h"), atmosphere="Ar",
                   gas_flow_mode="flowing", evidence=[d.ev("Experimental, Characterization")])
    d.link("TREATED_BY", powder, treat, order=1)
    xrd = d.characterization("ptfe-xrd", "XRD of the annealed particles", "powder X-ray diffraction", powder,
                             "as_prepared", "Figure 2", information_depth="bulk", sampling="ensemble")
    d.state("ptfe", "PtFe nanoparticles after the anneal", powder, anneal, [xrd], "Figure 2",
            architecture=["nanoparticles", "intermetallic", "unsupported"])
    return d.finish()


if __name__ == "__main__":
    write_canonical(HERE / "synthesis-strategies.json", synthesis_strategies())
    write_canonical(HERE / "staged-colloid.json", staged_colloid())
    write_canonical(HERE / "synthesis-conditions.json", synthesis_conditions())
    write_canonical(HERE / "salt-matrix-anneal.json", salt_matrix_anneal())
