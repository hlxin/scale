"""Publication rights (scale.rights, `scale evidence`): every committed document is public; quoted source text
respects the copyright cap per source class; text beyond the cap is withheld as a digest and a length, and comes back
from one's own copy of the source text. All data here is synthetic."""

import json

import pytest

from conftest import REPO, as_project_data
from scale import pgraph, rights
from scale.cli import main
from scale.util import ScaleError, dump_yaml, load_doc, match_text, write_canonical

PAPER, BOOK, OPEN = "ex:t/source/paper", "ex:t/source/book", "ex:t/source/open"
# an invented source text, long enough for several quotes
TEXT = ("The zinc oxide catalyst was pressed into pellets and reduced in hydrogen at 300 °C for twelve hours. "
        "At 380 °C and 150 atm the conversion of carbon monoxide reached 6.2 per cent per pass. "
        "Above 420 °C the activity fell steadily, which the authors attribute to sintering of the oxide. "
        "A copper-free\npreparation behaved alike, so copper is not needed for the reaction at these pressures. ") * 3


def _doc(quotes):
    """A research-data document whose test node carries one evidence item per (source, quote, quantitative)."""
    nodes = [{"id": s, "label": "Source", "props": {"name": s, "kind": "article", "title": s, "year": 2026, "origin": "curated"}}
             for s in (PAPER, BOOK, OPEN)]
    for i, (src, q, quant) in enumerate(quotes):
        props = {"name": f"claim {i}", "statement": "invented", "claim_kind": "finding", "origin": "reported",
                 "evidence": [{"source": src, "locator": f"p. {i + 1}", "kind": "text", "quote": q, "id": f"e{i}"}]}
        if quant:
            props["value"] = {"status": "present", "value": 6.2, "unit": "%", "evidence_ids": [f"e{i}"]}
        nodes.append({"id": f"ex:t/claim/{i}", "label": "Claim", "props": props})
    return {"directed": True, "multigraph": True, "graph": {"schema": "scale-catal", "data_status": "research_data"},
            "nodes": nodes, "links": []}


RIGHTS = {PAPER: {"class": "in_copyright", "licence": "all rights reserved", "basis": "invented"},
          BOOK: {"class": "restricted", "licence": "project only", "basis": "invented", "text_chars": 1000},
          OPEN: {"class": "open", "licence": "CC-BY-4.0", "basis": "invented"}}


def test_rights_files_are_checked(tmp_path):
    f = tmp_path / "rights.yaml"
    f.write_text(dump_yaml({"sources": RIGHTS}))
    assert rights.load_rights(f)[BOOK]["text_chars"] == 1000
    for bad, why in (({PAPER: {"class": "fair_use", "licence": "x", "basis": "y"}}, "class must be one of"),
                     ({PAPER: {"class": "open", "basis": "y"}}, "licence is required"),
                     ({PAPER: {"class": "open", "licence": "x", "basis": "y", "text_chars": 0}}, "positive integer"),
                     ({PAPER: {"class": "open", "licence": "x", "basis": "y", "share": 1}}, "keys are")):
        f.write_text(dump_yaml({"sources": bad}))
        with pytest.raises(ScaleError, match=why):
            rights.load_rights(f)
    sub = tmp_path / "a/b"
    sub.mkdir(parents=True)
    f.write_text(dump_yaml({"sources": RIGHTS}))
    assert rights.rights_file(sub / "doc.json", tmp_path) == f            # the nearest one above
    assert rights.rights_file(sub / "doc.json", sub) is None             # never above the repository root


