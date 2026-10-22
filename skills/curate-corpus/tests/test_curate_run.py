"""curate_run.py against SCALE's own tools, offline: a corpus of one source (a generated PDF and an SI text file)
goes through prepare, the hand-outs and every state, with the subagents' reports written by the test.

Run from a checkout of hlxin/scale with the package installed (pip install -e ".[pdf]"):
    python -m pytest skills/curate-corpus/tests
SCALE_CMD overrides the scale command (default: this Python's `-m scale.cli --repo <checkout>`).
"""
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "curate_run.py"
REPO = HERE.parents[2]
SCALE = os.environ.get("SCALE_CMD") or f"{shlex.quote(sys.executable)} -m scale.cli --repo {shlex.quote(str(REPO))}"

fitz = pytest.importorskip("fitz")
MODELS = ("--curator", "opus", "--reviewer", "sonnet")                  # asked before every run


def run(*args, ok=True):
    r = subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, args)], capture_output=True, text=True)
    assert (r.returncode == 0) == ok, r.stderr[-800:]
    lines = [json.loads(x) for x in r.stdout.splitlines() if x.strip()]
    return lines[0] if len(lines) == 1 else lines


def write(p, obj):
    time.sleep(1.05)                      # the states compare file times, which have one-second steps on some systems
    Path(p).write_text(json.dumps(obj), encoding="utf-8")


@pytest.fixture()
def corpus(tmp_path):
    pdf = tmp_path / "papers" / "7.pdf"
    pdf.parent.mkdir()
    doc = fitz.open()
    for text in ("Cu foil reduces CO2 to formate at -0.9 V vs RHE.", "The Faradaic efficiency to formate was 61 %."):
        doc.new_page().insert_text((72, 72), text)
    doc.save(str(pdf))
    si = tmp_path / "papers" / "7_SI.txt"
    si.write_text("Table S1. Faradaic efficiency to CO: 12 %.", encoding="utf-8")
    manifest = tmp_path / "corpus" / "sources.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({
        "corpus": "a test corpus", "frozen_at": "2026-10-19", "counts": {"in_scope": 1, "off_scope": 1},
        "included_status": "in_scope",
        "sources": [{"slug": "7", "status": "in_scope", "paper_id": 7, "title": "Formate on Cu", "year": 2025,
                     "pdf": "../papers/7.pdf", "si": ["../papers/7_SI.txt"], "licence": "cc-by"},
                    {"slug": "8", "status": "off_scope", "paper_id": 8, "status_reason": "screened out"}]}),
        encoding="utf-8")
    return manifest


def test_prepare_starts_a_scale_folder_with_the_si_pages(corpus, tmp_path):
    res = run("prepare", "--corpus", corpus, "--run", tmp_path / "run", "--scale", SCALE, *MODELS)
    assert res["picked"] == 1 and res["started"] == 1 and res["schema_version"]
    f = tmp_path / "run" / "sources" / "7"
    assert (f / "source.json").is_file() and (f / "rights.yaml").is_file() and (f / "BRIEF.md").is_file()
    si = json.loads((f / "work" / "si.json").read_text())["files"]
    assert si[0]["file"] == "7_SI.txt" and si[0]["pages"] == "S1"
    texts = next((f / "work" / "texts").glob("*.txt")).read_text()
    assert "[page 1]" in texts and "[page S1]" in texts and "Faradaic efficiency to CO: 12 %" in texts
    again = run("prepare", "--corpus", corpus, "--run", tmp_path / "run", "--scale", SCALE, *MODELS)
    assert again["started"] == 0 and again["already_there"] == 1          # resumable


