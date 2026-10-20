"""Build the synthetic state-and-site example of the catalysis domain (all values invented): site populations recorded for
the catalyst state they were counted or observed in, the site counts a turnover frequency is divided by, activity
assignments as claims with their evidence, operando observations with and without the kinetics measured while they ran,
and a measured spectrum, two fits to it and the assignment drawn from one of them.

    python build_examples.py

  sites-and-assignments.json
    Cu/ZnO (batch A) in CO2 hydrogenation to methanol, one invented paper and an invented reply to it
    one specimen, three states        reduced (pretreated), working (220 °C, 30 bar) and after the test, each with its
                                      own sites: 2 % of the exposed Cu atoms are Zn-decorated step sites after reduction,
                                      9 % in the working state, by two measurements; 310 µmol/g of exposed Cu after
                                      reduction and 240 µmol/g after the test, by N2O frontal chromatography (an Analysis
                                      that USES_MODEL the counting model and its assumptions); the state after the test
                                      records no step sites, and inherits none
    five turnover frequencies         of one methanol rate (4.1 mmol/(g h)): per exposed Cu atom (the count after
                                      reduction), per Zn-decorated step site (28 µmol/g, derived from the 9 %), at least
                                      0.038 s-1 per titrated site (the titration gives at most 30 µmol/g), per Cu atom
                                      (every Cu atom taken as a site) and one whose source does not say how it was
                                      calculated (kept as reported; the validator warns)
    a computed state                  a Cu(211) slab with Zn at the step (STATE_OF the model, no specimen), 50 % of its
                                      step-edge Cu atoms Zn-decorated, by DFT and ab initio thermodynamics
    a formulation-level count         the reply's "about 300 µmol/g" of exposed Cu for the formulation after reduction,
                                      from an assumed dispersion, on a state of the Catalyst (no specimen added)
    three assignments                 the ZnOx overlayer, a minority phase of the working state, and its Zn-decorated
                                      steps active for methanol formation (supported by the rate across five reduction
                                      temperatures and by the EXAFS fit); the reply's competing claim that Cu steps
                                      without Zn are the active sites (CONTRADICTS the first); bulk ZnO, the majority
                                      phase, a spectator
    operando observations             Cu K-edge XAS on the same specimen, with the kinetics measured while it ran and
                                      matched to the laboratory reactor; DRIFTS in another cell, only overlapping a run
                                      (the checklist reports the kinetics while characterizing missing)
    spectrum, fits and claim          the measured spectra (a Dataset), a linear combination fit and an EXAFS fit to
                                      them (two Analyses, spectral_fit, with fitted values and limitations) and the
                                      assignment that cites the EXAFS fit
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


def V(value, unit, **kw) -> dict:
    return {"status": "present", "value": value, "unit": unit, **kw}


def sites_and_assignments() -> dict:
    p = "ex:ss"
    doc = {"directed": True, "multigraph": True,
           "graph": {"schema": "scale-catal", "schema_version": HEAD_VERSION, "graph_id": f"{p}/graph",
                     "title": "Site populations by catalyst state, site-normalized rates, activity assignments and operando "
                              "pairings (synthetic)",
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

    paper = node("source/paper", "Source", "Invented paper", kind="article", year=2026,
                 title="Sites of a Cu/ZnO catalyst before, during and after CO2 hydrogenation (invented)")
    reply = node("source/reply", "Source", "Invented reply", kind="article", year=2026,
                 title="Which Cu sites make methanol? A reply (invented)")

    def ev(locator, kind="table", source=paper, **kw):
        return {"source": source, "locator": locator, "kind": kind, **kw}

    def species(key, formula, composition, name=None):
        return node(f"species/{key}", "ChemicalSpecies", name or formula, formula=formula,
                    elemental_composition=composition, charge=0)

    co2, h2 = species("co2", "CO2", {"C": 1, "O": 2}), species("h2", "H2", {"H": 2})
    meoh = species("methanol", "CH3OH", {"C": 1, "H": 4, "O": 1}, name="methanol")
    h2o = species("water", "H2O", {"H": 2, "O": 1})
    rxn = node("reaction/co2-meoh", "Reaction", "CO2 + 3 H2 -> CH3OH + H2O", equation="CO2 + 3 H2 -> CH3OH + H2O",
               balance_status="balanced", direction="reversible")
    for sp, role, coef in ((co2, "reactant", 1), (h2, "reactant", 3), (meoh, "product", 1), (h2o, "product", 1)):
        link("HAS_PARTICIPANT", rxn, sp, role=role, coefficient=coef)
    feed = node("feed/co2-h2", "Feed", "CO2/H2 = 1/3", evidence=[ev("Methods", "text")])
    link("HAS_COMPONENT", feed, co2, role="reactant")
    link("HAS_COMPONENT", feed, h2, role="reactant")

    # ---- the formulation, its phases and its sites
    cat = node("catalyst/cu-zno", "Catalyst", "Cu/ZnO, 40 wt% Cu", nominal_formula="Cu/ZnO", catalyst_family="metal",
               evidence=[ev("Table 1")])
    cu = node("material/cu", "Material", "fcc Cu", formula="Cu", structure_type="fcc", material_family="metal")
    zno = node("material/zno", "Material", "wurtzite ZnO", formula="ZnO", polymorph="wurtzite", material_family="oxide")
    znox = node("material/znox-overlayer", "Material", "ZnOx overlayer on Cu", formula="ZnOx", material_family="oxide",
                crystallinity="not_reported")
    link("HAS_COMPONENT", cat, cu, role="active_phase", fraction=V(40, "wt%"), evidence=[ev("Table 1")])
    link("HAS_COMPONENT", cat, zno, role="promoter", evidence=[ev("Table 1")])
    exposed_cu = node("site/exposed-cu", "ActiveSite", "exposed Cu atoms", site_kind="metal_site",
                      evidence=[ev("Methods", "text")])
    zn_step = node("site/zn-decorated-step", "ActiveSite", "Zn-decorated Cu step site", site_kind="step_edge",
                   proposed_composition="a Cu step edge with a Zn atom from the ZnOx overlayer", evidence=[ev("Figure 5", "figure")])
    cu_step = node("site/cu-step", "ActiveSite", "Cu step site without Zn", site_kind="step_edge",
                   evidence=[ev("Discussion", "text", source=reply)])
    link("LOCATED_ON", exposed_cu, cu)
    link("LOCATED_ON", zn_step, cu)
    link("LOCATED_ON", zn_step, znox)
    link("LOCATED_ON", cu_step, cu)

    # ---- three specimens of batch A, the reactors and the reduction
    def sample(key, name):
        sid = node(f"sample/{key}", "CatalystSample", name, sample_kind="granules", batch_identifier="A",
                   evidence=[ev("Methods", "text")])
        link("HAS_FORMULATION", sid, cat)
        return sid

    s_cell = sample("batch-a-xas-cell", "Cu/ZnO batch A, 5 mg in the XAS flow cell")
    s_lab = sample("batch-a-reactor", "Cu/ZnO batch A, 200 mg in the laboratory reactor")
    s_drifts = sample("batch-a-drifts", "Cu/ZnO batch A, in the DRIFTS cell")
    xas_cell = node("instrument/xas-cell", "Reactor", "Capillary flow cell at the beamline", reactor_kind="flow")
    lab_reactor = node("instrument/lab-reactor", "Reactor", "Laboratory fixed-bed reactor", reactor_kind="fixed_bed")
    drifts_cell = node("instrument/drifts-cell", "Reactor", "DRIFTS reaction cell", reactor_kind="flow")
    reduce = node("treatment/reduction", "Treatment", "Reduction in 5 % H2 at 250 °C, 2 h", treatment_kind="reduction",
                  temperature=V(250, "°C"), evidence=[ev("Methods", "text")])
    link("TREATED_BY", s_cell, reduce, order=1)

    # ---- the tests: the run in the XAS cell, its benchmark in the laboratory reactor, the DRIFTS run
    def variable(key, name, kind, unit):
        return node(f"variable/{key}", "Variable", name, scale="quantitative", quantity_kind=kind, unit=unit)

    v_rate = variable("methanol-rate", "methanol formation rate per catalyst mass", "production_rate", "mmol/(g h)")
    v_tof = variable("tof", "methanol turnover frequency", "turnover_frequency", "s-1")

    def test(key, name, sample_id, reactor, pressure, results, evidence, **props):
        tid = node(f"test/{key}", "CatalyticTest", name, test_kind="activity", driving_forces=["thermo"],
                   experiment_kind="physical", temperature=V(220, "°C"), pressure=V(pressure, "bar", basis="absolute"),
                   time_on_stream=V(10, "h"), temperature_measured_at="catalyst_bed", result_values=results,
                   evidence=evidence, **props)
        link("USES_CATALYST", tid, sample_id, state="reduced")
        link("FED_WITH", tid, feed)
        link("IN_REACTOR", tid, reactor)
        link("OF_REACTION", tid, rxn)
        return tid

    t_lab = test("laboratory-reactor", "CO2 hydrogenation in the laboratory reactor, 220 °C, 30 bar", s_lab, lab_reactor, 30,
                 [V(4.3, "mmol/(g h)", id="methanol_rate", variable=v_rate, target=meoh, evidence_ids=["t3_rate"])],
                 [ev("Table 3", id="t3_rate")])
    t_drifts = test("drifts-cell", "CO2 hydrogenation in the DRIFTS cell, 220 °C, 1 bar", s_drifts, drifts_cell, 1,
                    [V(0.2, "mmol/(g h)", id="methanol_rate", variable=v_rate, target=meoh, evidence_ids=["s4_rate"])],
                    [ev("Supporting information, Figure S4", "figure", id="s4_rate")])

    # ---- the states of the specimen in the XAS cell
    def state(key, name, kind, **props):
        return node(f"state/{key}", "CatalystState", name, state_kind=kind, **props)

    reduced = state("reduced", "reduced, before the reaction", "pretreated", regime="steady",
                    evidence=[ev("Table 2")])
    working = state("working", "working, 220 °C and 30 bar CO2/H2", "working", regime="steady",
                    conditions={"temperature": V(220, "°C"), "total_pressure": V(30, "bar")}, evidence=[ev("Figure 5", "figure")])
    after = state("after-test", "after the test, cooled in H2", "post_reaction", evidence=[ev("Table 2")])
    for st in (reduced, working, after):
        link("STATE_OF", st, s_cell)
    link("REACHED_BY", reduced, reduce, timing="after")

    # the counting: N2O frontal chromatography, and the model that turns an uptake into exposed Cu atoms
    counting = node("model/n2o-counting", "Model", "Exposed Cu from N2O uptake", model_kind="adsorption stoichiometry",
                    assumptions=["N2O oxidizes the exposed Cu atoms only, leaving one O atom per two of them",
                                 "every exposed Cu atom counts once, whatever its site"],
                    evidence=[ev("Methods", "text")])

    def rfc(key, name, at_state):
        x = node(f"characterization/{key}", "Characterization", name, technique="N2O reactive frontal chromatography",
                 observation_mode="in_situ", temperature=V(40, "°C"), evidence=[ev("Methods", "text")])
        link("CHARACTERIZES", x, s_cell, state=at_state)
        a = node(f"analysis/{key}-count", "Analysis", f"{name}: exposed Cu atoms from the N2O uptake", analysis_kind="other",
                 method="two exposed Cu atoms per O atom left by N2O", evidence=[ev("Methods", "text")])
        link("HAS_INPUT", a, x, role="data")
        link("USES_MODEL", a, counting)
        return x, a

    rfc_reduced, count_reduced = rfc("rfc-reduced", "N2O frontal chromatography after reduction", "reduced")
    rfc_after, count_after = rfc("rfc-after-test", "N2O frontal chromatography after the test", "spent")
    co_ir = node("characterization/co-ir-reduced", "Characterization", "CO infrared spectra after reduction, at 25 °C",
                 technique="infrared spectroscopy of adsorbed CO", observation_mode="quasi_in_situ", information_depth="surface",
                 sampling="ensemble", evidence=[ev("Methods", "text")])
    link("CHARACTERIZES", co_ir, s_cell, state="reduced")
    me_ir = node("characterization/me-ir-working", "Characterization",
                 "Modulation-excitation infrared spectra under reaction, CO2 partial pressure pulsed",
                 technique="modulation-excitation infrared spectroscopy", observation_mode="operando",
                 information_depth="surface", sampling="ensemble", evidence=[ev("Methods", "text")])
    link("CHARACTERIZES", me_ir, s_cell, state="operating")
    titration = node("characterization/co2-titration", "Characterization",
                     "CO2 pulse titration in the reaction feed", technique="CO2 pulse titration",
                     observation_mode="in_situ", evidence=[ev("Methods", "text")])
    link("CHARACTERIZES", titration, s_cell, state="operating")
    xas = node("characterization/cu-k-xas", "Characterization", "Cu K-edge XAS under reaction",
               technique="X-ray absorption spectroscopy (Cu K edge)", observation_mode="operando", information_depth="bulk",
               sampling="ensemble", evidence=[ev("Methods", "text")])
    link("CHARACTERIZES", xas, s_cell, state="operating")
    drifts = node("characterization/drifts", "Characterization", "DRIFTS under reaction", technique="DRIFTS",
                  observation_mode="operando", information_depth="surface", sampling="ensemble",
                  evidence=[ev("Supporting information, Figure S4", "figure")])
    link("CHARACTERIZES", drifts, s_drifts, state="operating")
    for st, x in ((reduced, rfc_reduced), (reduced, co_ir), (working, me_ir), (working, xas), (working, titration),
                  (after, rfc_after)):
        link("DETERMINED_BY", st, x)

    share = node("analysis/step-site-inventory", "Analysis", "Zn-decorated step sites per gram from their share",
                 analysis_kind="other", method="the share of Zn-decorated step sites times the exposed Cu atoms counted "
                 "after reduction", evidence=[ev("Table 2")])
    link("HAS_INPUT", share, me_ir, role="data")
    link("HAS_INPUT", share, count_reduced, role="data")

    # the site populations, each on the state it was counted or observed in, each with its own evidence
    link("HAS_SITE", reduced, exposed_cu, status="asserted",
         exposed_metal_count=V(310, "µmol/g", origin="derived", produced_by=count_reduced, uncertainty=15,
                               uncertainty_kind="standard_deviation", replicates=3,
                               definition="exposed Cu atoms from the N2O uptake at 40 °C, two per O atom",
                               evidence_ids=["t2_exposed_reduced"]),
         evidence=[ev("Table 2", id="t2_exposed_reduced")])
    link("HAS_SITE", reduced, zn_step, status="hypothesized",
         population_fraction=V(2, "%", basis="of the exposed Cu atoms", produced_by=co_ir, evidence_ids=["t2_share_reduced"]),
         evidence=[ev("Table 2", id="t2_share_reduced")])
    working_steps = link("HAS_SITE", working, zn_step, status="hypothesized",
                         population_fraction=V(9, "%", basis="of the exposed Cu atoms", produced_by=me_ir, uncertainty=2,
                                               uncertainty_kind="plus_minus_unspecified", evidence_ids=["f5_share"]),
                         site_inventory=V(28, "µmol/g", origin="derived", produced_by=share,
                                          definition="9 % of the 310 µmol/g of exposed Cu counted after reduction",
                                          evidence_ids=["t2_inventory"]),
                         evidence=[ev("Figure 5", "figure", id="f5_share"), ev("Table 2", id="t2_inventory")])
    titrated_steps = link("HAS_SITE", working, zn_step, status="hypothesized",
                          site_inventory=V(30, "µmol/g", bound="upper", produced_by=titration,
                                           definition="CO2 held in the reaction feed; CO2 may also bind sites that are not "
                                                      "Zn-decorated, so the count is at most this",
                                           evidence_ids=["t2_titration"]),
                          evidence=[ev("Table 2", id="t2_titration")])
    link("HAS_SITE", after, exposed_cu, status="asserted",
         exposed_metal_count=V(240, "µmol/g", origin="derived", produced_by=count_after, uncertainty=15,
                               uncertainty_kind="standard_deviation", replicates=3,
                               definition="exposed Cu atoms from the N2O uptake at 40 °C, two per O atom",
                               evidence_ids=["t2_exposed_after"]),
         evidence=[ev("Table 2", id="t2_exposed_after")])
    reduced_count = next(e["id"] for e in doc["links"] if e["type"] == "HAS_SITE" and e["source"] == reduced
                         and e["target"] == exposed_cu)

    # the phases of the working state: abundance is not activity
    link("HAS_PHASE", working, cu, dominance="majority", location="whole_particle", evidence=[ev("Figure 4", "figure")])
    link("HAS_PHASE", working, zno, dominance="majority", location="separate_domain", evidence=[ev("Figure 4", "figure")])
    link("HAS_PHASE", working, znox, dominance="minority", location="overlayer", evidence=[ev("Figure 5", "figure")])
    link("HAS_PHASE", reduced, cu, dominance="majority", location="whole_particle", evidence=[ev("Figure 4", "figure")])
    link("HAS_PHASE", reduced, zno, dominance="majority", location="separate_domain", evidence=[ev("Figure 4", "figure")])

    # ---- the run in the XAS cell and its site-normalized rates (one methanol rate, five denominators)
    def tof(key, value, ev_id, **kw):
        return V(value, "s-1", id=key, variable=v_tof, target=meoh, evidence_ids=[ev_id], **kw)

    t_cell = test("xas-cell", "CO2 hydrogenation in the XAS cell, 220 °C, 30 bar", s_cell, xas_cell, 30, [
        V(4.1, "mmol/(g h)", id="methanol_rate", variable=v_rate, target=meoh, evidence_ids=["t3_rate"]),
        tof("tof_per_exposed_cu", 0.0037, "t3_tof_exposed", basis="per exposed Cu atom, counted after reduction",
            normalized_by={"record": reduced_count, "path": "/exposed_metal_count"}),
        tof("tof_per_step_site", 0.041, "t3_tof_step", basis="per Zn-decorated step site",
            normalized_by={"record": working_steps, "path": "/site_inventory"}),
        tof("tof_per_titrated_site", 0.038, "t3_tof_titrated", bound="lower",
            normalized_by={"record": titrated_steps, "path": "/site_inventory"}),
        tof("tof_per_cu_atom", 0.00018, "t3_tof_atom", basis="per metal atom, every Cu atom taken as a site"),
        tof("tof_unstated", 0.02, "s2_tof"),
    ], [ev("Table 3", id="t3_rate"), ev("Table 3", id="t3_tof_exposed"), ev("Table 3", id="t3_tof_step"),
        ev("Table 3", id="t3_tof_titrated"), ev("Table 3", id="t3_tof_atom"),
        ev("Supporting information, Table S2", id="s2_tof")])
    link("IN_STATE", t_cell, working)
    link("REACHED_BY", working, t_cell, timing="during", elapsed=V(10, "h"))
    link("REACHED_BY", after, t_cell, timing="after")
    link("PRECEDES", reduce, t_cell)
    for x in (me_ir, titration):
        link("DURING", x, t_cell, specimen="same_specimen", timing="simultaneous", kinetics="matched_to_benchmark",
             benchmark=t_lab, evidence=[ev("Methods", "text")])

    # ---- operando XAS with the kinetics measured while it ran; DRIFTS that only overlaps a run
    link("DURING", xas, t_cell, specimen="same_specimen", timing="simultaneous", kinetics="matched_to_benchmark",
         benchmark=t_lab, evidence=[ev("Methods", "text", note="spectra and online GC on one time base; the methanol rate in "
                                                                "the cell within 5 % of the laboratory reactor's")])
    link("DURING", drifts, t_drifts, evidence=[ev("Supporting information, Figure S4", "figure")])

    spectra = node("dataset/cu-k-spectra", "Dataset", "Cu K-edge XANES and EXAFS spectra under reaction",
                   data_kind="spectrum", availability="available", uri="https://example.org/invented/cu-k-spectra")
    references = node("dataset/cu-references", "Dataset", "Reference spectra of Cu foil, Cu2O and CuO", data_kind="spectrum",
                      availability="available", uri="https://example.org/invented/cu-references")
    link("HAS_OUTPUT", xas, spectra)

    def fit(key, name, method, results, limitations, ev_id):
        a = node(f"analysis/{key}", "Analysis", name, analysis_kind="spectral_fit", method=method, limitations=limitations,
                 evidence=[ev("Table 4", id=ev_id)])
        for v in results.values():
            v.update(origin="fitted", produced_by=a, evidence_ids=[ev_id])
        next(x for x in doc["nodes"] if x["id"] == a)["props"]["results"] = results
        link("HAS_INPUT", a, spectra, role="data")
        return a

    lcf = fit("xanes-lcf", "Linear combination fit of the Cu K-edge XANES",
              "linear combination of the Cu foil, Cu2O and CuO references, -20 to +30 eV",
              {"cu0_share": V(92, "%", uncertainty=3, uncertainty_kind="standard_error"),
               "cu1_share": V(8, "%", uncertainty=3, uncertainty_kind="standard_error")},
              "Cu+ in Cu2O and Cu+ at the interface with ZnOx are not told apart by these references; a species below "
              "about a tenth of the Cu atoms is not resolved", "t4_lcf")
    link("HAS_INPUT", lcf, references, role="reference_standard")
    exafs = fit("exafs-first-shell", "First-shell EXAFS fit of the Cu K edge",
                "Cu-Cu and Cu-Zn paths, k 3-11 1/Å, S0^2 held at 0.85 from the Cu foil",
                {"cn_cu_cu": V(10.1, "1", uncertainty=0.5, uncertainty_kind="standard_error"),
                 "cn_cu_zn": V(0.6, "1", uncertainty=0.4, uncertainty_kind="standard_error")},
                "Cu-Zn and Cu-Cu scatter at similar distances; the coordination numbers correlate with the Debye-Waller "
                "factors; a fit with Cu-Cu only is worse but not excluded", "t4_exafs")

    # ---- the assignments: claims with named ABOUT roles and their evidence
    series = node("analysis/rate-against-share", "Analysis",
                  "Methanol rate against the share of Zn-decorated step sites over five reduction temperatures",
                  analysis_kind="statistical", method="linear regression of the methanol rate on the share",
                  results={"r_squared": V(0.97, "1", evidence_ids=["f6_fit"]), "points": V(5, "1", evidence_ids=["f6_fit"])},
                  evidence=[ev("Figure 6", "figure", id="f6_fit")])
    link("HAS_INPUT", series, t_cell, role="data")
    link("HAS_INPUT", series, me_ir, role="data")

    def claim(key, name, statement, source=paper, locator="Discussion", **props):
        return node(f"claim/{key}", "Claim", name, statement=statement, claim_kind="structure_property",
                    claim_status="proposed", inference_type="observational",
                    evidence=[ev(locator, "text", source=source)], **props)

    def about(c, target, role):
        link("ABOUT", c, target, role=role)

    active = claim("znox-steps-active", "ZnOx overlayer and its Zn-decorated Cu steps active for methanol",
                   "In the working state, the ZnOx overlayer, a minority phase, and the Cu steps it decorates are the sites "
                   "active for methanol formation.",
                   scope="Cu/ZnO batch A at 220 °C and 30 bar CO2/H2",
                   limitations="rests on the share of Zn-decorated steps from infrared spectra and on a correlation over "
                               "five reduction temperatures")
    for target, role in ((znox, "active"), (zn_step, "active"), (working, "state"), (rxn, "reaction"), (meoh, "product"),
                         (t_cell, "test")):
        about(active, target, role)
    link("SUPPORTS", series, active, premise_refs=[{"record": series, "path": "/results/r_squared"},
                                                   {"record": t_cell, "path": "/result_values/tof_per_step_site"}],
         warrant="the rate scales with the share of Zn-decorated steps when the share is varied on purpose, and the rate "
                 "per such site stays the same", evidence=[ev("Figure 6", "figure")])
    link("SUPPORTS", exafs, active, premise_refs=[{"record": exafs, "path": "/results/cn_cu_zn"}],
         warrant="Cu-Zn neighbours appear under reaction", evidence=[ev("Table 4")])

    rival = claim("cu-steps-active", "Cu steps without Zn active for methanol (the reply)",
                  "Cu step sites without Zn are the sites active for methanol formation; Zn only adds to their number.",
                  source=reply)
    for target, role in ((cu_step, "active"), (working, "state"), (rxn, "reaction"), (meoh, "product")):
        about(rival, target, role)
    link("CONTRADICTS", rival, active, warrant="the reply reads the rise in rate as more Cu steps, not as Zn at them",
         evidence=[ev("Discussion", "text", source=reply)])
    link("SUPPORTS", reply, rival, warrant="rates of Zn-free Cu catalysts per step site, in the reply's Figure 2",
         evidence=[ev("Figure 2", "figure", source=reply)])

    spectator = claim("zno-spectator", "Bulk ZnO a spectator for methanol",
                      "Bulk ZnO, the majority phase, is a spectator for methanol formation in the working state.",
                      locator="Discussion")
    for target, role in ((zno, "spectator"), (working, "state"), (rxn, "reaction")):
        about(spectator, target, role)

    # ---- a computed state: STATE_OF the model, no specimen
    slab = node("model/cu211-zn", "StructureModel", "Cu(211) slab with Zn at the step edge", representation="periodic_slab",
                composition="Cu with Zn at the step", facet="211", evidence=[ev("Computational methods", "text")])
    dft = node("computation/zn-at-steps", "Computation", "DFT and ab initio thermodynamics of Zn at Cu steps",
               method="DFT (RPBE), ab initio thermodynamics", temperature=V(220, "°C"), pressure=V(30, "bar"),
               evidence=[ev("Computational methods", "text")])
    link("USES_MODEL", dft, slab)
    computed = state("computed-zn-step", "computed: Zn at the Cu(211) step under 220 °C and 30 bar CO2/H2", "working",
                     evidence=[ev("Figure 7", "figure")])      # a research document would say origin computed
    link("STATE_OF", computed, slab)
    link("DETERMINED_BY", computed, dft)
    link("PREDICTS", dft, computed, agreement="partly_agrees", compared_with=working, evidence=[ev("Figure 7", "figure")])
    link("HAS_SITE", computed, zn_step, status="hypothesized",
         population_fraction=V(50, "%", basis="of the step-edge Cu atoms", origin="computed", produced_by=dft,
                               evidence_ids=["f7_share"]),
         site_density=V(3.1, "sites/nm2", origin="computed", produced_by=dft, definition="per nm2 of the (211) surface",
                        evidence_ids=["f7_share"]),
         evidence=[ev("Figure 7", "figure", id="f7_share")])

    # ---- a count the reply gives for the formulation only: a state of the Catalyst, no specimen added
    formulation = state("formulation-reduced", "the formulation after reduction, as the reply gives it", "pretreated",
                        evidence=[ev("Introduction", "text", source=reply)])
    link("STATE_OF", formulation, cat)
    link("HAS_SITE", formulation, exposed_cu, status="asserted",
         exposed_metal_count=V(300, "µmol/g", qualifier="approximate", origin="assumed",
                               definition="from a Cu dispersion of 5 % assumed, not measured", evidence_ids=["r_count"]),
         evidence=[ev("Introduction", "text", source=reply, id="r_count")])

    for e in derive_reported_in(doc):
        e["props"]["origin"] = SYN
        doc["links"].append(e)
    return doc


if __name__ == "__main__":
    write_canonical(HERE / "sites-and-assignments.json", sites_and_assignments())
