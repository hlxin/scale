"""Evidence vectors and search, graph query plans with typed outcomes, and the GALAXY bundle export."""

import copy
import importlib.util
import json

import pytest

from conftest import GRAPH_MANIFEST, REPO
from scale import galaxy, pgraph, pgraph_query
from scale.passages import Index, evidence_items, locate, passages_of, split_page, tokens
from scale.util import ScaleError, load_doc

pytest.importorskip("numpy")
X = REPO / "domain/examples/scale-graph"
HEAD_VERSION = __import__("yaml").safe_load((GRAPH_MANIFEST).read_text())["version"]
SRC = "ex:t/source/lazier-1930"
OLD = "ex:t/source/old-1928"
LATE = "ex:t/source/late-1962"


@pytest.fixture(scope="module")
def spec():
    return pgraph.load_spec(GRAPH_MANIFEST)


def ev(src, loc, quote):
    return {"source": src, "locator": loc, "kind": "text", "quote": quote}


def V(value, unit, text=None):
    return {"status": "present", "value": value, "unit": unit, **({"as_reported": text} if text else {})}


@pytest.fixture()
def doc():
    """Two tests from 1930 (Cu-Zn and Zn-Cr), one from 1962, a sulfur claim from 1928."""
    q_cu = "a copper-zinc catalyst produced 135 cc. of methanol per hour at 360° C."
    q_cr = "the zinc chromite catalyst produced 85 cc. per hour at 380° C."
    q_s = "sulfur compounds in the gas destroy the activity of copper catalysts"
    q_late = "the purified gas was passed over the copper catalyst at 250° C."
    nodes = [
        {"id": SRC, "label": "Source", "props": {"name": "Lazier patent", "title": "Lazier patent", "kind": "patent", "year": 1930}},
        {"id": OLD, "label": "Source", "props": {"name": "Old paper", "title": "Old paper", "kind": "article", "year": 1928}},
        {"id": LATE, "label": "Source", "props": {"name": "Late paper", "title": "Late paper", "kind": "article", "year": 1962}},
        {"id": "ex:t/species/cu", "label": "ChemicalSpecies", "props": {"name": "copper", "formula": "Cu"}},
        {"id": "ex:t/species/zno", "label": "ChemicalSpecies", "props": {"name": "zinc oxide", "formula": "ZnO"}},
        {"id": "ex:t/species/h2s", "label": "ChemicalSpecies", "props": {"name": "hydrogen sulfide", "formula": "H2S"}},
    ]
    links = []
    for key, src, quote, temp, formula in (("cu", SRC, q_cu, 360, "Cu"), ("cr", SRC, q_cr, 380, "ZnO"), ("late", LATE, q_late, 250, "Cu")):
        cat, smp, tst = f"ex:t/{key}/catalyst", f"ex:t/{key}/sample", f"ex:t/{key}/test"
        e = [ev(src, "p. 2", quote)]
        nodes += [{"id": cat, "label": "Catalyst", "props": {"name": f"{key} catalyst", "evidence": e}},
                  {"id": smp, "label": "CatalystSample", "props": {"name": f"{key} sample", "sample_kind": "batch", "evidence": e}},
                  {"id": tst, "label": "CatalyticTest", "props": {"name": f"{key} test", "test_kind": "activity", "driving_forces": ["thermo"],
                                                                   "temperature": V(temp, "°C"), "pressure": V(290, "atm"), "evidence": e}}]
        links += [{"id": f"{tst}/uses", "source": tst, "target": smp, "type": "USES_CATALYST", "props": {"evidence": e}},
                  {"id": f"{smp}/formulation", "source": smp, "target": cat, "type": "HAS_FORMULATION", "props": {"evidence": e}},
                  {"id": f"{cat}/component", "source": cat, "target": f"ex:t/species/{formula.lower()}", "type": "HAS_COMPONENT",
                   "props": {"role": "active_component", "evidence": e}}]
    nodes.append({"id": "ex:t/claim/sulfur", "label": "Claim", "props": {"name": "sulfur poisons Cu", "statement": q_s,
                                                                         "claim_kind": "finding", "claim_status": "proposed",
                                                                         "evidence": [ev(OLD, "p. 1", q_s)]}})
    d = {"directed": True, "multigraph": True,
         "graph": {"schema": "scale-graph", "schema_version": HEAD_VERSION, "graph_id": "ex:t/graph", "title": "test graph",
                   "data_status": "synthetic_example"}, "nodes": nodes, "links": links}
    d["links"] += pgraph.derive_reported_in(d)
    for r in d["nodes"] + d["links"]:
        r["props"]["origin"] = "synthetic"
    return d


def test_the_test_document_is_valid(doc, spec):
    rep = pgraph.validate(doc, spec)
    assert rep.errors == [], rep.errors


# ------------------------------------------------------------------------------------------ vectors and search
def test_tokens_know_formulas_and_spellings():
    t = tokens("Cu-ZnO; CO and Co; sulphur")
    assert {"copper", "zinc", "oxide", "carbon", "monoxide", "cobalt", "sulfur"} <= set(t)


def test_vectors_are_deterministic_int8(tmp_path, doc):
    items = evidence_items(doc)
    a, b = Index.build(items), Index.build(copy.deepcopy(items))
    assert a.vectors.dtype.name == "int8" and a.vectors.shape == (len(items), 512)
    assert a.vectors.tobytes() == b.vectors.tobytes() and a.embedder_id == "scale-hash-v1"
    a.save(tmp_path / "ix")
    c = Index.load(tmp_path / "ix")
    assert c.vectors.tobytes() == a.vectors.tobytes() and [i["id"] for i in c.items] == [i["id"] for i in a.items]


def test_search_finds_meaning_across_spellings(doc):
    ix = Index.build(evidence_items(doc))
    top = ix.search("sulphur poisoning of Cu", k=1)[0]
    assert top["record"] == "ex:t/claim/sulfur"
    assert ix.search("zinc chromite", k=1, mode="keyword")[0]["text"].startswith("the zinc chromite")
    with pytest.raises(ScaleError):
        ix.search("x", mode="fuzzy")
    assert ix.search("sulphur poisoning of Cu", k=1, mode="rrf")[0]["record"] == "ex:t/claim/sulfur"


SEARCH_TEXTS = ["copper zinc oxide catalyst", "zinc oxide", "copper catalyst", "copper zinc oxide catalyst",
                "sulphur poisons the copper catalyst", "chromium oxide on pumice", "zinc chromite", "methanol from CO2",
                "zinc oxide", "the copper catalyst was reduced", "", "iron carbonyl"]


def _reference_search(ix, query, k, mode, where=None):
    """The plain definition the index's search must match: full BM25 and cosine over every item, a full sort by score
    and item id, positive scores only."""
    import math
    from collections import Counter

    import numpy as np
    from scale.passages import get_embedder, quantize
    tf = [Counter(tokens(i["text"])) for i in ix.items]
    n, lens = len(tf), [sum(c.values()) for c in tf]
    avg, kw = sum(lens) / n, np.zeros(n)
    for w in sorted(set(tokens(query))):
        df = sum(1 for c in tf if c.get(w))
        if df:
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for i, c in enumerate(tf):
                if c.get(w):
                    kw[i] += idf * c[w] * 2.2 / (c[w] + 1.2 * (0.25 + 0.75 * lens[i] / avg))
    m = ix.vectors.astype(np.float64)
    qv = quantize(get_embedder().encode([query])).astype(np.float64)[0]
    norms = np.linalg.norm(m, axis=1)
    norms[norms == 0] = 1.0
    vc = m @ qv / (norms * (np.linalg.norm(qv) or 1.0))
    kwn = kw / kw.max() if kw.max() > 0 else kw
    score = {"hybrid": 0.5 * kwn + 0.5 * np.clip(vc, 0, None), "vector": vc, "keyword": kw}[mode]
    order = sorted(range(n), key=lambda i: (-score[i], ix.items[i]["id"]))
    return [ix.items[i]["id"] for i in order if score[i] > 0 and (not where or where(ix.items[i]))][:k]


def test_search_is_exactly_the_head_of_a_full_sort():
    """The inverted index, the blocked cosine and the partial sort return what the plain definitions return, ties
    (here: repeated texts) broken by item id, with or without a filter, and whether the vectors are kept or converted
    block by block."""
    import numpy as np
    from scale import passages
    items = [{"id": f"ex:t/r{j:02d}#evidence/0", "record": f"ex:t/r{j:02d}", "evidence": 0, "text": t,
              "source": f"ex:t/s{j % 3}"} for j, t in enumerate(SEARCH_TEXTS * 3)]
    ix = Index.build(items)
    odd = lambda it: it["source"] != "ex:t/s1"                                        # noqa: E731
    for q in ("copper zinc oxide", "zinc oxide", "sulfur poisoning", "nothing matches xyzzy", "catalyst"):
        for mode in ("hybrid", "vector", "keyword"):
            for k, where in ((1, None), (5, None), (100, None), (2, odd), (7, odd)):
                got = [h["id"] for h in ix.search(q, k=k, mode=mode, where=where)]
                assert got == _reference_search(ix, q, k, mode, where), (q, mode, k)
    kept = ix.cosine("zinc oxide catalyst")
    old, passages.CACHE_BYTES, passages.BLOCK = passages.CACHE_BYTES, 0, 7
    try:
        blocked = Index.build(items).cosine("zinc oxide catalyst")
    finally:
        passages.CACHE_BYTES, passages.BLOCK = old, 65536
    assert np.array_equal(kept, blocked)


def test_rrf_fuses_the_keyword_and_vector_rankings():
    from scale.passages import RRF_K
    items = [{"id": f"ex:t/r{j:02d}#evidence/0", "record": f"ex:t/r{j:02d}", "evidence": 0, "text": t}
             for j, t in enumerate(SEARCH_TEXTS)]
    ix = Index.build(items)
    q = "copper zinc oxide"
    hits = ix.search(q, k=50, mode="rrf")
    kw = {ix.items[i]["id"]: r for r, i in enumerate(ix.ranked(ix.bm25(q), 1000), 1)}
    vc = {ix.items[i]["id"]: r for r, i in enumerate(ix.ranked(ix.cosine(q), 1000), 1)}
    assert {h["id"] for h in hits} == set(kw) | set(vc)
    for h in hits:
        expect = sum(1 / (RRF_K + r[h["id"]]) for r in (kw, vc) if h["id"] in r)
        assert h["score"] == round(expect, 4) and h["score"] <= round(2 / (RRF_K + 1), 4)
    assert [h["score"] for h in hits] == sorted((h["score"] for h in hits), reverse=True)
    assert hits == ix.search(q, k=50, mode="rrf")


def test_saved_term_statistics_are_used_only_with_their_items(tmp_path):
    """The inverted index saved beside an index (<stem>.terms) is read back as saved, and ignored (rebuilt from the
    items) when the items it was saved with changed or it is missing."""
    import numpy as np
    items = [{"id": f"ex:t/r{j:02d}#evidence/0", "record": f"ex:t/r{j:02d}", "evidence": 0, "text": t}
             for j, t in enumerate(SEARCH_TEXTS)]
    a = Index.build(items)
    a.save(tmp_path / "ix")
    b = Index.load(tmp_path / "ix")
    assert b.vocab == a.vocab and all(np.array_equal(x, y) for x, y in (
        (a.indptr, b.indptr), (a.post_item, b.post_item), (a.post_count, b.post_count), (a.lengths, b.lengths)))
    assert b.search("zinc oxide", k=5) == a.search("zinc oxide", k=5)
    j = tmp_path / "ix.jsonl"                     # the items change, the saved statistics do not
    j.write_text(j.read_text().replace("zinc chromite", "iron oxide sludge"))
    c = Index.load(tmp_path / "ix")
    assert "sludge" in c.vocab and "chromite" not in c.vocab
    (tmp_path / "ix.terms").unlink()
    assert Index.load(tmp_path / "ix").vocab == c.vocab


def test_passages_and_their_locations():
    pages = [{"page": 1, "origin": "ocr", "text": "First paragraph about copper.\n\nSecond paragraph about zinc oxide."},
             {"page": 2, "origin": "text_layer", "text": "A " + "long sentence. " * 100}]
    ps = passages_of("s", "ex:s", pages)
    assert ps[0]["id"] == "s/p1/1" and ps[0]["origin"] == "ocr"
    assert all(len(p["text"]) <= 900 for p in ps) and len([p for p in ps if p["page"] == 2]) >= 2
    assert locate("second paragraph ABOUT zinc", ps)["id"] == "s/p1/1"
    assert split_page("") == []


