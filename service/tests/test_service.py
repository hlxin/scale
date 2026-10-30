"""The web service (service/scaleweb), offline: a scripted model stands in for the Messages API, GitHub is never
called, and the source's page texts come from a text file."""

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import REPO

sys.path.insert(0, str(REPO / "service"))                 # the scaleweb package, not installed with scale-catal
from scale import curate
from scale.util import load_doc, write_canonical
from scaleweb import agent, auth, fetch, runner  # noqa: E402
from scaleweb.inbox import SETTLE_S, Inbox  # noqa: E402
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
    assert "curate-corpus" not in first["system"][0]["text"][:3] and "# Curate" in first["system"][0]["text"]
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


NONCE = "n0nce-of-this-tab-0123"


def signed_in(svc, ret="https://hlxin.github.io/scale/", nonce=NONCE):
    """Start a sign-in at /auth/login; the OAuth state GitHub would send back to /auth/callback."""
    st, _, h = svc.route("GET", "/auth/login", {"return": ret, "nonce": nonce}, {}, b"")
    assert st == 302 and h["Location"].startswith("https://github.com/login/oauth/authorize?")
    return urllib.parse.parse_qs(urllib.parse.urlsplit(h["Location"]).query)["state"][0]


def answer(location):
    """The page's address and the answer in its fragment."""
    u = urllib.parse.urlsplit(location)
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, u.query, "")), dict(urllib.parse.parse_qsl(u.fragment))


def test_sign_in_admits_only_the_allowlist_and_returns_only_to_the_site(tmp_path, monkeypatch):
    svc = Service(cfg(tmp_path), repo=REPO)
    assert svc.route("GET", "/auth/login", {"return": "https://evil.example/", "nonce": NONCE}, {}, b"")[0] == 400
    for login, expect in (("Ada", "token"), ("eve", "signin")):
        state = signed_in(svc)
        monkeypatch.setattr(auth, "github_login", lambda c, code, login=login: login)
        _, _, h2 = svc.route("GET", "/auth/callback", {"code": "x", "state": state}, {}, b"")
        page, frag = answer(h2["Location"])
        assert page == "https://hlxin.github.io/scale/" and expect in frag and frag["nonce"] == NONCE
    assert frag["signin"] == "not-allowed" and frag["login"] == "eve"
    token = svc.route("GET", "/auth/callback", {"code": "x", "state": "forged.mac"}, {}, b"")
    assert token[0] == 400
    good = auth.session_for(svc.cfg, "ada")
    assert svc.route("GET", "/me", {}, {"authorization": f"Bearer {good}"}, b"")[1]["login"] == "ada"
    assert svc.route("GET", "/me", {}, {"authorization": f"Bearer {good[:-2]}xx"}, b"")[0] == 401
    old = auth.sign(svc.cfg, {"sub": "ada", "exp": int(time.time()) - 1})
    assert svc.route("GET", "/me", {}, {"authorization": f"Bearer {old}"}, b"")[0] == 401


def test_a_sign_in_is_one_transaction_of_the_tab_that_started_it(tmp_path, monkeypatch):
    """The page's nonce goes through GitHub and back with the answer, the OAuth state is used once, and the page's
    fragment (the explorer's open graph) comes back with the answer merged into it."""
    svc = Service(cfg(tmp_path), repo=REPO)
    monkeypatch.setattr(auth, "github_login", lambda c, code: "ada")
    for nonce in ("", "short", "has space in it 0123456", "x" * 129):        # no nonce, no sign-in
        assert svc.route("GET", "/auth/login", {"return": "https://hlxin.github.io/scale/", "nonce": nonce}, {}, b"")[0] == 400
    state = signed_in(svc, ret="https://hlxin.github.io/scale/?a=1#g=methanol%2Fpre1966&token=stale&nonce=old")
    _, _, h = svc.route("GET", "/auth/callback", {"code": "x", "state": state}, {}, b"")
    page, frag = answer(h["Location"])
    assert page == "https://hlxin.github.io/scale/?a=1"
    assert frag["g"] == "methanol/pre1966" and frag["nonce"] == NONCE and frag["token"] != "stale"
    assert auth.unsign(svc.cfg, frag["token"])["sub"] == "ada"
    again = svc.route("GET", "/auth/callback", {"code": "y", "state": state}, {}, b"")   # the same state twice
    assert again[0] == 400 and "used already" in again[1]["error"]


def test_a_return_address_cannot_add_a_header(tmp_path):
    svc = Service(cfg(tmp_path), repo=REPO)
    for ret in ("https://hlxin.github.io/scale/\r\nX-Injected: yes", "https://hlxin.github.io/scale/\nSet-Cookie: a=b",
                "https://hlxin.github.io/sc ale/", "https://hlxin.github.io/scälé/", "javascript://hlxin.github.io/%0aalert(1)",
                "https://hlxin.github.io.evil.example/", "https://user@hlxin.github.io/"):
        assert svc.route("GET", "/auth/login", {"return": ret, "nonce": NONCE}, {}, b"")[0] == 400, ret
    assert auth.clean_return(svc.cfg, "https://hlxin.github.io") == "https://hlxin.github.io/"


def test_an_allowlist_of_star_admits_any_github_account(tmp_path, monkeypatch):
    svc = Service(cfg(tmp_path), repo=REPO)
    svc.cfg.allowlist = ["*"]
    state = signed_in(svc)
    monkeypatch.setattr(auth, "github_login", lambda c, code: "Eve")
    _, _, h2 = svc.route("GET", "/auth/callback", {"code": "x", "state": state}, {}, b"")
    assert "token" in answer(h2["Location"])[1]
    eve = auth.session_for(svc.cfg, "eve")
    assert svc.route("GET", "/me", {}, {"authorization": f"Bearer {eve}"}, b"")[1]["login"] == "eve"
    svc.cfg.allowlist = ["ada"]                                  # the session stops when the account is no longer admitted
    assert svc.route("GET", "/me", {}, {"authorization": f"Bearer {eve}"}, b"")[0] == 401


