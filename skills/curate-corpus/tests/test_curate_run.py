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
    pdf = tmp_path / "files" / "7.pdf"
    pdf.parent.mkdir()
    doc = fitz.open()
    for text in ("Cu foil reduces CO2 to formate at -0.9 V vs RHE.", "The Faradaic efficiency to formate was 61 %."):
        doc.new_page().insert_text((72, 72), text)
    doc.save(str(pdf))
    si = tmp_path / "files" / "7_SI.txt"
    si.write_text("Table S1. Faradaic efficiency to CO: 12 %.", encoding="utf-8")
    manifest = tmp_path / "corpus" / "sources.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({
        "corpus": "a test corpus", "frozen_at": "2026-10-19", "counts": {"in_scope": 1, "off_scope": 1},
        "included_status": "in_scope",
        "sources": [{"slug": "7", "status": "in_scope", "source_id": 7, "title": "Formate on Cu", "year": 2025,
                     "pdf": "../files/7.pdf", "si": ["../files/7_SI.txt"], "licence": "cc-by"},
                    {"slug": "8", "status": "off_scope", "source_id": 8, "status_reason": "screened out"}]}),
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
    assert "curate-corpus" in Path(out["prompt"]).read_text()
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
    write(f / "work" / "review.json", {"verdict": "reject", "issues": [], "note": "wrong source"})
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


def test_a_passed_source_shows_in_the_source_index_at_once(tmp_path):
    """In an index-sources project, recording a passed source updates index.db (the index's Extracted column)."""
    import sqlite3
    sys.path.insert(0, str(REPO / "skills" / "index-sources" / "scripts"))
    from _common import Project
    from _ledger import Ledger
    proj = Project(tmp_path / "project")
    (proj.scr / "t").mkdir(parents=True)
    (proj.scr / "t" / "config.json").write_text(json.dumps({"topic": "Test topic", "slug": "t"}))
    pdf = proj.root / "sources" / "t" / "files" / "OA" / "7.pdf"
    pdf.parent.mkdir(parents=True)
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Cu foil reduces CO2 to formate at -0.9 V vs RHE.")
    doc.save(str(pdf))
    led = Ledger(proj)
    led.x("INSERT INTO sources (id, key, doi, title, authors, year, journal, doc_type, access_type, downloaded) "
          "VALUES (7, '10.1/seven', '10.1/seven', 'Formate on Cu', '[\"A. Author\"]', 2025, 'J. Test', 'article', 'OA', 1)")
    led.set_topic(7, "t", in_scope=1, relevance=5, path="sources/t/files/OA/7.pdf")
    led.add_dois(7, ["10.1/seven"])
    led.export()
    manifest = proj.root / "sources" / "t" / "corpora" / "c" / "sources.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"corpus": "c", "topic": "t", "frozen_at": "2026-10-22", "counts": {"in_scope": 1},
                                    "included_status": "in_scope",
                                    "sources": [{"slug": "7", "status": "in_scope", "source_id": 7, "title": "Formate on Cu",
                                                 "year": 2025, "pdf": "../../files/OA/7.pdf", "licence": "cc-by"}]}))
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
    assert con.execute("SELECT status, kg FROM extractions WHERE source_id = 7").fetchone() == ("extracted", "run")
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


def test_the_curator_and_the_reader_are_told_to_digitize_main_result_figures(corpus, tmp_path):
    r = tmp_path / "run"
    run("prepare", "--corpus", corpus, "--run", r, "--scale", SCALE, *MODELS)
    assert "Digitizing a figure" in Path(run("next", "--run", r, "--role", "curate")["prompt"]).read_text()
    write(r / "sources" / "7" / "work" / "curation.json", {"result": "curated", "records": 1, "gaps": 0, "note": "t"})
    assert "left undigitized" in Path(run("next", "--run", r, "--role", "review")["prompt"]).read_text()


