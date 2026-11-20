"""Value-to-evidence checks (tools/valuecheck.py; `scale review values`): a model that misreads a table writes a
record with a genuine quote and a wrong number. The verbatim check passes it; this check must not."""

import json
import subprocess
import sys

from conftest import REPO
from scale import valuecheck as vc
from scale.util import load_doc

ROW = "350 150 5000 17.9"          # a table row: temperature, pressure, space velocity, conversion


def _doc(props: dict) -> dict:
    ev = [{"source": "ex:t/source/s", "locator": "p. 2, Table I", "kind": "table", "quote": ROW}]
    return {"graph": {"title": "t"}, "nodes": [{"id": "ex:t/test/1", "label": "CatalyticTest",
                                                  "props": {"name": "run 1", "evidence": ev, **props}}], "links": []}


def _one(props: dict) -> dict:
    res = vc.check_document(_doc(props))
    assert res["values"] == 1
    return res["rows"][0]


def test_a_correct_table_value_is_backed():
    assert _one({"conversion": {"status": "present", "value": 17.9, "unit": "%", "as_reported": "17.9"}})["outcome"] == "ok"


def test_a_shifted_column_is_flagged_although_its_quote_is_verbatim():
    # a small model put the space velocity's neighbour (the pressure) in the conversion and typed it as printed
    row = _one({"conversion": {"status": "present", "value": 15.0, "unit": "%", "as_reported": "15.0"}})
    assert row["outcome"] == "flag" and row["checks_failed"] == ["value_vs_evidence"]


def test_a_mistyped_value_is_flagged_against_its_own_printed_text():
    row = _one({"conversion": {"status": "present", "value": 1.79, "unit": "%", "as_reported": "17.9"}})
    assert row["outcome"] == "flag" and "value_vs_as_reported" in row["checks_failed"]


def test_printed_forms_are_read_as_print_has_them():
    for value, printed in [(3560, "3, 560"), (-28085, "−28,085"), (390, "39O°C"), (250, "Two hundred and fifty cc"),
                           (125000000, "125,000,000 cubic feet/day"), (2.07e-5, "2.07 × 10⁻⁵")]:
        assert any(vc._close(abs(value), r) for r in vc.readings(printed)), printed


def test_what_no_tool_can_check_goes_to_a_person():
    fig = _one({"yield": {"status": "present", "value": 6.1, "unit": "%", "as_reported": "plotted point, Figure 6"}})
    words = vc.check_value({"status": "present", "value": 1, "unit": "h", "as_reported": "about an hour"},
                           [{"source": "s", "locator": "p. 1", "kind": "text", "quote": "reduced for about an hour"}])
    assert fig["outcome"] == words["outcome"] == "unverifiable"
    withheld = vc.check_value({"status": "present", "value": 5, "unit": "h"},
                              [{"source": "s", "locator": "p. 1", "kind": "text", "note": "quote withheld: sha256:ab chars:40"}])
    assert withheld["outcome"] == "unverifiable"


def test_nested_values_and_bounds_are_checked():
    doc = _doc({"conditions": [{"temperature": {"status": "present", "value": 350, "unit": "°C"}}],
                "conversion": {"status": "present", "value": 2, "unit": "%", "as_reported": "less than 2 per cent",
                               "bound": "upper"},
                "pressure": {"status": "not_reported", "missing_reason": "not_stated_in_source"}})
    res = vc.check_document(doc)
    assert {r["path"] for r in res["rows"]} == {"conditions[0].temperature", "conversion"}   # an absence is not checked
    assert "≤ 2 %" in vc.review_sheet(res)


def test_the_public_methanol_example_has_few_transcription_flags():
    res = vc.check_document(load_doc(REPO / "examples/methanol-synthesis-public"))
    assert res["values"] > 3000
    assert res["checks_failed"]["value_vs_as_reported"] <= 10          # each a real case for a person (OCR, mapping)
    assert res["counts"]["ok"] / res["values"] > 0.8


def test_the_command_writes_a_sheet_and_strict_fails_on_a_flag(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_doc({"conversion": {"status": "present", "value": 15.0, "unit": "%"}})))
    run = subprocess.run([sys.executable, "-m", "scale.cli", "review", "values", str(bad), "--strict"],
                         capture_output=True, text=True)
    assert run.returncode == 1 and "**1 flagged**" in run.stdout
