"""Page texts of a source document, for verbatim quote checks and passage search.

A page's text comes from the PDF's text layer when it has one, and otherwise from Tesseract OCR of
the rendered page. Each page records where its text came from (``text_layer`` or ``ocr``), so a
quote checked against OCR is known to be checked against OCR. Nothing is corrected by hand.

Needs PyMuPDF (``pip install pymupdf``) and, for OCR, the ``tesseract`` command.
"""

from __future__ import annotations

import collections
import hashlib
import re
import shutil
import subprocess
from pathlib import Path

from .util import ScaleError

MIN_CHARS = 40          # a page with less text than this in its text layer is treated as an image


def _fitz():
    try:
        import pymupdf
    except ImportError as e:  # pragma: no cover
        raise ScaleError("reading PDFs needs PyMuPDF: pip install pymupdf") from e
    return pymupdf


def tesseract_version() -> str | None:
    exe = shutil.which("tesseract")
    if not exe:
        return None
    out = subprocess.run([exe, "--version"], capture_output=True, text=True)
    return (out.stdout or out.stderr).splitlines()[0].strip()


def _tesseract(png: bytes, lang: str, psm: str) -> str:
    exe = shutil.which("tesseract")
    if not exe:
        raise ScaleError("this page has no text layer and tesseract is not installed (brew install tesseract)")
    out = subprocess.run([exe, "stdin", "stdout", "-l", lang, "--psm", psm], input=png, capture_output=True)
    if out.returncode:
        raise ScaleError(f"tesseract failed: {out.stderr.decode(errors='replace')[:200]}")
    return out.stdout.decode("utf-8", errors="replace")


def ocr_page(page, dpi: int = 300, lang: str = "eng", columns: int = 1) -> str:
    """OCR one page. With columns=2 each half of the page is read on its own, left then right (the
    two-column layout of early US patents), so lines of the two columns are not interleaved."""
    if columns == 1:
        return _tesseract(page.get_pixmap(dpi=dpi).tobytes("png"), lang, "3")
    if columns != 2:
        raise ScaleError("OCR reads one or two columns")
    r = page.rect
    mid = r.x0 + r.width * gutter(page)
    parts = []
    for x0, x1 in ((r.x0, mid), (mid, r.x1)):
        clip = type(r)(x0, r.y0, x1, r.y1)
        parts.append(_tesseract(page.get_pixmap(dpi=dpi, clip=clip).tobytes("png"), lang, "4"))
    return "\n\n".join(parts)


def gutter(page, lo: float = 0.35, hi: float = 0.65) -> float:
    """The page fraction where the two columns part: the centre of the widest run of low-ink pixel
    columns between lo and hi (the gutter, which may hold line numbers), measured on a grey render."""
    pix = page.get_pixmap(dpi=60, colorspace="gray")
    w, h, data = pix.width, pix.height, pix.samples
    top, bottom = int(h * 0.12), int(h * 0.95)             # skip the heading, which spans both columns
    ink = []
    for x in range(w):
        dark = 0
        for y in range(top, bottom):
            if data[y * pix.stride + x] < 128:
                dark += 1
        ink.append(dark)
    a, b = int(w * lo), int(w * hi)
    floor = min(ink[a:b])
    limit = floor + max(2, int((bottom - top) * 0.02))
    best, run_start, best_span = None, None, (0, 0)
    for x in range(a, b + 1):
        low = x < b and ink[x] <= limit
        if low and run_start is None:
            run_start = x
        elif not low and run_start is not None:
            if x - run_start > best_span[1] - best_span[0]:
                best_span = (run_start, x)
            run_start = None
    best = (best_span[0] + best_span[1]) / 2 if best_span[1] > best_span[0] else (a + b) / 2
    return best / w


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_pages(pdf: str | Path, ocr: str = "auto", lang: str = "eng", dpi: int = 300, columns: int = 1) -> dict:
    """Return {pdf_sha256, page_count, ocr_engine, pages: [{page, origin, text}]}.

    ocr: ``auto`` (OCR pages without a text layer), ``always`` or ``never``; columns: the page layout for OCR."""
    pdf = Path(pdf)
    fz = _fitz()
    doc = fz.open(pdf)
    pages, used_ocr = [], False
    for i, page in enumerate(doc, start=1):
        text = page.get_text()
        if ocr == "always" or (ocr == "auto" and len(text.strip()) < MIN_CHARS):
            text, origin, used_ocr = ocr_page(page, dpi, lang, columns), "ocr", True
        else:
            origin = "text_layer"
        pages.append({"page": i, "origin": origin, "text": text})
    return {"pdf_sha256": sha256_file(pdf), "page_count": len(pages),
            "ocr_engine": (f"{tesseract_version()} ({lang}, {dpi} dpi, {columns} column{'s' if columns > 1 else ''})" if used_ocr else None),
            "pages": pages}


