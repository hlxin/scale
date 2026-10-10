"""Readings of scanned pages by two readers: the page image, read by a curator, checked against OCR.

    scale pages render PDF --source ID --pages DIR [--dpi 200] [--only 1,3]
    scale pages region --pages DIR --source ID PAGE X0 Y0 X1 Y1 [--transcription TEXT]
    scale pages agree DOC --pages DIR
    scale pages check DOC --pages DIR [--second FILE]
    scale pages pending DOC --pages DIR [--no-crops] [--out FILE]
    scale pages merge-second DOC SECOND
    scale pages import CACHE --pages DIR [--overwrite] [--written-here]

Old scans lose values in their text layer or OCR: table cells run together, exponents and subscripts vanish,
digits turn into letters. The curator (a person or a vision-capable model) reads the **page image** as well as
the text; Tesseract reads the same page with word positions and confidences. A value read from the image gets
evidence with ``reading: vision_ocr`` (or ``vision``), the ``region`` it was read in (x0, y0, x1, y1 as fractions
of the page, origin top left, on the PDF page its ``locator`` starts with: ``p. 3, Table II``) and the curator's
``transcription``. The rules, applied by :func:`check`:

1. **The agreement is the tool's.** ``agree`` compares each transcription with the OCR words in its region
   (``sourcetext.region_agreement``) and writes ``agreement`` (agree, partial, disagree, no_ocr) on the evidence,
   and the OCR engines it used in the document's top-level ``ocr_engines`` (beside ``graph``, not a schema
   property). A curator never writes either. The check recomputes every agreement: a difference is an error when
   the words it reads were written by the engines the document records, and a warning when they were not
   (another Tesseract or renderer can read a region differently; the recorded agreement stands).
2. **A reading OCR does not confirm needs an independent second reading** of the same region by another curator
   who has not seen the first transcription (``pending`` lists the crops, never the transcription;
   ``merge-second`` puts the readings on the evidence). Its numbers must be the transcription's; a figure point
   (``kind: figure``, which OCR cannot read) within 5 % or 0.3, since plotted points are read off a grid. A value
   neither OCR nor a second reader confirms is left out and listed as an ``extraction_error`` gap.
3. **Every number of a record read from an image is in one of its transcriptions or quotes** (unsigned; a value
   printed in words, such as "atmospheric pressure", has no printed number to find).

DOC is a curated document: a scale-graph document or a curation fragment (any JSON object with ``nodes`` and
``links``). DIR, the pages folder, holds for each source ``DIR/<key>/`` (key: the Source id's last segment):
``p<N>.png`` (page images, for the curator's eyes), ``p<N>.words.json`` (the positioned words of the text layer and
of OCR, with the engine that wrote them), ``regions/<region key>.json`` (a 400 dpi OCR of a region, cached),
``crops/`` and ``source.json`` (the PDF the pages were rendered from and its sha256). Page images and OCR words
reproduce whole pages of the source: they stay local and are never committed or distributed. The document keeps
the agreements and the engines they were computed with, so a reader holding the same PDF can rebuild the words
(``render``) and re-run the check.

Rendering needs PyMuPDF (``pip install "scale-catal[pdf]"``) and OCR the ``tesseract`` command; ``agree`` and
``check`` read only cached words until a region has none. Deterministic for the same document and cached words.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import sourcetext
from .util import ScaleError, dump_canonical, load_doc, sha256_file

VISION = ("vision", "vision_ocr")            # evidence read from the page image
LOCATOR = re.compile(r"^p\. ?(\d+)(?:[-–](\d+))?\b")
PAGE_DPI, WORDS_DPI, REGION_DPI = 200, 300, 400
SECOND_MARGIN = 0.02                # page fraction added around a region in the second reader's crop
FIGURE_TOLERANCE = (0.05, 0.3)      # a figure point: two readings agree within 5 % or 0.3 (grid reading)
_SUBSCRIPT = re.compile(r"(?<=[A-Za-z)\]])[₀-₉⁰¹²³⁴⁵⁶⁷⁸⁹]{1,3}(?![₀-₉⁰¹²³⁴⁵⁶⁷⁸⁹.·])")


# ------------------------------------------------------------------------------------------ the pages folder
def source_key(source_id: str) -> str:
    """The folder of a source in the pages folder: the last segment of its id (``ex:demo/source/s1`` -> ``s1``)."""
    last = re.split(r"[/:]", str(source_id).rstrip("/"))[-1]
    key = re.sub(r"[^A-Za-z0-9._-]+", "-", last).strip("-.")
    if not key:
        raise ScaleError(f"{source_id!r}: a source id needs a last segment to name its pages folder")
    return key


def folder(pages: str | Path, source_id: str) -> Path:
    return Path(pages) / source_key(source_id)


def region_key(page: int, region: list[float]) -> str:
    return f"p{page}_" + "_".join(f"{x:.3f}" for x in region)


def region_id(source_id: str, page: int, region: list[float]) -> str:
    """A region across sources (``<source key>/<region key>``): what ``pending`` lists and a second reading names."""
    return f"{source_key(source_id)}/{region_key(page, region)}"


def valid_region(r) -> bool:
    return (isinstance(r, list) and len(r) == 4 and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                                         and 0 <= x <= 1 for x in r)
            and r[0] < r[2] and r[1] < r[3])


def evidence_page(ev: dict) -> int | None:
    """The PDF page a locator starts with (``p. 3, Table II`` -> 3)."""
    m = LOCATOR.match(ev.get("locator") or "")
    return int(m.group(1)) if m else None


def ocr_engine() -> str:
    """The OCR that runs here: Tesseract's version and language, and the renderer that makes its images."""
    return f"{sourcetext.tesseract_version()} (eng); pymupdf {sourcetext._fitz().__version__}"


