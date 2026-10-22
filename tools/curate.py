"""One publication into a scale-catal document: a subgraph to study one paper, patent or report.

    scale source start (--doi DOI | --pdf FILE | --text FILE, or a DOI with either) [--out DIR]
                       [--domain catalysis] [--version V] [--email ADDRESS] [--contributor ID]
    scale source check DIR [--derive-links]
    scale source finish DIR [--public] [--bundle] [--title TITLE]

``start`` is deterministic and writes a working folder; the reading itself (what the source reports, as records and
links with verbatim evidence) is done by the agent that runs it, following the curate-corpus skill
(skills/curate-corpus/SKILL.md); ``check`` holds the agent's graph to the schema, the source text and the
copyright cap; ``finish`` makes what can be shared.

**start.** A DOI is resolved through Crossref (title, authors, year, venue, type, licence). With a contact address
(``--email`` or ``SCALE_CONTACT_EMAIL``; never assumed), Unpaywall is asked for an open-access copy, and the PDF is
downloaded only when that copy carries an open licence (Creative Commons or public domain); otherwise the user gives
the PDF (``--pdf``) or its text (``--text``). A PDF's page texts are extracted (the text layer, OCR where a page has
none; ``pip install "scale-schema[pdf]"`` and the tesseract command). The folder::

    <slug>.graph.json      the graph to fill: header pinning the schema version, the Source record, the steward
    source.json            what was resolved and read: metadata, licence, PDF digest, page-text origins
    rights.yaml            the source's rights class, which the copyright cap reads
    BRIEF.md               what to curate and how: the schema's labels and checklist, the commands, the rules
    pdfs/<slug>.pdf        the PDF (local; git-ignored)
    work/texts/<slug>.txt  its page texts, each page headed "[page N]" (local; the verbatim check reads them)

**check.** Validates the graph under the schema it pins with every quote checked against the page texts, reports the
checklist conformance and the gaps, and counts quoted characters against the cap (``ok`` only with no error).

**finish.** Builds the evidence index; with ``--public``, writes ``<slug>.public.graph.json`` with quoted text capped
(only an in-copyright source's text is withheld, as sha256 and length); with ``--bundle``, exports that graph (or the
graph, without ``--public``) as a kg-bundle under ``bundle/`` with a short title.

Network access is only in :func:`resolve_doi` and :func:`download`, through ``fetch`` (replaceable, for tests).
"""

from __future__ import annotations

import datetime as _dt
import html
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from . import __version__, layout, pgraph, rights
from .util import ScaleError, dump_yaml, find_repo_root, load_doc, write_canonical

CROSSREF = "https://api.crossref.org/works/"
UNPAYWALL = "https://api.unpaywall.org/v2/"
EMAIL_ENV = "SCALE_CONTACT_EMAIL"
KINDS = {"journal-article": "article", "proceedings-article": "article", "posted-content": "preprint",
         "book": "book", "book-chapter": "book", "monograph": "book", "dissertation": "thesis", "report": "report",
         "standard": "report", "dataset": "other", "peer-review": "review_report"}
TEXT_VERSIONS = {"publishedVersion": "version_of_record", "acceptedVersion": "accepted_manuscript",
                 "submittedVersion": "submitted_manuscript"}
OPEN = re.compile(r"creativecommons\.org/(licenses|publicdomain)/|^cc[-_ ]?(by|0|zero)|^public[-_ ]domain|^pd$", re.I)
PUBLIC_DOMAIN = re.compile(r"creativecommons\.org/publicdomain/|^cc[-_ ]?(0|zero)|^public[-_ ]domain|^pd$", re.I)
Fetch = Callable[[str, dict], bytes]


def clean(text: str | None) -> str | None:
    """Registry text as a reader sees it: HTML entities unescaped, markup (<sup>, <i>, MathML) removed, spaces collapsed."""
    if text is None:
        return None
    t = re.sub(r"<sup>\s*[\d*\u2020\u2021,\s]+</sup>", "", text, flags=re.I)        # footnote markers go
    return " ".join(re.sub(r"<[^>]+>", "", html.unescape(t)).split()) or None


def fetch(url: str, headers: dict) -> bytes:
    """GET ``url`` (30 s timeout); the only network call of this module, replaced in tests."""
    req = urllib.request.Request(url, headers={"User-Agent": f"scale-schema/{__version__}", **headers})
    with urllib.request.urlopen(req, timeout=30) as r:      # noqa: S310  (https URLs built here)
        return r.read()


