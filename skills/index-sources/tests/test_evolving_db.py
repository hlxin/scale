"""publications/papers.db evolves in place: each export publishes only the papers the ledger marked, records the run and
what changed, keeps author ids, keeps the full-text index in step, writes CSVs only on request, carries its working
state (so a project received as papers.db alone is rebuilt and carries on), and re-runs its saved filters.

    python -m pytest tests          (from the skill folder; standard library and pytest only)
"""
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

pytest.importorskip("sqlite3")


def has_fts():
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True
    except sqlite3.OperationalError:
        return False


def paper(led, pid, title, authors, access="Paywalled", doi=None, abstract="A long enough abstract about "
          "catalysts and their activity, written for the test so that it is not treated as missing at all."):
    led.x("INSERT INTO papers (id, key, doi, title, authors, authors_detail, year, journal, doc_type, abstract, "
          "access_type, databases) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
          (pid, doi or f"nodoi:{pid}", doi, title, json.dumps([a["name"] for a in authors]), json.dumps(authors), 2025,
           "J. Test", "article", abstract, access, json.dumps(["openalex"])))
    led.set_topic(pid, "t", in_scope=1, relevance=4)
    if doi:
        led.add_dois(pid, [doi])


@pytest.fixture()
def project(tmp_path):
    from _common import Project
    from _ledger import Ledger
    proj = Project(tmp_path)
    (proj.scr / "t").mkdir(parents=True, exist_ok=True)
    (proj.scr / "t" / "config.json").write_text(json.dumps({"topic": "Test topic", "slug": "t"}))
    (proj.scr / "t" / "queries.json").write_text(json.dumps({"openalex": {"q1": "title.search:copper"}}))
    led = Ledger(proj)
    paper(led, 1, "Copper oxide reduces CO2", [{"name": "Ada Lovelace", "orcid": "0000-0001"}], doi="10.1/a")
    paper(led, 2, "Nickel phosphide for hydrogen", [{"name": "Alan Turing"}], doi="10.1/b")
    paper(led, 3, "Copper oxide reduces CO2 (preprint)", [{"name": "Ada Lovelace", "orcid": "0000-0001"}],
          doi="10.1/a-preprint")
    led.add_si_links([{"parent_doi": "10.1/a", "si_doi": "10.1/a.s001", "url": "https://x/s1", "title": "SI",
                       "source": "crossref_component"}])
    led.x("INSERT INTO paper_subjects VALUES (1, 'co2rr', 'main', 1, 'vocab', 1.0)")
    return proj, led


def counts_match(proj):
    """The topics' counts kept by deltas equal a full recount."""
    con = sqlite3.connect(str(proj.db))
    for slug, papers, ins, outs, dl in con.execute("SELECT slug, papers, in_scope, out_of_scope, downloaded FROM collections"):
        full = con.execute("SELECT COUNT(*), SUM(CASE WHEN c.in_scope=1 AND COALESCE(p.is_non_paper,0)=0 AND "
                           "COALESCE(p.is_retracted,0)=0 THEN 1 ELSE 0 END), SUM(CASE WHEN c.in_scope=0 AND "
                           "COALESCE(p.is_non_paper,0)=0 THEN 1 ELSE 0 END), SUM(CASE WHEN c.pdf_path IS NOT NULL "
                           "THEN 1 ELSE 0 END) FROM paper_collections c JOIN papers p ON p.id = c.paper_id "
                           "WHERE c.collection=?", (slug,)).fetchone()
        assert (papers, ins, outs, dl) == tuple(x or 0 for x in full), slug
    con.close()
    return True


def db(proj):
    con = sqlite3.connect(str(proj.db))
    con.row_factory = sqlite3.Row
    return con


def test_the_database_evolves_in_place_and_records_what_changed(project):
    proj, led = project
    led.export(topics=["t"])                                       # the first evolving build
    assert proj.db.is_file() and not (proj.pub / "t" / "index").exists()       # no CSVs unless asked
    ino = proj.db.stat().st_ino
    con = db(proj)
    assert con.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 3
    assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    ada = con.execute("SELECT id FROM authors WHERE orcid='0000-0001'").fetchone()[0]
    con.close()
    assert not led.q("SELECT 1 FROM publish_queue")             # everything published
    led.set(2, access_type="OA", license="cc-by")                  # a change to one paper
    paper(led, 4, "Ruthenium single atoms for ammonia", [{"name": "Grace Hopper"}], doi="10.1/d")   # a new paper
    led.export(topics=["t"])
    assert proj.db.stat().st_ino == ino                            # the same file, updated in place: no rebuild
    assert counts_match(proj)
    con = db(proj)
    run = con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert (run["added"], run["updated"], run["removed"], run["papers"]) == (1, 1, 0, 4)
    ch = {(r["paper_id"], r["change"], r["field"], r["old"], r["new"]) for r in con.execute(
        "SELECT * FROM changes WHERE run_id=?", (run["id"],))}
    assert (2, "changed", "access_type", "Paywalled", "OA") in ch and (4, "added", None, None, "t") in ch
    assert con.execute("SELECT id FROM authors WHERE orcid='0000-0001'").fetchone()[0] == ada   # stable author ids
    if has_fts():
        assert [r[0] for r in con.execute("SELECT rowid FROM papers_fts WHERE papers_fts MATCH 'ruthenium'")] == [4]
    con.close()


