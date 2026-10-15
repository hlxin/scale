"""Multimodal figure extractor — bundled so every extraction subagent doesn't reinvent it.

Given a PDF and a list of pages, extract candidate figure images and save them as PNGs.
The subagent then *reads* the candidates (Claude is multimodal), picks the one matching a
schema/description, and references its relative path in a Figure node. Keeping this
mechanical step in a script gives consistent output and saves every subagent from
re-deriving the pypdf/pymupdf fallback chain (the algorithm is inherited from
the earlier data-curation figure-attachment method).

Strategy (per page):
  A. pypdf per-embedded-image  → one PNG per raster embedded in the page (best for photos: TEM/SEM/XRD).
  B. pymupdf whole-page render → 1 PNG of the full page at --dpi (fallback for vector charts
     with no embedded raster; needs pymupdf — `pip install pymupdf`). The subagent should crop
     B-output to the figure region before adopting it (see templates/extraction_subagent.md).

Output:
  Saves PNGs to <out-dir> with names <prefix>_p<page>_img<i>.png (strategy A) or
  <prefix>_p<page>_full.png (strategy B), and prints a JSON manifest to stdout:
    {"saved": [{"path": "...", "page": 4, "size": [w, h], "method": "pypdf"}], "errors": [...]}

Usage:
    python extract_figures.py <pdf> --pages 4,6,7 --out <figures_dir> --prefix <paper_id>
    python extract_figures.py <pdf> --pages 4 --out figs --prefix 1 --dpi 220
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def ensure_pymupdf():
    """pymupdf is needed only for whole-page renders. It is never installed silently: install it yourself
    (pip install pymupdf) when the JSON reports it missing."""
    try:
        import fitz  # noqa: F401
        return True
    except Exception:
        return False


_DECOR = {}


def _sig(pil):
    w, h = pil.size
    return (w, h, pil.tobytes()[:4096])


def decorations(reader, path_key):
    """Signatures of rasters that repeat on several of the first pages (journal logos, page headers)."""
    if path_key in _DECOR:
        return _DECOR[path_key]
    seen, rep = {}, set()
    for pg in reader.pages[:min(5, len(reader.pages))]:
        try:
            for img in pg.images:
                sg = _sig(img.image)
                seen[sg] = seen.get(sg, 0) + 1
        except Exception:
            continue
    rep = {k for k, v in seen.items() if v >= 2}
    _DECOR[path_key] = rep
    return rep


def extract_pypdf(pdf_path: Path, page_num: int, out_dir: Path, prefix: str):
    """Strategy A: save each embedded raster on the page that looks like a figure. Returns (saved, errors)."""
    from pypdf import PdfReader
    saved = []
    reader = PdfReader(str(pdf_path))
    if page_num < 1 or page_num > len(reader.pages):
        return saved, [f"page {page_num} out of range (1..{len(reader.pages)})"]
    page = reader.pages[page_num - 1]
    errs = []
    try:
        images = list(page.images)
    except Exception as e:
        return saved, [f"pypdf page.images failed on p{page_num}: {e}"]
    decor = decorations(reader, str(pdf_path))
    for i, img in enumerate(images):
        try:
            pil = img.image
            w, h = pil.size
            # Skip tiny rasters (icons, rules), banner-shaped strips (journal headers) and rasters repeated across
            # pages (logos) — not figures. A page left with nothing falls back to a whole-page render.
            if w < 80 or h < 80 or max(w, h) / max(1, min(w, h)) > 5 or _sig(pil) in decor:
                continue
            dest = out_dir / f"{prefix}_p{page_num}_img{i}.png"
            if pil.mode not in ("RGB", "RGBA", "L", "LA", "P", "1"):
                pil = pil.convert("RGB")        # CMYK / YCbCr rasters cannot be written as PNG directly
            pil.save(str(dest))
            saved.append({"path": str(dest), "page": page_num, "size": [w, h], "method": "pypdf"})
        except Exception as e:
            errs.append(f"pypdf img{i} p{page_num}: {e}")
    return saved, errs


def extract_pymupdf_page(pdf_path: Path, page_num: int, out_dir: Path, prefix: str, dpi: int):
    """Strategy B: whole-page render. Subagent must crop afterwards."""
    if not ensure_pymupdf():
        return [], ["pymupdf is not installed (pip install pymupdf) — whole-page render unavailable"]
    import fitz
    try:
        doc = fitz.open(str(pdf_path))
        if page_num < 1 or page_num > doc.page_count:
            return [], [f"page {page_num} out of range (1..{doc.page_count})"]
        page = doc[page_num - 1]
        pix = page.get_pixmap(dpi=dpi)
        dest = out_dir / f"{prefix}_p{page_num}_full.png"
        pix.save(str(dest))
        return [{"path": str(dest), "page": page_num, "size": [pix.width, pix.height], "method": "pymupdf-fullpage"}], []
    except Exception as e:
        return [], [f"pymupdf p{page_num}: {e}"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--pages", required=True, help="comma-separated 1-based page numbers, e.g. 4,6,7")
    ap.add_argument("--out", type=Path, required=True, help="output dir for PNGs (e.g. <kg>/figures)")
    ap.add_argument("--prefix", required=True, help="filename prefix, typically the paper_id")
    ap.add_argument("--dpi", type=int, default=200, help="DPI for pymupdf whole-page fallback")
    ap.add_argument("--page-render", action="store_true",
                    help="force whole-page render (Strategy B) instead of per-image (A)")
    args = ap.parse_args()

    if not args.pdf.exists():
        print(json.dumps({"saved": [], "errors": [f"pdf not found: {args.pdf}"]}))
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        pages = [int(x) for x in str(args.pages).split(",") if x.strip()]
    except ValueError:
        print(json.dumps({"saved": [], "errors": [f"bad --pages value: {args.pages}"]}))
        return 1

    all_saved, all_errs = [], []
    for pg in pages:
        if args.page_render:
            s, e = extract_pymupdf_page(args.pdf, pg, args.out, args.prefix, args.dpi)
        else:
            s, e = extract_pypdf(args.pdf, pg, args.out, args.prefix)
            if not s:  # no embedded raster on this page → vector chart; fall back to page render
                s2, e2 = extract_pymupdf_page(args.pdf, pg, args.out, args.prefix, args.dpi)
                s += s2
                e += e2
        all_saved += s
        all_errs += e

    print(json.dumps({"saved": all_saved, "errors": all_errs}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
