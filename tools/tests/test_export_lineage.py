"""The kg-bundle export's release lineage from the command line (--previous, --ids-from, --replaced, --corpus), the
provenance and value detail it carries (statement kinds, status, confidence, extraction runs, bounds, dates,
locators, offsets), the frozen corpus manifest check, and the validator's plausibility advisories."""

import copy
import json

import pytest

from conftest import GRAPH_MANIFEST, HEAD_VERSION, REPO
from scale import corpus, kgbundle, pgraph
from scale.cli import main
from scale.util import ScaleError

T = "ex:exmpl/lineage"
SRC = f"{T}/source/paper"
TEXT = ("Results. The copper catalyst gave 42 % selectivity to methanol and 30 % to dimethyl ether at about 250 °C; "
        "conversion did not exceed 5 %. Table 2 lists the runs. Copper is the active phase, we conclude.")
Q_SEL = "The copper catalyst gave 42 % selectivity to methanol"
Q_TEMP = "at about 250 °C"
Q_CONV = "conversion did not exceed 5 %"
Q_CLAIM = "Copper is the active phase, we conclude."


def _validator():
    try:
        from test_graph_search_query import _bundle_validator as found
    except (ImportError, pytest.skip.Exception):         # that module needs numpy (the dev extra)
        return None
    return found()


@pytest.fixture(scope="module")
def head():
    return pgraph.load_spec(GRAPH_MANIFEST)


def ev(loc, quote, kind="text", **k):
    return {"source": SRC, "locator": loc, "kind": kind, "quote": quote, **k}


def V(value, unit, **k):
    return {"status": "present", "value": value, "unit": unit, **k}


def build() -> dict:
    """A small synthetic document: one test with a bound, an approximate and a missing value, two selectivities that
    name their products, a disputed claim, a link with a confidence and an extraction run."""
    meoh, dme = f"{T}/species/meoh", f"{T}/species/dme"
    nodes = [
        {"id": SRC, "label": "Source", "props": {"name": "Paper", "title": "An invented paper on copper", "kind": "article",
                                                 "year": 2020, "published_on": "2020-03", "date_basis": "published",
                                                 "text_version": "version_of_record", "retrieved_from": "the publisher",
                                                 "origin": "synthetic"}},
        {"id": f"{T}/catalyst/cu", "label": "Catalyst", "props": {"name": "copper", "origin": "synthetic",
                                                                  "evidence": [ev("p. 2, Table 2, row 1", Q_SEL, "table")]}},
        {"id": f"{T}/sample/cu", "label": "CatalystSample", "props": {"name": "copper sample", "sample_kind": "batch",
                                                                      "origin": "synthetic", "evidence": [ev("p. 2", Q_SEL)]}},
        {"id": meoh, "label": "ChemicalSpecies", "props": {"name": "methanol", "formula": "CH3OH", "origin": "synthetic"}},
        {"id": dme, "label": "ChemicalSpecies", "props": {"name": "dimethyl ether", "formula": "C2H6O", "origin": "synthetic"}},
        {"id": f"{T}/test/1", "label": "CatalyticTest", "props": {
            "name": "run 1", "test_kind": "activity", "driving_forces": ["thermo"], "origin": "synthetic",
            "temperature": V(250, "°C", qualifier="approximate", as_reported="about 250 °C"),
            "conversion": V(5, "%", bound="upper", as_reported="did not exceed 5 %"),
            "pressure": {"status": "not_reported", "missing_reason": "not_stated_in_source"},
            "results": {"selectivity_methanol": V(42, "%", target=meoh), "selectivity_dme": V(30, "%", target=dme)},
            "evidence": [ev("p. 2", Q_SEL), ev("p. 2, Fig. 3b", Q_TEMP, "figure", evidence_type="ECO:0000006"),
                         ev("p. 2", Q_CONV)]}},
        {"id": f"{T}/claim/active", "label": "Claim", "props": {
            "name": "copper is active", "statement": "Copper is the active phase.", "claim_kind": "conclusion",
            "claim_status": "disputed", "origin": "synthetic", "evidence": [ev("p. 2", Q_CLAIM)]}},
    ]
    links = [
        {"id": f"{T}/link/uses", "type": "USES_CATALYST", "source": f"{T}/test/1", "target": f"{T}/sample/cu",
         "props": {"status": "asserted", "confidence": 0.9, "origin": "synthetic", "evidence": [ev("p. 2", Q_SEL)],
                   "_alchemic_extraction": {"method": "llm", "model": "a-model", "prompt_version": "curate-source 0.1.0",
                                            "run_id": "run-1"}}},
        {"id": f"{T}/link/formulation", "type": "HAS_FORMULATION", "source": f"{T}/sample/cu", "target": f"{T}/catalyst/cu",
         "props": {"origin": "synthetic", "evidence": [ev("p. 2", Q_SEL)]}},
        {"id": f"{T}/link/supports", "type": "SUPPORTS", "source": f"{T}/test/1", "target": f"{T}/claim/active",
         "props": {"status": "disputed", "origin": "synthetic", "evidence": [ev("p. 2", Q_CLAIM)]}},
    ]
    doc = {"directed": True, "multigraph": True,
           "graph": {"schema": "scale-graph", "schema_version": HEAD_VERSION, "graph_id": f"{T}/graph",
                     "title": "Lineage and provenance of a kg-bundle export (synthetic)", "data_status": "synthetic_example",
                     "follows_domains": ["catalysis"], "stewardship": {"access": "public"},
                     "_alchemic_producer": {"agent": "a curation agent", "models": ["a-model"], "prompt_version": "p1"}},
           "nodes": nodes, "links": links}
    for nid, srcs in sorted(pgraph.expected_reported_in(doc).items()):
        for s in sorted(srcs):
            doc["links"].append({"id": f"{nid}/reported-in", "type": "REPORTED_IN", "source": nid, "target": s,
                                 "props": {"origin": "synthetic"}})
    return doc