def test_the_report_counts_distinct_characters_against_each_class_cap():
    long = "x" * 301
    doc = _doc([(PAPER, "the conversion of carbon monoxide", True), (PAPER, "conversion of carbon", False),   # contained
                (PAPER, "The Conversion of  carbon monoxide", False),                                          # equal, normalized
                (BOOK, long, False), (OPEN, long * 20, False)])
    rep = rights.report(doc, RIGHTS)
    s = rep["sources"]
    assert s[PAPER]["distinct_chars"] == len("the conversion of carbon monoxide") and s[PAPER]["cap"] == 4000
    assert s[BOOK]["cap"] == 100 and s[OPEN]["cap"] is None                  # 10 % of text_chars; open: no cap
    assert rep["violations"] == [f"{BOOK}: 1 quoted texts longer than 300 characters (longest 301)",
                                 f"{BOOK}: 301 distinct quoted characters; the cap is 100"]
    assert rep["unlisted"] == [] and not rep["ok"]
    rep = rights.report(doc, {OPEN: RIGHTS[OPEN]})                          # unknown sources count as in copyright
    assert rep["unlisted"] == [BOOK, PAPER] and rep["sources"][BOOK]["class"] == "in_copyright"


def test_cap_keeps_quantitative_evidence_first_then_shorter_and_withholds_the_rest():
    q = [TEXT[0:60], TEXT[100:150], TEXT[200:230], TEXT[250:400]]          # 60, 50, 30, 150 characters
    doc = _doc([(BOOK, q[0], True), (BOOK, q[1], False), (BOOK, q[2], False), (BOOK, q[3], False), (OPEN, TEXT[:500], False)])
    capped, rep = rights.cap(doc, RIGHTS)                                    # BOOK's cap: 100 distinct characters
    kept = {n["id"]: n["props"]["evidence"][0].get("quote") for n in capped["nodes"] if n["label"] == "Claim"}
    assert kept["ex:t/claim/0"] == q[0] and kept["ex:t/claim/2"] == q[2]     # quantitative first (60), then shortest (30)
    assert kept["ex:t/claim/1"] is None and kept["ex:t/claim/3"] is None     # 50 and 150 would pass the cap
    assert kept["ex:t/claim/4"] == TEXT[:500]                                # an open source is not capped
    assert rep["sources"][BOOK] == {"class": "restricted", "cap": 100, "kept": 2, "withheld": 2,
                                    "distinct_chars_before": 290, "distinct_chars_after": 90}
    ev = next(n for n in capped["nodes"] if n["id"] == "ex:t/claim/1")["props"]["evidence"][0]
    h, n = rights.digest(q[1])
    assert ev["note"] == f"quote withheld: sha256:{h} chars:{n}" and set(ev) == {"source", "locator", "kind", "id", "note"}
    assert rights.report(capped, RIGHTS)["ok"]                               # the capped document passes
    assert rights.cap(doc, RIGHTS)[0] == capped                              # deterministic
    assert "quote" in doc["nodes"][4]["props"]["evidence"][0]                # the input is left as it was


def test_withheld_text_is_valid_under_the_schema_and_keeps_an_earlier_note():
    from conftest import EXAMPLES, spec_of
    doc = as_project_data(load_doc(EXAMPLES / "scale-catal/example.json"))
    spec = spec_of(doc)                                                     # the version the example pins
    test = next(n for n in doc["nodes"] if n["label"] == "CatalyticTest")
    src = test["props"]["evidence"][0]["source"]
    test["props"]["evidence"][0]["quote"] = "q" * 400                       # a quote over the cap
    capped, _ = rights.cap(doc, {src: {"class": "in_copyright", "licence": "x", "basis": "y"}})
    ev = next(n for n in capped["nodes"] if n["label"] == "CatalyticTest")["props"]["evidence"][0]
    assert ev["note"].startswith(test["props"]["evidence"][0]["note"] + "; quote withheld: sha256:") and "quote" not in ev
    assert pgraph.validate(capped, spec).errors == []


