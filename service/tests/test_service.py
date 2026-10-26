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


def test_an_allowlist_of_star_admits_any_github_account(tmp_path, monkeypatch):
    svc = Service(cfg(tmp_path), repo=REPO)
    svc.cfg.allowlist = ["*"]
    _, _, h = svc.route("GET", "/auth/login", {"return": "https://hlxin.github.io/scale/"}, {}, b"")
    state = dict(x.split("=", 1) for x in h["Location"].split("?", 1)[1].split("&"))["state"]
    monkeypatch.setattr(auth, "github_login", lambda c, code: "Eve")
    _, _, h2 = svc.route("GET", "/auth/callback", {"code": "x", "state": state}, {}, b"")
    assert h2["Location"].startswith("https://hlxin.github.io/scale/#token=")
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
    assert st == 400 and "lawful access" in body["error"]                          # no statement of access, no job
    st, body, _ = svc.route("POST", "/jobs", {"filename": "paper.pdf", "attest": "1"}, h, b"%PDF-1.7 a file")
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
    assert svc.route("POST", "/jobs", {"attest": "1"}, other, b"%PDF-1.7")[0] == 429             # today's jobs used


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
