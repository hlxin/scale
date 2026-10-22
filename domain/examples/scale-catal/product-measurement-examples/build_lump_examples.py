"""Build the synthetic product-lump examples of the catalysis domain (all values invented; issue #39).

    python build_lump_examples.py

  product-lumps-cheng-like.json    syngas conversion with selectivities on CH4, C2-C4, C5+, C5-C11, C10-C20 and C21+
                                   (the columns of a Fischer-Tropsch table), held in the results map (the validator's selectivity-sum check reads that
                                   map and the per-product lists, not result_values). C5-C11, C10-C20 and C21+ are SUBSET_OF C5+, so
                                   the validator does not add them to C5+ (innermost lumps sum to 95 %, no sum warning).
                                   C5-C11 and C10-C20 share C10-C11 and neither is declared inside the other: the validator
                                   reports that overlap (the one warning of this document, on purpose).
  product-lumps-second-paper.json  a second, independent document that mints its own C2-C4 and C5+ lumps with other ids and
                                   the same defining properties (carbon window, open end, compound class): two tests with C5+
                                   selectivities of 65 and 55 %. Competency question CQ-13 selects "C5+" across both
                                   documents by those properties, never by id.
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


def V(value, unit, **kw) -> dict:
    return {"status": "present", "value": value, "unit": unit, **kw}


def build(p: str, title: str, cheng_like: bool) -> dict:
    doc = {"directed": True, "multigraph": True,
           "graph": {"schema": "scale-catal", "schema_version": HEAD_VERSION, "graph_id": f"{p}/graph", "title": title,
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
        doc["links"].append({"id": f"{p}/link/{n[0]}", "source": s, "target": t, "type": typ,
                              "props": {"origin": SYN, **props}})

    src = node("source/paper", "Source", "Invented Fischer-Tropsch paper", kind="article", year=2026,
               title="Syngas conversion with selectivities on product lumps (invented)")

    def ev(locator, kind="table", **kw):
        return {"source": src, "locator": locator, "kind": kind, **kw}

    co = node("species/co", "ChemicalSpecies", "CO", formula="CO", elemental_composition={"C": 1, "O": 1}, charge=0)
    h2 = node("species/h2", "ChemicalSpecies", "H2", formula="H2", elemental_composition={"H": 2}, charge=0)
    ch4 = node("species/ch4", "ChemicalSpecies", "CH4", formula="CH4", elemental_composition={"C": 1, "H": 4}, charge=0)
    v_conv = node("variable/conversion", "Variable", "CO conversion", scale="quantitative", quantity_kind="conversion",
                  unit="%")
    v_sel = node("variable/selectivity", "Variable", "product selectivity", scale="quantitative",
                 quantity_kind="selectivity", unit="%")
    rxn = node("reaction/fts", "Reaction", "n CO + 2n H2 -> (CH2)n + n H2O", equation="n CO + 2n H2 -> (CH2)n + n H2O",
               balance_status="not_checked", direction="forward")
    link("HAS_PARTICIPANT", rxn, co, role="reactant", coefficient=1)
    link("HAS_PARTICIPANT", rxn, h2, role="reactant", coefficient=2)
    cat = node("catalyst/co-mn", "Catalyst", "Co/Mn oxide", nominal_formula="CoMnOx", catalyst_family="metal",
               evidence=[ev("Table 1")])
    sample = node("sample/co-mn", "CatalystSample", "Co/Mn oxide, batch 1", sample_kind="powder", evidence=[ev("Table 1")])
    link("HAS_FORMULATION", sample, cat)
    feed = node("feed/syngas", "Feed", "H2/CO = 2", evidence=[ev("Methods", "text")])
    link("HAS_COMPONENT", feed, co, role="reactant")
    link("HAS_COMPONENT", feed, h2, role="reactant")
    reactor = node("instrument/reactor", "Reactor", "Fixed-bed flow reactor", reactor_kind="flow")

    def lump(key, name, lo, hi=None, cls="hydrocarbon", definition=None):
        props = dict(carbon_min=lo, compound_class=cls, definition=definition or f"{name} hydrocarbons")
        if hi is None:
            props["open_ended"] = True
        else:
            props["carbon_max"], props["open_ended"] = hi, False
        return node(f"lump/{key}", "ProductLump", name, evidence=[ev("Table 2")], **props)

    def test(key, name, conversion, sel: list[tuple[str, str, float]], t_c):
        ids = [f"{key.replace('-', '_')}_{k}" for _, k, _ in sel]
        return node(
            f"test/{key}", "CatalyticTest", name, test_kind="activity", driving_forces=["thermo"],
            experiment_kind="physical", temperature=V(t_c, "°C"), pressure=V(2, "MPa", basis="absolute"),
            time_on_stream=V(12, "h"), temperature_measured_at="catalyst_bed",
            evidence=[ev("Table 2", id="conv")] + [ev("Table 2", id=i) for i in ids],
            results={"conversion": V(conversion, "%", variable=v_conv, target=co, basis="carbon", evidence_ids=["conv"]),
                     **{f"selectivity_{k}": V(x, "%", variable=v_sel, target=t, basis="carbon", evidence_ids=[i])
                        for i, (t, k, x) in zip(ids, sel)}})

    if cheng_like:
        c2_c4 = lump("c2-c4", "C2-C4", 2, 4)
        c5p = lump("c5-plus", "C5+", 5)
        c5_c11 = lump("c5-c11", "C5-C11", 5, 11, definition="gasoline-range hydrocarbons, C5-C11")
        c10_c20 = lump("c10-c20", "C10-C20", 10, 20, definition="diesel-range hydrocarbons, C10-C20")
        c21p = lump("c21-plus", "C21+", 21, definition="wax, C21 and above")
        for inner in (c5_c11, c10_c20, c21p):
            link("SUBSET_OF", inner, c5p)
        t = test("cat-12h", "Syngas conversion over Co/Mn oxide at 260 °C, 12 h on stream", 80.6,
                 [(ch4, "ch4", 8.7), (c2_c4, "c2_c4", 11.3), (c5p, "c5_plus", 80.0), (c5_c11, "c5_c11", 40.0),
                  (c10_c20, "c10_c20", 30.0), (c21p, "c21_plus", 5.0)], 260)
    else:
        c2_c4 = lump("light", "C2-C4", 2, 4, definition="C2-C4 hydrocarbons")
        c5p = lump("heavy", "C5+", 5, definition="hydrocarbons with five carbon atoms or more")
        t = test("fe-k", "Syngas conversion over Fe/K at 300 °C", 45.0, [(c2_c4, "c2_c4", 15.0), (c5p, "c5_plus", 65.0)], 300)
        t2 = test("fe-k-low", "Syngas conversion over Fe/K at 340 °C", 60.0,
                  [(c2_c4, "c2_c4", 25.0), (c5p, "c5_plus", 55.0)], 340)
        for tt in (t2,):
            link("USES_CATALYST", tt, sample, state="reduced")
            link("FED_WITH", tt, feed)
            link("IN_REACTOR", tt, reactor)
            link("OF_REACTION", tt, rxn)
    link("USES_CATALYST", t, sample, state="reduced")
    link("FED_WITH", t, feed)
    link("IN_REACTOR", t, reactor)
    link("OF_REACTION", t, rxn)
    for e_ in derive_reported_in(doc):
        e_["props"]["origin"] = SYN
        doc["links"].append(e_)
    return doc


if __name__ == "__main__":
    write_canonical(HERE / "product-lumps-cheng-like.json",
                    build("ex:lumps-a", "Product lumps: a Fischer-Tropsch table with nested and overlapping cuts", True))
    write_canonical(HERE / "product-lumps-second-paper.json",
                    build("ex:lumps-b", "Product lumps: a second paper that mints its own C2-C4 and C5+", False))
    print("wrote product-lumps-cheng-like.json, product-lumps-second-paper.json")