def test_every_state_from_prepared_to_passed(corpus, tmp_path):
    r = tmp_path / "run"
    run("prepare", "--corpus", corpus, "--run", r, "--scale", SCALE, *MODELS)
    f = r / "sources" / "7"
    assert run("status", "--run", r)["states"] == {"prepared": 1}
    out = run("next", "--run", r, "--role", "curate", "--n", 5)
    assert out["id"] == "7" and Path(out["prompt"]).is_file()
    assert "curate-source" in Path(out["prompt"]).read_text()
    assert run("next", "--run", r, "--role", "curate")["handed_out"] == 0     # leased, not handed out twice
    graph = next(f.glob("*.graph.json"))
    good = graph.read_text()
    doc = json.loads(good)
    doc["nodes"].append({"id": "ex:pub/x/1", "label": "NotALabel", "props": {}})
    graph.write_text(json.dumps(doc))
    write(f / "work" / "curation.json", {"result": "curated", "records": 1, "gaps": 0, "note": "test"})
    assert run("status", "--run", r)["states"] == {"check_failed": 1}
    fix = run("next", "--run", r, "--role", "fix")
    assert "NotALabel" in Path(fix["prompt"]).read_text()                 # the check's error reaches the fixer
    time.sleep(1.05)
    graph.write_text(good)
    write(f / "work" / "curation.json", {"result": "curated", "records": 1, "gaps": 0, "note": "fixed", "attempt": 1})
    assert run("status", "--run", r)["states"] == {"curated": 1}
    run("next", "--run", r, "--role", "review")
    write(f / "work" / "review.json", {"verdict": "needs_fix", "issues": [{"record": "ex:a", "locator": "p. 1",
                                                                          "problem": "unit", "fix": "V vs RHE"}]})
    assert run("status", "--run", r)["states"] == {"needs_fix": 1}
    assert "V vs RHE" in Path(run("next", "--run", r, "--role", "fix")["prompt"]).read_text()
    write(f / "work" / "curation.json", {"result": "curated", "records": 1, "gaps": 0, "note": "again", "attempt": 2})
    assert run("status", "--run", r)["states"] == {"curated": 1}             # a change makes the old reading stale
    write(f / "work" / "review.json", {"verdict": "pass", "issues": []})
    st = run("status", "--run", r, "--apply")
    assert st["states"] == {"passed": 1} and st["applied"] == 1
    line = json.loads((r / "state.jsonl").read_text().splitlines()[-1])
    assert line["result"] == "extracted" and line["id"] == "7"
    assert run("status", "--run", r, "--apply")["applied"] == 0             # recorded once
    asm = run("assemble", "--run", r)                                     # a local graph of the passed documents
    assert asm["added"] == 1 and asm["refused"] == {} and Path(asm["built"]).is_file()
    assert (r / "graph" / "parts" / "header.json").is_file() and (r / "graph" / "rights.yaml").is_file()
    assert run("assemble", "--run", r)["already_there"] == 1                # the same source is never added twice


def test_a_rejected_source_is_settled(corpus, tmp_path):
    r = tmp_path / "run"
    run("prepare", "--corpus", corpus, "--run", r, "--scale", SCALE, *MODELS)
    f = r / "sources" / "7"
    write(f / "work" / "curation.json", {"result": "no_data", "records": 0, "gaps": 0, "note": "test"})
    write(f / "work" / "review.json", {"verdict": "reject", "issues": [], "note": "wrong paper"})
    assert run("status", "--run", r)["states"] == {"rejected": 1}


def test_a_corpus_that_fails_the_check_is_refused(corpus, tmp_path):
    m = json.loads(corpus.read_text())
    m["counts"] = {"in_scope": 5}
    corpus.write_text(json.dumps(m))
    run("prepare", "--corpus", corpus, "--run", tmp_path / "run", "--scale", SCALE, *MODELS, ok=False)


def test_gap_reports_are_counted_by_kind(corpus, tmp_path):
    r = tmp_path / "run"
    run("prepare", "--corpus", corpus, "--run", r, "--scale", SCALE, *MODELS)
    gaps = r / "sources" / "7" / "work" / "gaps"
    (gaps / "superseded").mkdir(parents=True)
    for gid, kind in (("GAP-1", "missing_concept"), ("GAP-2", "ambiguous_source_information")):
        (gaps / f"{gid}.json").write_text(json.dumps({"id": gid, "kind": kind, "about": f"about {gid}"}))
    (gaps / "superseded" / "GAP-3.json").write_text(json.dumps({"id": "GAP-3", "kind": "missing_concept"}))
    g = run("status", "--run", r)["gaps"]
    assert g["reports"] == {"ambiguous_source_information": 1, "missing_concept": 1}     # superseded/ not counted
    assert g["missing_concept"] == [{"source": "7", "gap": "GAP-1", "about": "about GAP-1"}]


def test_a_passed_source_shows_in_the_paper_index_at_once(tmp_path):
    """In a paper-acquisition project, recording a passed source updates papers.db (the index's Extracted column)."""
    import sqlite3
    sys.path.insert(0, str(REPO / "skills" / "paper-acquisition" / "scripts"))
    from _common import Project
    from _ledger import Ledger
    proj = Project(tmp_path / "project")
    (proj.scr / "t").mkdir(parents=True)
    (proj.scr / "t" / "config.json").write_text(json.dumps({"topic": "Test topic", "slug": "t"}))
    pdf = proj.root / "publications" / "t" / "papers" / "OA" / "7.pdf"
    pdf.parent.mkdir(parents=True)
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Cu foil reduces CO2 to formate at -0.9 V vs RHE.")
    doc.save(str(pdf))
    led = Ledger(proj)
    led.x("INSERT INTO papers (id, key, doi, title, authors, year, journal, doc_type, access_type, downloaded) "
          "VALUES (7, '10.1/seven', '10.1/seven', 'Formate on Cu', '[\"A. Author\"]', 2025, 'J. Test', 'article', 'OA', 1)")
    led.set_topic(7, "t", in_scope=1, relevance=5, path="publications/t/papers/OA/7.pdf")
    led.add_dois(7, ["10.1/seven"])
    led.export()
    manifest = proj.root / "publications" / "t" / "corpora" / "c" / "sources.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"corpus": "c", "topic": "t", "frozen_at": "2026-10-22", "counts": {"in_scope": 1},
                                    "included_status": "in_scope",
                                    "sources": [{"slug": "7", "status": "in_scope", "paper_id": 7, "title": "Formate on Cu",
                                                 "year": 2025, "pdf": "../../papers/OA/7.pdf", "licence": "cc-by"}]}))
    r = tmp_path / "run"
    run("prepare", "--corpus", manifest, "--run", r, "--scale", SCALE, *MODELS)
    f = r / "sources" / "7"
    run("next", "--run", r, "--role", "curate")
    write(f / "work" / "curation.json", {"result": "curated", "records": 1, "gaps": 0, "note": "test"})
    assert run("status", "--run", r)["states"] == {"curated": 1}
    run("next", "--run", r, "--role", "review")
    write(f / "work" / "review.json", {"verdict": "pass", "issues": []})
    st = run("status", "--run", r, "--apply")
    assert st["applied"] == 1 and st["index"]["exported"] is True
    con = sqlite3.connect(str(proj.db))
    assert con.execute("SELECT status, kg FROM extractions WHERE paper_id = 7").fetchone() == ("extracted", "run")
    con.close()



