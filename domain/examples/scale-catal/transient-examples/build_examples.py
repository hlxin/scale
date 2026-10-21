"""Build the synthetic transient example of the catalysis domain (all values invented): tests driven by a program, the
responses they give, what the analyses of those responses find, and kinetic constants fitted to them under two
treatments of the reactor.

    python build_examples.py

  transient-kinetics.json
    an isotope switch        CO oxidation over Pt/CeO2 at 200 °C, 12CO switched to 13CO at steady state with Kr in the
                             new feed (an Operation of time_pattern step, its levels and what t = 0 is); the outlet 13CO2
                             and Kr series with their delay, corrected; an isotopic_transient analysis giving the surface
                             residence time and the amount of the intermediates of CO2
    a concentration          CO oxidation over Pt/CeO2 at 150 °C in a DRIFTS cell, CO switched between 0 and 1 % as a
      modulation             square wave (60 s, 10 periods), the infrared spectra taken during it (operando, one trigger
                             for the valve and the spectrometer); a modulation_excitation analysis giving the phase delays
                             of linear CO on Pt, of gas-phase CO2 and of carbonate on ceria; two claims it supports,
                             linear CO an intermediate and carbonate a spectator
    a pseudo-random          CO2 methanation over Ni/Al2O3 at 320 °C, the CO2 inlet switched between 4 and 8 % in a 63-bit
      binary sequence        sequence of 5 s bits, the generator given; one kinetic model fitted to the responses twice,
                             as plug flow (a profile-likelihood interval) and as a differential reactor (a standard error
                             from the curvature), each stating its rate basis, concentration measure and thermodynamic
                             consistency: the two activation energies of one step, which a comparison shows with their
                             treatments; another step's, which the data do not determine
    a chemical loop          CH4 partial oxidation over an Fe2O3/Al2O3 oxygen carrier at 900 °C, 20 cycles of reduction,
                             purge, reoxidation and purge, each segment with its label and duration
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


def T(text, **kw) -> dict:
    return {"status": "present", "text_value": text, **kw}


def transient_kinetics() -> dict:
    p = "ex:tk"
    doc = {"directed": True, "multigraph": True,
           "graph": {"schema": "scale-catal", "schema_version": HEAD_VERSION, "graph_id": f"{p}/graph",
                     "title": "Tests driven by a program, the analyses of their responses, and kinetic constants fitted "
                              "to them (synthetic)",
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
                 title="Isotopic, modulated and pseudo-random transients over Pt/CeO2, Ni/Al2O3 and an iron oxide carrier "
                       "(invented)")

    def ev(locator, kind="text", **kw):
        return {"source": paper, "locator": locator, "kind": kind, **kw}

    # ---- species and reactions
    def species(key, formula, composition, name=None, charge=0, **props):
        return node(f"species/{key}", "ChemicalSpecies", name or formula, formula=formula,
                    elemental_composition=composition, charge=charge, **props)

    co, o2, co2 = species("co", "CO", {"C": 1, "O": 1}), species("o2", "O2", {"O": 2}), species("co2", "CO2", {"C": 1, "O": 2})
    co13 = species("13co", "CO", {"C": 1, "O": 1}, name="13CO", isotopic_label="13C")
    kr, ar = species("kr", "Kr", {"Kr": 1}), species("ar", "Ar", {"Ar": 1})
    ch4, h2, h2o = species("ch4", "CH4", {"C": 1, "H": 4}), species("h2", "H2", {"H": 2}), species("h2o", "H2O", {"H": 2, "O": 1})
    co_lin = species("co-linear-pt", "CO", {"C": 1, "O": 1}, name="CO adsorbed linearly on Pt (2070 cm-1)")
    carbonate = species("carbonate-ceria", "CO3", {"C": 1, "O": 3}, name="carbonate on CeO2 (1550 cm-1)", charge=-2,
                        species_kind="ion")

    def reaction(key, equation, parts):
        rid = node(f"reaction/{key}", "Reaction", equation, equation=equation, balance_status="balanced",
                   direction="forward")
        for sp, role, coef in parts:
            link("HAS_PARTICIPANT", rid, sp, role=role, coefficient=coef)
        return rid

    co_ox = reaction("co-oxidation", "CO + 1/2 O2 -> CO2", [(co, "reactant", 1), (o2, "reactant", 0.5), (co2, "product", 1)])
    methanation = reaction("co2-methanation", "CO2 + 4 H2 -> CH4 + 2 H2O", [(co2, "reactant", 1), (h2, "reactant", 4),
                                                                            (ch4, "product", 1), (h2o, "product", 2)])
    pox = reaction("ch4-partial-oxidation", "CH4 + 1/2 O2 -> CO + 2 H2", [(ch4, "reactant", 1), (o2, "reactant", 0.5),
                                                                          (co, "product", 1), (h2, "product", 2)])

    def feed(key, name, components):
        fid = node(f"feed/{key}", "Feed", name, evidence=[ev("Methods")])
        for sp in components:
            link("HAS_COMPONENT", fid, sp, role="reactant")
        return fid

    def catalyst(key, name, formula, family):
        cat = node(f"catalyst/{key}", "Catalyst", name, nominal_formula=formula, catalyst_family=family,
                   evidence=[ev("Methods, catalysts")])
        sample = node(f"sample/{key}", "CatalystSample", f"{name}, 150-250 um sieve fraction", sample_kind="granules",
                      evidence=[ev("Methods, catalysts")])
        link("HAS_FORMULATION", sample, cat)
        return sample

    pt = catalyst("pt-ceo2", "1 wt% Pt/CeO2", "Pt/CeO2", "metal")
    ni = catalyst("ni-al2o3", "10 wt% Ni/Al2O3", "Ni/Al2O3", "metal")
    fe = catalyst("fe2o3-al2o3", "Fe2O3/Al2O3 oxygen carrier (60 wt% Fe2O3)", "Fe2O3/Al2O3", "oxide")
    micro = node("instrument/microreactor", "Reactor", "Quartz microreactor, 4 mm i.d.", reactor_kind="fixed_bed",
                 evidence=[ev("Methods, reactors")])
    cell = node("instrument/drifts-cell", "Reactor", "DRIFTS reaction cell with a dome window", reactor_kind="flow",
                evidence=[ev("Methods, reactors")])

    def test(key, name, sample, reactor, rxn, fed, temp, **props):
        tid = node(f"test/{key}", "CatalyticTest", name, test_kind=props.pop("test_kind", "kinetics"),
                   driving_forces=["thermo"], experiment_kind="physical", temperature=V(temp, "°C"),
                   pressure=V(1, "bar", basis="absolute"), temperature_measured_at="catalyst_bed",
                   evidence=[ev(props.pop("locator", "Table 1"), "table")], **props)
        link("USES_CATALYST", tid, sample, state="reduced")
        link("FED_WITH", tid, fed)
        link("IN_REACTOR", tid, reactor)
        link("OF_REACTION", tid, rxn)
        return tid

    def series(key, name, variable, unit, **props):
        return node(f"dataset/{key}", "TimeSeries", name, variable=variable, unit=unit, series_kind="instantaneous",
                    availability="not_reported", evidence=[ev(props.pop("locator", "Figure 2"), "figure")], **props)

    def variable(key, name, kind, unit):
        return node(f"variable/{key}", "Variable", name, scale="quantitative", quantity_kind=kind, unit=unit)

    v_tau = variable("residence-time", "surface residence time", "surface_residence_time", "s")
    v_amount = variable("intermediates", "amount of surface intermediates", "surface_intermediate_amount", "umol/g")
    v_delay = variable("phase-delay", "phase delay behind the stimulus", "phase_delay", "s")
    v_ea = variable("activation-energy", "activation energy of a step", "activation_energy", "kJ/mol")

    # ---- 1. an isotope switch at steady state
    ssitka = test("ssitka-200c", "CO oxidation at 200 °C, 12CO switched to 13CO at steady state", pt, micro, co_ox,
                  feed("co-o2-ar", "1 % CO and 2 % O2 in Ar (0.5 % Kr in the 13CO feed)", [co, co13, o2, ar, kr]), 200,
                  flow_rate=V(50, "mL/min"), conversion=V(6, "%", target=co))
    switch = node("operation/isotope-switch", "Operation", "Switch from 12CO to 13CO at steady state",
                  operation_mode="dynamic", time_pattern="step", varied_quantities=["isotopic label of the CO fed"],
                  levels=[T("12CO"), T("13CO")], program_detail="exact", time_origin="the switch of the four-way valve",
                  total_duration=V(10, "min"), evidence=[ev("Methods, transients")])
    link("HAS_OPERATION", ssitka, switch)
    s_13co2 = series("13co2-response", "outlet 13CO2 (m/z 45), normalized", "13CO2 response, normalized", "1",
                     sampling_interval=V(0.1, "s"), time_resolution=V(0.2, "s"), delay=V(1.1, "s"), delay_corrected=True,
                     time_origin="the switch of the four-way valve")
    s_kr = series("kr-response", "outlet Kr (m/z 84), normalized", "Kr response, normalized", "1",
                  sampling_interval=V(0.1, "s"), time_resolution=V(0.2, "s"), delay=V(1.1, "s"), delay_corrected=True,
                  time_origin="the switch of the four-way valve")
    for s_ in (s_13co2, s_kr):
        link("HAS_OUTPUT", ssitka, s_)
    a_ssitka = node("analysis/ssitka-co2", "Analysis", "Isotopic transient of CO2 formation at 200 °C",
                    analysis_kind="isotopic_transient", temperature=V(200, "°C"),
                    method="the area between the normalized 13CO2 and Kr transients",
                    limitations="assumes one pool of intermediates and no kinetic isotope effect; CO2 readsorbing on ceria "
                                "would lengthen the residence time",
                    evidence=[ev("Table 2", "table", id="t2")],
                    result_values=[
                        {"id": "tau_co2", "status": "present", "value": 1.6, "unit": "s", "variable": v_tau, "target": co2,
                         "evidence_ids": ["t2"]},
                        {"id": "n_co2", "status": "present", "value": 0.9, "unit": "umol/g", "variable": v_amount,
                         "target": co2, "evidence_ids": ["t2"]}])
    for x in (ssitka, s_13co2, s_kr):
        link("HAS_INPUT", a_ssitka, x, role="data")

    # ---- 2. a concentration modulation with the spectra taken during it
    mes = test("modulation-150c", "CO oxidation at 150 °C in the DRIFTS cell, CO modulated", pt, cell, co_ox,
               feed("co-modulated", "CO modulated in 2 % O2 in Ar", [co, o2, ar]), 150, locator="Figure 4")
    square = node("operation/co-square-wave", "Operation", "CO switched between 0 and 1 % as a square wave, 60 s, 10 periods",
                  operation_mode="dynamic", time_pattern="periodic", waveform="square",
                  varied_quantities=["CO mole fraction in the feed"], levels=[V(0, "%"), V(1, "%")], period=V(60, "s"),
                  duty_cycle=V(50, "%"), cycles=10, program_detail="parametric",
                  time_origin="the first switch to CO", evidence=[ev("Methods, transients")])
    link("HAS_OPERATION", mes, square)
    s_ir = series("drifts-spectra", "time-resolved DRIFT spectra", "absorbance", "1", sampling_interval=V(0.5, "s"),
                  time_resolution=V(0.5, "s"), time_origin="the first switch to CO", locator="Figure 4")
    s_co2 = series("co2-outlet", "outlet CO2 (m/z 44)", "CO2 signal", "A", sampling_interval=V(0.2, "s"),
                   delay=V(1.4, "s"), delay_corrected=True, time_origin="the first switch to CO", locator="Figure 4")
    drifts = node("characterization/operando-drifts", "Characterization", "Operando DRIFTS during the CO modulation",
                  technique="diffuse reflectance infrared Fourier transform spectroscopy", observation_mode="operando",
                  evidence=[ev("Figure 4", "figure")])
    link("DURING", drifts, mes, specimen="same_specimen", timing="simultaneous", kinetics="measured",
         synchronization="one trigger starts the valve sequence and the spectrometer; the outlet MS lags by 1.4 s, "
                         "measured with an Ar pulse and removed",
         evidence=[ev("Methods, transients")])
    link("HAS_OUTPUT", drifts, s_ir)
    link("HAS_OUTPUT", mes, s_co2)
    a_mes = node("analysis/phase-sensitive-detection", "Analysis",
                 "Phase-sensitive detection of the spectra and the outlet CO2 at the modulation frequency",
                 analysis_kind="modulation_excitation", temperature=V(150, "°C"),
                 method="demodulation at the fundamental (k = 1); phase angles converted to delays at 1/60 Hz",
                 limitations="delays are behind the CO stimulus; a band that overlaps another shares its phase",
                 evidence=[ev("Figure 5", "figure", id="f5")],
                 result_values=[
                     {"id": "delay_co_linear", "status": "present", "value": 2.0, "unit": "s", "variable": v_delay,
                      "target": co_lin, "definition": "lag of the 2070 cm-1 band behind the stimulus",
                      "evidence_ids": ["f5"]},
                     {"id": "delay_co2", "status": "present", "value": 2.4, "unit": "s", "variable": v_delay,
                      "target": co2, "definition": "lag of gas-phase CO2 behind the stimulus, the line delay removed",
                      "evidence_ids": ["f5"]},
                     {"id": "delay_carbonate", "status": "present", "value": 14.5, "unit": "s", "variable": v_delay,
                      "target": carbonate, "definition": "lag of the 1550 cm-1 band behind the stimulus",
                      "evidence_ids": ["f5"]}])
    for x in (mes, s_ir, s_co2):
        link("HAS_INPUT", a_mes, x, role="data")

    def claim(key, name, statement, **props):
        return node(f"claim/{key}", "Claim", name, statement=statement, claim_kind="mechanism", claim_status="proposed",
                    inference_type="interventional", evidence=[ev("Discussion")], **props)

    intermediate = claim("linear-co-intermediate", "Linearly adsorbed CO on Pt an intermediate of CO2 formation",
                         "Linearly adsorbed CO on Pt is an intermediate of CO2 formation at 150 °C.",
                         scope="Pt/CeO2 at 150 °C, 1 % CO modulated in 2 % O2",
                         limitations="rests on phase delays at one modulation frequency")
    for target, role in ((co_lin, "active"), (co_ox, "reaction"), (co2, "product"), (mes, "test")):
        link("ABOUT", intermediate, target, role=role)
    link("SUPPORTS", a_mes, intermediate,
         premise_refs=[{"record": a_mes, "path": "/result_values/delay_co_linear"},
                       {"record": a_mes, "path": "/result_values/delay_co2"}],
         warrant="the band responds before the product and follows the stimulus", evidence=[ev("Figure 5", "figure")])
    spectator = claim("carbonate-spectator", "Carbonate on ceria a spectator of CO2 formation",
                      "Carbonate on ceria is a spectator of CO2 formation at 150 °C.",
                      scope="Pt/CeO2 at 150 °C, 1 % CO modulated in 2 % O2")
    for target, role in ((carbonate, "spectator"), (co_ox, "reaction"), (co2, "product"), (mes, "test")):
        link("ABOUT", spectator, target, role=role)
    link("SUPPORTS", a_mes, spectator,
         premise_refs=[{"record": a_mes, "path": "/result_values/delay_carbonate"},
                       {"record": a_mes, "path": "/result_values/delay_co2"}],
         warrant="the carbonate band lags the product by 12 s", evidence=[ev("Figure 5", "figure")])

    # ---- 3. a pseudo-random binary sequence and a kinetic model fitted to it twice
    prbs_test = test("methanation-prbs-320c", "CO2 methanation at 320 °C, CO2 inlet in a pseudo-random binary sequence",
                     ni, micro, methanation, feed("h2-co2", "H2/CO2 = 4 in Ar", [co2, h2, ar]), 320, locator="Figure 6")
    prbs = node("operation/co2-sequence", "Operation", "CO2 inlet between 4 and 8 % in a 63-bit sequence of 5 s bits",
                operation_mode="dynamic", time_pattern="programmed", waveform="pseudo_random_binary",
                varied_quantities=["CO2 mole fraction in the feed"], levels=[V(4, "%"), V(8, "%")], sequence_length=63,
                bit_duration=V(5, "s"), cycles=3, program_detail="exact", time_origin="the first bit of the sequence",
                note="the sequence's generator and seed are given in the Supporting Information",
                evidence=[ev("Methods, transients"), ev("Supporting Information, Table S1", "table")])
    link("HAS_OPERATION", prbs_test, prbs)
    s_ch4 = series("ch4-outlet", "outlet CH4 (m/z 15)", "CH4 signal", "A", sampling_interval=V(0.25, "s"),
                   time_resolution=V(0.3, "s"), delay=V(0.8, "s"), delay_corrected=False,
                   time_origin="the first bit of the sequence", locator="Figure 6")
    link("HAS_OUTPUT", prbs_test, s_ch4)
    mech = node("mechanism/methanation-ni", "Mechanism", "CO2 methanation on Ni, four steps",
                mechanism_format="other", evidence=[ev("Methods, kinetic model")])
    link("DESCRIBES_REACTION", mech, methanation)

    def step(key, equation, kind):
        sid = node(f"step/{key}", "ElementaryStep", equation, equation=equation, step_kind=kind, reversible=True,
                   evidence=[ev("Table 3", "table")])
        link("HAS_ELEMENTARY_STEP", mech, sid)
        return sid

    s_diss = step("co2-dissociation", "CO2* + * -> CO* + O*", "surface_reaction")
    s_hyd = step("co-hydrogenation", "CO* + H* -> HCO* + *", "surface_reaction")

    def fit(key, name, reactor_model, values, **props):
        fid = node(f"analysis/{key}", "Analysis", name, analysis_kind="kinetic_fit", reactor_model=reactor_model,
                   rate_basis="per_site", concentration_measure="partial_pressure", thermodynamic_consistency="enforced",
                   temperature=V(320, "°C"), method="weighted least squares on the outlet CH4 and CO2 responses",
                   evidence=[ev("Table 3", "table", id="t3")],
                   result_values=[dict(v, origin="fitted", produced_by=f"{p}/analysis/{key}", evidence_ids=["t3"])
                                  for v in values], **props)
        for x in (prbs_test, s_ch4):
            link("HAS_INPUT", fid, x, role="data")
        link("HAS_INPUT", fid, mech, role="parameter")
        return fid

    def ea(id_, value, target, **kw):
        return {"id": id_, "status": "present", "value": value, "unit": "kJ/mol", "variable": v_ea, "target": target, **kw}

    fit("fit-plug-flow", "The model fitted as plug flow", "plug_flow",
        [ea("ea_co2_dissociation", 92, s_diss, interval_lower=85, interval_upper=99,
            uncertainty_kind="confidence_interval", confidence_level=0.95, interval_method="profile_likelihood",
            identifiability="identifiable"),
         ea("ea_co_hydrogenation", 68, s_hyd, identifiability="practically_unidentifiable",
            note="its profile stays flat above 60 kJ/mol")],
        limitations="the CO hydrogenation barrier is not determined by these responses; H2 adsorption is held at "
                    "equilibrium")
    fit("fit-differential", "The same model fitted as a differential reactor", "differential",
        [ea("ea_co2_dissociation", 78, s_diss, uncertainty=3, uncertainty_kind="standard_error", interval_method="curvature",
            identifiability="identifiable")],
        limitations="treats the bed as one composition although the conversion reaches 30 %")

    # ---- 4. a chemical loop
    loop = test("chemical-loop-900c", "CH4 partial oxidation by chemical looping at 900 °C", fe,
                node("instrument/looping-reactor", "Reactor", "Fixed-bed looping reactor", reactor_kind="fixed_bed",
                     evidence=[ev("Methods, reactors")]),
                pox, feed("ch4-then-air", "5 % CH4 in Ar, then air, alternating", [ch4, o2, ar]), 900,
                test_kind="activity", locator="Figure 7",
                selectivity=V(85, "%", target=co, definition="CO selectivity during the reduction half-cycle, cycles 5-20"))
    cycle = node("operation/looping-cycle", "Operation", "Reduction, purge, reoxidation, purge; 20 cycles",
                 operation_mode="dynamic", time_pattern="periodic", varied_quantities=["the gas fed"],
                 segments=[{"label": T("reduction (5 % CH4 in Ar)"), "duration": V(60, "s")},
                           {"label": T("purge (Ar)"), "duration": V(30, "s")},
                           {"label": T("reoxidation (air)"), "duration": V(45, "s")},
                           {"label": T("purge (Ar)"), "duration": V(30, "s")}],
                 cycles=20, program_detail="exact", time_origin="the start of the first reduction",
                 evidence=[ev("Methods, chemical looping")])
    link("HAS_OPERATION", loop, cycle)

    for e in derive_reported_in(doc):
        e["props"]["origin"] = SYN
        doc["links"].append(e)
    return doc


if __name__ == "__main__":
    write_canonical(HERE / "transient-kinetics.json", transient_kinetics())
    print("wrote transient-kinetics.json")
