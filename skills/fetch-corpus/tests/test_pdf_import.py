"""PDFs from elsewhere, checked like downloads: import_pdfs.py copies in the PDFs another project already downloaded
(made by index-sources, or by paper-acquisition before the rename — read as it is, never upgraded), and
accept_pdf.py files a PDF the same-source check rejected once someone has looked at it. No network.

    python -m pytest tests          (from the skill folder; needs index-sources beside it; PyMuPDF and pytest)
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
INDEX = HERE.parents[1] / "index-sources" / "scripts"
sys.path.insert(0, str(INDEX))
sys.path.insert(0, str(INDEX.parent / "tests"))

fitz = pytest.importorskip("fitz")
from test_same_source import make_pdf  # noqa: E402

TITLE = "Prospects for the application of methanation technologies for synthetic renewable methane"
LICENSED = "\nThis article is licensed under CC BY 4.0, https://creativecommons.org/licenses/by/4.0/"


@pytest.fixture()
def project(tmp_path):
    from _common import Project
    from _ledger import Ledger
    proj = Project(tmp_path / "project")
    (proj.scr / "t").mkdir(parents=True, exist_ok=True)
    (proj.scr / "t" / "config.json").write_text(json.dumps({"topic": "Test topic", "slug": "t"}))
    led = Ledger(proj)
    for pid, doi in ((3, "10.1000/scan.3"), (4, "10.1000/old.4"), (5, "10.1000/new.5")):
        led.x("INSERT INTO sources (id, key, doi, title, authors, year, journal, doc_type, access_type, license) "
              "VALUES (?,?,?,?,?,?,?,?,?,?)", (pid, doi, doi, TITLE, json.dumps(["A. Author"]), 2024, "J. Test",
                                               "article", "OA", "cc-by"))
        led.set_topic(pid, "t", in_scope=1, relevance=4)
        led.add_dois(pid, [doi])
    return proj


def run(script, *args):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True,
                       timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def earlier_project(root):
    """A project as paper-acquisition left it: publications/, a ledger with papers and paper_topics."""
    rel = "publications/x/papers/OA/8.pdf"
    (root / rel).parent.mkdir(parents=True)
    make_pdf(root / rel, f"{TITLE}\nDOI 10.1000/old.4{LICENSED}")
    (root / ".scripts").mkdir()
    con = sqlite3.connect(str(root / ".scripts" / "ledger.sqlite"))
    con.executescript("CREATE TABLE papers (id INTEGER PRIMARY KEY, doi TEXT, access_type TEXT, version TEXT, "
                      "download_source TEXT, download_url TEXT, downloaded INTEGER);"
                      "CREATE TABLE paper_topics (paper_id INTEGER, topic TEXT, path TEXT);")
    con.execute("INSERT INTO papers VALUES (8, '10.1000/OLD.4', 'OA', 'publishedVersion', 'unpaywall', 'https://x.test/8', 1)")
    con.execute("INSERT INTO paper_topics VALUES (8, 'x', ?)", (rel,))
    con.commit()
    con.close()
    return rel


def test_pdfs_another_project_downloaded_are_copied_in_and_checked(project, tmp_path):
    from _common import Project
    from _ledger import Ledger
    other = Project(tmp_path / "colleague")                 # made by index-sources
    theirs = Ledger(other)
    rel = "sources/x/files/OA/7.pdf"
    (other.root / rel).parent.mkdir(parents=True, exist_ok=True)
    make_pdf(other.root / rel, f"{TITLE}\nDOI 10.1000/new.5{LICENSED}")
    theirs.x("INSERT INTO sources (id, key, doi, title, authors, year, journal, doc_type, access_type, license, downloaded) "
             "VALUES (7, '10.1000/new.5', '10.1000/new.5', ?, '[]', 2024, 'J. Test', 'article', 'OA', 'cc-by', 1)",
             (TITLE,))
    theirs.set_topic(7, "x", in_scope=1, path=rel)
    old = tmp_path / "earlier"                               # made by paper-acquisition, before the rename
    old_rel = earlier_project(old)
    for frm, sid in ((other.root, 5), (old, 4)):
        assert run("import_pdfs.py", "--project", project.root, "--from", frm, "--access", "OA,OA+ND",
                   "--dry-run")["to_import"] == 1
        out = run("import_pdfs.py", "--project", project.root, "--from", frm, "--access", "OA,OA+ND")
        assert out["outcomes"] == {"valid_pdf": 1}, out
        assert Ledger(project).get(sid)["downloaded"] == 1
    assert (other.root / rel).is_file() and (old / old_rel).is_file()               # copied, never moved
    assert not (old / "sources").exists()                                         # the earlier project not upgraded
    con = sqlite3.connect(str(old / ".scripts" / "ledger.sqlite"))
    assert {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} == {"papers",
                                                                                                "paper_topics"}
    con.close()


def test_a_rejected_pdf_is_filed_after_review(project, tmp_path):
    from _download import file_pdf
    from _ledger import Ledger
    led = Ledger(project)
    entry = {"src": "test", "version": "publishedVersion", "access": "OA", "license": "cc-by", "url": "https://x.test/3"}
    out, why = file_pdf(project, led, led.get(3), entry, make_pdf(tmp_path / "scan.pdf", ""), "open")
    assert out == "wrong_paper" and why.startswith("no text layer"), why
    kept = why.split(" kept at ")[1]
    res = run("accept_pdf.py", "--project", project.root, "--id", 3, "--file", kept,
              "--reason", "page 1 shows the title and authors (a scan)")
    assert res["outcome"] == "valid_pdf", res
    assert Ledger(project).get(3)["downloaded"] == 1
    assert (project.scr / "rejected" / "accepted" / Path(kept).name).is_file() and not (project.root / kept).exists()
    attempts = [json.loads(l) for l in (project.logs / "download_attempts.jsonl").read_text().splitlines()]
    assert attempts[-1]["step"] == "accepted_after_review" and attempts[-1]["reason"].startswith("page 1 shows")
