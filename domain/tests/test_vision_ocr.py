"""Values read from page images, checked against positioned OCR: the agreement rule, the evidence fields and the
two-reader check of ``scale pages`` (``scale.sourcetext``, ``scale.pagereading``), on synthetic pages."""

import json
import shutil

import pytest

from conftest import GRAPH_MANIFEST
from scale import pagereading, pgraph
from scale.sourcetext import in_region, numbers_in, region_agreement, values_in

SRC = "ex:demo/source/s1"


def W(text, box, conf=90.0):
    return {"text": text, "conf": conf, "box": box}


def test_numbers_read_with_ocr_look_alikes():
    assert numbers_in("300° C., 200 atm, 5.2 per cent") == ["300", "200", "5.2"]
    assert numbers_in("3OO atmospheres and l5 per cent", lenient=True) == ["300", "15"]
    assert numbers_in("titrated .0891 g, Fig. 3") == ["0.0891", "3"]           # a leading decimal point
    assert numbers_in("the Oxide") == []                       # letters alone stay letters


def test_region_agreement():
    words = [W("Zinc", [0.1, 0.30, 0.2, 0.32]), W("oxide", [0.21, 0.30, 0.3, 0.32]), W("16,2OO", [0.5, 0.30, 0.6, 0.32], 41),
             W("4.5", [0.7, 0.30, 0.75, 0.32]), W("87", [0.8, 0.30, 0.85, 0.32]), W("elsewhere", [0.1, 0.8, 0.3, 0.82])]
    row = in_region(words, (0.05, 0.29, 0.95, 0.33))
    assert len(row) == 5
    assert region_agreement("Zinc oxide 16,200 4.5 87", row)["agreement"] == "agree"
    got = region_agreement("Zinc oxide 16,200 4.8 87", row)
    assert got["agreement"] == "partial" and got["missing"] == ["4.8"]
    assert region_agreement("Zinc oxide 99", row)["agreement"] == "disagree"
    assert region_agreement("H₂ 61.8 % in 5 cm³", [W("H", [0, 0, 1, 1]), W("61.8", [0, 0, 1, 1]), W("5", [0, 0, 1, 1])])["agreement"] == "agree"
    assert region_agreement("Zn₇₅ 300", [W("Zn", [0, 0, 1, 1]), W("300", [0, 0, 1, 1])])["agreement"] == "partial"
    assert region_agreement("CO2 5% N2 5%", [W("CO2", [0, 0, 1, 1]), W("9%", [0, 0, 1, 1]), W("N2", [0, 0, 1, 1]), W("5%", [0, 0, 1, 1])])["agreement"] == "partial"
    assert region_agreement("a feed of 5% argon, 5% nitrogen", [W(t, [0, 0, 1, 1]) for t in "a feed of 9% argon, 5% nitrogen".split()])["agreement"] == "partial"
    assert region_agreement("2 parts Cr2O3 at 300", [W("2", [0, 0, 1, 1]), W("parts", [0, 0, 1, 1]), W("Cr203", [0, 0, 1, 1]), W("300", [0, 0, 1, 1])])["agreement"] == "agree"
    assert numbers_in("100,-\n000 space velocity") == ["100000"]
    assert region_agreement("page 1, column 30, 30 pounds of brass", [W(t, [0, 0, 1, 1]) for t in "page 1, column 30, 80 pounds of brass".split()])["agreement"] == "partial"
    assert region_agreement("30 pounds of brass", [W(t, [0, 0, 1, 1]) for t in "30 pounds of brass".split()])["agreement"] == "agree"
    assert region_agreement("group VIII", [W("group", [0, 0, 1, 1]), W("VII", [0, 0, 1, 1])])["agreement"] == "partial"
    assert region_agreement("½ to ¾", [W("1%", [0, 0, 1, 1]), W("to.%", [0, 0, 1, 1])])["agreement"] == "no_ocr"
    assert region_agreement("run 275A 300", [W("275A", [0.1, 0.3, 0.2, 0.32]), W("300", [0.3, 0.3, 0.4, 0.32])])["agreement"] == "agree"
    assert region_agreement("Zinc oxide 99", [W("Zinc", [0, 0, 1, 1])])["agreement"] == "no_ocr"


def test_the_evidence_fields_are_in_the_head_schema():
    spec = pgraph.load_spec(GRAPH_MANIFEST)
    f = spec["evidence"]["fields"]
    assert {"reading", "region", "transcription", "agreement", "second_reading"} <= set(f)
    assert f["agreement"]["values"] == ["agree", "partial", "disagree", "no_ocr"]


