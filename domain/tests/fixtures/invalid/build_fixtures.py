"""Build the invalid scale-catal fixtures from a valid public example, one defect each.

`scale check` (step "invalid scale-catal fixtures are rejected for their stated reasons") and
domain/tests/test_invalid_fixtures.py validate every document here and require that it is
rejected with the error stated in expect.yaml. Every fixture pins the schema version its base example
pins (VERSION, read from the example, never spelled here) and is checked under that version, so a
schema change that raises the head leaves them failing for their stated reasons. After `scale graph migrate`
moves the examples, or after a schema change that alters an error message, rerun this script and review
the diff:
python domain/tests/fixtures/invalid/build_fixtures.py
"""

import copy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _repo() -> Path:
    for base in (HERE, Path.cwd().resolve()):
        for p in [base, *base.parents]:
            if (p / "scale-release.yaml").exists() and (p / "releases").is_dir():
                return p
    raise SystemExit("run inside a SCALE repository checkout")


REPO = _repo()
sys.path.insert(0, str(REPO / "tools"))

from scale.api import template  # noqa: E402
from scale.util import load_doc, write_canonical  # noqa: E402

BASE = REPO / "domain/examples/scale-catal/driving-force-examples/electro.json"
VERSION = load_doc(BASE)["graph"]["schema_version"]      # the version a fixture pins: its base example's
# what a later schema version added is shown wrong on an example of that version (expect.yaml names it as base)
AGENTIC = REPO / "domain/examples/scale-catal/agentic-examples/self-driving-campaign.json"
TRANSIENT = REPO / "domain/examples/scale-catal/transient-examples/transient-kinetics.json"


def test_node(doc: dict) -> dict:
    return next(n for n in doc["nodes"] if n["label"] == "CatalyticTest")


def node(doc: dict, local: str) -> dict:
    return next(n for n in doc["nodes"] if n["id"].endswith("/" + local))


def component(doc: dict, local: str) -> dict:
    """The electrolyte's HAS_COMPONENT link to the species ``local``."""
    return next(e for e in doc["links"] if e["type"] == "HAS_COMPONENT" and e["target"].endswith("/" + local))


def result(doc: dict, **entry) -> dict:
    """The test with one Faradaic efficiency in result_values (a Variable of kind faradaic_efficiency, the evidence item
    that states it); ``entry`` changes or (None) drops its fields. Returns the test."""
    t = test_node(doc)
    var = {"id": "ex:df-electro/variable/fe", "label": "Variable",
           "props": {"name": "Faradaic efficiency", "scale": "quantitative", "quantity_kind": "faradaic_efficiency",
                     "unit": "%", "origin": "synthetic"}}
    doc["nodes"].append(var)
    t["props"]["evidence"].append({"id": "fe_table", "source": "ex:df-electro/source/paper", "locator": "Table 1",
                                   "kind": "table"})
    x = {"id": "nh3_fe", "status": "present", "value": 92, "unit": "%", "variable": var["id"],
         "target": node(doc, "species/ammonia")["id"], "evidence_ids": ["fe_table"]}
    for k, v in entry.items():
        if v is None:
            x.pop(k, None)
        else:
            x[k] = v
    t["props"]["result_values"] = [x]
    return t


def site_population(doc: dict, **props) -> dict:
    """A working state of the sample (STATE_OF it) and a HAS_SITE from it to a Cu step site, with ``props`` (its
    population values) and the evidence item they cite (``hs_table``). Returns the link."""
    sample = node(doc, "sample/cu")["id"]
    src = "ex:df-electro/source/paper"
    doc["nodes"] += [{"id": "ex:df-electro/state/working", "label": "CatalystState",
                      "props": {"name": "working, at -0.6 V vs RHE", "state_kind": "working", "origin": "synthetic"}},
                     {"id": "ex:df-electro/site/cu-step", "label": "ActiveSite",
                      "props": {"name": "Cu step site", "site_kind": "step_edge", "origin": "synthetic"}}]
    doc["links"].append({"id": "ex:df-electro/state/working/state-of", "type": "STATE_OF", "source": "ex:df-electro/state/working",
                         "target": sample, "props": {"origin": "synthetic"}})
    link = {"id": "ex:df-electro/state/working/has-site", "type": "HAS_SITE", "source": "ex:df-electro/state/working",
            "target": "ex:df-electro/site/cu-step",
            "props": {"status": "hypothesized", "origin": "synthetic", **props,
                      "evidence": [{"id": "hs_table", "source": src, "locator": "Table 2", "kind": "table"}]}}
    doc["links"].append(link)
    return link