# ------------------------------------------------------------------------------------------ query plans
CU_PLAN = {"question": "Which tests used a Cu catalyst?", "match": {"label": "CatalyticTest", "as": "test"},
           "steps": [{"from": "test", "edge": "USES_CATALYST", "to": "CatalystSample", "as": "sample"},
                     {"from": "sample", "edge": "HAS_FORMULATION", "to": "Catalyst", "as": "catalyst"},
                     {"from": "catalyst", "edge": "HAS_COMPONENT", "to": "ChemicalSpecies", "as": "cu",
                      "where": [{"prop": "formula", "op": "eq", "value": "Cu"}]}],
           "return": ["test.name", "test.temperature", "catalyst.name"], "evidence": True}


def test_query_answers_with_dated_evidence(doc, spec):
    res = pgraph_query.run(doc, spec, CU_PLAN)
    assert res["status"] == "answered" and {r["bound"]["test"] for r in res["rows"]} == {"ex:t/cu/test", "ex:t/late/test"}
    row = next(r for r in res["rows"] if r["bound"]["test"] == "ex:t/cu/test")
    assert row["values"]["test.temperature"]["value"] == 360 and row["earliest_source_year"] == 1930
    assert all(e["source"] != "ex:t/species/cu" for e in row["evidence"])     # shared kinds do not date a row


def test_published_before_keeps_only_older_evidence(doc, spec):
    res = pgraph_query.run(doc, spec, {**CU_PLAN, "published_before": "1959-01-01"})
    assert [r["bound"]["test"] for r in res["rows"]] == ["ex:t/cu/test"]
    assert any("1962" in x["reason"] for x in res["excluded"])


def test_filters_compare_only_in_the_stated_unit(doc, spec):
    plan = {**CU_PLAN, "where": [{"var": "test", "prop": "temperature", "op": "le", "value": 300, "unit": "°C"}]}
    assert [r["bound"]["test"] for r in pgraph_query.run(doc, spec, plan)["rows"]] == ["ex:t/late/test"]
    k = copy.deepcopy(plan)
    k["where"][0]["unit"] = "K"
    res = pgraph_query.run(doc, spec, k)
    assert res["status"] == "missing_context" and all(x["reason"].startswith("incompatible_unit") for x in res["excluded"])


def test_eq_ne_and_in_on_a_number_compare_in_the_filters_unit(doc, spec):
    """eq, ne and in with numbers on a value object are numeric comparisons: they need the filter's unit (a plan error
    without one, or unit_unstated where the schema cannot tell), never match a value in another unit (nothing is
    converted), and a reported range holds the numbers inside it."""
    d = copy.deepcopy(doc)
    temps = {"ex:t/cu/test": V(380, "°C"), "ex:t/cr/test": V(716, "°F"),            # 716 °F is 380 °C: never compared
             "ex:t/late/test": {"status": "present", "lower": 370, "upper": 390, "unit": "°C"}}
    for n in d["nodes"]:
        if n["id"] in temps:
            n["props"]["temperature"] = temps[n["id"]]
    plan = {"match": {"label": "CatalyticTest", "as": "t"}, "return": ["t.name"]}

    def rows(op, value, unit=None, **kw):
        f = {"var": "t", "prop": "temperature", "op": op, "value": value, **({"unit": unit} if unit else {})}
        res = pgraph_query.run(d, spec, {**plan, "where": [f], **kw})
        return sorted(r["bound"]["t"] for r in res["rows"]), res
    found, res = rows("eq", 380, "°C")
    assert found == ["ex:t/cu/test", "ex:t/late/test"]                      # the °F test is not compared
    assert res["coverage"]["excluded"]["by_reason"] == {"incompatible_unit": 1}
    assert "convertible_left_out" not in res["coverage"] and "converted" not in res["coverage"]
    found, res = rows("eq", 380, "K")                                       # 380 K is not 380 °C
    assert found == [] and res["status"] == "missing_context"
    assert rows("ne", 380, "°C")[0] == []                                    # the °F test is left out, not "not 380"
    assert rows("ne", 375, "°C")[0] == ["ex:t/cu/test"]                      # 375 lies in the reported range
    assert rows("in", [360, 380], "°C")[0] == ["ex:t/cu/test", "ex:t/late/test"]
    assert rows("in", [360, 716], "°F")[0] == ["ex:t/cr/test"]
    for op, value in (("eq", 380), ("ne", 380), ("in", [380, 300])):
        with pytest.raises(ScaleError, match="states no unit"):
            rows(op, value)
    # where the schema cannot tell (a step without `to`), a number with no unit is left out, never compared
    loose = {"match": {"label": "CatalystSample", "as": "sample"},
             "steps": [{"from": "sample", "edge": "USES_CATALYST", "direction": "in", "as": "test"}],
             "where": [{"var": "test", "prop": "temperature", "op": "eq", "value": 380}], "return": ["test.name"]}
    res = pgraph_query.run(d, spec, loose)
    assert res["status"] == "missing_context" and res["coverage"]["excluded"]["by_reason"] == {"unit_unstated": 3}
    # text and plain numbers compare as before
    assert pgraph_query.run(d, spec, {**plan, "where": [{"var": "t", "prop": "name", "op": "in", "value": ["cu test"]}]})["row_count"] == 1
    year = {"match": {"label": "Source", "as": "src"}, "where": [{"var": "src", "prop": "year", "op": "eq", "value": 1930}]}
    assert pgraph_query.run(d, spec, year)["row_count"] == 1


def test_a_one_sided_bound_is_never_read_as_the_exact_number(doc, spec):
    """A value with a bound ("did not exceed 1 %", "at least 2") passes a numeric filter only when every number the
    bound allows passes it, fails when none does, and is left out otherwise (one_sided_bound, counted; with no row the
    answer is missing context); eq and in never hold for a bound alone. A bound in another unit is not compared."""
    d = copy.deepcopy(doc)
    vals = {"ex:t/cu/test": {**V(1, "%", "did not exceed 1 %"), "bound": "upper"},
            "ex:t/cr/test": {**V(2, "%", "at least 2 %"), "bound": "lower"}}
    for n in d["nodes"]:
        if n["id"] in vals:
            n["props"]["conversion"] = vals[n["id"]]
    assert pgraph.validate(d, spec).errors == []
    plan = {"match": {"label": "CatalyticTest", "as": "t"}, "return": ["t.name"]}

    def run(op, value, **kw):
        res = pgraph_query.run(d, spec, {**plan, "where": [{"var": "t", "prop": "conversion", "op": op, "value": value,
                                                            "unit": "%"}], **kw})
        return sorted(r["bound"]["t"] for r in res["rows"]), res["coverage"]["excluded"]["by_reason"], res
    cu, cr = "ex:t/cu/test", "ex:t/cr/test"            # at most 1 %, at least 2 %; the late test has no conversion
    for op, value, found, undecided in (("le", 1, [cu], 0), ("lt", 5, [cu], 1), ("gt", 1.5, [cr], 0), ("ge", 2, [cr], 0),
                                        ("gt", 0.5, [cr], 1), ("ge", 1, [cr], 1), ("eq", 1, [], 1), ("eq", 2, [], 1),
                                        ("in", [1, 2], [], 2), ("eq", 1.5, [], 0), ("ne", 1.5, [cr, cu], 0),
                                        ("in", [5, 6], [], 1)):
        rows, why, res = run(op, value)
        assert rows == found and why == {"not_curated": 1, **({"one_sided_bound": undecided} if undecided else {})}, (op, value)
        assert any("one_sided_bound" in x for x in res["limitations"]) == bool(undecided), (op, value)
    only = {**plan, "match": {**plan["match"], "id": cu}}
    res = pgraph_query.run(d, spec, {**only, "where": [{"var": "t", "prop": "conversion", "op": "gt", "value": 0.5, "unit": "%"}]})
    assert res["status"] == "missing_context" and res["excluded"][0]["reason"].startswith("one_sided_bound (the value is at most 1 %")
    assert pgraph_query.against_bound("upper", 1, "le", 1) is True and pgraph_query.against_bound("lower", 2, "lt", 2) is False
    # a bound in another unit is not compared at all (nothing is converted): incompatible_unit, never the number
    t = next(n for n in d["nodes"] if n["id"] == cu)["props"]
    t["temperature"] = {**V(300, "°C", "below 300 °C"), "bound": "upper"}
    res = pgraph_query.run(d, spec, {**only, "where": [{"var": "t", "prop": "temperature", "op": "le", "value": 600, "unit": "K"}]})
    assert res["status"] == "missing_context" and res["coverage"]["excluded"]["by_reason"] == {"incompatible_unit": 1}
    res = pgraph_query.run(d, spec, {**only, "where": [{"var": "t", "prop": "temperature", "op": "le", "value": 300, "unit": "°C"}]})
    assert res["row_count"] == 1


def test_absence_and_schema_gap_are_different_answers(doc, spec):
    none = {**CU_PLAN, "where": [{"var": "test", "prop": "name", "op": "eq", "value": "no such test"}]}
    assert pgraph_query.run(doc, spec, none)["status"] == "no_matching_record"
    gap = copy.deepcopy(CU_PLAN)
    gap["return"] = ["test.sulfur_content_ppm"]
    res = pgraph_query.run(doc, spec, gap)
    assert res["status"] == "schema_gap" and "CatalyticTest.sulfur_content_ppm is not declared" in res["schema_gaps"]


def test_missing_values_are_reported_not_guessed(doc, spec):
    d = copy.deepcopy(doc)
    t = next(n for n in d["nodes"] if n["id"] == "ex:t/cu/test")
    t["props"]["temperature"] = {"status": "not_reported", "missing_reason": "not_stated_in_source"}
    plan = {**CU_PLAN, "where": [{"var": "test", "prop": "temperature", "op": "le", "value": 400, "unit": "°C"}]}
    res = pgraph_query.run(d, spec, plan)
    assert {"record": "ex:t/cu/test", "filter": plan["where"][0], "reason": "not_reported"} in res["excluded"]


def test_text_search_inside_a_plan(doc, spec):
    ix = Index.build(evidence_items(doc))
    plan = {"match": {"label": "Claim", "as": "claim"}, "text": {"query": "sulphur and copper", "vars": ["claim"]},
            "return": ["claim.statement"]}
    res = pgraph_query.run(doc, spec, plan, ix)
    assert res["status"] == "answered" and res["rows"][0]["text_score"] > 0
    with pytest.raises(ScaleError):
        pgraph_query.run(doc, spec, plan)


def test_describe_shows_what_a_domain_uses(spec):
    """The one catalysis checklist covers the whole domain: every driving force's terms, with its cases. Each label names
    the file that declares it (`defined_in`: the kernel or the domain)."""
    d = pgraph.describe(spec, ["CatalyticTest", "HAS_COMPONENT"], profile="catalysis")
    props = d["labels"]["CatalyticTest"]["properties"]
    assert {"heating_mode", "electrode_potential", "irradiance", "discharge_power", "temperature"} <= set(props)
    assert len(d["checklist"]["labels"]["CatalyticTest"]["when"]) == 7
    assert "role" in d["edges"]["HAS_COMPONENT"]["properties"]
    assert d["labels"]["CatalyticTest"]["defined_in"] == "catalysis" and "module" not in d["labels"]["CatalyticTest"]
    assert pgraph.describe(spec, ["Operation"])["labels"]["Operation"]["defined_in"] == "kernel"
    with pytest.raises(ScaleError, match="unknown domain or profile 'thermocatalysis'"):
        pgraph.describe(spec, ["CatalyticTest"], profile="thermocatalysis")
    with pytest.raises(ScaleError):
        pgraph.describe(spec, ["NoSuchLabel"])


# ------------------------------------------------------------------------------------------ GALAXY export
def _galaxy_validator():
    import os
    from pathlib import Path
    kit = os.environ.get("SCALE_GALAXY_VALIDATOR")                # the path of GALAXY's bundle_validate.py, if at hand
    path = Path(kit) if kit else None
    if not path or not path.exists():
        return None
    import sys
    s = importlib.util.spec_from_file_location("bundle_validate", path)
    m = importlib.util.module_from_spec(s)
    sys.modules["bundle_validate"] = m
    s.loader.exec_module(m)
    return m


def test_galaxy_quantities_are_converted_and_keep_the_reported_text():
    q, text = galaxy.quantity("temperature", V(360, "°C", "360° C."))
    assert q == {"value": 633.15, "unit": "K", "as_reported": "360° C."} and text is None
    q, _ = galaxy.quantity("pressure", {"status": "present", "lower": 200, "upper": 300, "unit": "atm"})
    assert q["unit"] == "MPa" and q["uncertainty"]["kind"] == "range"
    assert galaxy.quantity("space_velocity", V(5, "vol/vol/h")) == (None, "5 vol/vol/h")
    assert galaxy.quantity("conversion", {"status": "not_reported"}) == (None, None)


