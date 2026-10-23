"""A project made before the sources were so named: upgraded in place, once (library module — not run directly).

Until index-sources 4.0 (paper-acquisition, and index-sources before this change) the skill called every source a
paper: publications/papers.db with tables papers, paper_authors, paper_collections ..., the PDFs in
publications/<topic>/papers/, and the search databases in a table `sources`. Now a source is a source (SCALE's word
for a paper, preprint, patent, thesis, report or dataset) and the services that find them are databases:

  publications/                 -> sources/
  publications/papers.db        -> sources/index.db
  <topic>/papers/<access>/      -> <topic>/files/<access>/
  tables   papers -> sources, paper_* -> source_*, sources (search services) -> databases,
           paper_sources -> source_databases, papers_fts -> sources_fts, _paper_state -> _source_state
  columns  paper_id -> source_id, is_non_paper -> is_notice, source_databases.database, supplements.found_by,
           collections.sources, runs.sources

upgrade_project() runs from Project() before anything is opened: it moves the folders, renames the databases'
tables and columns (an ALTER TABLE rename rewrites only the schema, so even a database of millions of rows takes
seconds; the full-text index is rebuilt) and rewrites the stored paths. It does nothing on a project that is
already upgraded. upgrade_db() upgrades one database file alone (upgrade.py --db: a copy received by itself).
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

TABLES = {  # old -> new, in this order (the search services' `sources` makes way for the sources first)
    "sources": "databases", "papers": "sources", "paper_authors": "source_authors",
    "paper_collections": "source_collections", "paper_subjects": "source_subjects", "paper_topics": "source_topics",
    "paper_sources": "source_databases", "_paper_state": "_source_state",
}
COLUMNS = {"paper_id": "source_id", "is_non_paper": "is_notice"}
TABLE_COLUMNS = {("source_databases", "source"): "database", ("supplements", "source"): "found_by",
                 ("collections", "papers"): "sources", ("runs", "papers"): "sources"}
PATH_COLUMNS = {("source_topics", "path"), ("source_topics", "si_paths"), ("sources", "si_files"),
                ("sources", "pdf"), ("source_collections", "pdf_path"), ("source_collections", "si_paths"),
                ("files", "path")}
_OLD_PATH = re.compile(r"(?<![\w.-])publications/([^/\"]+)/papers/")


def new_path(text):
    """Stored paths (a path, or JSON holding paths) as the upgraded project names them."""
    if not text or "publications/" not in text:
        return text
    return _OLD_PATH.sub(r"sources/\1/files/", text).replace("publications/", "sources/")


def _log(msg):
    print(f"[upgrade] {msg}", file=sys.stderr, flush=True)


def is_old(con):
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
    return "papers" in names or bool(names & {"paper_topics", "paper_collections", "_paper_state"})


def upgrade_db(path):
    """Rename one database's tables and columns in place (index.db, the working ledger or the vector store).
    Returns True when something was upgraded."""
    path = Path(path)
    if not path.is_file():
        return False
    con = sqlite3.connect(str(path), timeout=300, isolation_level=None)
    try:
        if not is_old(con):
            return False
        _log(f"{path.name}: renaming papers to sources ...")
        con.execute("PRAGMA legacy_alter_table=OFF")
        con.execute("BEGIN IMMEDIATE")
        master = con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master").fetchall()
        tables = {n for t, n, _, _ in master if t == "table"}
        fts = [n for t, n, _, s in master if t == "table" and s and "VIRTUAL TABLE" in s.upper() and "paper" in n]
        # views, the full-text index and the triggers that name what is renamed: dropped, made again by the scripts
        for t, n, tbl, s in master:
            if t in ("view", "trigger") and s and (re.search(r"paper", s, re.I) or tbl in fts):
                con.execute(f'DROP {t.upper()} IF EXISTS "{n}"')
        for n in fts:
            con.execute(f'DROP TABLE IF EXISTS "{n}"')
        tables -= set(fts) | {n + s for n in fts for s in ("_data", "_idx", "_docsize", "_config", "_content")}
        for old, new in TABLES.items():
            if old in tables and new not in tables - {old}:
                con.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')
                tables = (tables - {old}) | {new}
        for t in sorted(tables):
            for col in [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]:
                new = TABLE_COLUMNS.get((t, col)) or COLUMNS.get(col)
                if new:
                    con.execute(f'ALTER TABLE "{t}" RENAME COLUMN "{col}" TO "{new}"')
        for n, s in con.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL "
                                "AND name LIKE '%paper%'").fetchall():
            con.execute(f'DROP INDEX "{n}"')
            con.execute(s.replace(n, n.replace("papers", "sources").replace("paper", "source"), 1))
        for t, col in PATH_COLUMNS:
            if t in tables and col in {r[1] for r in con.execute(f'PRAGMA table_info("{t}")')}:
                rows = con.execute(f'SELECT rowid, "{col}" FROM "{t}" WHERE "{col}" LIKE \'%publications/%\'').fetchall()
                con.executemany(f'UPDATE "{t}" SET "{col}"=? WHERE rowid=?', [(new_path(v), r) for r, v in rows])
        con.execute("COMMIT")
        if {"sources", "collections"} <= tables:                 # index.db: its views (and full-text index) again
            from _publish import FTS_DDL, FTS_TRIGGERS, POST
            for stmt in re.findall(r"CREATE VIEW .*?;\n", POST, re.S):
                con.execute(stmt.replace("CREATE VIEW", "CREATE VIEW IF NOT EXISTS", 1))
            if fts:
                _log(f"{path.name}: rebuilding the full-text index ...")
                con.executescript(FTS_DDL + FTS_TRIGGERS)
        _log(f"{path.name}: upgraded")
        return True
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def _move(old, new):
    if old.exists() and not new.exists():
        old.rename(new)
        _log(f"moved {old.name} -> {new}")


def upgrade_project(root):
    """Upgrade a project folder made before the rename (see the module docstring); a no-op once upgraded."""
    root = Path(root)
    pub, old_pub = root / "sources", root / "publications"
    if old_pub.is_dir() and pub.exists() and any(old_pub.iterdir()):
        sys.exit(f"ERROR: {root} has both publications/ (the folder's earlier name) and sources/: move what "
                 "publications/ holds into sources/ by hand, then run again")
    _move(old_pub, pub)
    if not pub.is_dir():
        return
    for suffix in ("", "-wal", "-shm"):
        _move(pub / f"papers.db{suffix}", pub / f"index.db{suffix}")
    for d in sorted(p for p in pub.iterdir() if p.is_dir()):
        _move(d / "papers", d / "files")
        for m in d.glob("corpora/*/sources.json"):                  # frozen corpora: their pdf / si paths
            text = m.read_text(encoding="utf-8")
            if '/papers/' in text or '"paper_id"' in text:
                data = json.loads(text)
                for s in data.get("sources") or []:
                    if isinstance(s.get("pdf"), str):
                        s["pdf"] = s["pdf"].replace("/papers/", "/files/")
                    if isinstance(s.get("si"), list):
                        s["si"] = [x.replace("/papers/", "/files/") if isinstance(x, str) else x for x in s["si"]]
                    if "paper_id" in s:
                        s["source_id"] = s.pop("paper_id")
                m.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
                _log(f"rewrote the paths of {m.relative_to(root)}")
    for db in (pub / "index.db", root / ".scripts" / "ledger.sqlite", pub / "vectors.db"):
        upgrade_db(db)