def normalize_doi(doi: str) -> str:
    """A DOI from a DOI, a doi: CURIE or a doi.org link, lowercased (DOIs are case-insensitive)."""
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", doi.strip(), flags=re.I).strip()
    if not re.match(r"^10\.\d{4,9}/\S+$", d):
        raise ScaleError(f"not a DOI: {doi!r} (expected 10.<registrant>/<suffix>, a doi: CURIE or a doi.org link)")
    return d.lower()


def slug_of(doi: str | None, pdf: Path | None) -> str:
    """The source's slug: the DOI with / as - (as the methanol example names its sources), else the PDF's name."""
    if doi:
        return doi.replace("/", "-")
    base = re.sub(r"[^a-z0-9._-]+", "-", (pdf.stem if pdf else "source").lower()).strip("-.")
    return base or "source"


def rights_class(licences: list[str]) -> str:
    """public_domain, open or in_copyright from licence URLs or ids (anything unknown is in copyright)."""
    if any(PUBLIC_DOMAIN.search(x or "") for x in licences):
        return "public_domain"
    return "open" if any(OPEN.search(x or "") for x in licences) else "in_copyright"


def resolve_doi(doi: str, email: str | None = None, get: Fetch = fetch) -> dict:
    """Metadata of a DOI from Crossref, and its best open-access copy from Unpaywall when ``email`` is given:
    ``{doi, title, authors, year, venue, kind, publisher, licences, url, open_access: {pdf, licence, version, host} | None,
    notes}``."""
    doi = normalize_doi(doi)
    notes: list[str] = []
    try:
        msg = json.loads(get(CROSSREF + urllib.parse.quote(doi), {"Accept": "application/json"}))["message"]
    except Exception as exc:  # noqa: BLE001  (a network or registry failure is reported, not raised)
        raise ScaleError(f"{doi}: Crossref could not resolve it ({exc}); give the PDF with --pdf, or the metadata later "
                         "in the Source record") from None
    parts = (msg.get("issued") or msg.get("published-print") or msg.get("published-online") or {}).get("date-parts") or [[]]
    year = parts[0][0] if parts and parts[0] else None
    out = {"doi": doi, "title": clean((msg.get("title") or [""])[0]),
           "authors": [clean(" ".join(x for x in (a.get("given"), a.get("family")) if x) or a.get("name", ""))
                       for a in msg.get("author") or []],
           "year": year, "published_on": "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(parts[0])) if year else None,
           "venue": clean((msg.get("container-title") or [None])[0]), "kind": KINDS.get(msg.get("type"), "other"),
           "publisher": clean(msg.get("publisher")), "licences": [x.get("URL") for x in msg.get("license") or [] if x.get("URL")],
           "url": msg.get("URL") or f"https://doi.org/{doi}", "open_access": None, "notes": notes}
    if not email:
        notes.append(f"no contact address (--email or {EMAIL_ENV}): no open-access copy was looked for")
        return out
    try:
        oa = json.loads(get(f"{UNPAYWALL}{urllib.parse.quote(doi)}?email={urllib.parse.quote(email)}", {}))
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Unpaywall could not be asked ({exc})")
        return out
    loc = oa.get("best_oa_location") or {}
    if loc.get("url_for_pdf"):
        out["open_access"] = {"pdf": loc["url_for_pdf"], "licence": loc.get("license"), "version": loc.get("version"),
                              "host": loc.get("host_type"), "landing": loc.get("url")}
    else:
        notes.append("no open-access PDF found")
    return out


def download(url: str, dest: Path, get: Fetch = fetch) -> Path:
    data = get(url, {"Accept": "application/pdf"})
    if not data.startswith(b"%PDF"):
        raise ScaleError(f"{url}: not a PDF (the open-access copy may need a browser); download it and give --pdf")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def _pages_from_text(text: str) -> list[dict]:
    """Pages of a plain-text source: split at "[page N]" headers (as written here) or form feeds; one page otherwise."""
    if re.search(r"^\[page \d+\]$", text, re.M):
        chunks = re.split(r"^\[page (\d+)\]\n?", text, flags=re.M)[1:]
        return [{"page": int(chunks[i]), "origin": "text", "text": chunks[i + 1].rstrip("\n")}
                for i in range(0, len(chunks), 2)]
    return [{"page": i, "origin": "text", "text": t} for i, t in enumerate(text.split("\f"), start=1)]


def _page_text(pages: list[dict]) -> str:
    return "".join(f"[page {p['page']}]\n{p['text'].rstrip()}\n\n" for p in pages)


