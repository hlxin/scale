"""Procedure steps of a preparation: the synthetic fixtures (tools/tests/fixtures/procedure-steps/) pass and fail as
their index (expect.yaml) states; the counterexample fails with exactly one error, the stated one."""

import pytest

from conftest import REPO, spec_of
from scale import pgraph
from scale.util import load_doc, load_yaml

FX = REPO / "tools/tests/fixtures/procedure-steps"
INDEX = load_yaml(FX / "expect.yaml")


@pytest.mark.parametrize("entry", INDEX["pass"], ids=[e["file"] for e in INDEX["pass"]])
def test_each_passing_fixture_is_valid(entry):
    doc = load_doc(FX / entry["file"])
    rep = pgraph.validate(doc, spec_of(doc))
    assert rep.ok and rep.errors == [], [e["message"] for e in rep.errors]
    assert entry["covers"]


@pytest.mark.parametrize("entry", INDEX["fail"], ids=[e["file"] for e in INDEX["fail"]])
def test_each_counterexample_fails_with_exactly_its_stated_error(entry):
    doc = load_doc(FX / entry["file"])
    rep = pgraph.validate(doc, spec_of(doc))
    messages = [e["message"] for e in rep.errors]
    assert not rep.ok and len(messages) == 1 and entry["error"] in messages[0], messages
    assert entry["reason"]


def test_the_index_names_every_fixture_and_they_are_public_synthetic_examples():
    files = sorted(p.name for p in FX.glob("*.json"))
    assert files == sorted(e["file"] for e in INDEX["pass"] + INDEX["fail"])
    for name in files:
        g = load_doc(FX / name)["graph"]
        assert g["data_status"] == "synthetic_example" and g["stewardship"] == {"access": "public"}, name
    spec = spec_of(load_doc(FX / "pass-steps-part-of.json"))
    assert "HAS_PROCEDURE_STEP" not in spec["edges"] and "PART_OF" in spec["edges"]
