"""Accept a PDF that the same-source check rejected, once someone has looked at its pages and confirmed it is the source
(pages that are only images, a title printed in another language, a font no reader decodes). The file is validated and
filed exactly like a download — licence read from the PDF, a copy for every topic that wants the source, the index
updated — and the decision is logged with its reason. Rejected files are in .scripts/rejected/wrong_paper/
(<ID>_<hash>.pdf, the index Notes say why); an accepted one moves to .scripts/rejected/accepted/ (a file from
anywhere else, e.g. another project, is copied and left where it is).

  python3 -I accept_pdf.py --id 1234 --file .scripts/rejected/wrong_paper/1234_7c4eda02.pdf \
                          --reason "page 1 shows the title, authors and DOI (pages are images)" [--version acceptedVersion]

Prints one JSON object.
"""
import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _core  # noqa: F401,E402  (index-sources' scripts: the shared core)
import _pdf as C  # noqa: E402
from _common import Project, add_project_arg, die, jsonl_iter, now_iso  # noqa: E402
from _download import _file_checked, attempt, decide_access  # noqa: E402
from _ledger import Ledger  # noqa: E402
from _vectors import after_step  # noqa: E402


def origin(proj, pid, name):
    """(step, url) of the logged download that this rejected file came from."""
    found = ("", "")
    for a in jsonl_iter(proj.logs / "download_attempts.jsonl"):
        if a.get("id") == pid and a.get("outcome") == "wrong_paper" and name in (a.get("reason") or ""):
            found = (a.get("step") or "", a.get("url") or "")
    return found


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--reason", required=True, help="what was checked and what the pages show")
    ap.add_argument("--version", choices=["publishedVersion", "acceptedVersion", "submittedVersion"], default=None)
    a = ap.parse_args()
    proj = Project(a.project)
    led = Ledger(proj)
    source = led.get(a.id)
    if not source:
        die(f"no source {a.id} in the index")
    if source.get("downloaded"):
        die(f"source {a.id} is already downloaded")
    f = Path(a.file) if Path(a.file).is_absolute() else proj.root / a.file
    if not f.is_file():
        die(f"no file {a.file}")
    ok, why, pages = C.validate(f)
    if not ok:
        die(f"{a.file} is not a usable PDF ({why})")
    step, url = origin(proj, a.id, f.name)
    via_proxy = step.startswith("ezproxy")
    entry = {"src": f"{step or 'unknown'}.reviewed", "version": a.version or ("publishedVersion" if via_proxy else None),
             "access": source.get("access_type"), "license": source.get("license"), "url": url}
    tmp = proj.tmp / f"{uuid.uuid4().hex}.part"
    shutil.copy2(f, tmp)
    first, last = C.extract_text(tmp)
    out, detail = _file_checked(proj, led, source, entry, tmp, pages, url, "ezproxy" if via_proxy else "open",
                                decide_access(entry, f"{first}\n{C.poppler_text(tmp)}", last))
    attempt(proj, a.id, source.get("doi"), step="accepted_after_review", url=url[:300], outcome=out, reason=a.reason,
            file=proj.rel(f))
    rejected = (proj.scr / "rejected").resolve()
    if out == "valid_pdf" and rejected in f.resolve().parents:    # files from anywhere else are never moved
        kept = proj.scr / "rejected" / "accepted"
        kept.mkdir(parents=True, exist_ok=True)
        f.replace(kept / f.name)
    led.export()
    print(json.dumps({"id": a.id, "outcome": out, "detail": detail, "vector_store": after_step(proj, led),
                      "finished_at": now_iso()}))


if __name__ == "__main__":
    main()
