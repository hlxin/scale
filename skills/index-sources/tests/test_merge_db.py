"""merge_db.py: two people update separate copies of the same index.db; merging one into the other keeps everything
both did — sources either found (the same source found by both kept once, IDs that collide renumbered), access checks,
screening, downloads, retractions, merges of duplicates, curation results, search windows and history — and a second
merge changes nothing.

    python -m pytest tests          (from the skill folder; standard library and pytest only)
"""
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))


def add_source(led, pid, title, doi, access="Paywalled"):
    led.x("INSERT INTO sources (id, key, doi, title, authors, authors_detail, year, journal, doc_type, abstract, "
          "access_type, databases) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
          (pid, doi, doi, title, json.dumps(["A. Author"]), json.dumps([{"name": "A. Author"}]), 2025, "J. Test",
           "article", "An abstract long enough to count as one, about catalysts and how well they work in tests.",
           access, json.dumps(["openalex"])))
    led.set_topic(pid, "t", in_scope=1, relevance=4)
    led.add_dois(pid, [doi])


def download(proj, led, pid):
    rel = f"sources/t/files/OA/{pid}.pdf"
    (proj.root / rel).parent.mkdir(parents=True, exist_ok=True)
    (proj.root / rel).write_bytes(b"%PDF-1.4 source " + str(pid).encode())
    led.set(pid, downloaded=1, version="publishedVersion", download_url=f"https://example.org/{pid}.pdf",
            download_source="openalex", sha1=f"sha-{pid}", access_type="OA", license="cc-by", access_basis="pdf",
            license_evidence="pdf_article_license_statement", last_checked="2026-10-26")
    led.set_topic(pid, "t", path=rel)


def copy_of(base_db, folder):
    from _common import Project
    from _ledger import Ledger
    (folder / "sources").mkdir(parents=True)
    shutil.copy(base_db, folder / "sources" / "index.db")
    proj = Project(folder)
    return proj, Ledger(proj)                       # rebuilt from the copy of the database


@pytest.fixture()
def two_copies(tmp_path):
    from _common import Project
    from _ledger import Ledger
    base = Project(tmp_path / "base")
    (base.scr / "t").mkdir(parents=True, exist_ok=True)
    (base.scr / "t" / "config.json").write_text(json.dumps({"topic": "Test topic", "slug": "t"}))
    (base.scr / "t" / "queries.json").write_text(json.dumps({"openalex": {"q1": "title.search:copper"}}))
    (base.scr / "t" / "state.json").write_text(json.dumps({"search_runs": {"full": {"finished_at": "2026-10-14T00:00:00Z"}}}))
    led = Ledger(base)
    for i, title in enumerate(["Copper oxide reduces CO2", "Nickel phosphide for hydrogen", "Cobalt oxide for oxygen",
                               "Silver for CO", "Tin for formate", "Copper oxide reduces CO2 (preprint)"], 1):
        add_source(led, i, title, f"10.1/{i}")
    led.export()

    pa, la = copy_of(base.db, tmp_path / "a")
    add_source(la, 7, "Ruthenium single atoms for ammonia", "10.1/shared")         # found by both copies
    add_source(la, 8, "Only copy A found this", "10.1/a-only")
    la.set(2, access_type="OA", license="cc-by", last_checked="2026-11-01")        # A checked last
    la.set_topic(3, "t", relevance=2, relevance_note="off topic", relevance_method="claude", in_scope=0)
    la.export()

    pb, lb = copy_of(base.db, tmp_path / "b")
    add_source(lb, 7, "Ruthenium single atoms for ammonia", "10.1/shared")
    add_source(lb, 8, "Only copy B found this", "10.1/b-only")                      # the same ID as A's other source
    lb.set(2, access_type="Free-to-read", last_checked="2026-10-25")
    download(pb, lb, 4)
    download(pb, lb, 8)
    lb.set(5, retracted=1)
    for d in lb.aliases(6):                                                    # B merged the preprint into source 1
        lb.x("UPDATE dois SET source_id=1 WHERE doi=?", (d,))
    for t in ("source_subjects", "extractions", "source_topics"):
        lb.x(f"DELETE FROM {t} WHERE source_id=6")
    lb.x("DELETE FROM sources WHERE id=6")
    lb.x("INSERT INTO extractions VALUES (1, 't', 'run-b', 'extracted', '0.5.0', 9, 12, '2026-10-27', 'from b')")
    st = json.loads((pb.scr / "t" / "state.json").read_text())
    st["search_runs"]["since-2026-10-20"] = {"finished_at": "2026-10-21T00:00:00Z"}
    (pb.scr / "t" / "state.json").write_text(json.dumps(st))
    (pb.scr / "t" / "queries.json").write_text(json.dumps({"openalex": {"q1": "title.search:copper",
                                                                        "q2": "title.search:ruthenium"}}))
    lb.export()
    return pa, pb


def merge(into, other_db, *extra):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "merge_db.py"), "--project", str(into.root),
                        "--from", str(other_db), *map(str, extra)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def state(proj):
    from _ledger import Ledger
    led = Ledger(proj)
    by_doi = {r["doi"]: dict(r) for r in led.q("SELECT * FROM sources")}
    return led, by_doi