def test_rehydrate_restores_the_text_from_ones_own_copy():
    q = ["reduced in hydrogen at 300 °C", "copper-free preparation behaved alike", TEXT[105:180]]
    doc = _doc([(PAPER, q[0], False), (PAPER, q[1], False), (PAPER, q[2], True)])
    capped, rep = rights.cap(doc, {PAPER: {"class": "in_copyright", "licence": "x", "basis": "y", "text_chars": 600}})
    assert rep["sources"][PAPER]["kept"] == 1                                 # a cap of 60: the 75-character quote and
    #                                                                           29 + 37 do not fit; 29 does
    capped, _ = rights.cap(doc, {PAPER: {"class": "in_copyright", "licence": "x", "basis": "y", "text_chars": 10}})
    full, rep = rights.rehydrate(capped, {PAPER: TEXT})
    assert rep == {"restored": 3, "unresolved": [], "ok": True}
    for i, quote in enumerate(q):
        ev = next(n for n in full["nodes"] if n["id"] == f"ex:t/claim/{i}")["props"]["evidence"][0]
        assert match_text(ev["quote"]) == match_text(quote) and "note" not in ev
    assert "copper-free preparation" in json.dumps(full)                    # the line break comes back as a space
    _, rep = rights.rehydrate(capped, {PAPER: "an unrelated text"})
    assert not rep["ok"] and {u["why"] for u in rep["unresolved"]} == {"not found in the source text"}
    _, rep = rights.rehydrate(capped, {})
    assert {u["why"] for u in rep["unresolved"]} == {"no source text"}


def test_rehydrate_finds_text_with_decomposed_accents():
    """Text extraction often writes an accent as a base letter and a combining mark; the checker's normalization
    composes them, and so must the window rehydrate slides over the source text."""
    text = "The pellets were calcined at 500 C in cafe\u0301 air, then the \u039f\u03a3 sample was \u1100\u1161 reduced. " * 2
    quotes = ["calcined at 500 C in cafe\u0301 air", "calcined at 500 C in caf\u00e9 air, then",   # decomposed, composed
              "the \u039f\u03a3 sample", "\u1100\u1161 reduced"]                                 # a final sigma; Hangul jamo
    doc = _doc([(PAPER, q, False) for q in quotes])
    for q in quotes:
        assert match_text(q) in match_text(text)                                 # the checker accepts each
    capped, rep = rights.cap(doc, {PAPER: {"class": "in_copyright", "licence": "x", "basis": "y", "text_chars": 10}})
    assert rep["sources"][PAPER]["withheld"] == len(quotes)
    full, rep = rights.rehydrate(capped, {PAPER: text})
    assert rep == {"restored": len(quotes), "unresolved": [], "ok": True}
    for i, quote in enumerate(quotes):
        ev = next(n for n in full["nodes"] if n["id"] == f"ex:t/claim/{i}")["props"]["evidence"][0]
        assert match_text(ev["quote"]) == match_text(quote)
    assert next(n for n in full["nodes"] if n["id"] == "ex:t/claim/0")["props"]["evidence"][0]["quote"] == quotes[0]


def test_the_cli_caps_reports_and_rehydrates(tmp_path, capsys):
    d = tmp_path / "ex"
    d.mkdir()
    (d / "rights.yaml").write_text(dump_yaml({"sources": {**RIGHTS, PAPER: {"class": "in_copyright", "licence": "x", "basis": "y",
                                                                             "text_chars": 100}}}))
    doc = _doc([(PAPER, TEXT[0:40], True), (PAPER, TEXT[100:160], False)])
    write_canonical(d / "doc.json", doc)
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "paper.txt").write_text(TEXT)                                   # <last segment of the source id>.txt
    assert main(["evidence", "report", str(d / "doc.json")]) == 1           # 100 distinct characters; the cap is 10
    capsys.readouterr()
    assert main(["evidence", "cap", str(d / "doc.json"), "-o", str(d / "capped.json")]) == 0
    assert json.loads(capsys.readouterr().out)["withheld"] == 2
    assert main(["evidence", "report", str(d / "capped.json")]) == 0
    assert main(["evidence", "rehydrate", str(d / "capped.json"), "--texts", str(texts), "-o", str(d / "back.json")]) == 0
    back = load_doc(d / "back.json")
    assert [match_text(n["props"]["evidence"][0]["quote"]) for n in back["nodes"] if n["label"] == "Claim"] == \
        [match_text(TEXT[0:40]), match_text(TEXT[100:160])]