def test_galaxy_export(tmp_path, doc, spec):
    m = galaxy.export(doc, spec, tmp_path / "b", "test-bundle", created="2026-09-28T00:00:00Z")
    galaxy.seal(tmp_path / "b")
    g = json.loads((tmp_path / "b/kg/graph.json").read_text())
    ids = {n["id"] for n in g["nodes"]}
    assert "Publication:scale:lazier-1930" in ids and m["counts"]["papers"] == 3
    edges = [e for e in g["links"] if e["type"] != "REPORTED_IN"]
    assert all(e["id"] == galaxy.canonical_edge_id(e["type"], e["source"], e["target"], e["props"]["source_paper_ids"][0]) for e in edges)
    assert all(e["props"]["_evidence"] and e["props"]["_statement"] == "observation" for e in edges)
    t = next(n for n in g["nodes"] if n["props"].get("scale_id") == "ex:t/cu/test")
    assert t["props"]["temperature"] == {"value": 633.15, "unit": "K", "as_reported": "360 °C"}
    v = _galaxy_validator()
    if v:
        rep = v.validate_bundle(tmp_path / "b")
        assert rep.ok, [f.message for f in rep.errors][:5]


# ------------------------------------------------------------------------------------------ units, coverage, second-hand


def test_a_numeric_filter_states_its_unit(doc, spec):
    plan = {**CU_PLAN, "where": [{"var": "test", "prop": "temperature", "op": "le", "value": 300}]}
    with pytest.raises(ScaleError, match="states no unit"):
        pgraph_query.run(doc, spec, plan)
    # where the schema cannot tell (a step without `to`), a value the filter has no unit for is left out, never compared
    loose = {"match": {"label": "CatalystSample", "as": "sample"},
             "steps": [{"from": "sample", "edge": "USES_CATALYST", "direction": "in", "as": "test"}],
             "where": [{"var": "test", "prop": "temperature", "op": "le", "value": 300}], "return": ["test.name"]}
    res = pgraph_query.run(doc, spec, loose)
    assert res["status"] == "missing_context" and res["coverage"]["excluded"]["by_reason"] == {"unit_unstated": 3}
    assert any("because a unit is unstated: the filter's" in x for x in res["limitations"])
    year = {"match": {"label": "Source", "as": "src"}, "where": [{"var": "src", "prop": "year", "op": "lt", "value": 1950}],
            "return": ["src.name"]}
    assert pgraph_query.run(doc, spec, year)["row_count"] == 2                  # a plain number needs no unit
    # the same unit-less filter inside such a step: the values it could not compare make the status missing_context,
    # and the limitations say why, although the step's filters add nothing to `excluded`
    in_step = {"match": {"label": "CatalystSample", "as": "sample"},
               "steps": [{"from": "sample", "edge": "USES_CATALYST", "direction": "in", "as": "test",
                          "where": [{"prop": "temperature", "op": "le", "value": 300}]}], "return": ["test.name"]}
    res = pgraph_query.run(doc, spec, in_step)
    assert res["status"] == "missing_context" and res["excluded"] == []
    assert res["coverage"]["not_evaluated_in_steps"] == {"total": 3, "by_reason": {"unit_unstated": 3}, "rows": 3}
    assert [s.get("rows_not_evaluated") for s in res["coverage"]["steps"] if s["kind"] == "step"] == [3]
    assert any("3 values were not compared because a unit is unstated" in x for x in res["limitations"])
    assert any("comparisons in steps could not be made" in x and "3 rows were left out by a required step" in x
               for x in res["limitations"])


def test_a_step_comparison_it_cannot_make_counts_only_for_the_rows_a_required_step_left_out(doc, spec):
    """missing_context comes from a step only for a row a required step left out because no link passed and one
    could not be compared. An optional step's comparisons, and a required step's on rows that pass it (and that a
    later stage leaves out), are counted in the coverage and the limitations, never in the status."""
    batch = {"prop": "batch_identifier", "op": "eq", "value": "B1"}           # recorded on no sample
    optional = {"match": {"label": "CatalyticTest", "as": "t"},
                "steps": [{"from": "t", "edge": "USES_CATALYST", "to": "CatalystSample", "as": "s", "optional": True,
                           "where": [batch]}],
                "where": [{"var": "t", "prop": "name", "op": "eq", "value": "no such test"}], "return": ["t.name", "s.name"]}
    res = pgraph_query.run(doc, spec, optional)
    assert res["status"] == "no_matching_record"
    assert res["coverage"]["not_evaluated_in_steps"] == {"total": 3, "by_reason": {"not_curated": 3}, "rows": 0}
    assert any("comparisons in steps could not be made" in x for x in res["limitations"])
    # the only matching test is left out on purpose (second-hand evidence): still no match, not missing context
    d = copy.deepcopy(doc)
    for r in d["nodes"] + d["links"]:
        for e in r["props"].get("evidence") or []:
            if e["source"] == LATE:
                e["evidence_type"] = "ECO:0000033"
    own = {**optional, "own_work_only": True, "where": [{"var": "t", "prop": "name", "op": "eq", "value": "late test"}]}
    res = pgraph_query.run(d, spec, own)
    assert res["status"] == "no_matching_record" and res["coverage"]["second_hand_only"] == 1
    # a required step: a row with a link that passes is kept, whatever its other links; one with none is left out
    d = copy.deepcopy(doc)
    next(n for n in d["nodes"] if n["id"] == "ex:t/cu/sample")["props"]["batch_identifier"] = "B1"
    d["links"].append({"id": "ex:t/cu/test/uses-cr", "source": "ex:t/cu/test", "target": "ex:t/cr/sample",
                       "type": "USES_CATALYST", "props": {"evidence": [ev(SRC, "p. 2", "x")], "origin": "synthetic"}})
    required = {**optional, "steps": [{**optional["steps"][0], "optional": False}]}
    res = pgraph_query.run(d, spec, required)          # cu test passes the step, then the where leaves it out
    step = next(s for s in res["coverage"]["steps"] if s["kind"] == "step")
    assert (step["rows_in"], step["rows_out"], step.get("rows_not_evaluated")) == (3, 1, 2)
    assert res["status"] == "missing_context"          # cr and late tests: left out by the step, not compared
    res = pgraph_query.run(d, spec, {**required, "where": [{"var": "t", "prop": "name", "op": "ne", "value": "cu test"}]})
    assert res["status"] == "missing_context" and res["coverage"]["not_evaluated_in_steps"]["rows"] == 2
    only_cu = {**required, "match": {"id": "ex:t/cu/test", "as": "t"}}
    res = pgraph_query.run(d, spec, only_cu)
    assert res["status"] == "no_matching_record"       # its unevaluated link did not decide anything
    assert res["coverage"]["not_evaluated_in_steps"] == {"total": 1, "by_reason": {"not_curated": 1}, "rows": 0}


def test_a_percent_is_compared_only_on_the_basis_it_states(doc, spec):
    """A selectivity on a carbon basis and one on a mass basis are not one quantity: a filter compares a value only when
    both state the same basis (the filter's basis; compared as a unit is, case included, whitespace runs aside) or
    neither does. A basis on one side only is other_basis, whichever side states it, in % or in any other unit."""
    d = copy.deepcopy(doc)
    tests = {n["id"]: n for n in d["nodes"] if n["label"] == "CatalyticTest"}
    cu, cr, late = "ex:t/cu/test", "ex:t/cr/test", "ex:t/late/test"
    tests[cu]["props"]["conversion"] = {**V(60, "%"), "basis": "carbon basis"}
    tests[cr]["props"]["conversion"] = {**V(70, "%"), "basis": "CO2 conversion, not CO"}
    tests[late]["props"]["conversion"] = V(80, "%")
    plan = {"match": {"label": "CatalyticTest", "as": "t"}, "return": ["t.conversion"],
            "where": [{"var": "t", "prop": "conversion", "op": "ge", "value": 50, "unit": "%"}]}
    res = pgraph_query.run(d, spec, plan)
    assert [r["bound"]["t"] for r in res["rows"]] == [late]                  # neither states a basis
    assert {x["record"]: x["reason"].split(" ")[0] for x in res["excluded"]} == {cu: "other_basis", cr: "other_basis"}
    assert any("not compared for their unit or basis (other_basis 2)" in x for x in res["limitations"])
    plan["where"][0]["basis"] = " carbon  basis"
    res = pgraph_query.run(d, spec, plan)
    assert [r["bound"]["t"] for r in res["rows"]] == [cu]                    # the same basis, whitespace runs aside
    assert {x["record"]: x["reason"].split(" ")[0] for x in res["excluded"]} == {cr: "other_basis", late: "other_basis"}
    assert next(x["reason"] for x in res["excluded"] if x["record"] == late) == \
        "other_basis (the value states no basis; filter on ' carbon  basis')"
    res = pgraph_query.run(d, spec, {**plan, "where": [{**plan["where"][0], "basis": "Carbon basis"}]})
    assert res["rows"] == [] and next(x["reason"] for x in res["excluded"] if x["record"] == cu) == \
        "other_basis ('carbon basis', filter on 'Carbon basis')"                 # case is kept
    # in another unit too (mol%, °C): a basis on one side only keeps the value apart; mol% is never %
    for unit in ("mol%", "°C"):
        for n in tests.values():
            n["props"]["conversion"] = {**n["props"]["conversion"], "unit": unit}
        res = pgraph_query.run(d, spec, {**plan, "where": [{**plan["where"][0], "unit": unit, "basis": "carbon basis"}]})
        assert [r["bound"]["t"] for r in res["rows"]] == [cu], unit
        res = pgraph_query.run(d, spec, {**plan, "where": [{**plan["where"][0], "unit": "%", "basis": "carbon basis"}]})
        assert res["coverage"]["excluded"]["by_reason"] == {"incompatible_unit": 3}, unit
    # an empty basis is none; one that is not text is never the filter's
    tests[late]["props"]["conversion"] = {**V(80, "%"), "basis": "  "}
    tests[cr]["props"]["conversion"] = {**V(70, "%"), "basis": 5}
    res = pgraph_query.run(d, spec, {**plan, "where": [{k: v for k, v in plan["where"][0].items() if k != "basis"}]})
    assert [r["bound"]["t"] for r in res["rows"]] == [late] and res["coverage"]["excluded"]["by_reason"] == {"incompatible_unit": 1,
                                                                                                          "other_basis": 1}
    assert pgraph_query.run(d, spec, {**plan, "where": [{**plan["where"][0], "basis": "5"}]})["coverage"]["excluded"]["by_reason"] \
        == {"incompatible_unit": 1, "other_basis": 2}


