"""import_list.py with patent numbers and SCALE corpus lists: a patent number in its usual forms gives one patent row
(keyed by office and number, the row a patent search finds), a corpus list's statuses become manual scope decisions
that later screening keeps, two patents of one office's series are never merged however alike they look, and
topics.py set --add puts a topic in front of a paper's own.

    python -m pytest tests          (from the skill folder; standard library and pytest only)
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

TITLE = "Catalyst for synthetic-methanol production"
SOURCES = [
    {"kind": "patent", "status": "in_scope", "patent": "US1625924A", "title": TITLE, "published": "1927-04-26",
     "assignee": "Roessler & Hasslacher Chemical", "date_basis": "grant date printed on the patent"},
    {"kind": "patent", "status": "in_scope", "patent": "US1625925A", "title": TITLE, "published": "1927",
     "assignee": "Roessler & Hasslacher Chemical", "date_basis": "grant date printed on the patent"},
    {"kind": "patent", "status": "not_retrieved", "patent": "GB240955A", "published": "1924", "assignee": "BASF",
     "title": "Improvements in the synthetic manufacture of methanol and higher alcohols",
     "date_basis": "priority year only (grant date unknown)", "inventors": "Alwin Mittasch; Mathias Pier"},
    {"kind": "patent", "status": "off_scope", "patent": "US3285948A", "published": "1966-11-15",
     "title": "Halides of ruthenium and osmium in conjunction with cobalt and iodine", "off_scope": "homogeneous"},
    {"kind": "thesis_or_report", "status": "in_scope", "published": "1940", "authors": ["Alexander R. Roy"],
     "title": "Some observations on the mechanism of surface reactions in the synthesis of methanol",
     "venue": "PhD thesis, University of Glasgow (Enlighten)"},
    {"kind": "thesis_or_report", "status": "in_scope", "published": "1953", "title": "Synthese-gasfabriek der methanol-synthese",
     "venue": "Research Repository (Delft University of Technology)"},
    {"kind": "article", "status": "not_screened", "published": "1931",
     "title": "A note on zinc chromite catalysts and their reduction", "venue": "Journal of Old Chemistry"},
]


def run(script, proj, *args):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / script), "--project", str(proj.root), *map(str, args)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.fixture()
def project(tmp_path):
    from _common import Project
    proj = Project(tmp_path / "project")
    for slug in ("t", "u"):
        (proj.scr / slug).mkdir(parents=True, exist_ok=True)
        (proj.scr / slug / "config.json").write_text(json.dumps(
            {"topic": f"Test topic {slug}", "slug": slug, "screening": {"method": "keywords", "threshold": 3}}))
        (proj.scr / slug / "keywords.json").write_text(json.dumps(          # nothing here matches these titles
            {"include_groups": [["electrocatalytic nitrate reduction"]], "threshold": 3}))
    corpus = tmp_path / "graphs" / "demo-corpus" / "sources.json"
    corpus.parent.mkdir(parents=True)
    corpus.write_text(json.dumps({"corpus": "demo", "sources": SOURCES}))
    return proj, corpus


def ledger(proj):
    from _ledger import Ledger
    return Ledger(proj)


def test_patent_numbers_in_their_usual_forms_give_one_key(tmp_path):
    import import_list as il
    keys = {il.patent_entry(n, loose=True)["key"] for n in ("US1558559A", "US-1558559-A", "US 1,558,559", "us1558559a")}
    assert keys == {"patent:US1558559"}
    e = il.patent_entry("DE1568864A1", "Process for the synthetic production of methanol", "1965", "ICI", "A. B; C. D")
    assert e["ids"] == {"patent": "DE-1568864-A1"} and e["journal"] == "DE patent" and e["authors"] == ["A. B", "C. D"]
    assert e["link"] == "https://patents.google.com/patent/DE1568864A1" and e["publisher"] == "ICI"
    for not_a_number in ("2023", "ID 12345", "WOS:000123", "OSTI:5111572", "arXiv:2101.00001", "10.1021/ie50223a008"):
        assert il.patent_number(not_a_number) is None
    txt = tmp_path / "list.txt"
    txt.write_text("10.1021/ie50223a008\nUS1681751A\nsome text 2023\nGB-229715-A\n")
    got = il.read_entries(txt)
    assert [e.get("doi") or e.get("key") for e in got] == ["10.1021/ie50223a008", "patent:US1681751", "patent:GB229715"]
    gp = tmp_path / "google.csv"           # a Google Patents CSV export: the search line, then the table
    gp.write_text("search URL:,https://patents.google.com/?q=methanol\nid,title,assignee,inventor/author,priority date,"
                  "filing/creation date,publication date,grant date,result link\nUS-1681751-A,Synthesis of methanol,"
                  "Du Pont,\"Wilbur A. Lazier, Some One\",1927-05-16,1927-05-16,1928-08-21,1928-08-21,"
                  "https://patents.google.com/patent/US1681751A/en\n")
    (e,) = il.read_entries(gp)
    assert (e["key"], e["year"], e["publisher"], e["authors"]) == ("patent:US1681751", "1928", "Du Pont",
                                                                    ["Wilbur A. Lazier", "Some One"])
    js = tmp_path / "list.json"
    js.write_text(json.dumps(["10.1021/ie50223a008", "US1681752A", {"patent": "US 1,681,753", "title": "Synthesis"}]))
    assert [e.get("doi") or e.get("key") for e in il.read_entries(js)] == ["10.1021/ie50223a008", "patent:US1681752",
                                                                          "patent:US1681753"]


def test_a_scale_corpus_list_keeps_its_statuses_as_manual_decisions(project):
    proj, corpus = project
    res = run("import_list.py", proj, "--topic", "t", "--file", corpus, "--scope", "file")
    assert (res["records_written"], res["patents"], res["decided_in_scope"], res["decided_out_of_scope"]) == (7, 4, 5, 1)
    assert res["exports"] == {"SCALE corpus list": 7}
    b = run("build_list.py", proj, "--topic", "t", "--run", "manual")
    assert (b["new_in_ledger"], b["manual_decisions"]) == (7, 6)
    led = ledger(proj)
    rows = {r["key"]: dict(r) for r in led.q("SELECT p.*, t.relevance, t.relevance_note, t.relevance_method, t.in_scope "
                                              "FROM papers p JOIN paper_topics t ON t.paper_id=p.id AND t.topic='t'")}
    us = rows["patent:US1625924"]
    assert (us["doc_type"], us["journal"], us["publisher"], us["year"]) == ("patent", "US patent",
                                                                            "Roessler & Hasslacher Chemical", 1927)
    assert json.loads(us["external_ids"]) == {"patent": "US-1625924-A"} and json.loads(us["databases"]) == ["manual", "scale"]
    assert (us["relevance_method"], us["in_scope"], us["relevance"]) == ("manual", 1, 5)
    assert "patent:US1625925" in rows                                        # same title, its own row
    gb = rows["patent:GB240955"]
    assert "full text not in the corpus" in gb["relevance_note"] and "priority year" in gb["relevance_note"]
    assert json.loads(gb["authors"]) == ["Alwin Mittasch", "Mathias Pier"]
    off = rows["patent:US3285948"]
    assert (off["in_scope"], off["relevance_method"]) == (0, "manual") and "homogeneous" in off["relevance_note"]
    by_title = {r["title"]: r for r in rows.values()}
    assert by_title["Some observations on the mechanism of surface reactions in the synthesis of methanol"]["doc_type"] == "thesis"
    assert by_title["Synthese-gasfabriek der methanol-synthese"]["doc_type"] == "report"      # a 3-word title is kept
    assert by_title["A note on zinc chromite catalysts and their reduction"]["relevance_method"] is None
    run("screen.py", proj, "--topic", "t", "keywords")          # would score every title out of scope
    led = ledger(proj)
    methods = dict(led.q("SELECT p.key, t.relevance_method || ':' || t.in_scope FROM papers p JOIN paper_topics t "
                         "ON t.paper_id=p.id AND t.topic='t'"))
    assert methods["patent:US1625924"] == "manual:1" and methods["patent:US3285948"] == "manual:0"
    assert sorted(v for v in methods.values() if not v.startswith("manual")) == ["keywords:0"]


def test_the_same_list_into_another_topic_finds_the_same_rows(project):
    proj, corpus = project
    run("import_list.py", proj, "--topic", "t", "--file", corpus, "--scope", "file")
    run("build_list.py", proj, "--topic", "t", "--run", "manual")
    run("import_list.py", proj, "--topic", "u", "--file", corpus, "--scope", "in")
    b = run("build_list.py", proj, "--topic", "u", "--run", "manual")
    assert (b["new_in_ledger"], b["already_in_ledger"], b["manual_decisions"]) == (0, 7, 7)
    led = ledger(proj)
    assert tuple(led.q("SELECT COUNT(*), SUM(in_scope) FROM paper_topics WHERE topic='u' AND relevance_method='manual'")[0]) == (7, 7)
    assert led.q("SELECT in_scope FROM paper_topics t JOIN papers p ON p.id=t.paper_id "
                 "WHERE p.key='patent:US3285948' AND t.topic='t'")[0][0] == 0      # topic t keeps its own decision


def test_two_patents_of_one_series_are_never_merged(project):
    proj, corpus = project
    run("import_list.py", proj, "--topic", "t", "--file", corpus, "--scope", "file")
    run("build_list.py", proj, "--topic", "t", "--run", "manual")
    import dedup
    led = ledger(proj)
    us24, us25 = (led.find_id(key=k) for k in ("patent:US1625924", "patent:US1625925"))
    for pid in (us24, us25):                   # same title, same inventor, granted the same day: still two patents
        led.set(pid, authors=["Wilbur A. Lazier"])
    gb = led.upsert({"key": "patent:GB271840", "title": TITLE, "authors": ["Wilbur A. Lazier"], "year": 1926,
                     "doc_type": "patent", "external_ids": {"patent": "GB-271840-A"}}, "t")[0]
    groups, _ = dedup.find(led)
    pairs = {(kind, k["id"], o["id"]) for kind, k, o in groups}
    assert {(k, o) for _, k, o in pairs} == {(us24, gb)}                      # the GB filing joins one of them
    assert {kind for kind, _, _ in pairs} == {"patent_family"}


def test_set_add_puts_a_topic_in_front_of_the_papers_own(project):
    proj, corpus = project
    run("import_list.py", proj, "--topic", "t", "--file", corpus, "--scope", "file")
    run("build_list.py", proj, "--topic", "t", "--run", "manual")
    led = ledger(proj)
    pid = led.find_id(key="patent:US1625924")
    with led.tx():
        led.set_subjects(pid, ["co2-hydrogenation", "rwgs", "fts"], [], "vocab", force=True)
    run("topics.py", proj, "set", "--ids", pid, "--main", "co2-methanol", "--add", "--topic", "t")
    led = ledger(proj)
    subj = led.subjects_of(pid)
    assert [s["term"] for s in sorted(subj, key=lambda s: s["rank"]) if s["kind"] == "main"] == [
        "co2-methanol", "co2-hydrogenation", "rwgs"]
    assert "fts" in {s["term"] for s in subj if s["kind"] == "related"}
    assert {s["method"] for s in subj if s["kind"] == "main"} == {"manual"}
