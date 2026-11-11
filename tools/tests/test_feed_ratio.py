"""Feed ratio warnings (issue #107): a feed's gas ratio held only in Feed.ratios, or only implied by the fractions of two
reactant gases, is warned about (never an error); a ratio on a HAS_COMPONENT edge of the feed silences both; one
reactant in an inert diluent, or a document with no Feed, is not warned about. Nothing is stored or converted."""

import copy

import pytest

from conftest import spec_of
from scale import api, pgraph

FEED = "ex:f/feed/1"
ONLY_MAP = "feed ratio only in ratios"
IMPLIED = "reactant gases and no ratio"


def _species(sid: str, name: str, formula: str) -> dict:
    return {"id": sid, "label": "ChemicalSpecies", "props": {"name": name, "formula": formula, "origin": "curated"}}


def _edge(i: int, target: str, role: str, value: float) -> dict:
    return {"id": f"ex:f/link/{i}", "type": "HAS_COMPONENT", "source": FEED, "target": target,
            "props": {"status": "asserted", "origin": "curated", "role": role, "fraction_basis": "volume",
                      "fraction": {"status": "present", "value": value, "unit": "%"}}}


@pytest.fixture()
def doc() -> dict:
    """A feed of 33 % CO and 67 % H2 (both reactants), on the catalysis template."""
    d = copy.deepcopy(api.ScaleToolkit().call("template", {"domain": "catalysis"})["document"])
    d["nodes"] += [_species("ex:f/sp/co", "carbon monoxide", "CO"), _species("ex:f/sp/h2", "hydrogen", "H2"),
                   {"id": FEED, "label": "Feed", "props": {"name": "syngas", "origin": "curated"}}]
    d["links"] = list(d.get("links") or []) + [_edge(1, "ex:f/sp/co", "reactant", 33), _edge(2, "ex:f/sp/h2", "reactant", 67)]
    return d


def _msgs(d: dict) -> list[str]:
    return [w["message"] for w in pgraph.validate(d, spec_of(d)).warnings if w["record"] == FEED]


def _feed(d: dict) -> dict:
    return next(n for n in d["nodes"] if n["id"] == FEED)["props"]


def _edges(d: dict) -> list[dict]:
    return [e for e in d["links"] if e["type"] == "HAS_COMPONENT" and e["source"] == FEED]


def _val(**kw) -> dict:
    return {"status": "present", "unit": "1", **kw}


def _ratio(d: dict) -> None:
    next(e for e in _edges(d) if e["target"].endswith("/h2"))["props"]["ratio"] = [
        _val(value=2, basis="mole", target="ex:f/sp/co")]


def test_fractions_of_two_reactants_warn(doc):
    m = _msgs(doc)
    assert len(m) == 1 and IMPLIED in m[0] and "numerator gas" in m[0] and "origin curated" in m[0]


def test_ratios_key_warns_and_fractions_text_differs(doc):
    _feed(doc)["ratios"] = {"h2_co": _val(value=2)}
    m = _msgs(doc)
    assert len(m) == 2 and len({x for x in m}) == 2
    assert any(ONLY_MAP in x and "h2_co" in x for x in m) and any(IMPLIED in x for x in m)


@pytest.mark.parametrize("key", ["h2_co_ratio", "ph2_pco_ratio", "co_h2", "co_h2_n2"])
def test_ratio_keys(doc, key):
    for e in _edges(doc):
        e["props"].pop("fraction")
    _feed(doc)["ratios"] = {key: _val(value=2)}
    m = _msgs(doc)
    assert len(m) == 1 and ONLY_MAP in m[0] and key in m[0]


def test_value_text_naming_two_gases_warns(doc):
    for e in _edges(doc):
        e["props"].pop("fraction")
    _feed(doc)["ratios"] = {"syngas_ratio": _val(value=2, as_reported="H2/CO = 2")}
    assert len(_msgs(doc)) == 1 and ONLY_MAP in _msgs(doc)[0]


def test_non_gas_ratio_key_does_not_warn(doc):
    for e in _edges(doc):
        e["props"].pop("fraction")
    _feed(doc)["ratios"] = {"dilution_ratio": _val(value=2)}
    assert _msgs(doc) == []


def test_edge_ratio_silences_both(doc):
    _feed(doc)["ratios"] = {"h2_co": _val(value=2)}
    _ratio(doc)
    assert _msgs(doc) == []
    assert pgraph.validate(doc, spec_of(doc)).errors == []


def test_one_reactant_and_inert_diluent_do_not_warn(doc):
    _, h2 = _edges(doc)
    h2["props"]["role"] = "inert"
    assert _msgs(doc) == []
    h2["props"]["role"] = "diluent"
    assert _msgs(doc) == []


def test_empty_ratio_list_still_warns(doc):
    next(e for e in _edges(doc) if e["target"].endswith("/h2"))["props"]["ratio"] = []
    m = _msgs(doc)
    assert len(m) == 1 and IMPLIED in m[0]


def test_feed_without_component_edge_does_not_warn(doc):
    doc["links"] = [e for e in doc["links"] if e["type"] != "HAS_COMPONENT"]
    assert _msgs(doc) == []


@pytest.mark.parametrize("key", ["no_he", "ne_no", "he_ratio"])
def test_short_ambiguous_key_tokens_do_not_warn(doc, key):
    for e in _edges(doc):
        e["props"].pop("fraction")
    _feed(doc)["ratios"] = {key: _val(value=2)}
    assert _msgs(doc) == []


def test_warning_never_an_error(doc):
    r = pgraph.validate(doc, spec_of(doc))
    assert not any(e["record"] == FEED for e in r.errors)
    assert doc["nodes"] and _feed(doc).get("ratios") is None     # nothing is stored