def joined(pages: list[dict]) -> str:
    """The whole text, pages separated, for verbatim quote checks."""
    return "\n\n".join(p["text"] for p in pages)


# ------------------------------------------------------------------------------------------ images and positioned OCR
# For reading scanned pages with two independent readers: a page image (read by a vision-capable
# curator) and OCR words with their positions and confidences (read by Tesseract). A value read from
# the image is checked against the OCR words in the same region (see ``region_agreement``).

def render_page(pdf: str | Path, page_no: int, dpi: int = 200, clip: tuple[float, float, float, float] | None = None) -> bytes:
    """PNG of a page (1-based), or of a region of it given as page fractions (x0, y0, x1, y1)."""
    fz = _fitz()
    doc = fz.open(Path(pdf))
    page = doc[page_no - 1]
    r = page.rect
    rect = None
    if clip:
        x0, y0, x1, y1 = clip
        rect = type(r)(r.x0 + r.width * x0, r.y0 + r.height * y0, r.x0 + r.width * x1, r.y0 + r.height * y1)
    return page.get_pixmap(dpi=dpi, clip=rect).tobytes("png")


def ocr_words(png: bytes, lang: str = "eng", psm: str = "3") -> list[dict]:
    """Tesseract words of an image: {text, conf (0-100), box (x0, y0, x1, y1) as fractions of the image}."""
    exe = shutil.which("tesseract")
    if not exe:
        raise ScaleError("tesseract is not installed (brew install tesseract)")
    out = subprocess.run([exe, "stdin", "stdout", "-l", lang, "--psm", psm, "tsv"], input=png, capture_output=True)
    if out.returncode:
        raise ScaleError(f"tesseract failed: {out.stderr.decode(errors='replace')[:200]}")
    lines = out.stdout.decode("utf-8", errors="replace").splitlines()
    head = lines[0].split("\t")
    idx = {k: i for i, k in enumerate(head)}
    rows = [ln.split("\t") for ln in lines[1:]]
    page = next((r for r in rows if r[idx["level"]] == "1"), None)
    W, H = (float(page[idx["width"]]), float(page[idx["height"]])) if page else (1.0, 1.0)
    words = []
    for r in rows:
        if len(r) < len(head) or r[idx["level"]] != "5" or not r[idx["text"]].strip():
            continue
        x, y, w, h = (float(r[idx[k]]) for k in ("left", "top", "width", "height"))
        words.append({"text": r[idx["text"]], "conf": round(float(r[idx["conf"]]), 1),
                      "box": [round(x / W, 4), round(y / H, 4), round((x + w) / W, 4), round((y + h) / H, 4)]})
    return words


def text_layer_words(pdf: str | Path, page_no: int) -> list[dict]:
    """Words of a page's text layer with their boxes (fractions of the page); conf is None."""
    fz = _fitz()
    page = fz.open(Path(pdf))[page_no - 1]
    r = page.rect
    return [{"text": w[4], "conf": None, "box": [round((w[0] - r.x0) / r.width, 4), round((w[1] - r.y0) / r.height, 4),
                                                   round((w[2] - r.x0) / r.width, 4), round((w[3] - r.y0) / r.height, 4)]}
            for w in page.get_text("words")]


def in_region(words: list[dict], region: tuple[float, float, float, float], pad: float = 0.005) -> list[dict]:
    x0, y0, x1, y1 = region
    return [w for w in words if w["box"][0] >= x0 - pad and w["box"][1] >= y0 - pad
            and w["box"][2] <= x1 + pad and w["box"][3] <= y1 + pad]


# OCR commonly reads these characters for digits in old print
_DIGIT_LIKE = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "l": "1", "I": "1", "|": "1", "i": "1", "!": "1",
                             "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2", "G": "6", "b": "6", "g": "9", "q": "9",
                             "A": "4", "T": "7", "·": ".", "•": "."})
_SUPER_SUB = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻₀₁₂₃₄₅₆₇₈₉", "0123456789-0123456789")
NUMBER = re.compile(r"\d+(?:\.\d+)?|(?<![\w.])\.\d+")     # 5.2, 300 and a leading-decimal .0891