def test_every_reading_of_a_printed_value_backs_it():
    def has(text, x):
        return any(abs(v - x) <= 1e-9 * max(1, abs(x)) for v in values_in(text))
    assert has("0,305", 0.305) and has("501,8", 501.8) and has("16,200", 16200)
    assert has("heat 24 250 kcal", 24250) and has("1.685 mm", 1685) and has("1.685 mm", 1.685) and has("1.234.567", 1234567)
    assert has("K = 2.07 × 10⁻⁵", 2.07e-5) and has("4,46 .10-5", 4.46e-5) and has("1×10⁴", 1e4) and has("2,316.10⁻⁴", 2.316e-4)
    assert has("0.5-0.6 X 10-2 cm2/sec", 0.005) and has("0.5-0.6 X 10-2 cm2/sec", 0.006)
    assert has("only 2:2 and 3.1 grams", 2.2)
    assert has("Kp [× 10⁻⁵] | 60.6 | 17.8", 6.06e-4) and has("Kp × 10^5: 60.6", 6.06e-4)
    assert has("½ year", 0.5) and has("1½ h", 1.5)
    assert numbers_in("0,305 and 0,017") == ["0.305", "0.017"]
    assert numbers_in("5·2 per cent") == ["5.2"] and numbers_in("about 1·10⁴") == ["1", "10", "4"]
    assert numbers_in("CO × H₂²") == ["2", "2"]
    assert numbers_in("Mg(NO₃)₂.6H₂O") == ["3", "2", "6", "2"] and numbers_in("Cu(NO3)2.3H2O") == ["3", "2", "3", "2"]
    assert numbers_in("Fig. 4, 350 °C") == ["4", "350"] and numbers_in("10, 000", lenient=True) == ["10000"]
    assert numbers_in("1200 Nm³/hr, H₂ 3,14 . 10²/m, 8 × 10⁻⁴") == numbers_in("1200 Nm3/hr, H2 3,14 . 10^2/m, 8 X 10-4")


@pytest.fixture()
def cur(tmp_path):
    """A pages folder with one source's cached words of page 3 (synthetic: OCR reads 180 as "l8O") and an empty
    region OCR cache, so that the check reads only these words."""
    pages = tmp_path / "pages"
    (pages / "s1/regions").mkdir(parents=True)
    (pages / "s1/p3.words.json").write_text(json.dumps({"page": 3, "text_layer": [], "ocr": [
        W("run", [0.1, 0.40, 0.15, 0.42]), W("4", [0.16, 0.40, 0.18, 0.42]), W("300", [0.3, 0.40, 0.35, 0.42]),
        W("l8O", [0.4, 0.40, 0.45, 0.42], 30), W("5.2", [0.5, 0.40, 0.55, 0.42])]}))
    region = [0.05, 0.39, 0.95, 0.43]
    (pages / f"s1/regions/{pagereading.region_key(3, region)}.json").write_text("[]")
    return pages, region


def frag(region, transcription, agreement=None, value=180, second=None):
    ev = {"source": SRC, "locator": "p. 3, Table II, run 4", "kind": "table", "reading": "vision_ocr",
          "region": region, "transcription": transcription}
    if agreement:
        ev["agreement"] = agreement
    if second:
        ev["second_reading"] = second
    return {"source": "s1", "nodes": [{"id": "ex:demo/s1/test/run-4", "label": "CatalyticTest", "props": {
        "pressure": {"status": "present", "value": value, "unit": "atm"}, "evidence": [ev]}}], "links": []}


def test_vision_evidence_is_confirmed_by_ocr(cur):
    pages, region = cur
    assert pagereading.check(frag(region, "run 4  300  180  5.2", "agree"), pages) == []   # OCR reads "l8O" as 180


def test_the_agreement_is_the_tools_not_the_curators(cur):
    pages, region = cur
    errs = pagereading.check(frag(region, "run 4  300  180  5.2", "disagree"), pages)
    assert any("the tool computes 'agree'" in e for e in errs)


def test_an_unconfirmed_reading_needs_a_matching_second_reading(cur):
    pages, region = cur
    errs = pagereading.check(frag(region, "run 4  300  190  5.2", "partial", value=190), pages)
    assert any("independent second reading" in e for e in errs)
    assert pagereading.check(frag(region, "run 4  300  190  5.2", "partial", value=190, second="4 300 190 5.2"), pages) == []
    errs = pagereading.check(frag(region, "run 4  300  190  5.2", "partial", value=190, second="4 300 180 5.2"), pages)
    assert any("does not give the numbers" in e for e in errs)


def test_every_value_is_in_a_transcription_or_quote(cur):
    pages, region = cur
    errs = pagereading.check(frag(region, "run 4  300  180  5.2", "agree", value=175), pages)
    assert any("value 175 is in no transcription or quote" in e for e in errs)


