"""Bring in the PDFs that another project made by index-sources (or by paper-acquisition, its earlier name: an earlier
project on the same topic, a colleague's copy) already downloaded, for sources of this index that are not downloaded
here. Each file is matched by DOI through the other project's ledger, copied (the other folder is never changed, nor
upgraded), checked like a download — a valid PDF, the same source, the licence printed in it — and filed the same
way. Nothing is fetched from the network.

  python3 -I import_pdfs.py --from /path/to/other/project [--access OA,OA+ND] [--topic co2rr] [--dry-run]

--access keeps only files the other project filed under those access types and that the licence check here puts in
them too (OA,OA+ND = open licences only); --topic keeps only sources of that topic here. Sources the other project
has but this index lacks are counted (not_in_index), never added. Prints one JSON object.
"""
import argparse
import json
import shutil
import sqlite3
import sys
import uuid
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _core  # noqa: F401,E402  (index-sources' scripts: the shared core)
import _pdf as C  # noqa: E402
from _common import ACCESS_TYPES, NOT_DOWNLOADED_TYPES, Project, add_project_arg, die, log, now_iso  # noqa: E402
from _download import attempt, decide_access, file_pdf  # noqa: E402
from _ledger import Ledger  # noqa: E402
from _vectors import after_step  # noqa: E402


def their_files(other, access):
    """[(their source id, doi, access type, version, database, url, PDF path)] for every PDF the other project filed."""
    db = other / ".scripts" / "ledger.sqlite"
    if not db.is_file():
        die(f"{other} has no .scripts/ledger.sqlite: not a project made by index-sources")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    # a project made before the sources were so named (papers, paper_topics) is read as it is
    s, t, fk = ("papers", "paper_topics", "paper_id") if "papers" in tables else ("sources", "source_topics", "source_id")
    rows = con.execute(f"SELECT p.id, lower(p.doi), p.access_type, p.version, p.download_source, p.download_url, t.path "
                       f"FROM {s} p JOIN {t} t ON t.{fk} = p.id "
                       f"WHERE p.downloaded = 1 AND t.path IS NOT NULL ORDER BY p.id").fetchall()
    con.close()
    out, seen = [], set()
    for r in rows:
        if r[0] in seen or (access and r[2] not in access) or not (other / r[6]).is_file():
            continue
        seen.add(r[0])
        out.append(r)
    return out


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--from", dest="other", required=True, help="the other project's folder (holds .scripts/ledger.sqlite)")
    ap.add_argument("--access", default="", help="comma list of access types, e.g. OA,OA+ND")
    ap.add_argument("--topic", default=None, help="only sources of this topic here")
    ap.add_argument("--dry-run", action="store_true", help="count what would be imported; copy nothing")
    a = ap.parse_args()
    access = frozenset(x.strip() for x in a.access.split(",") if x.strip())
    if access - set(ACCESS_TYPES):
        die(f"unknown access type(s) {sorted(access - set(ACCESS_TYPES))}; known: {ACCESS_TYPES}")
    proj = Project(a.project)
    other = Path(a.other).expanduser().resolve()
    if other == proj.root:
        die("--from is this project")
    led = Ledger(proj)
    files = their_files(other, access)
    skipped, todo = Counter(), []
    for pid, doi, their_access, version, database, url, path in files:
        if not doi:
            skipped["no_doi_there"] += 1
            continue
        mine = led.find_id(doi=doi)
        if mine is None:
            skipped["not_in_index"] += 1
            continue
        source = led.get(mine)
        if source.get("downloaded"):
            skipped["already_here"] += 1
            continue
        if source.get("is_erratum") or (source.get("doc_type") or "") in NOT_DOWNLOADED_TYPES:
            skipped["notice_dataset_or_software"] += 1     # never downloaded here either (download_open.py)
            continue
        if a.topic and a.topic not in {t["topic"] for t in led.topics_of(mine)}:
            skipped["other_topic"] += 1
            continue
        todo.append((source, version, database, url, other / path))
    log(f"import from {other.name}: {len(files)} PDFs there; {len(todo)} to bring in; skipped {dict(skipped)}")
    if a.dry_run:
        print(json.dumps({"from": str(other), "pdfs_there": len(files), "to_import": len(todo), "skipped": dict(skipped),
                          "to_import_by_access_here": dict(Counter(p.get("access_type") for p, *_ in todo)),
                          "to_import_by_status_here": dict(Counter(p.get("dl_status") or "none" for p, *_ in todo))}))
        return
    outcomes = Counter()
    for i, (source, version, database, url, src) in enumerate(todo, 1):
        tmp = proj.tmp / f"{uuid.uuid4().hex}.part"
        shutil.copy2(src, tmp)
        entry = {"src": f"{database or 'unknown'}.import", "version": version, "access": source.get("access_type"),
                 "license": source.get("license"), "url": url or ""}
        if access:                                 # the licence printed in the PDF decides, as for a download
            first, last = C.extract_text(tmp)
            got = decide_access(entry, f"{first}\n{C.poppler_text(tmp)}", last)[0]
            if got not in access:
                tmp.unlink(missing_ok=True)
                outcomes[f"not_{'_'.join(sorted(access))}_here"] += 1
                attempt(proj, source["id"], source.get("doi"), step="import_pdfs", url=str(src),
                        outcome="access_differs", reason=f"licence check here: {got}")
                continue
        out, why = file_pdf(proj, led, source, entry, tmp, "import", final_url=url)
        outcomes[out] += 1
        attempt(proj, source["id"], source.get("doi"), step="import_pdfs", url=str(src), outcome=out, reason=why)
        if i % 50 == 0:
            log(f"import: {i}/{len(todo)} {dict(outcomes)}")
            led.export_progress()
    led.export()
    print(json.dumps({"from": str(other), "pdfs_there": len(files), "tried": len(todo), "outcomes": dict(outcomes),
                      "skipped": dict(skipped), "vector_store": after_step(proj, led), "finished_at": now_iso()}))


if __name__ == "__main__":
    main()