def tof_over(doc: dict, normalized_by: dict) -> dict:
    """The test with one ammonia turnover frequency in result_values (a Variable of kind turnover_frequency, the evidence
    item that states it), divided by what ``normalized_by`` names. Returns the test."""
    t = test_node(doc)
    var = {"id": "ex:df-electro/variable/tof", "label": "Variable",
           "props": {"name": "ammonia turnover frequency", "scale": "quantitative", "quantity_kind": "turnover_frequency",
                     "unit": "s-1", "origin": "synthetic"}}
    doc["nodes"].append(var)
    t["props"]["evidence"].append({"id": "tof_table", "source": "ex:df-electro/source/paper", "locator": "Table 2",
                                   "kind": "table"})
    t["props"]["result_values"] = [{"id": "nh3_tof", "status": "present", "value": 0.8, "unit": "s-1", "variable": var["id"],
                                    "target": node(doc, "species/ammonia")["id"], "normalized_by": normalized_by,
                                    "evidence_ids": ["tof_table"]}]
    return t


def defect(name: str, title: str, change, base: dict | None = None) -> None:
    doc = copy.deepcopy(base or load_doc(BASE))
    doc["graph"]["graph_id"] = f"ex:invalid/{name}"
    doc["graph"]["title"] = f"INVALID FIXTURE ({name}): {title}"
    change(doc)
    write_canonical(HERE / f"{name}.json", doc)


