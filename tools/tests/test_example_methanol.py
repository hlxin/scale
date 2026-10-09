"""The methanol-synthesis example (examples/methanol-synthesis-pre1966/): the frozen corpus, the curated scale-graph and the
manuscript's questions as query plans, run on the public files alone.

The graph is the ARPA-E CATALYST curation of the historical methanol-synthesis literature published before 1966,
scoped to CO and CO2 hydrogenation (105 sources),
cleared for publication by the project partners, moved to today's 0.1.0 and capped (scale evidence cap): quoted text
beyond a source's cap is withheld as sha256 + length. The curation inputs (fragments, page texts, OCR, GALAXY bundles)
stay in the restricted copy; the evidence index is rebuilt here (scale graph index), never committed."""

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
PLANS = sorted((EX / "queries/scale-graph").glob("*.yaml"))
assert PLANS, "no methanol query plans"


@pytest.fixture(scope="module")
def pg():
    return load_doc(GRAPH)


@pytest.fixture(scope="module")
def manifest():
    return load_doc(EX / "corpus/manifest.json")


@pytest.fixture(scope="module")
def spec(pg):
    return spec_of(pg)


@pytest.fixture(scope="module")
def index(pg):
    from scale.passages import Index, evidence_items, graph_sha256
    return Index.build(evidence_items(pg), graph_sha256=graph_sha256(pg))


def _run(pg, spec, index, plan: dict) -> dict:
    from scale import pgraph_query
    return pgraph_query.run(pg, spec, plan, index if plan.get("text") else None)


# ------------------------------------------------------------------------------------------ the frozen corpus
def test_corpus_is_frozen_before_the_cutoff(manifest):
    assert manifest["cutoff"]["date"] == CUTOFF
    srcs = {s["slug"]: s for s in manifest["sources"]}
    inscope = [s for s in manifest["sources"] if s["status"] == "in_scope"]
    assert len(inscope) == manifest["counts"]["in_scope"] == 108
    assert all(int(s["published"][:4]) < 1966 for s in inscope)
    assert srcs[KUME_1959]["status"] == srcs[ICI_1960]["status"] == "in_scope"   # before 1966, ICI's own 1960 patent included
    held = [s for s in manifest["sources"] if s["status"] == "held_out_target"]
    assert len(held) == 10 and all("1966" in s["corpus_role"] for s in held)  # the commercialization, held out by role
    assert "US 2,061,470" in manifest["cutoff"]["caution"]                   # a Cu-Zn-Al disclosure the cutoff does not remove


# ------------------------------------------------------------------------------------------ the graph
def test_graph_is_public_research_data_under_the_current_schema(pg, spec):
    from scale import pgraph
    g = pg["graph"]
    assert g["schema_version"] == "0.1.0" and g["follows_domains"] == ["catalysis"]
    assert g["data_status"] == "research_data" and g["stewardship"]["access"] == "public"
    assert CUTOFF in g["title"] and "US 2,061,470" in g["description"]
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


def test_missing_concept_gaps_are_resolved_or_open():
    gaps = [g for g in load_doc(EX / "curation/assembly-report.json")["gaps"] if g["kind"] == "missing_concept"]
    resolved = [g for g in gaps if g.get("status") == "resolved"]
    assert len(gaps) == 47 and len(resolved) == 39


# ------------------------------------------------------------------------------------------ the manuscript's questions
@pytest.mark.parametrize("plan", PLANS, ids=lambda p: p.stem)
def test_manuscript_questions_are_answered_from_evidence_before_the_cutoff(pg, spec, index, plan):
    res = _run(pg, spec, index, load_yaml(plan))
    assert res["status"] == "answered" and res["rows"]
    assert all((ev.get("source_year") or 0) < 1966 for r in res["rows"] for ev in r.get("evidence") or [])


@pytest.mark.parametrize("plan, rows", [("q1-copper-lower-temperature", 236), ("q2b-inhibited-by", 88),
                                        ("q4-co2-feedstock", 135), ("q6-cu-zn-al-formulations", 5)])
def test_structured_questions_keep_their_answers(pg, spec, index, plan, rows):
    assert _run(pg, spec, index, load_yaml(EX / f"queries/scale-graph/{plan}.yaml"))["row_count"] == rows


def test_cu_zn_al_query_returns_the_1928_catalyst(pg, spec, index):
    res = _run(pg, spec, index, load_yaml(EX / "queries/scale-graph/q6-cu-zn-al-formulations.yaml"))
    assert min(r["earliest_source_year"] for r in res["rows"]) == 1928