def test_a_doi_the_commons_holds_is_not_curated_again(tmp_path):
    """A DOI the commons holds is answered from it: no job, no model, nothing taken from the day's jobs; asked again
    with again=1 it is curated all the same."""
    svc = Service(cfg(tmp_path, commons="graphs/methanol-synthesis-pre1966"), repo=REPO)
    svc.client_factory = lambda: pytest.fail("no model is called for a known DOI")
    svc.cfg.jobs_per_user_per_day = 1
    h = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}", "content-type": "application/json"}
    st, body, _ = svc.route("POST", "/jobs", {}, h, json.dumps({"doi": "https://doi.org/10.1246/NIKKASHI1898.60.166"}).encode())
    assert st == 200 and body["known"]["in_commons"][0]["by"] == ["doi"]
    assert body["known"]["in_commons"][0]["url"].startswith("https://github.com/hlxin/scale/blob/main/graphs/")
    st, body, _ = svc.route("POST", "/jobs", {}, h, json.dumps({"doi": "10.1246/nikkashi1898.60.166"}).encode())
    assert st == 200 and "known" in body                         # still free: the day's one job is not used
    svc.jobs.submit = lambda user, **kw: "j-again"
    st, body, _ = svc.route("POST", "/jobs", {"again": "1"}, h, json.dumps({"doi": "10.1246/nikkashi1898.60.166"}).encode())
    assert st == 202 and body["job"] == "j-again"


def test_a_job_curates_returns_the_capped_graph_until_collected_and_keeps_nothing(tmp_path, monkeypatch):
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
    assert st == 400 and "lawful access" in body["error"]                          # no statement of access, no job
    st, body, _ = svc.route("POST", "/jobs", {"filename": "paper.pdf", "attest": "1"}, h, b"%PDF-1.7 a file")
    assert st == 202
    st, job, _ = svc.route("GET", f"/jobs/{body['job']}", {}, h, b"")
    assert st == 200 and job["state"] == "done", job.get("error")
    assert job["check"]["ok"] and job["source"]["rights_class"] == "in_copyright"
    quotes = [ev for n in job["graph"]["nodes"] for ev in (n["props"].get("evidence") or [])]
    assert quotes and all(len(ev.get("quote", "")) <= 300 for ev in quotes)
    jid = body["job"]
    st, again, _ = svc.route("GET", f"/jobs/{jid}", {}, h, b"")                    # a reply lost on the way: asked again
    assert st == 200 and again["graph"] == job["graph"]
    bob = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'bob')}"}
    svc.cfg.allowlist.append("bob")
    assert svc.route("POST", f"/jobs/{jid}/done", {}, bob, b"")[0] == 404            # only its owner collects it
    assert svc.route("POST", f"/jobs/{jid}/done", {}, h, b"")[0] == 200
    assert svc.route("GET", f"/jobs/{jid}", {}, h, b"")[0] == 404                    # then it is forgotten
    assert not any(Path(svc.jobs.root).iterdir())                                   # nothing kept
    other = {**h, "authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}"}
    svc.cfg.jobs_per_user_per_day = 1
    assert svc.route("POST", "/jobs", {"attest": "1"}, other, b"%PDF-1.7")[0] == 429             # today's jobs used


def test_an_uncollected_result_goes_an_hour_after_its_job_ends_and_a_running_job_stays(tmp_path):
    svc = Service(cfg(tmp_path), repo=REPO)
    now = time.time()

    def job(jid, state, ended=None):
        (svc.jobs.root / jid).mkdir()
        return {"id": jid, "owner": "ada", "state": state, "created": now - 7200, "folder": svc.jobs.root / jid, "log": [],
                **({"ended": ended} if ended else {})}
    svc.jobs.jobs = {"fresh": job("fresh", "done", now - 60), "old": job("old", "failed", now - 3700),
                     "running": job("running", "curating")}
    svc.jobs.sweep()
    assert set(svc.jobs.jobs) == {"fresh", "running"} and not (svc.jobs.root / "old").exists()
    assert not svc.jobs.done("running", "ada") and svc.jobs.view("running", "ada")["state"] == "curating"


def test_a_receipt_never_signs_in_and_a_session_is_no_receipt(tmp_path):
    """A contribution receipt lives a week, a session a day: each token names its use, and each check takes only its own."""
    svc = Service(cfg(tmp_path), repo=REPO)
    graph, entry = {"graph": {}, "nodes": [], "links": []}, {"class": "open"}
    receipt, session = auth.receipt(svc.cfg, "ada", graph, entry), auth.session_for(svc.cfg, "ada")
    assert auth.user_of(svc.cfg, f"Bearer {receipt}") is None
    assert svc.route("GET", "/me", {}, {"authorization": f"Bearer {receipt}"}, b"")[0] == 401
    assert auth.user_of(svc.cfg, f"Bearer {session}") == "ada"
    assert auth.check_receipt(svc.cfg, session, "ada", graph) is None
    assert auth.check_receipt(svc.cfg, receipt, "ada", graph) == entry
    legacy = auth.sign(svc.cfg, {"sub": "ada", "exp": int(time.time()) + 600})     # a token that names no use
    assert auth.user_of(svc.cfg, f"Bearer {legacy}") is None


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
    assert "config.js" in html and "app.js" in (site / "publication.html").read_text(encoding="utf-8")
    assert "apiKey" not in (site / "explorer.js").read_text(encoding="utf-8")     # no reader is asked for a model key
    assert "SCALE_SERVICE_URL" in (site / "config.js").read_text(encoding="utf-8")
    assert "hlxin.github.io/scale" in (REPO / "README.md").read_text(encoding="utf-8")


class FakeGitHub:
    """main holds graphs/catal-commons as this checkout has it; pull requests and branches are kept in memory."""

    def __init__(self):
        root = REPO / "graphs" / "catal-commons"
        self.files = {f"graphs/catal-commons/{p.relative_to(root)}": p.read_text(encoding="utf-8")
                      for p in root.rglob("*") if p.is_file()}
        self.pulls, self.trees, self.refs, self.calls = [], {}, {}, []

    def __call__(self, method, url, token, body=None, raw=False):
        assert token == "bot-token"
        self.calls.append((method, url))
        if url.startswith("https://raw.githubusercontent.com/"):
            sha, path = url.split("/", 6)[5], url.split("/", 6)[6]
            files = self.files if sha == "main-sha" else self.trees[sha]
            return files[path]
        path = url.split("/repos/hlxin/scale", 1)[1]
        if path == "/git/ref/heads/main":
            return {"object": {"sha": "main-sha"}}
        if path.startswith("/git/trees/main-sha"):
            return {"tree": [{"path": p, "type": "blob"} for p in self.files]}
        if path == "/git/commits/main-sha":
            return {"tree": {"sha": "main-tree"}}
        if path == "/git/trees" and method == "POST":
            self.trees["new-tree"] = {**self.files, **{t["path"]: t["content"] for t in body["tree"]}}
            self.tree_body = body
            return {"sha": "new-tree"}
        if path == "/git/commits" and method == "POST":
            self.trees["new-commit"] = self.trees[body["tree"]]
            self.commit = body
            return {"sha": "new-commit"}
        if path == "/git/refs":
            self.refs[body["ref"]] = body["sha"]
            return {}
        if path == "/pulls" and method == "POST":
            n = 100 + len(self.pulls)
            self.pulls.append({"number": n, "html_url": f"https://github.com/hlxin/scale/pull/{n}", "title": body["title"],
                               "body": body["body"], "head": {"ref": body["head"], "sha": "new-commit"}})
            return {"number": n, "html_url": f"https://github.com/hlxin/scale/pull/{n}"}
        if path.startswith("/pulls?state=open"):
            return self.pulls
        if path.startswith("/pulls/") and path.endswith("/files?per_page=100"):
            changed = self.tree_body["tree"]
            return [{"filename": t["path"], "status": "added"} for t in changed]
        if path.endswith("/requested_reviewers"):
            self.reviewers = body["reviewers"]
            return {}
        raise AssertionError(f"unexpected {method} {path}")


