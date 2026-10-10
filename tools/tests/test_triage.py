import json

import pytest

from conftest import REPO
from scale import intake
from scale.cli import main
from scale.util import load_doc

RAW = REPO / "tools/tests/fixtures/triage/github-raw.json"


@pytest.fixture(scope="module")
def queue():
    raw = json.loads(RAW.read_text())
    return intake.ingest(raw, intake.Vocabulary.from_repo(REPO))


def test_ingest_skips_bots_and_own_output(queue):
    keys = {i["key"] for i in queue["items"]}
    assert "comment-902" not in keys and "comment-903" not in keys      # bot, and the triage system's own comment
    assert {"issue-12", "comment-901", "review-77", "discussion-3"} <= keys


def test_clusters_merge_threads_and_duplicates(queue):
    by_id = {c["cluster_id"]: c for c in queue["clusters"]}
    assert set(by_id) == {"T12", "T13", "T14", "TP15", "TD3"}
    assert {i["key"] for i in by_id["T12"]["items"]} == {"issue-12", "comment-901", "issue-16"}   # thread + near-duplicate
    assert {i["key"] for i in by_id["TP15"]["items"]} == {"pr-15", "review-77"}


def test_categories_and_references(queue):
    by_id = {c["cluster_id"]: c for c in queue["clusters"]}
    assert by_id["T12"]["category"] == "missing_concept" and by_id["T12"]["refs"]["classes"] == ["ElectrochemicalCell"]
    assert by_id["T13"]["category"] == "extraction_error" and by_id["T13"]["refs"]["records"] == ["ex:df-electro/test/m03"]
    assert by_id["T14"]["category"] == "new_source" and by_id["T14"]["refs"]["doi"] == ["10.1021/jacs.5c07490"]
    assert by_id["TD3"]["category"] == "question"
    assert queue["clusters"][0]["cluster_id"] == "T12"     # missing concepts first


def test_proposal_references_are_six_digit_numbers_named_as_proposals():
    """A six-digit number is a proposal reference only where the text says so (a bare one may be anything);
    pr-, issue-, cq- and gap- numbers are not."""
    text = ("see proposal 000008, Proposal #000009 and domain/proposals/000007/README.md; "
            "not order 123456, P-0006, pr-0012 or cq-0001")
    assert intake.PATTERNS["proposal"].findall(text) == ["000008", "000009", "000007"]


def test_rule_proposals_never_recommend_or_decide(queue):
    props, rejected = intake.merge_proposals(queue, None)
    assert not rejected and len(props) == len(queue["clusters"])
    assert all(p["recommended_option"] is None and "decision" not in p for p in props)
    mc = next(p for p in props if p["cluster_id"] == "T12")
    assert mc["reviewers_required"] == ["domain"] and [o["action"] for o in mc["options"]][0] == "change_schema"


def test_external_proposals_are_validated(queue):
    good = {"cluster_id": "T13", "category": "extraction_error", "summary": "Claimed wrong yield",
            "options": [{"id": "A", "action": "not_an_error", "description": "Quote says 2.3 mg h−1 cm−2 (Results, Fig. 1E)."},
                        {"id": "B", "action": "re_extract", "description": "Re-check the figure."}],
            "recommended_option": "A", "confidence": 0.8, "proposed_by": "any-agent-system 1.0"}
    bad = {"cluster_id": "T12", "category": "missing_concept", "summary": "x", "options": [{"id": "A", "action": "x", "description": "y"}],
           "proposed_by": "z", "decision": "A"}
    unknown = dict(good, cluster_id="T999")
    props, rejected = intake.merge_proposals(queue, [good, bad, unknown])
    assert next(p for p in props if p["cluster_id"] == "T13")["proposed_by"] == "any-agent-system 1.0"
    assert next(p for p in props if p["cluster_id"] == "T12")["proposed_by"].startswith("scale rules")   # bad one replaced by rules
    assert {r["cluster_id"] for r in rejected} == {"T12", "T999"}


def test_the_digest_decides_nothing_and_points_to_pull_requests(queue):
    """Decisions are pull-request reviews: the digest lists topics and options and says how to act on one (a pull
    request, or a comment that @scale-agents take up); there is no /decide command and nothing is written to the
    decision log."""
    props, _ = intake.merge_proposals(queue, None)
    body = intake.render_digest(queue, props, "hlxin/scale", None, [])
    assert body.startswith("# SCALE feedback digest") and "## T12" in body and "scale-triage-state" in body
    assert "/decide" not in body and "/defer" not in body and "an approving review" in body
    assert "open a pull request" in body and "@scale-agents open a pull request" in body
    assert not hasattr(intake, "parse_decisions") and not hasattr(intake, "append_decisions")
    assert intake.DIGEST_LABEL == "feedback-digest"


def test_cli_end_to_end_offline(tmp_path, capsys):
    out = tmp_path / "run"
    assert main(["--repo", str(REPO), "triage", "ingest", "--from-file", str(RAW), "--out", str(out), "--github-repo", "hlxin/scale"]) == 0
    assert main(["--repo", str(REPO), "triage", "propose", str(out)]) == 0
    assert (out / "digest.md").exists() and (out / "proposals.json").exists()
    capsys.readouterr()
    assert main(["--repo", str(REPO), "triage", "publish", str(out)]) == 0      # dry run by default
    assert json.loads(capsys.readouterr().out)["dry_run"] is True


def test_agent_command_hook(tmp_path):
    out = tmp_path / "run"
    main(["--repo", str(REPO), "triage", "ingest", "--from-file", str(RAW), "--out", str(out), "--github-repo", "hlxin/scale"])
    agent = tmp_path / "agent.py"
    agent.write_text("import json,sys\nq=json.load(open(sys.argv[1]))\n"
                     "json.dump({'proposals':[{'cluster_id':c['cluster_id'],'category':c['category'],'summary':c['title'],"
                     "'options':[{'id':'A','action':'answer','description':'d'}],'proposed_by':'toy-agent'} for c in q['clusters']]},"
                     "open(sys.argv[2],'w'))\n")
    import sys as _sys
    assert main(["--repo", str(REPO), "triage", "propose", str(out), "--agent-command", f"{_sys.executable} {agent}", "--strict"]) == 0
    props = load_doc(out / "proposals.json")["proposals"]
    assert all(p["proposed_by"] == "toy-agent" for p in props)


def test_catalogue_and_suggest_links(tmp_path):
    doc = load_doc(REPO / "domain/examples/scale-graph/driving-force-examples/electro.json")
    md = intake.catalogue_markdown(doc, "hlxin/scale")
    assert "## CatalyticTest" in md and "ex:df-electro/test/m03" in md and "template=comment.yml" in md
    assert "current_density -120 mA/cm2" in md                       # values as reported, with units
    assert "faradaic_efficiency 92 % (NH3)" in md                 # list-valued results are shown, per target
    url = intake.suggest_url("hlxin/scale", "ex:df-electro/test/m03", "E vs RHE?")
    assert url.startswith("https://github.com/hlxin/scale/issues/new?") and "record=ex%3Adf-electro" in url
