"""freeze_corpus.py on a small project: every paper of the topic gets one status with its reason, the counts add up,
the rule leaves papers out with the rule's reason, the paths resolve from the manifest, and a corpus is frozen once.

    python -m pytest tests          (from the skill folder; standard library and pytest only)
SCALE_CMD, when set (e.g. "scale" or "uv run scale"), also runs `scale corpus check` on the manifest.
"""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

PAPERS = [  # id, doi, doc_type, year, access, downloaded, dl_status, erratum, retracted, in_scope, relevance note
    (1, "10.1/ABC", "article", 2024, "OA", 1, None, 0, 0, 1, None),
    (2, "10.1/q", "article", 2024, "Paywalled", 0, "queued_paywalled", 0, 0, 1, None),
    (3, "10.1/off", "article", 2024, "OA", 0, None, 0, 0, 0, "off topic"),
    (4, "10.1/err", "article", 2024, "OA", 0, None, 1, 0, 1, None),
    (5, "10.1/ret", "article", 2024, "OA", 1, None, 0, 1, 1, None),
    (6, "10.1/data", "dataset", 2024, "OA", 0, None, 0, 0, 1, None),
    (7, "10.1/old", "article", 2010, "OA", 1, None, 0, 0, 1, None),
    (8, None, "article", 2024, "OA", 0, None, 0, 0, None, None),
]


@pytest.fixture()
def project(tmp_path):
    from _common import Project
    from _ledger import Ledger
    proj = Project(tmp_path)
    led = Ledger(proj)
    for pid, doi, dt, year, acc, dl, dls, err, ret, scope, note in PAPERS:
        led.x("INSERT INTO papers(id, key, doi, title, year, doc_type, access_type, license, downloaded, dl_status, "
              "is_erratum, retracted, version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (pid, doi or f"nodoi:{pid}", doi.lower() if doi else None, f"Paper {pid}", year, dt, acc, "cc-by", dl,
               dls, err, ret, "publishedVersion"))
        path = f"publications/t/papers/{acc}/{pid}.pdf" if dl else None
        si = [f"publications/t/papers/SI/{acc}/{pid}_SI.pdf"] if pid == 1 else []
        for p in [path, *si]:
            if p:
                (tmp_path / p).parent.mkdir(parents=True, exist_ok=True)
                (tmp_path / p).write_bytes(b"%PDF-1.4\n")
        led.x("INSERT INTO paper_topics(paper_id, topic, in_scope, relevance_note, path, si_paths) VALUES (?,?,?,?,?,?)",
              (pid, "t", scope, note, path, json.dumps(si)))
    td = tmp_path / ".scripts" / "t"
    td.mkdir(parents=True, exist_ok=True)
    (td / "config.json").write_text(json.dumps({"topic": "Test topic", "slug": "t"}))
    return tmp_path


def freeze(project, *args, ok=True):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "freeze_corpus.py"), "--project", str(project),
                        "--topic", "t", *args], capture_output=True, text=True)
    assert (r.returncode == 0) == ok, r.stderr[-600:]
    return json.loads(r.stdout) if ok else r.stderr


def test_every_paper_has_one_status_and_the_counts_add_up(project):
    res = freeze(project, "--name", "all")
    m = json.loads((project / res["manifest"]).read_text())
    by_id = {s["paper_id"]: s for s in m["sources"]}
    assert {i: by_id[i]["status"] for i in by_id} == {1: "in_scope", 2: "not_retrieved", 3: "off_scope", 4: "excluded",
                                                      5: "retracted", 6: "excluded", 7: "in_scope", 8: "not_screened"}
    assert by_id[2]["status_reason"] == "queued for the library EZproxy" and by_id[3]["status_reason"] == "off topic"
    assert "erratum" in by_id[4]["status_reason"] and "dataset" in by_id[6]["status_reason"]
    assert m["counts"] == {"excluded": 2, "in_scope": 2, "not_retrieved": 1, "not_screened": 1, "off_scope": 1,
                           "retracted": 1}
    assert sum(m["counts"].values()) == len(m["sources"]) == 8 and m["included_status"] == "in_scope"
    one = by_id[1]
    assert one["slug"] == "10.1-abc" and by_id[8]["slug"] == "8"          # as scale source start names sources
    base = (project / res["manifest"]).parent
    assert (base / one["pdf"]).resolve() == (project / "publications/t/papers/OA/1.pdf").resolve()
    assert [(base / p).resolve().name for p in one["si"]] == ["1_SI.pdf"]
    assert one["text_version"] == "version_of_record"


def test_the_rule_leaves_papers_out_with_its_reason(project):
    m = json.loads((project / freeze(project, "--name", "recent", "--years", "2015-2026")["manifest"]).read_text())
    old = next(s for s in m["sources"] if s["paper_id"] == 7)
    assert old["status"] == "excluded" and old["status_reason"] == "left out by the rule: published 2010"
    assert m["counts"]["in_scope"] == 1 and "published 2015-2026" in m["cutoff"]["rule"]


def test_a_corpus_is_frozen_once(project):
    freeze(project, "--name", "once")
    assert "frozen once" in freeze(project, "--name", "once", ok=False)


def test_a_rule_that_includes_nothing_is_refused(project):
    assert "no source is included" in freeze(project, "--name", "none", "--years", "1900-1901", ok=False)


@pytest.mark.skipif(not os.environ.get("SCALE_CMD"), reason="set SCALE_CMD to run SCALE's own corpus check")
def test_scale_accepts_the_manifest(project):
    res = freeze(project, "--name", "scale")
    r = subprocess.run([*shlex.split(os.environ["SCALE_CMD"]), "corpus", "check", str(project / res["manifest"])],
                       capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout)["ok"], r.stdout[-600:]