def test_a_unit_is_compared_as_it_is_spelled_case_included_whitespace_aside(doc, spec):
    """The one rule for units: a value is compared only when its unit is the filter's, spelled the same, case included,
    once runs of whitespace count as one space; never a synonym and never a conversion (mPa is not MPa, mmol is not
    Mmol, mol % is not mol%, mol% is not %, barg is not bar, 1/h is not h-1). A value that states no unit, or a plain
    number against a filter with a unit, is unit_unstated."""
    d = copy.deepcopy(doc)
    tests = {n["id"]: n["props"] for n in d["nodes"] if n["label"] == "CatalyticTest"}
    cu, cr, late = "ex:t/cu/test", "ex:t/cr/test", "ex:t/late/test"
    tests[cu]["conversion"], tests[cr]["conversion"], tests[late]["conversion"] = V(60, "mol%"), V(70, "%"), V(80, "mol %")
    tests[cu]["pressure"], tests[cr]["pressure"], tests[late]["pressure"] = V(20, "bar"), V(20, " bar "), V(20, "barg")
    tests[cu]["space_velocity"], tests[cr]["space_velocity"] = V(12000, "h-1"), V(12000, "1/h")
    tests[late]["space_velocity"] = V(200, "min-1")
    assert pgraph.validate(d, spec).errors == []

    def run(prop, unit, op="ge", value=1):
        res = pgraph_query.run(d, spec, {"match": {"label": "CatalyticTest", "as": "t"}, "return": ["t.name"],
                                         "where": [{"var": "t", "prop": prop, "op": op, "value": value, "unit": unit}]})
        return sorted(r["bound"]["t"] for r in res["rows"]), {x["record"]: x["reason"].split(" ")[0] for x in res["excluded"]}, res
    assert run("conversion", "%")[:2] == ([cr], {cu: "incompatible_unit", late: "incompatible_unit"})     # mol% is not %
    assert run("conversion", "mol%")[:2] == ([cu], {cr: "incompatible_unit", late: "incompatible_unit"})  # mol % is not mol%
    assert run("conversion", " mol%  ")[0] == [cu]                                                       # the ends aside
    assert run("conversion", "MOL%")[:2] == ([], {cu: "incompatible_unit", cr: "incompatible_unit", late: "incompatible_unit"})
    assert run("conversion", "mol  %")[0] == [late]                                                      # a space run is one
    assert run("pressure", "bar")[:2] == ([cr, cu], {late: "incompatible_unit"})                         # barg is not bar
    assert run("pressure", "MPa", "le", 5)[0] == []                                                      # 20 bar is not 2 MPa
    assert run("pressure", "BAR")[:2] == ([], {cu: "incompatible_unit", cr: "incompatible_unit", late: "incompatible_unit"})
    assert run("space_velocity", "h-1")[:2] == ([cu], {cr: "incompatible_unit", late: "incompatible_unit"})
    found, why, res = run("conversion", "%")
    assert res["excluded"][0]["reason"] in ("incompatible_unit ('mol%', filter in '%')", "incompatible_unit ('mol %', filter in '%')")
    assert any("not compared for their unit or basis (incompatible_unit 2)" in x and "nothing is converted" in x
               for x in res["limitations"])
    # a value that states no unit, and a plain number against a filter with a unit: unit_unstated, never compared
    for unstated in (None, "", "   "):
        tests[cu]["conversion"] = {"status": "present", "value": 60, **({"unit": unstated} if unstated is not None else {})}
        assert run("conversion", "%")[1][cu] == "unit_unstated", unstated
    year = {"match": {"label": "Source", "as": "src"}, "return": ["src.name"],
            "where": [{"var": "src", "prop": "year", "op": "lt", "value": 1950, "unit": "a"}]}
    res = pgraph_query.run(d, spec, year)
    assert res["status"] == "missing_context" and res["coverage"]["excluded"]["by_reason"] == {"unit_unstated": 3}
    assert pgraph_query.run(d, spec, {**year, "where": [{k: v for k, v in year["where"][0].items() if k != "unit"}]})["row_count"] == 2
    assert pgraph_query.unit_key("  mol \t %  ") == "mol %" and pgraph_query.unit_key("°C") == pgraph_query.unit_key(" °C ")
    # case is kept: an SI prefix that differs only in case is another unit, never the filter's (5 mPa is not 5 MPa)
    tests[cu]["pressure"], tests[cr]["pressure"], tests[late]["pressure"] = V(5, "mPa"), V(2, "MPa"), V(5, "bar")
    assert pgraph.validate(d, spec).errors == []
    found, why, res = run("pressure", "MPa", "ge", 1)
    assert (found, why) == ([cr], {cu: "incompatible_unit", late: "incompatible_unit"})
    assert next(x["reason"] for x in res["excluded"] if x["record"] == cu) == "incompatible_unit ('mPa', filter in 'MPa')"
    assert res["coverage"]["compared_in_unit"] == 1
    assert run("pressure", "mPa", "ge", 1)[:2] == ([cu], {cr: "incompatible_unit", late: "incompatible_unit"})
    tests[cu]["conversion"], tests[cr]["conversion"] = V(60, "Mmol g-1 s-1"), V(70, "mmol g-1 s-1")
    tests[late]["conversion"] = V(80, "mmol  g-1 s-1 ")
    assert run("conversion", "mmol g-1 s-1")[:2] == ([cr, late], {cu: "incompatible_unit"})
    assert run("conversion", "Mmol g-1 s-1")[:2] == ([cu], {cr: "incompatible_unit", late: "incompatible_unit"})
    # every character is kept: the Kelvin sign (U+212A) is not the letter K, a micro sign is not a Greek mu
    for spelled, other in (("\u212a", "K"), ("\u00b5mol", "\u03bcmol"), ("°C", "ºC")):
        assert pgraph_query.unit_key(spelled) != pgraph_query.unit_key(other)
        tests[cu]["temperature"] = V(500, spelled)
        assert run("temperature", other, "ge", 1)[1][cu] == "incompatible_unit", spelled
        assert cu in run("temperature", spelled, "ge", 1)[0], spelled


def test_a_unit_that_is_not_text_is_never_compared_and_never_stops_a_query(doc, spec):
    """A stored value whose unit is a number, a list, an object or a boolean is left out as incompatible_unit; the export
    keeps it as text and stats name it; a filter unit that is not non-empty text is a plan error."""
    for unit in (5, ["MPa"], {"x": 1}, True):
        d = copy.deepcopy(doc)
        for n in d["nodes"]:
            if n["label"] == "CatalyticTest":
                n["props"]["pressure"] = {"status": "present", "value": 2, "unit": unit}
        plan = {"match": {"label": "CatalyticTest", "as": "t"}, "return": ["t.name", "t.pressure"],
                "where": [{"var": "t", "prop": "pressure", "op": "gt", "value": 1, "unit": "MPa"}]}
        res = pgraph_query.run(d, spec, plan)
        assert res["status"] == "missing_context" and res["row_count"] == 0, unit
        assert res["coverage"]["excluded"]["by_reason"] == {"incompatible_unit": 3}, unit
        assert res["excluded"][0]["reason"] == f"incompatible_unit (the value's unit is not text: {type(unit).__name__}; filter in 'MPa')"
        ordered = pgraph_query.run(d, spec, {"match": {"label": "CatalyticTest", "as": "t"}, "return": ["t.name"],
                                             "order_by": [{"prop": "pressure"}]})
        assert ordered["row_count"] == 3
        assert pgraph.stats(d)["units_in_use"]["CatalyticTest"]["pressure"] == {f"(a unit that is not text: {type(unit).__name__})": 3}
    plan = {"match": {"label": "CatalyticTest", "as": "t"}, "return": ["t.name"],
            "where": [{"var": "t", "prop": "pressure", "op": "gt", "value": 1, "unit": "MPa"}]}
    for bad in ([], 5, "", "  ", ["MPa"]):
        with pytest.raises(ScaleError, match="a unit is text"):
            pgraph_query.run(doc, spec, {**plan, "where": [{**plan["where"][0], "unit": bad}]})


def test_a_malformed_value_is_left_out_with_a_reason_never_a_crash(doc, spec):
    """A value that holds no finite number (text, a boolean, NaN, an infinity, an int too large for a float, nothing)
    is not_a_number; a malformed unit or basis is incompatible_unit or other_basis; an absent value's note that is not
    text is no note: each left out with its reason and counted, in match, in a step and through a map path, never an
    exception."""
    bad_values = [{"status": "present", "value": "60", "unit": "%"}, {"status": "present", "value": True, "unit": "%"},
                  {"status": "present", "value": float("nan"), "unit": "%"}, {"status": "present", "value": float("inf"), "unit": "%"},
                  {"status": "present", "value": 10 ** 400, "unit": "%"}, {"status": "present", "unit": "%"},
                  {"status": "present", "lower": "a", "upper": None, "unit": "%"}, {"status": "present", "text_value": "high", "unit": "%"},
                  {"status": "present", "value": [60], "unit": "%"}]
    cu = "ex:t/cu/test"
    for v in bad_values:
        d = copy.deepcopy(doc)
        t = next(n for n in d["nodes"] if n["id"] == cu)
        t["props"]["conversion"] = v
        t["props"]["results"] = {"x": {**v, "target": "ex:t/species/cu"}}
        for where in ([{"var": "t", "prop": "conversion", "op": "ge", "value": 50, "unit": "%"}],
                      [{"var": "t", "prop": "conversion", "op": "eq", "value": 60, "unit": "%"}],
                      [{"var": "t", "prop": "results.*[target=ex:t/species/cu]", "op": "in", "value": [60, 70], "unit": "%"}]):
            res = pgraph_query.run(d, spec, {"match": {"id": cu, "as": "t"}, "where": where, "return": ["t.name"]})
            assert res["status"] == "missing_context" and res["coverage"]["excluded"]["by_reason"] == {"not_a_number": 1}, (v, where)
        step = {"from": "s", "edge": "USES_CATALYST", "direction": "in", "to": "CatalyticTest", "as": "t",
                "where": [{"prop": "conversion", "op": "lt", "value": 50, "unit": "%"}]}
        res = pgraph_query.run(d, spec, {"match": {"id": "ex:t/cu/sample", "as": "s"}, "steps": [step], "return": ["t.name"]})
        assert res["status"] == "missing_context" and res["coverage"]["not_evaluated_in_steps"]["by_reason"] == {"not_a_number": 1}, v
    # a malformed unit or basis on a value that holds a number
    for v, code in (({"status": "present", "value": 60, "unit": None}, "unit_unstated"),
                    ({"status": "present", "value": 60, "unit": ["%"]}, "incompatible_unit"),
                    ({"status": "present", "value": 60, "unit": "%", "basis": ["carbon"]}, "other_basis"),
                    ({"status": "present", "value": 60, "unit": "%", "basis": {"kind": "carbon"}}, "other_basis")):
        d = copy.deepcopy(doc)
        next(n for n in d["nodes"] if n["id"] == cu)["props"]["conversion"] = v
        for extra in ({}, {"basis": "carbon"}):
            res = pgraph_query.run(d, spec, {"match": {"id": cu, "as": "t"}, "return": ["t.name"], "where": [
                {"var": "t", "prop": "conversion", "op": "ge", "value": 50, "unit": "%", **extra}]})
            assert res["coverage"]["excluded"]["by_reason"] == {code: 1}, (v, extra)
    # a plain property that is not a number, under lt/le/gt/ge
    res = pgraph_query.run(doc, spec, {"match": {"label": "Source", "as": "s"}, "return": ["s.name"],
                                       "where": [{"var": "s", "prop": "name", "op": "gt", "value": 1}]})
    assert res["status"] == "missing_context" and res["coverage"]["excluded"]["by_reason"] == {"not_a_number": 3}
    # an absent value whose note is not text: no note, under every op (exists and missing included), never a crash
    for note in (5, 5.5, True, ["x"], {"a": 1}, float("nan"), None):
        d = copy.deepcopy(doc)
        next(n for n in d["nodes"] if n["id"] == cu)["props"]["conversion"] = {
            "status": "not_reported", "missing_reason": "not_stated_in_source", "note": note}
        for f in ({"op": "exists"}, {"op": "missing"}, {"op": "ge", "value": 50, "unit": "%"},
                  {"op": "eq", "value": 60, "unit": "%"}, {"op": "ne", "value": 60, "unit": "%"},
                  {"op": "in", "value": [60], "unit": "%"}, {"op": "eq", "value": "x"}):
            res = pgraph_query.run(d, spec, {"match": {"id": cu, "as": "t"}, "return": ["t.name"],
                                             "where": [{"var": "t", "prop": "conversion", **f}]})
            want = {"exists": ("no_matching_record", {}), "missing": ("answered", {})}.get(
                f["op"], ("missing_context", {"not_reported": 1}))
            assert (res["status"], res["coverage"]["excluded"]["by_reason"]) == want, (note, f)
        assert pgraph_query.absent_reason({"status": "not_reported", "note": note}) == "not_reported"


def test_a_gauge_value_in_the_filters_unit_is_not_an_absolute_pressure(doc, spec):
    """The basis a value states keeps it apart whatever its unit: a gauge pressure recorded in MPa with basis gauge is
    left out of `pressure le 5 MPa` (other_basis) and found by a filter on that basis; a gauge unit is another unit
    (psig is not psi). A basis written only in the reported text is not read: the limitation says so."""
    d = copy.deepcopy(doc)
    props = {n["id"]: n["props"] for n in d["nodes"] if n["label"] == "CatalyticTest"}
    props["ex:t/cu/test"]["pressure"] = {**V(3, "MPa"), "basis": "gauge"}
    props["ex:t/cr/test"]["pressure"] = V(20, "psig")
    props["ex:t/late/test"]["pressure"] = V(3, "MPa", "3 MPa (gauge)")             # the basis only in the reported text
    plan = {"match": {"label": "CatalyticTest", "as": "t"}, "return": ["t.name", "t.pressure"],
            "where": [{"var": "t", "prop": "pressure", "op": "le", "value": 5, "unit": "MPa"}]}
    res = pgraph_query.run(d, spec, plan)
    assert [r["bound"]["t"] for r in res["rows"]] == ["ex:t/late/test"]
    assert {x["record"]: x["reason"] for x in res["excluded"]} == {
        "ex:t/cu/test": "other_basis (the value is on 'gauge'; the filter states no basis)",
        "ex:t/cr/test": "incompatible_unit ('psig', filter in 'MPa')"}
    assert res["coverage"]["compared_in_unit"] == 1
    assert any(x.startswith("1 values were compared in a filter's unit by their number, unit and stated basis alone")
               and "reported text or note" in x and "as_reported and note" in x for x in res["limitations"])
    assert res["rows"][0]["values"]["t.pressure"]["as_reported"] == "3 MPa (gauge)"       # returned as reported
    res = pgraph_query.run(d, spec, {**plan, "where": [{**plan["where"][0], "basis": " gauge "}]})
    assert [r["bound"]["t"] for r in res["rows"]] == ["ex:t/cu/test"]
    res = pgraph_query.run(d, spec, {**plan, "where": [{**plan["where"][0], "basis": "Gauge"}]})   # case is kept
    assert res["rows"] == [] and next(x["reason"] for x in res["excluded"] if x["record"] == "ex:t/cu/test") == \
        "other_basis ('gauge', filter on 'Gauge')"
    assert pgraph_query.run(d, spec, {**plan, "where": [{**plan["where"][0], "unit": "psi", "value": 50}]})["row_count"] == 0
    assert [r["bound"]["t"] for r in pgraph_query.run(d, spec, {**plan, "where": [{**plan["where"][0], "unit": "psig",
                                                                                       "value": 50}]})["rows"]] == ["ex:t/cr/test"]


