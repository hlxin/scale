"""Narrowed download runs leave the rest alone: download_open.py --access / --ids try only what they name, and a source
outside them keeps the status it has (an open-access-only run never takes sources out of the EZproxy runner's queue);
download_paywalled.py --access works only the queue of those access types, and --dry-run counts that queue per
publisher without contacting anything. No network: the sources tried have no copy to fetch.

    python -m pytest tests          (from the skill folder; needs index-sources beside it)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
INDEX = HERE.parents[1] / "index-sources" / "scripts"
sys.path.insert(0, str(INDEX))

SOURCES = [  # id, doi, access, dl_status
    (1, None, "OA", None),                                  # no copy anywhere: tried, fails
    (2, "10.1021/acs.2", "Paywalled", "queued_paywalled"),  # waiting for the EZproxy runner
    (3, None, "Free-to-read", None),                        # never tried yet
    (4, None, "OA", None),                                  # not in --ids
    (5, "10.1002/w.5", "OA", "queued_paywalled"),           # an open copy only on a bot-walled site
]


@pytest.fixture()
def project(tmp_path):
    from _common import Project
    from _ledger import Ledger
    proj = Project(tmp_path / "project")
    led = Ledger(proj)
    for pid, doi, acc, dls in SOURCES:
        led.x("INSERT INTO sources (id, key, doi, title, year, doc_type, access_type, dl_status) VALUES (?,?,?,?,?,?,?,?)",
              (pid, doi or f"nodoi:{pid}", doi, f"Source {pid}", 2024, "article", acc, dls))
        led.set_topic(pid, "t", in_scope=1, relevance=4)
    (proj.scr / "t").mkdir(parents=True, exist_ok=True)
    (proj.scr / "t" / "config.json").write_text(json.dumps({"topic": "Test topic", "slug": "t",
                                                            "download": {"access_types": ["OA", "Free-to-read"]}}))
    return proj


def run(proj, script, *args, code=0):
    env = {**os.environ, "SCALE_SOURCES_HOME": str(proj.root.parent / "home")}    # no EZproxy set up, no real limiter
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / script), "--project", str(proj.root), *map(str, args)],
                       capture_output=True, text=True, timeout=300, env=env)
    assert r.returncode == code, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}


def status(proj):
    from _ledger import Ledger
    led = Ledger(proj)
    return {pid: led.get(pid)["dl_status"] for pid, *_ in SOURCES}


def test_a_narrowed_open_run_leaves_the_rest_as_it_was(project, tmp_path):
    ids = tmp_path / "ids.txt"
    ids.write_text("1\n2\n3\n")
    out = run(project, "download_open.py", "--topic", "t", "--access", "OA", "--ids", ids)
    assert out["tried"] == 1 and out["outcomes"] == {"failed": 1}
    # 2 stays queued for the EZproxy runner; 3, never tried, is marked as of a type not selected; 4 and 5: not asked
    assert status(project) == {1: "failed", 2: "queued_paywalled", 3: "not_selected", 4: None, 5: "queued_paywalled"}
    out = run(project, "download_open.py", "--topic", "t")      # the topic's own selection decides for every source
    assert out["tried"] == 2                                     # 3 and 4; 1 failed before, 5 stays queued
    assert status(project) == {1: "failed", 2: "not_selected", 3: "failed", 4: "failed", 5: "queued_paywalled"}
    run(project, "download_open.py", "--topic", "t", "--access", "OA,Open", code=2)


def test_the_ezproxy_queue_of_some_access_types_is_counted_without_contacting_anything(project):
    out = run(project, "download_paywalled.py", "--dry-run")
    assert (out["queue"], out["pdfs"], out["access"]) == ({"acs": 1, "wiley": 1}, 2, "all")
    out = run(project, "download_paywalled.py", "--dry-run", "--access", "OA,OA+ND")
    assert (out["queue"], out["pdfs"], out["access"]) == ({"wiley": 1}, 1, ["OA", "OA+ND"])
    out = run(project, "download_paywalled.py", "--dry-run", "--skip-publishers", "wiley")
    assert out["queue"] == {"acs": 1} and out["skipped_publishers"] == ["wiley"]
    assert "unknown access type" in run(project, "download_paywalled.py", "--access", "Open", code=2)["error"]
    assert not (project.root.parent / "home" / "ezproxy").exists()        # nothing machine-wide was touched
