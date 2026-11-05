"""One odd server reply must not end a download run. A redirect whose Location header is not UTF-8 (seen 2026-11-04:
byte 0xb7) made requests raise UnicodeDecodeError even with allow_redirects=False; it escaped fetch() and ended
download_open.py, and re-running hit the same paper first, so the run never advanced. Now the redirect is followed
(the raw bytes percent-encoded), fetch() returns a result whatever the reply, and download_open.py logs a route that
raises and tries the next one. No network beyond a stand-in server on 127.0.0.1.

    python -m pytest tests          (from the skill folder; needs index-sources beside it)
"""
import http.server
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "index-sources" / "scripts"))
sys.path.insert(0, str(HERE.parent / "scripts"))

PDF = b"%PDF-1.4\n% a test file\n" + b"0" * 64 + b"\n%%EOF\n"


class Handler(http.server.BaseHTTPRequestHandler):
    """http.server writes header values as latin-1, so "\xb7" goes out as the single raw byte 0xb7."""

    def do_GET(self):
        if self.path == "/bad-redirect":
            self._redirect("/files/paper\xb7one.pdf")
        elif self.path == "/bad-redirect-to-nothing":
            self._redirect("/gone\xb7")
        elif self.path == "/files/paper%B7one.pdf":
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(PDF)))
            self.end_headers()
            self.wfile.write(PDF)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture()
def server():
    from _common import PACER
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    PACER.set("127.0.0.1", 0)
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_location_url_keeps_what_requests_reads_and_encodes_the_rest():
    from _common import location_url
    assert location_url("https://example.org/a/b.pdf?x=1&y=%20") == "https://example.org/a/b.pdf?x=1&y=%20"
    assert location_url("/caf\xc3\xa9.pdf") == "/café.pdf"            # UTF-8 bytes: decoded, as requests does
    assert location_url("/paper\xb7one.pdf") == "/paper%B7one.pdf"         # any other byte: percent-encoded as it is
    assert location_url("/a%20b\xb7?q=\xe9") == "/a%20b%B7?q=%E9"
    assert location_url("/café中") == "/café中"         # already text (not latin-1): unchanged


def test_the_fake_reply_is_the_one_that_crashed_requests(server):
    import requests
    try:
        requests.Session().get(server + "/bad-redirect", allow_redirects=False, stream=True).close()
    except UnicodeDecodeError:
        return
    pytest.skip("this requests version reads such a Location header itself")


def test_fetch_follows_a_non_utf8_redirect(server, tmp_path):
    from _download import fetch
    res = fetch(SimpleNamespace(tmp=tmp_path), server + "/bad-redirect")
    assert res["kind"] == "pdf", res
    assert res["final_url"] == server + "/files/paper%B7one.pdf"
    assert Path(res["path"]).read_bytes() == PDF


def test_fetch_returns_a_result_when_that_redirect_leads_nowhere(server, tmp_path):
    from _download import fetch
    res = fetch(SimpleNamespace(tmp=tmp_path), server + "/bad-redirect-to-nothing")
    assert res == {"kind": "http_error", "status": 404, "final_url": server + "/gone%B7"}


def test_fetch_returns_a_result_even_with_a_plain_requests_session(server, tmp_path, monkeypatch):
    """Without the tolerant session (e.g. another copy of _common.py), fetch() still answers instead of raising."""
    import requests
    import _download
    monkeypatch.setattr(_download, "session", requests.Session)
    res = _download.fetch(SimpleNamespace(tmp=tmp_path), server + "/bad-redirect")
    if res["kind"] == "pdf":                       # a requests version that reads the header itself
        return
    assert res["kind"] == "network_error" and "UnicodeDecodeError" in res["error"]


# ---------------------------------------------------------------- download_open.py: one route raising
@pytest.fixture()
def project(tmp_path, monkeypatch):
    import _common
    from _ledger import Ledger
    monkeypatch.setattr(_common, "GLOBAL_DIR", tmp_path / "home")   # no real keys or EZproxy set-up
    proj = _common.Project(tmp_path / "proj")
    (proj.scr / "t").mkdir(parents=True, exist_ok=True)
    (proj.scr / "t" / "config.json").write_text(json.dumps({"topic": "Test topic", "slug": "t"}))
    led = Ledger(proj)
    versions = [{"pdf_url": f"https://repo.example.org/{n}.pdf", "access": "OA", "src": "openalex",
                 "version": "publishedVersion", "license": "cc-by"} for n in ("raises", "second")]
    led.x("INSERT INTO sources (id, key, doi, title, authors, year, journal, doc_type, access_type, license, versions) "
          "VALUES (1, '10.9999/x', '10.9999/x', 'Copper oxide reduces CO2', '[]', 2025, 'J. Test', 'article', 'OA', "
          "'cc-by', ?)", (json.dumps(versions),))
    led.set_topic(1, "t", in_scope=1, relevance=4)
    return proj, led


def run_open(proj, monkeypatch, exc):
    import download_open
    tried = []

    def fake_try_entry(proj_, led_, p, e):
        tried.append(e["url"])
        if e["url"].endswith("/raises.pdf"):
            raise exc
        return "fail"

    monkeypatch.setattr(download_open, "try_entry", fake_try_entry)
    monkeypatch.setattr(sys, "argv", ["download_open.py", "--project", str(proj.root), "--topic", "t", "--workers", "1"])
    return download_open.main(), tried


def test_download_open_logs_a_route_that_raises_and_tries_the_next(project, monkeypatch, capsys):
    proj, led = project
    bad = UnicodeDecodeError("utf-8", b"https://repo.example.org/\xb7", 25, 26, "invalid start byte")
    rc, tried = run_open(proj, monkeypatch, bad)
    assert not rc
    assert tried == ["https://repo.example.org/raises.pdf", "https://repo.example.org/second.pdf",
                     "https://doi.org/10.9999/x"]
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["outcomes"] == {"failed": 1} and out["route_errors"] == 1
    status, note = led.q("SELECT dl_status, dl_note FROM sources WHERE id = 1")[0]
    assert status == "failed" and "UnicodeDecodeError" in note and "--retry-failed" in note
    logged = [json.loads(l) for l in (proj.logs / "download_attempts.jsonl").read_text().splitlines()]
    assert [l["outcome"] for l in logged] == ["error"] and "UnicodeDecodeError" in logged[0]["reason"]


def test_download_open_still_stops_on_a_full_disk(project, monkeypatch):
    proj, led = project
    with pytest.raises(OSError):
        run_open(proj, monkeypatch, OSError(28, "No space left on device"))
    assert led.q("SELECT dl_status FROM sources WHERE id = 1")[0][0] is None     # not marked failed