_PDF_CHECKED: dict[tuple, Path] = {}


def pdf_of(pages: str | Path, source_id: str) -> Path:
    """The PDF a source's pages were rendered from (``source.json``), refused when it is gone or has changed."""
    f = folder(pages, source_id) / "source.json"
    if not f.is_file():
        raise ScaleError(f"no PDF recorded for {source_id} in {pages}: run `scale pages render PDF --source {source_id} "
                         f"--pages {pages}`")
    rec = json.loads(f.read_text(encoding="utf-8"))
    pdf = Path(rec.get("pdf") or "")
    if not pdf.is_file():
        raise ScaleError(f"{f}: the PDF {pdf} is not there; render the pages again from the PDF you hold")
    st = pdf.stat()
    key = (str(pdf), st.st_size, st.st_mtime_ns)
    if key not in _PDF_CHECKED:
        if rec.get("sha256") and sha256_file(pdf) != rec["sha256"]:
            raise ScaleError(f"{pdf} is not the PDF {f} records (sha256 differs); render the pages again")
        _PDF_CHECKED[key] = pdf
    return pdf


def render(pdf: str | Path, source_id: str, pages: str | Path, dpi: int = PAGE_DPI, only: list[int] | None = None) -> dict:
    """Page images for the curator's eyes (``dpi``, PNG) and positioned words for the check: the text layer's words
    and Tesseract's words with confidences (300 dpi), per page, with the OCR engine. Existing files are kept."""
    pdf = Path(pdf)
    if not pdf.is_file():
        raise ScaleError(f"{pdf}: no PDF there")
    n = len(sourcetext._fitz().open(pdf))
    nums = list(only) if only else list(range(1, n + 1))
    bad = [p for p in nums if not 1 <= p <= n]
    if bad:
        raise ScaleError(f"{pdf} has pages 1-{n}; asked for {bad}")
    d = folder(pages, source_id)
    d.mkdir(parents=True, exist_ok=True)
    digest = sha256_file(pdf)
    rec_file = d / "source.json"
    if rec_file.is_file():
        rec = json.loads(rec_file.read_text(encoding="utf-8"))
        if rec.get("source") != source_id or rec.get("sha256") != digest:
            raise ScaleError(f"{d} holds the pages of {rec.get('source')} from a PDF with sha256 {rec.get('sha256')}; "
                             f"not {source_id} from {pdf}")
    rec_file.write_text(dump_canonical({"source": source_id, "pdf": str(pdf.resolve()), "sha256": digest, "pages": n}),
                        encoding="utf-8")
    engine = None
    for pg in nums:
        png, words = d / f"p{pg}.png", d / f"p{pg}.words.json"
        if not png.exists():
            png.write_bytes(sourcetext.render_page(pdf, pg, dpi))
        if not words.exists():
            engine = engine or ocr_engine()
            words.write_text(dump_canonical({"page": pg, "text_layer": sourcetext.text_layer_words(pdf, pg),
                                             "ocr": sourcetext.ocr_words(sourcetext.render_page(pdf, pg, WORDS_DPI)),
                                             "ocr_engine": engine}), encoding="utf-8")
    return {"source": source_id, "folder": str(d), "pages": len(nums), "of": n}