def finished_job(tmp_path, monkeypatch, gh):
    c = cfg(tmp_path, github_token="bot-token", reviewers=["mutianyou2013", "diazr04"])
    svc = Service(c, repo=REPO, run_inline=True, github_request=gh)
    real = curate.start

    meta = {"message": {"title": ["Copper catalysts for methanol synthesis"], "issued": {"date-parts": [[2026]]},
                        "type": "journal-article"}}

    def start(out, doi=None, pdf=None, **kw):
        (tmp_path / "paper.txt").write_text(TEXT, encoding="utf-8")
        return real(out, text=tmp_path / "paper.txt", doi=doi, get=lambda url, h: json.dumps(meta).encode(), **kw)
    monkeypatch.setattr(curate, "start", start)
    svc.client_factory = lambda: Model(curation_turns("ex:pub/source/10.9999-paper.1", "ex:pub/10.9999-paper.1"))
    h = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}", "content-type": "application/pdf"}
    jid = svc.route("POST", "/jobs", {"filename": "paper.pdf", "doi": "10.9999/paper.1", "attest": "1"}, h, b"%PDF-1.7 a file")[1]["job"]
    job = svc.route("GET", f"/jobs/{jid}", {}, h, b"")[1]
    assert job["state"] == "done" and job["rights"]["class"] == "in_copyright" and job["receipt"]
    return svc, h, json.loads(json.dumps(job))              # the page's copy, after a round trip through JSON


def test_a_curated_graph_is_contributed_by_a_pull_request_once(tmp_path, monkeypatch):
    gh = FakeGitHub()
    svc, h, job = finished_job(tmp_path, monkeypatch, gh)
    req = lambda path, **kw: svc.route("POST", path, {}, h, json.dumps({"graph": job["graph"], "receipt": job["receipt"], **kw}).encode())
    st, body, _ = req("/contribute/check")
    assert st == 200 and body["new"]["source"] == "scale:commons/source/10.9999-paper.1" and body["new"]["quotes"]["kept"] == 0
    assert not any(m == "POST" for m, _ in gh.calls)                          # a check writes nothing
    st, body, _ = req("/contribute")
    assert st == 201 and body["pull_request"]["url"] == "https://github.com/hlxin/scale/pull/100"
    assert gh.refs == {"refs/heads/contrib/10.9999-paper.1": "new-commit"} and gh.reviewers == ["mutianyou2013", "diazr04"]
    assert {t["path"] for t in gh.tree_body["tree"]} == {"graphs/catal-commons/parts/sources/10.9999-paper.1.json",
                                                        "graphs/catal-commons/parts/shared.json",
                                                        "graphs/catal-commons/rights.yaml",
                                                        "graphs/catal-commons/contributors.yaml"}
    ledger = next(t for t in gh.tree_body["tree"] if t["path"].endswith("contributors.yaml"))
    assert "github: ada" in ledger["content"] and "source: 10.9999-paper.1" in ledger["content"]   # the leaderboard's credit
    pr = gh.pulls[0]
    assert pr["title"].startswith("catal-commons: add ") and "Contributed by @ada" in pr["body"]
    assert "in_copyright" in pr["body"] and "quotes withheld" in pr["body"]
    st, body, _ = req("/contribute/check")                                    # now it is proposed in an open pull request
    assert st == 200 and body["proposed"]["number"] == 100 and body["proposed"]["by"] == ["doi", "title_year"]
    gh.files, gh.pulls = gh.trees["new-commit"], []                           # merged: now it is on main
    st, body, _ = req("/contribute/check")
    assert st == 200 and body["already"][0]["source"] == "scale:commons/source/10.9999-paper.1"


def test_only_the_graph_the_service_curated_for_the_user_can_be_contributed(tmp_path, monkeypatch):
    gh = FakeGitHub()
    svc, h, job = finished_job(tmp_path, monkeypatch, gh)
    gh.calls.clear()                                             # the job looked its DOI up in the commons
    changed = json.loads(json.dumps(job["graph"]))
    changed["nodes"][0]["props"]["name"] = "something else"
    for graph, receipt, headers in ((changed, job["receipt"], h), (job["graph"], "forged.mac", h),
                                    (job["graph"], job["receipt"], {**h, "authorization": f"Bearer {auth.session_for(svc.cfg, 'bob')}"})):
        svc.cfg.allowlist = ["ada", "bob"]
        st, body, _ = svc.route("POST", "/contribute", {}, headers, json.dumps({"graph": graph, "receipt": receipt}).encode())
        assert st == 403, body
    assert not gh.calls


