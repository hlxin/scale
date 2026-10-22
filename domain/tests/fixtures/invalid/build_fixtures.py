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
VERSION = load_doc(BASE)["graph"]["schema_version"]      # the one version every fixture pins: the base example's


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
    # it states its access (public, like every committed document) but not who contributed it or its project
    defect("research-data-without-stewardship", "research data that does not say who contributed it or which project it belongs to",
           lambda d: d["graph"].__setitem__("stewardship", {"access": "public"}), base=template("catalysis", VERSION))

    # multifunctional catalysts (#40): an integration mode outside its list, a function that is no reaction (a species, a
    # record that does not exist), a function on a link that is no component, a proximity without its status
    bi = REPO / "domain/examples/scale-catal/bifunctional-examples/tandem-granule-mixture.json"

    def bifunctional(change):
        return lambda d: change(d, next(n for n in d["nodes"] if n["id"] == "ex:bifunctional/catalyst/tandem"),
                                next(e for e in d["links"] if e["id"] == "ex:bifunctional/link/1"))
    defect("integration-mode-not-allowed", "an integration mode the list does not name",
           bifunctional(lambda d, c, e: c["props"].__setitem__("integration_mode", "sandwich")), base=load_doc(bi))
    defect("function-is-a-species", "a component whose function is a chemical species, not a reaction",
           bifunctional(lambda d, c, e: e["props"].__setitem__("function", ["ex:bifunctional/species/co"])), base=load_doc(bi))
    defect("function-is-no-record", "a component whose function is a reaction the document does not hold",
           bifunctional(lambda d, c, e: e["props"].__setitem__("function", ["ex:bifunctional/reaction/missing"])), base=load_doc(bi))
    defect("function-on-has-part", "a function stated on a HAS_PART link, which does not declare it",
           bifunctional(lambda d, c, e: next(x for x in d["links"] if x["type"] == "HAS_PART")["props"].__setitem__(
               "function", ["ex:bifunctional/reaction/step1"])), base=load_doc(bi))
    defect("site-proximity-without-status", "a site proximity without its status",
           bifunctional(lambda d, c, e: c["props"]["site_proximity"].pop("status")), base=load_doc(bi))


if __name__ == "__main__":
    main()
