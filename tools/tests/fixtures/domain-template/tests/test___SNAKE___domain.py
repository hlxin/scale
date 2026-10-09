"""Starter tests of the __TITLE__ domain, scaffolded by the tests' new_domain(): its declaration passes
`scale domains check` and its graph schema manifest (the science kernel plus its domain file) loads and
accepts the example. Add tests for what the domain adds (its vocabulary, its examples, its competency
questions)."""

from pathlib import Path

from scale import layout, pgraph
from scale.domains import check
from scale.util import load_doc

DOMAIN = Path(__file__).resolve().parents[1]                 # domain/ of the repository
REPO = layout.find_root(DOMAIN)
NAME = layout.domain_name(DOMAIN)                             # the domain's name, from its DOMAIN.yaml


def test___SNAKE___declaration_passes_the_domain_check():
    res = check(REPO, [NAME])
    assert res["ok"], res["errors"]


def test___SNAKE___example_is_a_scale_graph_document():
    doc = load_doc(DOMAIN / "examples" / f"{NAME}.example.graph.json")
    assert doc["graph"]["schema"] == "scale-graph" and doc["nodes"]
    spec = pgraph.load_spec(DOMAIN / layout.DOMAIN_GRAPH_MANIFEST)
    assert spec["version"] == doc["graph"]["schema_version"] and pgraph.validate(doc, spec).errors == []