def page_words(pages: str | Path, source_id: str, page: int) -> dict:
    """``{text_layer: [...], ocr: [...], ocr_engine}``: the words of a page with their boxes, as ``render`` wrote them."""
    f = folder(pages, source_id) / f"p{page}.words.json"
    if not f.exists():
        raise ScaleError(f"no page words for {source_id} p. {page} in {pages}: run `scale pages render PDF --source "
                         f"{source_id} --pages {pages}` (or `scale pages import` for another folder's words)")
    return json.loads(f.read_text(encoding="utf-8"))


def region_reading(pages: str | Path, source_id: str, page: int, region: list[float]) -> dict:
    """``{words, engines}``: the words the text layer and OCR place in a region (the page's words there and a fresh
    400 dpi OCR of the region itself, cached and mapped back to page coordinates), and the OCR engines that produced
    them (``"None"`` for words cached without their engine)."""
    pw = page_words(pages, source_id, page)
    words = sourcetext.in_region(pw.get("text_layer") or [], region) + sourcetext.in_region(pw.get("ocr") or [], region)
    cache = folder(pages, source_id) / "regions" / f"{region_key(page, region)}.json"
    if cache.exists():
        got = json.loads(cache.read_text(encoding="utf-8"))
        crop, crop_engine = (got, None) if isinstance(got, list) else (got["words"], got.get("ocr_engine"))
    else:
        x0, y0, x1, y1 = region
        raw = sourcetext.ocr_words(sourcetext.render_page(pdf_of(pages, source_id), page, REGION_DPI, tuple(region)), psm="6")
        crop = [{**w, "box": [round(x0 + w["box"][0] * (x1 - x0), 4), round(y0 + w["box"][1] * (y1 - y0), 4),
                              round(x0 + w["box"][2] * (x1 - x0), 4), round(y0 + w["box"][3] * (y1 - y0), 4)]} for w in raw]
        crop_engine = ocr_engine()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(dump_canonical({"ocr_engine": crop_engine, "words": crop}), encoding="utf-8")
    return {"words": words + crop, "engines": sorted({str(pw.get("ocr_engine")), str(crop_engine)})}


def region(pages: str | Path, source_id: str, page: int, box: list[float], dpi: int = REGION_DPI,
           transcription: str | None = None) -> dict:
    """A zoomed image of a region (``crops/<region key>.png``, for a close reading) and what OCR reads there; with a
    transcription, the agreement the tool would record."""
    if not valid_region(box):
        raise ScaleError("a region is x0 y0 x1 y1, page fractions with x0 < x1 and y0 < y1")
    crop = folder(pages, source_id) / "crops" / f"{region_key(page, box)}.png"
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(sourcetext.render_page(pdf_of(pages, source_id), page, dpi, tuple(box)))
    words = region_reading(pages, source_id, page, box)["words"]
    text = " ".join(w["text"] for w in words)
    confs = [w["conf"] for w in words if w.get("conf") is not None]
    res = {"region_id": region_id(source_id, page, box), "crop": str(crop), "ocr_text": text,
           "ocr_numbers": sourcetext.numbers_in(text, lenient=True),
           "ocr_mean_conf": round(sum(confs) / len(confs), 1) if confs else None}
    if transcription:
        res["agreement"] = sourcetext.region_agreement(transcription, words)
    return res


