"""The index columns Retracted and Preprint link (papers.db: is_retracted, preprint_url): a journal article keeps the
links of the preprints merged into its row, a retraction notice is told from the paper it retracts (repair.py from
the cached Crossref answers, classify_access.py as it decides), and a database of an older version gains the new
column, filled, at its next update.

    python -m pytest tests          (from the skill folder; standard library and pytest only)
"""
import csv
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

ABSTRACT = ("An abstract long enough to count as one, about copper catalysts, how they are made and how well they "
            "work in the tests reported here.")
NOTICE = {"doi": "10.1016/j.notice", "update_to": [{"DOI": "10.1016/j.retracted", "type": "retraction",
                                                    "label": "Retraction"}]}
SELF = {"doi": "10.1016/j.self", "update_to": [{"DOI": "10.1016/j.self", "type": "retraction"}]}


def run(script, proj, *args):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / script), "--project", str(proj.root), *map(str, args)],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def paper(led, pid, doi, title, doc_type="article", **f):
    led.x("INSERT INTO papers (id, key, doi, title, authors, year, journal, doc_type, abstract, access_type, databases) "
          "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (pid, doi, doi, title, json.dumps(["A. Author"]), 2024, "J. Test", doc_type,
                                            ABSTRACT, "Paywalled", json.dumps(["openalex"])))
    if f:
        led.set(pid, **f)
    led.set_topic(pid, "t", in_scope=1, relevance=4)
    led.add_dois(pid, [doi])


@pytest.fixture()
def project(tmp_path):
    from _common import Project
    from _ledger import Ledger
    proj = Project(tmp_path / "project")
    (proj.scr / "t").mkdir(parents=True, exist_ok=True)
    (proj.scr / "t" / "config.json").write_text(json.dumps({"topic": "Test topic", "slug": "t"}))
    led = Ledger(proj)
    paper(led, 1, "10.1021/acs.one", "A journal article with a ChemRxiv preprint and an arXiv record",
          external_ids={"arxiv": "2101.00001v2"})
    led.add_dois(1, ["10.26434/chemrxiv-2020-one"])                       # its preprint, merged into its row
    paper(led, 2, "10.1016/j.two", "A journal article whose arXiv copy only the open-access lookups know",
          versions=[{"url": "https://zenodo.org/record/9", "version": "submittedVersion"},
                    {"url": "https://arxiv.org/abs/2202.02222v1", "version": "submittedVersion"}])
    paper(led, 3, "10.26434/chemrxiv-2022-three", "A preprint that is not published yet", doc_type="preprint",
          is_preprint=1)
    paper(led, 4, "10.1021/acs.four", "A journal article without a preprint")
    paper(led, 5, "10.1016/j.retracted", "Copper catalysts that were later retracted")
    paper(led, 6, "10.1016/j.notice", "Retraction notice to Copper catalysts that were later retracted",
          doc_type="erratum", retracted=1, is_erratum=1)                    # as older versions marked a notice
    paper(led, 7, "10.1016/j.self", "RETRACTED: A paper its publisher marked itself")
    led.export()
    return proj


def cache(proj, name, recs):
    from _cache import Cache
    Cache(proj, name).add([{"found": True, **r} for r in recs])


def index_rows(proj):
    rows = {}
    for f in ("merged.csv", "excluded.csv"):
        with open(proj.index_dir("t") / f, encoding="utf-8-sig", newline="") as fh:
            rows.update({int(r["ID"]): r for r in csv.DictReader(fh)})
    return rows


def db(proj):
    return sqlite3.connect(str(proj.db))


def test_a_journal_article_keeps_its_preprint_links(project):
    proj = project
    run("export.py", proj, "--topic", "t", "--csv")
    rows = index_rows(proj)
    with open(proj.index_dir("t") / "merged.csv", encoding="utf-8-sig", newline="") as fh:
        header = next(csv.reader(fh))
    assert header[6:11] == ["Doc type", "Retracted", "DOI/ID", "URL", "Preprint link"]
    assert rows[1]["URL"] == "https://doi.org/10.1021/acs.one"
    assert rows[1]["Preprint link"] == "https://doi.org/10.26434/chemrxiv-2020-one; https://arxiv.org/abs/2101.00001"
    assert rows[2]["Preprint link"] == "https://arxiv.org/abs/2202.02222"            # not the Zenodo copy
    assert rows[3]["Preprint link"] == "https://doi.org/10.26434/chemrxiv-2022-three"  # a preprint: its own link
    assert rows[4]["Preprint link"] == ""
    con = db(proj)
    assert dict(con.execute("SELECT id, preprint_url FROM papers WHERE id <= 4")) == {
        1: rows[1]["Preprint link"], 2: rows[2]["Preprint link"], 3: rows[3]["Preprint link"], 4: None}


