"""fetch-corpus on a small project: a frozen corpus is fetched and settled — each included source gets its file or the
reason it has none, a later fetch includes it again, and --corpus keeps a download step to the corpus's sources.
No network: the downloads are simulated, and the download step is run where it has nothing to fetch.

    python -m pytest tests          (from the skill folder; needs index-sources beside it)
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
INDEX = HERE.parents[1] / "index-sources" / "scripts"
sys.path.insert(0, str(INDEX))

SOURCES = [  # id, doi, year, access, downloaded, dl_status, in_scope
    (1, "10.1/one", 2024, "OA", 1, None, 1),
    (2, "10.1/two", 2024, "Paywalled", 0, "queued_paywalled", 1),
    (3, "10.1/three", 2024, "Paywalled", 0, None, 1),
    (4, "10.1/old", 2010, "Paywalled", 0, None, 1),           # left out of the corpus by its rule (--years)
]


@pytest.fixture()
def project(tmp_path):
    from _common import Project
    from _ledger import Ledger
    proj = Project(tmp_path)
    led = Ledger(proj)
    for pid, doi, year, acc, dl, dls, scope in SOURCES:
        led.x("INSERT INTO sources(id, key, doi, title, year, doc_type, access_type, downloaded, dl_status, version) "
              "VALUES (?,?,?,?,?,?,?,?,?,?)", (pid, doi, doi, f"Source {pid}", year, "article", acc, dl, dls,
                                               "publishedVersion"))
        path = f"sources/t/files/{acc}/{pid}.pdf" if dl else None
        if path:
            (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / path).write_bytes(b"%PDF-1.4\n")
        led.x("INSERT INTO source_topics(source_id, topic, in_scope, relevance, path) VALUES (?,?,?,?,?)",
              (pid, "t", scope, 5, path))
    td = tmp_path / ".scripts" / "t"
    td.mkdir(parents=True, exist_ok=True)
    (td / "config.json").write_text(json.dumps({"topic": "Test topic", "slug": "t",
                                                "download": {"access_types": ["OA", "Paywalled"]}}))
    return tmp_path


def run(folder, script, *args):
    r = subprocess.run([sys.executable, "-I", str(folder / script), *map(str, args)], capture_output=True, text=True,
                       timeout=300)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}


def frozen(project):
    res = run(INDEX, "freeze_corpus.py", "--project", project, "--topic", "t", "--name", "c", "--years", "2015-2026")
    return project / res["manifest"]


def test_a_settled_corpus_gives_each_source_its_file_or_the_reason(project):
    manifest = frozen(project)
    res = run(SCRIPTS, "settle_corpus.py", "--project", project, "--corpus", manifest)
    m = json.loads(manifest.read_text())
    by_id = {s["source_id"]: s for s in m["sources"]}
    assert by_id[1]["status"] == "in_scope" and (manifest.parent / by_id[1]["pdf"]).resolve().name == "1.pdf"
    assert (by_id[2]["status"], by_id[2]["status_reason"]) == ("not_retrieved", "queued for the library EZproxy")
    assert (by_id[3]["status"], by_id[3]["status_reason"]) == ("not_retrieved", "not fetched yet")
    assert by_id[4]["status"] == "excluded"                                   # the corpus's rule stays as frozen
    assert m["counts"] == {"excluded": 1, "in_scope": 1, "not_retrieved": 2} and m["fetched_at"]
    assert res["with_file"] == 1 and not res["problems"]


def test_a_later_fetch_includes_the_source_again(project):
    from _common import Project
    from _ledger import Ledger
    manifest = frozen(project)
    run(SCRIPTS, "settle_corpus.py", "--project", project, "--corpus", manifest)
    led = Ledger(Project(project))                     # the library's EZproxy fetches source 2 later
    rel = "sources/t/files/Paywalled/2.pdf"
    (project / rel).parent.mkdir(parents=True, exist_ok=True)
    (project / rel).write_bytes(b"%PDF-1.4\n")
    led.set(2, downloaded=1, dl_status=None)
    led.set_topic(2, "t", path=rel)
    run(SCRIPTS, "settle_corpus.py", "--project", project, "--corpus", manifest)
    by_id = {s["source_id"]: s for s in json.loads(manifest.read_text())["sources"]}
    assert by_id[2]["status"] == "in_scope" and "status_reason" not in by_id[2] and by_id[2]["pdf"].endswith("2.pdf")


def test_a_corpus_keeps_the_download_step_to_its_sources(project):
    """Paywalled sources without the library's access are marked as having no route — only the corpus's."""
    from _common import Project
    from _ledger import Ledger
    manifest = frozen(project)
    run(SCRIPTS, "download_open.py", "--project", project, "--corpus", manifest)
    led = Ledger(Project(project))
    status = {r[0]: r[1] for r in led.q("SELECT id, dl_status FROM sources")}
    assert status[3] == "no_route" and status[4] is None                     # 4 is not in the corpus: untouched


def test_a_manifest_frozen_before_the_rename_is_read(project):
    sys.path.insert(0, str(SCRIPTS))
    from _corpus import included_ids
    old = {"topic": "t", "sources": [{"slug": "a", "status": "in_scope", "paper_id": 7},
                                     {"slug": "b", "status": "off_scope", "paper_id": 8}]}
    assert included_ids(old) == {7}