# ------------------------------------------------------------------------------------------ the check
def _records(doc: dict) -> list[dict]:
    if not isinstance(doc, dict) or not isinstance(doc.get("nodes", []), list) or not isinstance(doc.get("links", []), list):
        raise ScaleError("a curated document is a JSON object with nodes and links")
    return [r for r in (doc.get("nodes") or []) + (doc.get("links") or []) if isinstance(r, dict)]


def _image_evidence(rec: dict):
    for i, ev in enumerate((rec.get("props") or {}).get("evidence") or []):
        if isinstance(ev, dict) and ev.get("reading") in VISION:
            yield i, ev


def record_numbers(props: dict) -> list[str]:
    """The numbers of a record's value objects (its own properties and its results, conditions and properties maps),
    unsigned: a printed sign ("-", "−", "–") is not part of the numbers read from a transcription or quote. A value
    printed in words (``as_reported`` without digits, e.g. "atmospheric pressure" recorded as 1 atm) has no printed
    number and is left out."""
    out = []

    def take(v):
        if isinstance(v, dict) and v.get("status", "present") == "present":
            words = v.get("as_reported")
            if isinstance(words, str) and words.strip() and not re.search(r"\d", words):
                return                  # printed in words ("atmospheric pressure", "Nil"): no printed number to find
            out.extend(str(abs(v[k])) for k in ("value", "lower", "upper")
                       if isinstance(v.get(k), (int, float)) and not isinstance(v.get(k), bool))
    for k, v in props.items():
        if k in ("results", "conditions", "properties") and isinstance(v, dict):
            for x in v.values():
                take(x)
        elif k != "evidence":
            take(v)
    return out


def readings_match(a: list[str], b: list[str], figure: bool = False) -> bool:
    """The second reading confirms the first: every number of the first transcription is also read by the second
    reader (each matched once; for a figure point within FIGURE_TOLERANCE). The second reader may read more (a row
    label, the composition and temperature a figure point stands for)."""
    rel, ab = FIGURE_TOLERANCE if figure else (0.0, 0.0)
    pool = [float(v) for v in b]
    for v in sorted({float(x) for x in a}):        # a number written twice is one reading
        hit = next((i for i, q in enumerate(pool) if abs(v - q) <= max(rel * abs(v), ab) + 1e-9), None)
        if hit is None:
            return False
        pool.pop(hit)
    return True


