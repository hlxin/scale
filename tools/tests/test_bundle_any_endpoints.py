"""An endpoint the schema declares ANY is exported as an empty list (unconstrained) in the bundle's edge types, never as
every kind (issue #44): the spec digest is unchanged, the declared kind pairs are those the schema means, and the
conformance check lets an edge of such a type join any two kinds while a typed endpoint still refuses a wrong kind."""

import pytest

from conftest import GRAPH_MANIFEST
from scale import pgraph
from scale.kgbundle import _conforms, vocabulary
from scale.util import ScaleError


@pytest.fixture(scope="module")
def vocab():
    return vocabulary(pgraph.load_spec(GRAPH_MANIFEST))


def test_an_endpoint_declared_any_is_an_empty_list(vocab):
    _, edges = vocab
    assert edges["REVISES"]["from"] == [] and edges["REVISES"]["to"] == []
    for et in ("HAS_INPUT", "HAS_OUTPUT", "ABOUT", "INCLUDES"):
        assert edges[et]["to"] == [] and edges[et]["from"] != []


def test_exactly_these_sides_are_unconstrained(vocab):
    _, edges = vocab
    empty = {(et, side) for et, t in edges.items() for side in ("from", "to") if not t[side]}
    assert empty == {("REVISES", "from"), ("REVISES", "to"), ("HAS_INPUT", "to"), ("HAS_OUTPUT", "to"),
                     ("ABOUT", "to"), ("INCLUDES", "to"), ("REPORTED_IN", "from")}


def test_the_declared_kind_pairs_are_far_below_every_kind_to_every_kind(vocab):
    nodes, edges = vocab
    declared = sum(len(t["from"]) * len(t["to"]) for t in edges.values() if t["from"] and t["to"])
    assert declared == 1395 and declared < 6014      # the schema's typed pairs, REPORTED_IN's 54 no longer among them
    assert all(len(t["from"]) < len(nodes) and len(t["to"]) < len(nodes) for t in edges.values())
    assert edges["REPORTED_IN"]["to"] == ["Publication"]


def test_an_edge_between_arbitrary_kinds_conforms_where_an_end_is_unconstrained(vocab):
    nodes, edges = vocab
    labels = sorted(nodes)
    a, b = labels[0], labels[-1]
    ns = [{"id": "a", "label": a, "props": {}}, {"id": "b", "label": b, "props": {}}]
    _conforms(nodes, edges, ns, [{"id": "e", "type": "REVISES", "source": "a", "target": "b", "props": {}}], "t")
    _conforms(nodes, edges, ns, [{"id": "e", "type": "REVISES", "source": "b", "target": "a", "props": {}}], "t")


def test_a_typed_edge_with_a_wrong_kind_still_fails(vocab):
    nodes, edges = vocab
    wrong = next(x for x in sorted(nodes) if x not in edges["HAS_INPUT"]["from"])
    ns = [{"id": "a", "label": wrong, "props": {}}, {"id": "b", "label": "Publication", "props": {}}]
    with pytest.raises(ScaleError, match="not allowed"):
        _conforms(nodes, edges, ns, [{"id": "e", "type": "HAS_INPUT", "source": "a", "target": "b", "props": {}}], "t")
    with pytest.raises(ScaleError, match="not allowed"):
        _conforms(nodes, edges, ns, [{"id": "e", "type": "REPORTED_IN", "source": "b", "target": "a", "props": {}}], "t")