def _graph(bundle):
    return json.loads((bundle / "kg/graph.json").read_text())


def _by_scale(bundle):
    g = _graph(bundle)
    return {x["props"].get("scale_id"): x for x in g["nodes"] + g["links"] if x["props"].get("scale_id")}


def test_the_export_carries_statement_kinds_status_confidence_and_extraction_runs(tmp_path, head):
    doc = build()
    assert pgraph.validate(doc, head).errors == []
    doc["links"][1]["props"]["statement_kind"] = "assumption"      # a planned kernel property: read when recorded
    m = kgbundle.export(doc, head, tmp_path / "b", "lineage", created="2026-10-06T00:00:00Z")
    by = _by_scale(tmp_path / "b")
    uses, form, sup = by[f"{T}/link/uses"]["props"], by[f"{T}/link/formulation"]["props"], by[f"{T}/link/supports"]["props"]
    assert form["_statement"] == "assumption" and "statement_kind" not in form          # the recorded kind
    assert uses["_statement"] == "observation" and uses["scale_status"] == "asserted"
    assert sup["_statement"] == "hypothesis" and sup["scale_status"] == "disputed"      # never a plain conclusion
    assert uses["_confidence"] == 0.9 and "confidence" not in uses
    assert uses["_extraction"] == {"method": "llm", "model": "a-model", "prompt_version": "curate-source 0.1.0", "run_id": "run-1"}
    rep = m["export_report"]
    assert rep["statement_inferred"] == {"hypothesis": 1, "observation": 1}            # the recorded kind is not counted
    assert m["producer"] == {"agent": "a curation agent", "models": ["a-model"], "prompt_version": "p1"}
    schema = json.loads((tmp_path / "b/kg/schema.json").read_text())
    st = schema["edge_types"]["SUPPORTS"]["properties"]["scale_status"]
    assert st["type"] == "enum" and "refuted" in st["values"]
    assert "_confidence" not in schema["edge_types"]["USES_CATALYST"]["properties"]   # a format property, not declared
    # without a header extension the producer is SCALE's curation agents, with no model claimed
    plain = copy.deepcopy(build())
    plain["graph"].pop("_alchemic_producer")
    assert kgbundle.export(plain, head, tmp_path / "p", "plain", created="2026-10-06T00:00:00Z")["producer"]["models"] == []
    v = _validator()
    if v:
        kgbundle.seal(tmp_path / "b")
        res = v.validate_bundle(tmp_path / "b")
        assert res.ok, [f.message for f in res.errors][:5]