def check(doc: dict, pages: str | Path, second: dict | None = None, warnings: list[str] | None = None) -> list[str]:
    """The errors of the evidence a document read from page images (see the module docstring). ``second`` holds
    second readings not yet merged (``{"<record id>#<evidence index>" or region id: reading}``). An agreement the
    OCR here does not reproduce is an error when the document records the same OCR engines as the cached words
    (``ocr_engines``, written by ``agree``), and a warning (into ``warnings``) when the engines differ or were not
    recorded; without a ``warnings`` list it is an error."""
    errs: list[str] = []
    waiting: dict[str, list[str]] = {}
    second = second or {}
    recorded = doc.get("ocr_engines")
    for rec in _records(doc):
        rid, props = str(rec.get("id")), rec.get("props") or {}
        vis = list(_image_evidence(rec))
        for i, ev in vis:
            page, src = evidence_page(ev), ev.get("source")
            if not src:
                errs.append(f"{rid}: evidence[{i}] read from the image names no source")
                continue
            if page is None:
                errs.append(f"{rid}: evidence[{i}] read from the image needs a locator that starts with the PDF page "
                            f"('p. 3, Table II')")
                continue
            if not valid_region(ev.get("region")):
                errs.append(f"{rid}: evidence[{i}] read from the image needs region [x0, y0, x1, y1] (page fractions)")
                continue
            if not ev.get("transcription"):
                errs.append(f"{rid}: evidence[{i}] read from the image needs a transcription")
                continue
            try:
                rr = region_reading(pages, src, page, ev["region"])
                got = sourcetext.region_agreement(ev["transcription"], rr["words"], ev.get("kind"))
            except ScaleError as e:
                errs.append(f"{rid}: evidence[{i}]: {e}")
                continue
            if ev.get("agreement") != got["agreement"]:
                same_engine = recorded is not None and set(rr["engines"]) <= set(recorded)
                if same_engine or warnings is None or ev.get("agreement") is None:
                    errs.append(f"{rid}: evidence[{i}] agreement is {ev.get('agreement')!r}, the tool computes "
                                f"{got['agreement']!r} (run `scale pages agree`; the agreement is never written by hand)")
                else:
                    warnings.append(f"{rid}: evidence[{i}] agreement {ev.get('agreement')!r} was computed with "
                                    f"{recorded or 'an OCR engine the document does not record'}; the OCR here "
                                    f"({', '.join(rr['engines'])}) computes {got['agreement']!r}. The recorded agreement "
                                    f"stands; bring in the words it was computed from (`scale pages import`) or re-run "
                                    f"`scale pages agree` with them")
                    got = {**got, "agreement": ev["agreement"]}
            if got["agreement"] != "agree":
                rk = region_id(src, page, ev["region"])
                sr = ev.get("second_reading") or second.get(f"{rid}#{i}") or second.get(rk)
                if not sr:
                    waiting.setdefault(rk, []).append(f"{rid}#{i}")
                else:
                    # notation written in sub- or superscripts (H₂, cm³, d²⁰₄) is not a reading of a value; a
                    # composition (Zn₆₆.₆) is
                    a_ = sourcetext.numbers_in(_SUBSCRIPT.sub("", ev["transcription"]))
                    b_ = sourcetext.numbers_in(re.sub(r"(?<![A-Za-z])[oO](?=[.,]\d)", "0", sr))   # a typed "o,45" is 0,45
                    if not readings_match(a_, b_, ev.get("kind") == "figure"):
                        errs.append(f"{rid}: evidence[{i}] the second reading {b_} does not give the numbers of the "
                                    f"transcription {a_}")
        if vis:        # every number of a record read from an image is backed by a transcription or a quote
            evs = [ev for ev in props.get("evidence") or [] if isinstance(ev, dict)]
            backed = [abs(x) for ev in evs
                      for x in sourcetext.values_in((ev.get("transcription") or "") + " " + (ev.get("quote") or ""))]
            for n in record_numbers(props):
                if not any(abs(float(n) - b) <= 1e-9 * max(1.0, abs(b)) for b in backed):
                    errs.append(f"{rid}: value {n} is in no transcription or quote of the record")
    for rk, keys in sorted(waiting.items()):     # one error per region: a second reader reads a region once
        errs.append(f"region {rk}: OCR does not confirm the reading of {len(keys)} evidence item(s) ({keys[0]}"
                    f"{', …' if len(keys) > 1 else ''}); it needs an independent second reading (`scale pages pending`)")
    return errs


def agree(doc: dict, pages: str | Path) -> dict:
    """Write the tool-computed agreement onto every evidence item read from an image (in place), and the OCR engines
    every agreement was computed with in ``ocr_engines``."""
    counts: dict[str, int] = {}
    need: list[str] = []
    engines: set[str] = set()
    for rec in _records(doc):
        for i, ev in _image_evidence(rec):
            page = evidence_page(ev)
            if page is None or not ev.get("source") or not valid_region(ev.get("region")) or not ev.get("transcription"):
                continue                  # `check` names what is missing
            rr = region_reading(pages, ev["source"], page, ev["region"])
            engines |= set(rr["engines"])
            got = sourcetext.region_agreement(ev["transcription"], rr["words"], ev.get("kind"))
            ev["agreement"] = got["agreement"]
            counts[got["agreement"]] = counts.get(got["agreement"], 0) + 1
            if got["agreement"] != "agree" and not ev.get("second_reading"):
                need.append(f"{rec.get('id')}#{i}")
    if engines:
        doc["ocr_engines"] = sorted(engines)       # the OCR every agreement above was computed with
    return {"agreement": dict(sorted(counts.items())), "need_second_reading": len(need), "ocr_engines": sorted(engines)}