def test_a_merge_is_recorded_and_the_merged_paper_leaves(project):
    proj, led = project
    led.export(topics=["t"])
    for d in led.aliases(3):                                       # what dedup.merge does: aliases move, the row goes
        led.x("UPDATE dois SET paper_id=1 WHERE doi=?", (d,))
    for t in ("paper_subjects", "extractions", "paper_topics"):
        led.x(f"DELETE FROM {t} WHERE paper_id=3")
    led.x("DELETE FROM papers WHERE id=3")
    led.export()
    con = db(proj)
    assert con.execute("SELECT COUNT(*) FROM papers WHERE id=3").fetchone()[0] == 0
    assert counts_match(proj)
    gone = con.execute("SELECT change, old, new FROM changes WHERE paper_id=3").fetchone()
    assert tuple(gone) == ("removed", "10.1/a-preprint", "merged into 1")
    assert {r[0] for r in con.execute("SELECT value FROM identifiers WHERE paper_id=1 AND scheme='doi'")} == \
        {"10.1/a", "10.1/a-preprint"}
    if has_fts():
        assert not con.execute("SELECT rowid FROM papers_fts WHERE papers_fts MATCH 'preprint'").fetchall()
    con.close()


def test_csvs_only_on_request_and_a_rebuild_keeps_the_history(project):
    proj, led = project
    led.export(topics=["t"])
    led.set(1, access_type="OA")
    led.export(topics=["t"])
    n = led.export(topics=["t"], db=False, csv=True)
    assert n == 3 and (proj.pub / "t" / "index" / "merged.csv").is_file()
    led.export(rebuild=True)
    con = db(proj)
    assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 3        # build, sync, rebuild
    assert con.execute("SELECT COUNT(*) FROM changes WHERE field='access_type'").fetchone()[0] == 1
    con.close()


def test_a_project_received_as_papers_db_alone_carries_on(project, tmp_path):
    proj, led = project
    led.x("INSERT INTO extractions VALUES (1, 't', 'run-1', 'extracted', '0.5.0', 18, 25, '2026-10-19', 'ok')")
    led.add_si_links([{"parent_doi": "10.9/issue-7", "si_doi": "10.9/issue-7.s1", "url": "https://x/i", "title": "SI",
                       "source": "crossref"}])                        # an SI link whose parent is no indexed paper
    led.export(topics=["t"])
    other = tmp_path / "received"
    (other / "publications").mkdir(parents=True)
    shutil.copy(proj.db, other / "publications" / "papers.db")
    from _common import Project
    from _ledger import Ledger
    proj2 = Project(other)
    led2 = Ledger(proj2)                                           # no ledger: it is rebuilt from the database
    for table, key in (("papers", "id"), ("paper_topics", "paper_id, topic"), ("paper_subjects", "paper_id, term"),
                       ("dois", "doi"), ("si_links", "parent_doi, si_doi"), ("extractions", "paper_id, topic, kg")):
        a = [tuple(r) for r in led.q(f"SELECT * FROM {table} ORDER BY {key}")]
        b = [tuple(r) for r in led2.q(f"SELECT * FROM {table} ORDER BY {key}")]
        assert a == b, table
    assert json.loads((proj2.scr / "t" / "queries.json").read_text()) == {"openalex": {"q1": "title.search:copper"}}
    assert not led2.q("SELECT 1 FROM publish_queue")
    led2.set(2, access_type="OA")                                  # and it carries on, in place
    led2.export()
    con = db(proj2)
    assert con.execute("SELECT access_type FROM papers WHERE id=2").fetchone()[0] == "OA"
    assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
    con.close()


@pytest.mark.skipif(not has_fts(), reason="this SQLite has no FTS5")
def test_a_saved_filter_follows_the_database(project):
    proj, led = project
    led.export(topics=["t"])
    from _filters import define, refresh
    con = db(proj)
    with con:
        define(con, "copper", {"description": "copper papers", "exclude": {"retracted": True},
                               "groups": {"cu": [{"fts": "copper", "topics": ["co2rr"]}]}})
    assert refresh(con) == {"copper": 2}
    con.close()
    led.set(2, title="Nickel and copper phosphide for hydrogen")    # its text changes: the filter re-runs by itself
    res = led.export()
    assert led.last_publish["filters"] == {"copper": 3} and res == 1
    con = db(proj)
    levels = {(r[0], r[1]) for r in con.execute("SELECT paper_id, level FROM filter_members WHERE filter='copper'")}
    assert levels == {(1, "strict"), (2, "strict"), (3, "strict")}
    con.close()