def test_bounds_approximations_absences_and_dates_are_exported_or_counted(tmp_path, head):
    m = kgbundle.export(build(), head, tmp_path / "b", "lineage", created="2026-10-06T00:00:00Z")
    by = _by_scale(tmp_path / "b")
    t = by[f"{T}/test/1"]["props"]
    assert t["conversion"]["value"] == 5 and t["conversion_bound"] == "upper"
    assert t["temperature"]["value"] == 523.15 and t["temperature_qualifier"] == "approximate"
    assert "pressure" not in t and "pressure_as_reported" not in t                     # a typed absence has no value ...
    assert t["_value_status"] == {"pressure": {"status": "not_reported", "missing_reason": "not_stated_in_source"}}
    rep = m["export_report"]
    assert rep["absences"] == {"not_reported": 1} and m["format_version"] == "1.1.0"   # ... but says why (format 1.1.0)
    assert rep["bounds"] == {"conversion": 1} and rep["approximate_values"] == {"temperature": 1}
    assert json.loads(t["results"])["selectivity_methanol"]["value"] == 42 and "results_selectivity_methanol" not in t
    pub = by[SRC]["props"]
    assert (pub["published_on"], pub["date_basis"], pub["text_version"], pub["retrieved_from"]) == (
        "2020-03", "published", "version_of_record", "the publisher")
    schema = json.loads((tmp_path / "b/kg/schema.json").read_text())
    assert schema["node_types"]["Publication"]["properties"]["published_on"] == {"type": "date"}
    assert schema["node_types"]["CatalyticTest"]["properties"]["conversion_bound"]["values"] == ["upper", "lower"]


def test_a_link_resting_only_on_withheld_quotes_is_exported_with_their_digests(tmp_path, head):
    """A quote withheld under the copyright cap (its sha256 and length in the evidence note) is the kg-bundle 1.1.0
    quote_withheld, so the link stays an edge; one longer than the format's 600 characters is left out and counted, and a
    source whose text the bundle ships is quoted, never withheld."""
    from scale import rights
    doc = build()
    link = next(e for e in doc["links"] if e["id"] == f"{T}/link/uses")
    h, n = rights.digest(Q_SEL)
    link["props"]["evidence"] = [{**{k: v for k, v in link["props"]["evidence"][0].items() if k != "quote"},
                                  "note": f"quote withheld: sha256:{h} chars:{n}"}]
    m = kgbundle.export(doc, head, tmp_path / "b", "withheld", created="2026-10-06T00:00:00Z")
    e = _by_scale(tmp_path / "b")[f"{T}/link/uses"]["props"]
    assert e["_evidence"] == [{"quote_withheld": {"sha256": h, "chars": n, "normalization": "scale-match-text-1",
                                                  "reason": "copyright"}, "source_id": e["source_paper_ids"][0],
                               "locator": {"page": 2}}]
    assert m["format_version"] == "1.1.0" and "withheld_too_long" not in m["export_report"]
    v = _validator()
    if v:
        kgbundle.seal(tmp_path / "b")
        res = v.validate_bundle(tmp_path / "b")
        assert res.ok, [f.message for f in res.errors][:5]
        assert h == v.withheld_quote(Q_SEL)["sha256"]                    # the same normalization on both sides
    link["props"]["evidence"][0]["note"] = f"quote withheld: sha256:{h} chars:601"
    m = kgbundle.export(doc, head, tmp_path / "c", "withheld", created="2026-10-06T00:00:00Z")
    assert f"{T}/link/uses" not in _by_scale(tmp_path / "c") and m["export_report"]["withheld_too_long"] == 1


