"""precedents.py and check_quotes.py against SCALE's own tools, in this process, on the public synthesis examples.

Run from a checkout of hlxin/scale with the package installed:
    python -m pytest skills/query-graph/tests
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
REPO = HERE.parents[2]
EXAMPLES = REPO / "domain/examples/scale-catal/synthesis-examples"
sys.path.insert(0, str(SCRIPTS))

import check_quotes  # noqa: E402
import precedents  # noqa: E402


def call():
    from scale.api import ScaleToolkit
    return ScaleToolkit(repo=REPO).call


def test_precedents_rank_the_preparations_by_the_requirements_they_meet_the_first_weighing_most(tmp_path):
    reqs = [{"name": "Pd", "field": "catalyst.nominal_formula", "matches": "Pd(?![a-z])"},
            {"name": "cube", "field": "state.particle_shape", "matches": "cube"},
            {"name": "alumina", "field": "component.name", "matches": "alumin|Al2O3"}]
    res = call()("query", {"plan": json.loads(precedents.PLAN.read_text()),
                           "path": str(EXAMPLES / "synthesis-strategies.json")})
    out = precedents.rank(res["rows"], reqs, "prep.id", 8)
    first, second = out["candidates"][:2]
    assert first["key"] == "ex:syn/preparation/pd-cubes" and first["misses"] == []
    assert second["key"] == "ex:syn/preparation/pd-fsp" and second["meets"] == ["Pd"]   # Pd outweighs alumina
    by = {r["name"]: r for r in out["requirements"]}
    assert by["Pd"]["met_by"] == 2 and by["cube"]["met_by"] == 1
    assert by["cube"]["not_curated"] == 4         # no shape stated (Cu-SSZ-13 and its stages, Pt ALD "not_reported")
    assert out["closest_by_requirement"]["alumina"][0] == {"key": "ex:syn/preparation/pd-cubes",
                                                           "also_meets": ["Pd", "cube"]}
    # the command gives the same ranking through the tools of this process
    (tmp_path / "req.json").write_text(json.dumps(reqs))
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "precedents.py"), "--requirements", str(tmp_path / "req.json"),
                        "--graph", str(EXAMPLES / "synthesis-strategies.json"), "--out", str(tmp_path / "out.json")],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stderr[-600:]
    assert json.loads((tmp_path / "out.json").read_text())["candidates"][0]["key"] == "ex:syn/preparation/pd-cubes"


def test_a_size_is_compared_only_in_its_unit_and_a_missing_value_is_not_a_failure():
    size = {"name": "5 nm", "field": "size", "between": [4, 6], "unit": "nm"}
    assert precedents.meets(size, {"status": "present", "value": 5.1, "unit": "nm"}) is True
    assert precedents.meets(size, {"status": "present", "value": 9, "unit": "nm"}) is False
    assert precedents.meets(size, {"status": "present", "value": 5, "unit": "Å"}) == "other"
    assert precedents.meets(size, None) is None
    assert precedents.meets(size, {"status": "not_reported", "missing_reason": "not_stated_in_source"}) is None
    assert precedents.meets({"name": "cube", "field": "shape", "matches": "cube"}, ["not_reported"]) is None
    assert precedents.meets({"name": "cube", "field": "shape", "matches": "cube"}, ["rod", "Cube"]) is True


def test_check_quotes_finds_the_records_words_and_lists_the_basis_of_their_compositions(tmp_path):
    doc = json.loads((EXAMPLES / "synthesis-conditions.json").read_text())
    quote = "the support was contacted with the Pt solution at pH 9 for one hour"
    step = next(n for n in doc["nodes"] if n["label"] == "ProcedureStep" and "pt-sea-9" in n["id"])
    step["props"]["evidence"][0]["quote"] = quote
    (tmp_path / "doc.json").write_text(json.dumps(doc))
    proposal = (f'Base: `ex:cnd/preparation/pt-sea-9`: "{quote}". A record that is no preparation: '
                f'`ex:cnd/preparation/none`. Words no record holds: "the support was boiled in aqua regia for a day". '
                f'Written short: `cnd/preparation/pt-sea-11`.')
    res = check_quotes.check(proposal, str(tmp_path / "doc.json"), call())
    assert res["named"] == ["ex:cnd/preparation/pt-sea-9"] and res["not_a_preparation"] == ["ex:cnd/preparation/none"]
    assert res["written_short"] == ["cnd/preparation/pt-sea-11"]
    assert [q["found"] for q in res["quotes"]] == [True, False] and res["failures"] == 2
    pt = next(c for c in res["compositions"]["ex:cnd/preparation/pt-sea-9"] if c["role"] == "active_component")
    assert pt["share"].startswith("1 % (by mass") and pt["share"].endswith("basis not stated")