def test_a_material_made_for_another_use_is_curated_not_left_no_data(corpus, tmp_path):
    r = tmp_path / "run"
    run("prepare", "--corpus", corpus, "--run", r, "--scale", SCALE, *MODELS)
    curate = Path(run("next", "--run", r, "--role", "curate")["prompt"]).read_text()
    assert "makes or characterizes a material itself" in curate and "a review, an editorial" in curate
    write(r / "sources" / "7" / "work" / "curation.json", {"result": "no_data", "records": 0, "gaps": 0, "note": "t"})
    review = Path(run("next", "--run", r, "--role", "review")["prompt"]).read_text()
    assert "whatever the material" in review and "whatever the material" in SCRIPT.read_text()  # the API reader


def test_an_api_curator_runs_sandboxed_and_never_sees_another_run(corpus, tmp_path):
    def api_host(*args, ok=True, env=None):
        r = subprocess.run([sys.executable, "-I", str(HERE.parent / "scripts" / "api_host.py"), *map(str, args)],
                           capture_output=True, text=True, env={**os.environ, **(env or {})})
        assert (r.returncode == 0) == ok, r.stderr[-800:]
        return r.stdout

    other = tmp_path / "runs" / "by-claude"
    run("prepare", "--corpus", corpus, "--run", other, "--scale", SCALE, *MODELS)
    run("next", "--run", other, "--role", "curate")
    api_host("--run", other, "--id", "7", "--dry-run", ok=False)              # a Claude curator is a subagent's job
    r = tmp_path / "runs" / "by-api"
    run("prepare", "--corpus", corpus, "--run", r, "--scale", SCALE, "--curator", "api:test-model", "--reviewer",
        "sonnet", "--api-base-url", "http://127.0.0.1:9/v1", "--api-key-env", "TEST_HOST_KEY")
    api_host("--run", r, "--id", "7", "--dry-run", ok=False)                  # nothing handed out yet
    run("next", "--run", r, "--role", "curate")
    plan = json.loads(api_host("--run", r, "--id", "7", "--dry-run", "--deny", tmp_path / "elsewhere"))
    cmd, env, deny = plan["cmd"], plan["env"], plan["settings"]["permissions"]["deny"]
    assert cmd[cmd.index("--model") + 1] == "test-model" and env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9"
    sandbox = plan["settings"]["sandbox"]
    assert sandbox["enabled"] and env["TMPDIR"].endswith("/work/tmp")
    assert sandbox["allowUnsandboxedCommands"] is False                    # no command may ask to leave it
    assert sandbox["failIfUnavailable"] is True                            # no session runs without it
    assert f"Read(/{other.resolve()}/**)" in deny and f"Read(/{(tmp_path / 'elsewhere').resolve()}/**)" in deny
    assert not any(d.startswith(f"Read(/{r.resolve()}") for d in deny)       # its own run stays readable
    assert "--key-env TEST_HOST_KEY" in plan["settings"]["apiKeyHelper"] and "s3cret" not in json.dumps(plan)
    assert api_host("--key", "llm_api_key", "--key-env", "TEST_HOST_KEY", env={"TEST_HOST_KEY": "s3cret"}).strip() == "s3cret"
    if len(env["TMPDIR"]) > 70:                                             # a scratch path too long for the sandbox's
        refused = subprocess.run([sys.executable, "-I", str(HERE.parent / "scripts" / "api_host.py"), "--run", str(r),
                                  "--id", "7"], capture_output=True, text=True)  # sockets: refused before Claude Code runs
        assert refused.returncode != 0 and "the sandbox needs" in refused.stderr + refused.stdout