def test_locators_name_tables_and_figures_and_shipped_texts_get_char_offsets(tmp_path, head):
    assert kgbundle._locator("p. 2, Table 2, row 1", "table") == {"page": 2, "section": "Table 2, row 1", "table": "Table 2"}
    assert kgbundle._locator("p. 4, Fig. 3b, curve A", "figure")["figure"] == "Fig. 3b"
    # a panel letter only right after the number or in parentheses, never the first letter of the next word
    for loc, fig in (("p. 5, Fig. 2 inset", "Fig. 2"), ("p. 3, Figure 4 and text", "Figure 4"), ("Fig. 5 shows", "Fig. 5"),
                     ("p. 6, Fig. 1(a)", "Fig. 1(a)"), ("Figure 2 (c), top", "Figure 2 (c)"), ("Fig. 7 (top curve)", "Fig. 7"),
                     ("Fig. S2", "Fig. S2")):
        assert kgbundle._locator(loc, "figure")["figure"] == fig, loc
    assert kgbundle._locator("p. 5, Table IV", "table")["table"] == "Table IV"
    assert "table" not in kgbundle._locator("p. 2, Table 2", "text")                     # only a table reading names it
    assert kgbundle.char_span(TEXT, Q_SEL) == (TEXT.index(Q_SEL), TEXT.index(Q_SEL) + len(Q_SEL))
    spaced = "The  copper\ncatalyst gave 42 %  selectivity to METHANOL"                # whitespace and case differ
    start, end = kgbundle.char_span(TEXT, spaced)
    assert TEXT[start:end] == Q_SEL and kgbundle.char_span(TEXT, "not in the text") is None
    doc = build()
    doc["nodes"][0]["props"]["doi"] = "10.0000/invented"
    m = kgbundle.export(doc, head, tmp_path / "b", "lineage", created="2026-10-06T00:00:00Z",
                      texts={"10.0000/invented": ("paper.txt", TEXT, "CC-BY-4.0")})
    t = _by_scale(tmp_path / "b")[f"{T}/test/1"]["props"]
    fig = next(e for e in t["_evidence"] if e["quote"] == Q_TEMP)
    assert fig["locator"]["figure"] == "Fig. 3b" and fig["evidence_type"] == "ECO:0000006"
    assert TEXT[fig["locator"]["char_start"]:fig["locator"]["char_end"]] == Q_TEMP
    assert m["export_report"]["evidence_with_char_offsets"] >= 4
    # the bundle's licence note names the licences of the texts it ships, not only public-domain ones
    note = m["licence_policy"]["note"]
    assert "CC-BY-4.0" in note and "public-domain" not in note and "US patent" not in note
    plain = kgbundle.export(build(), head, tmp_path / "n", "lineage", created="2026-10-06T00:00:00Z")
    assert plain["licence_policy"]["note"].startswith("No source texts are shipped")
    v = _validator()
    if v:
        kgbundle.seal(tmp_path / "b")
        res = v.validate_bundle(tmp_path / "b")
        assert res.ok, [f.message for f in res.errors][:5]


def test_a_type_gets_an_iri_only_from_an_absolute_maps_to(tmp_path, head):
    assert kgbundle.iri_of({"maps_to": ["EXPO ScientificExperiment", "http://purl.obolibrary.org/obo/OBI_0000070"]}) \
        == "http://purl.obolibrary.org/obo/OBI_0000070"
    assert kgbundle.iri_of({"maps_to": ["OBI assay"]}) is None and kgbundle.iri_of({}) is None
    spec = copy.deepcopy(head)
    spec["nodes"]["CatalyticTest"]["maps_to"] = ["OBI assay", "http://purl.obolibrary.org/obo/OBI_0000070"]
    kgbundle.export(build(), spec, tmp_path / "b", "lineage", created="2026-10-06T00:00:00Z")
    types = json.loads((tmp_path / "b/kg/schema.json").read_text())["node_types"]
    assert types["CatalyticTest"]["iri"] == "http://purl.obolibrary.org/obo/OBI_0000070" and "iri" not in types["Catalyst"]
    d = pgraph.describe(head, ["Experiment", "CatalyticTest", "REPORTED_IN"])
    assert "OBI planned process" in d["labels"]["Experiment"]["maps_to"] and "maps_to" not in d["labels"]["CatalyticTest"]