def pending(doc: dict, pages: str | Path, crops: bool = True) -> list[dict]:
    """The regions a second reader must read: one item per region with its locator, kind and (with ``crops``) a
    400 dpi crop with a margin, never the first transcription."""
    by_region: dict[str, dict] = {}
    for rec in _records(doc):
        for i, ev in _image_evidence(rec):
            page = evidence_page(ev)
            if (ev.get("agreement") in (None, "agree") or ev.get("second_reading") or page is None or not ev.get("source")
                    or not valid_region(ev.get("region"))):
                continue
            rk = region_id(ev["source"], page, ev["region"])
            item = by_region.get(rk)
            if item is None:
                crop = None
                if crops:      # with a margin: a tight region must not cut off what the second reader needs
                    crop = folder(pages, ev["source"]) / "crops" / f"{region_key(page, ev['region'])}.second.png"
                    if not crop.exists():
                        crop.parent.mkdir(parents=True, exist_ok=True)
                        x0, y0, x1, y1 = ev["region"]
                        padded = (max(0.0, x0 - SECOND_MARGIN), max(0.0, y0 - SECOND_MARGIN),
                                  min(1.0, x1 + SECOND_MARGIN), min(1.0, y1 + SECOND_MARGIN))
                        crop.write_bytes(sourcetext.render_page(pdf_of(pages, ev["source"]), page, REGION_DPI, padded))
                item = by_region[rk] = {"region_id": rk, "source": ev["source"], "page": page, "locator": ev.get("locator"),
                                        "region": ev["region"], "kind": ev.get("kind"),
                                        "crop": str(crop) if crop else None, "keys": []}
            item["keys"].append(f"{rec.get('id')}#{i}")
    return sorted(by_region.values(), key=lambda x: x["region_id"])


def merge_second(doc: dict, second: dict) -> int:
    """Copy second readings (``{"<record id>#<evidence index>" or region id: reading}``) onto the evidence read from
    images, in place; returns how many were written."""
    if not isinstance(second, dict) or not all(isinstance(v, str) for v in second.values()):
        raise ScaleError("second readings are a JSON object: {\"<record id>#<i>\" or \"<region id>\": \"what was read\"}")
    n = 0
    for rec in _records(doc):
        for i, ev in _image_evidence(rec):
            page = evidence_page(ev)
            rk = (region_id(ev["source"], page, ev["region"])
                  if page is not None and ev.get("source") and valid_region(ev.get("region")) else None)
            reading = second.get(f"{rec.get('id')}#{i}") or (second.get(rk) if rk else None)
            if reading:
                ev["second_reading"] = reading
                n += 1
    return n


def import_words(cache: str | Path, pages: str | Path, overwrite: bool = False, written_here: bool = False) -> dict:
    """Copy page words and region words from another pages folder (an older cache, another machine's) into
    ``pages``. Existing files are kept unless ``overwrite``: the folder whose OCR the agreements were computed with
    overwrites, so that every machine checks against that OCR. ``written_here`` records this machine's engine with
    every file (the curator states that the cache was written here; refused when a file names another Tesseract)."""
    cache, pages = Path(cache), Path(pages)
    if not cache.is_dir():
        raise ScaleError(f"{cache}: no pages folder there")
    copied = kept = 0
    for src in sorted(cache.glob("*/p*.words.json")) + sorted(cache.glob("*/regions/*.json")):
        dest = pages / src.relative_to(cache)
        if dest.exists() and not overwrite:
            kept += 1
            continue
        got = json.loads(src.read_text(encoding="utf-8"))
        if src.parent.name == "regions" and isinstance(got, list):
            got = {"ocr_engine": None, "words": got}         # a region cache written before engines were recorded
        if written_here:
            stated = got.get("ocr_engine")
            if stated and not stated.startswith(str(sourcetext.tesseract_version())):
                raise ScaleError(f"{src} records {stated!r}, not the OCR here ({ocr_engine()}); import it without "
                                 f"--written-here")
            got["ocr_engine"] = ocr_engine()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(dump_canonical(got), encoding="utf-8")
        copied += 1
    return {"copied": copied, "kept": kept, "into": str(pages)}


def load(path: str | Path) -> dict:
    p = Path(path)
    if not p.is_file():
        raise ScaleError(f"{p}: no document there")
    doc = load_doc(p)
    _records(doc)
    return doc

