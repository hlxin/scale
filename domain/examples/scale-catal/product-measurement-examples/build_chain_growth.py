"""Build the synthetic chain-growth-probability example of the catalysis domain (all values invented; issue #108).

    python build_chain_growth.py

  chain-growth-probability.json
    Three Fischer-Tropsch tests that each report an Anderson-Schulz-Flory chain-growth probability alpha, obtained or
    counted differently, so that no two are one quantity:
      a fit test        alpha from the slope of ln(W_n/n) against n over C14-C21, weight basis
      a mole-fit test   alpha from the slope of ln(x_n) against n over C5-C10, mole basis
      a lumped test     alpha computed from the lumped C2-C4 and C2+ selectivities (no fit, no carbon range)
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
P = "ex:cg"


def V(value, unit, **kw) -> dict:
    return {"status": "present", "value": value, "unit": unit, **kw}


def build() -> dict:
    doc = {"directed": True, "multigraph": True,
           "graph": {"schema": "scale-catal", "schema_version": HEAD_VERSION, "graph_id": f"{P}/graph",
                     "title": "Chain-growth probability: how alpha was obtained (invented)",
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
               title="Chain-growth probabilities obtained in three ways (invented)")

    def ev(locator, kind="table", **kw):
        return {"source": src, "locator": locator, "kind": kind, **kw}

    co = node("species/co", "ChemicalSpecies", "CO", formula="CO", elemental_composition={"C": 1, "O": 1}, charge=0)
    h2 = node("species/h2", "ChemicalSpecies", "H2", formula="H2", elemental_composition={"H": 2}, charge=0)
    v_alpha = node("variable/alpha", "Variable", "chain-growth probability", scale="quantitative",
                   quantity_kind="chain_growth_probability", unit="1")
    rxn = node("reaction/fts", "Reaction", "n CO + 2n H2 -> (CH2)n + n H2O", equation="n CO + 2n H2 -> (CH2)n + n H2O",
               balance_status="not_checked", direction="forward")
    link("HAS_PARTICIPANT", rxn, co, role="reactant", coefficient=1)
    link("HAS_PARTICIPANT", rxn, h2, role="reactant", coefficient=2)
    cat = node("catalyst/co", "Catalyst", "Co on titania", nominal_formula="Co/TiO2", catalyst_family="metal",
               evidence=[ev("Table 1")])
    sample = node("sample/co", "CatalystSample", "Co on titania, batch 1", sample_kind="powder", evidence=[ev("Table 1")])
    link("HAS_FORMULATION", sample, cat)
    feed = node("feed/syngas", "Feed", "H2/CO = 2", evidence=[ev("Methods", "text")])
    link("HAS_COMPONENT", feed, co, role="reactant")
    link("HAS_COMPONENT", feed, h2, role="reactant")
    reactor = node("instrument/reactor", "Reactor", "Fixed-bed flow reactor", reactor_kind="flow")

    def test(key, name, evid, results):
        t = node(f"test/{key}", "CatalyticTest", name, test_kind="activity", driving_forces=["thermo"],
                 experiment_kind="physical", temperature=V(220, "°C"), pressure=V(2, "MPa", basis="absolute"),
                 temperature_measured_at="catalyst_bed", time_on_stream=V(12, "h"),
                 evidence=[ev(loc, id=i) for i, loc in evid], result_values=results)
        link("USES_CATALYST", t, sample, state="reduced")
        link("FED_WITH", t, feed)
        link("IN_REACTOR", t, reactor)
        link("OF_REACTION", t, rxn)
        return t

    def alpha(rid, value, evid, **kw):
        return V(value, "1", id=rid, variable=v_alpha, evidence_ids=[evid], **kw)

    test("weight-fit", "Synthesis, alpha from a weight-basis fit", [("fit_w", "Figure 3")], [
        alpha("alpha_w", 0.89, "fit_w", basis="weight fraction W_n",
              definition="slope of ln(W_n/n) against n over C14-C21 (linear fit of the ASF plot)")])
    test("mole-fit", "Synthesis, alpha from a mole-basis fit", [("fit_x", "Figure 4")], [
        alpha("alpha_x", 0.71, "fit_x", basis="mole fraction x_n",
              definition="slope of ln(x_n) against n over C5-C10 (linear fit of the ASF plot)")])
    test("lumped", "Synthesis, alpha from lumped selectivities", [("lumped", "Table 2")], [
        alpha("alpha_l", 0.62, "lumped",
              definition="calculated from the lumped selectivities (C2-C4 and C2+), no distribution fitted")])
    for e in derive_reported_in(doc):
        e["props"]["origin"] = SYN
        doc["links"].append(e)
    return doc


if __name__ == "__main__":
    write_canonical(HERE / "chain-growth-probability.json", build())
    print("wrote chain-growth-probability.json")