def test_a_merge_keeps_what_both_copies_did(two_copies):
    pa, pb = two_copies
    res = merge(pa, pb.db)
    assert res["added"] == 1 and res["merged_here"] == 1
    led, p = state(pa)
    assert sorted(p) == ["10.1/1", "10.1/2", "10.1/3", "10.1/4", "10.1/5", "10.1/a-only", "10.1/b-only", "10.1/shared"]
    assert p["10.1/a-only"]["id"] == 8 and p["10.1/b-only"]["id"] == 9          # B's 8 renumbered, A's kept
    assert led.q("SELECT source_id FROM dois WHERE doi='10.1/6'")[0][0] == 1      # B's merge of the preprint, here too
    assert p["10.1/2"]["access_type"] == "OA"                                    # A checked it more recently
    assert p["10.1/4"]["access_type"] == "OA" and p["10.1/4"]["access_basis"] == "pdf"   # B read it from the PDF
    assert not p["10.1/4"]["downloaded"]                                         # but the file is in B's folder
    assert "https://example.org/4.pdf" in {v.get("url") for v in json.loads(p["10.1/4"]["versions"])}
    assert p["10.1/5"]["retracted"] == 1
    from test_evolving_db import counts_match
    assert counts_match(pa)
    t3 = led.q("SELECT relevance_method, in_scope FROM source_topics WHERE source_id=3 AND topic='t'")[0]
    assert tuple(t3) == ("claude", 0)                                            # A's better screening decision
    assert led.q("SELECT note FROM extractions WHERE source_id=1 AND kg='run-b'")[0][0] == "from b"
    st = json.loads((pa.scr / "t" / "state.json").read_text())
    assert set(st["search_runs"]) == {"full", "since-2026-10-20"}                # Update knows B's window
    assert "q2" in json.loads((pa.scr / "t" / "queries.json").read_text())["openalex"]
    con = sqlite3.connect(str(pa.db))
    runs = con.execute("SELECT step, note FROM runs ORDER BY id").fetchall()
    assert any("[from " in (n or "") for _, n in runs)                       # B's own runs, imported
    merge_run = con.execute("SELECT id FROM runs WHERE step='merge_db'").fetchone()[0]
    ch = {(r[0], r[1], r[2]) for r in con.execute("SELECT source_id, change, field FROM changes WHERE run_id=?", (merge_run,))}
    assert (9, "added", None) in ch and (6, "removed", None) in ch and (5, "changed", "is_retracted") in ch
    con.close()


def test_a_second_merge_changes_nothing(two_copies):
    pa, pb = two_copies
    merge(pa, pb.db)
    con = sqlite3.connect(str(pa.db))
    runs, changes = (con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("runs", "changes"))
    con.close()
    res = merge(pa, pb.db)
    assert res.get("added", 0) == 0 and res.get("updated", 0) == 0 and res.get("merged_here", 0) == 0
    con = sqlite3.connect(str(pa.db))
    assert (con.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
            con.execute("SELECT COUNT(*) FROM changes").fetchone()[0]) == (runs, changes)
    con.close()


def test_with_files_the_other_copys_downloads_come_in_under_this_copys_ids(two_copies):
    pa, pb = two_copies
    res = merge(pa, pb.db, "--files", pb.root)
    assert res["files_imported"] == 2
    led, p = state(pa)
    assert p["10.1/4"]["downloaded"] == 1 and p["10.1/b-only"]["downloaded"] == 1
    path = led.q("SELECT path FROM source_topics WHERE source_id=9 AND topic='t'")[0][0]
    assert path == "sources/t/files/OA/9.pdf" and (pa.root / path).read_bytes().endswith(b"source 8")


def test_both_directions_give_the_same_sources(two_copies, tmp_path):
    pa, pb = two_copies
    pa2 = tmp_path / "a2"
    shutil.copytree(pa.root, pa2)
    from _common import Project
    merge(pa, pb.db)                                          # B into A
    merge(Project(pb.root), Project(pa2).db)                  # A (before) into B
    _, p_ab = state(pa)
    _, p_ba = state(Project(pb.root))
    assert set(p_ab) == set(p_ba)
    for doi in p_ab:
        for f in ("title", "access_type", "retracted", "journal"):
            assert p_ab[doi][f] == p_ba[doi][f], (doi, f)


def test_a_dry_run_writes_nothing(two_copies):
    pa, pb = two_copies
    before = pa.db.read_bytes()
    res = merge(pa, pb.db, "--dry-run")
    assert res["dry_run"] is True and res["added"] == 1
    assert pa.db.read_bytes() == before


def test_a_copy_of_an_older_version_merges_too(two_copies):
    pa, pb = two_copies
    con = sqlite3.connect(str(pb.db))
    con.execute("ALTER TABLE sources DROP COLUMN preprint_url")          # B's index.db as paper-acquisition 3.6 left it
    con.commit()
    con.close()
    res = merge(pa, pb.db)
    assert res["added"] == 1 and res["merged_here"] == 1
    again = merge(pa, pb.db)
    assert again.get("added", 0) == 0 and again.get("updated", 0) == 0 and again.get("unchanged", 0) > 0