def main() -> None:
    defect("dangling-link", "a link whose target is no record of the document",
           lambda d: d["links"].append({"id": "ex:invalid/dangling", "type": "OF_REACTION", "source": test_node(d)["id"],
                                        "target": "ex:df-electro/reaction/missing", "props": {"origin": "synthetic"}}))
    defect("unknown-property", "a property the label does not declare (an invented attribute)",
           lambda d: test_node(d)["props"].__setitem__("site_turnover", {"status": "present", "value": 1.2, "unit": "1/s"}))
    defect("value-without-status", "a value object without its status",
           lambda d: test_node(d)["props"]["current_density"].pop("status"))
    defect("enum-value-not-allowed", "an enumerated property with a value outside its list",
           lambda d: test_node(d)["props"].__setitem__("control_mode", "manual"))
    defect("edge-endpoint-not-allowed", "an edge type between labels it does not join",
           lambda d: d["links"].append({"id": "ex:invalid/source-uses-catalyst", "type": "USES_CATALYST",
                                        "source": "ex:df-electro/source/paper", "target": "ex:df-electro/sample/cu",
                                        "props": {"origin": "synthetic"}}))
    defect("evidence-without-locator", "evidence that does not say where in the source it is",
           lambda d: test_node(d)["props"]["evidence"][0].pop("locator"))
    defect("reported-in-without-evidence", "a REPORTED_IN link that no evidence of its record backs",
           lambda d: test_node(d)["props"].pop("evidence"))
    # quantity contracts (0.3.0): a unit of another dimension than the property's kind, a concentration stored as a
    # fraction, and a normalization reference that names no denominator, a value of another dimension or no property
    defect("temperature-in-kg", "a temperature in a unit of mass",
           lambda d: test_node(d)["props"].__setitem__("temperature", {"status": "present", "value": 298, "unit": "kg"}))
    defect("fraction-in-mol-per-litre", "an electrolyte's concentration stored as a dimensionless fraction",
           lambda d: component(d, "nitrate")["props"].__setitem__("fraction", component(d, "nitrate")["props"].pop("concentration")))
    defect("normalized-by-without-denominator", "a temperature that names what it is divided by",
           lambda d: test_node(d)["props"]["temperature"].__setitem__(
               "normalized_by", {"record": node(d, "electrode/cu-on-cp")["id"], "path": "/geometric_area"}))
    defect("normalized-by-wrong-dimension", "a current density divided by a catalyst loading (a mass per area)",
           lambda d: test_node(d)["props"]["current_density"].__setitem__(
               "normalized_by", {"record": node(d, "electrode/cu-on-cp")["id"], "path": "/catalyst_loading"}))
    defect("normalized-by-unresolved-path", "a current density divided by an electrode area the electrode does not hold",
           lambda d: test_node(d)["props"]["current_density"].__setitem__(
               "normalized_by", {"record": node(d, "electrode/cu-on-cp")["id"], "path": "/electrochemically_active_area"}))
    # result entries (0.4.0): a product that is no chemical species, an entry without its variable, id or evidence, an
    # id named twice, a product neither named nor said to be unidentified, both at once, and a reference by position
    defect("product-target-is-a-source", "a Faradaic efficiency whose product is the source document",
           lambda d: result(d, target="ex:df-electro/source/paper"))
    defect("result-without-variable", "a result entry that does not say what it is a value of",
           lambda d: result(d, variable=None))
    defect("result-without-id", "a result entry without the id a reference names it by",
           lambda d: result(d, id=None))
    def repeat_id(d: dict) -> None:
        entries = result(d)["props"]["result_values"]
        entries.append(dict(entries[0], value=88, phase="liquid"))          # told apart by its phase; only its id repeats
    defect("result-ids-repeat", "two result entries with one id", repeat_id)
    defect("result-without-evidence-ids", "a result entry that states a value but not the evidence that states it",
           lambda d: result(d, evidence_ids=None))
    defect("product-result-without-identity", "a Faradaic efficiency that neither names its product nor says it is unidentified",
           lambda d: result(d, target=None))
    defect("target-and-unresolved-target", "a result that names its product and says the product is unidentified",
           lambda d: result(d, unresolved_target="unidentified nitrogen products"))

    def by_position(d: dict) -> None:
        t = result(d)
        d["nodes"].append({"id": "ex:df-electro/hypothesis/selective", "label": "Hypothesis",
                           "props": {"name": "Cu reduces nitrate to ammonia selectively", "hypothesis_kind": "descriptive",
                                     "statement": "Cu reduces nitrate to ammonia with a Faradaic efficiency above 90 %.",
                                     "origin": "synthetic"}})
        d["links"].append({"id": "ex:invalid/tests-by-position", "type": "TESTS", "source": t["id"],
                           "target": "ex:df-electro/hypothesis/selective",
                           "props": {"outcome": "supports", "origin": "synthetic",
                                     "result_refs": [{"record": t["id"], "path": "/result_values/0"}]}})
    defect("result-ref-by-position", "a test outcome that names the result it rests on by its position in result_values",
           by_position)
    defect("interpretation-not-in-vocabulary", "a test read as something its vocabulary does not name",
           lambda d: test_node(d)["props"].__setitem__("interpretations", ["catalytic_synergy"]))

    def transport_check(doc):
        t = test_node(doc)
        doc["nodes"].append({"id": "ex:df-electro/analysis/transport", "label": "Analysis",
                             "props": {"name": "Mass transport check", "analysis_kind": "transport_check",
                                       "evaluation_basis": "estimated", "origin": "synthetic"}})
        doc["links"].append({"id": "ex:df-electro/analysis/transport/has-input/1", "type": "HAS_INPUT",
                             "source": "ex:df-electro/analysis/transport", "target": t["id"],
                             "props": {"role": "data", "origin": "synthetic"}})
    defect("transport-basis-not-in-vocabulary", "a transport check whose basis is neither asserted, numerical nor experimental",
           transport_check)
    # site populations of a catalyst state (0.6.0): a site that a test has, a share in a unit of a count, a count in a unit
    # of a surface area, a computed count that does not name its computation, a rate per site divided by a share, and an
    # operando pairing stated in words the vocabulary does not hold
    def site_of_test(d: dict) -> None:
        site_population(d, population_fraction={"status": "present", "value": 10, "unit": "%", "basis": "of the exposed Cu",
                                                "evidence_ids": ["hs_table"]})
        has = next(e for e in d["links"] if e["type"] == "HAS_SITE")
        has["source"] = test_node(d)["id"]
    defect("has-site-from-a-test", "a catalytic test that has a site population", site_of_test)
    defect("site-fraction-in-umol-per-gram", "a share of sites stated in a unit of a count per mass",
           lambda d: site_population(d, population_fraction={"status": "present", "value": 30, "unit": "µmol/g",
                                                             "evidence_ids": ["hs_table"]}))
    defect("site-inventory-as-surface-area", "a count of sites stated as a metal surface area",
           lambda d: site_population(d, site_inventory={"status": "present", "value": 25, "unit": "m2/g",
                                                        "evidence_ids": ["hs_table"]}))
    defect("computed-site-count-without-producer", "a computed count of sites that does not name the computation",
           lambda d: site_population(d, site_inventory={"status": "present", "value": 12, "unit": "µmol/g",
                                                        "origin": "computed", "evidence_ids": ["hs_table"]}))

    def tof_per_share(d: dict) -> None:
        link = site_population(d, population_fraction={"status": "present", "value": 10, "unit": "%",
                                                       "basis": "of the exposed Cu atoms", "evidence_ids": ["hs_table"]})
        tof_over(d, {"record": link["id"], "path": "/population_fraction"})
    defect("tof-divided-by-a-share", "a turnover frequency divided by a share of sites, not by a count", tof_per_share)

    def operando_words(d: dict) -> None:
        d["nodes"].append({"id": "ex:df-electro/characterization/xas", "label": "Characterization",
                           "props": {"name": "Cu K-edge XAS during the electrolysis", "technique": "XAS",
                                     "observation_mode": "operando", "origin": "synthetic"}})
        d["links"].append({"id": "ex:df-electro/characterization/xas/during", "type": "DURING",
                           "source": "ex:df-electro/characterization/xas", "target": test_node(d)["id"],
                           "props": {"specimen": "same_reactor", "origin": "synthetic"}})
    defect("operando-specimen-not-in-vocabulary", "an operando observation whose specimen is stated in other words",
           operando_words)
    # computed energies and kinetic parameters (0.7.0): an adsorption energy whose process is a species, an elementary
    # activation energy in volts, and a charge treatment stated in words the vocabulary does not hold
    def computation(d: dict, **props) -> dict:
        c = {"id": "ex:df-electro/computation/dft", "label": "Computation",
             "props": {"name": "DFT of nitrate on Cu(111)", "computation_kind": "electronic_structure",
                       "level_of_theory": {"status": "present", "text_value": "RPBE"}, "origin": "synthetic",
                       "evidence": [{"id": "dft_table", "source": "ex:df-electro/source/paper", "locator": "Table 3",
                                     "kind": "table"}], **props}}
        d["nodes"].append(c)
        d["links"].append({"id": "ex:df-electro/computation/dft/reported-in", "type": "REPORTED_IN", "source": c["id"],
                           "target": "ex:df-electro/source/paper", "props": {"origin": "synthetic"}})
        return c

    def energy_of_a_species(d: dict) -> None:
        d["nodes"].append({"id": "ex:df-electro/variable/adsorption-energy", "label": "Variable",
                           "props": {"name": "nitrate adsorption energy", "scale": "quantitative",
                                     "quantity_kind": "reaction_energy", "unit": "eV", "origin": "synthetic"}})
        computation(d, result_values=[{"id": "nitrate_adsorption", "status": "present", "value": -1.2, "unit": "eV",
                                       "variable": "ex:df-electro/variable/adsorption-energy",
                                       "target": node(d, "species/nitrate")["id"], "evidence_ids": ["dft_table"]}])
    defect("adsorption-energy-of-a-species", "an adsorption energy whose target is the adsorbate, not the reaction that "
           "defines it", energy_of_a_species)

    def barrier_in_volts(d: dict) -> None:
        c = computation(d)
        d["nodes"].append({"id": "ex:df-electro/step/no3-dissociation", "label": "ElementaryStep",
                           "props": {"name": "NO3* -> NO2* + O*", "origin": "synthetic",
                                     "activation_energy": {"status": "present", "value": 0.7, "unit": "V",
                                                           "origin": "computed", "produced_by": c["id"]}}})
    defect("activation-energy-in-volts", "an elementary step's activation energy in volts", barrier_in_volts)
    defect("charge-treatment-not-in-vocabulary", "a computation whose charge treatment is stated in other words",
           lambda d: computation(d, charge_treatment="grand_canonical"))
    def result_of_kind(d: dict, kind: str, unit: str, value) -> None:
        """The test with one result of ``kind`` in ``unit`` (a Variable of that kind, the evidence item that states it)."""
        t = test_node(d)
        d["nodes"].append({"id": f"ex:df-electro/variable/{kind}", "label": "Variable",
                           "props": {"name": kind.replace("_", " "), "scale": "quantitative", "quantity_kind": kind,
                                     "origin": "synthetic"}})
        t["props"]["evidence"].append({"id": f"{kind}_table", "source": "ex:df-electro/source/paper",
                                       "locator": "Table 2", "kind": "table"})
        t["props"].setdefault("result_values", []).append(
            {"status": "present", "value": value, "unit": unit, "id": kind, "variable": f"ex:df-electro/variable/{kind}",
             "target": "ex:df-electro/species/ammonia", "evidence_ids": [f"{kind}_table"]})
    defect("turnover-number-per-second", "a turnover number in reciprocal seconds",
           lambda d: result_of_kind(d, "turnover_number", "s-1", 0.8))
    defect("enzyme-activity-in-kilojoules", "an enzyme activity in kilojoules",
           lambda d: result_of_kind(d, "enzyme_activity", "kJ", 12))
    defect("catalysis-mode-not-in-vocabulary", "a test whose catalysis mode is stated in other words",
           lambda d: test_node(d)["props"].__setitem__("catalysis_mode", "slurry"))
    # a person's checks of the records (graph.checks) and what TRACE-AI asks of an agentic campaign, 0.7.2 on
    agentic = load_doc(AGENTIC)

    def check(d: dict) -> dict:
        return d["graph"]["checks"][0]
    defect("check-names-unknown-record", "a person's check that names a record the graph does not hold",
           lambda d: check(d)["records"].append("ex:sdl/test/round-9"), base=agentic)
    defect("check-counts-more-wrong-than-checked", "a check that counts more fields wrong than it checked",
           lambda d: check(d).__setitem__("fields_wrong", 50), base=agentic)
    defect("acknowledgement-on-an-unchecked-record", "a warning acknowledged on a record the check does not cover",
           lambda d: check(d)["records"].remove("ex:sdl/design/campaign"), base=agentic)
    defect("autonomy-level-not-in-vocabulary", "a campaign whose level of autonomy is not on the TRACE-AI scale",
           lambda d: node(d, "design/campaign")["props"].__setitem__("autonomy_level", "A6"), base=agentic)
    defect("split-strategy-not-in-vocabulary", "a validation whose split is stated in other words",
           lambda d: next(e for e in d["links"] if (e["props"] or {}).get("split_strategy") == "random")["props"]
           .__setitem__("split_strategy", "shuffled"), base=agentic)
    # a test's program, the analyses of its responses and kinetic constants fitted to them, 0.7.3 on
    transient = load_doc(TRANSIENT)

    def entry(d: dict, local: str, key: str) -> dict:
        return next(v for v in node(d, local)["props"]["result_values"] if v["id"] == key)
    defect("waveform-not-in-vocabulary", "a modulation whose waveform is stated in other words",
           lambda d: node(d, "operation/co-square-wave")["props"].__setitem__("waveform", "rectangular"), base=transient)
    defect("program-detail-not-in-vocabulary", "a program whose detail is stated in other words",
           lambda d: node(d, "operation/co2-sequence")["props"].__setitem__("program_detail", "complete"), base=transient)
    defect("residence-time-in-kelvin", "a surface residence time in kelvin",
           lambda d: entry(d, "analysis/ssitka-co2", "tau_co2").__setitem__("unit", "K"), base=transient)
    defect("reactor-model-not-in-vocabulary", "a kinetic fit whose reactor treatment is stated in other words",
           lambda d: node(d, "analysis/fit-plug-flow")["props"].__setitem__("reactor_model", "pfr"), base=transient)
    defect("interval-method-not-in-vocabulary", "an interval whose method is stated in other words",
           lambda d: entry(d, "analysis/fit-differential", "ea_co2_dissociation").__setitem__("interval_method", "hessian"),
           base=transient)
    defect("phase-reference-not-in-vocabulary", "phase delays whose reference is stated in other words",
           lambda d: node(d, "analysis/phase-sensitive-detection")["props"].__setitem__("phase_reference", "input"),
           base=transient)
    # it states its access (public, like every committed document) but not who contributed it or its project
    defect("research-data-without-stewardship", "research data that does not say who contributed it or which project it belongs to",
           lambda d: d["graph"].__setitem__("stewardship", {"access": "public"}), base=template("catalysis", VERSION))


if __name__ == "__main__":
    main()
