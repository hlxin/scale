"""Build the synthetic selectivity-basis example of the catalysis domain (all values invented; issue #82).

    python build_selectivity_basis.py

  selectivity-basis.json
    Fischer-Tropsch tests whose selectivities state different things as their count and their whole:
      a Lyu-like test      CO2 20.3 % of the converted CO (carbon, CO2 in the denominator), beside CH4, C2-C4 and C5+ that
                           add to 100 % among the hydrocarbons (CO2 excluded): two wholes in one table row
      a Xie-like test      CH4 and C5+ as shares of the converted CO, CO2 included
      an olefin test       C5+ olefins 74.5 % within the olefins and aldehydes 97 wt% within the oxygenates: shares within a
                           record (the value's relative_to), by carbon atoms and by mass
      an unstated test     a methane selectivity that states neither what it counts nor what it is a share of
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
P = "ex:sb"


def V(value, unit, **kw) -> dict:
    return {"status": "present", "value": value, "unit": unit, **kw}


def build() -> dict:
    doc = {"directed": True, "multigraph": True,
           "graph": {"schema": "scale-catal", "schema_version": HEAD_VERSION, "graph_id": f"{P}/graph",
                     "title": "Selectivity basis: what a selectivity counts and is a share of (invented)",
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
               title="Selectivities on different bases (invented)")

    def ev(locator, kind="table", **kw):
        return {"source": src, "locator": locator, "kind": kind, **kw}

    co = node("species/co", "ChemicalSpecies", "CO", formula="CO", elemental_composition={"C": 1, "O": 1}, charge=0)
    h2 = node("species/h2", "ChemicalSpecies", "H2", formula="H2", elemental_composition={"H": 2}, charge=0)
    co2 = node("species/co2", "ChemicalSpecies", "CO2", formula="CO2", elemental_composition={"C": 1, "O": 2}, charge=0)
    ch4 = node("species/ch4", "ChemicalSpecies", "CH4", formula="CH4", elemental_composition={"C": 1, "H": 4}, charge=0)
    v_sel = node("variable/selectivity", "Variable", "product selectivity", scale="quantitative",
                 quantity_kind="selectivity", unit="%")

    def lump(key, name, cmin, cmax, cls, definition):
        return node(f"lump/{key}", "ProductLump", name, carbon_min=cmin, **({"carbon_max": cmax} if cmax else {}),
                    open_ended=cmax is None, compound_class=cls, definition=definition, evidence=[ev("Table 1")])

    l_c24 = lump("c2-c4", "C2-C4", 2, 4, "hydrocarbon", "C2-C4 hydrocarbons")
    l_c5 = lump("c5-plus", "C5+", 5, None, "hydrocarbon", "hydrocarbons with five carbon atoms or more")
    l_olefins = lump("olefins", "olefins", 2, None, "olefin", "all olefins formed")
    l_c5_olefins = lump("c5-olefins", "C5+ olefins", 5, None, "olefin", "olefins with five carbon atoms or more")
    l_oxy = lump("oxygenates", "oxygenates", 1, None, "oxygenate", "all oxygenates formed")
    l_ald = lump("aldehydes", "aldehydes", 1, None, "oxygenate", "aldehydes among the oxygenates")

    rxn = node("reaction/fts", "Reaction", "n CO + 2n H2 -> (CH2)n + n H2O", equation="n CO + 2n H2 -> (CH2)n + n H2O",
               balance_status="not_checked", direction="forward")
    link("HAS_PARTICIPANT", rxn, co, role="reactant", coefficient=1)
    link("HAS_PARTICIPANT", rxn, h2, role="reactant", coefficient=2)
    cat = node("catalyst/fe", "Catalyst", "Fe carbide on graphene", nominal_formula="Fe2C", catalyst_family="metal",
               evidence=[ev("Table 1")])
    sample = node("sample/fe", "CatalystSample", "Fe carbide on graphene, batch 1", sample_kind="powder",
                  evidence=[ev("Table 1")])
    link("HAS_FORMULATION", sample, cat)
    feed = node("feed/syngas", "Feed", "H2/CO = 1", evidence=[ev("Methods", "text")])
    link("HAS_COMPONENT", feed, co, role="reactant")
    link("HAS_COMPONENT", feed, h2, role="reactant")
    reactor = node("instrument/reactor", "Reactor", "Fixed-bed flow reactor", reactor_kind="flow")

    def test(key, name, evid, results):
        t = node(f"test/{key}", "CatalyticTest", name, test_kind="activity", driving_forces=["thermo"],
                 experiment_kind="physical", temperature=V(300, "°C"), pressure=V(2, "MPa", basis="absolute"), temperature_measured_at="catalyst_bed",
                 time_on_stream=V(12, "h"), evidence=[ev(loc, id=i) for i, loc in evid], result_values=results)
        link("USES_CATALYST", t, sample, state="reduced")
        link("FED_WITH", t, feed)
        link("IN_REACTOR", t, reactor)
        link("OF_REACTION", t, rxn)
        return t

    def sel(rid, target, value, evid, unit="%", **kw):
        return V(value, unit, id=rid, variable=v_sel, target=target, evidence_ids=[evid], **kw)

    # a Lyu-like row: CO2 as a share of the converted CO, the hydrocarbons as shares of the hydrocarbons (CO2 excluded)
    test("lyu-like", "Syngas conversion, CO2 beside the hydrocarbons", [("lyu", "Table 1")], [
        sel("lyu_co2", co2, 20.3, "lyu", basis="carbon basis", definition="CO2 selectivity, as a share of the converted CO"),
        sel("lyu_ch4", ch4, 2.6, "lyu", basis="carbon basis", definition="selectivity among the hydrocarbons, CO2 not included"),
        sel("lyu_c24", l_c24, 31.6, "lyu", basis="carbon basis", definition="selectivity among the hydrocarbons, CO2 not included"),
        sel("lyu_c5", l_c5, 65.8, "lyu", basis="carbon basis", definition="selectivity among the hydrocarbons, CO2 not included"),
    ])
    # a Xie-like test: the products as shares of the converted CO, CO2 included
    test("xie-like", "Syngas conversion, shares of the converted CO", [("xie", "Table 2")], [
        sel("xie_ch4", ch4, 9, "xie", basis="carbon basis", definition="share of the converted CO, CO2 included in the denominator"),
        sel("xie_c5", l_c5, 28, "xie", basis="carbon basis", definition="share of the converted CO, CO2 included in the denominator"),
    ])
    # shares within one record: a pool of olefins (carbon atoms), the oxygenates (mass)
    test("within-pool", "Olefin and oxygenate distributions", [("pool", "Table 3")], [
        sel("c5_olefins_in_olefins", l_c5_olefins, 74.5, "pool", basis="carbon basis", relative_to=l_olefins,
            definition="share within the olefins distribution"),
        sel("aldehydes_in_oxygenates", l_ald, 97, "pool", unit="wt%", relative_to=l_oxy,
            definition="share within the oxygenates, by mass"),
    ])
    # a test that states neither what it counts nor what it is a share of
    test("unstated", "Syngas conversion, selectivity without a basis", [("plain", "Table 4")], [
        sel("plain_ch4", ch4, 12, "plain"),
    ])
    for e in derive_reported_in(doc):
        e["props"]["origin"] = SYN
        doc["links"].append(e)
    return doc


if __name__ == "__main__":
    write_canonical(HERE / "selectivity-basis.json", build())
    print("wrote selectivity-basis.json")
