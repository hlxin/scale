"""Saved filters in sources/index.db: define one, see its sources, refresh it, or export it as its own database.

  python3 -I filters.py list
  python3 -I filters.py define --name co2-reduction-electricity --file co2-reduction-electricity.filter.json
  python3 -I filters.py show --name co2-reduction-electricity            # sources per label and level
  python3 -I filters.py refresh [--name co2-reduction-electricity]       # re-run now (syncs re-run them anyway)
  python3 -I filters.py export --name co2-reduction-electricity --out sources/exports/co2.db [--public]

A filter's definition (JSON; the format is in _filters.py) is stored in the database with its sources
(`filter_members`), so whoever receives index.db has it too. Every sync that adds or removes sources or changes their
text, topics or retraction re-runs every saved filter. `export` writes a database of the filter's sources with the same
tables as index.db (sources, authors, topics, identifiers, SI, the full-text index) and the filter's selection table;
with --public only OA and OA+ND sources keep their abstract (the others' licences do not allow redistribution).
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import Project, add_project_arg, die, log, now_iso  # noqa: E402
from _filters import define, refresh  # noqa: E402
from _publish import DDL, FTS_DDL, FTS_TRIGGERS, POST, STATE_DDL, _fts_ok, has_state  # noqa: E402

COPY = ("source_authors", "source_collections", "source_subjects", "source_databases", "identifiers", "files", "supplements",
        "extractions")


def open_db(proj, write=False):
    if not has_state(proj.db):
        die(f"{proj.rel(proj.db)} is not an evolving database yet: run export.py once (it builds it)")
    con = sqlite3.connect(str(proj.db) if write else f"file:{proj.db}?mode=ro", uri=not write, timeout=300)
    if write:
        con.executescript(STATE_DDL)
    return con


def export_subset(proj, name, out, public=False):
    src = open_db(proj)
    row = src.execute("SELECT definition, refreshed_at, members, description FROM filters WHERE name=?", (name,)).fetchone()
    if not row:
        die(f"no saved filter named {name!r} (filters.py list)")
    definition = json.loads(row[0])
    spec = definition.get("export") or {}
    table, label_col = spec.get("table") or "selection", spec.get("label_column") or "label"
    src.close()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(str(tmp))
    con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;" + DDL)
    con.execute("ATTACH DATABASE ? AS src", (str(proj.db),))
    con.execute(f"CREATE TABLE {table} (source_id INTEGER, {label_col} TEXT, level TEXT, PRIMARY KEY (source_id, {label_col}))")
    con.execute(f"INSERT INTO {table} SELECT source_id, label, level FROM src.filter_members WHERE filter=?", (name,))
    con.execute(f"CREATE TEMP TABLE ids AS SELECT DISTINCT source_id AS id FROM {table}")
    have = {r[1] for r in con.execute("PRAGMA src.table_info(sources)")}
    cols = ", ".join(r[1] for r in con.execute("PRAGMA main.table_info(sources)") if r[1] in have)
    con.execute(f"INSERT INTO sources ({cols}) SELECT {cols} FROM src.sources WHERE id IN (SELECT id FROM ids)")
    for t in COPY:
        con.execute(f"INSERT INTO {t} SELECT * FROM src.{t} WHERE source_id IN (SELECT id FROM ids)")
    con.execute("INSERT INTO authors SELECT * FROM src.authors WHERE id IN (SELECT DISTINCT author_id FROM source_authors)")
    for t in ("subjects", "databases", "collections"):
        con.execute(f"INSERT INTO {t} SELECT * FROM src.{t}")
    about = dict(con.execute("SELECT name, value FROM src.about").fetchall())
    if public:
        con.execute("UPDATE sources SET abstract=NULL WHERE COALESCE(access_type, '') NOT IN ('OA', 'OA+ND')")
    counts = {f"{lab}:{lev}": n for lab, lev, n in con.execute(
        f"SELECT {label_col}, level, COUNT(*) FROM {table} GROUP BY 1, 2 ORDER BY 1, 2")}
    n = con.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    about = {k: v for k, v in about.items() if k.startswith(("column:", "vocabulary", "examples"))}
    about.update({"subset": name, "subset_definition": json.dumps(definition, ensure_ascii=False),
                  "subset_description": row[3] or definition.get("description") or "",
                  "subset_counts": json.dumps({"sources": n, **counts}), "subset_built_at": now_iso(),
                  "subset_source_updated_at": dict(con.execute("SELECT name, value FROM src.about").fetchall()).get(
                      "updated_at", ""),
                  "subset_abstracts": "only for OA and OA+ND sources (their licences allow redistribution)" if public
                  else "every abstract of the source database", "sources": str(n)})
    con.executemany("INSERT INTO about VALUES (?,?)", sorted(about.items()))
    con.commit()
    con.execute("DETACH DATABASE src")
    con.executescript(POST)
    if _fts_ok(con):
        con.executescript(FTS_DDL + FTS_TRIGGERS)
    con.commit()
    con.execute("VACUUM")
    con.close()
    os.replace(tmp, out)
    return {"export": proj.rel(out), "sources": n, "counts": counts, "public": public, "table": table}


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("cmd", choices=["list", "define", "show", "refresh", "export"])
    ap.add_argument("--name")
    ap.add_argument("--file", help="the filter's definition (JSON) for define")
    ap.add_argument("--description")
    ap.add_argument("--out", help="export: the database file to write")
    ap.add_argument("--public", action="store_true", help="export: abstracts only for OA and OA+ND sources")
    a = ap.parse_args()
    proj = Project(a.project)
    if a.cmd == "list":
        con = open_db(proj)
        rows = [dict(zip(("name", "description", "members", "refreshed_at", "updated_at"), r)) for r in con.execute(
            "SELECT name, description, members, refreshed_at, updated_at FROM filters ORDER BY name")]
        print(json.dumps({"filters": rows}, ensure_ascii=False))
    elif a.cmd == "define":
        if not (a.name and a.file):
            die("define needs --name and --file")
        definition = json.loads(Path(a.file).read_text(encoding="utf-8"))
        if not isinstance(definition.get("groups"), dict) or not definition["groups"]:
            die("a definition needs groups: {label: [rule, ...]} (see _filters.py)")
        con = open_db(proj, write=True)
        with con:
            define(con, a.name, definition, a.description)
        res = refresh(con, [a.name])
        con.close()
        print(json.dumps({"defined": a.name, "members": res.get(a.name)}))
    elif a.cmd == "show":
        con = open_db(proj)
        f = con.execute("SELECT description, members, refreshed_at FROM filters WHERE name=?", (a.name,)).fetchone()
        if not f:
            die(f"no saved filter named {a.name!r}")
        by = {f"{lab}:{lev}": n for lab, lev, n in con.execute(
            "SELECT label, level, COUNT(*) FROM filter_members WHERE filter=? GROUP BY 1, 2 ORDER BY 1, 2", (a.name,))}
        print(json.dumps({"name": a.name, "description": f[0], "sources": f[1], "refreshed_at": f[2], "counts": by},
                         ensure_ascii=False))
    elif a.cmd == "refresh":
        con = open_db(proj, write=True)
        res = refresh(con, [a.name] if a.name else None)
        con.close()
        print(json.dumps({"refreshed": res}))
    elif a.cmd == "export":
        if not (a.name and a.out):
            die("export needs --name and --out")
        log(f"exporting filter {a.name} ...")
        print(json.dumps(export_subset(proj, a.name, a.out, a.public)))


if __name__ == "__main__":
    main()