def test_convert_is_refused_and_nothing_is_converted(doc, spec):
    """Unit conversion is not available (planned with the units proposal): a plan or filter that asks for it is refused,
    `convert: false` is accepted, and a value in another unit of the same quantity is left out, never converted. A
    misstated basis or filter number is a plan error, never an exception."""
    plan = {**CU_PLAN, "where": [{"var": "test", "prop": "temperature", "op": "le", "value": 600, "unit": "K"}]}
    off = pgraph_query.run(doc, spec, plan)
    assert off["status"] == "missing_context" and off["coverage"]["excluded"]["by_reason"] == {"incompatible_unit": 2}
    assert "convertible_left_out" not in off["coverage"] and not any("convert:" in x for x in off["limitations"])
    assert pgraph_query.run(doc, spec, {**plan, "convert": False})["coverage"] == off["coverage"]
    for asked in ({**plan, "convert": True}, {**plan, "where": [{**plan["where"][0], "convert": True}]},
                  {**plan, "convert": "yes"}):
        with pytest.raises(ScaleError, match="convert is not available"):
            pgraph_query.run(doc, spec, asked)
    for f, msg in (({"basis": ""}, "states a basis"), ({"basis": 5}, "states a basis"), ({"basis": None}, "states a basis"),
                   ({"basis": "carbon", "unit": None}, "states a basis"), ({"value": "abc"}, "compares with a number"),
                   ({"value": None}, "compares with a number"), ({"value": float("nan")}, "compares with a number")):
        with pytest.raises(ScaleError, match=msg):
            pgraph_query.run(doc, spec, {**plan, "where": [{**plan["where"][0], **f}]})
    with pytest.raises(ScaleError, match="states a basis"):        # a basis on a filter that compares no number
        pgraph_query.run(doc, spec, {**plan, "where": [{"var": "test", "prop": "name", "op": "exists", "basis": "x"}]})
    assert pgraph_query.run(doc, spec, {**plan, "where": [{**plan["where"][0], "value": "600"}]})["status"] == "missing_context"
    md = pgraph_query.render_markdown(pgraph_query.run(doc, spec, {**plan, "where": [{**plan["where"][0], "unit": "°C"}]}))
    assert "converted for the filter" not in md and "conversions" not in md


def test_coverage_counts_each_stage_and_every_reason_beyond_the_listed_500(doc, spec):
    res = pgraph_query.run(doc, spec, CU_PLAN)
    cov = res["coverage"]
    assert cov["ran"] and cov["candidates"] == 3 and cov["link_types"] == ["USES_CATALYST", "HAS_FORMULATION", "HAS_COMPONENT"]
    assert [(s["kind"], s["rows_in"], s["rows_out"]) for s in cov["steps"]] == [
        ("match", 3, 3), ("step", 3, 3), ("step", 3, 3), ("step", 3, 2), ("limit", 2, 2)]
    assert cov["unfiltered"] is False and "Coverage: 3 candidates" in pgraph_query.render_markdown(res)
    listing = {"match": {"label": "CatalyticTest", "as": "test"}, "return": ["test.name"]}
    res = pgraph_query.run(doc, spec, listing)
    assert res["status"] == "answered" and res["coverage"]["unfiltered"] is True
    assert any("narrows nothing" in x for x in res["limitations"])
    # a step's filter that cannot be evaluated is counted on the step, not listed in excluded
    d = copy.deepcopy(doc)
    next(n for n in d["nodes"] if n["id"] == "ex:t/species/zno")["props"].pop("formula")
    res = pgraph_query.run(d, spec, CU_PLAN)
    assert res["coverage"]["steps"][3]["left_out_by_reason"] == {"not_curated": 1} and res["excluded"] == []
    # more records left out than excluded lists: coverage counts them all
    many = copy.deepcopy(doc)
    for i in range(510):
        many["nodes"].append({"id": f"ex:t/many/{i}", "label": "CatalyticTest",
                              "props": {"name": f"t{i}", "temperature": {"status": "not_reported", "missing_reason": "not_stated_in_source"}}})
    res = pgraph_query.run(many, spec, {"match": {"label": "CatalyticTest", "as": "t", "where": [
        {"prop": "temperature", "op": "le", "value": 400, "unit": "°C"}]}, "return": ["t.name"]})
    assert len(res["excluded"]) == 500 and res["coverage"]["excluded"] == {"total": 510, "listed": 500, "by_reason": {"not_reported": 510}}
    assert any("first 500 of 510" in x for x in res["limitations"])


def test_absent_values_say_whether_anyone_looked(doc, spec):
    d = copy.deepcopy(doc)
    tests = {n["id"]: n for n in d["nodes"] if n["label"] == "CatalyticTest"}
    tests["ex:t/cu/test"]["props"]["temperature"] = {"status": "not_reported", "missing_reason": "not_curated"}
    tests["ex:t/cr/test"]["props"]["temperature"] = {"status": "not_reported", "missing_reason": "ambiguous_in_source"}
    plan = {"match": {"label": "CatalyticTest", "as": "t", "where": [{"prop": "temperature", "op": "le", "value": 200, "unit": "°C"}]}}
    res = pgraph_query.run(d, spec, plan)
    assert res["coverage"]["excluded"]["by_reason"] == {"ambiguous_in_source": 1, "not_curated": 1}



def test_the_answer_has_the_access_of_the_whole_document(doc, spec):
    """An answer's access fails closed: the least open effective stewardship anywhere in the queried document (its
    header and every node and link, whether or not a row shows it), as scale graph filter reads it. Rows carry no
    access of their own; a plan that finds nothing, and one the schema cannot run, carry the document's too."""
    d = copy.deepcopy(doc)
    d["graph"]["stewardship"] = {"access": "public"}
    plan = {**CU_PLAN, "as_of": "2026-10-07"}
    res = pgraph_query.run(d, spec, plan)
    assert res["access"] == {"level": "public", "note": "Every record of the queried document, and its header, is public: "
                                                        "the answer carries no access limit of its own."}
    assert res["rows"] and all("access" not in r and "access_requires" not in r for r in res["rows"])
    assert not any(x.startswith("Access ") for x in res["limitations"])
    # one project-only record that no row shows (a species no test uses): the whole answer is project
    secret = {"id": "ex:t/species/secret", "label": "ChemicalSpecies",
              "props": {"name": "secret species", "formula": "Xx", "stewardship": {"access": "project", "project": "ex:t/project/p"}}}
    d["nodes"].append(secret)
    res = pgraph_query.run(d, spec, plan)
    shown = {i for r in res["rows"] for i in [*r["bound"].values(), *r["links"]]}
    assert secret["id"] not in shown and res["access"]["level"] == "project"
    assert res["access"]["note"].startswith(f"The queried document is not all public: 1 of its {len(d['nodes']) + len(d['links'])} "
                                            "records is less open than public, the least open project.")
    assert any(x.startswith("Access project:") and "`scale graph filter --public`" in x for x in res["limitations"])
    md = pgraph_query.render_markdown(res)
    assert "access: **project**" in md and "Access: The queried document is not all public" in md
    none = pgraph_query.run(d, spec, {**plan, "where": [{"var": "test", "prop": "name", "op": "eq", "value": "no such test"}]})
    assert none["status"] == "no_matching_record" and none["access"]["level"] == "project"
    gap = pgraph_query.run(d, spec, {"match": {"label": "NoSuchLabel", "as": "x"}, "as_of": "2026-10-07"})
    assert gap["status"] == "schema_gap" and gap["access"]["level"] == "project"
    assert any(x.startswith("Access project:") for x in gap["limitations"])
    # an embargo in force is institution, read on the plan's as_of, which the note names; lapsed, its later access
    secret["props"]["stewardship"] = {"access": "embargoed", "embargo_until": "2099-01-01",
                                      "access_after_embargo": "consortium", "contributed_by": ["ex:t/org/lab"]}
    now = pgraph_query.run(d, spec, plan)["access"]
    assert now["level"] == "institution" and "(embargoes read on 2026-10-07)" in now["note"]
    secret["props"]["stewardship"]["embargo_until"] = "2020-01-01"                    # lapsed: its later access
    assert pgraph_query.run(d, spec, plan)["access"]["level"] == "consortium"
    assert pgraph_query.run(d, spec, {**plan, "as_of": "2019-06-01"})["access"]["level"] == "institution"   # not yet then
    # the header alone: every record public, the header not
    d["nodes"].remove(secret)
    for r in d["nodes"] + d["links"]:
        r["props"]["stewardship"] = {"access": "public"}
    d["graph"]["stewardship"] = {"access": "project", "project": "ex:t/project/p"}
    head = pgraph_query.run(d, spec, plan)["access"]
    assert head["level"] == "project" and "not all public: its header is less open than public" in head["note"]
    # a graph that states no stewardship: institution, as the filter reads a missing access; no embargo, so no date
    bare = pgraph_query.run(doc, spec, CU_PLAN)["access"]
    assert bare["level"] == "institution" and "embargo" not in bare["note"]
    assert pgraph_query.run(doc, spec, CU_PLAN) == pgraph_query.run(doc, spec, CU_PLAN)


def test_a_project_only_notice_closes_the_answer_and_the_public_view_answers_publicly(spec):
    """A public document whose retraction notice is project-only: every answer from it is project, with or without
    evidence (the notice decides an evidence item's source_status and whether a row is left out). The same query on
    the public view (scale graph filter --public) is public, and the notice's effect is absent there: the source
    reads current_or_unknown and its row is not left out."""
    d = load_doc(X / "source-lifecycle/retracted-source.json")
    sp = pgraph.load_spec(pgraph.pinned(GRAPH_MANIFEST, d["graph"]["schema_version"]))
    notice, p = "ex:exmpl/lifecycle-example/source/retraction-notice-b", "ex:exmpl/project/examples"
    zncr = "ex:exmpl/lifecycle-example/test/zncr"
    proj = {"access": "project", "project": p}
    next(n for n in d["nodes"] if n["id"] == notice)["props"]["stewardship"] = dict(proj)
    for e in d["links"]:
        if e["type"] == "RETRACTS" or (e["type"] == "REPORTED_IN" and e["target"] == notice):
            e["props"]["stewardship"] = dict(proj)
    assert d["graph"]["stewardship"]["access"] == "public" and pgraph.validate(d, sp).errors == []
    plan = {"match": {"label": "CatalyticTest", "as": "t"}, "return": ["t.name"], "as_of": "2026-10-07"}
    for extra in ({}, {"evidence": True}, {"include_retracted": True}, {"evidence": True, "include_retracted": True}):
        res = pgraph_query.run(d, sp, {**plan, **extra})
        assert res["access"]["level"] == "project" and all("access" not in r for r in res["rows"]), extra
        assert any(x.startswith("Access project:") for x in res["limitations"]), extra
    res = pgraph_query.run(d, sp, plan)
    assert [x["record"] for x in res["excluded"]] == [zncr]           # left out on the notice's word
    pub = pgraph.filter_for(d, [], "2026-10-07")
    assert notice not in {n["id"] for n in pub["nodes"]}
    res = pgraph_query.run(pub, sp, {**plan, "evidence": True})
    assert res["access"]["level"] == "public" and not any(x.startswith("Access ") for x in res["limitations"])
    row = next(r for r in res["rows"] if r["bound"]["t"] == zncr)     # not left out: the view holds no notice
    assert {e["source_status"] for e in row["evidence"]} == {"current_or_unknown"} and res["excluded"] == []


