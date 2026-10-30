"""Elsevier's open articles come through Elsevier's article API (ScienceDirect blocks scripted clients): an open source
with an Elsevier DOI is asked of the API first when a developer key is set, the key goes in a header to the API's own
host only (never to another host a redirect leads to) and is never logged, a one-page reply is no full text, and a
refusal (429: the rate or the week's quota; 401, 403: the key) ends the route for the run. No network: the API is a
stand-in.

    python -m pytest tests          (from the skill folder; needs index-sources beside it)
"""
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
INDEX = HERE.parents[1] / "index-sources" / "scripts"
sys.path.insert(0, str(INDEX))
sys.path.insert(0, str(SCRIPTS))

KEY = "test-key-0123456789"
DOI = "10.1016/j.example.2024.101"


def source(**f):
    return {"id": 7, "doi": DOI, "title": "Copper nanocubes reduce CO2 to ethylene", "access_type": "OA",
            "license": "cc-by", "versions": [], **f}


@pytest.fixture()
def proj(tmp_path):
    from _common import Project
    import download_open as D
    D.ELSEVIER_OFF.clear()
    yield Project(tmp_path / "project")
    D.ELSEVIER_OFF.clear()


def test_an_open_elsevier_source_is_asked_of_the_api_first_and_only_with_a_key():
    import download_open as D
    from _download import is_blocked
    first = D.routes(source(), {"OA", "OA+ND"}, {"scopus": KEY})[0]
    assert first["src"] == "elsevier_api" and first["url"].startswith("https://api.elsevier.com/content/article/doi/")
    assert first["headers"] == {"X-ELS-APIKey": KEY}
    for p, selected, keys in ((source(), {"OA"}, {}),                            # no key
                              (source(access_type="Paywalled"), {"OA", "Paywalled"}, {"scopus": KEY}),
                              (source(), {"OA+ND"}, {"scopus": KEY}),            # an access type not fetched
                              (source(doi="10.1021/acs.example.1"), {"OA"}, {"scopus": KEY})):
        assert all(e["src"] != "elsevier_api" for e in D.routes(p, selected, keys))
    assert not is_blocked("api.elsevier.com") and is_blocked("www.sciencedirect.com")


class Reply:
    def __init__(self, status, headers=None, body=b""):
        self.status_code, self.headers, self.body = status, headers or {}, body

    def iter_content(self, n):
        for i in range(0, len(self.body), n):
            yield self.body[i:i + n]

    def close(self):
        pass


class Session:
    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def get(self, url, headers=None, **kw):
        self.sent.append((url, dict(headers or {})))
        return self.replies.pop(0)


class NoPace:
    def wait(self, host):
        pass


def test_the_key_goes_to_the_api_host_only(proj, monkeypatch):
    import _download
    monkeypatch.setattr(_download, "PACER", NoPace())
    url = f"https://api.elsevier.com/content/article/doi/{DOI}?httpAccept=application/pdf"
    s = Session([Reply(302, {"location": "https://cdn.example.org/a.pdf"}), Reply(200, {}, b"%PDF-1.4\n" + b"0" * 64)])
    monkeypatch.setattr(_download, "session", lambda: s)
    res = _download.fetch(proj, url, headers={"X-ELS-APIKey": KEY})
    assert res["kind"] == "pdf"
    assert s.sent[0][1].get("X-ELS-APIKey") == KEY and "X-ELS-APIKey" not in s.sent[1][1]
    s = Session([Reply(302, {"location": "https://www.sciencedirect.com/science/article/pii/S1"})])
    monkeypatch.setattr(_download, "session", lambda: s)
    assert _download.fetch(proj, url, headers={"X-ELS-APIKey": KEY})["kind"] == "redirect_blocked"
    assert len(s.sent) == 1                                          # the blocked host is never asked


def one_page_pdf(path):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Copper nanocubes reduce CO2 to ethylene (first page only)")
    doc.embfile_add("padding", os.urandom(80_000))                   # as large as a real first page
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path


def test_a_one_page_reply_is_no_full_text_and_the_key_is_never_logged(proj, monkeypatch):
    import download_open as D
    pdf = one_page_pdf(proj.tmp / "reply.part")
    seen = []

    def fetch(proj, url, accept=None, headers=None):
        seen.append(headers)
        return {"kind": "pdf", "path": pdf, "bytes": pdf.stat().st_size, "final_url": url, "status": 200}

    monkeypatch.setattr(D, "fetch", fetch)
    e = D.routes(source(), {"OA"}, {"scopus": KEY})[0]
    assert D.try_entry(proj, None, source(), e) == "fail" and seen == [{"X-ELS-APIKey": KEY}]
    assert not pdf.exists()                                          # the page is not kept
    log = (proj.logs / "download_attempts.jsonl").read_text()
    assert '"first_page_only"' in log and KEY not in log


def test_a_refusal_ends_the_api_route_for_the_run(proj, monkeypatch):
    import download_open as D
    calls = []

    def fetch(proj, url, accept=None, headers=None):
        calls.append(url)
        return {"kind": "http_error", "status": 429, "final_url": url}

    monkeypatch.setattr(D, "fetch", fetch)
    e = D.routes(source(), {"OA"}, {"scopus": KEY})[0]
    assert D.try_entry(proj, None, source(), e) == "api_off" and D.ELSEVIER_OFF.is_set()
    assert D.try_entry(proj, None, source(id=8), e) == "api_off" and len(calls) == 1   # not asked again
    log = (proj.logs / "download_attempts.jsonl").read_text()
    assert log.count('"api_refused"') == 1 and KEY not in log