def test_a_negative_value_is_backed_by_its_printed_number(cur):
    pages, region = cur
    assert pagereading.check(frag(region, "run 4  300  180  5.2", "agree", value=-180), pages) == []


def test_a_value_printed_in_words_needs_no_printed_number(cur):
    pages, region = cur
    f = frag(region, "run 4  300  180  5.2", "agree", value=1)
    assert any("value 1 is in no transcription" in e for e in pagereading.check(f, pages))
    f["nodes"][0]["props"]["pressure"]["as_reported"] = "atmospheric pressure"
    assert pagereading.check(f, pages) == []


def test_an_agreement_from_another_ocr_engine_is_a_warning(cur):
    pages, region = cur
    f = frag(region, "run 4  300  180  5.2", "partial")          # recorded elsewhere; the OCR here reads "agree"
    assert any("the tool computes 'agree'" in e for e in pagereading.check(f, pages))   # no warnings list: an error
    warns = []
    pagereading.check(f, pages, warnings=warns)
    assert any("does not record" in w for w in warns)             # no engine recorded: the recorded agreement stands
    f["ocr_engines"] = ["None"]                                    # the engines of the cached words here
    warns = []
    assert any("the tool computes 'agree'" in e for e in pagereading.check(f, pages, warnings=warns)) and not warns
    f["ocr_engines"] = ["tesseract 9.9 (eng); pymupdf 9.9"]
    warns = []
    pagereading.check(f, pages, warnings=warns)
    assert any("tesseract 9.9" in w for w in warns)


def test_agree_records_the_ocr_engines(cur, tmp_path):
    from scale.cli import main
    pages, region = cur
    p = tmp_path / "s1.json"
    p.write_text(json.dumps(frag(region, "run 4  300  180  5.2")))
    assert main(["pages", "agree", str(p), "--pages", str(pages)]) == 0
    got = json.loads(p.read_text())
    assert got["ocr_engines"] == ["None"] and got["nodes"][0]["props"]["evidence"][0]["agreement"] == "agree"