def test_a_model_behind_an_api_curates_and_the_run_records_it(corpus, tmp_path):
    r = tmp_path / "run"
    run("prepare", "--corpus", corpus, "--run", r, "--scale", SCALE, "--curator", "api:test-curator", "--reviewer",
        "sonnet", ok=False)                                                  # an API curator needs its endpoint
    run("prepare", "--corpus", corpus, "--run", r, "--scale", SCALE, "--curator", "api:", "--reviewer", "sonnet",
        "--api-base-url", "http://127.0.0.1:9/v1", ok=False)                 # and a model's name
    res = run("prepare", "--corpus", corpus, "--run", r, "--scale", SCALE, "--curator", "api:test-curator",
              "--reviewer", "sonnet", "--api-base-url", "http://127.0.0.1:9/v1")
    assert res["models"] == {"curator": "api:test-curator", "reviewer": "sonnet"}
    line = run("next", "--run", r, "--role", "curate")
    assert (line["model"], line["base_url"]) == ("api:test-curator", "http://127.0.0.1:9/v1")
    write(r / "sources" / "7" / "work" / "curation.json", {"result": "curated", "records": 1, "gaps": 0, "note": "t"})
    assert "base_url" not in run("next", "--run", r, "--role", "review")    # a Claude subagent reads it
    write(r / "sources" / "7" / "work" / "review.json", {"verdict": "pass", "issues": [], "coverage": "all", "note": "ok"})
    run("status", "--run", r, "--apply")
    state = json.loads((r / "state.jsonl").read_text().splitlines()[-1])
    assert (state["curator"], state["second_reading"]) == ("api:test-curator", "sonnet")


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
            answer = "Here: " + json.dumps(answers[len(seen) - 1])
            if len(seen) == 1:                                   # the first answer in one piece
                out, kind = json.dumps({"choices": [{"message": {"content": answer}}]}), "application/json"
            else:                                                # the second streamed, in two events
                out = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': part}}]})}\n\n"
                              for part in (answer[:9], answer[9:])) + "data: [DONE]\n\n"
                kind = "text/event-stream"
            self.send_response(200)
            self.send_header("Content-Type", kind)
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
        assert ask["path"] == "/v1/chat/completions" and ask["auth"] == "Bearer secret" and ask["body"]["stream"]
        assert "left undigitized" in ask["body"]["messages"][0]["content"]       # the figure rule reaches the reader
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


def _stream_server(plan):
    """A local endpoint answering each request with the next of `plan`: a list of SSE data lines (or None to close
    without any); returns the server and the list of requests seen."""
    import http.server
    import threading
    seen = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            seen.append(1)
            lines = plan[min(len(seen), len(plan)) - 1]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write("".join(f"data: {x}\n\n" for x in lines).encode("utf-8"))

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


def _delta(**kw):
    return json.dumps({"choices": [{"delta": kw}]})


def test_a_cut_stream_is_retried_and_a_whole_one_is_read(monkeypatch):
    sys.path.insert(0, str(HERE.parent / "scripts"))
    import curate_run
    monkeypatch.setattr(curate_run.time, "sleep", lambda s: None)
    answer = json.dumps({"verdict": "pass", "issues": []})
    cut = [_delta(reasoning_content="thinking"), _delta(content="")]                    # no finish_reason, no [DONE]
    stop = [_delta(reasoning_content="t"), _delta(content=answer), json.dumps(
        {"choices": [{"delta": {}, "finish_reason": "stop"}]})]                          # whole by finish_reason alone
    srv, seen = _stream_server([cut, stop])
    try:
        got = curate_run._chat(f"http://127.0.0.1:{srv.server_port}/v1", "k", "m", [])
        assert got == (answer, "t") and len(seen) == 2                                    # the cut one was sent again
        srv2, seen2 = _stream_server([[_delta(content=answer), "[DONE]"]])                # whole by [DONE] alone
        try:
            assert curate_run._chat(f"http://127.0.0.1:{srv2.server_port}/v1", "k", "m", []) == (answer, "")
        finally:
            srv2.shutdown()
    finally:
        srv.shutdown()