def test_a_papers_text_is_kept_only_by_its_licence_or_the_users_agreement_and_can_be_withdrawn(tmp_path, monkeypatch):
    """The archive keeps a paper in copyright (the uploaded PDF and its page texts) only when its contributor agreed;
    the agreement is listed to them, and withdrawing it removes the paper. A kept paper is curated again from its PDF
    under another schema version with nobody uploading it, and the new graph is kept beside it."""
    from scaleweb.app import recurate
    svc = Service(cfg(tmp_path, archive=str(tmp_path / "kept")), repo=REPO, run_inline=True)
    real = curate.start

    given = []

    def start(out, doi=None, pdf=None, text=None, **kw):              # the PDF's text, without PyMuPDF
        given.append(Path(pdf).read_bytes() if pdf else None)
        if text is None:
            (tmp_path / "paper.txt").write_text(TEXT, encoding="utf-8")
            text = tmp_path / "paper.txt"
        return real(out, text=text, **kw)
    monkeypatch.setattr(curate, "start", start)
    sid = "ex:pub/source/paper"
    h = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}", "content-type": "application/pdf"}
    assert svc.route("GET", "/health", {}, {}, b"")[1]["keeps_texts"] is True
    for keep, expect in (("0", None), ("1", "consent")):
        svc.client_factory = lambda: Model(curation_turns(sid, "ex:pub/paper"))
        st, body, _ = svc.route("POST", "/jobs", {"filename": "paper.pdf", "keep": keep, "attest": "1"}, h, b"%PDF-1.7 a file")
        job = svc.route("GET", f"/jobs/{body['job']}", {}, h, b"")[1]
        assert job["state"] == "done" and job["source"]["rights_class"] == "in_copyright"
        assert (job["kept"] or {}).get("because") == expect
    kept = svc.route("GET", "/kept", {}, h, b"")[1]["kept"]
    folder = tmp_path / "kept" / kept[0]["sha256"]
    assert len(kept) == 1 and kept[0]["pdf"] and (folder / "pages.txt").read_text().startswith("[page 1]")
    assert (folder / "paper.pdf").read_bytes() == b"%PDF-1.7 a file"   # the copy the contributor uploaded
    assert "graph" not in json.dumps(kept)                         # a page sees what is kept, never the text
    plan = recurate(svc, dry_run=True)
    assert plan == [] or all(p["to"] == svc.jobs.version() for p in plan)
    meta = tmp_path / "kept" / kept[0]["sha256"] / "meta.json"
    m = json.loads(meta.read_text())
    m["curations"][-1]["schema_version"] = "0.0.1"                    # curated under an older schema
    meta.write_text(json.dumps(m))
    svc.client_factory = lambda: Model(curation_turns(sid, "ex:pub/paper"))
    rows = recurate(svc)
    assert [r["state"] for r in rows] == ["done"], rows[0].get("error")
    assert given[-1] == b"%PDF-1.7 a file" and len(list((tmp_path / "kept").iterdir())) == 1   # from the kept PDF, not kept twice
    assert Path(rows[0]["graph"]).is_file()
    assert recurate(svc, dry_run=True) == []                          # now curated under the commons' version
    bob = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'bob')}"}
    svc.cfg.allowlist = ["ada", "bob"]
    assert svc.route("POST", "/kept/forget", {}, bob, json.dumps({"sha256": kept[0]["sha256"]}).encode())[0] == 404
    assert svc.route("POST", "/kept/forget", {}, h, json.dumps({"sha256": kept[0]["sha256"]}).encode())[0] == 200
    assert not folder.exists()                                       # no agreement left: the PDF and text are gone


def test_answers_credit_the_sources_they_use_once_a_person_a_day_never_the_contributor(tmp_path):
    """A signed-in query, search or question credits each commons source its answer names; a source's reach counts
    distinct (person, day) pairs and never its own contributor; nothing of the question is kept, and the login only
    as a keyed digest. /leaderboard returns the boards with that reach."""
    from scaleweb.usage import Usage
    u = Usage(tmp_path / "usage.json", "s" * 32, "scale:commons")
    answer = {"rows": [{"id": "scale:commons/paper-a/test/1", "evidence": [{"source": "scale:commons/source/paper-b"}]},
                       {"id": "scale:commons/graph/catal-commons"}, {"id": "ex:other/x/y"}]}
    assert u.sources_in(answer) == {"paper-a", "paper-b"}                  # the graph's own id is no source
    for who, day in (("ada", "2026-10-24"), ("ada", "2026-10-24"), ("ada", "2026-10-25"), ("bob", "2026-10-25")):
        u.record(who, answer, day)
    assert u.record(None, answer) == set()                                   # signed out: not counted
    assert u.reach({"paper-a": "bob", "paper-b": "carol"}) == {"paper-a": 2, "paper-b": 3}
    kept = (tmp_path / "usage.json").read_text()
    assert "ada" not in kept and "bob" not in kept and "test/1" not in kept
    assert Usage(tmp_path / "usage.json", "s" * 32, "scale:commons").reach({}) == {"paper-a": 3, "paper-b": 3}
    svc = Service(cfg(tmp_path), repo=REPO)
    st, board, _ = svc.route("GET", "/leaderboard", {}, {}, b"")
    assert st == 200 and board["with_reach"] and "scoring" in board and "recent" in board


# ------------------------------------------------------------------------------------------------- the inbox
def text_start(monkeypatch, tmp_path):
    """curate.start reads the test's text instead of the PDF (no PyMuPDF), and resolves a DOI offline."""
    real = curate.start
    meta = {"message": {"title": ["Copper catalysts for methanol synthesis"], "issued": {"date-parts": [[2026]]},
                        "type": "journal-article"}}

    def start(out, doi=None, pdf=None, **kw):
        assert pdf is None or pdf.read_bytes().startswith(b"%PDF")
        (tmp_path / "paper.txt").write_text(TEXT, encoding="utf-8")
        return real(out, text=tmp_path / "paper.txt", doi=doi, get=lambda url, h: json.dumps(meta).encode(), **kw)
    monkeypatch.setattr(curate, "start", start)


def fake_claude(quote="copper is the active phase", calls=None):
    """Claude Code in a test: it writes one claim into the folder's graph, its quote in the source's text or not."""
    def run(folder, prompt, system, cfg, bin_dir):
        if calls is not None:
            calls.append({"prompt": prompt, "system": system, "folder": folder})
        info = load_doc(folder / "source.json")
        gpath = folder / f"{info['slug']}.graph.json"
        doc = load_doc(gpath)
        sid = info["source_id"]
        doc["nodes"] = [n for n in doc["nodes"] if n["label"] != "Claim"] + [claim(sid, sid.replace("/source/", "/"), quote)]
        write_canonical(gpath, doc)
        return {"result": "One claim curated.", "num_turns": 4, "duration_ms": 60000}
    return run


def no_github(*a, **kw):
    pytest.fail("GitHub is not called without the bot's token")