def test_a_second_hand_note_names_no_title_unless_the_document_is_public(doc, spec):
    """A row resting only on second-hand evidence names its citing sources: by title when the whole document is
    public, by id otherwise (whichever record makes it less open), with or without evidence."""
    d = copy.deepcopy(doc)
    d["graph"]["stewardship"] = {"access": "public"}
    for r in d["nodes"] + d["links"]:
        for e in r["props"].get("evidence") or []:
            if e["source"] == LATE:
                e["evidence_type"] = "ECO:0000033"
    late_of = lambda res: next(r for r in res["rows"] if r["bound"]["test"] == "ex:t/late/test")   # noqa: E731
    assert late_of(pgraph_query.run(d, spec, CU_PLAN))["second_hand"]["note"] == "second-hand (cited by Late paper)"
    for restricted in (LATE, "ex:t/species/zno"):            # the citing source itself, or a record no row shows
        d2 = copy.deepcopy(d)
        next(n for n in d2["nodes"] if n["id"] == restricted)["props"]["stewardship"] = {
            "access": "institution", "contributed_by": ["ex:t/org/lab"]}
        for ev_flag in (False, True):
            res = pgraph_query.run(d2, spec, {**CU_PLAN, "evidence": ev_flag})
            assert late_of(res)["second_hand"] == {"cited_by": [LATE], "note": f"second-hand (cited by {LATE})"}
            assert res["access"]["level"] == "institution", (restricted, ev_flag)
            assert "Late paper" not in json.dumps(res) and "Late paper" not in pgraph_query.render_markdown(res)


def test_second_hand_evidence_is_named_and_can_be_left_out(doc, spec):
    d = copy.deepcopy(doc)
    d["graph"]["stewardship"] = {"access": "public"}         # all public: the note may name its sources by title
    for r in d["nodes"] + d["links"]:
        for ev in r["props"].get("evidence") or []:
            if ev["source"] == LATE:
                ev["evidence_type"] = "ECO:0000033"            # the 1962 paper reports another work's result
    next(n for n in d["nodes"] if n["id"] == SRC)["props"]["peer_reviewed"] = False
    res = pgraph_query.run(d, spec, CU_PLAN)
    late = next(r for r in res["rows"] if r["bound"]["test"] == "ex:t/late/test")
    cu = next(r for r in res["rows"] if r["bound"]["test"] == "ex:t/cu/test")
    assert late["second_hand"] == {"cited_by": [LATE], "note": "second-hand (cited by Late paper)"} and "second_hand" not in cu
    assert all(e["second_hand"] and e["source_kind"] == "article" and e["source_peer_reviewed"] is None for e in late["evidence"])
    assert all(e["source_kind"] == "patent" and e["source_peer_reviewed"] is False and "second_hand" not in e for e in cu["evidence"])
    assert res["coverage"]["second_hand_rows"] == 1 and any("second-hand" in x for x in res["limitations"])
    md = pgraph_query.render_markdown(res)
    assert "second-hand (cited by Late paper)" in md and "patent, not peer reviewed" in md
    own = pgraph_query.run(d, spec, {**CU_PLAN, "own_work_only": True})
    assert [r["bound"]["test"] for r in own["rows"]] == ["ex:t/cu/test"]
    assert own["excluded"][0]["reason"].startswith("second_hand_only") and own["excluded"][0]["sources"] == [LATE]
    only = {**CU_PLAN, "own_work_only": True, "where": [{"var": "test", "prop": "name", "op": "eq", "value": "late test"}]}
    assert pgraph_query.run(d, spec, only)["status"] == "no_matching_record"      # left out on purpose, not missing context


def test_paths_address_map_and_list_entries(doc, spec):
    d = copy.deepcopy(doc)
    t = next(n for n in d["nodes"] if n["id"] == "ex:t/cu/test")
    t["props"]["results"] = {"selectivity_cu": {**V(80, "%"), "target": "ex:t/species/cu"},
                             "selectivity_zno": {**V(20, "%"), "target": "ex:t/species/zno"},
                             "methanol_rate": V(135, "cc/h", "135 cc. of methanol per hour")}
    assert pgraph.validate(d, spec).errors == []
    by_target = {"var": "test", "prop": "results.*[target=ex:t/species/cu]", "op": "ge", "value": 50, "unit": "%"}
    res = pgraph_query.run(d, spec, {**CU_PLAN, "where": [by_target],
                                     "return": ["test.results.methanol_rate", "test.results.*[target=ex:t/species/zno]",
                                                "test.results.no_such_key"]})
    assert [r["bound"]["test"] for r in res["rows"]] == ["ex:t/cu/test"]
    vals = res["rows"][0]["values"]
    assert vals["test.results.methanol_rate"]["value"] == 135 and vals["test.results.no_such_key"] is None
    assert vals["test.results.*[target=ex:t/species/zno]"] == {"selectivity_zno": {**V(20, "%"), "target": "ex:t/species/zno"}}
    assert {"record": "ex:t/cu/test", "field": "test.results.no_such_key",          # the map is there, the key is not
            "reason": "no_matching_entry (results.no_such_key)"} in res["missing_context"]
    assert {x["reason"].split(" ")[0] for x in res["excluded"]} == {"not_curated"}           # the late test has no results
    other = {**by_target, "prop": "results.*[target=ex:t/species/h2s]"}
    res = pgraph_query.run(d, spec, {**CU_PLAN, "where": [other]})
    assert {x["record"]: x["reason"].split(" ")[0] for x in res["excluded"]}["ex:t/cu/test"] == "no_matching_entry"
    with pytest.raises(ScaleError, match="states no unit"):
        pgraph_query.run(d, spec, {**CU_PLAN, "where": [{**by_target, "unit": None}]})
    with pytest.raises(ScaleError, match="not a map or list"):
        pgraph_query.run(d, spec, {**CU_PLAN, "where": [{**by_target, "prop": "temperature.value"}]})
    with pytest.raises(ScaleError, match="cannot read the property path"):
        pgraph_query.run(d, spec, {**CU_PLAN, "return": ["test.results[target=]"]})
    gap = pgraph_query.run(d, spec, {**CU_PLAN, "return": ["test.outcomes.methanol_rate"]})
    assert gap["status"] == "schema_gap" and gap["schema_gaps"] == ["CatalyticTest.outcomes is not declared"]
    rec = {"props": {"levels": [{**V(1, "MPa"), "variable": "ex:v/p"}, {**V(2, "MPa"), "variable": "ex:v/q"}]}}
    assert pgraph_query.returned(rec, "levels.1")["value"] == 2
    assert pgraph_query.returned(rec, "levels.*[variable=ex:v/q]") == [{**V(2, "MPa"), "variable": "ex:v/q"}]
    assert pgraph_query.check(rec, {"prop": "levels.*", "op": "gt", "value": 1.5, "unit": "MPa"})[0] is True


def test_not_stated_is_no_unit_never_one_to_compare_in(doc, spec):
    """`not stated`, the unit a curator writes for a number the source prints without one (in any case and spacing),
    states no unit: its values are left out as unit_unstated, never compared in one another's company, a filter in it
    is a plan error, and stats count it under (no unit)."""
    d = copy.deepcopy(doc)
    tests = {n["id"]: n["props"] for n in d["nodes"] if n["label"] == "CatalyticTest"}
    cu, cr, late = "ex:t/cu/test", "ex:t/cr/test", "ex:t/late/test"
    tests[cu]["pressure"] = V(5, "not stated", "5 bar")
    tests[cr]["pressure"] = V(5, "Not  Stated", "5 MPa")
    tests[late]["pressure"] = V(2, " NOT STATED ", "2 atm")
    assert pgraph.validate(d, spec).errors == []
    plan = {"match": {"label": "CatalyticTest", "as": "t"}, "return": ["t.name"],
            "where": [{"var": "t", "prop": "pressure", "op": "ge", "value": 3, "unit": "MPa"}]}
    res = pgraph_query.run(d, spec, plan)
    assert res["status"] == "missing_context" and res["rows"] == []
    assert res["coverage"]["excluded"]["by_reason"] == {"unit_unstated": 3} and res["coverage"]["compared_in_unit"] == 0
    assert {x["reason"] for x in res["excluded"]} == {"unit_unstated (the value states no unit; filter in 'MPa')"}
    for placeholder in ("not stated", "Not Stated", "  NOT   STATED "):       # never a unit to plan on
        with pytest.raises(ScaleError, match="the unit 'not stated'"):
            pgraph_query.run(d, spec, {**plan, "where": [{**plan["where"][0], "unit": placeholder}]})
        with pytest.raises(ScaleError, match="the unit 'not stated'"):
            pgraph_query.comparable(V(5, "MPa"), placeholder)
        assert pgraph.states_no_unit(placeholder)
    bare = copy.deepcopy(d)                                                     # the plan check refuses it before any value is read
    for n in bare["nodes"]:
        if n["label"] == "CatalyticTest":
            n["props"].pop("pressure", None)
    with pytest.raises(ScaleError, match="the unit 'not stated'"):
        pgraph_query.run(bare, spec, {**plan, "where": [{**plan["where"][0], "unit": "not stated"}]})
    for unit in ("not stated bar", "notstated", "stated", "MPa"):                # another unit, spelled as written
        assert not pgraph.states_no_unit(unit)
    assert pgraph.stats(d)["units_in_use"]["CatalyticTest"]["pressure"] == {"(no unit)": 3}
    tests[cu]["pressure"] = V(4, "MPa")                                         # a stated unit is still compared
    res = pgraph_query.run(d, spec, plan)
    assert [r["bound"]["t"] for r in res["rows"]] == [cu] and res["coverage"]["excluded"]["by_reason"] == {"unit_unstated": 2}
    assert pgraph.stats(d)["units_in_use"]["CatalyticTest"]["pressure"] == {"(no unit)": 2, "MPa": 1}


def test_a_query_and_a_search_read_embargoes_on_the_one_clock(doc, spec, tmp_path, capsys, monkeypatch):
    """A query's access, a plan's as_of, and a search's access (command line and agent tool) read embargoes on
    pgraph.embargo_today, the earlier of the local and the UTC date, as the filter and the exports do: at 21:00 on 7
    October 2026 four hours behind UTC (8 October in UTC) and at 09:00 on 8 October thirteen hours ahead (7 October in
    UTC), a record embargoed until 2026-10-07 still holds; on 8 October in both it has lapsed."""
    import datetime

    from scale.api import ScaleToolkit
    from scale.cli import main
    d = copy.deepcopy(doc)
    d["graph"]["stewardship"] = {"access": "public", "licence": "CC-BY-4.0"}
    next(n for n in d["nodes"] if n["id"] == "ex:t/cu/test")["props"]["stewardship"] = {
        "access": "embargoed", "embargo_until": "2026-10-07", "access_after_embargo": "public"}
    f = tmp_path / "emb.json"
    f.write_text(json.dumps(d))
    assert main(["graph", "index", str(f)]) in (0, None)
    capsys.readouterr()
    kit = ScaleToolkit(repo=REPO, workspace=tmp_path)
    plan = {"match": {"label": "CatalyticTest", "as": "t"}, "return": ["t.name"]}
    tz = datetime.timezone
    for now, day, level in (
            (datetime.datetime(2026, 10, 7, 21, 0, tzinfo=tz(datetime.timedelta(hours=-4))), "2026-10-07", "institution"),
            (datetime.datetime(2026, 10, 8, 9, 0, tzinfo=tz(datetime.timedelta(hours=13))), "2026-10-07", "institution"),
            (datetime.datetime(2026, 10, 8, 12, 0, tzinfo=tz(datetime.timedelta(hours=-4))), "2026-10-08", "public")):
        monkeypatch.setattr(pgraph, "clock", lambda now=now: now)
        assert pgraph.embargo_today() == day
        assert pgraph_query.run(d, spec, plan)["access"]["level"] == level, now
        assert pgraph_query.run(d, spec, {**plan, "as_of": "2026-10-09"})["access"]["level"] == level   # never later
        assert pgraph_query.run(d, spec, {**plan, "as_of": "2026-10-07"})["access"]["level"] == "institution"
        assert main(["graph", "search", str(f), "copper zinc catalyst", "--mode", "keyword"]) in (0, None)
        assert json.loads(capsys.readouterr().out)["access"]["level"] == level, now
        assert kit.call("scale_search", {"path": "emb.json", "query": "copper zinc catalyst"})["access"]["level"] == level