def test_prepare_asks_for_the_models_first_and_each_line_names_its_model(corpus, tmp_path):
    r = tmp_path / "run"
    r_ = subprocess.run([sys.executable, "-I", str(SCRIPT), "prepare", "--corpus", str(corpus), "--run", str(r),
                         "--scale", SCALE], capture_output=True, text=True)
    assert r_.returncode != 0 and "--curator" in r_.stderr and "skip is not recommended" in r_.stderr
    res = run("prepare", "--corpus", corpus, "--run", r, "--scale", SCALE, *MODELS)
    assert res["models"] == {"curator": "opus", "reviewer": "sonnet"}
    assert run("next", "--run", r, "--role", "curate")["model"] == "opus"
    write(r / "sources" / "7" / "work" / "curation.json", {"result": "curated", "records": 1, "gaps": 0, "note": "t"})
    assert run("next", "--run", r, "--role", "review")["model"] == "sonnet"


def test_a_run_that_skips_the_second_reading_settles_on_the_check(corpus, tmp_path):
    r = tmp_path / "run"
    run("prepare", "--corpus", corpus, "--run", r, "--scale", SCALE, "--curator", "haiku", "--reviewer", "skip")
    run("next", "--run", r, "--role", "curate")
    write(r / "sources" / "7" / "work" / "curation.json", {"result": "curated", "records": 1, "gaps": 0, "note": "t"})
    assert run("next", "--run", r, "--role", "review")["handed_out"] == 0
    st = run("status", "--run", r, "--apply")
    assert st["states"] == {"passed": 1} and st["applied"] == 1
    line = json.loads((r / "state.jsonl").read_text().splitlines()[-1])
    assert (line["curator"], line["second_reading"]) == ("haiku", "skip")


def test_an_api_model_reads_a_second_time(corpus, tmp_path):
    import http.server
    import threading
    seen, answers = [], [{"verdict": "needs_fix", "issues": [{"record": "ex:a", "locator": "p. 1", "problem": "unit",
                                                              "fix": "V vs RHE"}], "coverage": "all", "note": "x"},
                         {"verdict": "pass", "issues": [], "coverage": "all", "note": "fine"}]

    class Reader(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            out = json.dumps({"choices": [{"message": {"content": "Here: " + json.dumps(answers[len(seen) - 1])}}]})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out.encode("utf-8"))

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Reader)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["TEST_READER_KEY"] = "secret"
    try:
        r = tmp_path / "run"
        run("prepare", "--corpus", corpus, "--run", r, "--scale", SCALE, "--curator", "sonnet", "--reviewer",
            "api:test-reader", "--api-base-url", f"http://127.0.0.1:{srv.server_port}/v1", "--api-key-env",
            "TEST_READER_KEY")
        f = r / "sources" / "7"
        run("next", "--run", r, "--role", "curate")
        write(f / "work" / "curation.json", {"result": "curated", "records": 1, "gaps": 0, "note": "t"})
        assert "review-api" in run("next", "--run", r, "--role", "review")["next"]
        got = run("review-api", "--run", r)
        assert got["read"] == [{"id": "7", "verdict": "needs_fix", "issues": 1}] and not got["failed"]
        ask = seen[0]
        assert ask["path"] == "/v1/chat/completions" and ask["auth"] == "Bearer secret"
        assert ask["body"]["model"] == "test-reader" and "Faradaic efficiency" in ask["body"]["messages"][1]["content"]
        assert run("status", "--run", r)["states"] == {"needs_fix": 1}
        assert "V vs RHE" in Path(run("next", "--run", r, "--role", "fix")["prompt"]).read_text()
        write(f / "work" / "curation.json", {"result": "curated", "records": 1, "gaps": 0, "note": "fixed", "attempt": 1})
        assert run("review-api", "--run", r)["read"][0]["verdict"] == "pass"
        assert run("status", "--run", r)["states"] == {"passed": 1}
        assert json.loads((f / "work" / "review.json").read_text())["reader"] == "api:test-reader"
    finally:
        os.environ.pop("TEST_READER_KEY", None)
        srv.shutdown()
