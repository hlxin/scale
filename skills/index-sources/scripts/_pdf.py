"""PDF checks (library module — not run directly): validity, same-paper title match (or the source's own DOI printed in
it), SI-document guard, and the license statement printed in the PDF. PDFs are untrusted input; they are only parsed
(PyMuPDF / pypdf, and poppler's pdftotext as a second reader when it is installed), never executed.
"""
import hashlib
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path

import fitz  # PyMuPDF
import pypdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ND_LICENSES, OPEN_LICENSES as ALLOWED_LICENSES

fitz.TOOLS.mupdf_display_errors(False)
logging.getLogger("pypdf").setLevel(logging.ERROR)  # malformed-xref warnings are noise here

STOP = set("""a an the of and or for in on at to by with from via into onto over under using toward towards its their
this that these those as is are be based study studies new novel high highly efficient effect effects role
""".split())


def validate(path):
    """Return (ok, reason, page_count)."""
    p = Path(path)
    try:
        size = p.stat().st_size
    except OSError:
        return False, "missing", 0
    if size == 0:
        return False, "empty", 0
    if size < 50 * 1024:
        return False, "too_small", 0
    with open(p, "rb") as fh:
        head = fh.read(2048)
    if head[:4] != b"%PDF":
        return False, "bad_magic", 0
    low = head.lower()
    if b"<html" in low or b"<!doctype" in low or b"<head>" in low:
        return False, "html_disguised_as_pdf", 0
    try:
        n = len(pypdf.PdfReader(str(p), strict=False).pages)
    except Exception:
        try:  # pypdf can be stricter than viewers; accept if MuPDF opens it
            with fitz.open(str(p)) as d:
                n = d.page_count
        except Exception:
            return False, "pypdf_open_error", 0
    if n < 1:
        return False, "zero_pages", 0
    return True, "ok", n


def sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_text(path, first=2, last=3, max_chars=60000):
    """Text of the first `first` and last `last` pages (license statements live there)."""
    out_first, out_last = [], []
    try:
        with fitz.open(str(path)) as d:
            n = d.page_count
            idx_first = list(range(min(first, n)))
            idx_last = [i for i in range(max(0, n - last), n) if i not in idx_first]
            for i in idx_first:
                out_first.append(d[i].get_text("text"))
            for i in idx_last:
                out_last.append(d[i].get_text("text"))
    except Exception:
        return "", ""
    return "\n".join(out_first)[:max_chars], "\n".join(out_last)[:max_chars]


def poppler_text(path, pages=2):
    """The first pages read by poppler's pdftotext, a second reader for fonts PyMuPDF decodes badly; "" without it."""
    exe = shutil.which("pdftotext")
    if not exe:
        return ""
    try:
        r = subprocess.run([exe, "-q", "-l", str(pages), str(path), "-"], capture_output=True, timeout=60)
        return r.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def doi_printed(doi, text):
    """True when this exact DOI is printed in the text: line breaks inside it allowed, but not a longer DOI that
    merely starts with it (10.15376/biores.21.2.Wang is not 10.15376/biores.21.2.Wang2)."""
    if not doi or not text:
        return False
    body = r"\s*".join(re.escape(ch) for ch in doi.strip().lower())
    return re.search(rf"(?<![a-z0-9.]){body}(?![a-z0-9])", text.lower()) is not None


def _norm(s):
    s = s.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("ﬀ", "ff").replace("ﬃ", "ffi")
    s = re.sub(r"-\s*\n\s*", "", s)  # de-hyphenate line breaks
    s = s.replace("₂", "2").replace("₃", "3")
    return re.sub(r"[^a-z0-9]+", "", s.lower())


_SI_HEAD = re.compile(r"(supporting\s+information|supplementary\s+(information|materials?|data|notes?)|electronic\s+supplementary|"
                      r"supplemental\s+(information|materials?))", re.I)


def looks_like_si_document(first_text):
    """True when the first page *opens* as an SI file ("Supporting Information for ...", "Supplementary
    Information", "Electronic Supplementary Information") rather than an article that cites its SI."""
    head = re.sub(r"\s+", " ", (first_text or "")[:500])
    m = _SI_HEAD.search(head)
    if not m:
        return False
    before = head[:m.start()]
    # the SI phrase must be among the first ~12 words of the page and no abstract precedes it
    return len(before.split()) <= 12 and "abstract" not in before.lower()


def title_match(title, first_text):
    """Fraction of informative title tokens found in the first pages (spacing-insensitive)."""
    toks = [t for t in re.findall(r"[a-z0-9]+", (title or "").lower().replace("₂", "2")) if len(t) >= 4 and t not in STOP]
    if len(toks) < 3:
        return None  # too short to judge
    hay = _norm(first_text)
    if not hay:
        return 0.0
    hit = sum(1 for t in toks if t in hay)
    return hit / len(toks)


# --- license statements ------------------------------------------------------------------
_CTX = re.compile(r"(open[\s-]+access|licen[cs]e|creative\s*commons|creativecommons|cc[\s-]*by|attribution|"
                  r"this\s+(is\s+an|article|work|source)|distributed\s+under|made\s+available\s+under|published\s+under|"
                  r"terms\s+of\s+the)", re.I)
