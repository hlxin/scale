"""The methanol-synthesis example (examples/methanol-synthesis-pre1966/): the frozen corpus (sources.json), the curated
scale-catal and the manuscript's questions as query plans, run on the public files alone.

The graph is the curation of the historical methanol-synthesis literature published before 1966,
scoped to CO and CO2 hydrogenation (105 sources), cleared for publication, moved to today's
0.1.0 and capped (scale evidence cap): quoted text beyond a source's cap is withheld as sha256 + length. The PDFs
(pdfs/) and page texts are local; the evidence index is built here, never committed."""

from collections import Counter

import pytest

from conftest import REPO, spec_of
from scale import rights
from scale.util import load_doc, load_yaml

EX = REPO / "examples/methanol-synthesis-pre1966"
GRAPH = EX / "methanol-synthesis.graph.json"
CUTOFF = "1966-01-01"
KUME_1959 = "10.1246-nikkashi1898.62.7_939"
ICI_1960 = "us2964551a"
PLANS = sorted((EX / "queries").glob("*.yaml"))
assert PLANS, "no methanol query plans"


@pytest.fixture(scope="module")
def pg():
    return load_doc(GRAPH)


@pytest.fixture(scope="module")
def manifest():
    return load_doc(EX / "sources.json")


@pytest.fixture(scope="module")
def spec(pg):
    return spec_of(pg)


@pytest.fixture(scope="module")
def graph(pg, spec):
    from scale.pgraph_query import Graph
    return Graph(pg, spec)


@pytest.fixture(scope="module")
def index(pg):
    from scale.passages import Index, evidence_items, graph_sha256
    return Index.build(evidence_items(pg), graph_sha256=graph_sha256(pg))


def _run(pg, spec, index, graph, plan: dict) -> dict:
    from scale import pgraph_query
    return pgraph_query.run(pg, spec, plan, index if plan.get("text") else None, graph)


# ------------------------------------------------------------------------------------------ the frozen corpus
def test_corpus_is_frozen_before_the_cutoff(manifest):
    assert manifest["cutoff"]["date"] == CUTOFF
    srcs = {s["slug"]: s for s in manifest["sources"]}
    inscope = [s for s in manifest["sources"] if s["status"] == "in_scope"]
    assert len(inscope) == manifest["counts"]["in_scope"] == 105
    assert all(int(s["published"][:4]) < 1966 for s in inscope)
    assert srcs[KUME_1959]["status"] == srcs[ICI_1960]["status"] == "in_scope"   # before 1966, ICI's own 1960 patent included
    held = [s for s in manifest["sources"] if s["status"] == "held_out_target"]
    assert len(held) == 10 and all("1966" in s["corpus_role"] for s in held)  # the commercialization, held out by role
    assert "US 2,061,470" in manifest["cutoff"]["caution"]                   # a Cu-Zn-Al disclosure the cutoff does not remove


# ------------------------------------------------------------------------------------------ the graph
def test_graph_is_public_research_data_under_the_current_schema(pg, spec):
    from scale import pgraph
    g = pg["graph"]
    assert g["schema_version"] == "0.2.0" and g["follows_domains"] == ["catalysis"]
    assert g["data_status"] == "research_data" and g["stewardship"]["access"] == "public"
    assert "1966" in g["title"] and len(g["title"]) <= 40 and CUTOFF in g["description"] and "US 2,061,470" in g["description"]
    rep = pgraph.validate(pg, spec)
    assert rep.errors == [], rep.errors[:5]
    assert rights.access_problems(REPO, [GRAPH]) == []


def test_quoted_text_is_within_the_cap(pg):
    rep = rights.report(pg, rights.load_rights(EX / "rights.yaml"))
    assert rep["violations"] == [] and rep["unlisted"] == []
    assert sum(r["withheld_items"] for r in rep["sources"].values()) > 0      # capped, withheld as sha256 + length


