"""Add a list of papers to a topic: DOIs, a database or reference-manager export, or a web page that lists papers
(journal table of contents, lab publication page, a review's reference list).

Exports read: Web of Science (Plain text, Tab-delimited, BibTeX, RIS), Scopus (CSV, BibTeX, RIS), Zotero / EndNote /
Mendeley (BibTeX, RIS, CSV), this skill's own index CSVs, and plain lists of DOIs (.txt, .json). The file's abstract
and author keywords are kept (placeholders such as "[No abstract available]" and the trailing copyright line are
dropped; a longer Crossref abstract wins), and a Web of Science or Scopus export adds that database to the paper's
Database column. Metadata comes from Crossref for every DOI; entries without a DOI keep the file's title/authors/year
and are matched by title later. Imported papers skip the topic gate (you chose them). Then run build_list.py as usual.

  python3 -I import_list.py --topic <slug> --file savedrecs.txt   # .txt .bib .ris .csv .tsv .json (auto-detected)
  python3 -I import_list.py --topic <slug> --url https://...      # static page: every DOI on it
For pages that need a browser (JavaScript, login), open them in Claude in Chrome, copy the DOIs into a .txt file and
import that file. Excel exports (.xls, .xlsx) are not read: export Plain text, Tab-delimited, CSV, BibTeX or RIS.
"""
import argparse
import csv
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (HTTPFail, Project, add_project_arg, clean_text, die, get_json, http_get, jsonl_append, load_config,
                     log, norm_doi, normalize_abstract, now_iso, polite_email, update_state)
from _sources import crossref_items

