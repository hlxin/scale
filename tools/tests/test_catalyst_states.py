"""Catalyst states and contexts in the catalysis domain: the synthetic fixtures (tools/tests/fixtures/catalyst-states/)
pass and fail as their index (expect.yaml) states. Each is checked under the version it pins, as `scale graph validate`
checks it; a counterexample fails with exactly one error, the stated one, so that it tests the rule it names."""

import pytest

from conftest import REPO, spec_of
from scale import pgraph
from scale.util import load_doc, load_yaml

FX = REPO / "tools/tests/fixtures/catalyst-states"
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
    assert len(INDEX["pass"]) == 2 and len(INDEX["fail"]) == 8
    for name in files:
        g = load_doc(FX / name)["graph"]
        assert g["data_status"] == "synthetic_example" and g["stewardship"] == {"access": "public"}, name
        assert "proposal" not in g["title"].lower(), name                     # no proposal id of another numbering
    # the concepts they exercise are in the schema the fixtures pin
    spec = spec_of(load_doc(FX / "pass-states.json"))
    for label in ("CatalystState", "StateTransition"):
        assert label in spec["nodes"], label
    for edge in ("AFFECTS_PATHWAY", "PREDICTS", "DETECTS", "DRIVES_TRANSITION", "HAS_COMPONENT", "TRIGGERED_BY"):
        assert edge in spec["edges"], edge