def test_stats_count_units_in_use_and_link_patterns(doc):
    d = copy.deepcopy(doc)
    next(n for n in d["nodes"] if n["id"] == "ex:t/cu/test")["props"]["results"] = {"methanol_rate": V(135, "cc/h")}
    s = pgraph.stats(d)
    assert s["units_in_use"]["CatalyticTest"] == {"pressure": {"atm": 3}, "results.methanol_rate": {"cc/h": 1},
                                                  "temperature": {"°C": 3}}
    assert {"source": "CatalyticTest", "type": "USES_CATALYST", "target": "CatalystSample", "count": 3} in s["link_patterns"]
    assert s["link_patterns"] == sorted(s["link_patterns"], key=lambda p: (-p["count"], p["source"], p["type"], p["target"]))


def test_a_space_velocity_on_the_hydrogen_is_not_compared_with_one_on_the_feed(doc, spec):
    """A space velocity whose stated basis names a gas is compared only with a filter on that basis; one whose unit names
    the gas is in another unit. Nothing is read from the wording beyond equality: a basis is the filter's or not."""
    d = copy.deepcopy(doc)
    props = {n["id"]: n["props"] for n in d["nodes"] if n["label"] == "CatalyticTest"}
    props["ex:t/cu/test"]["space_velocity"] = {**V(12000, "h-1"), "basis": "counted on the hydrogen fed"}
    props["ex:t/cr/test"]["space_velocity"] = V(12000, "vol H2/vol catalyst/h")
    props["ex:t/late/test"]["space_velocity"] = V(12000, "h-1")
    plan = {"match": {"label": "CatalyticTest", "as": "t"}, "return": ["t.name"],
            "where": [{"var": "t", "prop": "space_velocity", "op": "ge", "value": 10000, "unit": "h-1"}]}
    res = pgraph_query.run(d, spec, plan)
    assert [r["bound"]["t"] for r in res["rows"]] == ["ex:t/late/test"]
    assert res["coverage"]["excluded"]["by_reason"] == {"incompatible_unit": 1, "other_basis": 1}
    res = pgraph_query.run(d, spec, {**plan, "where": [{**plan["where"][0], "basis": "counted on the hydrogen fed"}]})
    assert [r["bound"]["t"] for r in res["rows"]] == ["ex:t/cu/test"]
    res = pgraph_query.run(d, spec, {**plan, "where": [{**plan["where"][0], "basis": "H2"}]})       # another wording
    assert res["row_count"] == 0 and res["coverage"]["excluded"]["by_reason"] == {"incompatible_unit": 1, "other_basis": 2}


def test_a_failing_entry_never_hides_one_that_cannot_be_compared(doc, spec):
    """A filter on several entries holds when one passes and fails only when every one fails: an entry that fails next
    to one in another unit, not reported or a one-sided bound leaves the record out with that entry's reason
    (missing_context), never as failing (no_matching_record)."""
    cu = "ex:t/species/cu"
    f = {"var": "test", "prop": f"results.*[target={cu}]", "op": "ge", "value": 50, "unit": "%"}
    plan = {"match": {"id": "ex:t/cu/test", "as": "test"}, "where": [f], "return": ["test.name"]}
    yield_ = {**V(10, "%"), "target": cu}
    for other, code in (({**V(80, "mol%"), "target": cu}, "incompatible_unit"),
                        ({"status": "not_reported", "missing_reason": "not_stated_in_source", "target": cu}, "not_reported"),
                        ({**V(60, "%", "at most 60 %"), "bound": "upper", "target": cu}, "one_sided_bound"),
                        ({**V(0.8, "1"), "target": cu}, "incompatible_unit"),
                        ({**V(60, "%"), "target": cu}, None), ({**V(20, "%"), "target": cu}, False)):
        d = copy.deepcopy(doc)
        next(n for n in d["nodes"] if n["id"] == "ex:t/cu/test")["props"]["results"] = {"methanol_yield": yield_,
                                                                                   "methanol_selectivity": other}
        assert pgraph.validate(d, spec).errors == []
        res = pgraph_query.run(d, spec, plan)
        if code is None:
            assert res["status"] == "answered", other
        elif code is False:                    # every entry fails: the record fails, nothing missing
            assert res["status"] == "no_matching_record" and res["coverage"]["excluded"]["total"] == 0
        else:
            assert res["status"] == "missing_context", other
            assert res["coverage"]["excluded"]["by_reason"] == {code: 1}, other
        # the same filter on a required step: the link's test is not evaluated, never taken as failing
        step = {"from": "sample", "edge": "USES_CATALYST", "direction": "in", "to": "CatalyticTest", "as": "test",
                "where": [{k: v for k, v in f.items() if k != "var"}]}
        res = pgraph_query.run(d, spec, {"match": {"id": "ex:t/cu/sample", "as": "sample"}, "steps": [step],
                                         "return": ["test.name"]})
        if code is None:
            assert res["status"] == "answered", other
        elif code is False:
            assert res["status"] == "no_matching_record" and "left_out_by_reason" not in res["coverage"]["steps"][1]
        else:
            assert res["status"] == "missing_context" and res["coverage"]["steps"][1]["left_out_by_reason"] == {code: 1}
            assert res["coverage"]["steps"][1]["rows_not_evaluated"] == 1, other
    rec = {"props": {"results": {"a": yield_, "b": {"status": "not_reported", "target": cu}}}}
    assert pgraph_query.check(rec, f) == (None, "not_reported")
    assert pgraph_query.check({"props": {"results": {"a": yield_}}}, f) == (False, None)


def test_a_withheld_value_or_entry_is_neither_there_nor_missing(doc, spec):
    """On a document scale graph filter made, a value or an entry the filter withheld reads as withheld, whether it is
    filtered on, returned or asked whether it exists (exists and missing cannot be decided on it); a map or list entry
    that is not there reads as no_matching_entry, and, the document being filtered, a limitation says that such an
    absence may be a reference the filter removed. A numeric filter on a whole list of values is a plan error."""
    from test_schema_identity import _two_source_doc
    d, tid, meoh = _two_source_doc()
    sp = pgraph.load_spec(pgraph.pinned(GRAPH_MANIFEST, d["graph"]["schema_version"]))
    out = pgraph.filter_for(d, [], "2026-10-07")
    m = {"label": "CatalyticTest", "as": "t"}

    def run(where=None, ret=("t.name",)):
        return pgraph_query.run(out, sp, {"match": {**m, **({"where": where} if where else {})}, "return": list(ret)})
    for w in ({"prop": f"results.*[target={meoh}]", "op": "ge", "value": 0, "unit": "g/h"},
              {"prop": "results.methanol_production", "op": "exists"}, {"prop": "results.*", "op": "missing"},
              {"prop": "temperature", "op": "exists"}, {"prop": "temperature", "op": "missing"},
              {"prop": "energy_yield.0", "op": "ge", "value": 0, "unit": "g/kWh"}):
        res = run([w])
        assert res["status"] == "missing_context" and res["coverage"]["excluded"]["by_reason"] == {"withheld": 1}, w
    assert run([{"prop": "energy_yield.*", "op": "ge", "value": 1, "unit": "g/kWh"}])["status"] == "answered"  # one passes
    with pytest.raises(ScaleError, match="compares a whole list"):
        run([{"prop": "energy_yield", "op": "ge", "value": 0, "unit": "g/kWh"}])
    res = run(ret=["t.results.methanol_production", f"t.results.*[target={meoh}]", "t.results.no_such_key"])
    assert [x["reason"] for x in res["missing_context"]] == ["withheld", "no_matching_entry (results.no_such_key)"]
    assert res["coverage"]["filtered_for"] == out["graph"]["filtered_for"]
    assert any(x.startswith("This document was filtered for a viewer") for x in res["limitations"])
    # the same plan on the unfiltered document: no such limitation
    res = pgraph_query.run(d, sp, {"match": m, "return": ["t.results.no_such_key"]})
    assert "filtered_for" not in res["coverage"] and not any("filtered for a viewer" in x for x in res["limitations"])


def test_coverage_counts_a_record_left_out_of_several_rows_once(doc, spec):
    """A record that several rows hold (a test with two catalyst samples) is left out once per reason: excluded lists it
    once and coverage counts it once, as the same filter in match.where does; a value compared in a filter's unit is
    counted once, and so is a step's comparison on a link several rows reach."""
    d = copy.deepcopy(doc)
    d["links"].append({"id": "ex:t/cu/test/uses-cr", "source": "ex:t/cu/test", "target": "ex:t/cr/sample",
                       "type": "USES_CATALYST", "props": {"evidence": [ev(SRC, "p. 2", "x")], "origin": "synthetic"}})
    d["links"].append({"id": "ex:t/cr/test/uses-cu", "source": "ex:t/cr/test", "target": "ex:t/cu/sample",
                       "type": "USES_CATALYST", "props": {"evidence": [ev(SRC, "p. 2", "x")], "origin": "synthetic"}})
    tests = {n["id"]: n for n in d["nodes"] if n["label"] == "CatalyticTest"}
    tests["ex:t/cu/test"]["props"]["temperature"] = {"status": "not_reported", "missing_reason": "not_stated_in_source"}
    tests["ex:t/cr/test"]["props"]["temperature"] = V(653.15, "K")
    f = {"var": "test", "prop": "temperature", "op": "ge", "value": 300, "unit": "°C"}
    step = {"from": "test", "edge": "USES_CATALYST", "to": "CatalystSample", "as": "sample"}
    res = pgraph_query.run(d, spec, {"match": {"label": "CatalyticTest", "as": "test"}, "steps": [step], "where": [f],
                                     "return": ["test.name"]})
    assert res["coverage"]["steps"][1]["rows_out"] == 5          # two rows each for the cu and cr tests
    assert res["coverage"]["excluded"] == {"total": 2, "listed": 2, "by_reason": {"incompatible_unit": 1, "not_reported": 1}}
    assert sorted(x["record"] for x in res["excluded"]) == ["ex:t/cr/test", "ex:t/cu/test"]
    assert any(x.startswith("2 records were left out") for x in res["limitations"])
    same = pgraph_query.run(d, spec, {"match": {"label": "CatalyticTest", "as": "test", "where": [{k: v for k, v in f.items() if k != "var"}]},
                                      "return": ["test.name"]})
    assert same["coverage"]["excluded"] == res["coverage"]["excluded"]
    # two filters on one value, over the same fan-out: each value compared, or left out, is counted once
    two = [f, {**f, "op": "le", "value": 400}]
    res = pgraph_query.run(d, spec, {"match": {"label": "CatalyticTest", "as": "test"}, "steps": [step], "where": two,
                                     "return": ["test.name"]})
    assert res["coverage"]["excluded"]["total"] == 2 and res["coverage"]["compared_in_unit"] == 1     # the late test
    kelvin = [{**f, "unit": "K", "value": 600}, {**f, "op": "le", "unit": "K", "value": 700}]
    res = pgraph_query.run(d, spec, {"match": {"label": "CatalyticTest", "as": "test"}, "steps": [step], "where": kelvin,
                                     "return": ["test.name"]})
    assert res["coverage"]["compared_in_unit"] == 1 and res["row_count"] == 2      # the cr test's 653.15 K, in two rows
    assert res["coverage"]["excluded"]["by_reason"] == {"incompatible_unit": 1, "not_reported": 1}
    # a record left out by two filters for one reason is one entry: the cu test, bound as test (its temperature not
    # reported) and, through a shared sample, as test2 (its pressure not reported)
    tests["ex:t/cu/test"]["props"]["pressure"] = {"status": "not_reported", "missing_reason": "not_stated_in_source"}
    back = {"from": "sample", "edge": "USES_CATALYST", "direction": "in", "to": "CatalyticTest", "as": "test2"}
    both = [f, {"var": "test2", "prop": "pressure", "op": "ge", "value": 1, "unit": "atm"}]
    res = pgraph_query.run(d, spec, {"match": {"label": "CatalyticTest", "as": "test"}, "steps": [step, back], "where": both,
                                     "return": ["test.name"]})
    assert sorted(x["record"] for x in res["excluded"]) == ["ex:t/cr/test", "ex:t/cu/test"]      # the cu test once
    assert res["coverage"]["excluded"]["by_reason"] == {"incompatible_unit": 1, "not_reported": 1}
    # a step from the test, after a step that gave it two rows: each record compared counted once (3 samples, reached
    # by 9 comparisons over the 5 rows)
    batch = {"from": "test", "edge": "USES_CATALYST", "to": "CatalystSample", "as": "s2", "optional": True,
             "where": [{"prop": "batch_identifier", "op": "eq", "value": "B1"}]}
    res = pgraph_query.run(d, spec, {"match": {"label": "CatalyticTest", "as": "test"}, "steps": [step, batch],
                                     "return": ["test.name"]})
    assert res["coverage"]["steps"][2]["left_out_by_reason"] == {"not_curated": 3}
    # a returned field missing on a record that several rows hold: one missing_context entry, counted once
    res = pgraph_query.run(d, spec, {"match": {"label": "CatalyticTest", "as": "test"}, "steps": [step],
                                     "return": ["test.name", "test.pressure"]})
    assert res["row_count"] == 5 and [x["record"] for x in res["missing_context"]] == ["ex:t/cu/test"]
    assert res["coverage"]["missing_context"] == {"total": 1, "listed": 1}
    assert "1 returned fields are not reported or not curated (each record's field once); see missing_context." \
        in res["limitations"]
    # one record bound by two variables (the cu test as test and, back through a shared sample, as test2): its missing
    # pressure is listed once, under the first path that returns it, and makes one gap
    res = pgraph_query.run(d, spec, {"match": {"label": "CatalyticTest", "as": "test"}, "steps": [step, back],
                                     "return": ["test.pressure", "test2.pressure"]})
    cu = [x for x in res["missing_context"] if x["record"] == "ex:t/cu/test"]
    assert len(cu) == 1 and cu[0]["field"] in ("test.pressure", "test2.pressure") and cu[0]["reason"] == "not_reported"
    assert res["coverage"]["missing_context"]["total"] == len(res["missing_context"]) == 1
    from scale.gaps import gaps_from_query
    assert [g["records"] for g in gaps_from_query(res)] == [["ex:t/cu/test"]]


