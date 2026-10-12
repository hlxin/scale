"""The public-domain methanol-synthesis example (examples/methanol-synthesis-public/): 55 sources that are public domain
in the United States, kept as parts, with their PDFs and page texts. It is exactly the public-domain part of the full
graph, every source is public domain, every quote is in full and is found verbatim in its source's page texts, and the
manuscript's questions are answered from it. The full graph (105 sources, most in copyright) is kept outside this
repository; the test that this folder is its public-domain part runs where a restricted copy holds it."""

import pytest

from conftest import REPO, spec_of
from scale import graphparts as gp
from scale import layout, pgraph, pgraph_query
from scale.sourcetext import joined, sha256_file
from scale.util import load_doc, load_yaml

EX = REPO / "examples/methanol-synthesis-public"
# the full graph is kept outside the repository: found only in a restricted copy (SCALE_RESTRICTED_DATA)
FULL = layout.locate(REPO, "examples/methanol-synthesis-pre1966/methanol-synthesis.graph.json")
PLANS = sorted((EX / "queries").glob("*.yaml"))


@pytest.fixture(scope="module")
def manifest():
    return load_doc(EX / "sources.json")


@pytest.fixture(scope="module")
def doc():
    return load_doc(EX)


@pytest.mark.skipif(FULL is None, reason="the full methanol graph is kept outside the repository (a restricted copy)")
def test_it_is_the_public_domain_part_of_the_full_graph(manifest):
    slugs = [s["slug"] for s in manifest["sources"]]
    assert len(slugs) == 55 and manifest["counts"] == {"in_scope": 55}
    expected = gp.subset(gp.split(load_doc(FULL)), slugs)
    here = gp.read_parts(EX)
    assert here["header"]["graph"]["graph_id"] == "ex:msyn/graph/public"
    assert here["sources"] == expected["sources"] and here["shared"] == expected["shared"]
    assert {k: v for k, v in here["header"].items() if k != "graph"} == \
           {k: v for k, v in expected["header"].items() if k != "graph"}


def test_every_source_is_public_domain_with_its_pdf_and_page_texts(manifest):
    rights = load_yaml(EX / "rights.yaml")["sources"]
    kinds = {}
    for s in manifest["sources"]:
        sid = f"ex:msyn/source/{s['slug']}"
        assert rights[sid]["class"] == "public_domain", sid
        assert s["status"] == "in_scope" and sha256_file(EX / s["pdf"]) == s["text"]["pdf_sha256"], sid
        pages = load_doc(EX / s["text"]["page_texts"])
        assert pages["pdf_sha256"] == s["text"]["pdf_sha256"] and (pages["ocr_engine"] or None) == s["text"]["ocr_engine"]
        assert len(joined(pages["pages"])) - 2 * (len(pages["pages"]) - 1) == s["text"]["chars"], sid  # the texts curated from
        kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
    assert set(rights) == {f"ex:msyn/source/{s['slug']}" for s in manifest["sources"]}
    assert kinds == {"article": 16, "patent": 39}
    assert sorted(p.name for p in (EX / "pdfs").iterdir()) == sorted(f"{s['slug']}.pdf" for s in manifest["sources"])


def test_every_quote_is_in_full_and_found_in_its_page_texts(doc, manifest):
    texts = {f"ex:msyn/source/{s['slug']}": joined(load_doc(EX / s["text"]["page_texts"])["pages"])
             for s in manifest["sources"]}
    quotes = 0
    for rec in doc["nodes"] + doc["links"]:
        for ev in (rec.get("props") or {}).get("evidence") or []:
            assert ev.get("source") in texts, (rec["id"], ev.get("source"))
            assert "withheld" not in (ev.get("note") or ""), rec["id"]
            quotes += bool(ev.get("quote"))
    assert quotes > 10000
    rep = pgraph.validate(doc, spec_of(doc), texts)
    assert rep.ok, rep.errors[:5]


# ------------------------------------------------------------------------------------------ the manuscript's questions
@pytest.fixture(scope="module")
def graph(doc):
    return pgraph_query.Graph(doc, spec_of(doc))


@pytest.fixture(scope="module")
def index(doc):
    from scale.passages import Index, evidence_items, graph_sha256
    return Index.build(evidence_items(doc), graph_sha256=graph_sha256(doc))


def _run(doc, graph, index, plan):
    return pgraph_query.run(doc, graph.spec, plan, index if plan.get("text") else None, graph)


def test_the_questions_travel_with_the_example():
    assert [p.stem for p in PLANS] == ["q1-copper-lower-temperature", "q2-feed-poisons", "q2b-inhibited-by",
                                       "q3-feed-purification", "q4-co2-feedstock", "q5-carbon-source",
                                       "q6-cu-zn-al-formulations"]


@pytest.mark.parametrize("plan", PLANS, ids=lambda p: p.stem)
def test_the_manuscript_questions_are_answered_from_evidence_before_the_cutoff(doc, graph, index, plan):
    res = _run(doc, graph, index, load_yaml(plan))
    assert res["status"] == "answered" and res["rows"]
    assert all((ev.get("source_year") or 0) < 1966 for r in res["rows"] for ev in r.get("evidence") or [])


@pytest.mark.parametrize("plan, rows", [("q1-copper-lower-temperature", 117), ("q2b-inhibited-by", 60),
                                        ("q4-co2-feedstock", 55), ("q6-cu-zn-al-formulations", 3)])
def test_the_structured_questions_keep_their_answers(doc, graph, index, plan, rows):
    assert _run(doc, graph, index, load_yaml(EX / f"queries/{plan}.yaml"))["row_count"] == rows