def test_repair_tells_a_retraction_notice_from_the_paper_it_retracts(project):
    from _ledger import Ledger
    proj = project
    cache(proj, "crossref", [NOTICE, SELF])
    res = run("repair.py", proj, "--retractions-only")
    assert res["retractions"] == {"notices": 1, "notices_were_marked_retracted": 1, "papers_newly_retracted": 1,
                                  "marked_itself": 1}
    led = Ledger(proj)
    r5, r6, r7 = led.get(5), led.get(6), led.get(7)
    assert r5["retracted"] == 1 and r5["external_ids"]["retraction_notice"] == "10.1016/j.notice"
    assert (r6["retracted"], r6["is_erratum"], r6["external_ids"]["retraction_of"]) == (0, 1, "10.1016/j.retracted")
    assert r7["retracted"] == 1
    run("export.py", proj, "--topic", "t", "--csv")
    rows = index_rows(proj)
    assert rows[5]["Retracted"] == "Yes" and "RETRACTED (notice: https://doi.org/10.1016/j.notice)" in rows[5]["Notes"]
    assert rows[6]["Retracted"] == "Retraction notice"
    assert "Retraction notice of https://doi.org/10.1016/j.retracted" in rows[6]["Notes"]
    assert (rows[7]["Retracted"], rows[4]["Retracted"]) == ("Yes", "No")
    con = db(proj)
    assert dict(con.execute("SELECT id, is_retracted FROM papers WHERE id IN (5, 6, 7)")) == {5: 1, 6: 0, 7: 1}
    assert set(con.execute("SELECT paper_id, scheme, value FROM identifiers WHERE scheme LIKE 'retraction%'")) == {
        (5, "retraction_notice", "10.1016/j.notice"), (6, "retraction_of", "10.1016/j.retracted")}
    from test_evolving_db import counts_match
    assert counts_match(proj)
    again = run("repair.py", proj, "--retractions-only")
    assert again["retractions"] == {"notices": 1, "notices_were_marked_retracted": 0, "papers_newly_retracted": 0,
                                    "marked_itself": 0}


def test_classify_marks_the_paper_a_notice_retracts(project):
    from _ledger import Ledger
    proj = project
    dois = ["10.1021/acs.one", "10.26434/chemrxiv-2020-one", "10.1016/j.two", "10.26434/chemrxiv-2022-three",
            "10.1021/acs.four", "10.1016/j.retracted", "10.1016/j.notice", "10.1016/j.self"]
    cache(proj, "crossref", [{"doi": d, "type": "journal-article"} for d in dois if d not in (NOTICE["doi"], SELF["doi"])]
          + [NOTICE, SELF])
    # OpenAlex marks the notice as retracted too; only it knows that paper 4 is retracted
    cache(proj, "openalex", [{"doi": d, "retracted": d in ("10.1016/j.notice", "10.1021/acs.four"), "oa_status": "closed",
                              "locations": [], "ids": {}} for d in dois])
    skip = "s2,openalex,unpaywall,europepmc,pmcaws,datacite"                   # every answer is cached: no request
    res = run("classify_access.py", proj, "--topic", "t", "--refresh", "--skip", skip)
    assert (res["newly_retracted"], res["retraction_notices"]) == (3, 1)
    led = Ledger(proj)
    flags = {i: (led.get(i)["retracted"], led.get(i)["is_erratum"]) for i in (4, 5, 6, 7)}
    assert flags == {4: (1, 0), 5: (1, 0), 6: (0, 1), 7: (1, 0)}
    assert led.get(5)["external_ids"]["retraction_notice"] == "10.1016/j.notice"
    again = run("classify_access.py", proj, "--topic", "t", "--refresh", "--skip", skip)
    assert again["newly_retracted"] == 0 and Ledger(proj).get(6)["retracted"] == 0     # the notice stays a notice


def test_an_older_database_gains_the_preprint_column(project, tmp_path):
    from _ledger import Ledger
    proj = project
    con = db(proj)
    con.execute("ALTER TABLE papers DROP COLUMN preprint_url")              # papers.db as paper-acquisition 3.6 left it
    con.commit()
    con.close()
    spec = tmp_path / "all.filter.json"
    spec.write_text(json.dumps({"groups": {"all": [{"fts": "journal OR preprint OR retracted OR paper"}]}}))
    run("filters.py", proj, "define", "--name", "all", "--file", spec)
    sub = run("filters.py", proj, "export", "--name", "all", "--out", tmp_path / "subset.db")   # as it is
    assert sub["papers"] >= 4
    led = Ledger(proj)
    led.set(4, cited_by=5)                                                   # any update
    led.export()
    con = db(proj)
    links = dict(con.execute("SELECT id, preprint_url FROM papers"))
    assert links[1].startswith("https://doi.org/10.26434/chemrxiv-2020-one") and links[3] and links[4] is None
    assert links[2] == "https://arxiv.org/abs/2202.02222"
    note = con.execute("SELECT note FROM runs WHERE note LIKE 'papers gained%'").fetchone()[0]
    assert note == "papers gained preprint_url; 3 papers have a preprint link"
    assert con.execute("SELECT value FROM about WHERE name='format'").fetchone()[0] == "evolving-2"
