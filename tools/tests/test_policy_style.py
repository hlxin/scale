import copy

from conftest import DRIVING_FORCE_EXAMPLES, GRAPH_MANIFEST, REPO
from scale import pgraph
from scale.policy import load_policy, reviewers, sample_records
from scale.style import fmt_file, lint_yaml_text, naming_problems
from scale.util import dump_canonical, load_doc

POLICY = load_policy(REPO)


# ---------------------------------------------------------------- the review policy

def test_every_change_needs_one_approval():
    """One approval for every pull request; the kinds of change are information for the reviewer, not approval
    classes, and there is no comment period, stage or committee."""
    assert POLICY["policy_version"] == 4
    assert not {"committee", "provisional_approvers", "stage", "stages", "area_review", "objections"} & set(POLICY)
    assert POLICY["approvals"] == {"required": 1}
    assert all(set(t) <= {"name", "examples", "needs"} for t in POLICY["tiers"].values())
    assert POLICY["new_concepts_maturity"] == "provisional"
    assert [m["github"] for m in reviewers(POLICY)] == ["hlxin", "mutianyou2013", "diazr04"]


def test_records_sampling_is_configured():
    rec = POLICY["records"]["agent_extracted_records"]
    assert rec["sample_fraction"] == 0.1 and rec["full_check_first_batches"] == 3


# ---------------------------------------------------------------- Tier 1 record checks

def test_record_sample_is_reproducible():
    doc = load_doc(DRIVING_FORCE_EXAMPLES / "photoelectro.json")
    a, b = sample_records(doc, 0.3, 7), sample_records(doc, 0.3, 7)
    assert a == b and a and all(r["evidence"] and r["evidence"][0]["source"] for r in a)
    assert len(sample_records(doc, 1.0, 7)) > len(a)
    full = {r["id"]: r for r in sample_records(doc, 1.0, 7)}
    test = next(r for r in full.values() if r["label"] == "CatalyticTest")
    assert test["values"] and all("status" in v for v in test["values"].values())     # what the reviewer checks
    flagged = sample_records(doc, 0.0, 7, include_flagged=[test["id"]])
    assert [r["id"] for r in flagged if r["flagged"]] == [test["id"]]


# ---------------------------------------------------------------- formats and names

def test_yaml_lint_catches_the_real_traps():
    assert any("flow mapping" in p for p in lint_yaml_text("a: {range: string, description: e.g. x, y}\n"))
    assert any("ambiguous" in p for p in lint_yaml_text("on:\n  push: {}\n"))
    assert any("ambiguous" in p for p in lint_yaml_text("slots:\n  n:\n    range: integer\n"))
    assert any("duplicate key" in p for p in lint_yaml_text("a: 1\na: 2\n"))
    assert lint_yaml_text("units: [V, mV]\nempty: {}\nn2: '2'\n'on': true\n") == []


def test_naming_rules():
    spec = pgraph.load_spec(GRAPH_MANIFEST)
    assert naming_problems(spec) == []                         # released names comply (pH is a documented exception)
    bad = copy.deepcopy(spec)
    bad["nodes"]["bad_label"] = {"properties": {"BadProp": {"type": "text"}}}
    bad["edges"]["usesThing"] = {"properties": {}}
    probs = naming_problems(bad)
    assert any("bad_label" in p and "PascalCase" in p for p in probs) and any("BadProp" in p for p in probs)
    assert any("usesThing" in p and "UPPER_SNAKE_CASE" in p for p in probs)


def test_canonical_json_is_stable(tmp_path):
    p = tmp_path / "d.json"
    p.write_text('{"value": 1, "type": "T", "id": "ex:a"}')
    assert fmt_file(p) and fmt_file(p) is None                 # reformatted once, then stable
    assert p.read_text() == dump_canonical({"id": "ex:a", "type": "T", "value": 1})
    assert list(load_doc(p)) == ["id", "type", "value"]


def test_repository_passes_lint():
    from scale.cli import main
    assert main(["--repo", str(REPO), "lint"]) == 0
    assert main(["--repo", str(REPO), "fmt", "--check"]) == 0