def test_a_stream_that_stays_cut_fails_and_its_work_is_kept(corpus, tmp_path, monkeypatch, capsys):
    cut = [_delta(reasoning_content="walked every field"), _delta(content="")]
    srv, seen = _stream_server([cut])
    os.environ["TEST_READER_KEY"] = "secret"
    try:
        r = tmp_path / "run"
        run("prepare", "--corpus", corpus, "--run", r, "--scale", SCALE, "--curator", "sonnet", "--reviewer",
            "api:test-reader", "--api-base-url", f"http://127.0.0.1:{srv.server_port}/v1", "--api-key-env",
            "TEST_READER_KEY")
        f = r / "sources" / "7"
        run("next", "--run", r, "--role", "curate")
        write(f / "work" / "curation.json", {"result": "curated", "records": 1, "gaps": 0, "note": "t"})
        sys.path.insert(0, str(HERE.parent / "scripts"))
        import curate_run
        monkeypatch.setattr(curate_run.time, "sleep", lambda s: None)
        monkeypatch.setattr(sys, "argv", ["curate_run.py", "review-api", "--run", str(r)])
        curate_run.main()
        got = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert got["read"] == [] and len(seen) == 5                                       # tried five times, no verdict
        assert got["failed"][0]["raw"] == "work/review-raw-1.json" and "cut off" in got["failed"][0]["error"]
        raw = json.loads((f / "work" / "review-raw-1.json").read_text())
        assert raw["reasoning_content"] == "walked every field" and raw["content"] == ""
        assert not (f / "work" / "review.json").exists()
    finally:
        os.environ.pop("TEST_READER_KEY", None)
        srv.shutdown()


def test_an_answer_without_a_verdict_is_kept_too(corpus, tmp_path):
    srv, seen = _stream_server([[_delta(reasoning_content="r"), _delta(content="no json here"), "[DONE]"]])
    os.environ["TEST_READER_KEY"] = "secret"
    try:
        r = tmp_path / "run"
        run("prepare", "--corpus", corpus, "--run", r, "--scale", SCALE, "--curator", "sonnet", "--reviewer",
            "api:test-reader", "--api-base-url", f"http://127.0.0.1:{srv.server_port}/v1", "--api-key-env",
            "TEST_READER_KEY")
        f = r / "sources" / "7"
        run("next", "--run", r, "--role", "curate")
        write(f / "work" / "curation.json", {"result": "curated", "records": 1, "gaps": 0, "note": "t"})
        got = run("review-api", "--run", r)
        assert got["read"] == [] and "no verdict" in got["failed"][0]["error"] and len(seen) == 1
        raw = json.loads((f / "work" / "review-raw-1.json").read_text())
        assert (raw["content"], raw["reasoning_content"]) == ("no json here", "r")
    finally:
        os.environ.pop("TEST_READER_KEY", None)
        srv.shutdown()


def _scripts():
    sys.path.insert(0, str(HERE.parent / "scripts"))
    import curate_run
    return curate_run


