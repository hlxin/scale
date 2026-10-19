"""Build the synthetic comparison example of the catalysis domain (all values invented): current densities of CO2
electroreduction on one Ag electrode that differ only in what a scientific comparison must keep apart.

    python build_examples.py

  current-density-comparison.json
    two tests at -0.8 V vs RHE, geometric area      compared and ranked together
    the same numbers vs SHE                          the same potential on another scale: never ranked with them
    an ECSA-normalized test                          normalized by the electrode's measured ECSA (normalized_by), with no
                                                     value-level basis: kept apart from the geometric ones
    a potential converted from Ag/AgCl to RHE        an evidenced conversion (derived, produced_by the conversion), so it
                                                     joins the RHE ranking
    a basis that contradicts its record              basis ECSA, current_normalization geometric_area: flagged, left out
    a normalization not reported                     left out as missing context, never assumed geometric
    a reference scale not reported                   left out as missing context
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


def build() -> dict:
    p = "ex:cmp"
    doc = {"directed": True, "multigraph": True,
           "graph": {"schema": "scale-catal", "schema_version": HEAD_VERSION, "graph_id": f"{p}/graph",
                     "title": "CO2 electroreduction on Ag: current densities that a scientific comparison keeps apart",
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

    src = node("source/paper", "Source", "Invented paper", kind="article", year=2026,
               title="CO2 electroreduction on Ag: comparing current densities (invented)")

    def ev(locator, kind="table"):
        return [{"source": src, "locator": locator, "kind": kind}]

    co2 = node("species/co2", "ChemicalSpecies", "CO2", formula="CO2", elemental_composition={"C": 1, "O": 2}, charge=0)
    co = node("species/co", "ChemicalSpecies", "CO", formula="CO", elemental_composition={"C": 1, "O": 1}, charge=0)
    hp = node("species/proton", "ChemicalSpecies", "H+", formula="H+", elemental_composition={"H": 1}, charge=1)
    e = node("species/electron", "ChemicalSpecies", "e-", formula="e-", elemental_composition={}, charge=-1)
    h2o = node("species/water", "ChemicalSpecies", "H2O", formula="H2O", elemental_composition={"H": 2, "O": 1}, charge=0)
    khco3 = node("species/khco3", "ChemicalSpecies", "KHCO3", formula="KHCO3", elemental_composition={"K": 1, "H": 1, "C": 1, "O": 3},
                 charge=0)
    rxn = node("reaction/co2rr-co", "Reaction", "CO2 + 2 H+ + 2 e- -> CO + H2O", equation="CO2 + 2 H+ + 2 e- -> CO + H2O",
               balance_status="balanced", direction="forward")
    for sp, role, coef in ((co2, "reactant", 1), (hp, "reactant", 2), (e, "reactant", 2), (co, "product", 1), (h2o, "product", 1)):
        link("HAS_PARTICIPANT", rxn, sp, role=role, coefficient=coef)
    cat = node("catalyst/ag", "Catalyst", "Ag nanoparticles", nominal_formula="Ag", catalyst_family="metal", evidence=ev("Table 1"))
    sample = node("sample/ag", "CatalystSample", "Ag nanoparticles, batch 1", sample_kind="powder", evidence=ev("Table 1"))
    link("HAS_FORMULATION", sample, cat)
    ecsa = node("characterization/ecsa", "Characterization", "Double-layer capacitance ECSA", technique="double-layer capacitance",
                evidence=ev("Figure S2", "figure"))
    electrode = node("electrode/ag-on-cp", "Electrode", "Ag on carbon paper", substrate="carbon paper", geometric_area=V(1.0, "cm2"),
                     electrochemically_active_area=V(4.2, "cm2", origin="measured"), ecsa_method="double_layer_capacitance",
                     evidence=ev("Methods", "text"))
    link("CHARACTERIZES", ecsa, sample, state="as_prepared")
    link("HAS_PART", electrode, sample, role="catalyst layer")
    ref = node("instrument/ref", "ReferenceElectrode", "Ag/AgCl reference", reference_type="ag_agcl", filling="saturated KCl")
    el = node("electrolyte/khco3", "Electrolyte", "0.1 M KHCO3", pH=V(6.8, "1"), evidence=ev("Methods", "text"))
    link("HAS_COMPONENT", el, khco3, role="inert", concentration=V(0.1, "mol/L"))
    conversion = node("analysis/she-to-rhe", "Analysis", "Ag/AgCl potentials on the RHE scale", analysis_kind="other",
                      method="E(RHE) = E(Ag/AgCl) + 0.197 V + 0.0591 V x pH, at pH 6.8 and 298 K", temperature=V(298, "K"),
                      evidence=ev("Methods", "text"))

    common = dict(test_kind="activity", driving_forces=["electro"], experiment_kind="physical", control_mode="potentiostatic",
                  ir_compensation="applied", temperature=V(298, "K"))

    def test(rid, name, potential, scale, density, normalization, **kw):
        props = {**common, "electrode_potential": potential, "reference_scale": scale, "current_density": density,
                 "current_normalization": normalization, "evidence": ev("Table 2"), **kw}
        t = node(f"test/{rid}", "CatalyticTest", name, **props)
        link("USES_CATALYST", t, sample, state="as_prepared")
        link("USES_ELECTRODE", t, electrode, role="working")
        link("USES_ELECTRODE", t, ref, role="reference")
        link("IN_ELECTROLYTE", t, el)
        link("OF_REACTION", t, rxn)
        return t

    test("rhe-geo-1", "Ag, -0.8 V vs RHE, per geometric area", V(-0.8, "V"), "rhe", V(-10.2, "mA/cm2"), "geometric_area",
         faradaic_efficiency=[V(79, "%", target=co)], partial_current_density=[V(-8.1, "mA/cm2", target=co)])
    test("rhe-geo-2", "Ag, -0.8 V vs RHE, per geometric area, second electrode", V(-0.8, "V"), "rhe", V(-12.5, "mA/cm2"),
         "geometric_area", faradaic_efficiency=[V(83, "%", target=co)])
    test("she-geo", "Ag, -0.8 V vs SHE, per geometric area (the same numbers on another scale)", V(-0.8, "V"), "she",
         V(-10.2, "mA/cm2"), "geometric_area", faradaic_efficiency=[V(79, "%", target=co)])
    test("rhe-ecsa", "Ag, -0.8 V vs RHE, per ECSA", V(-0.8, "V"), "rhe",
         V(-2.4, "mA/cm2", normalized_by={"record": electrode, "path": "/electrochemically_active_area"}), "ecsa")
    converted = test("agcl-converted", "Ag, -1.2 V vs Ag/AgCl, converted to RHE", V(-0.60, "V", basis="RHE", origin="derived",
                     produced_by=conversion, as_reported="-1.20 V vs Ag/AgCl (sat. KCl); -0.60 V vs RHE by the conversion"),
                     "ag_agcl", V(-4.1, "mA/cm2"), "geometric_area")
    link("HAS_INPUT", conversion, converted, role="data")          # the potential as measured, and the pH it is converted at
    link("HAS_INPUT", conversion, el, role="data")
    test("contradictory", "Ag, -0.9 V vs RHE, basis ECSA but normalized per geometric area", V(-0.9, "V"), "rhe",
         V(-15.0, "mA/cm2", basis="ECSA"), "geometric_area")
    test("normalization-unknown", "Ag, -0.7 V vs RHE, normalization not reported", V(-0.7, "V"), "rhe", V(-6.0, "mA/cm2"),
         "not_reported")
    test("scale-unknown", "Ag, -0.8 V, reference scale not reported", V(-0.8, "V"), "not_reported", V(-9.7, "mA/cm2"),
         "geometric_area")
    for e_ in derive_reported_in(doc):
        e_["props"]["origin"] = SYN
        doc["links"].append(e_)
    return doc


if __name__ == "__main__":
    write_canonical(HERE / "current-density-comparison.json", build())
    print("wrote current-density-comparison.json")