def test_a_second_reader_gets_the_region_not_the_transcription(cur, tmp_path, capsys):
    """`pending` lists one item per region (never the first transcription); `merge-second` puts the readings on the
    evidence by region id; `check` then passes, and fails (exit 1) on a reading that does not match."""
    from scale.cli import main
    pages, region = cur
    doc = frag(region, "run 4  300  190  5.2", value=190)
    doc["nodes"].append({"id": "ex:demo/s1/test/run-4b", "label": "CatalyticTest", "props": {
        "temperature": {"status": "present", "value": 300, "unit": "°C"},
        "evidence": [dict(doc["nodes"][0]["props"]["evidence"][0], transcription="run 4  300")]}})
    p = tmp_path / "doc.json"
    p.write_text(json.dumps(doc))
    assert main(["pages", "agree", str(p), "--pages", str(pages)]) == 0
    capsys.readouterr()
    assert main(["pages", "pending", str(p), "--pages", str(pages), "--no-crops"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["pending"] == 1 and "190" not in json.dumps(out)
    item = out["regions"][0]
    assert item["region_id"] == pagereading.region_id(SRC, 3, region) and item["keys"] == ["ex:demo/s1/test/run-4#0"]
    with pytest.raises(SystemExit) as e:                                         # waiting for its second reading
        main(["pages", "check", str(p), "--pages", str(pages)])
    assert e.value.code == 1
    second = tmp_path / "second.json"
    second.write_text(json.dumps({item["region_id"]: "4 300 180 5.2"}))
    with pytest.raises(SystemExit) as e:
        main(["pages", "check", str(p), "--pages", str(pages), "--second", str(second)])
    assert e.value.code == 1 and "does not give the numbers" in capsys.readouterr().out
    second.write_text(json.dumps({item["region_id"]: "4 300 190 5.2"}))
    assert main(["pages", "merge-second", str(p), str(second)]) == 0
    capsys.readouterr()
    assert main(["pages", "check", str(p), "--pages", str(pages)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_a_figure_point_needs_a_second_reading_within_its_tolerance(cur):
    pages, region = cur
    f = frag(region, "curve A at 300: about 42", "no_ocr", value=42)
    f["nodes"][0]["props"]["evidence"][0]["kind"] = "figure"
    assert any("independent second reading" in e for e in pagereading.check(f, pages))
    f["nodes"][0]["props"]["evidence"][0]["second_reading"] = "300 °C, 43.5 %"
    assert pagereading.check(f, pages) == []                      # 43.5 is within 5 % of 42
    f["nodes"][0]["props"]["evidence"][0]["second_reading"] = "300 °C, 47 %"
    assert any("does not give the numbers" in e for e in pagereading.check(f, pages))


def test_import_keeps_the_words_already_there_unless_overwrite(cur, tmp_path):
    pages, region = cur
    other = tmp_path / "other"
    (other / "s1/regions").mkdir(parents=True)
    (other / "s1/p3.words.json").write_text(json.dumps({"page": 3, "text_layer": [], "ocr": [], "ocr_engine": "x"}))
    (other / "s1/p4.words.json").write_text(json.dumps({"page": 4, "text_layer": [], "ocr": []}))
    (other / "s1/regions/p4_0.000_0.000_1.000_1.000.json").write_text("[]")
    got = pagereading.import_words(other, pages)
    assert got["copied"] == 2 and got["kept"] == 1
    assert json.loads((pages / "s1/regions/p4_0.000_0.000_1.000_1.000.json").read_text()) == {"ocr_engine": None, "words": []}
    assert "ocr_engine" not in json.loads((pages / "s1/p3.words.json").read_text())
    assert pagereading.import_words(other, pages, overwrite=True)["copied"] == 3
    assert json.loads((pages / "s1/p3.words.json").read_text())["ocr_engine"] == "x"


def test_a_reading_names_its_page_region_and_source(cur):
    pages, region = cur
    f = frag(region, "run 4  300  180  5.2", "agree")
    ev = f["nodes"][0]["props"]["evidence"][0]
    ev["locator"] = "Table II"
    assert any("starts with the PDF page" in e for e in pagereading.check(f, pages))
    ev["locator"], ev["region"] = "p. 3", [0.5, 0.4, 0.2, 0.42]
    assert any("needs region" in e for e in pagereading.check(f, pages))
    ev["region"] = region
    ev["locator"] = "p. 4"
    assert any("no page words for" in e for e in pagereading.check(f, pages))
    assert pagereading.source_key("ex:demo/source/10.1021-ie50228a016") == "10.1021-ie50228a016"


def test_render_and_region_read_a_pdf(tmp_path):
    """On a real PDF: render writes page images and positioned words with the OCR engine, refuses another PDF for
    the same source, and a region crop is read by OCR (needs pymupdf and tesseract; skipped without them).

    CI does not cover this path: its test jobs install the `dev` extra only, without pymupdf (the `pdf` extra) or
    tesseract, so this test is skipped there. Run it locally where tesseract is installed:
    `uv run --extra dev --extra pdf pytest domain/tests/test_vision_ocr.py`."""
    fitz = pytest.importorskip("pymupdf")
    if not shutil.which("tesseract"):
        pytest.skip("tesseract is not installed")
    pdf = tmp_path / "s1.pdf"
    d = fitz.open()
    page = d.new_page()
    page.insert_text((72, 200), "Run 4   300   180   5.2", fontsize=18)
    d.save(pdf)
    pages = tmp_path / "pages"
    got = pagereading.render(pdf, SRC, pages)
    assert got["pages"] == 1 and (pages / "s1/p1.png").exists()
    words = json.loads((pages / "s1/p1.words.json").read_text())
    assert words["ocr_engine"].startswith("tesseract") and "180" in " ".join(w["text"] for w in words["text_layer"])
    h = page.rect.height
    box = [0.05, 150 / h, 0.95, 215 / h]
    res = pagereading.region(pages, SRC, 1, box, transcription="Run 4 300 180 5.2")
    assert res["agreement"]["agreement"] == "agree" and (pages / "s1/crops").is_dir()
    other = tmp_path / "other.pdf"
    d2 = fitz.open()
    d2.new_page().insert_text((72, 72), "another source")
    d2.save(other)
    with pytest.raises(Exception, match="holds the pages of"):
        pagereading.render(other, SRC, pages)


def test_every_record_of_one_pdf_is_compared_with_its_digest(tmp_path):
    """Two sources' records name one PDF: once it has been read for the first (whose digest it has), the second, which
    records another digest, is still refused; the digest is cached, the comparison is not."""
    import hashlib
    import json as _json
    from scale import pagereading
    from scale.util import ScaleError as _ScaleError
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 a paper")
    good = hashlib.sha256(pdf.read_bytes()).hexdigest()
    pages = tmp_path / "pages"
    for sid, digest in (("ex:t/source/a", good), ("ex:t/source/b", "0" * 64)):
        d = pagereading.folder(pages, sid)
        d.mkdir(parents=True)
        (d / "source.json").write_text(_json.dumps({"pdf": str(pdf), "sha256": digest}))
    assert pagereading.pdf_of(pages, "ex:t/source/a") == pdf
    with pytest.raises(_ScaleError, match="sha256 differs"):
        pagereading.pdf_of(pages, "ex:t/source/b")