def test_with_an_inbox_an_upload_waits_for_claude_code_and_the_service_curates_nothing(tmp_path):
    svc = Service(cfg(tmp_path, inbox=str(tmp_path / "inbox"), archive=str(tmp_path / "kept")), repo=REPO)
    svc.client_factory = lambda: pytest.fail("with an inbox the service's own model curates nothing")
    health = svc.route("GET", "/health", {}, {}, b"")[1]
    assert health["inbox"] is True and health["keeps_texts"] is True                 # the box to keep a paper shows
    h = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}", "content-type": "application/pdf"}
    st, body, _ = svc.route("POST", "/jobs", {"filename": "paper.pdf"}, h, b"%PDF-1.7 a file")
    assert st == 400 and "lawful access" in body["error"]                    # the statement of access still holds
    st, body, _ = svc.route("POST", "/jobs", {"filename": "Copper paper.pdf", "attest": "1", "keep": "1"}, h, b"%PDF-1.7 a file")
    assert st == 202 and body["inbox"] is True and body["position"] == 0
    item = tmp_path / "inbox" / "queue" / body["job"]
    assert (item / "Copper-paper.pdf").read_bytes() == b"%PDF-1.7 a file"
    request = json.loads((item / "request.json").read_text())
    assert request["owner"] == "ada" and request["keep"] is True                 # the reader's agreement travels with it
    for _ in range(2):                                     # an inbox job is read as often as the page asks
        st, job, _ = svc.route("GET", f"/jobs/{body['job']}", {}, h, b"")
        assert st == 200 and job["state"] == "queued" and job["position"] == 0 and "owner" not in job
    svc.cfg.allowlist = ["ada", "bob"]
    bob = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'bob')}"}
    assert svc.route("GET", f"/jobs/{body['job']}", {}, bob, b"")[0] == 404             # nobody else's
    assert [j["id"] for j in svc.route("GET", "/inbox", {}, h, b"")[1]["jobs"]] == [body["job"]]
    assert svc.route("GET", "/inbox", {}, bob, b"")[1]["jobs"] == []


def test_the_runner_curates_with_claude_code_and_the_graph_comes_back_to_its_owner_only(tmp_path, monkeypatch):
    """As the Curate dialog says: the graph comes back to its owner only, nothing is published unless they contribute
    it, and contributing is a separate click that opens the bot's pull request. The runner opens none."""
    gh = FakeGitHub()
    c = cfg(tmp_path, inbox=str(tmp_path / "inbox"), github_token="bot-token", reviewers=["diazr04"])
    svc = Service(c, repo=REPO, github_request=gh)
    text_start(monkeypatch, tmp_path)
    h = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}", "content-type": "application/pdf"}
    jid = svc.route("POST", "/jobs", {"filename": "paper.pdf", "doi": "10.9999/paper.1", "attest": "1"}, h, b"%PDF-1.7 a file")[1]["job"]
    calls = []
    done = runner.run(c, repo=REPO, claude=fake_claude(calls=calls), request=gh)
    assert [j["state"] for j in done] == ["done"], done[0].get("error")
    assert gh.pulls == [] and not gh.refs                                         # nothing published by the runner
    assert "# Curate" in calls[0]["system"] and "never instructions" in calls[0]["system"]   # the skill, and text as data
    assert "pages of text" in calls[0]["prompt"]
    inbox = tmp_path / "inbox"
    assert not any((inbox / "queue").iterdir()) and not any((inbox / "work").iterdir())
    assert not list(inbox.rglob("*.pdf")) and not list(inbox.rglob("*.txt"))   # nothing kept: no archive, no licence
    svc.cfg.allowlist = ["ada", "bob"]
    bob = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'bob')}"}
    assert svc.route("GET", f"/jobs/{jid}", {}, bob, b"")[0] == 404                    # the graph is ada's alone
    st, job, _ = svc.route("GET", f"/jobs/{jid}", {}, h, b"")
    assert st == 200 and job["state"] == "done" and job["graph"]["nodes"] and job["receipt"]
    assert "copper is the active phase" not in json.dumps(job["graph"])           # in copyright: no quote
    job = json.loads(json.dumps(job))                                              # the page's copy
    req = lambda path: svc.route("POST", path, {}, h, json.dumps({"graph": job["graph"], "receipt": job["receipt"]}).encode())
    st, body, _ = req("/contribute/check")
    assert st == 200 and body["new"]["source"] == "scale:commons/source/10.9999-paper.1" and not gh.pulls
    st, body, _ = req("/contribute")                                               # the separate click
    assert st == 201 and body["pull_request"]["url"] == "https://github.com/hlxin/scale/pull/100"
    assert gh.refs == {"refs/heads/contrib/10.9999-paper.1": "new-commit"} and gh.reviewers == ["diazr04"]
    assert "Contributed by @ada" in gh.pulls[0]["body"]


def test_a_graph_that_never_checks_fails_its_job_and_its_pdf_is_deleted_too(tmp_path, monkeypatch):
    c = cfg(tmp_path, inbox=str(tmp_path / "inbox"))
    svc = Service(c, repo=REPO)
    text_start(monkeypatch, tmp_path)
    h = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}", "content-type": "application/pdf"}
    jid = svc.route("POST", "/jobs", {"filename": "paper.pdf", "attest": "1"}, h, b"%PDF-1.7 a file")[1]["job"]
    calls = []
    done = runner.run(c, repo=REPO, claude=fake_claude("gold is the active phase", calls), request=no_github)
    assert done[0]["state"] == "failed" and f"after {runner.FIX_ROUNDS} rounds" in done[0]["error"]
    assert len(calls) == 1 + runner.FIX_ROUNDS and "still has 1 problems" in calls[1]["prompt"]   # the errors go back
    assert svc.route("GET", f"/jobs/{jid}", {}, h, b"")[1]["state"] == "failed"
    assert not list((tmp_path / "inbox").rglob("*.pdf"))


def test_an_open_paper_is_kept_and_another_only_when_its_owner_ticks_the_box(tmp_path, monkeypatch):
    """The archive's rules, as the page says: a paper under an open licence is kept always, any other only when its
    owner ticked the box (listed to them, and withdrawn on their word), and the rest is deleted when the job ends."""
    c = cfg(tmp_path, inbox=str(tmp_path / "inbox"), archive=str(tmp_path / "kept"))
    svc = Service(c, repo=REPO)
    real = curate.start
    licences = {"10.9999/open.1": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}]}

    def start(out, doi=None, pdf=None, **kw):               # each paper its own text (the archive keys papers by it)
        text = tmp_path / f"{doi.replace('/', '-')}.txt"
        text.write_text(TEXT + f"\n[page 3]\nThis is {doi}.\n", encoding="utf-8")
        meta = {"message": {"title": [f"Copper catalysts {doi}"], "issued": {"date-parts": [[2026]]},
                            "type": "journal-article", "license": licences.get(doi, [])}}
        return real(out, text=text, doi=doi, get=lambda url, h: json.dumps(meta).encode(), **kw)
    monkeypatch.setattr(curate, "start", start)
    h = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}", "content-type": "application/pdf"}
    jobs = {}
    for doi, keep in (("10.9999/open.1", "0"), ("10.9999/closed.1", "0"), ("10.9999/closed.2", "1")):
        jobs[doi] = svc.route("POST", "/jobs", {"filename": "paper.pdf", "doi": doi, "attest": "1", "keep": keep}, h,
                              f"%PDF-1.7 {doi}".encode())[1]["job"]
    done = {j["id"]: j for j in runner.run(c, repo=REPO, claude=fake_claude(), request=no_github)}
    assert {j["state"] for j in done.values()} == {"done"}
    assert done[jobs["10.9999/open.1"]]["kept"]["because"] == "open_licence"
    assert done[jobs["10.9999/closed.1"]]["kept"] is None
    assert done[jobs["10.9999/closed.2"]]["kept"]["because"] == "consent"
    assert len(list((tmp_path / "kept").iterdir())) == 2 and not list((tmp_path / "inbox").rglob("*.pdf"))
    kept = svc.route("GET", "/kept", {}, h, b"")[1]["kept"]
    assert [k["doi"] for k in kept] == ["10.9999/closed.2"] and kept[0]["pdf"]   # the one kept on ada's word
    assert svc.route("POST", "/kept/forget", {}, h, json.dumps({"sha256": kept[0]["sha256"]}).encode())[0] == 200
    assert len(list((tmp_path / "kept").iterdir())) == 1                          # withdrawn: deleted