def _brief(slug: str, graph: str, meta: dict, domain: str | None, version: str, spec: dict, text_file: str | None) -> str:
    labels = sorted(spec.get("nodes") or {})
    edges = sorted(spec.get("edges") or {})
    src = f"ex:pub/source/{slug}"
    return f"""# Curate {meta.get('title') or slug}

The source: {meta.get('title') or '(title not resolved)'}{f" ({meta['year']})" if meta.get('year') else ''}
{f"DOI {meta['doi']}, " if meta.get('doi') else ''}{meta.get('venue') or ''}. Rights: **{meta['rights_class']}**
({'; '.join(meta.get('licences') or []) or 'no licence found: treated as in copyright'}).

Fill `{graph}` under {spec["schema"]} {version}{f", following the {domain} checklist" if domain else ''}, as the curate-corpus
skill says (skills/curate-corpus/SKILL.md). In short:

1. Read the page texts{f" (`{text_file}`, each page headed `[page N]`)" if text_file else " (none extracted: give --pdf or --text, or read the source yourself)"}
   and record what the source reports: one record per entity, one link per relationship, each with its evidence
   (`source: {src}`, `locator: "p. N"` or a section, table or figure, `kind`, and a short verbatim `quote`).
2. Values are value objects in the source's unit, the printed text in `as_reported`; an absent value says why
   (`status: not_reported` with `missing_reason`). Never fill a gap with a typical value.
3. Use only what the schema declares: `scale graph describe <Label> --domain {domain or 'catalysis'}` (labels: {', '.join(labels[:40])}{', …' if len(labels) > 40 else ''};
   {len(edges)} edge types). What it cannot say goes in the record's `unmodeled` list or a gap, never an invented
   property.
4. Check as you go, and fix what it reports: `scale source check <this folder>` (`--derive-links` writes the
   REPORTED_IN links the evidence implies, one per record and cited source).
5. When it passes: `scale source finish <this folder>` (add `--public` for a copy to share, `--bundle` for a kg-bundle).

Ids start `ex:pub/{slug}/`; the source is `{src}`. Give the graph a short `title` (at most 40 characters; a platform
shows it as the graph's name), e.g. the subject and the year; the full reference is in `description`.
"""


