"""The methods calculations apply, as records of their own, and the calculations that failed (scale-catal 0.7.5): a
method's kind and names, the check that a computation's level of theory is a name of the method it uses, benchmarks of
a method, and a failed calculation with what stopped it and the rerun that succeeded."""

import copy

import pytest

from conftest import EXAMPLES, spec_of
from scale import pgraph
from scale.pgraph_profiles import conformance
from scale.util import load_doc

METHODS = EXAMPLES / "scale-catal/method-examples/computational-methods.json"
P = "ex:cm"


@pytest.fixture()
def doc():
    return copy.deepcopy(load_doc(METHODS))


def node(d: dict, local: str) -> dict:
    return next(n for n in d["nodes"] if n["id"] == f"{P}/{local}")


def links(d: dict, typ: str, source: str | None = None, target: str | None = None) -> list[dict]:
    return [e for e in d["links"] if e["type"] == typ and (source is None or e["source"] == f"{P}/{source}")
            and (target is None or e["target"] == f"{P}/{target}")]


def warnings(d: dict) -> list[str]:
    return [w["message"] for w in pgraph.validate(d, spec_of(d)).warnings]


def missing(d: dict) -> dict:
    return conformance(d, spec_of(d))["profiles"]["catalysis"]["missing_recommended"]


def test_the_example_is_valid_with_no_warning(doc):
    rep = pgraph.validate(doc, spec_of(doc))
    assert rep.ok and rep.warnings == [], rep.warnings
    assert node(doc, "method/rpbe")["props"]["method_kind"] == "exchange_correlation_functional"
    assert node(doc, "method/rpbe")["props"]["identifiers"] == {"libxc": "GGA_X_RPBE+GGA_C_PBE"}
    assert {e["target"] for e in links(doc, "USES_METHOD", source="computation/o-ni111")} == {
        f"{P}/method/rpbe", f"{P}/method/d3"}


def test_a_level_of_theory_must_be_a_name_of_the_method_it_uses(doc):
    comp = node(doc, "computation/o-pt111")["props"]
    comp["level_of_theory"]["text_value"] = "PBE"                       # it uses RPBE
    said = [m for m in warnings(doc) if "is none of the names of the electronic-structure method" in m]
    assert said == ["level_of_theory 'PBE' is none of the names of the electronic-structure method it uses (RPBE); a "
                    "comparison reads level_of_theory, so state the method's name there, or add the source's name to its "
                    "aliases"]
    comp["level_of_theory"]["text_value"] = "revised PBE of Hammer, Hansen and Nørskov"     # an alias
    assert not [m for m in warnings(doc) if "none of the names" in m]
    node(doc, "computation/benchmark-beef-vdw")["props"]["level_of_theory"]["text_value"] = "beef vdw"
    assert not [m for m in warnings(doc) if "none of the names" in m]    # case, spaces and hyphens ignored
    # a dispersion correction alone names no electronic-structure method: nothing to match
    d2 = load_doc(METHODS)
    d2["links"] = [e for e in d2["links"] if not (e["type"] == "USES_METHOD" and e["source"] == f"{P}/computation/o-ni111"
                                                  and e["target"] == f"{P}/method/rpbe")]
    node(d2, "computation/o-ni111")["props"]["level_of_theory"]["text_value"] = "RPBE-D3"
    assert not [m for m in warnings(d2) if "none of the names" in m]


def test_a_benchmark_evaluates_the_method_and_a_claim_is_about_it(doc):
    bench = {e["source"]: e["props"] for e in links(doc, "EVALUATES") if e["target"].startswith(f"{P}/method/")}
    assert set(bench) == {f"{P}/computation/benchmark-{k}" for k in ("pbe", "rpbe", "beef-vdw")}
    assert {p["evaluation_kind"] for p in bench.values()} == {"benchmark"}
    (about,) = links(doc, "ABOUT", source="claim/pbe-overbinds")
    assert about["target"] == f"{P}/method/pbe"


def test_the_checklist_asks_a_failed_calculation_what_stopped_it(doc):
    assert not missing(doc).get("Computation.status_reason")
    del node(doc, "computation/o-ni111-first-attempt")["props"]["status_reason"]
    del node(doc, "computation/o-diffusion-first-attempt")["props"]["failure_kind"]
    m = missing(doc)
    assert m.get("Computation.status_reason") == 1 and m.get("Computation.failure_kind") == 1


def test_a_rerun_shows_what_made_a_failed_calculation_succeed(doc):
    first = node(doc, "computation/o-ni111-first-attempt")["props"]
    assert first["experiment_status"] == "failed" and first["failure_kind"] == "electronic_not_converged"
    (retry,) = links(doc, "REPLICATES", target="computation/o-ni111-first-attempt")
    rerun = node(doc, "computation/o-ni111")["props"]
    changed = {k for k in set(first["settings"]) | set(rerun["settings"])
               if first["settings"].get(k) != rerun["settings"].get(k)}
    assert retry["props"]["level"] == "repeat" and changed == {"initial_magnetic_moments", "density_mixing"}


def test_malformed_aliases_are_reported_never_raised(doc):
    node(doc, "method/rpbe")["props"]["aliases"] = 1
    rep = pgraph.validate(doc, spec_of(doc))                            # no exception: the type check reports it
    assert not rep.ok and any(e["message"] == "aliases: expected a list" for e in rep.errors)