def test_a_large_document_is_cut_into_parts_that_read_every_record_and_link_once():
    cr = _scripts()
    nodes = [{"id": "ex:src", "label": "Source", "props": {"title": "S"}}]
    nodes += [{"id": f"ex:test/{k}", "label": "CatalyticTest", "props": {"name": f"run {k}", "pad": "x" * 400}}
              for k in range(12)]
    nodes += [{"id": f"ex:prep/{k}", "label": "Preparation", "props": {"name": f"prep {k}"}} for k in range(3)]
    links = [{"id": f"ex:l/{k}", "type": "REPORTED_IN", "source": n["id"], "target": "ex:src", "props": {}}
             for k, n in enumerate(nodes[1:])]
    links.append({"id": "ex:l/org", "type": "PARTICIPATES_IN", "source": "scale:org/x", "target": "ex:src", "props": {}})
    graph = {"directed": True, "multigraph": True, "graph": {"schema_version": "0.7.8"}, "nodes": nodes, "links": links}
    assert cr.doc_parts(graph, 10 ** 6) == [(graph, [])]                   # within the budget: one part, as before
    parts = cr.doc_parts(graph, 2500)
    assert len(parts) > 2
    seen_nodes = [n["id"] for p, _ in parts for n in p["nodes"]]
    seen_links = [x["id"] for p, _ in parts for x in p["links"]]
    assert sorted(seen_nodes) == sorted(n["id"] for n in nodes)           # every record once
    assert sorted(seen_links) == sorted(x["id"] for x in links)           # every link once, with the record it starts
    for p, others in parts:
        mine = {n["id"] for n in p["nodes"]}
        assert p["graph"] == graph["graph"] and all(x["source"] in mine for x in p["links"] if x["source"] != "scale:org/x")
        listed = {o.split(" | ")[0] for o in others}
        assert listed == {n["id"] for n in nodes} - mine                  # the other parts' records are listed
        assert len(json.dumps(p, separators=(",", ":"))) <= 2500
    labels = [n["label"] for p, _ in parts for n in p["nodes"]]
    assert labels == sorted(labels, key=["Source", "CatalyticTest", "Preparation"].index)   # a label kept together
    assert any("run 3" in o for _, others in parts for o in others)


def test_minor_issues_pass_and_a_major_one_or_one_without_severity_sends_it_back(corpus, tmp_path):
    cr = _scripts()
    minor = {"record": "ex:a", "locator": "p. 1", "problem": "quote could be longer", "fix": "extend", "severity": "minor"}
    major = {**minor, "problem": "wrong unit", "severity": "major"}
    assert cr.settled_verdict({"verdict": "needs_fix", "issues": [minor]}) == "pass"
    assert cr.settled_verdict({"verdict": "pass", "issues": [minor, major]}) == "needs_fix"
    assert cr.settled_verdict({"verdict": "needs_fix", "issues": [{**minor, "severity": None}]}) == "needs_fix"
    assert cr.settled_verdict({"verdict": "reject", "issues": []}) == "reject"
    r = tmp_path / "run"
    run("prepare", "--corpus", corpus, "--run", r, "--scale", SCALE, *MODELS)
    f = r / "sources" / "7"
    run("next", "--run", r, "--role", "curate")
    write(f / "work" / "curation.json", {"result": "curated", "records": 1, "gaps": 0, "note": "t"})
    run("next", "--run", r, "--role", "review")
    write(f / "work" / "review.json", {"verdict": "needs_fix", "issues": [minor, major]})
    assert run("status", "--run", r)["states"] == {"needs_fix": 1}
    fix = Path(run("next", "--run", r, "--role", "fix")["prompt"]).read_text()
    assert "[major] ex:a (p. 1): wrong unit" in fix and "[minor]" in fix
    write(f / "work" / "curation.json", {"result": "curated", "records": 1, "gaps": 0, "note": "fixed", "attempt": 1})
    review = Path(run("next", "--run", r, "--role", "review")["prompt"]).read_text()
    assert "wrong unit" in review and "Today's date is 20" in review and "severity" in review   # checked first
    write(f / "work" / "review.json", {"verdict": "needs_fix", "issues": [minor]})          # only a minor one left
    assert run("status", "--run", r)["states"] == {"passed": 1}


