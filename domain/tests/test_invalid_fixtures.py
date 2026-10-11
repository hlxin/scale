"""Invalid scale-catal documents, one defect each: every one is rejected, for the reason expect.yaml
states, and nothing else is wrong with it (so the fixture tests the rule it names). Each is checked under the version
it pins, as `scale graph validate` (and so `scale check`) checks it; they all pin their base example's version."""

import pytest

from conftest import FIXTURES, pinned_schema, spec_of
from scale import pgraph
from scale.devcheck import invalid_fixtures
from scale.util import load_doc, load_yaml

INDEX = load_yaml(FIXTURES / "invalid/expect.yaml")["fixtures"]


@pytest.mark.parametrize("entry", INDEX, ids=[e["file"] for e in INDEX])
def test_each_invalid_fixture_is_rejected_for_its_stated_reason(entry):
    doc = load_doc(FIXTURES / "invalid" / entry["file"])
    rep = pgraph.validate(doc, spec_of(doc))
    assert not rep.ok
    assert [e["message"] for e in rep.errors if entry["error"] in e["message"]], [e["message"] for e in rep.errors]
    assert len(rep.errors) == 1, [e["message"] for e in rep.errors]          # one defect each
    assert entry["reason"]


def test_the_index_names_every_fixture_and_scale_check_uses_it():
    from conftest import REPO
    assert len(invalid_fixtures(REPO)) == len(INDEX) >= 8
    assert sorted(p.name for p in (FIXTURES / "invalid").glob("*.json")) == sorted(e["file"] for e in INDEX)
    base = load_doc(REPO / "domain/examples/scale-catal/driving-force-examples/electro.json")
    pins = {load_doc(FIXTURES / "invalid" / e["file"])["graph"]["schema_version"] for e in INDEX}
    assert pins == {base["graph"]["schema_version"]}, pins                   # one version: the base example's (build_fixtures)
    assert pinned_schema(base)                                                # the head or a frozen version