def _cli(args, capsys):
    rc = main(["--repo", str(REPO), *args])
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_the_cli_export_records_the_previous_release_and_the_merged_records(tmp_path, capsys):
    f = tmp_path / "doc.json"
    doc = build()
    f.write_text(json.dumps(doc))
    base = ["graph", "export", str(f), "--to", "kg-bundle", "--created", "2026-10-06T00:00:00Z"]
    assert _cli(base + ["--out", str(tmp_path / "v1")], capsys)[0] == 0
    first = json.loads((tmp_path / "v1/bundle.json").read_text())
    assert first["version"] == "1.0.0" and first["previous"] is None
    old_cat = _by_scale(tmp_path / "v1")[f"{T}/catalyst/cu"]["id"]
    # the next release: the catalyst record is merged into a new one (its id retired), which the map says
    survivor = f"{T}/catalyst/copper"
    for n in doc["nodes"]:
        if n["id"] == f"{T}/catalyst/cu":
            n["id"] = survivor
    for e in doc["links"]:
        for end in ("source", "target"):
            if e[end] == f"{T}/catalyst/cu":
                e[end] = survivor
        e["id"] = e["id"].replace(f"{T}/catalyst/cu/", f"{survivor}/")
    f.write_text(json.dumps(doc))
    rmap = tmp_path / "replaced.json"
    rmap.write_text(json.dumps({f"{T}/catalyst/cu": survivor}))
    rc, _, err = _cli(base + ["--out", str(tmp_path / "v2"), "--previous", str(tmp_path / "v1")], capsys)
    assert rc == 2 and "--version" in err                                              # a later release names its version
    rc, _, err = _cli(base + ["--out", str(tmp_path / "v2"), "--previous", str(tmp_path / "v1"), "--version", "1.0.0"], capsys)
    assert rc == 2 and "does not come after" in err
    rc, out, _ = _cli(base + ["--out", str(tmp_path / "v2"), "--previous", str(tmp_path / "v1"), "--version", "1.1.0",
                              "--replaced", str(rmap)], capsys)
    assert rc == 0
    second = json.loads((tmp_path / "v2/bundle.json").read_text())
    assert second["previous"] == {"version": "1.0.0", "graph_sha256": first["graph_sha256"]}
    assert second["changes"]["nodes_added"] == 1 and second["export_report"]["replaced"] == {"listed": 1, "applied": 1}
    new = _by_scale(tmp_path / "v2")
    assert new[survivor]["props"]["replaced_ids"] == [old_cat]
    assert new[f"{T}/test/1"]["id"] == _by_scale(tmp_path / "v1")[f"{T}/test/1"]["id"]   # ids frozen at first release
    log = (tmp_path / "v2/CHANGELOG.md").read_text()
    assert log.index("## 1.1.0") < log.index("## 1.0.0") and "previous release 1.0.0" in log
    # an earlier build's ids, without recording it as the previous release
    rc, _, _ = _cli(base + ["--out", str(tmp_path / "ids"), "--ids-from", str(tmp_path / "v1")], capsys)
    assert rc == 0 and json.loads((tmp_path / "ids/bundle.json").read_text())["previous"] is None
    assert _by_scale(tmp_path / "ids")[f"{T}/test/1"]["id"] == new[f"{T}/test/1"]["id"]
    for bad, msg in ((["--previous", str(tmp_path / "v1"), "--ids-from", str(tmp_path / "v1")], "not both"),
                     (["--replaced", str(rmap)], "--previous or --ids-from"),
                     (["--previous", str(tmp_path)], "no bundle.json")):
        rc, _, err = _cli(base + ["--out", str(tmp_path / "x"), "--version", "2.0.0", *bad], capsys)
        assert rc == 2 and msg in err, (bad, err)
    v = _validator()
    if v:
        res = v.validate_bundle(tmp_path / "v2")
        assert res.ok, [f.message for f in res.errors][:5]


MANIFEST = {"corpus": "An invented corpus", "cutoff": {"date": "1966-01-01", "rule": "published before 1966-01-01"},
            "frozen_at": "2026-09-01", "counts": {"in_scope": 2, "not_retrieved": 1, "off_scope": 1},
            "sources": [{"slug": "a", "status": "in_scope"}, {"slug": "b", "status": "in_scope"},
                        {"slug": "c", "status": "not_retrieved"}, {"slug": "d", "status": "off_scope"}]}