def numbers_in(text: str, lenient: bool = False) -> list[str]:
    """The numbers in a text; lenient reads OCR look-alikes (O->0, l->1, S->5, …) inside digit runs.

    Raised and lowered digits are read as digits, so that "Nm³", "CO₂", "10²" and "10⁻⁴" give the same
    numbers as "Nm3", "CO2", "10^2" and "10-4": after a digit they are an exponent, a number of their own."""
    text = re.sub(r"(\d)[·•](?=10\s*(?:[⁰¹²³⁴⁵⁶⁷⁸⁹⁻]|\^))", r"\1 × ", text)      # 1·10⁴: a multiplication dot
    text = re.sub(r"(\)[₀-₉\d]?|[₀-₉])[.·](?=\d{0,2}[A-Z])", r"\1 · ", text)   # Mg(NO₃)₂.6H₂O: a hydrate dot
    text = re.sub(r"(?<=[\d₀-₉])(?=[⁰¹²³⁴⁵⁶⁷⁸⁹⁻])|(?<=\d)(?=[₀-₉])", " ", text).translate(_SUPER_SUB)
    if lenient:
        text = re.sub(r"[0-9OoDQlI|i!SsBZzGbgqAT·•,.]+", lambda m: m.group(0).translate(_DIGIT_LIKE)
                      if re.search(r"\d", m.group(0)) else m.group(0), text)
    text = re.sub(r"(\d)[·•](\d)", r"\1.\2", text)                     # 5·2: a raised decimal point
    text = re.sub(r"(\d),-\s*(\d{3})(?!\d)", r"\1\2", text)             # 100,- / 000: a number broken across lines
    text = re.sub(r"(?<![\d.,])0,(\d)", r"0.\1", text)             # 0,305: a decimal comma (no thousands after 0)
    text = re.sub(r"(\d),\s?(\d{3})(?!\d)" if lenient else r"(\d),(\d{3})(?!\d)", r"\1\2", text)
    # 16,200 is a thousands separator; OCR also splits it ("10, 000"), a curator's "Fig. 4, 350 °C" is two numbers
    text = re.sub(r"(\d),(\d)", r"\1.\2", text)                     # 2,5: a decimal comma
    return [("0" + n if n.startswith(".") else n.rstrip(".")) for n in NUMBER.findall(text.replace(" ", " "))]


_SUPER = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
_FRACTION = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3}
_SCI = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:[×xX*·]|\s?\.)?\s*10\s*\^?\s*([-−–]?\s*\d{1,2})(?!\d)")


def values_in(text: str) -> list[float]:
    """Every value a printed text can stand for, to decide whether a recorded value is backed by it.

    Printed numbers are ambiguous out of context, so each plausible reading is kept: the numbers of
    numbers_in; a comma (0,305; 501,8) or a colon (2:2, a damaged raised point) read as a decimal point as
    well as a thousands separator; digits
    grouped by a space or a point (24 250; 1.685 in German print); a power of ten (2.07 × 10⁻⁵, 4,46 .10-5, 1×10⁴, 2,316.10⁻⁴); and the
    fraction glyphs (½, 1½); and each number scaled by a power of ten printed without a mantissa, as in a
    column header "Kp [× 10⁻⁵]"."""
    t = text.translate(_SUPER).replace("\u2009", " ").replace("\u00a0", " ")
    out = [float(n) for n in numbers_in(t)]
    out += [float(n) for n in NUMBER.findall(re.sub(r"(\d)[,:](\d)", r"\1.\2", t))]      # 2:2, a damaged raised point
    out += [float(re.sub(r"[ .]", "", m.group(0))) for m in re.finditer(r"(?<![\d.,])\d{1,3}(?:( |\.)\d{3})(?:\1\d{3})*(?![\d,]|\.\d)", t)]
    for m in re.finditer(r"(?:(\d+(?:[.,]\d+)?)\s*(?:-|–|to)\s*)?" + _SCI.pattern, t):   # 0.5-0.6 × 10⁻²: a range
        exp = int(re.sub(r"[−–\s]", lambda c: "" if c.group(0).isspace() else "-", m.group(3)))
        out += [float(x.replace(",", ".")) * 10 ** exp for x in (m.group(1), m.group(2)) if x]
    header = [int(re.sub(r"[−–\s]", lambda c: "" if c.group(0).isspace() else "-", e)) for e in
              re.findall(r"(?<![\d.,\s])\s*[×xX*]\s*10\s*\^?\s*([-−–]?\s*\d{1,2})(?!\d)", t)]
    plain = [float(n) for n in numbers_in(t)]
    for e in set(header):          # a column header "Kp [× 10⁻⁵]": each printed number is scaled, in either sense
        out += [x * 10 ** e for x in plain] + [x * 10 ** -e for x in plain]
    for m in re.finditer(r"(\d*)\s?([½¼¾⅓⅔])", t):
        out.append((int(m.group(1)) if m.group(1) else 0) + _FRACTION[m.group(2)])
    return out


