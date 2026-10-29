"""The same-source check of a downloaded PDF (file_pdf): the source's own DOI printed in a PDF of 3+ pages proves it
even when the title cannot be matched (another language, a font no reader decodes), a longer DOI that merely starts
with it does not, and pages that are only images are rejected with that reason (fetch-corpus' accept_pdf.py files
such a PDF once someone has looked at it).

    python -m pytest tests          (from the skill folder; standard library, PyMuPDF and pytest)
"""
import json
import os
import struct
import sys
import zlib
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

fitz = pytest.importorskip("fitz")

TITLE = "Prospects for the application of methanation technologies for synthetic renewable methane"


def noise_png(n=160):
    """An incompressible picture, so a test PDF passes the 50 KB size floor."""
    raw = b"".join(b"\x00" + os.urandom(n * 3) for _ in range(n))
    chunk = lambda kind, data: (struct.pack(">I", len(data)) + kind + data
                                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_pdf(path, first_page_text, pages=3):
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        if i == 0 and first_page_text:
            page.insert_text((72, 72), first_page_text, fontsize=11)
        page.insert_image(fitz.Rect(72, 200, 400, 528), stream=noise_png())
    doc.save(str(path))
    return path


@pytest.fixture()
def project(tmp_path):
    from _common import Project
    from _ledger import Ledger
    proj = Project(tmp_path / "project")
    (proj.scr / "t").mkdir(parents=True, exist_ok=True)
    (proj.scr / "t" / "config.json").write_text(json.dumps({"topic": "Test topic", "slug": "t"}))
    led = Ledger(proj)
    for pid, doi in ((1, "10.31548/energiya3(73).2024.107"), (2, "10.15376/biores.21.2.wang"), (3, "10.1000/scan.3")):
        led.x("INSERT INTO sources (id, key, doi, title, authors, year, journal, doc_type, access_type, license) "
              "VALUES (?,?,?,?,?,?,?,?,?,?)", (pid, doi, doi, TITLE, json.dumps(["A. Author"]), 2024, "J. Test",
                                               "article", "OA", "cc-by"))
        led.set_topic(pid, "t", in_scope=1, relevance=4)
        led.add_dois(pid, [doi])
    return proj, led


def entry():
    return {"src": "test", "version": "publishedVersion", "access": "OA", "license": "cc-by", "url": "https://x.test/1"}


def test_the_exact_doi_is_found_and_a_longer_one_is_not():
    from _pdf import doi_printed
    assert doi_printed("10.1038/s41598-022-12264-8", "Scientific Reports | https://doi.org/10.1038/s41598-022-12264-8 www")
    assert doi_printed("10.1038/S41598-022-12264-8", "doi: 10.1038/s41598-022-\n12264-8.")      # case, line break
    assert not doi_printed("10.15376/biores.21.2.Wang", "DOI: 10.15376/biores.21.2.Wang2")
    assert not doi_printed("10.1000/abc", "") and not doi_printed(None, "10.1000/abc")


def test_a_title_in_another_language_passes_on_its_printed_doi(project, tmp_path):
    from _download import file_pdf
    proj, led = project
    pdf = make_pdf(tmp_path / "a.pdf", "Perspektyvy zastosuvannia tekhnolohii metanatsii\nDOI 10.31548/energiya3(73).2024.107")
    out, why = file_pdf(proj, led, led.get(1), entry(), pdf, "open")
    assert out == "valid_pdf", why
    assert led.get(1)["downloaded"] == 1
    assert led.topics_of(1)[0]["path"] == "sources/t/files/OA/1.pdf"


def test_a_longer_doi_or_a_short_notice_is_still_the_wrong_source(project, tmp_path):
    from _download import file_pdf
    proj, led = project
    out, why = file_pdf(proj, led, led.get(2), entry(), make_pdf(tmp_path / "b.pdf", "Round bamboo buildings\n"
                                                                 "DOI: 10.15376/biores.21.2.Wang2"), "open")
    assert out == "wrong_paper" and "title_match" in why
    out, why = file_pdf(proj, led, led.get(1), entry(), make_pdf(tmp_path / "c.pdf", "Correction to an article\n"
                                                                 "DOI 10.31548/energiya3(73).2024.107", pages=1), "open")
    assert out == "wrong_paper"


def test_pages_that_are_images_are_rejected_with_that_reason(project, tmp_path):
    from _download import file_pdf
    proj, led = project
    out, why = file_pdf(proj, led, led.get(3), entry(), make_pdf(tmp_path / "d.pdf", ""), "open")
    assert out == "wrong_paper" and why.startswith("no text layer"), why
    kept = why.split(" kept at ")[1]
    assert kept.startswith(".scripts/rejected/wrong_paper/3_") and (proj.root / kept).is_file()
    assert led.get(3)["downloaded"] == 0
