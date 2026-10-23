"""A project made before the sources were so named (publications/papers.db, tables papers / paper_* / collections,
paper_id, license, download_*, the PDFs in <topic>/papers/) is upgraded when a script opens it: folders, file names,
tables, columns, the changes it recorded, the full-text index and the stored paths, with nothing lost; and it is
upgraded once.

    python -m pytest tests          (from the skill folder; standard library and pytest only)
"""
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

from _upgrade import COLUMNS, TABLE_COLUMNS, TABLES  # noqa: E402


def make_project(root):
    from _common import Project
    from _ledger import Ledger
    proj = Project(root)
    (proj.scr / "t").mkdir(parents=True, exist_ok=True)
    (proj.scr / "t" / "config.json").write_text(json.dumps({"topic": "Test topic", "slug": "t"}))
    led = Ledger(proj)
    for pid, title in ((1, "Copper oxide reduces CO2 to ethylene"), (2, "Zinc oxide promotes copper for methanol")):
        led.x("INSERT INTO sources (id, key, doi, title, authors, year, journal, doc_type, access_type, databases) "
              "VALUES (?,?,?,?,?,?,?,?,?,?)", (pid, f"10.1/{pid}", f"10.1/{pid}", title, '["A. Author"]', 2024, "J",
                                               "article", "OA", '["openalex"]'))
        led.add_dois(pid, [f"10.1/{pid}"])
        rel = f"sources/t/files/OA/{pid}.pdf"
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"%PDF-1.4\n")
        led.set(pid, downloaded=1)
        led.set_topic(pid, "t", in_scope=1, relevance=5, path=rel)
    led.add_si_links([{"parent_doi": "10.1/1", "si_doi": "10.1/1.s001", "url": "https://x/s1", "title": "SI",
                       "source": "crossref_component"}])
    led.export()
    corpus = root / "sources/t/corpora/c/sources.json"
    corpus.parent.mkdir(parents=True)
    corpus.write_text(json.dumps({"topic": "t", "counts": {"in_scope": 1}, "sources": [
        {"slug": "10.1-1", "status": "in_scope", "source_id": 1, "pdf": "../../files/OA/1.pdf"}]}))
    led.db.close()


def downgrade_db(path, kind, fts=False):
    """The database as the skill wrote it before the rename (the upgrade's maps for its kind, read backwards)."""
    con = sqlite3.connect(str(path), isolation_level=None)
    for t, n in con.execute("SELECT type, name FROM sqlite_master WHERE type IN ('view', 'trigger')").fetchall():
        if not n.startswith("passages_fts"):
            con.execute(f'DROP {t.upper()} "{n}"')
    con.execute("DROP TABLE IF EXISTS sources_fts")
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for (t, old), new in TABLE_COLUMNS.get(kind, {}).items():
        if t in tables:
            con.execute(f'ALTER TABLE "{t}" RENAME COLUMN "{new}" TO "{old}"')
    for t in tables:
        for col in [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]:
            old = {v: k for k, v in COLUMNS.items()}.get(col)
            if old:
                con.execute(f'ALTER TABLE "{t}" RENAME COLUMN "{col}" TO "{old}"')
    for old, new in reversed(list(TABLES[kind].items())):
        if new in tables:
            con.execute(f'ALTER TABLE "{new}" RENAME TO "{old}"')
            tables = (tables - {new}) | {old}
    if "changes" in tables:
        con.execute("UPDATE changes SET change = 'collection' WHERE change = 'topic'")
        con.execute("UPDATE changes SET field = 'license' WHERE field = 'licence'")
    for t, col in (("paper_topics", "path"), ("paper_collections", "pdf_path"), ("files", "path")):
        if t in tables:
            con.execute(f"UPDATE {t} SET {col} = replace(replace({col}, 'sources/t/files/', 'publications/t/papers/'), "
                        "'sources/', 'publications/')")
    if fts:
        con.execute("CREATE VIRTUAL TABLE papers_fts USING fts5(title, abstract, keywords, content='papers', "
                    "content_rowid='id')")
        con.execute("INSERT INTO papers_fts(papers_fts) VALUES ('rebuild')")
        con.execute("CREATE VIEW v_papers AS SELECT p.* FROM papers p")
    con.close()


