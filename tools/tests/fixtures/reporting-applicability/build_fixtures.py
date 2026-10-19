"""Build the reporting-applicability fixtures (README.md): small synthetic documents, every value invented, whose
catalysis checklist outcome expect.yaml states. tools/tests/test_reporting_applicability.py checks each one.

    python tools/tests/fixtures/reporting-applicability/build_fixtures.py

They reuse the helpers of the evidence examples' builder (domain/examples/scale-catal/evidence-examples/) and pin
the schema version it pins (the head's when built).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _repo() -> Path:
    """The SCALE checkout, searched upward from here and from the working directory (a copy elsewhere runs too)."""
    for base in (HERE, Path.cwd().resolve()):
        for p in (base, *base.parents):
            if (p / "scale-release.yaml").exists() and (p / "releases").is_dir():
                return p
    raise SystemExit("run inside a SCALE repository checkout")


_spec = importlib.util.spec_from_file_location(
    "evidence_examples", _repo() / "domain/examples/scale-catal/evidence-examples/build_examples.py")
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)
V, Doc = ex.V, ex.Doc


class Base:
    """The records every test of a fixture shares: CO oxidation over Pt/Al2O3 in a fixed bed, a light source, a DBD."""

    def __init__(self, d: Doc):
        self.d = d
        co, o2, co2 = (d.species("co", "CO", {"C": 1, "O": 1}), d.species("o2", "O2", {"O": 2}),
                       d.species("co2", "CO2", {"C": 1, "O": 2}))
        self.co = co
        self.rxn = d.reaction("co-oxidation", "2 CO + O2 -> 2 CO2", [(co, "reactant", 2), (o2, "reactant", 1),
                                                                     (co2, "product", 2)])
        cat = d.node("catalyst/pt", "Catalyst", "Pt/Al2O3", nominal_formula="Pt/Al2O3", catalyst_family="metal",
                     evidence=[d.ev("Table 1")])
        self.sample = d.node("sample/pt", "CatalystSample", "Pt/Al2O3 granules", sample_kind="granules",
                             evidence=[d.ev("Table 1")])
        d.link("HAS_FORMULATION", self.sample, cat)
        self.feed = d.feed("co-o2", "CO/O2 in He", [co, o2])
        self.reactor = d.node("instrument/reactor", "Reactor", "Fixed-bed reactor", reactor_kind="fixed_bed")
        self.lamp = d.node("instrument/lamp", "LightSource", "Xe lamp", source_kind="xenon_lamp", spectrum="full arc",
                           evidence=[d.ev("Methods", "text")])
        self.dbd = d.node("instrument/dbd", "PlasmaSource", "Packed-bed DBD", discharge_kind="dielectric_barrier",
                          configuration="in_plasma", evidence=[d.ev("Methods", "text")])
        self.v_light = d.node("variable/illumination", "Variable", "illumination", scale="nominal",
                              categories=["light", "dark"])
        self.v_plasma = d.node("variable/plasma", "Variable", "plasma", scale="nominal", categories=["on", "off"])
        self.v_size = d.node("variable/particle-size", "Variable", "particle size", scale="nominal",
                             categories=["coarse", "fine"])

    def test(self, key, forces=("thermo",), reactor=True, **props):
        """A test with what its driving forces must report, so that only what a case asks beyond them is missing."""
        d = self.d
        props.setdefault("test_kind", "activity")
        if forces is not None:
            props["driving_forces"] = list(forces)
        if forces and "thermo" in forces:
            props.setdefault("temperature", V(180, "°C"))
            props.setdefault("pressure", V(1, "bar", basis="absolute"))
            props.setdefault("temperature_measured_at", "catalyst_bed")
        if forces and "photo" in forces:
            props.setdefault("illumination", "light")
        props.setdefault("experiment_kind", "physical")
        tid = d.node(f"test/{key}", "CatalyticTest", key.replace("-", " "), evidence=[d.ev("Table 2")], **props)
        if props["test_kind"] not in ("equilibrium_estimate", "equilibrium_measurement"):
            d.link("USES_CATALYST", tid, self.sample, state="reduced")
            d.link("OF_REACTION", tid, self.rxn)
            if forces and "thermo" in forces:
                d.link("FED_WITH", tid, self.feed)
                if reactor:
                    d.link("IN_REACTOR", tid, self.reactor)
            if forces and "photo" in forces:
                d.link("ILLUMINATED_BY", tid, self.lamp, geometry="front")
            if forces and "plasma" in forces:
                d.link("USES_PLASMA", tid, self.dbd)
        return tid

    def transport_check(self, key, test, basis, inputs=(), **props):
        d = self.d
        aid = d.node(f"analysis/{key}", "Analysis", key.replace("-", " "), analysis_kind="transport_check",
                     evaluation_basis=basis, method=props.pop("method", "as stated"), verdict="no transport limitation",
                     temperature=V(180, "°C"), evidence=[d.ev("Section S3", "text")], **props)
        for x in (test, *inputs):
            d.link("HAS_INPUT", aid, x, role="data")
        return aid

    def dark_control(self, key, light, matched_at, over="steady_state"):
        d = self.d
        tid = self.test(key, forces=("thermo",), test_kind="control", illumination="dark")
        d.link("DARK_CONTROL_FOR", tid, light, control_kind="negative", differs_in=[self.v_light],
               temperature_matched_by="external_heating", temperature_matched_at=matched_at, temperature_matched_over=over)
        return tid

    def trace(self, key, test):
        d = self.d
        ts = d.node(f"dataset/{key}", "TimeSeries", f"rate over time, {key}", variable="CO2 formation rate",
                    unit="umol/(g*s)", series_kind="instantaneous", availability="not_reported", evidence=[d.ev("Figure 3")])
        d.link("HAS_OUTPUT", test, ts)
        return ts

    def state_after(self, key, test):
        d = self.d
        st = d.node(f"state/{key}", "CatalystState", f"catalyst after {key}", state_kind="post_reaction", regime="steady",
                    evidence=[d.ev("Figure 4")])
        d.link("REACHED_BY", st, test, timing="after")
        ch = d.node(f"characterization/{key}", "Characterization", f"TEM after {key}",
                    technique="transmission electron microscopy", observation_mode="ex_situ", evidence=[d.ev("Figure 4")])
        d.link("DETERMINED_BY", st, ch)
        return st


def applicability(known: bool) -> dict:
    """Tests whose driving forces are stated (known) or are not (absent or empty: unknown), and an equilibrium estimate,
    exempt either way."""
    d = Doc("ex:ra", "Applicability " + ("known" if known else "unknown"), "Applicability fixtures (invented)")
    b = Base(d)
    if known:
        b.test("thermo-stated")
        b.test("other-stated", forces=("other",))
    else:
        b.test("forces-absent", forces=None)
        b.test("forces-empty", forces=())
    b.test("equilibrium", forces=None, test_kind="equilibrium_estimate", experiment_kind="computational")
    return d.finish()


def evidence(found: bool) -> dict:
    """One test per reading the checklist asks evidence for: with that evidence connected (found) or without it, or with
    evidence that falls short (an assertion only, a bulk temperature match, a constant trace for the material)."""
    d = Doc("ex:re", "Connected evidence " + ("found" if found else "missing"), "Evidence fixtures (invented)")
    b = Base(d)
    rate = dict(test_kind="kinetics", interpretations=["intrinsic_kinetics"], conversion=V(5, "%", target=b.co))
    t = b.test("intrinsic-numerical", **rate)
    if found:
        b.transport_check("weisz-prater", t, "numerical", method="Weisz-Prater criterion",
                          results={"weisz_prater_number": V(0.1, "1")})
    t = b.test("intrinsic-experimental", **rate)
    run = b.test("intrinsic-experimental-fine", test_kind="kinetics", conversion=V(5, "%", target=b.co))
    d.link("CONTROL_FOR", run, t, control_kind="reference", differs_in=[b.v_size])
    b.transport_check("particle-size", t, "experimental", inputs=(run,) if found else (),
                      method="rates at two particle sizes")
    t = b.test("intrinsic-high-conversion", **{**rate, "conversion": V(60, "%", target=b.co)})
    b.transport_check("weisz-prater-high-conversion" if found else "asserted", t, "numerical" if found else "asserted",
                      **({"results": {"weisz_prater_number": V(4.0, "1")}} if found else {}))
    b.test("system-performance", reactor=found, interpretations=["system_performance"], conversion=V(95, "%", target=b.co))
    light = dict(forces=("photo", "thermo"), heat_source="light_and_external", light_induced_temperature_rise=V(30, "K"))
    t = b.test("photothermal", interpretations=["photothermal_effect"], **light)
    if found:
        sep = d.node("analysis/thermal-contribution", "ThermalContributionAnalysis", "rate against irradiance",
                     partition_method="intensity_dependence", evidence=[d.ev("Figure 5")])
        d.link("HAS_INPUT", sep, t, role="data")
    t = b.test("nonthermal", interpretations=["nonthermal_light_effect"], **light)
    b.dark_control("nonthermal-dark", t, "illuminated_surface" if found else "catalyst_bed")
    t = b.test("synergy", forces=("plasma",), interpretations=["plasma_catalyst_synergy"], discharge_power=V(15, "W"),
               temperature=V(180, "°C"))
    if found:
        bare = d.node("experiment/plasma-bare", "Experiment", "plasma over the bare support", experiment_kind="physical",
                      evidence=[d.ev("Table 3")])
        d.link("USES_PLASMA", bare, b.dbd)
        d.link("CONTROL_FOR", bare, t, control_kind="negative", differs_in=[b.v_plasma])
        thermal = b.test("synergy-thermal-alone", test_kind="control")
        d.link("CONTROL_FOR", thermal, t, control_kind="negative", differs_in=[b.v_plasma])
    t = b.test("performance-stability", test_kind="stability", interpretations=["performance_stability"],
               time_on_stream=V(100, "h"))
    if found:
        b.trace("performance", t)
    t = b.test("material-stability", test_kind="stability", interpretations=["material_stability"],
               time_on_stream=V(100, "h"))
    b.trace("material", t)                  # a constant trace of performance is there either way
    if found:
        b.state_after("material", t)
    return d.finish()


if __name__ == "__main__":
    for name, doc in (("pass-applicability-known", applicability(True)), ("fail-applicability-unknown", applicability(False)),
                      ("pass-evidence-found", evidence(True)), ("fail-evidence-missing", evidence(False))):
        ex.write_canonical(HERE / f"{name}.json", doc)
        print("wrote", f"{name}.json")
