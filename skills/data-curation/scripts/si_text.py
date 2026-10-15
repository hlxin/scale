"""Print the text of a supplementary file that the Read tool cannot open (.docx, .xlsx, .pptx, .odt, .txt/.csv).

Read-only; standard library only (Office files are zip archives of XML). Tables keep one row per line with cells
separated by ' | ', so values stay with their column headers.

  python3 -I si_text.py <file> [--max-chars 60000]
"""
import argparse
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


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
                cells = ["".join(x.text or "" for x in c.iter(f"{W}t")).strip() for c in row.iter(f"{W}tc")]
                out.append(" | ".join(cells))
            out.append("")
    return "\n".join(out)


def xlsx_text(z):
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{S}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{S}t")))
    out = []
    sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    for sh in sheets:
        out.append(f"## {Path(sh).stem}")
        for row in ET.fromstring(z.read(sh)).iter(f"{S}row"):
            vals = []
            for c in row.iter(f"{S}c"):
                v = c.find(f"{S}v")
                txt = v.text if v is not None else "".join(t.text or "" for t in c.iter(f"{S}t"))
                if c.get("t") == "s" and txt is not None and txt.isdigit() and int(txt) < len(shared):
                    txt = shared[int(txt)]
                vals.append((txt or "").strip())
            if any(vals):
                out.append(" | ".join(vals))
    return "\n".join(out)


def pptx_text(z):
    out = []
    for n in sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                    key=lambda n: int(re.findall(r"\d+", n)[-1])):
        out.append(f"## {Path(n).stem}")
        out += [t.text for t in ET.fromstring(z.read(n)).iter(f"{A}t") if t.text and t.text.strip()]
    return "\n".join(out)


def odt_text(z):
    root = ET.fromstring(z.read("content.xml"))
    return "\n".join("".join(el.itertext()) for el in root.iter() if el.tag.endswith("}p") and "".join(el.itertext()).strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--max-chars", type=int, default=60000)
    a = ap.parse_args()
    ext = a.file.suffix.lower()
    try:
        if ext in (".txt", ".csv", ".tsv", ".md"):
            text = a.file.read_text(errors="ignore")
        else:
            with zipfile.ZipFile(a.file) as z:
                text = {".docx": docx_text, ".xlsx": xlsx_text, ".pptx": pptx_text, ".odt": odt_text}.get(ext, docx_text)(z)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        print(f"cannot read {a.file.name}: {e}", file=sys.stderr)
        return 1
    print(text[:a.max_chars] + ("\n[... truncated ...]" if len(text) > a.max_chars else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
