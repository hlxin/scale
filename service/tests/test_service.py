"""The web service (service/scaleweb), offline: a scripted model stands in for the Messages API, GitHub is never
called, and the source's page texts come from a text file."""

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import REPO

sys.path.insert(0, str(REPO / "service"))                 # the scaleweb package, not installed with scale-catal
from scale import curate
from scale.util import load_doc
from scaleweb import agent, auth, fetch  # noqa: E402
from scaleweb.app import Service  # noqa: E402
from scaleweb.config import Config  # noqa: E402

TEXT = ("[page 1]\nResults. The copper catalyst gave 42 % selectivity to methanol at about 250 °C.\n\n"
        "[page 2]\nWe conclude that copper is the active phase.\n")
PUBLIC = REPO / "examples" / "methanol-synthesis-public"


class Model:
    """A scripted model: each turn returns the next list of blocks; ``usage`` counts 100 tokens a turn."""

    def __init__(self, turns):
        self.turns, self.seen = list(turns), []
        self.messages = self

    def create(self, **kw):
        self.seen.append(kw)
        blocks = self.turns.pop(0)
        if callable(blocks):
            blocks = blocks(kw)
        return SimpleNamespace(content=blocks, stop_reason="tool_use", usage=SimpleNamespace(input_tokens=80, output_tokens=20))


def use(name, inp, i=0):
    return {"type": "tool_use", "id": f"t{name}{i}", "name": name, "input": inp}


def cfg(tmp_path, **kw):
    return Config(secret="s" * 40, github_client_id="cid", allowlist=["ada"], site_origins=["https://hlxin.github.io"],
                  public_url="https://scale.example", workdir=str(tmp_path / "jobs"), **kw)


def started(tmp_path):
    (tmp_path / "paper.txt").write_text(TEXT, encoding="utf-8")
    res = curate.start(tmp_path / "w", text=tmp_path / "paper.txt", repo=REPO)
    return tmp_path / "w", res


def claim(sid, prefix, quote):
    return {"id": f"{prefix}/claim/1", "label": "Claim",
            "props": {"name": "copper active", "statement": "Copper is the active phase.", "claim_kind": "finding",
                      "claim_status": "proposed", "origin": "reported",
                      "evidence": [{"source": sid, "locator": "p. 2", "kind": "text", "quote": quote}]}}


def curation_turns(sid, prefix, quote="copper is the active phase"):
    return [[use("read_pages", {"first": 1, "last": 2})],
            [use("describe", {"names": ["Claim"]})],
            [use("upsert", {"nodes": [claim(sid, prefix, quote)]})],
            [use("check", {})],
            [{"type": "text", "text": "Checked."}, use("done", {"summary": "One claim curated."})]]


def test_the_model_curates_through_the_tools_until_the_check_passes(tmp_path):
    w, res = started(tmp_path)
    sid = res["source_id"]
    prefix = sid.replace("/source/", "/")
    model = Model(curation_turns(sid, prefix))
    log = []
    out = agent.curate_folder(w, model, "m", max_turns=10, max_tokens=10_000, log=log.append, repo=REPO)
    assert out["check"]["ok"] and out["summary"] == "One claim curated." and out["tokens"] == 500
    assert [line.split()[0] for line in log] == ["read_pages", "describe", "upsert", "check"]
    first = model.seen[0]
    assert "curate-source" not in first["system"][0]["text"][:3] and "# Curate" in first["system"][0]["text"]
    assert "[page 2]" in model.seen[1]["messages"][2]["content"][0]["content"]       # the page texts reached the model
    doc = load_doc(w / res["graph"])
    assert any(e["type"] == "REPORTED_IN" and e["source"] == f"{prefix}/claim/1" for e in doc["links"])


def test_a_quote_not_in_the_source_keeps_the_check_failing_and_the_fixed_records_stay(tmp_path):
    w, res = started(tmp_path)
    sid = res["source_id"]
    prefix = sid.replace("/source/", "/")
    turns = curation_turns(sid, prefix, quote="gold is the active phase")
    turns.insert(3, [use("remove", {"ids": [sid, f"{prefix}/nothing"]})])
    out = agent.curate_folder(w, Model(turns), "m", max_turns=10, max_tokens=10_000, repo=REPO)
    assert not out["check"]["ok"] and out["check"]["errors"][0]["record"] == f"{prefix}/claim/1"
    assert any(n["id"] == sid for n in load_doc(w / res["graph"])["nodes"])      # the Source cannot be removed


def test_the_loop_stops_at_its_token_budget(tmp_path):
    w, res = started(tmp_path)
    turns = [[use("graph_summary", {}, i)] for i in range(10)]
    out = agent.curate_folder(w, Model(turns), "m", max_turns=10, max_tokens=250, repo=REPO)
    assert out["stopped"].startswith("token budget reached") and out["tokens"] == 300


def test_a_question_is_answered_with_the_tools_own_query(tmp_path):
    svc = Service(cfg(tmp_path), repo=REPO)
    graph = load_doc(PUBLIC)
    plan = {"match": {"label": "Catalyst", "as": "c"}, "return": ["c.name"], "limit": 3}
    direct = svc.route("POST", "/query", {}, {}, json.dumps({"graph": graph, "plan": plan}).encode())
    assert direct[0] == 200 and direct[1]["status"] == "answered" and len(direct[1]["rows"]) == 3
    model = Model([[use("query", {"plan": plan})],
                   lambda kw: [{"type": "text", "text": "Three catalysts [rows]."}]])
    svc.client_factory = lambda: model
    token = auth.session_for(svc.cfg, "Ada")
    st, body, _ = svc.route("POST", "/ask", {}, {"authorization": f"Bearer {token}"},
                            json.dumps({"graph": graph, "question": "Which catalysts?"}).encode())
    assert st == 200 and body["answer"] == "Three catalysts [rows]." and body["plans"][0]["status"] == "answered"
    asked = json.loads(model.seen[1]["messages"][2]["content"][0]["content"])
    assert asked["rows"] == direct[1]["rows"]                       # the model saw exactly what scale query returns
    assert "# Query scale-catal documents" in model.seen[0]["system"][0]["text"]


