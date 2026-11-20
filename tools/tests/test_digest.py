"""One paper's digest (tools/digest.py; `scale source digest`; the first-paper skill): run on a single source cut out of
the public methanol example, looked up against the full methanol graph."""

import json
import subprocess
import sys

import pytest

from conftest import REPO
from scale import graphparts as gp
from scale.digest import digest, reaction_key, render
from scale.util import write_canonical

SLUG = "10.1021-ie50226a034"          # Frolich et al. 1928: oxides tested for methanol synthesis, some inactive
FULL = REPO / "graphs/methanol-synthesis-pre1966"


@pytest.fixture(scope="module")
def one():
    return gp.build(gp.subset(gp.read_parts(REPO / "examples/methanol-synthesis-public"), [SLUG]))


@pytest.fixture(scope="module")
def d(one):
    return digest(one, [FULL])


def test_every_test_is_listed_with_its_catalyst_conditions_and_results(d):
    rows = d["conditions_and_outcomes"]
    assert len(rows) == d["counts"]["CatalyticTest"] == 86
    zr = next(r for r in rows if "ZrO2" in r["catalyst"])
    assert "pressure 150 atm" in zr["conditions"] and "conversion ≤ 2 %" in zr["results"]


def test_has_this_been_done_excludes_the_paper_itself_and_says_not_found_honestly(d):
    by = {(r["elements"], r["reaction"]): r for r in d["has_this_been_done"]}
    cuzn = by[("Cu–Zn", "CO + H2 -> CH3OH")]
    assert cuzn["reported_before"] > 0 and cuzn["graphs"] == ["methanol-synthesis-pre1966"]
    assert by[("Zr", "CO + H2 -> CH3OH")]["reported_before"] == 0       # the paper's own ZrO2 tests do not count
    md = render(d)
    assert "not found" in md and "not new to the literature" in md


def test_negative_results_keep_bounds_and_zeros(d):
    why = [w for r in d["negative_results"] for w in r["why"]]
    assert "conversion ≤ 2 %" in why and "conversion 0 %" in why


def test_claims_and_hypotheses_stay_apart_and_flags_are_shown(d):
    assert len(d["claims"]) == 38 and len(d["hypotheses"]) == 2
    md = render(d)
    assert "## The authors' claims" in md and "**Hypotheses**" in md
    assert d["values"]["counts"]["flag"] == len(d["flagged_values"]) and "flagged" in md


def test_reactions_are_matched_by_their_species():
    r = lambda eq: {"id": "x", "props": {"equation": eq}}
    assert reaction_key(r("CO + 2 H2 -> CH3OH")) == reaction_key(r("2H2 + CO = CH3OH")) == "CO + H2 -> CH3OH"


def test_the_command(one, tmp_path):
    g = tmp_path / "one.graph.json"
    write_canonical(g, one)
    run = subprocess.run([sys.executable, "-m", "scale.cli", "--repo", str(REPO), "source", "digest", str(g),
                          "--against", str(FULL), "--format", "json"], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["references"] == ["methanol-synthesis-pre1966"]