_PATTERNS = [  # most specific first
    ("cc-by-nc-nd", r"(by[\s-]*nc[\s-]*nd\b|noncommercial[\s-]*no[\s-]*deriv|non[\s-]*commercial[\s-]*no[\s-]*deriv|licenses/by-nc-nd)"),
    ("cc-by-nd", r"(cc[\s-]*by[\s-]*nd\b|attribution[\s-]*no[\s-]*deriv|licenses/by-nd/)"),
    ("cc-by-nc-sa", r"(by[\s-]*nc[\s-]*sa\b|noncommercial[\s-]*share[\s-]*alike|non[\s-]*commercial[\s-]*share[\s-]*alike|licenses/by-nc-sa)"),
    ("cc-by-nc", r"(cc[\s-]*by[\s-]*nc\b(?![\s-]*(nd|sa))|attribution[\s-]*non[\s-]*commercial\b(?![\s-]*(no|share))|licenses/by-nc/)"),
    ("cc-by-sa", r"(cc[\s-]*by[\s-]*sa\b|attribution[\s-]*share[\s-]*alike|licenses/by-sa/)"),
    ("cc0", r"(\bcc0\b|cc[\s-]*zero|publicdomain/zero|public\s+domain\s+dedication)"),
    ("cc-by", r"(cc[\s-]*by\b(?![\s-]*(nc|nd|sa))|creative\s*commons\s+attribution\b(?![\s-]*(non|no|share))(?:\s*(?:\d(?:\.\d)?|international|license|licence|unported))|licenses/by/\d)"),
]
_PATTERNS = [(k, re.compile(p, re.I)) for k, p in _PATTERNS]
_ARR = re.compile(r"all\s+rights\s+reserved", re.I)


def license_from_text(first_text, last_text):
    """Return (license_token | None, evidence_snippet, all_found, all_rights_reserved)."""
    found = []
    for part in (first_text, last_text):
        flat = re.sub(r"\s+", " ", part or "")
        for m in _CTX.finditer(flat):
            win = flat[max(0, m.start() - 250): m.end() + 350]
            if _CREDIT_RX.search(flat[max(0, m.start() - 150): m.end() + 50]):
                continue  # figure/table credit, not the article's own license
            for k, rx in _PATTERNS:
                mm = rx.search(win)
                if mm:
                    found.append((k, win[max(0, mm.start() - 120): mm.end() + 120]))
                    break
    arr = bool(_ARR.search(first_text or "")) or bool(_ARR.search(last_text or ""))
    if not found:
        return None, "", [], arr
    kinds = [k for k, _ in found]
    # the source's own statement should dominate; if any ND statement is present, be conservative
    nd = [f for f in found if f[0] in ND_LICENSES]
    if nd:
        return nd[0][0], nd[0][1][:400], sorted(set(kinds)), arr
    best = max(set(kinds), key=kinds.count)
    snip = next(s for k, s in found if k == best)
    return best, snip[:400], sorted(set(kinds)), arr


# Article-level license statements (the source's OWN license, not a figure credit like
# "Reproduced from ref. 12 under CC BY"). Used as the strongest evidence for the corpus folder.
_ART_RX = re.compile(
    r"(this\s+(is\s+an?\s+)?(open[\s-]+access\s+)?(article|work|source|manuscript|chapter|review)\s+(is\s+)?"
    r"(licensed|distributed|published|made\s+available|available)\s+under"
    r"|open[\s-]+access\s+(this\s+)?(article|work)\s+(is\s+)?(licensed|distributed|published)\s+under"
    r"|(is|are)\s+(an?\s+)?open[\s-]+access\s+article\s+(distributed|published|licensed)\s+under"
    r"|this\s+article\s+is\s+an\s+open\s+access\s+article\s+distributed"
    r"|this\s+is\s+an?\s+open[\s-]+access\s+(article|source)\s+under"
    r"|(article|source)\s+(is\s+)?(distributed\s+|published\s+)?under\s+the\s+terms\s+(and\s+conditions\s+)?of\s+the\s+creative\s+commons"
    r"|content\s+from\s+this\s+work\s+may\s+be\s+used\s+under\s+the\s+terms\s+of"
    r"|published\s+under\s+(an?\s+|the\s+)?(creative\s+commons|cc[\s-]*by|acs\s+authorchoice)"
    r"|licen[cs]ed\s+under\s+(an?\s+|the\s+)?(creative\s+commons|cc[\s-]*by))", re.I)
_CREDIT_RX = re.compile(r"(reproduced|adapted|reprinted|modified)\s+(with\s+permission\s+)?from|\bref(s|erence)?\.?\s*\d", re.I)


def article_license(first_text, last_text):
    """Return (token, snippet) for the source's own license statement, or (None, "")."""
    for part in (first_text, last_text):
        flat = re.sub(r"\s+", " ", part or "")
        for m in _ART_RX.finditer(flat):
            win = flat[max(0, m.start() - 60): m.end() + 260]
            if _CREDIT_RX.search(flat[max(0, m.start() - 120): m.start()]):
                continue  # "... reproduced from ref. 5. This work is licensed under" -> a credit line
            for k, rx in _PATTERNS:
                mm = rx.search(win)
                if mm:
                    return k, win[:400]
            if re.search(r"creative\s*commons\s+attribution\s+(\d|license|licence|international)", win, re.I):
                return "cc-by", win[:400]
    return None, ""


def license_verdict(pdf_lic, meta_lic, pmc_license=None, arr=False):
    """Combine the PDF statement with metadata. Returns (keep, final_license, evidence)."""
    if pmc_license:
        t = pmc_license
        return (t in ALLOWED_LICENSES), t, "pmc_license_code"
    if pdf_lic in ND_LICENSES:
        return False, pdf_lic, "pdf_statement_nd"
    if pdf_lic in ALLOWED_LICENSES:
        return True, pdf_lic, "pdf_statement"
    if meta_lic in ALLOWED_LICENSES:
        if arr:
            return False, "all-rights-reserved", "pdf_all_rights_reserved_contradicts_metadata"
        return True, meta_lic, "metadata_only"
    return False, pdf_lic or meta_lic or "unknown", "license_unverified"