def test_committed_documents_are_public_and_respect_the_cap(tmp_path):
    assert rights.access_problems(REPO) == [] and len(rights.committed_documents(REPO)) > 30
    res = rights.copyright_check(REPO)
    assert res["ok"], res["problems"]
    assert [d["document"] for d in res["documents"]] == ["domain/tests/fixtures/invalid/research-data-without-stewardship.json",
                                                     "examples/methanol-synthesis-public"]    # a graph kept as parts
    # a project's document, or a research document without rights, is found
    repo = tmp_path / "repo"
    (repo / "x").mkdir(parents=True)
    from conftest import EXAMPLES
    ex = load_doc(EXAMPLES / "scale-catal/example.json")
    write_canonical(repo / "x/public.json", ex)
    write_canonical(repo / "x/project.json", as_project_data(ex))
    hidden = json.loads(json.dumps(ex))
    hidden["nodes"][1]["props"]["stewardship"] = {"access": "institution"}
    write_canonical(repo / "x/one-record.json", hidden)
    write_canonical(repo / "work/local.json", as_project_data(ex))          # local material is not committed
    probs = rights.access_problems(repo)
    assert len(probs) == 3 and probs[0].startswith("x/one-record.json: 1 records are not public")
    assert probs[1] == "x/project.json: the graph's stewardship access is project"
    # a missing access is not public: SCALE's own visibility rule reads it as institution, and hides the document
    # from the public; so the check asks for an explicit access: public, on the graph or on every record
    from scale.pgraph import filter_for
    unstated = json.loads(json.dumps(ex))
    del unstated["graph"]["stewardship"]
    for r in unstated["nodes"] + unstated["links"]:
        r.get("props", {}).pop("stewardship", None)
    assert filter_for(unstated, [], "2026-10-04")["nodes"] == []           # what the tools show the public of it
    write_canonical(repo / "y/unstated.json", unstated)
    assert rights.access_problems(repo, [repo / "y/unstated.json"]) == [
        "y/unstated.json: the graph states no stewardship access (read as institution); declare access: public",
        f"y/unstated.json: {len(ex['nodes']) + len(ex['links'])} records are not public (e.g. {ex['nodes'][0]['id']})"]
    for r in unstated["nodes"] + unstated["links"]:                         # every record public on its own: still
        r.setdefault("props", {})["stewardship"] = {"access": "public"}     # the graph's own default is missing
    write_canonical(repo / "y/unstated.json", unstated)
    assert rights.access_problems(repo, [repo / "y/unstated.json"]) == [
        "y/unstated.json: the graph states no stewardship access (read as institution); declare access: public"]
    unstated["graph"]["stewardship"] = {"access": "public"}
    write_canonical(repo / "y/unstated.json", unstated)
    assert rights.access_problems(repo, [repo / "y/unstated.json"]) == []
    assert rights.copyright_check(repo)["problems"] == ["x/project.json: research data without a rights.yaml in its folder or above"]
    (repo / "x/rights.yaml").write_text(dump_yaml({"sources": {}}))
    assert rights.copyright_check(repo)["problems"] == [
        "x/project.json: source ex:exmpl/thermo/source/invented-paper has no entry in x/rights.yaml"]


def test_mixed_documents_are_held_to_the_cap_and_synthetic_examples_are_not(tmp_path, capsys):
    repo = tmp_path / "repo"
    (repo / "x").mkdir(parents=True)
    doc = _doc([(PAPER, TEXT[0:301], True)])                                # one quote over 300 characters
    doc["graph"]["data_status"] = "mixed"
    write_canonical(repo / "x/doc.json", doc)
    args = ["--repo", str(repo), "evidence", "report", "--all"]
    assert main(args) == 1                                                 # no rights file
    assert json.loads(capsys.readouterr().out)["problems"] == [
        "x/doc.json: research data without a rights.yaml in its folder or above"]
    (repo / "x/rights.yaml").write_text(dump_yaml({"sources": RIGHTS}))
    assert main(args) == 1                                                 # over the cap
    assert json.loads(capsys.readouterr().out)["problems"] == [
        f"x/doc.json: {PAPER}: 1 quoted texts longer than 300 characters (longest 301)"]
    doc["graph"]["data_status"] = "synthetic_example"                     # invented text: no cap
    write_canonical(repo / "x/doc.json", doc)
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["documents"] == []


