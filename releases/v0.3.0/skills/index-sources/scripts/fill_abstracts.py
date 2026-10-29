"""Fill missing abstracts from the downloaded PDFs (an option of Download mode and of curation — an index-only run has
no PDFs, so its abstracts come from metadata only).

Reads pages 1-2 of each downloaded source of the topic whose abstract is missing or shorter than 80 characters, takes
the text under an "Abstract" / "Summary" heading (up to Keywords / Introduction), and stores it with
abstract_source = "pdf". PDFs without such a heading (common for RSC and Nature journals) are left alone: a curator
copies the abstract verbatim while reading each source. --heuristic also tries the first long prose paragraph of page 1
(abstract_source = "pdf (first-page paragraph)"); it is right only about half the time, so check a sample first.
Topic A/B/C from the vocabulary are recomputed for the sources that got an abstract.

  python3 -I fill_abstracts.py --topic <slug> [--dry-run] [--heuristic] [--ids 12,57]
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import Project, add_project_arg, clean_text, load_config, log, now_iso, update_state
from _ledger import Ledger
from _topics import Vocab, apply_vocab

HEAD = re.compile(r"(?im)^\s*(?:a\s*b\s*s\s*t\s*r\s*a\s*c\t?\s*t|abstract|summary|synopsis)\s*[:.\-—–]?\s*")
STOP = re.compile(r"(?im)^\s*(?:key\s*words?|index terms|(?:1|i)\s*\.?\s*introduction\b|introduction\b|graphical abstract|"
                  r"background\b|main\b|results\b|received\b|article history|abbreviations)")
NOISE = re.compile(r"(©|\(c\)\s*\d{4}|copyright|all rights reserved|creative commons|this is an open access article|"
                   r"https?://|doi:|e-?mail|corresponding author|preprint|archive ouverte|documents may come from|"
                   r"intended for publication|peer review|✉|accepted manuscript)", re.I)
CITES = re.compile(r"[a-z\)]\d{1,3}(?:[,–-]\d{1,3})+\b|\[\d+(?:[,–-]\d+)*\]")   # superscript / bracket citations


def page_text(pdf, pages=2):
    import fitz
    fitz.TOOLS.mupdf_display_errors(False)
    with fitz.open(pdf) as doc:
        return "\n".join(doc[i].get_text("text") for i in range(min(pages, doc.page_count)))


def tidy(t):
    t = re.sub(r"-\n(?=[a-z])", "", t)
    t = re.sub(r"\s*\n\s*", " ", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return clean_text(t)


def plausible(t):
    if not (300 <= len(t) <= 4000):
        return False
    letters = sum(c.isalpha() for c in t)
    return letters / max(1, len(t)) > 0.7 and t.count(". ") >= 2 and not re.search(r"\[\d+\]\s*\w+.*\[\d+\]", t)


def from_heading(text):
    m = HEAD.search(text)
    if not m:
        return None
    rest = text[m.end():]
    s = STOP.search(rest)
    chunk = rest[:s.start()] if s else rest[:3500]
    lines = [l for l in chunk.splitlines() if not NOISE.search(l)]
    t = tidy("\n".join(lines))
    return t if plausible(t) else None


AFFIL = re.compile(r"(universit|department|institute|laborator|college|school of|faculty|academy|\bdept\b|centre|"
                   r"center for|division|\bcnrs\b|\bstreet\b|\broad\b|\bp\.?o\.? box)", re.I)


def prose_like(p):
    words = p.split()
    caps = sum(1 for w in words if w[:1].isupper())
    return len(AFFIL.findall(p)) < 2 and caps / max(1, len(words)) < 0.3 and len(CITES.findall(p)) < 2 and \
        not re.match(r"^([A-Z][a-z]+\s){1,3}[A-Z][a-z]+\s?\d", p)


def from_paragraph(text):
    head = text[:STOP.search(text).start()] if STOP.search(text) else text[:6000]
    paras = [tidy(p) for p in re.split(r"\n\s*\n|\n(?=[A-Z][a-z]+\s)", head)]
    paras = [p for p in paras if plausible(p) and not NOISE.search(p[:200]) and prose_like(p)]
    return max(paras, key=len) if paras else None


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--heuristic", action="store_true", help="also try the first long paragraph of page 1")
    ap.add_argument("--ids", default=None)
    a = ap.parse_args()
    proj = Project(a.project)
    load_config(proj, a.topic)
    led = Ledger(proj)
    rows = led.topic_rows(a.topic, "AND p.downloaded = 1 AND t.path IS NOT NULL AND LENGTH(COALESCE(p.abstract, '')) < 80")
    if a.ids:
        want = {int(x) for x in a.ids.split(",") if x.strip().isdigit()}
        rows = [r for r in rows if r["id"] in want]
    got, heur, failed, samples = [], 0, 0, []
    for r in rows:
        pdf = proj.root / r["t_path"]
        if not pdf.exists():
            continue
        try:
            text = page_text(pdf)
        except Exception as e:
            log(f"{r['id']}: unreadable PDF ({e})")
            failed += 1
            continue
        ab, src = from_heading(text), "pdf"
        if not ab and a.heuristic:
            ab, src = from_paragraph(text), "pdf (first-page paragraph)"
            heur += bool(ab)
        if not ab:
            failed += 1
            continue
        got.append((r, ab, src))
        if len(samples) < 5:
            samples.append({"id": r["id"], "title": (r.get("title") or "")[:90], "source": src, "abstract": ab[:300] + "…"})
    if not a.dry_run and got:
        with led.tx():
            for r, ab, src in got:
                led.set(r["id"], abstract=ab, abstract_source=src)
        apply_vocab(led, Vocab(proj), led.topic_rows(a.topic, f"AND p.id IN ({','.join(str(r['id']) for r, _, _ in got)})"))
        led.export(topics=[a.topic])
    res = {"candidates": len(rows), "filled": len(got), "from_first_page_paragraph": heur, "not_found": failed,
           "dry_run": a.dry_run, "samples": samples}
    if not a.dry_run:
        update_state(proj, a.topic, lambda st: st.update({"fill_abstracts": {**{k: v for k, v in res.items() if k != "samples"},
                                                                             "at": now_iso()}}))
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
