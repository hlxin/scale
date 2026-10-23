"""Settle a fetched corpus: write into its manifest which files were fetched, and why the others were not.

  python3 -I settle_corpus.py --corpus <sources.json> [--project <folder>]

For every source the corpus includes (and every one an earlier settle marked not_retrieved), from the index:
  - its file is on disk: status in_scope, with pdf, si and text_version (paths relative to the manifest's folder)
  - no file: status not_retrieved, status_reason why (queued for the library EZproxy, no copy found, access type not
    fetched, not fetched yet, the file is missing on disk)
The other entries (off_scope, excluded ...) and the corpus's rule are left as frozen. The counts are recounted and
`fetched_at` is set. Run it after download_open.py / download_paywalled.py / fetch_si.py --corpus, and again after a
later fetch: a source fetched since is included again. Then `scale corpus check <manifest>` and curate-corpus.
"""
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _core  # noqa: F401,E402  (index-sources' scripts: the shared core)
from _common import Project, add_project_arg, log, today  # noqa: E402
from _corpus import INCLUDED, load, source_id  # noqa: E402
from _ledger import Ledger  # noqa: E402
from freeze_corpus import NOT_RETRIEVED, TEXT_VERSIONS, check  # noqa: E402

NOT_FETCHED = {"not_selected": "access type not fetched", **NOT_RETRIEVED}


def settle(proj, led, path):
    path = Path(path).resolve()
    m = load(path)
    included = m.get("included_status") or "in_scope"
    todo = {source_id(s): s for s in m["sources"] if s.get("status") in INCLUDED + ("not_retrieved",)}
    base, reasons = path.parent, Counter()
    for block in led.iter_topic(m["topic"]):
        for p in block:
            e = todo.get(p["id"])
            if e is None:
                continue
            for k in ("pdf", "si", "text_version", "status_reason"):
                e.pop(k, None)
            if p.get("downloaded") and p.get("t_path") and (proj.root / p["t_path"]).is_file():
                e["status"] = included
                e["pdf"] = os.path.relpath(proj.root / p["t_path"], base)
                if TEXT_VERSIONS.get(p.get("version") or ""):
                    e["text_version"] = TEXT_VERSIONS[p["version"]]
                si = p.get("t_si_paths") or []
                si = json.loads(si) if isinstance(si, str) else si
                si = [os.path.relpath(proj.root / s, base) for s in si if (proj.root / s).is_file()]
                if si:
                    e["si"] = si
            else:
                e["status"] = "not_retrieved"
                e["status_reason"] = ("the file is missing on disk" if p.get("downloaded") else
                                      NOT_FETCHED.get(p.get("dl_status") or "", "not fetched yet"))
                reasons[e["status_reason"]] += 1
            del todo[p["id"]]
    for e in todo.values():                       # no longer in the topic's index (merged, removed)
        for k in ("pdf", "si", "text_version"):
            e.pop(k, None)
        e["status"], e["status_reason"] = "not_retrieved", "no longer in the topic's index"
        reasons[e["status_reason"]] += 1
    m["counts"] = dict(sorted(Counter(s["status"] for s in m["sources"]).items()))
    m["fetched_at"] = today()
    problems = check(m)
    path.write_text(json.dumps(m, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    n = m["counts"].get(included, 0)
    log(f"settled {proj.rel(path)}: {n} sources with their file, {sum(reasons.values())} not retrieved")
    return {"manifest": proj.rel(path), "with_file": n, "not_retrieved": dict(reasons.most_common()),
            "counts": m["counts"], "problems": problems,
            "next": (f"scale corpus check {proj.rel(path)}; then curate-corpus" if n else
                     "nothing fetched yet: run download_open.py --corpus first")}


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--corpus", required=True, help="the corpus manifest (sources.json) to settle")
    a = ap.parse_args()
    proj = Project(a.project)
    print(json.dumps(settle(proj, Ledger(proj), a.corpus)))


if __name__ == "__main__":
    main()