def test_an_api_reader_reads_a_large_document_in_parts_with_the_date_and_the_previous_issues(corpus, tmp_path):
    import http.server
    import threading
    seen = []
    first = {"verdict": "needs_fix", "issues": [{"record": "ex:a", "locator": "p. 1", "problem": "wrong unit",
                                                 "fix": "V vs RHE", "severity": "major"}], "coverage": "c", "note": "n"}
    minor = {"verdict": "needs_fix", "issues": [{"record": "ex:b", "locator": "p. 2", "problem": "short quote",
                                                 "fix": "extend", "severity": "minor"}], "coverage": "c", "note": "n2"}

    class Reader(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body["messages"][1]["content"])
            answer = first if len(seen) == 1 else minor
            out = f"data: {json.dumps({'choices': [{'delta': {'content': json.dumps(answer)}}]})}\n\ndata: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
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
        got = run("review-api", "--run", r)                                 # small enough: one request, as before
        assert got["read"] == [{"id": "7", "verdict": "needs_fix", "issues": 1}] and len(seen) == 1
        assert "TODAY'S DATE: 20" in seen[0] and "PREVIOUS READING" not in seen[0] and "PART 1" not in seen[0]
        run("next", "--run", r, "--role", "fix")
        write(f / "work" / "curation.json", {"result": "curated", "records": 1, "gaps": 0, "note": "fixed", "attempt": 1})
        graph = json.loads(next(f.glob("*.graph.json")).read_text())
        size = len(json.dumps(graph, separators=(",", ":")))
        got = run("review-api", "--run", r, "--max-doc-chars", size // 2)   # too large now: read in parts
        n = got["read"][0]["parts"]
        assert n >= 2 and len(seen) == 1 + n and got["read"][0]["verdict"] == "pass"   # only a minor issue: passed
        for k, ask in enumerate(seen[1:], 1):
            assert f"PART {k} OF {n}" in ask and "THE RECORDS IN THE OTHER PARTS" in ask
            assert "[major] ex:a (p. 1): wrong unit" in ask                  # the previous issues, to check first
        review = json.loads((f / "work" / "review.json").read_text())
        assert review["parts"] == n and len(review["issues"]) == 1 and review["issues"][0]["severity"] == "minor"
        assert run("status", "--run", r)["states"] == {"passed": 1}
    finally:
        os.environ.pop("TEST_READER_KEY", None)
        srv.shutdown()


def test_a_reading_is_fitted_to_the_readers_context_window():
    cr = _scripts()
    doc, text = 950_000, 80_000                                          # a large document and its page texts
    assert cr.reading_budget(None, doc, text, 10_000, 15_000, 300_000) == (text, cr.DOC_CHARS)   # no window: as before
    t, d = cr.reading_budget(1_000_000, doc, text, 10_000, 15_000, 300_000)
    assert (t, d) == (text, doc)                                         # 1M tokens: all of it in one request
    t, d = cr.reading_budget(128_000, doc, text, 10_000, 15_000, 300_000)
    room = (128_000 - cr.ANSWER_TOKENS) * cr.CHARS_PER_TOKEN - 10_000 - cr.width(cr.READER)
    assert t == text and d < doc and d + t + 15_000 <= room              # 128k tokens: parts, each fits with the texts
    t, d = cr.reading_budget(64_000, doc, 250_000, 10_000, 15_000, 300_000)
    room = (64_000 - cr.ANSWER_TOKENS) * cr.CHARS_PER_TOKEN - 10_000 - cr.width(cr.READER)
    assert d == room // 2 and t + d + 15_000 <= room and t < 250_000     # small window: the texts are cut, not the parts
    assert cr.reading_budget(1_000_000, doc, text, 0, 0, 300_000, max_doc_chars=200_000)[1] == 200_000   # a cap holds
    assert cr.reading_budget(262_144, 200_000, 50_000, 10_000, 5_000, 300_000)[1] == 200_000   # it fits: one part


def test_text_outside_ascii_counts_as_a_token_a_character():
    cr = _scripts()
    assert cr.width("abc") == 3 and cr.width("電子") == 2 * cr.CHARS_PER_TOKEN
    assert cr.head_within("ab電子cd", 5) == "ab電" and cr.head_within("ab電子cd", 4) == "ab" and cr.head_within("abc", 10) == "abc"
    nodes = [{"id": f"ex:{k}", "label": "Claim", "props": {"name": "電子回収率" * 40}} for k in range(10)]
    graph = {"graph": {}, "nodes": nodes, "links": []}
    for p, _ in cr.doc_parts(graph, 2000):
        assert cr.width(json.dumps(p, ensure_ascii=False, separators=(",", ":"))) <= 2000