def test_a_corpus_manifest_accounts_for_every_candidate_once(tmp_path, capsys):
    res = corpus.check(MANIFEST)
    assert res["ok"] and res["candidates"] == 4 and res["corpus"] == {
        "description": "An invented corpus Rule: published before 1966-01-01.", "frozen_at": "2026-09-01",
        "n_screened": 4, "n_included": 2}
    bad = copy.deepcopy(MANIFEST)
    bad["sources"] += [{"slug": "a", "status": "in_scope"}, {"slug": "e", "status": "excluded"}, {"slug": "f"}]
    problems = corpus.check(bad)["problems"]
    assert any("e" in p and "status_reason" in p for p in problems)                  # excluded: say why
    assert any("(f)" in p and "no status" in p for p in problems)
    assert any(p.startswith("a: listed 2 times") for p in problems)
    assert any("in_scope says 2, the sources list 3" in p for p in problems)
    assert any("add up to 4, the candidates are 6" in p for p in problems)
    f = tmp_path / "manifest.json"
    f.write_text(json.dumps(MANIFEST))
    rc, out, _ = _cli(["corpus", "check", str(f)], capsys)
    assert rc == 0 and json.loads(out)["corpus"]["n_included"] == 2
    f.write_text(json.dumps(bad))
    with pytest.raises(SystemExit) as exc:
        main(["--repo", str(REPO), "corpus", "check", str(f)])
    assert exc.value.code == 1
    capsys.readouterr()
    # the export fills bundle.json's corpus block from a manifest that adds up, and refuses one that does not
    g = tmp_path / "doc.json"
    g.write_text(json.dumps(build()))
    base = ["graph", "export", str(g), "--to", "kg-bundle", "--created", "2026-10-06T00:00:00Z"]
    rc, _, err = _cli(base + ["--out", str(tmp_path / "b"), "--corpus", str(f)], capsys)
    assert rc == 2 and "does not add up" in err
    f.write_text(json.dumps(MANIFEST))
    assert _cli(base + ["--out", str(tmp_path / "b"), "--corpus", str(f)], capsys)[0] == 0
    assert json.loads((tmp_path / "b/bundle.json").read_text())["corpus"]["n_screened"] == 4
    with pytest.raises(ScaleError, match="no corpus manifest"):
        corpus.load(tmp_path / "missing.json")


def test_a_link_resting_only_on_a_cited_result_is_not_the_citing_sources_observation(tmp_path, head):
    """The format's principle 4: a result a source cites from another work (ECO:0000033) is not that source's finding, so the
    citing source's edge is left out and counted, never exported as an observation; the records stay."""
    doc = build()
    uses = doc["links"][0]
    uses["props"]["evidence"][0]["evidence_type"] = "ECO:0000033"
    assert pgraph.validate(doc, head).errors == []
    m = kgbundle.export(doc, head, tmp_path / "b", "lineage", created="2026-10-06T00:00:00Z")
    by = _by_scale(tmp_path / "b")
    assert uses["id"] not in by and f"{T}/test/1" in by and f"{T}/sample/cu" in by
    assert m["export_report"]["second_hand_not_exported"] == {"USES_CATALYST": 1}
    assert "USES_CATALYST" not in m["export_report"]["not_exported_links"]          # not for want of a quote
    # one first-hand item from the same source: the source's own statement, exported with both items
    uses["props"]["evidence"].append(ev("p. 3", Q_SEL))
    m = kgbundle.export(doc, head, tmp_path / "c", "lineage", created="2026-10-06T00:00:00Z")
    edge = _by_scale(tmp_path / "c")[uses["id"]]["props"]
    assert edge["_statement"] == "observation" and len(edge["_evidence"]) == 2 and "second_hand_not_exported" not in m["export_report"]


