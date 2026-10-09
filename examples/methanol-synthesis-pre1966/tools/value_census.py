"""Count the printed values each source's catalytic tests carry, to measure a re-curation.

    python value_census.py [--sources work/scope-co-co2.json] [--out census.json]

For every source: its CatalyticTests, and per field how many tests carry a present value
(temperature, pressure, space velocity, flow rate, duration, time on stream, conversion, yield,
selectivity, space-time yield, production rate, catalyst amount on USES_CATALYST, feed ratio), plus
the number of values in results and conditions maps, and how the evidence was read.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from curation import DATA as EX  # noqa: E402   the curated data: the restricted copy of this example
FIELDS = ("temperature", "pressure", "space_velocity", "flow_rate", "duration", "time_on_stream", "conversion", "yield",
          "selectivity", "space_time_yield", "production_rate", "feed_ratio")


def present(v) -> bool:
    return isinstance(v, dict) and v.get("status", "present") == "present"


def census(slugs: list[str]) -> dict:
    out = {}
    for slug in slugs:
        frag = json.loads((EX / "curation/fragments" / f"{slug}.json").read_text())
        tests = [n for n in frag["nodes"] if n["label"] == "CatalyticTest"]
        ids = {t["id"] for t in tests}
        c = Counter()
        for t in tests:
            p = t["props"]
            for f in FIELDS:
                c[f] += present(p.get(f))
            c["map_values"] += sum(present(v) for k in ("results", "conditions") for v in (p.get(k) or {}).values())
        amounts = sum(1 for e in frag["links"] if e["type"] == "USES_CATALYST" and e["source"] in ids and present(e["props"].get("amount")))
        reading = Counter(ev.get("reading", "text") for r in frag["nodes"] + frag["links"] for ev in r["props"].get("evidence") or [])
        out[slug] = {"tests": len(tests), **{f: c[f] for f in FIELDS}, "catalyst_amount": amounts, "map_values": c["map_values"],
                     "values": sum(c[f] for f in FIELDS) + amounts + c["map_values"], "evidence_reading": dict(reading)}
    tot = defaultdict(int)
    for v in out.values():
        for k, x in v.items():
            if isinstance(x, int):
                tot[k] += x
    return {"total": dict(tot), "by_source": out}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", type=Path, default=EX / "work/scope-co-co2.json")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    res = census(json.loads(a.sources.read_text()))
    if a.out:
        a.out.write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res["total"], indent=1))