def test_an_earlier_cutoff_holds_out_kume_1959(pg, spec, index):
    plan = {**load_yaml(EX / "queries/scale-graph/q4-co2-feedstock.yaml"), "published_before": "1959-01-01"}
    res = _run(pg, spec, index, plan)
    years = [ev.get("source_year") or 0 for r in res["rows"] for ev in r.get("evidence") or []]
    assert res["rows"] and max(years) < 1959


def test_the_benchmark_corpus_is_the_co_co2_hydrogenation_sources(manifest):
    """corpus/sources.json: the in-scope sources on CO/CO2 + H2, each with the digest of its PDF (the PDFs are local)."""
    srcs = load_doc(EX / "corpus/sources.json")
    frozen = {s["slug"]: s for s in manifest["sources"] if s["status"] == "in_scope"}
    kept = {s["slug"] for s in srcs["sources"]}
    assert len(kept) == srcs["counts"]["sources"] == 105 and kept <= set(frozen)
    assert {e["slug"] for e in srcs["excluded"]} == set(frozen) - kept
    assert all(s["pdf_sha256"] == frozen[s["slug"]]["text"]["pdf_sha256"] and s["pdf"] == f"pdfs/{s['slug']}.pdf"
               for s in srcs["sources"])
    assert "corpus/pdfs/" in (EX / ".gitignore").read_text().split()


def test_the_graph_is_scoped_to_the_benchmark_corpus(pg):
    """The graph keeps CO and CO2 hydrogenation only: its sources are exactly the corpus's 105."""
    kept = {s["slug"] for s in load_doc(EX / "corpus/sources.json")["sources"]}
    assert {n["id"].removeprefix("ex:msyn/source/") for n in pg["nodes"] if n["label"] == "Source"} == kept
    assert pg["graph"]["graph_id"] == "ex:msyn/graph/co-co2-hydrogenation" and "105 sources" in pg["graph"]["title"]


def test_the_releases_are_intact_and_answer_as_recorded():
    """releases/v<version>/: immutable snapshots; every file's digest, the graph's content digest and every plan's
    answer still hold (tools/release_graph.py verify)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("release_graph", EX / "tools/release_graph.py")
    rg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rg)
    assert (EX / "releases/v1.0.0/RELEASE.yaml").is_file()
    assert rg.verify() == []
    m = load_yaml(EX / "releases/v1.0.0/RELEASE.yaml")
    assert m["schema"] == {"name": "scale-graph", "version": "0.1.0", "follows_domains": ["catalysis"],
                           "spec_sha256": "3c2fa7205a7bae5e0bbfa7d87826ff7ab7803e78536129064101c7d5a2c02006"}
    assert m["counts"]["sources"] == m["corpus"]["sources"] == 105 and m["validation"]["errors"] == 0


def test_the_galaxy_bundle_is_the_release_exported_with_its_schema():
    """galaxy/methanol-synthesis-pre1966_v1.0.0/: the GALAXY bundle of release v1.0.0, sealed (SHA256SUMS,
    validation.json), its schema extending scale-graph by version and spec digest, its corpus the scoped manifest."""
    import hashlib
    b = EX / "galaxy/methanol-synthesis-pre1966_v1.0.0"
    m = load_doc(b / "bundle.json")
    release = load_yaml(EX / "releases/v1.0.0/RELEASE.yaml")
    assert m["format"] == "galaxy-kg-bundle" and m["bundle_id"] == "methanol-synthesis-pre1966" and m["version"] == "1.0.0"
    assert m["graph_sha256"] == hashlib.sha256((b / "kg/graph.json").read_bytes()).hexdigest()
    sums = dict(reversed(line.split("  ", 1)) for line in (b / "SHA256SUMS").read_text().splitlines())
    assert all(hashlib.sha256((b / f).read_bytes()).hexdigest() == h for f, h in sums.items())
    v = load_doc(b / "validation.json")
    assert v["ok"] and v["n_errors"] == 0 and v["n_warnings"] == 0
    schema = load_doc(b / "kg/schema.json")
    assert schema["extends"] == {"schema_id": "scale-graph", "version": release["schema"]["version"],
                                 "sha256": release["schema"]["spec_sha256"]}
    h = m["scale_header"]
    assert h["graph_id"] == release["graph_id"] and h["schema_sha256"] == release["schema"]["spec_sha256"]
    assert h["stewardship"]["access"] == "public" and m["counts"]["papers"] == 105
    assert m["corpus"]["n_included"] == 105 and m["corpus"]["n_screened"] == 178
    assert "### Not carried over" in (b / "CHANGELOG.md").read_text()
