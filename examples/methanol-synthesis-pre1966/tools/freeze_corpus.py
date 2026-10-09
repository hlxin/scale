"""Freeze the historical methanol-synthesis corpus for curation under a publication-date cutoff.

    python freeze_corpus.py CORPUS_DIR [--cutoff 1966-01-01] [--work WORK_DIR] [--out corpus/manifest.json] [--texts-from BUNDLE]

A source is in scope when it was **published or publicly disclosed before the cutoff date**
(default 1 January 1966, before ICI's low-pressure commercialization; CUTOFF_WHY). For a journal article or
thesis that is its publication year; for a patent it is the grant (publication) date printed on
the patent, not its priority or filing date, cross-checked against the USPTO table of the first
patent number issued each year. Nothing after the cutoff enters the curated graph.

For every retrieved PDF the page texts are written to WORK_DIR/texts/<slug>.json: the PDF's text
layer where it has one, Tesseract OCR where it does not (each page says which). These texts are
local working copies for quote checks and passage search; they are not redistributed.

Deterministic for the same corpus, PDFs and Tesseract version.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

def _repo_root(*starts: Path) -> Path:
    """The SCALE checkout (scale-release.yaml and releases/), searched upward from each start in turn."""
    for p in (q for s in starts for q in (s, *s.parents)):
        if (p / "scale-release.yaml").exists() and (p / "releases").is_dir():
            return p
    raise SystemExit("run inside a SCALE repository checkout: no scale-release.yaml and releases/ above "
                     + ", ".join(map(str, starts)))


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_repo_root(HERE, Path.cwd()) / "tools"))
from scale.sourcetext import extract_pages, sha256_file  # noqa: E402
from scale import layout  # noqa: E402
from scale.util import dump_canonical  # noqa: E402

# the frozen corpus is written to the restricted copy (the copy outside the repository), beside the local work/ (page texts);
# the public corpus manifest in this folder is copied from there
DATA = layout.restricted_path(_repo_root(HERE, Path.cwd()), "examples/methanol-synthesis-pre1966")

# First US utility patent number issued in each year (USPTO, "Issue Years and Patent Numbers").
US_FIRST_NUMBER = {1920: 1326899, 1921: 1364063, 1922: 1401948, 1923: 1440362, 1924: 1478996, 1925: 1521590,
                   1926: 1568040, 1927: 1612700, 1928: 1654521, 1929: 1696897, 1930: 1742181, 1931: 1787424,
                   1932: 1839190, 1933: 1892663, 1934: 1941302, 1935: 1985878, 1936: 2026516, 1937: 2066309,
                   1938: 2104004, 1939: 2142080, 1940: 2185170, 1941: 2227418, 1942: 2268540, 1943: 2307007,
                   1944: 2338081, 1945: 2366154, 1946: 2391856, 1947: 2413675, 1948: 2433824, 1949: 2457797,
                   1950: 2492944, 1951: 2536016, 1952: 2580379, 1953: 2624046, 1954: 2664562, 1955: 2698434,
                   1956: 2728913, 1957: 2775762, 1958: 2818567, 1959: 2866973, 1960: 2919443, 1961: 2966681,
                   1962: 3015103, 1963: 3070801, 1964: 3116487, 1965: 3163865, 1966: 3226729, 1967: 3295143,
                   1968: 3360800, 1969: 3419907}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def us_issue_year(number: str) -> int | None:
    m = re.match(r"US(\d+)", number)
    if not m:
        return None
    n = int(m.group(1))
    years = [y for y, first in US_FIRST_NUMBER.items() if first <= n]
    return max(years) if years else None


def printed_grant_date(pages: list[dict]) -> str | None:
    """'Patented Oct. 27, 1925' (or 'Patented Sept. 15, 1959') on the first pages, as YYYY-MM-DD."""
    text = " ".join(p["text"] for p in pages[:2])
    m = re.search(r"Patent(?:ed|cd)\s*,?\s*([A-Z][a-z]{2,5})\.?\s*(\d{1,2})\s*[,.]?\s*(1[89]\d\d)", text)
    if not m:
        return None
    mon = MONTHS.get(m.group(1)[:3].lower())
    return f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}" if mon else None


# Non-US patents whose grant date and patentee the parser above cannot read, as printed on page 1.
PRINTED_ON_PATENT = {
    "PL9584B1": {"granted": "1928-10-10", "assignee": "Société Anonyme Compagnie de Béthune",
                 "printed": "page 1: 'Société Anonyme Compagnie de Bethune (Bully Les Mines Pas-de-Calais, Francja)'; "
                            "'Udzielono 10 października 1928 r.' (granted); filed 10 June 1927, priority 17 July 1926 (France)"},
}


# Why a cutoff was chosen (the rediscovery target it holds out).
CUTOFF_WHY = {
    "1959-01-01": ("Kume, Abe and Tanioka (Nippon Kagaku Zasshi 62, 1959) report methanol synthesis from CO2 and H2 over "
                   "Cu-Zn-Al formulations; a cutoff of 1 January 1959 holds it out as a rediscovery target."),
    "1966-01-01": ("ICI launched low-pressure methanol synthesis over Cu/ZnO/Al2O3 in 1966 (GB 1,010,871, published 1966; "
                   "US 3,326,956); a cutoff of 1 January 1966 holds out that commercialization and what followed as "
                   "rediscovery targets, and admits everything published before it, ICI's earlier publications included."),
}


def slug_for(doi: str | None, patent: str | None, hid: str | None) -> str:
    if doi:
        return doi.lower().replace("/", "-")
    if patent:
        return patent.lower()
    return f"hid-{hid}"


def text_summary(t: dict) -> dict:
    origins = {}
    for p in t["pages"]:
        origins[p["origin"]] = origins.get(p["origin"], 0) + 1
    chars = sum(len(p["text"]) for p in t["pages"])
    return {"pages": t["page_count"], "page_text_origins": origins, "chars": chars, "ocr_engine": t["ocr_engine"],
            "pdf_sha256": t["pdf_sha256"]}


def texts_from_bundle(bundle: Path, corpus: Path, rel: str, work: Path, slug: str, frozen: dict | None) -> None:
    """Write the page texts a released GALAXY bundle ships (text/<slug>.txt, the US patents) as the
    working copy, so the texts the curation was checked against are used rather than a new OCR run
    (another Tesseract build of the same version can read a few characters differently). The PDF must
    be the one frozen before; the OCR engine is the one recorded then."""
    src = bundle / "text" / f"{slug}.txt"
    if not src.exists() or not frozen or frozen.get("pdf") != rel:
        return
    parts = re.split(r"\n===== page (\d+) \((\w+)\) =====\n", src.read_text())
    pages = [{"page": int(parts[i]), "origin": parts[i + 1], "text": parts[i + 2]} for i in range(1, len(parts), 3)]
    sha = sha256_file(corpus / rel)
    if sha != frozen["text"]["pdf_sha256"]:
        raise SystemExit(f"{slug}: the PDF differs from the one frozen before; cannot reuse the bundle's texts")
    t = {"slug": slug, "pdf": rel, "pdf_sha256": sha, "page_count": len(pages), "ocr_engine": frozen["text"]["ocr_engine"], "pages": pages}
    out = work / "texts" / f"{slug}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(t, ensure_ascii=False, indent=1) + "\n")


def load_text(corpus: Path, rel: str, work: Path, slug: str, columns: int = 1) -> dict:
    """Page texts; early US patents are set in two columns, so their OCR reads each column on its own."""
    out = work / "texts" / f"{slug}.json"
    pdf = corpus / rel
    if out.exists():
        t = json.loads(out.read_text())
        if t.get("pdf") == rel and (t.get("ocr_engine") is None or f"{columns} column" in t["ocr_engine"]):
            return t
    t = {"slug": slug, "pdf": rel, **extract_pages(pdf, columns=columns)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(t, ensure_ascii=False, indent=1) + "\n")
    print(f"  text {slug}: {t['page_count']} pages ({text_summary(t)['page_text_origins']})", file=sys.stderr)
    return t


FOOTNOTE_MARK = re.compile(r"(?:(?<=[a-z])|(?<=[A-Z]{2}))1(?:,\s?2)?\)?(?:\.?$|(?=:\s))")


def byline(authors) -> list[str]:
    """The corpus metadata gives authors as a list or as one string ("A; B"); placeholders
    ("U. Undetermined", "(TU Delft student report)") are not authors."""
    names = authors if isinstance(authors, list) else str(authors or "").split(";")
    return [n.strip() for n in names if n.strip() and not n.strip().startswith("(") and n.strip() != "U. Undetermined"]


def clean_title(title: str) -> str:
    """Drop a footnote marker the bibliography copied from the printed title ("…Hydrogen1",
    "…Methanolsynthese1).", "…Methanol1,2", "…Hydrogen1: III—…"); a formula ("ZnO-CrO3", "CO2 en H2") stays."""
    return FOOTNOTE_MARK.sub("", title)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("corpus", type=Path)
    ap.add_argument("--cutoff", default="1966-01-01", help="published before this date (YYYY-MM-DD)")
    ap.add_argument("--work", type=Path, default=DATA / "work")
    ap.add_argument("--out", type=Path, default=DATA / "corpus" / "manifest.json")
    ap.add_argument("--texts-from", type=Path, help="a released GALAXY bundle whose text/ page texts to reuse (see texts_from_bundle)")
    a = ap.parse_args(argv)
    frozen = {s["slug"]: s for s in json.loads(a.out.read_text())["sources"]} if a.texts_from and a.out.exists() else {}
    cutoff = dt.date.fromisoformat(a.cutoff)
    hist = a.corpus / "historical"
    authors = {}
    for line in (a.corpus / "metadata" / "historical_corpus.jsonl").read_text().splitlines():
        r = json.loads(line)
        authors[str(r.get("hid"))] = r.get("authors") or []
    entries = []

    for r in csv.DictReader(open(hist / "bibliography.csv", encoding="utf-8")):
        slug = slug_for(r["doi"], None, r["hid"])
        e = {"slug": slug, "kind": "thesis_or_report" if r["bucket"] == "gray" else "article", "hid": r["hid"],
             "doi": r["doi"] or None, "title": clean_title(r["title"]), "authors": byline(authors.get(r["hid"]) or r["first_author"]),
             "venue": r["journal"] or None, "published": r["year"], "date_basis": "publication year (bibliography)",
             "corpus_role": r["era_role"], "note": r["note"] or None}
        entries.append((e, r["pdf"] if r["retrieved"] == "yes" and r["pdf"] else None, int(r["year"])))

    for r in csv.DictReader(open(hist / "patents.csv", encoding="utf-8")):
        slug = slug_for(None, r["patent"], None)
        e = {"slug": slug, "kind": "patent", "patent": r["patent"], "title": r["title"], "assignee": r["assignee"] or None,
             "inventors": r["inventors"] or None, "priority_date": r["priority_date"] or None,
             "corpus_role": r["era"], "note": (r["offscope_reason"] or None)}
        if r["homogeneous_offscope"] == "yes":
            e["off_scope"] = r["offscope_reason"] or "homogeneous catalysis"
        entries.append((e, r["pdf_path"] if r["pdf"] == "yes" and r["pdf_path"] else None, None))

    out = []
    for e, rel, year in entries:
        if rel and (a.corpus / rel).exists():
            if a.texts_from:
                texts_from_bundle(a.texts_from, a.corpus, rel, a.work, e["slug"], frozen.get(e["slug"]))
            t = load_text(a.corpus, rel, a.work, e["slug"], columns=2 if e["kind"] == "patent" and e["slug"].startswith("us") else 1)
            e["pdf"] = rel
            e["text"] = text_summary(t)
            if e["kind"] == "patent":
                printed = printed_grant_date(t["pages"])
                table = us_issue_year(e["patent"])
                if printed and (not table or int(printed[:4]) == table):
                    e["published"], e["date_basis"] = printed, "grant date printed on the patent (agrees with the USPTO issue-year table)"
                elif printed:
                    e["published"], e["date_basis"] = str(table), "grant year from the USPTO issue-year table"
                    e["date_check"] = f"the text gives {printed}, which disagrees with the table (an OCR misreading)"
                elif table:
                    e["published"], e["date_basis"] = str(table), "grant year from the USPTO issue-year table (no legible grant date)"
                elif e["patent"] in PRINTED_ON_PATENT:
                    known = PRINTED_ON_PATENT[e["patent"]]
                    e["published"], e["date_basis"] = known["granted"], "grant date printed on the patent (read from the page)"
                    e["assignee"] = e["assignee"] or known["assignee"]
                    e["date_check"] = known["printed"]
                else:
                    e["published"], e["date_basis"] = (e["priority_date"] or "")[:4] or None, "priority year only (grant date unknown)"
        else:
            e["pdf"] = None
            if e["kind"] == "patent":
                table = us_issue_year(e["patent"])
                e["published"] = str(table) if table else (e["priority_date"] or "")[:4] or None
                e["date_basis"] = "grant year from the USPTO issue-year table" if table else "priority year only (grant date unknown)"
        pub = e.get("published")
        first_day = dt.date(int(pub[:4]), int(pub[5:7]) if len(pub) >= 7 else 1, int(pub[8:10]) if len(pub) >= 10 else 1) if pub else None
        last_day = (dt.date(int(pub[:4]), 12, 31) if len(pub) == 4 else first_day) if pub else None
        if e.get("off_scope"):
            status = "off_scope"
        elif "held_out" in (e.get("corpus_role") or ""):
            status = "held_out_target"
        elif first_day is None:
            status = "undated"
        elif last_day < cutoff:
            status = "in_scope" if e["pdf"] else "not_retrieved"
        elif first_day >= cutoff:
            status = "after_cutoff"
        else:
            status = "straddles_cutoff"
        if e["kind"] == "patent" and "USPTO" in e["date_basis"] and status == "in_scope" and not e.get("date_check"):
            pass
        e["status"] = status
        if status == "in_scope" and e["text"]["chars"] < 200:
            e["status"], e["status_reason"] = "no_text", "no usable text after OCR"
        out.append({k: v for k, v in e.items() if v not in (None, "", [])})

    out.sort(key=lambda e: (e.get("published") or "9999", e["slug"]))
    counts = {}
    for e in out:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    manifest = {
        "corpus": "methanol-synthesis historical corpus (ARPA-E CATALYST), frozen for SCALE curation",
        "cutoff": {"date": a.cutoff, "rule": f"published or publicly disclosed before {a.cutoff}",
                   "why": CUTOFF_WHY.get(a.cutoff, "a cutoff chosen for a rediscovery evaluation"),
                   "patents": "grant (publication) date printed on the patent, not the priority or filing date",
                   "caution": ("The cutoff does not remove every Cu-Zn-Al disclosure: the corpus leakage audit "
                               "(historical/LEAKAGE_AUDIT.md) lists US 2,061,470 (Larson, granted 1936), whose Example 10 is "
                               "87 CuO / 10 ZnO / 3 Al2O3, and Cu-Zn catalysts from 1928 on. They are in scope and curated as "
                               "reported; a rediscovery evaluation must hold them out separately if it needs to.")},
        "counts": dict(sorted(counts.items())),
        "sources": out,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(dump_canonical(manifest))
    print(json.dumps(manifest["counts"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