def downgrade(root):
    pub = root / "sources"
    downgrade_db(pub / "index.db", "index", fts=True)
    downgrade_db(root / ".scripts" / "ledger.sqlite", "ledger")
    (pub / "index.db").rename(pub / "papers.db")
    (pub / "t" / "files").rename(pub / "t" / "papers")
    m = pub / "t/corpora/c/sources.json"
    m.write_text(m.read_text().replace("../../files/", "../../papers/").replace('"source_id"', '"paper_id"'))
    pub.rename(root / "publications")


def names(path):
    con = sqlite3.connect(str(path))
    try:
        return {r[0]: r[1] or "" for r in con.execute("SELECT name, sql FROM sqlite_master")}
    finally:
        con.close()


def test_an_old_project_is_upgraded_with_nothing_lost(tmp_path):
    root = tmp_path / "project"
    make_project(root)
    downgrade(root)
    assert "papers" in names(root / "publications/papers.db") and (root / "publications/t/papers/OA/1.pdf").is_file()

    from _common import Project
    from _ledger import Ledger
    proj = Project(root)                                     # what every script does first
    assert not (root / "publications").exists() and (root / "sources/t/files/OA/1.pdf").is_file()
    idx, ledger = names(root / "sources/index.db"), names(root / ".scripts/ledger.sqlite")
    for n in ("sources", "databases", "source_databases", "topics", "source_topics", "_source_state", "sources_fts",
              "v_sources", "v_topic_sources"):
        assert n in idx, n
    assert not [n for n in idx if "paper" in n] and not [n for n in ledger if "paper" in n]
    con = sqlite3.connect(str(proj.db))
    assert not [n for n in idx if "collection" in n]
    cols = {r[1] for r in con.execute("PRAGMA table_info(sources)")}
    assert {"licence", "licence_url", "licence_source", "retrieved_from", "retrieved_url", "retrieved_on",
            "is_notice"} <= cols and not [c for c in cols if c.startswith(("license", "download_"))]
    assert con.execute("SELECT slug, name, sources FROM topics").fetchall() == [("t", "Test topic", 2)]
    assert not con.execute("SELECT 1 FROM changes WHERE change = 'collection' OR field = 'license'").fetchall()
    assert con.execute("SELECT source_id, pdf_path FROM source_topics ORDER BY 1").fetchall() == [
        (1, "sources/t/files/OA/1.pdf"), (2, "sources/t/files/OA/2.pdf")]
    assert con.execute("SELECT database FROM source_databases WHERE source_id = 1").fetchone() == ("openalex",)
    assert con.execute("SELECT found_by FROM supplements").fetchone() == ("crossref_component",)
    assert con.execute("SELECT rowid FROM sources_fts WHERE sources_fts MATCH 'methanol'").fetchall() == [(2,)]
    con.close()
    m = json.loads((root / "sources/t/corpora/c/sources.json").read_text())
    assert m["sources"][0]["source_id"] == 1 and m["sources"][0]["pdf"] == "../../files/OA/1.pdf"
    led = Ledger(proj)                                       # and the project carries on: a change reaches the index
    led.set_topic(2, "t", relevance=1, relevance_note="after the upgrade")
    led.export()
    con = sqlite3.connect(str(proj.db))
    assert con.execute("SELECT relevance_note FROM source_topics WHERE source_id = 2").fetchone() == (
        "after the upgrade",)
    con.close()
    led.db.close()
    before = names(root / "sources/index.db")
    Project(root)                                            # once: a second open changes nothing
    assert names(root / "sources/index.db") == before
