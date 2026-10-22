"""The access rules the skills and the curation guide give curators, checked against what the tools do with the
records they make: a comparison Claim across two projects' tests, the evidence_ids of a record citing several
sources, and the access of a gap written by hand."""

import json

from conftest import REPO
from scale import pgraph
from scale.gaps import make_gap, not_public

P, Q = "ex:mix/project/p", "ex:mix/project/q"
BOTH, ONLY_P = "ex:mix/org/both", "ex:mix/org/only-p"
DAY = "2026-10-07"


def _two_projects(claim_stewardship: dict) -> dict:
    """A test of project P and one of project Q, institution BOTH in both projects and ONLY_P in P alone, and a
    comparison Claim about the two tests with the given stewardship."""
    def test(key, project):
        return {"id": f"ex:mix/test/{key}", "label": "CatalyticTest",
                "props": {"name": f"{key} test", "stewardship": {"access": "project", "project": project},
                          "temperature": {"status": "present", "value": 250 if key == "p" else 270, "unit": "°C"}}}
    nodes = [test("p", P), test("q", Q),
             {"id": "ex:mix/claim/1", "label": "Claim",
              "props": {"statement": "the two tests differ in temperature", "claim_kind": "comparison",
                        "stewardship": claim_stewardship}},
             {"id": P, "label": "Project", "props": {"name": "p"}}, {"id": Q, "label": "Project", "props": {"name": "q"}},
             {"id": BOTH, "label": "Institution", "props": {"name": "both"}},
             {"id": ONLY_P, "label": "Institution", "props": {"name": "only p"}}]
    links = [{"id": "l/both-p", "source": BOTH, "target": P, "type": "PARTICIPATES_IN", "props": {}},
             {"id": "l/both-q", "source": BOTH, "target": Q, "type": "PARTICIPATES_IN", "props": {}},
             {"id": "l/onlyp-p", "source": ONLY_P, "target": P, "type": "PARTICIPATES_IN", "props": {}}]
    for key in ("p", "q"):
        links.append({"id": f"l/about-{key}", "source": "ex:mix/claim/1", "target": f"ex:mix/test/{key}", "type": "ABOUT",
                      "props": {"stewardship": claim_stewardship}})
    return {"directed": True, "multigraph": True,
            "graph": {"schema": "scale-catal", "graph_id": "ex:mix/graph", "data_status": "research_data",
                      "stewardship": {"access": "institution", "contributed_by": [BOTH]}},
            "nodes": nodes, "links": links}


def _sees_claim(doc: dict, viewer: list[str]) -> bool:
    return "ex:mix/claim/1" in {n["id"] for n in pgraph.filter_for(doc, viewer, DAY)["nodes"]}


def test_a_comparison_claim_across_two_projects_is_never_one_projects():
    """scan-conflicts step 7: a Claim comparing a test of project P with one of project Q describes both, and
    neither project's stewardship is the least open of the two. Under P's stewardship the filter keeps it for P,
    whose members outside Q would read Q's value in its statement; as the skill says, it is either kept out of the
    shared document or an institution's, naming only institutions that may see both, and then no project's view,
    nor the public's, nor an institution in one project only, holds it."""
    leak = _two_projects({"access": "project", "project": P})
    assert _sees_claim(leak, [P]) and "ex:mix/test/q" not in {n["id"] for n in pgraph.filter_for(leak, [P], DAY)["nodes"]}
    safe = _two_projects({"access": "institution", "contributed_by": [BOTH]})
    assert not _sees_claim(safe, [P]) and not _sees_claim(safe, [Q]) and not _sees_claim(safe, [])
    assert not _sees_claim(safe, [ONLY_P])
    assert _sees_claim(safe, [BOTH])
    text = (REPO / "skills/scan-conflicts/SKILL.md").read_text()
    assert "none of them is\n   the least open" in text and "never one project's stewardship" in text


def test_the_curation_guide_states_the_evidence_ids_rule_of_the_skill():
    """docs/curation.md states, as the curate-corpus skill does, that every value of a record citing several sources
    gets its evidence_ids, and that a value without them on a record that lost evidence is withheld (fail closed),
    as the filter does (test_a_filtered_value_is_never_cited_to_a_source_that_may_not_state_it)."""
    for path in ("docs/curation.md", "skills/curate-corpus/SKILL.md"):
        text = " ".join((REPO / path).read_text().split())
        assert "several sources" in text and "`evidence_ids`" in text, path
        assert "a value without `evidence_ids` on a record that lost evidence (fail closed)" in text, path


def test_a_hand_written_gap_states_its_access():
    """The skills' route steps: a gap written by hand with no access reads as institution (not for a public tracker);
    with access.level public it may be filed."""
    bare = make_gap("missing_concept", record="ex:c", about="a concept", detected_by="curation", schema=None)
    assert "access" not in bare and not_public(bare)
    assert not_public(json.loads(json.dumps({**bare, "access": {"level": "public", "note": ""}}))) is None
    for path in ("skills/curate-corpus/SKILL.md", "skills/query-graph/SKILL.md"):
        text = " ".join((REPO / path).read_text().split())
        assert "write by hand states its" in text and "reads as institution" in text, path