def test_search_runs_without_sign_in_and_asking_needs_it(tmp_path):
    svc = Service(cfg(tmp_path), repo=REPO)
    graph = load_doc(PUBLIC)
    st, body, _ = svc.route("POST", "/search", {}, {}, json.dumps({"graph": graph, "query": "zinc chromium", "k": 3}).encode())
    assert st == 200 and len(body["hits"]) == 3
    assert svc.route("POST", "/ask", {}, {}, json.dumps({"graph": graph, "question": "?"}).encode())[0] == 401


def test_sign_in_admits_only_the_allowlist_and_returns_only_to_the_site(tmp_path, monkeypatch):
    svc = Service(cfg(tmp_path), repo=REPO)
    assert svc.route("GET", "/auth/login", {"return": "https://evil.example/"}, {}, b"")[0] == 400
    st, _, h = svc.route("GET", "/auth/login", {"return": "https://hlxin.github.io/scale/"}, {}, b"")
    assert st == 302 and h["Location"].startswith("https://github.com/login/oauth/authorize?")
    state = dict(x.split("=", 1) for x in h["Location"].split("?", 1)[1].split("&"))["state"]
    for login, expect in (("Ada", "#token="), ("eve", "#signin=not-allowed")):
        monkeypatch.setattr(auth, "github_login", lambda c, code, login=login: login)
        _, _, h2 = svc.route("GET", "/auth/callback", {"code": "x", "state": state}, {}, b"")
        assert h2["Location"].startswith("https://hlxin.github.io/scale/" + expect)
    token = svc.route("GET", "/auth/callback", {"code": "x", "state": "forged.mac"}, {}, b"")
    assert token[0] == 400
    good = auth.session_for(svc.cfg, "ada")
    assert svc.route("GET", "/me", {}, {"authorization": f"Bearer {good}"}, b"")[1]["login"] == "ada"
    assert svc.route("GET", "/me", {}, {"authorization": f"Bearer {good[:-2]}xx"}, b"")[0] == 401
    old = auth.sign(svc.cfg, {"sub": "ada", "exp": int(time.time()) - 1})
    assert svc.route("GET", "/me", {}, {"authorization": f"Bearer {old}"}, b"")[0] == 401


def test_a_job_curates_returns_the_capped_graph_once_and_keeps_nothing(tmp_path, monkeypatch):
    svc = Service(cfg(tmp_path), repo=REPO, run_inline=True)
    real = curate.start

    def start(out, doi=None, pdf=None, **kw):                     # the PDF's text, without PyMuPDF
        assert pdf.read_bytes().startswith(b"%PDF")
        (tmp_path / "paper.txt").write_text(TEXT, encoding="utf-8")
        return real(out, text=tmp_path / "paper.txt", **kw)
    monkeypatch.setattr(curate, "start", start)
    sid = "ex:pub/source/paper"
    model = Model(curation_turns(sid, "ex:pub/paper"))
    svc.client_factory = lambda: model
    h = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}", "content-type": "application/pdf"}
    assert svc.route("POST", "/jobs", {}, {**h, "authorization": ""}, b"%PDF")[0] == 401
    assert svc.route("POST", "/jobs", {}, h, b"not a pdf")[0] == 400
    st, body, _ = svc.route("POST", "/jobs", {"filename": "paper.pdf"}, h, b"%PDF-1.7 a file")
    assert st == 202
    st, job, _ = svc.route("GET", f"/jobs/{body['job']}", {}, h, b"")
    assert st == 200 and job["state"] == "done", job.get("error")
    assert job["check"]["ok"] and job["source"]["rights_class"] == "in_copyright"
    quotes = [ev for n in job["graph"]["nodes"] for ev in (n["props"].get("evidence") or [])]
    assert quotes and all(len(ev.get("quote", "")) <= 300 for ev in quotes)
    assert svc.route("GET", f"/jobs/{body['job']}", {}, h, b"")[0] == 404           # read once
    assert not any(Path(svc.jobs.root).iterdir())                                   # nothing kept
    other = {**h, "authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}"}
    svc.cfg.jobs_per_user_per_day = 1
    assert svc.route("POST", "/jobs", {}, other, b"%PDF-1.7")[0] == 429             # today's jobs used


def test_links_are_fetched_only_from_public_addresses():
    assert fetch.doi_in("https://doi.org/10.1021/ie50220a011") == "10.1021/ie50220a011"
    assert fetch.doi_in("see doi:10.1098/rspa.1923.0036.") == "10.1098/rspa.1923.0036"
    assert fetch.doi_in("https://example.org/paper") is None
    assert fetch.arxiv_pdf("https://arxiv.org/abs/2401.01234v2") == "https://arxiv.org/pdf/2401.01234v2"
    for bad in ("file:///etc/passwd", "http://127.0.0.1/x.pdf", "http://169.254.169.254/latest", "http://localhost/a"):
        with pytest.raises(fetch.FetchError):
            fetch.check_url(bad)


def test_the_page_names_the_service_and_the_readme_links_the_page():
    site = REPO / "site"
    html = (site / "index.html").read_text(encoding="utf-8")
    assert "config.js" in html and "app.js" in html
    assert "SCALE_SERVICE_URL" in (site / "config.js").read_text(encoding="utf-8")
    assert "hlxin.github.io/scale" in (REPO / "README.md").read_text(encoding="utf-8")
