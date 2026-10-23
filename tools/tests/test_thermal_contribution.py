"""An analysis that separates the heating a driving force causes from its other effects (scale-catal 0.7.4): an Analysis of
analysis_kind thermal_contribution for light or a plasma, its partition_method and its shares as result entries; the
deprecated ThermalContributionAnalysis, still valid and reported as deprecated; and the light checklist, which accepts
either form."""

import copy

import pytest

from conftest import EXAMPLES, spec_of
from scale import pgraph
from scale.pgraph_profiles import conformance
from scale.util import load_doc

THERMAL = EXAMPLES / "scale-catal/thermal-examples/thermal-contribution.json"
EVIDENCE = EXAMPLES / "scale-catal/evidence-examples/kinetic-evidence.json"
P = "ex:tc"


@pytest.fixture()
def doc():
    return copy.deepcopy(load_doc(THERMAL))


def node(d: dict, local: str) -> dict:
    return next(n for n in d["nodes"] if n["id"] == f"{P}/{local}")


def warnings(d: dict) -> list[str]:
    return [w["message"] for w in pgraph.validate(d, spec_of(d)).warnings]


def report(d: dict) -> dict:
    return conformance(d, spec_of(d))["profiles"]["catalysis"]


def test_the_example_is_valid_with_no_warning_and_finds_every_piece_of_evidence(doc):
    rep = pgraph.validate(doc, spec_of(doc))
    assert rep.ok and rep.warnings == [], rep.warnings
    r = report(doc)
    assert r["evidence"]["found"] == r["evidence"]["expected"] == 8
    kinds = {n["props"].get("analysis_kind") for n in doc["nodes"] if n["label"] == "Analysis"}
    assert kinds == {"thermal_contribution"}


def test_the_deprecated_label_stays_valid_and_says_what_replaces_it(doc):
    sep = node(doc, "analysis/irradiance-dependence")
    sep["label"] = "ThermalContributionAnalysis"
    rep = pgraph.validate(doc, spec_of(doc))
    assert rep.ok
    said = [w["message"] for w in rep.warnings if w["record"] == sep["id"]]
    assert said == ["ThermalContributionAnalysis is deprecated; record it as an Analysis with analysis_kind "
                    "thermal_contribution (scale-catal 0.7.4), whose partition_method is the analysis's own and whose "
                    "shares are result entries; it stays valid"]
    assert report(doc)["evidence"]["found"] == 8            # the checklist still finds the light-heat separation


def test_a_document_of_an_earlier_version_is_not_told_its_label_is_deprecated():
    d = load_doc(EVIDENCE)                                     # pins 0.7.1, when ThermalContributionAnalysis was current
    assert any(n["label"] == "ThermalContributionAnalysis" for n in d["nodes"])
    assert not [m for m in warnings(d) if "deprecated" in m]


def test_light_heat_separation_rests_on_the_analysis_and_a_surface_match_on_the_dark_control(doc):
    def missing(d):
        return report(d).get("missing_evidence") or {}
    # without its analysis the photothermal reading has nothing that separates light from heat
    d = copy.deepcopy(doc)
    d["links"] = [e for e in d["links"] if not (e["type"] == "HAS_INPUT" and e["source"] == f"{P}/analysis/irradiance-dependence")]
    assert missing(d).get("light_heat_separation") == 1
    # a non-thermal reading needs a match at the illuminated surface: an analysis resting on a control at matched
    # temperature is no such match, one resting on a dependence is
    d = copy.deepcopy(doc)
    d["links"] = [e for e in d["links"] if e["type"] != "DARK_CONTROL_FOR"]
    assert missing(d).get("local_temperature_match") == 1
    node(d, "analysis/dark-control-comparison")["props"]["partition_method"] = "wavelength_dependence"
    assert "local_temperature_match" not in missing(d)


def test_the_new_kind_asks_how_it_separated_and_what_it_found(doc):
    sep = node(doc, "analysis/plasma-heating")["props"]
    del sep["partition_method"], sep["result_values"]
    m = report(doc)["missing_recommended"]
    assert m.get("Analysis.partition_method") == 1 and m.get("Analysis.result_values") == 1


def test_describe_says_what_replaces_a_deprecated_label(doc):
    out = pgraph.describe(spec_of(doc), ["ThermalContributionAnalysis", "Analysis"])
    assert out["labels"]["ThermalContributionAnalysis"]["deprecated"].startswith("an Analysis with analysis_kind thermal_contribution")
    assert "deprecated" not in out["labels"]["Analysis"]
    assert "partition_method" in out["labels"]["Analysis"]["properties"]


def test_a_control_alone_is_not_the_test_an_analysis_separates(doc):
    """The plasma analysis compares the plasma test with the catalyst without plasma; with only the control left, the
    checklist does not find the test it separates."""
    doc["links"] = [e for e in doc["links"] if not (e["type"] == "HAS_INPUT" and e["source"] == f"{P}/analysis/plasma-heating"
                                                    and e["target"] == f"{P}/test/plasma-catalyst")]
    assert (report(doc).get("missing_evidence") or {}).get("separated_test") == 1