def test_claude_code_runs_confined_and_never_sees_a_token(tmp_path, monkeypatch):
    c = cfg(tmp_path, inbox=str(tmp_path / "inbox"), github_token="bot-token")
    cmd = runner.claude_command(c, "the brief", "the skill")
    assert "--restricted" in cmd and cmd[cmd.index("--permission-prompts") + 1] == "none"
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk" and "--strict-mcp-config" in cmd
    allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
    assert [a for a in allowed if a.startswith("Bash")] == ["Bash(scale source check:*)", "Bash(scale graph describe:*)"]
    assert set(allowed) - {"Read", "Write", "Edit", "Glob", "Grep"} == {a for a in allowed if a.startswith("Bash")}
    sandbox = json.loads(cmd[cmd.index("--settings") + 1])["sandbox"]
    assert sandbox["enabled"] is True and sandbox["autoAllowBashIfSandboxed"] is False   # no other command runs on its own
    for k in ("SCALE_WEB_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN", "SCALE_WEB_SECRET", "GITHUB_CLIENT_SECRET"):
        monkeypatch.setenv(k, "a secret")
    env = runner.claude_env(tmp_path / "bin")
    assert "a secret" not in env.values() and env["PATH"].split(os.pathsep)[0] == str(tmp_path / "bin")
    scale = runner.scale_bin(tmp_path) / "scale"                 # Claude Code's `scale` is the runner's scale-catal
    out = subprocess.run([str(scale), "source", "--help"], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0 and "check" in out.stdout


def test_a_pdf_dropped_into_the_queue_by_hand_is_curated_and_a_stopped_job_is_taken_again_once(tmp_path):
    inbox = Inbox(tmp_path / "inbox")
    lock = inbox.lock()
    assert lock is not None and inbox.lock() is None                         # one runner at a time
    lock.close()

    def drop(name, data=b"%PDF-1.7 by hand", settled=True):
        (inbox.queue / name).write_bytes(data)
        if settled:
            os.utime(inbox.queue / name, (time.time() - SETTLE_S - 5,) * 2)
    drop("Dropped.pdf")
    drop("notes.txt", b"x")
    drop(".DS_Store", b"x")
    assert inbox.adopt(None) == [] and not any(inbox.queue.iterdir())        # nobody to credit: set aside, queue empty
    assert sorted(p.name.split("-", 2)[2] for p in inbox.rejected.iterdir()) == ["Dropped.pdf", "notes.txt"]
    drop("Dropped.pdf")
    drop("copying.pdf", settled=False)
    ids = inbox.adopt("ada")
    assert len(ids) == 1 and [p.name for p in inbox.queue.iterdir() if p.is_file()] == ["copying.pdf"]  # still copying
    (inbox.queue / "copying.pdf").unlink()
    item = inbox.claim()
    assert item["owner"] == "ada" and (item["folder"] / "Dropped.pdf").is_file() and inbox.claim() is None
    assert inbox.recover() == [item["id"]] and inbox.view(item["id"], "ada")["state"] == "queued"   # taken again
    item = inbox.claim()
    inbox.recover()                                                           # stopped a second time: it fails
    assert inbox.view(item["id"], "ada")["state"] == "failed" and not (inbox.work / item["id"]).exists()
    assert not (inbox.queue / item["id"]).exists()


def test_a_claude_code_run_that_records_nothing_fails_and_opens_no_pull_request(tmp_path, monkeypatch):
    """The folder's graph passes the check empty, so a Claude Code run that ends at once (an unsupported model, a
    sign-in that expired) must fail the job, never curate it or open a pull request."""
    gh = FakeGitHub()
    c = cfg(tmp_path, inbox=str(tmp_path / "inbox"), github_token="bot-token")
    svc = Service(c, repo=REPO, github_request=gh)
    text_start(monkeypatch, tmp_path)
    h = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}", "content-type": "application/pdf"}
    svc.route("POST", "/jobs", {"filename": "paper.pdf", "attest": "1"}, h, b"%PDF-1.7 a file")
    calls = []

    def ends_at_once(folder, prompt, system, cfg, bin_dir):
        calls.append(prompt)
        return {"is_error": True, "num_turns": 1, "result": "API Error: 400 this version does not support this model"}
    done = runner.run(c, repo=REPO, claude=ends_at_once, request=gh)
    assert done[0]["state"] == "failed" and "recorded nothing: API Error: 400" in done[0]["error"]
    assert len(calls) == 1 and gh.pulls == [] and not gh.refs                 # no fix rounds, no pull request
    assert not list((tmp_path / "inbox").rglob("*.pdf"))


def digest_start(monkeypatch, tmp_path):
    """curate.start reads the test's text, and records the uploaded PDF's sha256 as reading the PDF would."""
    real = curate.start

    def start(out, doi=None, pdf=None, **kw):
        (tmp_path / "paper.txt").write_text(TEXT, encoding="utf-8")
        res = real(out, text=tmp_path / "paper.txt", doi=doi, **kw)
        doc = load_doc(Path(out) / res["graph"])
        next(n for n in doc["nodes"] if n["id"] == res["source_id"])["props"]["text_sha256"] = \
            hashlib.sha256(pdf.read_bytes()).hexdigest()
        write_canonical(Path(out) / res["graph"], doc)
        return res
    monkeypatch.setattr(curate, "start", start)


