"""Build the synthetic Fischer-Tropsch conditions example of the catalysis domain (all values invented; issues #90, #92-#95).

    python build_fts_conditions.py

  fts-conditions.json
    One invented paper on syngas conversion over zeolite-containing catalysts, with what scale-catal added for it:
      three feeds       CO/H2 = 1/2 (printed inverted), CO:H2O = 3:2 (no H2), and a partial-pressure ratio PH2/PCO, each a
                        HAS_COMPONENT.ratio on the edge of its numerator gas (target the denominator, basis stated)
      three reactors    a batch slurry autoclave (reactor_kind slurry, operation_mode batch), a microchannel reactor and a
                        monolith reactor (operation_mode continuous)
      two contact times W/F in g h mol-1 and in g s mL-1, CatalyticTest.space_time, beside a GHSV (a space velocity)
      three acid sites  Bronsted, Lewis, and a total NH3-TPD acidity on a site whose kind is not stated
      pore structure    micropore, mesopore and total pore volumes and mesopore and BET areas, Variables of the declared
                        kinds specific_pore_volume and specific_surface_area, the unit written two ways
The short quotes in the evidence are the wording of the invented paper; the real sources that motivated each term are in
the pull request that added it.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _repo_root(*starts: Path) -> Path:
    for p in (q for s in starts for q in (s, *s.parents)):
        if (p / "scale-release.yaml").exists() and (p / "releases").is_dir():
            return p
    raise SystemExit("run inside a SCALE repository checkout")


HERE = Path(__file__).resolve().parent
REPO = _repo_root(HERE, Path.cwd())
sys.path.insert(0, str(REPO / "tools"))
from scale import layout  # noqa: E402
from scale.pgraph import derive_reported_in  # noqa: E402
from scale.util import write_canonical  # noqa: E402

SYN = "synthetic"
HEAD_VERSION = __import__("yaml").safe_load((REPO / layout.DOMAIN / layout.DOMAIN_GRAPH_MANIFEST).read_text())["version"]
P = "ex:fts"


def V(value, unit, **kw) -> dict:
    return {"status": "present", "value": value, "unit": unit, **kw}


def build() -> dict:
    doc = {"directed": True, "multigraph": True,
           "graph": {"schema": "scale-catal", "schema_version": HEAD_VERSION, "graph_id": f"{P}/graph",
                     "title": "Fischer-Tropsch conditions: feed ratios, reactor kinds, contact time, acid sites, pore structure (invented)",
                     "data_status": "synthetic_example", "follows_domains": ["catalysis"],
                     "stewardship": {"access": "public"}},
           "nodes": [], "links": []}
    n = [0]

    def node(rid, label, name, **props):
        nid = f"{P}/{rid}"
        doc["nodes"].append({"id": nid, "label": label, "props": {"name": name, "origin": SYN, **props}})
        return nid

    def link(typ, s, t, **props):
        n[0] += 1
        doc["links"].append({"id": f"{P}/link/{n[0]}", "source": s, "target": t, "type": typ,
                             "props": {"origin": SYN, **props}})

    src = node("source/paper", "Source", "Invented Fischer-Tropsch paper", kind="article", year=2026,
               title="Syngas conversion over zeolite-containing catalysts (invented)")

    def ev(locator, quote, kind="table", **kw):
        return {"source": src, "locator": locator, "kind": kind, "quote": quote, **kw}

    co = node("species/co", "ChemicalSpecies", "CO", formula="CO", elemental_composition={"C": 1, "O": 1}, charge=0)
    h2 = node("species/h2", "ChemicalSpecies", "H2", formula="H2", elemental_composition={"H": 2}, charge=0)
    h2o = node("species/h2o", "ChemicalSpecies", "H2O", formula="H2O", elemental_composition={"H": 2, "O": 1}, charge=0)
    peg = node("species/peg", "ChemicalSpecies", "PEG-400", formula="HO(C2H4O)nH", charge=0)
    rxn = node("reaction/fts", "Reaction", "n CO + 2n H2 -> (CH2)n + n H2O", equation="n CO + 2n H2 -> (CH2)n + n H2O",
               balance_status="not_checked", direction="forward")
    link("HAS_PARTICIPANT", rxn, co, role="reactant", coefficient=1)
    link("HAS_PARTICIPANT", rxn, h2, role="reactant", coefficient=2)
    cat = node("catalyst/cofe", "Catalyst", "Co on H-ZSM-5", nominal_formula="Co/H-ZSM-5", catalyst_family="metal",
               evidence=[ev("Table 1", "Co/H-ZSM-5")])
    sample = node("sample/cofe", "CatalystSample", "Co on H-ZSM-5, batch 1", sample_kind="powder",
                  evidence=[ev("Table 1", "Co/H-ZSM-5")])
    link("HAS_FORMULATION", sample, cat)

    # ---- the feeds (#90): the ratio sits on the edge of its numerator, the target is the denominator
    f_inv = node("feed/co-h2", "Feed", "CO/H2 = 1/2", ratios={"co_h2_ratio": V(0.5, "1", as_reported="1/2", basis="CO/H2, as printed")},
                 evidence=[ev("Table 2, footnote", "CO/H2 = 1/2")])
    link("HAS_COMPONENT", f_inv, co, role="reactant",
         ratio=[V(0.5, "1", as_reported="1/2", target=h2, basis="mole", evidence_ids=["feed_inv"])],
         evidence=[ev("Table 2, footnote", "CO/H2 = 1/2", id="feed_inv")])
    link("HAS_COMPONENT", f_inv, h2, role="reactant")
    f_wgs = node("feed/co-h2o", "Feed", "CO:H2O = 3:2", evidence=[ev("Methods", "CO:H2O ratio of 3:2", "text")])
    link("HAS_COMPONENT", f_wgs, co, role="reactant",
         ratio=[V(1.5, "1", as_reported="3:2", target=h2o, basis="mole", evidence_ids=["feed_wgs"])],
         evidence=[ev("Methods", "CO:H2O ratio of 3:2", "text", id="feed_wgs")])
    link("HAS_COMPONENT", f_wgs, h2o, role="reactant")
    f_pp = node("feed/ph2-pco", "Feed", "PH2/PCO = 2, with PEG-400 as the liquid",
                evidence=[ev("Results", "PH2/PCO ratio", "text")])
    link("HAS_COMPONENT", f_pp, h2, role="reactant",
         ratio=[V(2, "1", as_reported="PH2/PCO = 2", target=co, basis="partial pressure", evidence_ids=["feed_pp"])],
         evidence=[ev("Results", "PH2/PCO ratio", "text", id="feed_pp")])
    link("HAS_COMPONENT", f_pp, co, role="reactant")
    link("HAS_COMPONENT", f_pp, peg, role="solvent")

    # ---- the reactors (#93)
    r_slurry = node("instrument/slurry", "Reactor", "50-mL slurry autoclave", reactor_kind="slurry", operation_mode="batch",
                    evidence=[ev("Methods", "slurry reactor", "text")])
    r_micro = node("instrument/microchannel", "Reactor", "Microchannel microreactor", reactor_kind="microchannel",
                   operation_mode="continuous", evidence=[ev("Methods", "microchannel microreactor", "text")])
    r_mono = node("instrument/monolith", "Reactor", "Monolith reactor", reactor_kind="monolith",
                  operation_mode="continuous", evidence=[ev("Methods", "monolith reactor", "text")])

    def test(key, name, feed, reactor, quote, **props):
        t = node(f"test/{key}", "CatalyticTest", name, test_kind="activity", driving_forces=["thermo"],
                 experiment_kind="physical", temperature=V(220, "°C"), pressure=V(2, "MPa", basis="absolute"),
                 temperature_measured_at="catalyst_bed", evidence=[ev("Table 2", quote)], **props)
        link("USES_CATALYST", t, sample, state="reduced")
        link("FED_WITH", t, feed)
        link("IN_REACTOR", t, reactor)
        link("OF_REACTION", t, rxn)
        return t

    # ---- the contact times (#94): W/F in two units, beside a GHSV that stays a space velocity
    test("slurry", "Slurry test, contact time in g h mol-1", f_pp, r_slurry, "W/F = 5.1 gcat h mol-1",
         space_time=V(5.1, "g h mol-1", as_reported="5.1 gcat h mol-1", basis="W/F, catalyst mass per molar feed flow",
                      evidence_ids=["wf"]))
    t_micro = test("microchannel", "Microchannel test, contact time per volumetric flow", f_inv, r_micro,
                   "W/F = 0.4 g s mL-1",
                   space_time=V(0.4, "g s mL-1", basis="W/F, catalyst mass per volumetric flow, at STP", evidence_ids=["wf"]),
                   feed_ratio=V(0.5, "1", as_reported="CO/H2 = 1/2", basis="CO/H2, as printed"))
    test("monolith", "Monolith test, a GHSV", f_wgs, r_mono, "GHSV = 3000 h-1",
         space_velocity=V(3000, "h-1", basis="GHSV", evidence_ids=["wf"]))
    for t in doc["nodes"]:
        if t["label"] == "CatalyticTest":
            t["props"]["evidence"].append({"id": "wf", **ev("Table 2", "W/F")})
    del t_micro

    # ---- the acid sites (#92): the kind of site, with a total acidity on a site of a kind not stated
    bas = node("site/bronsted", "ActiveSite", "Bronsted acid site", site_kind="acid_site", acid_type="bronsted",
               proposed_composition="Si-OH-Al bridging hydroxyl", evidence=[ev("Section 3.2", "Bronsted acid sites", "text")])
    las = node("site/lewis", "ActiveSite", "Lewis acid site", site_kind="acid_site", acid_type="lewis",
               proposed_composition="extra-framework aluminium", evidence=[ev("Section 3.2", "extra framework aluminum", "text")])
    total = node("site/acid-total", "ActiveSite", "Acid sites counted by NH3-TPD", site_kind="acid_site",
                 acid_type="not_stated", evidence=[ev("Table 1", "Total Acidity")])
    state = node("state/desilicated", "CatalystState", "after desilication", state_kind="as_prepared")
    link("STATE_OF", state, sample)
    tpd = node("characterization/nh3-tpd", "Characterization", "NH3-TPD", technique="NH3 temperature-programmed desorption",
               experiment_kind="physical", evidence=[ev("Table 1", "NH3-TPD", id="tpd")])
    pyr = node("characterization/pyridine-ir", "Characterization", "Pyridine infrared", technique="pyridine FTIR",
               experiment_kind="physical", evidence=[ev("Section 3.2", "Bronsted acid sites", "text", id="pyr")])
    link("CHARACTERIZES", tpd, sample, state="as_prepared")
    link("CHARACTERIZES", pyr, sample, state="as_prepared")
    link("HAS_SITE", state, total, status="asserted",
         site_density=V(743, "µmol/g", origin="measured", produced_by=tpd, definition="total acidity, sites of both kinds",
                        evidence_ids=["t1_total"]), evidence=[ev("Table 1", "Total Acidity", id="t1_total")])
    link("HAS_SITE", state, bas, status="asserted",
         site_density=V(120, "µmol/g", origin="measured", produced_by=pyr, evidence_ids=["t1_bas"]),
         evidence=[ev("Section 3.2", "Bronsted acid sites", "text", id="t1_bas")])
    link("HAS_SITE", state, las, status="asserted",
         site_density=V(35, "µmol/g", origin="measured", produced_by=pyr, evidence_ids=["t1_las"]),
         evidence=[ev("Section 3.2", "extra framework aluminum", "text", id="t1_las")])

    # ---- the pore structure (#95): the class in the measurand's name, the declared kind and its unit checked
    def var(key, name, kind, unit, definition):
        return node(f"variable/{key}", "Variable", name, scale="quantitative", quantity_kind=kind, unit=unit,
                    definition=definition)

    v_total = var("total-pore-volume", "total_pore_volume", "specific_pore_volume", "cm3/g", "N2 at p/p0 = 0.95")
    v_micro = var("micropore-volume", "micropore_volume", "specific_pore_volume", "cm3/g", "t-plot")
    v_meso = var("mesopore-volume", "mesopore_volume", "specific_pore_volume", "cm3/g", "total pore volume minus the t-plot micropore volume")
    v_bet = var("bet-area", "specific_surface_area", "specific_surface_area", "m2/g", "BET, p/p0 0.05-0.30")
    v_mesoa = var("mesopore-area", "mesopore_surface_area", "specific_surface_area", "m2/g", "t-plot")
    phys = node("characterization/n2-physisorption", "Characterization", "N2 physisorption at 77 K",
                technique="N2 physisorption", experiment_kind="physical", evidence=[ev("Table 1", "Vmicro", id="t1_pore")],
                result_values=[
                    V(0.27, "mL/g", id="vmicro", variable=v_micro, definition="t-plot", evidence_ids=["t1_pore"]),
                    V(0.71, "cm3 g-1", id="vmeso", variable=v_meso, evidence_ids=["t1_pore"]),
                    V(0.98, "cm3/g", id="vtotal", variable=v_total, evidence_ids=["t1_pore"]),
                    V(640, "m2/g", id="sbet", variable=v_bet, evidence_ids=["t1_pore"]),
                    V(210, "m2 g-1", id="smeso", variable=v_mesoa, evidence_ids=["t1_pore"])])
    link("CHARACTERIZES", phys, sample, state="as_prepared")

    for e in derive_reported_in(doc):
        e["props"]["origin"] = SYN
        doc["links"].append(e)
    return doc


if __name__ == "__main__":
    write_canonical(HERE / "fts-conditions.json", build())
    print("wrote fts-conditions.json")