def _embargoed_late_source(doc: dict) -> dict:
    """The public test document whose 1962 paper, the only source of the late test, is embargoed until 2099 (then
    public) and reports another work's result, under a title that must not leave while the embargo holds."""
    d = copy.deepcopy(doc)
    d["graph"]["stewardship"] = {"access": "public"}
    for r in d["nodes"] + d["links"]:
        for e in r["props"].get("evidence") or []:
            if e["source"] == LATE:
                e["evidence_type"] = "ECO:0000033"
    late = next(n for n in d["nodes"] if n["id"] == LATE)
    late["props"].update(name="Embargoed title", title="Embargoed title",
                         stewardship={"access": "embargoed", "embargo_until": "2099-01-01",
                                      "access_after_embargo": "public", "contributed_by": ["ex:t/org/lab"]})
    return d


def test_a_later_or_malformed_as_of_never_opens_an_embargo(doc, spec):
    """A plan's as_of is an ISO date (YYYY-MM-DD; a YAML date too); anything else is a plan error. Embargoes are read
    on it or today, whichever is earlier, so a later as_of never opens an embargo still in force: the answer stays
    institution and its second-hand note names the embargoed source by id, never by its title, in the result and the
    markdown alike. An earlier as_of may keep an embargo that has lapsed today closed."""
    import datetime

    d = _embargoed_late_source(doc)
    today = datetime.date.today().isoformat()
    for as_of in (None, "2026-10-07", "2100-01-01", datetime.date(2100, 1, 1)):
        plan = {**CU_PLAN, **({"as_of": as_of} if as_of else {})}
        res = pgraph_query.run(d, spec, plan)
        late = next(r for r in res["rows"] if r["bound"]["test"] == "ex:t/late/test")
        assert res["access"]["level"] == "institution", as_of
        assert late["second_hand"]["note"] == f"second-hand (cited by {LATE})", as_of
        assert "Embargoed title" not in json.dumps(res) and "Embargoed title" not in pgraph_query.render_markdown(res)
        if as_of in ("2100-01-01", datetime.date(2100, 1, 1)):
            assert f"(embargoes read on {today})" in res["access"]["note"]
    for bad in ("zzz", 2100, "9", "tomorrow", "2099-01-01T00", "2100", "2026-02-30", ""):
        with pytest.raises(ScaleError, match="as_of"):
            pgraph_query.run(d, spec, {**CU_PLAN, "as_of": bad})
    # lapsed today: public, the note names the title; read on a day before it lapsed: institution again
    next(n for n in d["nodes"] if n["id"] == LATE)["props"]["stewardship"]["embargo_until"] = "2020-06-30"
    res = pgraph_query.run(d, spec, CU_PLAN)
    assert res["access"]["level"] == "public" and any(
        r["second_hand"]["note"] == "second-hand (cited by Embargoed title)" for r in res["rows"] if r.get("second_hand"))
    assert pgraph_query.run(d, spec, {**CU_PLAN, "as_of": "2020-06-30"})["access"]["level"] == "institution"


def test_a_public_view_of_a_project_graph_answers_publicly_and_is_never_sent_back_to_the_filter(doc, spec):
    """A project graph whose Cu path is public in its own right: its answers are project, and the limitation sends the
    reader to the public view. That view (scale graph filter --public) declares its audience in its header, so the
    same query on it is public. A public view made before the filter did so kept the project header: its answer is
    project, and the limitation says to make the view again from the original document, never to filter the view."""
    d = copy.deepcopy(doc)
    d["graph"]["stewardship"] = {"access": "project", "project": "ex:t/project/p", "contributed_by": ["ex:t/org/lab"]}
    open_ = {"ex:t/cu/test", "ex:t/cu/sample", "ex:t/cu/catalyst", "ex:t/species/cu", SRC}
    for r in d["nodes"]:
        if r["id"] in open_:
            r["props"]["stewardship"] = {"access": "public"}
    for r in d["links"]:
        if r["source"] in open_ and r["target"] in open_:
            r["props"]["stewardship"] = {"access": "public"}
    plan = {**CU_PLAN, "as_of": "2026-10-07"}
    res = pgraph_query.run(d, spec, plan)
    assert res["access"]["level"] == "project"
    advice = next(x for x in res["limitations"] if x.startswith("Access project:"))
    assert "For a public answer, run the query on the document `scale graph filter --public` makes" in advice
    view = pgraph.filter_for(d, [], "2026-10-07")
    assert view["graph"]["stewardship"]["access"] == "public" and len(view["nodes"]) == 5
    res = pgraph_query.run(view, spec, plan)
    assert res["access"]["level"] == "public" and [r["bound"]["test"] for r in res["rows"]] == ["ex:t/cu/test"]
    assert not any(x.startswith("Access ") for x in res["limitations"])
    old = {**view, "graph": {**view["graph"], "stewardship": d["graph"]["stewardship"]}}      # an earlier filter's view
    res = pgraph_query.run(old, spec, plan)
    advice = next(x for x in res["limitations"] if x.startswith("Access project:"))
    assert res["access"]["level"] == "project" and "already the public view" in advice
    assert "make the public view again from the original document" in advice and "For a public answer, run" not in advice
    # a view for one reader the header cannot name (a person): its answers go to that reader; the advice names the
    # public view of the original document
    d["nodes"].append({"id": "ex:t/person/a", "label": "Person", "props": {"name": "a person", "origin": "synthetic"}})
    person = pgraph.filter_for(d, ["ex:t/person/a"], "2026-10-07")
    advice = next(x for x in pgraph_query.run(person, spec, plan)["limitations"] if x.startswith("Access "))
    assert "a view `scale graph filter` made for a reader" in advice and "of the original document" in advice


def test_a_malformed_stewardship_reads_as_institution_and_the_query_answers(doc, spec):
    """A stewardship that is not an object, on a record or the header (the validator reports it), is read as
    institution: the answer is institution, never public, and the query runs instead of raising."""
    for bad in ("public", ["public"], 5):
        d = copy.deepcopy(doc)
        d["graph"]["stewardship"] = {"access": "public"}
        next(n for n in d["nodes"] if n["id"] == OLD)["props"]["stewardship"] = bad
        res = pgraph_query.run(d, spec, CU_PLAN)
        assert res["status"] == "answered" and res["access"]["level"] == "institution", bad
        d["graph"]["stewardship"] = bad
        assert pgraph_query.run(d, spec, CU_PLAN)["access"]["level"] == "institution", bad


def test_an_evidence_index_is_searched_only_for_the_document_it_was_built_from(tmp_path, capsys, doc, spec):
    """An index records the digest of the document it was built from. query (text) and search use an index only for
    that document, or one holding exactly its evidence quotes; an index of the unfiltered document is refused for its
    public view, whose project-only quote it holds, and its hits never choose a row there. search answers carry the
    document's access, as query answers do."""
    from scale.cli import main
    from scale.passages import graph_sha256, load_for

    d = copy.deepcopy(doc)
    d["graph"]["stewardship"] = {"access": "public"}
    next(n for n in d["nodes"] if n["id"] == LATE)["props"]["stewardship"] = {"access": "project", "project": "ex:t/project/p"}
    for r in d["nodes"] + d["links"]:
        for e in r["props"].get("evidence") or []:
            if e["source"] == LATE:
                e["quote"] = "zeolite xylophone phrase"
    full = Index.build(evidence_items(d), graph_sha256=graph_sha256(d))
    view = pgraph.filter_for(d, [], "2026-10-07")
    plan = {**CU_PLAN, "as_of": "2026-10-07",
            "text": {"query": "zeolite xylophone", "vars": ["test"], "mode": "keyword", "min_score": 0.01}}
    res = pgraph_query.run(view, spec, plan, full)          # the run itself reads only the view's own quotes
    assert res["rows"] == [] and res["access"]["level"] == "public"
    with pytest.raises(ScaleError, match="was built from another document"):
        full.check_for(view)
    assert full.check_for(d) is full
    # through the command line: the view beside the full document's index is refused; its own index is used
    f, v = tmp_path / "full.json", tmp_path / "view.json"
    f.write_text(json.dumps(d))
    v.write_text(json.dumps(view))
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    assert main(["graph", "index", str(f)]) in (0, None)
    assert json.loads(capsys.readouterr().out)["graph_sha256"] == graph_sha256(d)
    for args in (["graph", "query", str(v), str(tmp_path / "plan.json"), "--index", str(tmp_path / "full.evidence")],
                 ["graph", "search", str(v), "zeolite xylophone", "--index", str(tmp_path / "full.evidence")]):
        assert main(args) == 2, args
        err = capsys.readouterr().err
        assert "was built from another document" in err and "zeolite" not in err
    assert main(["graph", "index", str(v)]) in (0, None)
    capsys.readouterr()
    assert main(["graph", "search", str(v), "zeolite xylophone", "--mode", "keyword"]) in (0, None)
    out = json.loads(capsys.readouterr().out)
    assert out["hits"] == [] and out["access"]["level"] == "public"
    assert main(["graph", "search", str(f), "zeolite xylophone", "--mode", "keyword"]) in (0, None)
    out = json.loads(capsys.readouterr().out)
    assert out["hits"] and out["access"]["level"] == "project"
    # an index that records no digest (built before it was recorded) is used when it holds exactly the quotes
    Index.build(evidence_items(view)).save(tmp_path / "old")
    assert load_for(tmp_path / "old", view).graph_sha256 is None
    with pytest.raises(ScaleError, match="records no document digest"):
        load_for(tmp_path / "old", d)


def test_an_evidence_index_is_built_from_the_document_when_none_is_saved(tmp_path, capsys, doc):
    """query (text) and search build the index of a document in memory when none is saved beside it: the same index
    `scale graph index` saves, bound to the document, and nothing is written. A saved index is still refused when it is
    not the document's."""
    from scale.cli import main
    from scale.passages import graph_sha256, index_for

    f = tmp_path / "doc.json"
    f.write_text(json.dumps(doc))
    built = index_for(tmp_path / "doc.evidence", doc)
    assert built.graph_sha256 == graph_sha256(doc) and built.items == evidence_items(doc)
    assert sorted(x.name for x in tmp_path.iterdir()) == ["doc.json"]
    words = " ".join(evidence_items(doc)[0]["text"].split()[:4])
    assert main(["graph", "search", str(f), words, "--mode", "keyword"]) in (0, None)
    on_demand = json.loads(capsys.readouterr().out)
    assert on_demand["hits"] and sorted(x.name for x in tmp_path.iterdir()) == ["doc.json"]
    assert main(["graph", "index", str(f)]) in (0, None)
    capsys.readouterr()
    assert main(["graph", "search", str(f), words, "--mode", "keyword"]) in (0, None)
    assert json.loads(capsys.readouterr().out)["hits"] == on_demand["hits"]
    other = copy.deepcopy(doc)                      # a quote changed: the saved index is stale for it
    rec = next(r for r in other["nodes"] + other["links"] if any(e.get("quote") for e in r["props"].get("evidence") or []))
    next(e for e in rec["props"]["evidence"] if e.get("quote"))["quote"] = "a quote the saved index does not hold"
    with pytest.raises(ScaleError, match="was built from another document"):
        index_for(tmp_path / "doc.evidence", other)
