"""One publication into a scale-catal document (scale source start | check | finish; tools/curate.py), offline:
the registries are answered by a fake fetch, and the page texts come from a text file (or a PDF made here, when
PyMuPDF is installed)."""

import json

import pytest

from conftest import REPO
from scale import curate, pgraph
from scale.api import ScaleToolkit
from scale.util import ScaleError, load_doc, load_yaml, write_canonical

DOI = "10.9999/Example.2026.42"
TEXT = ("[page 1]\nResults. The copper catalyst gave 42 % selectivity to methanol at about 250 °C; the conver-\n"
        "sion did not exceed 5 %.\n\n[page 2]\nWe conclude that copper is the active phase.\n")
CROSSREF = {"message": {"title": ["Copper catalysts for <i>methanol</i><sup>1</sup> &amp; more"],
                        "author": [{"given": "Ada", "family": "Lovelace"}], "issued": {"date-parts": [[2026, 3, 1]]},
                        "container-title": ["J. Invented Catal."], "type": "journal-article", "publisher": "Nobody",
                        "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
                        "URL": "https://doi.org/10.9999/example.2026.42"}}


def fake(oa=None, pdf=b"%PDF-1.7 a file"):
    calls = []

    def get(url, headers):
        calls.append(url)
        if url.startswith(curate.CROSSREF):
            return json.dumps(CROSSREF).encode()
        if url.startswith(curate.UNPAYWALL):
            return json.dumps({"best_oa_location": oa}).encode()
        return pdf
    get.calls = calls
    return get


def test_a_doi_is_normalized_and_its_metadata_cleaned():
    for form in (DOI, f"doi:{DOI}", f"https://doi.org/{DOI}", f"http://dx.doi.org/{DOI} "):
        assert curate.normalize_doi(form) == DOI.lower()
    with pytest.raises(ScaleError, match="not a DOI"):
        curate.normalize_doi("example.org/paper")
    get = fake()
    m = curate.resolve_doi(DOI, get=get)
    assert m["title"] == "Copper catalysts for methanol & more" and m["authors"] == ["Ada Lovelace"]
    assert (m["year"], m["published_on"], m["kind"], m["venue"]) == (2026, "2026-03-01", "article", "J. Invented Catal.")
    assert curate.rights_class(m["licences"]) == "open" and m["open_access"] is None
    assert "no open-access copy was looked for" in m["notes"][0] and len(get.calls) == 1     # no address: no lookup
    assert curate.rights_class([]) == "in_copyright" and curate.rights_class(["cc0"]) == "public_domain"


def test_start_writes_a_folder_whose_graph_validates(tmp_path):
    (tmp_path / "paper.txt").write_text(TEXT, encoding="utf-8")
    res = curate.start(tmp_path / "w", doi=DOI, text=tmp_path / "paper.txt", repo=REPO, get=fake())
    w = tmp_path / "w"
    slug = "10.9999-example.2026.42"
    assert res["graph"] == f"{slug}.graph.json" and res["rights_class"] == "open" and res["pages"] == 2
    assert {p.name for p in w.iterdir()} >= {res["graph"], "source.json", "rights.yaml", "BRIEF.md", "work", ".gitignore"}
    doc = load_doc(w / res["graph"])
    g = doc["graph"]
    assert g["schema_version"] == pgraph.load_spec(pgraph.spec_for(REPO, None))["version"]
    assert g["follows_domains"] == ["catalysis"] and len(g["title"]) <= 40 and DOI.lower() in g["description"]
    src = next(n for n in doc["nodes"] if n["label"] == "Source")
    assert src["id"] == f"ex:pub/source/{slug}" and src["props"]["title"] == "Copper catalysts for methanol & more"
    assert curate.check(w, REPO)["ok"]                                     # the skeleton is valid as written
    assert load_yaml(w / "rights.yaml")["sources"][src["id"]]["class"] == "open"
    assert (w / f"work/texts/{slug}.txt").read_text().startswith("[page 1]\nResults.")
    assert "curate-corpus" in (w / "BRIEF.md").read_text()
    assert "pdfs/" in (w / ".gitignore").read_text().split()
    with pytest.raises(ScaleError, match="already holds"):
        curate.start(w, doi=DOI, text=tmp_path / "paper.txt", repo=REPO, get=fake())


def test_an_open_access_pdf_is_downloaded_only_under_an_open_licence(tmp_path):
    (tmp_path / "paper.txt").write_text(TEXT, encoding="utf-8")
    oa = {"url_for_pdf": "https://repo.example/paper.pdf", "license": "cc-by", "version": "acceptedVersion",
          "host_type": "repository"}
    res = curate.start(tmp_path / "a", doi=DOI, text=tmp_path / "paper.txt", email="curator@example.org", repo=REPO,
                       get=fake(oa))
    assert res["pdf"] == "pdfs/10.9999-example.2026.42.pdf"
    src = load_doc(tmp_path / "a" / res["graph"])["nodes"][0]["props"]
    assert src["retrieved_from"] == oa["url_for_pdf"] and src["text_version"] == "accepted_manuscript"
    res = curate.start(tmp_path / "b", doi=DOI, text=tmp_path / "paper.txt", email="curator@example.org", repo=REPO,
                       get=fake({**oa, "license": None}))
    assert res["pdf"] is None and any("states no open licence" in n for n in res["notes"])
    with pytest.raises(ScaleError, match="not a PDF"):
        curate.start(tmp_path / "c", doi=DOI, email="curator@example.org", repo=REPO, get=fake(oa, pdf=b"<html>"))


