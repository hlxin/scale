"""One-time revision of the curated fragments (2026-09-28 review, before GALAXY bundle 2.2.0).

    python revise_units_species_names.py [--check]

Edits curation/fragments/*.json in place; --check only reports what it would change. Idempotent.

1. Units spelled as printed but not as units become the unit they denote; the printed text stays in
   ``as_reported`` and a note says what was read:
   ``kg./cm2`` -> ``kg/cm2``, ``mm. Hg`` -> ``mm Hg``, ``°K`` -> ``K``, ``atmospheres`` -> ``atm``;
   a pressure printed in ``mm`` -> ``mm Hg``; a pressure printed in ``pounds`` -> ``lb/in2``;
   ``kg/cm3`` (a misprint in PL 9584) -> ``kg/cm2``.
2. A number printed without a unit keeps ``"unit": "not stated"`` (curation/GUIDE.md §5a):
   ``"unit not printed"`` and a space velocity in ``"1"`` are rewritten; a value with no number
   loses the unit ``"1"``.
3. A pressure printed as "atmospheric" (text_value atmospheric, atmospheric pressure, near
   atmospheric) is recorded as 1 atm, approximate, with the printed text in ``as_reported``.
4. Source-scoped species that are the shared species of the same formula take the shared id; the
   shared ``species/c`` becomes ``species/carbon``; the unused ``species/mgoh2`` is removed.
5. Records of one source that share a name get the distinguishing claim, run or example number.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

def _repo_root(*starts: Path) -> Path:
    """The SCALE checkout (scale-release.yaml and releases/), searched upward from each start in turn."""
    for p in (q for s in starts for q in (s, *s.parents)):
        if (p / "scale-release.yaml").exists() and (p / "releases").is_dir():
            return p
    raise SystemExit("run inside a SCALE repository checkout: no scale-release.yaml and releases/ above "
                     + ", ".join(map(str, starts)))


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_repo_root(HERE, Path.cwd()) / "tools"))
sys.path.insert(0, str(HERE))
from scale.util import dump_canonical  # noqa: E402
from curation import FRAGMENTS, MERGED_SPECIES  # noqa: E402   (the fragments are in the restricted copy)

UNIT_SPELLING = {"kg./cm2": "kg/cm2", "mm. Hg": "mm Hg", "°K": "K", "atmospheres": "atm"}
ATMOSPHERIC = {"atmospheric", "atmospheric pressure", "near atmospheric"}
SPECIES_IDS = MERGED_SPECIES
REMOVE = {"ex:msyn/species/mgoh2"}
NAME_SUFFIX = {  # record id -> text appended to its name
    "ex:msyn/10.1021-ie50225a025/test/table1-bzc-350a": " (run a)",
    "ex:msyn/10.1021-ie50225a025/test/table1-bzc-350b": " (run b)",
    "ex:msyn/hid-20090/test/series2-300c-run1": " (run 1)",
    "ex:msyn/hid-20090/test/series2-300c-run2": " (run 2)",
    "ex:msyn/hid-20090/test/series2-320c-run1": " (run 1)",
    "ex:msyn/hid-20090/test/series2-320c-run2": " (run 2)",
    "ex:msyn/us1844129a/treatment/example-1": " (Example 1)",
    "ex:msyn/us1844129a/treatment/example-2": " (Example 2)",
}
CLAIM_SOURCES = {"us1609593a", "us1625928a", "us1707331a"}   # patent claims named by their shared preamble


def add_note(v: dict, text: str) -> None:
    if text not in (v.get("note") or ""):
        v["note"] = f"{v['note']}; {text}" if v.get("note") else text


def has_number(v: dict) -> bool:
    return any(isinstance(v.get(k), (int, float)) for k in ("value", "lower", "upper"))


def revise_value(key: str, v: dict, log: list) -> None:
    before = json.dumps(v, sort_keys=True)
    unit = v.get("unit")
    if unit in UNIT_SPELLING:
        v["unit"] = UNIT_SPELLING[unit]
    elif unit == "mm" and "pressure" in key:
        v["unit"] = "mm Hg"
        add_note(v, "printed 'mm' (millimetres of mercury)")
    elif unit == "pounds" and "pressure" in key:
        v["unit"] = "lb/in2"
        v["note"] = (v.get("note") or "").replace("unit printed as 'pounds'", "").strip("; ") or None
        add_note(v, "printed 'pounds'; a pressure, in pounds per square inch")
    elif unit == "kg/cm3":
        v["unit"] = "kg/cm2"
        add_note(v, "printed 'kg/cm3', a misprint for kg/cm2")
    elif unit == "unit not printed" or (unit == "1" and "space_velocity" in key):
        v["unit"] = "not stated"
    if key == "pressure" and v.get("status") == "present" and not has_number(v) and v.get("text_value") in ATMOSPHERIC:
        near = v.pop("text_value") == "near atmospheric"
        v.update({"value": 1, "unit": "atm", "qualifier": "approximate"})
        add_note(v, "printed as near atmospheric pressure; recorded as 1 atm" if near else
                 "printed as atmospheric pressure; recorded as 1 atm")
    if v.get("unit") == "1" and not has_number(v):   # "1" is for dimensionless numbers, not text
        del v["unit"]
    if v.get("note") is None:
        v.pop("note", None)
    if json.dumps(v, sort_keys=True) != before:
        log.append(key)


def walk(o, log: list, key: str = "") -> None:
    """Revise every value object; its key is the property or map entry that holds it."""
    if isinstance(o, dict):
        if "status" in o and key:
            revise_value(key, o, log)
        for k, v in o.items():
            if k != "evidence":
                walk(v, log, k)
    elif isinstance(o, list):
        for v in o:
            walk(v, log, key)


def rename(o, ids: dict):
    if isinstance(o, dict):
        return {k: rename(v, ids) for k, v in o.items()}
    if isinstance(o, list):
        return [rename(v, ids) for v in o]
    return ids.get(o, o) if isinstance(o, str) else o


def revise(frag: dict) -> dict[str, int]:
    counts = {"values": 0, "species": 0, "removed": 0, "names": 0}
    slug = frag["source"] if isinstance(frag.get("source"), str) else ""
    log: list = []
    for r in frag.get("nodes", []) + frag.get("links", []):
        walk(r.get("props") or {}, log)
    counts["values"] = len(log)
    present = {n["id"] for n in frag.get("nodes", [])}
    ids = {a: b for a, b in SPECIES_IDS.items() if a in present}
    if ids:
        frag["nodes"] = rename(frag["nodes"], ids)
        frag["links"] = rename(frag["links"], ids)
        seen, nodes = set(), []
        for n in frag["nodes"]:                     # two renamed nodes may now share an id
            if n["id"] in seen:
                keep = next(x for x in nodes if x["id"] == n["id"])
                for ev in n["props"].get("evidence") or []:
                    if ev not in keep["props"].setdefault("evidence", []):
                        keep["props"]["evidence"].append(ev)
                continue
            seen.add(n["id"])
            nodes.append(n)
        frag["nodes"] = nodes
        counts["species"] = len(ids)
    n0 = len(frag["nodes"])
    frag["nodes"] = [n for n in frag["nodes"] if n["id"] not in REMOVE]
    counts["removed"] = n0 - len(frag["nodes"])
    names: dict[str, list] = {}
    for n in frag["nodes"]:
        names.setdefault((n["label"], n["props"].get("name")), []).append(n)
    for n in frag["nodes"]:
        suffix = NAME_SUFFIX.get(n["id"])
        m = re.search(r"/claim/patent-claim-(\d+)$", n["id"])
        if not suffix and m and slug in CLAIM_SOURCES and len(names[(n["label"], n["props"].get("name"))]) > 1:
            suffix = f" (claim {m.group(1)})"
        if suffix and not n["props"]["name"].endswith(suffix):
            n["props"]["name"] += suffix
            counts["names"] += 1
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    total: dict[str, int] = {}
    for f in sorted(FRAGMENTS.glob("*.json")):
        frag = json.loads(f.read_text())
        before = dump_canonical(frag)
        c = revise(frag)
        after = dump_canonical(frag)
        if after != before:
            print(f"{f.stem}: {c}")
            if not a.check:
                f.write_text(after)
        for k, v in c.items():
            total[k] = total.get(k, 0) + v
    print(json.dumps(total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