DOI_RX = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>{}|\\^`\[\]]+)", re.I)
ORIGIN_LABEL = {"wos": "Web of Science export", "scopus": "Scopus export"}
SCOPUS_EID_RX = re.compile(r"\b(2-s2\.0-\d+)")
TY_TYPE = {"JOUR": "article", "JFULL": "article", "MGZN": "article", "CONF": "conference-paper", "CPAPER": "conference-paper",
           "CHAP": "book-chapter", "BOOK": "book", "EBOOK": "book", "THES": "thesis", "RPRT": "report", "PAT": "patent",
           "DATA": "dataset", "DBASE": "dataset", "UNPB": "preprint"}


def dois_in_text(text):
    out = []
    for m in DOI_RX.finditer(text or ""):
        d = norm_doi(m.group(1).rstrip(".,;:)]}>'\""))
        if d and d not in out:
            out.append(d)
    return out


def clean_abstract(t):
    """An export's abstract -> plain text, or '' for a placeholder (heading and copyright line removed)."""
    return normalize_abstract(t)


def split_keywords(v):
    v = clean_text(v)
    if not v:
        return []
    parts = v.split(";") if ";" in v else v.split(",")
    return [p.strip() for p in parts if p.strip()][:25]


def entry(doi=None, title="", year="", journal="", authors=None, abstract="", keywords=None, type=None, origin=None,
          ids=None):
    return {"doi": norm_doi(doi) if doi else None, "title": clean_text(title), "year": str(year or "")[:4],
            "journal": clean_text(journal), "authors": [clean_text(a) for a in authors or [] if clean_text(a)],
            "abstract": clean_abstract(abstract), "keywords": keywords or [], "type": type or None, "origin": origin,
            "ids": {k: v for k, v in (ids or {}).items() if v}}


# ---------------------------------------------------------------- BibTeX (WoS, Scopus, Zotero, Mendeley)
FIELD_RX = re.compile(r"[\s,]*([A-Za-z][\w\-:.]*)\s*=\s*")
BARE_RX = re.compile(r"[^,}\s]*")


def bib_fields(body):
    """`name = {balanced braces} | "quoted" | bare,` ... -> {lowercase name: raw value}"""
    out, i, n = {}, 0, len(body)
    while i < n:
        m = FIELD_RX.match(body, i)
        if not m:
            break
        name, i = m.group(1).lower(), m.end()
        if i < n and body[i] in "{\"":
            close, depth, j = ("}" if body[i] == "{" else "\""), 0, i
            while j < n:
                c = body[j]
                if c == "\\":
                    j += 2
                    continue
                if close == "}":
                    depth += (c == "{") - (c == "}")
                    if depth == 0:
                        break
                elif c == "\"" and j > i:
                    break
                j += 1
            val, i = body[i + 1:j], j + 1
        else:
            m2 = BARE_RX.match(body, i)
            val, i = m2.group(0), m2.end()
        val = re.sub(r"\\([&%$#_])", r"\1", val).replace("{", "").replace("}", "")
        out.setdefault(name, re.sub(r"\s+", " ", val).strip())
    return out


def parse_bibtex(text):
    entries = []
    for block in re.split(r"\n\s*@", "\n" + text)[1:]:
        m = re.match(r"(\w+)\s*\{\s*([^,\s]*)\s*,", block)
        if not m or m.group(1).lower() in ("comment", "string", "preamble"):
            continue
        f = bib_fields(block[m.end():])
        key, src, url = m.group(2), f.get("source", "").lower(), f.get("url", "")
        wos_id = next((x for x in (key, f.get("unique-id", "")) if x.upper().startswith("WOS:")), None)
        eid = SCOPUS_EID_RX.search(url + " " + f.get("eid", ""))
        origin = "wos" if wos_id or "web of science" in src else "scopus" if (eid or "scopus" in src) else None
        entries.append(entry(doi=f.get("doi"), title=f.get("title", ""), year=f.get("year", ""),
                             journal=f.get("journal") or f.get("booktitle") or f.get("journaltitle", ""),
                             authors=[a for a in re.split(r"\s+and\s+", f.get("author", "")) if a.strip()],
                             abstract=f.get("abstract", ""),
                             keywords=split_keywords(f.get("author_keywords") or f.get("keywords", "")),
                             type=f.get("type") or m.group(1), origin=origin,
                             ids={"wos": wos_id.upper() if wos_id else None, "scopus": eid.group(1) if eid else None}))
    return entries


# ---------------------------------------------------------------- RIS (WoS, Scopus, EndNote, Zotero)
RIS_RX = re.compile(r"^([A-Z][A-Z0-9])\s{1,2}-\s?(.*)$")


def parse_ris(text):
    entries, cur, last = [], None, None
    for line in text.splitlines():
        m = RIS_RX.match(line)
        if not m:
            if cur is not None and last in ("AB", "N2", "TI", "T1") and line.strip():
                cur[last][-1] += " " + line.strip()       # wrapped abstract or title
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == "TY":
            cur, last = {"TY": [val]}, "TY"
        elif tag == "ER":
            if cur:
                entries.append(ris_entry(cur))
            cur, last = None, None
        elif cur is not None:
            cur.setdefault(tag, []).append(val)
            last = tag
    return entries


def ris_entry(f):
    first = lambda *tags: next((f[t][0] for t in tags if f.get(t) and f[t][0]), "")
    db, urls = " ".join(f.get("DB") or []).lower(), " ".join((f.get("UR") or []) + (f.get("L3") or []))
    wos_id = next((x for x in (f.get("AN") or []) + (f.get("UT") or []) if x.upper().startswith("WOS:")), None)
    eid = SCOPUS_EID_RX.search(urls)
    origin = "wos" if (wos_id or "web of science" in db) else "scopus" if ("scopus" in db or eid) else None
    doi = first("DO") or next(iter(dois_in_text(urls)), None)
    abstract = max((f.get("AB") or []) + (f.get("N2") or []), key=len, default="")
    year = re.search(r"(19|20)\d\d", first("PY", "Y1", "DA") or "")
    return entry(doi=doi, title=first("TI", "T1"), year=year.group(0) if year else "",
                 journal=first("T2", "JF", "JO", "J2"), authors=(f.get("AU") or []) + (f.get("A1") or []),
                 abstract=abstract, keywords=[k for k in f.get("KW") or [] if k][:25],
                 type=first("M3") or TY_TYPE.get(first("TY")), origin=origin,
                 ids={"wos": wos_id.upper() if wos_id else None, "scopus": eid.group(1) if eid else None})


# ---------------------------------------------------------------- Web of Science Plain text
def parse_wos_plain(text):
    """FN/VR header, records PT ... ER, two-letter tags, continuation lines indented by three spaces."""
    entries, cur, last = [], None, None
    for line in text.lstrip("﻿").splitlines():
        if line.startswith("   ") and cur is not None and last:
            cur[last].append(line.strip())
            continue
        tag, val = line[:2], line[3:].strip()
        if not re.match(r"^[A-Z][A-Z0-9]$", tag):
            continue
        if tag == "PT":
            cur, last = {"PT": [val]}, "PT"
        elif tag == "ER":
            if cur:
                entries.append(wos_entry(cur))
            cur, last = None, None
        elif cur is not None and tag not in ("FN", "VR", "EF"):
            cur.setdefault(tag, []).append(val)
            last = tag
    return entries


def wos_entry(f):
    """WoS field tags (plain text: one list item per line; tab-delimited: one string per tag) -> entry."""
    join = lambda t: " ".join(x for x in f.get(t) or [] if x)
    authors = [a.strip() for line in (f.get("AF") or f.get("AU") or []) for a in line.split(";") if a.strip()]
    year = re.search(r"(19|20)\d\d", join("PY") or join("EA") or join("PD"))
    ut = join("UT")
    return entry(doi=join("DI"), title=join("TI"), year=year.group(0) if year else "", journal=join("SO"),
                 authors=authors, abstract=join("AB"), keywords=split_keywords(join("DE")), type=join("DT") or None,
                 origin="wos", ids={"wos": ut.upper() if ut.upper().startswith("WOS:") else (ut or None)})


# ---------------------------------------------------------------- tables: Scopus CSV, WoS Tab-delimited, Zotero, index CSVs
COLS = {"doi": ("doi", "doi/id", "di"),
        "title": ("title", "article title", "ti"),
        "year": ("year", "publication year", "py"),
        "journal": ("source title", "journal", "venue", "publication title", "so"),
        "abstract": ("abstract", "abstract note", "ab"),
        "keywords": ("author keywords", "keywords", "de", "manual tags"),
        "authors": ("author full names", "authors", "author", "af", "au"),
        "type": ("document type", "doc type", "item type", "publication type", "dt")}


def parse_table(text, delimiter=None):
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t").delimiter
        except csv.Error:
            delimiter = ","
    quoting = csv.QUOTE_NONE if delimiter == "\t" else csv.QUOTE_MINIMAL   # WoS tab-delimited quotes nothing
    out = []
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿")), delimiter=delimiter, quoting=quoting):
        low = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items() if k}
        get = lambda f: next((low[c] for c in COLS[f] if low.get(c)), "")
        ut, eid = low.get("ut", ""), low.get("eid", "")
        if ut.upper().startswith("WOS:") or {"pt", "ut", "ti"} <= set(low):
            out.append(wos_entry({k.upper(): [v] for k, v in low.items()}))
            continue
        origin = "scopus" if (eid.startswith("2-s2.0-") or low.get("source", "").lower() == "scopus") else None
        doi = norm_doi(get("doi"))
        if not doi:
            found = dois_in_text(" ".join(low.values()))
            doi = found[0] if found else None
        authors = [re.sub(r"\s*\(\d+\)\s*$", "", a).strip() for a in re.split(r";", get("authors")) if a.strip()]
        out.append(entry(doi=doi, title=get("title"), year=get("year"), journal=get("journal"), authors=authors,
                         abstract=get("abstract"), keywords=split_keywords(get("keywords")), type=get("type") or None,
                         origin=origin, ids={"scopus": eid or None}))
    return out


def read_text(path):
    raw = Path(path).read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return next((raw.decode(e) for e in ("utf-8-sig", "cp1252", "latin-1") if _decodes(raw, e)), "")


def read_entries(path):
    ext = Path(path).suffix.lower()
    if ext in (".xls", ".xlsx"):
        die("Excel exports are not read: export the list as Plain text, Tab-delimited, CSV, BibTeX or RIS instead")
    text = read_text(path).lstrip("﻿")
    first = text.split("\n", 1)[0].rstrip("\r")
    cols = {c.strip().upper() for c in first.split("\t")}
    if re.match(r"FN\s", first) or (re.search(r"^PT [A-Z]\s*$", text, re.M) and re.search(r"^ER\s*$", text, re.M)):
        return parse_wos_plain(text)
    if "\t" in first and ({"PT", "UT"} <= cols or {"AU", "TI"} <= cols):
        return parse_table(text, delimiter="\t")
    if ext == ".bib" or re.search(r"^\s*@\w+\s*\{", text, re.M):
        return parse_bibtex(text)
    if ext == ".ris" or re.search(r"^TY\s{1,2}-", text, re.M):
        return parse_ris(text)
    if ext in (".csv", ".tsv"):
        return parse_table(text, delimiter="\t" if ext == ".tsv" else None)
    if ext == ".json":
        data = json.loads(text)
        items = data if isinstance(data, list) else data.get("items") or data.get("dois") or []
        return [entry(doi=x) if isinstance(x, str) else entry(doi=x.get("doi"), title=x.get("title", ""),
                                                               abstract=x.get("abstract", "")) for x in items]
    return [entry(doi=d) for d in dois_in_text(text)]


def _decodes(raw, enc):
    try:
        raw.decode(enc)
        return True
    except UnicodeDecodeError:
        return False


def crossref_lookup(dois):
    recs = []
    for i in range(0, len(dois), 40):
        chunk = dois[i:i + 40]
        params = {"filter": ",".join("doi:" + d for d in chunk), "rows": len(chunk)}
        if polite_email():
            params["mailto"] = polite_email()
        try:
            d = get_json("https://api.crossref.org/works", params=params, tries=5, timeout=(20, 120))
            recs += crossref_items(d)
        except HTTPFail as e:
            log(f"crossref lookup failed for {len(chunk)} DOIs: {e}")
    return recs


def add_file_fields(r, e):
    """Keep what the export knows: its abstract (when longer), author keywords, database of origin, WoS/Scopus ids."""
    if e.get("abstract") and len(e["abstract"]) > len(clean_text(r.get("abstract"))):
        r["abstract"] = e["abstract"]
        r["abstract_source"] = ORIGIN_LABEL.get(e.get("origin"), "Imported list")
    elif r.get("abstract"):
        r.setdefault("abstract_source", "Crossref")
    if e.get("keywords"):
        r["keywords"] = list(dict.fromkeys(list(r.get("keywords") or []) + e["keywords"]))[:25]
    if e.get("origin"):
        r["found_in"] = [e["origin"]]
    if e.get("ids"):
        r["ids"] = {**e["ids"], **{k: v for k, v in (r.get("ids") or {}).items() if v}}
    return r


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--file")
    g.add_argument("--url")
    a = ap.parse_args()
    proj = Project(a.project)
    load_config(proj, a.topic)
    if a.url:
        r = http_get(a.url, headers={"Accept": "text/html,application/xhtml+xml"}, tries=3, timeout=(20, 60))
        entries = [entry(doi=d) for d in dois_in_text(r.text)]
        origin = a.url
    else:
        if not Path(a.file).exists():
            die(f"no such file: {a.file}")
        entries = read_entries(a.file)
        origin = str(a.file)
    by_doi = {}
    for e in entries:
        if e.get("doi"):
            by_doi.setdefault(e["doi"], e)
    dois = list(by_doi)
    log(f"{len(entries)} entries, {len(dois)} DOIs")
    recs = crossref_lookup(dois)
    from_crossref = set()
    for r in recs:
        d = norm_doi(r.get("doi"))
        from_crossref.add(d)
        if d in by_doi:
            add_file_fields(r, by_doi[d])
    seen = set(from_crossref)
    for e in entries:
        if (e.get("doi") and e["doi"] not in seen) or (not e.get("doi") and len((e.get("title") or "").split()) >= 4):
            if e.get("doi"):
                seen.add(e["doi"])
            recs.append(add_file_fields({"doi": e.get("doi"), "title": e.get("title") or "", "abstract": "",
                                         "year": e.get("year") or None, "journal": e.get("journal") or None,
                                         "authors": e.get("authors") or [], "type": e.get("type")}, e))
    out = []
    for r in recs:
        r.update({"source": "manual", "qid": "import", "doi": norm_doi(r.get("doi")),
                  "title": clean_text(r.get("title")), "abstract": clean_text(r.get("abstract"))[:6000]})
        if not r["abstract"]:
            r.pop("abstract_source", None)
        out.append(r)
    jsonl_append(proj.topic_dir(a.topic) / "raw" / "manual" / "manual.jsonl", out)
    res = {"origin": origin, "entries": len(entries), "dois": len(dois), "metadata_from_crossref": len(from_crossref & set(dois)),
           "without_doi": sum(1 for r in out if not r["doi"]), "records_written": len(out),
           "exports": dict(Counter(ORIGIN_LABEL.get(e.get("origin"), "other") for e in entries)),
           "abstract_from_file": sum(1 for r in out if r.get("abstract_source") in (*ORIGIN_LABEL.values(), "Imported list")),
           "without_abstract": sum(1 for r in out if not r["abstract"]),
           "next": f"build_list.py --topic {a.topic} --run manual"}
    update_state(proj, a.topic, lambda st: st.setdefault("imports", []).append({**res, "at": now_iso()}))
    print(json.dumps(res))


if __name__ == "__main__":
    main()
