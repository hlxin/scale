"""The HTTP routes (standard library only, as ``scale serve``).

* ``GET  /health``                 liveness and the schema version
* ``GET  /auth/login?return=URL``  sign in with GitHub, back to the page at URL (one of the site origins)
* ``GET  /auth/callback``          GitHub's return; to the page with ``#token=…`` (allowlisted logins only)
* ``GET  /example``                the public methanol example (55 public-domain sources), built from its parts
* ``GET  /me``                     the signed-in login and what is left of today's budget
* ``POST /jobs``                   start curating: a PDF as the body (``Content-Type: application/pdf``, optional
                                   ``?doi=``), or JSON ``{"doi": …}`` or ``{"url": …}``; signed in
* ``GET  /jobs/{id}``              the job's state and log; when done, the graph (read once, then forgotten)
* ``POST /query``                  ``{"graph": doc, "plan": plan}``: ``scale query``, no model, no sign-in
* ``POST /search``                 ``{"graph": doc, "query": text, "k": n}``: ``scale search``, no sign-in
* ``POST /ask``                    ``{"graph": doc, "question": text}``: the question loop; signed in
* ``POST /contribute/check``       ``{"graph": doc, "receipt": r}``: is its source in catal-commons on main, or in an
                                   open contribution, and what adding it would change; signed in
* ``POST /contribute``             the same, then a pull request (the bot's, crediting the user) that adds it

Run it with ``python -m scaleweb`` (service/README.md). Cross-origin calls are allowed from the site origins only.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scale import __version__, commons, pgraph
from scale.api import ScaleToolkit
from scale.util import ScaleError, find_repo_root, load_doc, write_canonical

from . import agent, auth, fetch, github
from .config import Config
from .jobs import Jobs

GRAPH_MAX = 20 * 2**20            # the largest graph a query, search or question may send


def anthropic_client():
    import anthropic                                  # the service's one dependency beyond scale-catal
    return anthropic.Anthropic()


class Service:
    def __init__(self, cfg: Config, client_factory=anthropic_client, repo: Path | None = None, run_inline: bool = False,
                 github_request=github.http):
        self.cfg, self.client_factory, self.github_request = cfg, client_factory, github_request
        self.repo = Path(repo) if repo else find_repo_root()
        self.budget = auth.Budget(cfg)
        self.jobs = Jobs(cfg, self.budget, lambda: self.client_factory(), self.repo, run_inline=run_inline)
        self.kit = ScaleToolkit(workspace=tempfile.mkdtemp(prefix="scale-web-kit-"), repo=self.repo)
        self.schema_version = pgraph.load_spec(pgraph.spec_for(self.repo, None))["version"]

    # Each route returns (status, body, headers); body is a dict (JSON) or None.
    def route(self, method: str, path: str, query: dict, headers: dict, body: bytes) -> tuple[int, dict | None, dict]:
        user = auth.user_of(self.cfg, headers.get("authorization"))
        if method == "GET" and path == "/health":
            return 200, {"ok": True, "scale_catal": __version__, "schema_version": self.schema_version,
                         "sign_in": bool(self.cfg.github_client_id)}, {}
        if method == "GET" and path == "/example":
            return 200, load_doc(self.repo / "examples" / "methanol-synthesis-public"), {}
        if method == "GET" and path == "/auth/login":
            ret = query.get("return", "")
            if not auth.allowed_return(self.cfg, ret):
                return 400, {"error": "return to a page of the site only"}, {}
            return 302, None, {"Location": auth.login_url(self.cfg, ret)}
        if method == "GET" and path == "/auth/callback":
            return self._callback(query)
        if method == "GET" and path == "/me":
            if not user:
                return 401, {"error": "sign in with a GitHub account on the allowlist"}, {}
            return 200, {"login": user, "tokens_left_today": self.budget.left(), "model": self.cfg.model}, {}
        if method == "POST" and path == "/jobs":
            if not user:
                return 401, {"error": "sign in with a GitHub account on the allowlist"}, {}
            return self._submit(user, query, headers, body)
        if method == "GET" and path.startswith("/jobs/"):
            if not user:
                return 401, {"error": "sign in"}, {}
            view = self.jobs.view(path.removeprefix("/jobs/"), user)
            return (200, view, {}) if view else (404, {"error": "no such job (a finished job is read once)"}, {})
        if method == "POST" and path in ("/query", "/search", "/ask", "/contribute/check", "/contribute"):
            if len(body) > GRAPH_MAX:
                return 413, {"error": "the graph is too large for the service"}, {}
            try:
                req = json.loads(body or b"{}")
            except ValueError:
                return 400, {"error": "the body is not JSON"}, {}
            if not isinstance(req.get("graph"), dict):
                return 400, {"error": "give the graph as `graph`"}, {}
            if path == "/query":
                return 200, self.kit.call("query", {"document": req["graph"], "plan": req.get("plan") or {}}), {}
            if path == "/search":
                return self._with_file(req["graph"], lambda p, kit: (200, kit.call("search", {
                    "path": p.name, "query": str(req.get("query") or ""), "k": int(req.get("k") or 10)}), {}))
            if path.startswith("/contribute"):
                if not user:
                    return 401, {"error": "sign in to contribute"}, {}
                return self._contribute(user, req, open_pr=path == "/contribute")
            if not user:
                return 401, {"error": "sign in to ask a question (it uses the service's model)"}, {}
            refused = self.budget.take("question", user)
            if refused:
                return 429, {"error": refused}, {}
            return self._with_file(req["graph"], lambda p, kit: self._ask(p, str(req.get("question") or "")))
        return 404, {"error": "not found"}, {}

    def _callback(self, query: dict):
        state = auth.unsign(self.cfg, query.get("state", ""))
        if not state or not auth.allowed_return(self.cfg, state.get("ret", "")):
            return 400, {"error": "the sign-in expired; start again"}, {}
        try:
            login = auth.github_login(self.cfg, query.get("code", ""))
        except Exception:
            return 302, None, {"Location": state["ret"] + "#signin=failed"}
        if login.lower() not in self.cfg.allowlist:
            return 302, None, {"Location": state["ret"] + "#signin=not-allowed&login=" + urllib.parse.quote(login)}
        return 302, None, {"Location": state["ret"] + "#token=" + auth.session_for(self.cfg, login)}

    def _submit(self, user: str, query: dict, headers: dict, body: bytes):
        ctype = headers.get("content-type", "").split(";")[0].strip().lower()
        max_bytes = self.cfg.max_upload_mb * 2**20
        doi, pdf, name = None, None, None
        try:
            if ctype == "application/pdf":
                if len(body) > max_bytes:
                    return 413, {"error": f"the PDF is larger than {self.cfg.max_upload_mb} MB"}, {}
                if not body.startswith(b"%PDF"):
                    return 400, {"error": "the file is not a PDF"}, {}
                pdf, name = body, query.get("filename") or "paper.pdf"
                doi = fetch.doi_in(query.get("doi", "")) if query.get("doi") else None
            else:
                req = json.loads(body or b"{}")
                given = str(req.get("doi") or req.get("url") or "").strip()
                if not given:
                    return 400, {"error": "give a PDF, a DOI or a link"}, {}
                doi = fetch.doi_in(given)
                if req.get("url") and not doi or fetch.arxiv_pdf(given):
                    pdf, name = fetch.get_pdf(given, max_bytes), "linked.pdf"
                elif not doi:
                    return 400, {"error": "no DOI found in what was given"}, {}
        except (fetch.FetchError, ValueError) as e:
            return 400, {"error": str(e)}, {}
        except OSError as e:
            return 502, {"error": f"the link could not be fetched ({type(e).__name__}); upload the PDF instead"}, {}
        refused = self.budget.take("job", user)
        if refused:
            return 429, {"error": refused}, {}
        return 202, {"job": self.jobs.submit(user, doi=doi, pdf=pdf, filename=name)}, {}

    def _contribute(self, user: str, req: dict, open_pr: bool):
        """Is the graph's source in the commons (on main, or in an open contribution)? If not, what adding it changes,
        and with ``open_pr`` the pull request that adds it."""
        graph = req["graph"]
        entry = auth.check_receipt(self.cfg, str(req.get("receipt") or ""), user, graph)
        if entry is None:
            return 403, {"error": "only a graph this service curated for you, unchanged, can be contributed"}, {}
        if not self.cfg.github_token:
            return 503, {"error": "contributions are not set up on this service (SCALE_WEB_GITHUB_TOKEN)"}, {}
        repo = github.Repo(self.cfg.repo, self.cfg.github_token, self.cfg.commons, request=self.github_request)
        d = Path(tempfile.mkdtemp(prefix="scale-web-c-"))
        try:
            sha = repo.fetch_folder(d)
            try:
                res = commons.contribute(graph, d, entry, self.repo)
            except ScaleError as e:
                return 422, {"error": str(e)}, {}
            if res.get("already"):
                return 200, {"already": [{**h, "url": f"https://github.com/{self.cfg.repo}/blob/main/{self.cfg.commons}/{h['file']}"}
                                         for h in res["already"]]}, {}
            for pr in repo.open_contributions():
                hits = commons.find(graph, {"sources": pr["sources"]})
                if hits:
                    return 200, {"proposed": {"number": pr["number"], "url": pr["url"], "title": pr["title"],
                                              "by": hits[0]["by"]}}, {}
            preview = {k: res[k] for k in ("source", "slug", "class", "records", "shared_added",
                                           "shared_with_new_evidence", "quotes")}
            preview["files"] = sorted(f"{self.cfg.commons}/{f}" for f in res["files"])
            if not open_pr:
                return 200, {"new": preview}, {}
            refused = self.budget.take("contribution", user)
            if refused:
                return 429, {"error": refused}, {}
            title, body = self._pr_text(user, graph, entry, preview)
            try:
                pr = repo.open_pull_request(sha, f"{github.BRANCH_PREFIX}{res['slug']}", res["files"], title, body,
                                            f"{title}\n\nContributed by @{user} through the SCALE web service.",
                                            self.cfg.reviewers)
            except FileExistsError as e:
                return 409, {"error": str(e)}, {}
            return 201, {"new": preview, "pull_request": pr}, {}
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def _pr_text(self, user: str, graph: dict, entry: dict, p: dict) -> tuple[str, str]:
        src = next(n for n in graph["nodes"] if n.get("label") == "Source")["props"]
        name = src.get("title") or src.get("name") or p["slug"]
        ref = f"doi:{src['doi']}" if src.get("doi") else p["slug"]
        title = f"catal-commons: add {name[:70]}{'…' if len(name) > 70 else ''} ({ref})"
        withheld = (f"{p['quotes']['withheld']} quotes withheld as sha256 and length (the source is {p['class']}: the "
                    "commons quotes no text of a source in copyright)" if p["quotes"]["withheld"]
                    else f"every quote kept ({p['class']})")
        body = "\n".join([
            f"**What it adds.** `{p['source']}`, {name}" + (f" ({src['year']})" if src.get("year") else "")
            + (f", {ref}" if src.get("doi") else "") + f", to `{self.cfg.commons}`: {p['records']['nodes']} records and "
            f"{p['records']['links']} links in `parts/sources/{p['slug']}.json`, "
            f"{len(p['shared_added'])} new shared records and {len(p['shared_with_new_evidence'])} shared records "
            "with new evidence in `parts/shared.json`, and the source's entry in `rights.yaml`.",
            "",
            f"**Who.** Contributed by @{user} through the SCALE web service. The model ({self.cfg.model}) curated it "
            "by the curate-source skill until `scale source check` passed, every quote found in the source's text.",
            "",
            f"**Rights.** {entry.get('class')}: {entry.get('licence')} ({entry.get('basis')}); {withheld}.",
            "",
            "**Checked.** The source is not in the commons on main (by DOI, identifier, text digest or title and "
            "year) nor in an open contribution; the commons builds and validates with it (`scale graph contribute`).",
            "",
            "**For the reviewer.** Check the records against the source; the shared records it adds may duplicate "
            "ones under another id. A person approves and merges; the service never does.",
        ])
        return title, body

    def _with_file(self, graph: dict, fn):
        d = Path(tempfile.mkdtemp(prefix="scale-web-q-"))
        try:
            p = d / "graph.graph.json"
            write_canonical(p, graph)
            return fn(p, ScaleToolkit(workspace=d, repo=self.repo))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def _ask(self, path: Path, question: str):
        if not question.strip():
            return 400, {"error": "ask a question"}, {}
        res = agent.answer(path, question, self.client_factory(), self.cfg.model, 30,
                           min(200_000, self.budget.left()), repo=self.repo)
        self.budget.spend(res["tokens"])
        return 200, res, {}


def make_handler(svc: Service):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"scale-web/{__version__}"

        def _cors(self) -> dict:
            origin = self.headers.get("Origin", "").rstrip("/")
            if origin and origin in svc.cfg.site_origins:
                return {"Access-Control-Allow-Origin": origin, "Vary": "Origin",
                        "Access-Control-Allow-Headers": "Authorization, Content-Type",
                        "Access-Control-Allow-Methods": "GET, POST, OPTIONS"}
            return {}

        def _send(self, status: int, body: dict | None, headers: dict) -> None:
            data = json.dumps(body, ensure_ascii=False, default=str).encode() if body is not None else b""
            self.send_response(status)
            for k, v in {**self._cors(), **headers}.items():
                self.send_header(k, v)
            if body is not None:
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _handle(self, method: str) -> None:
            u = urllib.parse.urlparse(self.path)
            query = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            n = self.headers.get("Content-Length", "0")
            if not n.isdigit() or int(n) > svc.cfg.max_upload_mb * 2**20 + 2**20:
                return self._send(413 if n.isdigit() else 400, {"error": "the request is too large"}, {})
            body = self.rfile.read(int(n)) if int(n) else b""
            try:
                self._send(*svc.route(method, u.path, query, {k.lower(): v for k, v in self.headers.items()}, body))
            except Exception as e:                        # never a traceback or a dropped connection
                print(f"error on {method} {u.path}: {type(e).__name__}: {e}", file=sys.stderr)
                self._send(500, {"error": "the service could not complete the request"}, {})

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_OPTIONS(self):
            self._send(204, None, {})

        def log_message(self, fmt, *args):
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    return Handler


def main(argv: list[str] | None = None) -> None:
    import argparse
    p = argparse.ArgumentParser(prog="python -m scaleweb", description="The SCALE web service")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    a = p.parse_args(argv)
    svc = Service(Config.from_env())
    print(f"scale-web on {a.host}:{a.port} (scale-catal {__version__}, schema {svc.schema_version}, "
          f"{len(svc.cfg.allowlist)} allowlisted, model {svc.cfg.model})", file=sys.stderr)
    ThreadingHTTPServer((a.host, a.port), make_handler(svc)).serve_forever()