def test_every_quote_comes_from_an_in_scope_source(pg, manifest):
    years = {f"ex:msyn/source/{s['slug']}": int(s["published"][:4]) for s in manifest["sources"] if s["status"] == "in_scope"}
    evs = [ev for r in pg["nodes"] + pg["links"] for ev in r["props"].get("evidence") or []]
    cited = {ev["source"] for ev in evs}
    assert cited <= set(years) and max(years[c] for c in cited) < 1966
    assert all(ev["locator"].startswith("p.") for ev in evs)


def test_roles_are_on_edges_and_there_are_no_role_labels(pg):
    labels = Counter(n["label"] for n in pg["nodes"])
    assert not {"Support", "Promoter", "Precursor", "Binder", "Inhibitor"} & set(labels)
    roles = Counter(e["props"].get("role") for e in pg["links"] if e["type"] == "HAS_COMPONENT")
    assert roles["active_component"] and roles["promoter"] and roles["support"]


def test_shared_chemistry_is_merged_but_catalysts_are_not(pg):
    ids = {n["id"] for n in pg["nodes"]}
    assert {"ex:msyn/species/co", "ex:msyn/species/copper", "ex:msyn/reaction/co-hydrogenation-to-methanol"} <= ids
    for n in pg["nodes"]:
        if n["label"] in ("Catalyst", "CatalystSample", "CatalyticTest"):
            assert n["id"].split("/")[1] not in ("species", "reaction", "material"), n["id"]


def test_catalytic_tests_are_thermo_driven(pg):
    tests = [n for n in pg["nodes"] if n["label"] == "CatalyticTest"]
    assert len(tests) > 500 and all(set(n["props"]["driving_forces"]) <= {"thermo", "other"} for n in tests)


def test_the_graph_uses_the_process_and_equilibrium_concepts(pg):
    labels = Counter(n["label"] for n in pg["nodes"])
    types = Counter(e["type"] for e in pg["links"])
    assert labels["ProcessUnit"] > 10 and types["FEEDS_INTO"] > 10
    tests = [n["props"] for n in pg["nodes"] if n["label"] == "CatalyticTest"]
    assert sum(t["test_kind"] == "equilibrium_measurement" for t in tests) >= 20
    assert any(e["props"].get("negated") for e in pg["links"] if e["type"] in ("PRODUCES", "DETECTS"))


# ------------------------------------------------------------------------------------------ the manuscript's questions
@pytest.mark.parametrize("plan", PLANS, ids=lambda p: p.stem)
def test_manuscript_questions_are_answered_from_evidence_before_the_cutoff(pg, spec, index, graph, plan):
    res = _run(pg, spec, index, graph, load_yaml(plan))
    assert res["status"] == "answered" and res["rows"]
    assert all((ev.get("source_year") or 0) < 1966 for r in res["rows"] for ev in r.get("evidence") or [])


@pytest.mark.parametrize("plan, rows", [("q1-copper-lower-temperature", 236), ("q2b-inhibited-by", 88),
                                        ("q4-co2-feedstock", 135), ("q6-cu-zn-al-formulations", 5)])
def test_structured_questions_keep_their_answers(pg, spec, index, graph, plan, rows):
    assert _run(pg, spec, index, graph, load_yaml(EX / f"queries/{plan}.yaml"))["row_count"] == rows


def test_cu_zn_al_query_returns_the_1928_catalyst(pg, spec, index, graph):
    res = _run(pg, spec, index, graph, load_yaml(EX / "queries/q6-cu-zn-al-formulations.yaml"))
    assert min(r["earliest_source_year"] for r in res["rows"]) == 1928


def test_an_earlier_cutoff_holds_out_kume_1959(pg, spec, index, graph):
    plan = {**load_yaml(EX / "queries/q4-co2-feedstock.yaml"), "published_before": "1959-01-01"}
    res = _run(pg, spec, index, graph, plan)
    years = [ev.get("source_year") or 0 for r in res["rows"] for ev in r.get("evidence") or []]
    assert res["rows"] and max(years) < 1959