def start(out: Path, doi: str | None = None, pdf: Path | None = None, text: Path | None = None,
          domain: str | None = "catalysis", version: str | None = None, email: str | None = None,
          contributor: str = "scale:org/scale-researchers", project: str | None = None, repo: Path | None = None,
          get: Fetch = fetch,
          today: _dt.date | None = None) -> dict:
    """Write the working folder for one source (see the module docstring) and return what was done."""
    if not doi and not pdf and not text:
        raise ScaleError("give --doi, --pdf or --text (or a DOI with either)")
    today = today or _dt.date.today()
    repo = Path(repo) if repo else find_repo_root()
    spec = pgraph.load_spec(pgraph.spec_for(repo, version, None, None))
    version = spec["version"]
    doi = normalize_doi(doi) if doi else None
    meta = resolve_doi(doi, email or os.environ.get(EMAIL_ENV), get) if doi else {"title": None, "notes": []}
    slug = slug_of(doi, Path(pdf) if pdf else Path(text) if text else None)
    out = Path(out)
    if (out / f"{slug}.graph.json").exists():
        raise ScaleError(f"{out}: already holds {slug}.graph.json; curate it there, or give another --out")
    out.mkdir(parents=True, exist_ok=True)
    (out / ".gitignore").write_text("pdfs/\nwork/\n*.evidence.*\n", encoding="utf-8")
    pdf_path = out / "pdfs" / f"{slug}.pdf"
    retrieved_from, text_version = None, None
    if pdf:
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        if Path(pdf).resolve() != pdf_path.resolve():
            shutil.copyfile(pdf, pdf_path)
        retrieved_from = str(Path(pdf).name)
    elif meta.get("open_access") and rights_class([meta["open_access"].get("licence") or ""]) != "in_copyright":
        download(meta["open_access"]["pdf"], pdf_path, get)
        retrieved_from = meta["open_access"]["pdf"]
        text_version = TEXT_VERSIONS.get(meta["open_access"].get("version") or "")
        meta["licences"] = [*meta.get("licences", []), meta["open_access"]["licence"]]
    elif meta.get("open_access"):
        meta["notes"].append(f"an open-access copy exists ({meta['open_access']['pdf']}) but states no open licence: "
                             "not downloaded; give the PDF with --pdf")
    pages: list[dict] = []
    read: dict = {}
    if text:
        pages = _pages_from_text(Path(text).read_text(encoding="utf-8", errors="ignore"))
        read = {"text_file": Path(text).name, "pages": len(pages)}
    elif pdf_path.exists():
        from . import sourcetext
        try:
            ex = sourcetext.extract_pages(pdf_path)
        except ImportError as exc:
            raise ScaleError(f"reading a PDF needs PyMuPDF: pip install \"scale-schema[pdf]\" ({exc}); or give --text") from None
        pages = ex["pages"]
        read = {"pdf_sha256": ex["pdf_sha256"], "pages": ex["page_count"], "ocr_engine": ex["ocr_engine"],
                "page_text_origins": {o: sum(p["origin"] == o for p in pages) for o in {p["origin"] for p in pages}}}
    text_rel = None
    if pages:
        text_rel = f"work/texts/{slug}.txt"
        (out / text_rel).parent.mkdir(parents=True, exist_ok=True)
        (out / text_rel).write_text(_page_text(pages), encoding="utf-8")
    licences = [x for x in meta.get("licences") or [] if x]
    meta["rights_class"] = rights_class(licences)
    sid = f"ex:pub/source/{slug}"
    source = {k: v for k, v in {
        "name": meta.get("title") or slug, "kind": meta.get("kind") or "article", "title": meta.get("title") or slug,
        "doi": doi, "url": meta.get("url"), "year": meta.get("year"), "venue": meta.get("venue"),
        "licence": "; ".join(licences) or None, "text_version": text_version,
        "text_sha256": read.get("pdf_sha256"), "retrieved_from": retrieved_from,
        "retrieved_on": today.isoformat() if retrieved_from else None, "origin": "curated"}.items() if v is not None}
    from .kgbundle import concise_title
    title = (meta.get("title") or slug)
    graph_title = concise_title(title)
    steward = _steward(repo, contributor)
    project = project or f"ex:pub/project/{slug}"
    doc = {"directed": True, "multigraph": True,
           "graph": {"schema": spec["schema"], "schema_version": version, "graph_id": f"ex:pub/graph/{slug}",
                     "title": graph_title,
                     "description": f"Curated from {title}" + (f" ({meta['year']})" if meta.get("year") else "")
                                    + (f", doi:{doi}" if doi else "") + ". One source; what it reports, with verbatim evidence.",
                     "data_status": "research_data", **({"follows_domains": [domain]} if domain else {}),
                     "stewardship": {"contributed_by": [contributor], "project": project, "access": "public"}},
           "nodes": [{"id": sid, "label": "Source", "props": source}, steward,
                     {"id": project, "label": "Project", "props": {"name": f"Study of {graph_title}", "origin": "curated",
                                                                   "note": f"Curating one source, {sid}."}}],
           "links": [{"id": f"{project}/participant/{contributor.rsplit('/', 1)[-1]}", "type": "PARTICIPATES_IN",
                      "source": contributor, "target": project, "props": {"origin": "curated", "role": "data_provider"}}]}
    graph_file = f"{slug}.graph.json"
    write_canonical(out / graph_file, doc)
    (out / "rights.yaml").write_text(dump_yaml({"sources": {sid: {
        "class": meta["rights_class"], "licence": "; ".join(licences) or "no licence found",
        "basis": f"licences recorded with the DOI ({doi})" if doi and licences else "no licence found: in copyright",
        **({"text_chars": sum(len(p["text"]) for p in pages)} if pages else {})}}}), encoding="utf-8")
    info = {"slug": slug, "source_id": sid, "doi": doi, "metadata": {k: v for k, v in meta.items() if k != "notes"},
            "read": read, "schema_version": version, "domain": domain, "notes": meta.get("notes", [])}
    write_canonical(out / "source.json", info)
    (out / "BRIEF.md").write_text(_brief(slug, graph_file, meta, domain, version, spec, text_rel), encoding="utf-8")
    return {"folder": str(out), "graph": graph_file, "source_id": sid, "rights_class": meta["rights_class"],
            "pdf": str(pdf_path.relative_to(out)) if pdf_path.exists() else None, "page_texts": text_rel,
            "pages": len(pages), "schema_version": version, "notes": info["notes"],
            "next": f"fill {graph_file} following BRIEF.md, then: scale source check {out}"}