def test_several_uploads_at_once_wait_in_turn_and_are_each_curated_once(tmp_path, monkeypatch):
    """Four PDFs sent at the same moment are four jobs, each told its place in the queue; the runner curates them one
    after the other (one runner at a time) and deletes each PDF."""
    c = cfg(tmp_path, inbox=str(tmp_path / "inbox"))
    svc = Service(c, repo=REPO)
    digest_start(monkeypatch, tmp_path)
    h = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}", "content-type": "application/pdf"}
    with ThreadPoolExecutor(4) as pool:
        sent = list(pool.map(lambda i: svc.route("POST", "/jobs", {"filename": f"paper{i}.pdf", "attest": "1"}, h,
                                                 f"%PDF-1.7 paper {i}".encode()), range(4)))
    jobs = [body["job"] for st, body, _ in sent]
    assert [st for st, _, _ in sent] == [202] * 4 and len(set(jobs)) == 4
    assert sorted(svc.inbox.position(j) for j in jobs) == [0, 1, 2, 3]
    calls = []
    done = runner.run(c, repo=REPO, claude=fake_claude(calls=calls), request=no_github)
    assert sorted(j["id"] for j in done) == sorted(jobs) and {j["state"] for j in done} == {"done"}
    assert len(calls) == 4 and not list((tmp_path / "inbox").rglob("*.pdf"))


def test_the_same_pdf_sent_twice_by_one_reader_is_curated_once_and_another_readers_is_curated_for_them(tmp_path, monkeypatch):
    """One reader's second upload of a PDF is matched to their first by the PDF's digest before Claude Code starts. A
    graph comes back to its owner only, so another reader's upload of the same PDF is curated for them."""
    c = cfg(tmp_path, inbox=str(tmp_path / "inbox"))
    svc = Service(c, repo=REPO)
    digest_start(monkeypatch, tmp_path)
    svc.cfg.allowlist = ["ada", "bob"]
    ada = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}", "content-type": "application/pdf"}
    bob = {**ada, "authorization": f"Bearer {auth.session_for(svc.cfg, 'bob')}"}
    sent = [svc.route("POST", "/jobs", {"filename": name, "attest": "1"}, who, b"%PDF-1.7 one paper")[1]["job"]
            for name, who in (("paper.pdf", ada), ("copy.pdf", ada), ("paper.pdf", bob))]
    calls = []
    done = {j["id"]: j for j in runner.run(c, repo=REPO, claude=fake_claude(calls=calls), request=no_github)}
    first, again, bobs = (done[j] for j in sent)
    assert first["state"] == "done" and "graph" not in again and len(calls) == 2
    assert again["known"]["same_as"] == {"job": sent[0], "state": "done", "by": ["text_sha256"]}
    assert bobs["state"] == "done" and not bobs.get("known")                       # curated for bob, from his upload
    st, job, _ = svc.route("GET", f"/jobs/{sent[1]}", {}, ada, b"")
    assert st == 200 and job["known"]["same_as"]["job"] == sent[0] and "graph" not in job
    assert svc.route("GET", f"/jobs/{sent[0]}", {}, bob, b"")[0] == 404
    assert not list((tmp_path / "inbox").rglob("*.pdf"))


def test_a_source_record_for_a_cited_work_goes_back_to_claude_code(tmp_path, monkeypatch):
    """catal-commons takes one Source per contribution: a Source added for a cited work is handed back as a problem,
    and the owner's graph holds the publication's Source alone."""
    c = cfg(tmp_path, inbox=str(tmp_path / "inbox"))
    svc = Service(c, repo=REPO)
    text_start(monkeypatch, tmp_path)
    h = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}", "content-type": "application/pdf"}
    jid = svc.route("POST", "/jobs", {"filename": "paper.pdf", "doi": "10.9999/paper.1", "attest": "1"}, h, b"%PDF-1.7 a file")[1]["job"]
    calls, write = [], fake_claude()

    def cites(folder, prompt, system, cfg, bin_dir):
        calls.append(prompt)
        res = write(folder, prompt, system, cfg, bin_dir)
        info = load_doc(folder / "source.json")
        gpath = folder / f"{info['slug']}.graph.json"
        doc = load_doc(gpath)
        cited = f"{info['source_id'].replace('/source/', '/')}/source/ref12"
        doc["nodes"] = [n for n in doc["nodes"] if n["id"] != cited]
        if len(calls) == 1:                                   # first round: a Source for the work it cites
            doc["nodes"].append({"id": cited, "label": "Source", "props": {"name": "Cited work", "kind": "article",
                                                                           "origin": "reported"}})
        write_canonical(gpath, doc)
        return res
    done = runner.run(c, repo=REPO, claude=cites, request=no_github)
    assert done[0]["state"] == "done", done[0].get("error")
    assert len(calls) == 2 and "one Source per contribution" in calls[1]
    graph = svc.route("GET", f"/jobs/{jid}", {}, h, b"")[1]["graph"]
    assert sum(n["label"] == "Source" for n in graph["nodes"]) == 1


def test_kept_papers_are_curated_again_through_the_inbox_under_a_new_schema(tmp_path, monkeypatch):
    """A kept paper whose latest curation is under another schema version than catal-commons' goes through the inbox
    again, from its kept PDF, and the new graph is kept beside it; nobody uploads it twice."""
    c = cfg(tmp_path, inbox=str(tmp_path / "inbox"), archive=str(tmp_path / "kept"))
    svc = Service(c, repo=REPO)
    text_start(monkeypatch, tmp_path)
    h = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}", "content-type": "application/pdf"}
    svc.route("POST", "/jobs", {"filename": "paper.pdf", "doi": "10.9999/paper.1", "attest": "1", "keep": "1"}, h, b"%PDF-1.7 a file")
    assert runner.run(c, repo=REPO, claude=fake_claude(), request=no_github)[0]["kept"]["because"] == "consent"
    assert runner.recurate(c, repo=REPO, dry_run=True) == []                       # curated under the commons' version
    folder = next((tmp_path / "kept").iterdir())
    meta = json.loads((folder / "meta.json").read_text())
    meta["curations"][-1]["schema_version"] = "0.0.1"                              # as if the schema had moved on
    (folder / "meta.json").write_text(json.dumps(meta))
    queued = runner.recurate(c, repo=REPO)
    assert [r["from"] for r in queued] == ["0.0.1"] and queued[0]["job"]
    done = runner.run(c, repo=REPO, claude=fake_claude(), request=no_github)
    assert [j["state"] for j in done] == ["done"], done[0].get("error")
    assert (folder / "graphs" / f"{queued[0]['to']}.json").is_file() and runner.recurate(c, repo=REPO, dry_run=True) == []
    assert (folder / "paper.pdf").read_bytes() == b"%PDF-1.7 a file"              # the kept copy stays; the inbox's goes
    assert not list((tmp_path / "inbox").rglob("*.pdf"))
    assert [j["id"] for j in svc.route("GET", "/inbox", {}, h, b"")[1]["jobs"]] != [queued[0]["job"]]


