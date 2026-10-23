"""The text of a source's supporting-information files, as pages the verbatim check can read.

Supporting information belongs to its source's Source (docs/curation.md), so its text joins the source's page texts:
`append(texts_file, si_files)` adds each file's pages after the source's, headed `[page S1]`, `[page S2]` … with a line
naming the file, and returns what was read. PDFs are read with PyMuPDF (the text layer; a page without one stays
empty, and its values are read from the page image with `scale pages`); Office files are zip archives of XML, read with
the standard library, tables one row per line with cells separated by " | "; plain text files as they are. Other
formats are left out and listed with the reason. Deterministic: the same files give the same pages.
"""
import hashlib
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
PLAIN = (".txt", ".csv", ".tsv", ".md")
OFFICE = (".docx", ".xlsx", ".pptx", ".odt")


def docx_text(z):
    root = ET.fromstring(z.read("word/document.xml"))
    out = []
    body = root.find(f"{W}body")
    for el in list(body) if body is not None else []:
        if el.tag == f"{W}p":
            t = "".join(x.text or "" for x in el.iter(f"{W}t"))
            if t.strip():
                out.append(t)
        elif el.tag == f"{W}tbl":
            for row in el.iter(f"{W}tr"):
                out.append(" | ".join("".join(x.text or "" for x in c.iter(f"{W}t")).strip() for c in row.iter(f"{W}tc")))
            out.append("")
    return ["\n".join(out)]


def xlsx_text(z):
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{S}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{S}t")))
    pages = []
    for sh in sorted((n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                     key=lambda n: int(re.findall(r"\d+", n)[-1])):
        rows = [f"## {Path(sh).stem}"]
        for row in ET.fromstring(z.read(sh)).iter(f"{S}row"):
            vals = []
            for c in row.iter(f"{S}c"):
                v = c.find(f"{S}v")
                txt = v.text if v is not None else "".join(t.text or "" for t in c.iter(f"{S}t"))
                if c.get("t") == "s" and txt is not None and txt.isdigit() and int(txt) < len(shared):
                    txt = shared[int(txt)]
                vals.append((txt or "").strip())
            if any(vals):
                rows.append(" | ".join(vals))
        pages.append("\n".join(rows))                     # one page per sheet
    return pages


def pptx_text(z):
    pages = []
    for n in sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                    key=lambda n: int(re.findall(r"\d+", n)[-1])):
        pages.append("\n".join(t.text for t in ET.fromstring(z.read(n)).iter(f"{A}t") if t.text and t.text.strip()))
    return pages                                          # one page per slide


def odt_text(z):
    root = ET.fromstring(z.read("content.xml"))
    return ["\n".join("".join(el.itertext()) for el in root.iter()
                      if el.tag.endswith("}p") and "".join(el.itertext()).strip())]


def pdf_pages(path):
    import fitz                                           # PyMuPDF, as `scale source start` uses
    with fitz.open(str(path)) as doc:
        return [page.get_text() for page in doc]


def pages_of(path):
    """(pages, None) or ([], reason)."""
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            return pdf_pages(path), None
        if ext in PLAIN:
            return [path.read_text(encoding="utf-8", errors="ignore")], None
        if ext in OFFICE:
            with zipfile.ZipFile(path) as z:
                return {".docx": docx_text, ".xlsx": xlsx_text, ".pptx": pptx_text, ".odt": odt_text}[ext](z), None
    except ImportError:
        return [], "reading a PDF needs PyMuPDF (pip install pymupdf)"
    except (zipfile.BadZipFile, KeyError, ET.ParseError, RuntimeError, ValueError) as e:
        return [], f"unreadable: {type(e).__name__}"
    return [], f"format {ext or 'unknown'} is not read (an image, archive or data file: look at it yourself)"


def append(texts_file, si_files):
    """Append the SI files' pages to the page texts file; returns one entry per file (what was read, or why not)."""
    texts_file = Path(texts_file)
    out, n, chunks = [], 0, []
    for f in si_files:
        f = Path(f)
        entry = {"file": f.name, "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}
        pages, reason = pages_of(f)
        if reason:
            entry["left_out"] = reason
        else:
            first = n + 1
            for p in pages:
                n += 1
                chunks.append(f"[page S{n}]\nSupporting information file: {f.name}\n{p.rstrip()}\n")
            entry.update(pages=f"S{first}-S{n}" if n > first else f"S{first}", chars=sum(len(p) for p in pages))
        out.append(entry)
    if chunks:
        text = texts_file.read_text(encoding="utf-8") if texts_file.exists() else ""
        texts_file.parent.mkdir(parents=True, exist_ok=True)
        texts_file.write_text(text.rstrip("\n") + "\n\n" + "\n".join(chunks), encoding="utf-8")
    return out