def region_agreement(transcription: str, region_words: list[dict], kind: str | None = None) -> dict:
    """How far the numbers a curator read in a region are also read by OCR there.

    agree: every number of the transcription is among the OCR numbers (look-alikes allowed);
    partial: some are; disagree: none are; no_ocr: OCR found no numbers in the region. A transcription
    without numbers agrees when OCR reads each of its words; one with fraction glyphs (½) is no_ocr."""
    # a single raised or lowered digit after a letter (H₂, cm³, Al₂O₃) is a formula or unit, which OCR drops;
    # it is not compared (Zn₇₅ or Zn75, a composition, is)
    formula = re.sub(r"(?<=[A-Za-z)\]])[₀-₉⁰¹²³⁴⁵⁶⁷⁸⁹](?![₀-₉⁰¹²³⁴⁵⁶⁷⁸⁹])", "", transcription)
    formula = re.sub(r"([A-Z][a-z]?|\))\d(?=[A-Z(),.·\s]|$)", r"\1", formula)        # Cr2O3, Cu(NO3)2 in plain type
    want = numbers_in(formula)
    ocr_text = " ".join(w["text"] for w in region_words)
    if kind == "figure":           # a plotted point is not text: OCR cannot confirm it, a second reader must
        return {"agreement": "no_ocr", "numbers": want, "missing": want, "ocr_text": ocr_text}
    # how often OCR reads each number, in the reading that finds it most often: strict too (a run label "275A"
    # is 275, not a look-alike 2754), and with split digit groups joined (OCR splits "16 200")
    have = collections.Counter()
    joined = re.sub(r"(?<=\d) (?=\d)", "", ocr_text)      # only digit groups are joined: letters stay letters
    for variant in (numbers_in(ocr_text, lenient=True), numbers_in(joined, lenient=True), numbers_in(ocr_text)):
        for n, k in collections.Counter(variant).items():
            have[n] = max(have[n], k)
    if re.search(r"[½¼¾⅓⅔]", transcription):     # OCR cannot read fraction glyphs: a second reader must
        return {"agreement": "no_ocr", "numbers": want, "missing": want, "ocr_text": ocr_text}
    if not want:                   # no number: the words must be OCR's words ("group VIII" is not "group VII")
        said = {w.casefold() for w in re.findall(r"\w{2,}", re.sub(r"(\w)-\s+(\w)", r"\1\2", ocr_text))}
        words = re.findall(r"\w{2,}", transcription)
        missing = [w for w in words if w.casefold() not in said]
        # a Roman numeral or a short token must be read exactly; OCR may garble some long heading words
        strict = [w for w in missing if re.fullmatch(r"[IVXLC]+", w) or len(w) <= 4]
        status = ("agree" if not strict and len(missing) <= 0.3 * len(words) else
                  "no_ocr" if not said else "partial")
        return {"agreement": status, "numbers": [], "missing": missing, "ocr_text": ocr_text}
    if not have:
        return {"agreement": "no_ocr", "numbers": want, "missing": want, "ocr_text": ocr_text}
    missing, left = [], collections.Counter(have)      # each number is read as often as it is printed: "5% 5%" is not "9% 5%"
    for n in want:
        k = n if left[n] > 0 else n.replace(".", "")
        if left[k] > 0:
            left[k] -= 1
        else:
            missing.append(n)
    # a number followed by a word ("30 pounds") is read by OCR next to the same word: "column 30 … 80 pounds" is
    # not "30 pounds", though it has a 30
    def pairs(text, lenient):
        toks = re.findall(r"[\d.,]*\d|[A-Za-z]{3,}", text)
        out = set()
        for a, b in zip(toks, toks[1:]):
            if re.match(r"\d", a) and b.isalpha():
                out |= {(n, b.casefold()) for n in numbers_in(a, lenient=lenient)}
        return out
    seen = pairs(ocr_text, True) | pairs(ocr_text, False)
    seen_words = {w.casefold() for w in re.findall(r"[A-Za-z]{3,}", ocr_text)}
    for n, w in sorted(pairs(formula, False)):
        if n not in missing and w in seen_words and (n, w) not in seen and (n.replace(".", ""), w) not in seen:
            missing.append(n)          # OCR reads the word, but with another number before it
    status = "agree" if not missing else ("disagree" if len(missing) >= len(want) else "partial")
    confs = [w["conf"] for w in region_words if w.get("conf") is not None]
    return {"agreement": status, "numbers": want, "missing": missing, "ocr_text": ocr_text,
            "ocr_mean_conf": round(sum(confs) / len(confs), 1) if confs else None}