def test_check_holds_quotes_to_the_page_texts_and_finish_makes_what_can_be_shared(tmp_path):
    (tmp_path / "paper.txt").write_text(TEXT, encoding="utf-8")
    crossref = json.loads(json.dumps(CROSSREF))
    res = curate.start(tmp_path / "w", text=tmp_path / "paper.txt", doi=DOI, repo=REPO,
                       get=lambda url, h: json.dumps({**crossref, "message": {**crossref["message"], "license": []}}).encode())
    w, slug = tmp_path / "w", "10.9999-example.2026.42"
    assert res["rights_class"] == "in_copyright"
    gpath = w / res["graph"]
    doc = load_doc(gpath)
    sid = f"ex:pub/source/{slug}"

    def claim(i, quote):
        return {"id": f"ex:pub/{slug}/claim/{i}", "label": "Claim",
                "props": {"name": f"claim {i}", "statement": "Copper is the active phase.", "claim_kind": "finding",
                          "claim_status": "proposed", "origin": "reported",
                          "evidence": [{"source": sid, "locator": "p. 2", "kind": "text", "quote": quote}]}}
    doc["nodes"] += [claim(1, "copper is the active phase"), claim(2, "gold is the active phase")]
    write_canonical(gpath, doc)
    rep = curate.check(w, REPO)
    assert not rep["ok"] and any("no REPORTED_IN link" in e["message"] for e in rep["errors"])
    rep = curate.check(w, REPO, derive_links=True)                 # the links the evidence implies, then the check
    assert not rep["ok"] and [e["record"] for e in rep["errors"]] == [f"ex:pub/{slug}/claim/2"]
    assert rep["quotes_checked_against_text"]
    doc = load_doc(gpath)
    doc["nodes"] = [n for n in doc["nodes"] if not n["id"].endswith("/claim/2")]
    doc["nodes"].append(claim(3, "the conversion did not exceed 5 %"))           # across the line break "conver-\nsion"
    write_canonical(gpath, doc)
    assert curate.check(w, REPO, derive_links=True)["ok"]
    out = curate.finish(w, public=True, bundle=True, title="Copper for methanol", repo=REPO)
    assert (w / out["index"]).is_file() and (w / out["public"]["graph"]).is_file()
    b = out["bundle"]
    assert b["folder"] == "bundle/10-9999-example-2026-42_v1.0.0" and b["title"].startswith("Copper for methanol")
    m = json.loads((w / b["folder"] / "bundle.json").read_text())
    assert m["bundle_id"] == "10-9999-example-2026-42" and (w / b["folder"] / "SHA256SUMS").is_file()


def test_finish_refuses_a_graph_with_errors(tmp_path):
    (tmp_path / "p.txt").write_text(TEXT, encoding="utf-8")
    curate.start(tmp_path / "w", text=tmp_path / "p.txt", pdf=None, doi=DOI, repo=REPO, get=fake())
    g = tmp_path / "w/10.9999-example.2026.42.graph.json"
    doc = load_doc(g)
    doc["nodes"].append({"id": "ex:pub/x/claim/1", "label": "Claim", "props": {"name": "no statement"}})
    write_canonical(g, doc)
    with pytest.raises(ScaleError, match="errors: fix them first"):
        curate.finish(tmp_path / "w", repo=REPO)


def test_the_agent_tools_start_and_check_a_folder(tmp_path):
    tk = ScaleToolkit(workspace=tmp_path, repo=REPO)
    (tmp_path / "paper.txt").write_text(TEXT, encoding="utf-8")
    res = tk.call("source_start", {"text": "paper.txt", "folder": "study"})
    assert "error" not in res and res["graph"] == "paper.graph.json"
    assert tk.call("source_check", {"folder": "study"})["ok"]
    assert "error" in tk.call("source_start", {})


def test_a_pdf_is_read_into_page_texts(tmp_path):
    fitz = pytest.importorskip("fitz")
    pdf = fitz.open()
    for line in ("Results. The copper catalyst gave 42 % selectivity to methanol.", "We conclude that copper is active."):
        pdf.new_page().insert_text((72, 72), line)
    pdf.save(tmp_path / "Paper One.pdf")
    res = curate.start(tmp_path / "w", pdf=tmp_path / "Paper One.pdf", repo=REPO)
    assert res["pages"] == 2 and res["pdf"] == "pdfs/paper-one.pdf"
    src = load_doc(tmp_path / "w" / res["graph"])["nodes"][0]["props"]
    assert len(src["text_sha256"]) == 64 and src["retrieved_from"] == "Paper One.pdf"
    assert "[page 2]\nWe conclude" in (tmp_path / "w/work/texts/paper-one.txt").read_text()