def _steward(repo: Path | None, contributor: str) -> dict:
    """The curator's Institution record: from the stewardship registry when it lists the id, else a bare record."""
    from .util import load_yaml
    reg = load_yaml(Path(repo) / layout.STEWARDSHIP) if repo and (Path(repo) / layout.STEWARDSHIP).is_file() else {}
    entry = next((i for i in (reg or {}).get("institutions") or [] if i.get("id") == contributor), None)
    props = {k: v for k, v in (entry or {}).items() if k in ("name", "institution_kind", "note")}
    return {"id": contributor, "label": "Institution",
            "props": {"name": props.get("name") or contributor.rsplit("/", 1)[-1], **props, "origin": "curated"}}


def _folder(d: Path) -> tuple[Path, dict, Path]:
    d = Path(d)
    if not (d / "source.json").is_file():
        raise ScaleError(f"{d}: not a curation folder (no source.json; start one with scale source start)")
    info = load_doc(d / "source.json")
    return d, info, d / f"{info['slug']}.graph.json"


def check(d: Path, repo: Path | None = None, derive_links: bool = False) -> dict:
    """Validate the folder's graph with every quote checked against its page texts; conformance, gaps, the cap. With
    ``derive_links``, first rewrite its REPORTED_IN links as its evidence implies (one per record and cited source)."""
    d, info, gpath = _folder(d)
    doc = load_doc(gpath)
    if derive_links:
        doc["links"] = [e for e in doc["links"] if e.get("type") != "REPORTED_IN"] + pgraph.derive_reported_in(doc)
        write_canonical(gpath, doc)
    spec = pgraph.load_spec(pgraph.spec_for(repo, doc["graph"].get("schema_version"), None, doc))
    texts = rights.read_texts(d / "work/texts", None, doc) if (d / "work/texts").is_dir() else {}
    rep = pgraph.validate(doc, spec, texts or None)
    cap = rights.report(doc, rights.load_rights(d / "rights.yaml"))
    evidenced = sum(1 for r in doc["nodes"] + doc["links"] if (r.get("props") or {}).get("evidence"))
    gaps = [g for n in doc["nodes"] for g in (n.get("props") or {}).get("gaps") or []] if doc["nodes"] else []
    return {"graph": gpath.name, "ok": not rep.errors, "errors": rep.errors, "warnings": rep.warnings,
            "conformance": rep.conformance, "records": {"nodes": len(doc["nodes"]), "links": len(doc["links"]),
                                                        "with_evidence": evidenced},
            "quotes_checked_against_text": bool(texts), "gaps": len(gaps),
            "cap": {"ok": cap["ok"], "violations": cap["violations"], "class": info["metadata"].get("rights_class")}}


def finish(d: Path, public: bool = False, bundle: bool = False, title: str | None = None,
           repo: Path | None = None) -> dict:
    """The evidence index; with ``public`` a capped copy to share; with ``bundle`` a kg-bundle under bundle/."""
    from . import kgbundle
    from .passages import Index, evidence_items, graph_sha256
    d, info, gpath = _folder(d)
    res = check(d, repo)
    if not res["ok"]:
        raise ScaleError(f"{gpath.name} has {len(res['errors'])} errors: fix them first (scale source check {d})")
    doc = load_doc(gpath)
    out: dict = {"graph": gpath.name}
    Index.build(evidence_items(doc), graph_sha256=graph_sha256(doc)).save(gpath.with_name(f"{info['slug']}.evidence"))
    out["index"] = f"{info['slug']}.evidence.jsonl"
    if public:
        capped, _ = rights.cap(doc, rights.load_rights(d / "rights.yaml"))
        ppath = d / f"{info['slug']}.public.graph.json"
        write_canonical(ppath, capped)
        out["public"] = {"graph": ppath.name, "withheld": sum(1 for _, _, _, ev in rights.items(capped) if rights.withheld(ev))}
        doc = capped
    if bundle:
        spec = pgraph.load_spec(pgraph.spec_for(repo, doc["graph"].get("schema_version"), None, doc))
        bid = re.sub(r"[^a-z0-9]+", "-", info["slug"].lower()).strip("-")      # the format's bundle id: a lowercase slug
        bdir = d / "bundle" / f"{bid}_v1.0.0"
        if bdir.exists():
            shutil.rmtree(bdir)
        m = kgbundle.export(doc, spec, bdir, bid, "1.0.0", title=title)
        kgbundle.seal(bdir)
        out["bundle"] = {"folder": str(bdir.relative_to(d)), "title": m["topic"], "counts": m["counts"]}
    return out