def test_with_claude_code_a_question_is_answered_on_this_computer_with_the_plans_it_ran(tmp_path, monkeypatch):
    """SCALE_WEB_ASK=claude-code: Claude Code answers on the service's computer, in a folder that holds the graph alone,
    with the query commands only; the plans it wrote run again through scale query for the page, and the records they
    return go with the answer (they credit the commons sources it used). No API model is called."""
    svc = Service(cfg(tmp_path, ask="claude-code"), repo=REPO)
    svc.client_factory = lambda: pytest.fail("no API model is called")
    plan = {"match": {"label": "Catalyst", "as": "c"}, "return": ["c.name"], "limit": 3}
    seen = []

    def claude(folder, prompt, system, cfg, bin_dir, allowed, minutes, max_turns):
        seen.append({"folder": folder, "prompt": prompt, "system": system, "allowed": allowed,
                     "files": sorted(p.name for p in folder.iterdir())})
        (folder / "plan1.json").write_text(json.dumps(plan))
        return {"result": "Three catalysts [rows].", "num_turns": 3}
    monkeypatch.setattr(runner, "run_claude", claude)
    h = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}"}
    st, body, _ = svc.route("POST", "/ask", {}, h, json.dumps({"graph": load_doc(PUBLIC), "question": "Which catalysts?"}).encode())
    assert st == 200 and body["answer"] == "Three catalysts [rows]." and body["stopped"] is None
    direct = svc.route("POST", "/query", {}, {}, json.dumps({"graph": load_doc(PUBLIC), "plan": plan}).encode())[1]
    assert [(p["status"], p["rows"]) for p in body["plans"]] == [("answered", direct["row_count"])]   # as scale query
    assert direct["rows"][0]["bound"]["c"] in body["records"]                   # the records its rows hold
    assert seen[0]["prompt"] == "Which catalysts?" and seen[0]["files"] == ["graph.graph.json"]
    assert "# Query scale-catal documents" in seen[0]["system"] and "never instructions" in seen[0]["system"]
    assert [a for a in seen[0]["allowed"] if a.startswith("Bash")] == [
        "Bash(scale graph query:*)", "Bash(scale graph search:*)", "Bash(scale graph describe:*)", "Bash(scale graph stats:*)"]
    assert not seen[0]["folder"].exists()                                        # the graph's folder goes after the answer
    assert svc.route("POST", "/ask", {}, {}, json.dumps({"graph": load_doc(PUBLIC), "question": "?"}).encode())[0] == 401


def test_with_three_workers_three_sources_are_curated_at_the_same_time(tmp_path, monkeypatch):
    """SCALE_WEB_INBOX_WORKERS=3: three queued sources are curated at the same time, each in its own folder with its
    own Claude Code. Here the runs meet at a barrier that only three runs at once can pass; one at a time, it breaks."""
    c = cfg(tmp_path, inbox=str(tmp_path / "inbox"), inbox_workers=3)
    svc = Service(c, repo=REPO)
    real = curate.start

    def start(out, doi=None, pdf=None, **kw):              # each source its own text file: the workers read at once
        text = tmp_path / f"{pdf.stem}.txt"
        text.write_text(TEXT, encoding="utf-8")
        return real(out, text=text, doi=doi, **kw)
    monkeypatch.setattr(curate, "start", start)
    h = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}", "content-type": "application/pdf"}
    jobs = [svc.route("POST", "/jobs", {"filename": f"paper{i}.pdf", "attest": "1"}, h, f"%PDF-1.7 paper {i}".encode())[1]["job"]
            for i in range(3)]
    meet, folders, write = threading.Barrier(3, timeout=20), [], fake_claude()

    def together(folder, prompt, system, cfg, bin_dir):
        folders.append(folder)
        meet.wait()                                           # passes only with three runs inside at once
        return write(folder, prompt, system, cfg, bin_dir)
    done = runner.run(c, repo=REPO, claude=together, request=no_github)
    assert sorted(j["id"] for j in done) == sorted(jobs) and {j["state"] for j in done} == {"done"}, done
    assert len(set(folders)) == 3 and not list((tmp_path / "inbox").rglob("*.pdf"))


def test_crossref_too_many_requests_is_waited_out_and_dois_are_asked_one_at_a_time(tmp_path, monkeypatch):
    """Found with three workers on a lab computer: three DOIs looked up at once, and Crossref's public pool answered
    429 to one, which failed its job. The runner asks Crossref one DOI at a time and waits out a 429."""
    c = cfg(tmp_path, inbox=str(tmp_path / "inbox"), inbox_workers=3)
    svc = Service(c, repo=REPO)
    real, calls, inside = curate.start, [], []
    meta = {"message": {"title": ["Copper catalysts"], "issued": {"date-parts": [[2026]]}, "type": "journal-article"}}

    def start(out, doi=None, pdf=None, **kw):
        inside.append(1)
        try:
            assert len(inside) == 1, "two DOI lookups at once"
            calls.append(doi)
            if calls.count(doi) == 1 and doi.endswith(".1"):
                raise curate.ScaleError(f"{doi}: Crossref could not resolve it (HTTP Error 429: Too Many Requests)")
            text = tmp_path / f"{doi.replace('/', '-')}.txt"
            text.write_text(TEXT, encoding="utf-8")
            time.sleep(0.2)                                   # long enough for the workers to overlap
            return real(out, text=text, doi=doi, get=lambda url, h: json.dumps(meta).encode(), **kw)
        finally:
            inside.pop()
    monkeypatch.setattr(curate, "start", start)
    monkeypatch.setattr(runner, "CROSSREF_WAITS", (0, 0, 0))
    h = {"authorization": f"Bearer {auth.session_for(svc.cfg, 'ada')}", "content-type": "application/pdf"}
    for i in (1, 2, 3):
        svc.route("POST", "/jobs", {"filename": f"p{i}.pdf", "doi": f"10.9999/paper.{i}", "attest": "1"}, h,
                  f"%PDF-1.7 paper {i}".encode())
    done = runner.run(c, repo=REPO, claude=fake_claude(), request=no_github)
    assert {j["state"] for j in done} == {"done"}, [j.get("error") for j in done]
    assert calls.count("10.9999/paper.1") == 2                                  # the 429, then the record