def test_the_validator_warns_on_implausible_percentages_and_counts_second_hand_evidence(head):
    doc = build()
    rep = pgraph.validate(doc, head)
    assert rep.errors == [] and not [w for w in rep.warnings if "100 %" in w["message"] or "second-hand" in w["message"]]
    t = next(n for n in doc["nodes"] if n["id"] == f"{T}/test/1")["props"]
    t["results"]["selectivity_dme"]["value"] = 60          # 42 + 60 = 102 > 100 + 1 (the rounding of two whole numbers)
    t["conversion"] = V(104, "%")
    t["results"]["carbon_balance"] = V(103, "mol %")
    doc["links"][0]["props"]["evidence"][0]["evidence_type"] = "ECO:0000033"
    rep = pgraph.validate(doc, head)
    msgs = [w["message"] for w in rep.warnings]
    assert rep.errors == []
    assert any(m.startswith("conversion: 104 % is above 100 %") for m in msgs)
    assert any(m.startswith("results.carbon_balance: 103 mol % is above 100 %") for m in msgs)
    assert any(m.startswith("selectivities to 2 products sum to 102") for m in msgs)
    assert any("1 evidence item is second-hand" in m for m in msgs)
    # only one basis and one unit spelling are summed, compared as a query compares them (whitespace runs aside, case
    # kept): 60 mol% and 50 C% (or wt%, or %) are never added; 60 mol% and 50 " mol% " are, and the sum names the unit
    sels = t["results"]["selectivity_methanol"], t["results"]["selectivity_dme"]
    for (u1, b1), (u2, b2), warns in ((("mol%", None), ("C%", None), False), (("mol%", None), ("wt%", None), False),
                                      (("%", None), ("mol%", None), False), (("mol%", None), ("MOL%", None), False),
                                      (("mol%", None), (" mol% ", None), True),
                                      (("%", "carbon"), ("%", " carbon "), True), (("%", "carbon"), ("%", "Carbon"), False)):
        for v, u, b, x in ((sels[0], u1, b1, 60), (sels[1], u2, b2, 50)):
            v.update(value=x, unit=u)
            v.pop("basis", None)
            if b:
                v["basis"] = b
        summed = [m for m in (w["message"] for w in pgraph.validate(doc, head).warnings) if m.startswith("selectivities")]
        assert bool(summed) is warns, (u1, b1, u2, b2, summed)
        assert not warns or f"sum to 110.0 {u1.strip()}, above 100 %" in summed[0]
    for v, x in ((sels[0], 42), (sels[1], 60)):
        v.update(value=x, unit="%")
        v.pop("basis", None)
    # 42 + 58.5 = 100.5 stays within the rounding of 42 and 58.5 (0.5 + 0.05); a repeated product is a series, not summed
    t["results"]["selectivity_dme"]["value"] = 58.5
    assert not [m for m in (w["message"] for w in pgraph.validate(doc, head).warnings) if m.startswith("selectivities")]
    t["results"]["selectivity_dme"].update(value=90, target=f"{T}/species/meoh")
    assert not [m for m in (w["message"] for w in pgraph.validate(doc, head).warnings) if m.startswith("selectivities")]
    # a one-sided bound is never read as its number: "< 1 %" beside 99.8 % may sum to 100 % or less; "at least 2 %"
    # beside 99.8 % surely sums above it; an upper bound above 100 % never warns, a lower bound or a range above it does
    t["results"]["selectivity_dme"].update(value=1, bound="upper", as_reported="< 1", target=f"{T}/species/dme")
    sel = next(k for k, v in t["results"].items() if k != "selectivity_dme" and v.get("target") and "selectivity" in k)
    t["results"][sel]["value"] = 99.8
    assert pgraph.validate(doc, head).errors == []
    assert not [m for m in (w["message"] for w in pgraph.validate(doc, head).warnings) if m.startswith("selectivities")]
    t["results"]["selectivity_dme"].update(value=2, bound="lower", as_reported="at least 2")
    msgs = [w["message"] for w in pgraph.validate(doc, head).warnings]
    assert any(m.startswith("selectivities to 2 products sum to at least 101.8 %") for m in msgs)
    t["conversion"] = {**V(104, "%"), "bound": "upper"}
    t["results"]["carbon_balance"] = {"status": "present", "lower": 98, "upper": 103, "unit": "mol %"}
    msgs = [w["message"] for w in pgraph.validate(doc, head).warnings]
    assert not [m for m in msgs if m.startswith(("conversion:", "results.carbon_balance:"))]
    t["conversion"] = {**V(104, "%"), "bound": "lower"}
    t["results"]["carbon_balance"] = {"status": "present", "lower": 101, "upper": 103, "unit": "mol %"}
    msgs = [w["message"] for w in pgraph.validate(doc, head).warnings]
    assert any(m.startswith("conversion: at least 104 % is above 100 %") for m in msgs)
    assert any(m.startswith("results.carbon_balance: 101-103 mol % is above 100 %") for m in msgs)
    # an open range (a lower end only) is "at least" its lower end; one with an upper end only never warns
    t["results"]["carbon_balance"] = {"status": "present", "lower": 101, "unit": "mol %"}
    msgs = [w["message"] for w in pgraph.validate(doc, head).warnings]
    assert any(m.startswith("results.carbon_balance: at least 101 mol % is above 100 %") for m in msgs)
    t["results"]["carbon_balance"] = {"status": "present", "upper": 103, "unit": "mol %"}
    msgs = [w["message"] for w in pgraph.validate(doc, head).warnings]
    assert not [m for m in msgs if m.startswith("results.carbon_balance:")]