def test_the_corpus_is_one_checked_manifest_with_local_pdfs(manifest):
    """sources.json: every candidate source once, the counts adding up (scale corpus check); each in-scope source
    names its local PDF by slug (pdfs/<slug>.pdf, git-ignored) with the PDF's sha256, and where the project corpus
    keeps it."""
    from scale import corpus
    assert corpus.check(manifest)["ok"]
    inscope = [s for s in manifest["sources"] if s["status"] == "in_scope"]
    assert all(s["pdf"] == f"pdfs/{s['slug']}.pdf" and len(s["text"]["pdf_sha256"]) == 64 and s["corpus_pdf"]
               for s in inscope)
    assert all(s["slug"] == s["doi"].replace("/", "-") for s in inscope if s.get("doi"))
    assert "pdfs/" in (EX / ".gitignore").read_text().split()
    assert sorted(p.name for p in EX.iterdir() if not p.name.startswith(".") and p.name not in ("pdfs", "work")) == [
        "README.md", "methanol-synthesis-pre1966_v3.0.0.zip", "methanol-synthesis.graph.json", "queries", "rights.yaml",
        "sources.json", "stewardship.yaml"]


def test_the_bundle_is_this_graph_sealed():
    """The knowledge-graph bundle (kg-bundle format 1.1.0): one folder at the top of the zip, every file matching
    SHA256SUMS, the manifest's graph digest that of the graph inside, and that graph exported from this example."""
    import hashlib
    import json
    import zipfile
    z = zipfile.ZipFile(EX / "methanol-synthesis-pre1966_v3.0.0.zip")
    root = "methanol-synthesis-pre1966_v3.0.0/"
    assert {n.split("/")[0] for n in z.namelist()} == {root.rstrip("/")}
    sums = dict(reversed(line.split("  ", 1)) for line in z.read(root + "SHA256SUMS").decode().splitlines())
    assert all(hashlib.sha256(z.read(root + f)).hexdigest() == h for f, h in sums.items())
    m = json.loads(z.read(root + "bundle.json"))
    assert (m["format_version"], m["bundle_id"], m["version"], m["previous"]["version"]) == (
        "1.1.0", "methanol-synthesis-pre1966", "3.0.0", "2.0.0")
    # exported from the graph at the schema it pins (the head)
    from scale import pgraph
    pinned = load_doc(GRAPH)["graph"]["schema_version"]
    assert (m["schema_id"], m["schema_version"]) == ("scale-catal", pinned)
    head = pgraph.spec_path(REPO)
    spec = head if str(pgraph.load_spec(head)["version"]) == pinned else pgraph.frozen_spec(head, pinned)
    assert m["scale_header"]["schema_sha256"] == pgraph.spec_sha256(pgraph.load_spec(spec))
    title = load_doc(GRAPH)["graph"]["title"]          # a platform names the imported graph after the bundle's title
    assert m["topic"] == title == "Methanol Synthesis CO/CO2+H2 Pre-1966" and len(title) <= 40
    graph = z.read(root + "kg/graph.json")
    assert m["graph_sha256"] == hashlib.sha256(graph).hexdigest() and m["counts"]["edges"] == 17563
    assert m["scale_header"]["graph_id"] == load_doc(GRAPH)["graph"]["graph_id"]
    assert json.loads(z.read(root + "validation.json"))["ok"]


def test_the_graph_is_scoped_to_the_benchmark_corpus(pg, manifest):
    """The graph keeps CO and CO2 hydrogenation only: its sources are exactly the corpus's 105 in-scope sources."""
    kept = {s["slug"] for s in manifest["sources"] if s["status"] == "in_scope"}
    assert {n["id"].removeprefix("ex:msyn/source/") for n in pg["nodes"] if n["label"] == "Source"} == kept
    assert pg["graph"]["graph_id"] == "ex:msyn/graph/co-co2-hydrogenation" and "105 sources" in pg["graph"]["description"]
