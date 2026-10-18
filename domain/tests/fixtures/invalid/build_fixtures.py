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
    # it states its access (public, like every committed document) but not who contributed it or its project
    defect("research-data-without-stewardship", "research data that does not say who contributed it or which project it belongs to",
           lambda d: d["graph"].__setitem__("stewardship", {"access": "public"}), base=template("catalysis", VERSION))


if __name__ == "__main__":
    main()
