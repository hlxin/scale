"""Upgrade a project, or one database file, made before the sources were so named (papers.db, papers, paper_id ...).

Every script upgrades its own project when it opens it (see _upgrade.py); run this for a database that came alone —
a copy someone sent, or a shared catalog that is read elsewhere (consult.py) — or to upgrade a project on purpose.

  python3 -I upgrade.py [--project <folder>]          # the project (default: the current folder)
  python3 -I upgrade.py --db <file>                   # one index.db / papers.db; a papers.db is renamed index.db

Renaming tables and columns rewrites only the schema: seconds even for millions of rows; the full-text index is
rebuilt (minutes on a whole-field catalog). Run it where the file can be written, with nothing else open on it.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _upgrade import upgrade_db, upgrade_project  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=None, help="project folder (default: the current folder)")
    ap.add_argument("--db", default=None, help="one database file instead of a project")
    a = ap.parse_args()
    if a.db:
        db = Path(a.db)
        if not db.is_file():
            sys.exit(f"ERROR: no database at {db}")
        done = upgrade_db(db)
        if db.name == "papers.db" and not (db.parent / "index.db").exists():
            db = db.rename(db.parent / "index.db")
        print(json.dumps({"database": str(db), "upgraded": done}))
        return
    root = Path(a.project or ".").resolve()
    old = (root / "publications").is_dir()
    upgrade_project(root)
    print(json.dumps({"project": str(root), "upgraded": old}))


if __name__ == "__main__":
    main()