def test_scale_check_runs_the_access_and_cap_checks():
    from scale.devcheck import check_steps
    cmds = {s["name"]: [c[c.index("--repo") + 2:] for c in s["cmds"]] for s in check_steps(REPO, fast=True)
            if all("--repo" in c for c in s["cmds"])}                    # the scale commands (not reuse lint)
    assert cmds["every committed document is public (stewardship access)"] == [["evidence", "access"]]
    assert cmds["quoted text respects the copyright cap"] == [["evidence", "report", "--all"]]


def _gaps(*instances):
    return {"corpus": "corpus/new", "sample": 2, "themes": [
        {"title": "Reactor volume", "cannot_express": "the volume of the catalyst bed", "why_it_matters": "space velocity",
         "instances": list(instances)}]}


def test_a_gap_report_leaves_the_data_repository_only_within_the_cap(tmp_path, capsys, monkeypatch):
    """A gap report from a data repository is posted here only after this deterministic check."""
    ok = rights.gap_report(_gaps({"source": OPEN, "locator": "Table 1", "quote": TEXT[:300]},
                                 {"source": PAPER, "locator": "p. 2, cc @ada"}), RIGHTS)
    assert ok["ok"] and ok["quoted_chars"] == {OPEN: 300}
    assert "### 1. Reactor volume" in ok["markdown"] and "p. 2, cc @​ada" in ok["markdown"]
    # every class is held to 300 characters a quote (an issue reaches more readers than the data repository)
    bad = rights.gap_report(_gaps({"source": OPEN, "locator": "Table 1", "quote": TEXT[:301]}), RIGHTS)
    assert not bad["ok"] and bad["markdown"] is None and "the quote has 301 characters; at most 300" in bad["problems"][0]
    # the restricted source's cap is 10 % of its 1,000 characters
    two = [{"source": BOOK, "locator": f"p. {i}", "quote": TEXT[i * 80:i * 80 + 80]} for i in range(2)]
    assert "source ex:t/source/book: 160 distinct quoted characters; the cap is 100" in rights.gap_report(_gaps(*two), RIGHTS)["problems"]
    assert "no entry in the rights file" in rights.gap_report(_gaps({"source": "ex:t/source/x", "locator": "p. 1"}), RIGHTS)["problems"][0]
    extra = _gaps({"source": OPEN, "locator": "p. 1"})
    extra["records"] = [{"id": "x"}]                               # nothing rides along in another field
    assert rights.gap_report(extra, RIGHTS)["problems"] == ["a gap report holds corpus, sample and themes, nothing else"]
    long = _gaps({"source": OPEN, "locator": "p. 1"})
    long["themes"][0]["cannot_express"] = TEXT
    assert "at most 1000" in rights.gap_report(long, RIGHTS)["problems"][0]
    # the CLI finds the corpus's rights.yaml and writes the Markdown only when the report passes
    monkeypatch.chdir(tmp_path)
    (tmp_path / "corpus/new").mkdir(parents=True)
    (tmp_path / "corpus/rights.yaml").write_text(dump_yaml({"sources": RIGHTS}))
    write_canonical(tmp_path / "ok.json", _gaps({"source": OPEN, "locator": "Table 1", "quote": TEXT[:100]}))
    write_canonical(tmp_path / "bad.json", _gaps({"source": OPEN, "locator": "Table 1", "quote": TEXT[:400]}))
    assert main(["evidence", "gap-report", "ok.json", "--corpus", "corpus/new", "-o", "ok.md"]) == 0
    assert (tmp_path / "ok.md").read_text().startswith("Corpus `corpus/new`, sample 2: 1 gap theme.")
    assert main(["evidence", "gap-report", "bad.json", "--corpus", "corpus/new", "-o", "bad.md"]) == 1
    assert not (tmp_path / "bad.md").exists()
    capsys.readouterr()
