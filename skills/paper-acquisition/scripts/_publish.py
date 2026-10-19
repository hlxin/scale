"""Build publications/papers.db — the project's paper database (library module — not run directly).

A fresh, normalized SQLite snapshot of the working ledger, rebuilt atomically (tmp file -> rename) by every export, so
anyone can open it with any SQLite tool (DB Browser for SQLite, `sqlite3`, pandas, R) while scripts keep working.
Edits made to this file are overwritten by the next export: change data through the skill's scripts instead.

Tables
  papers             one row per paper: bibliographic data, abstract, Topic A/B/C, access, license, download state
  authors            one row per author (merged by ORCID / OpenAlex id, else by name)
  paper_authors      author order, institutions and countries per paper
  collections        the indexed topics (publications/<topic>/) with counts and dates
  paper_collections  paper <-> topic: relevance 0-5, scope decision, PDF path in that topic
  subjects           the topic vocabulary (Topic A/B/C and Related topics come from it)
  paper_subjects     paper <-> subject: kind 'main' (rank 1-3 = Topic A/B/C) or 'related'
  sources            search sources; paper_sources: where each paper was found
  identifiers        every identifier of a paper (DOIs incl. preprint/version aliases, PMCID, arXiv, patent no. ...)
  files              PDF and SI files per topic
  supplements        SI deposits the search found for a paper (Figshare, DataCite, ACS '.s001' DOIs ...), before or
                     without a download
  extractions        curation status per paper, topic and graph
  about              build time, counts, column descriptions and example queries
  papers_fts         full-text index over title, abstract and keywords (when the SQLite build has FTS5)
Views: v_papers (papers + collections + authors as text), v_collection_papers (one row per paper and topic).
"""
import json
import os
import re
import sqlite3

from _common import SOURCE_LABEL, export_abstract, json_read, log, now_iso

DDL = """
CREATE TABLE papers (
  id INTEGER PRIMARY KEY, doi TEXT, identifier TEXT, title TEXT, authors TEXT, year INTEGER, venue TEXT,
  publisher TEXT, doc_type TEXT, url TEXT, abstract TEXT, abstract_source TEXT, keywords TEXT,
  topic_a TEXT, topic_b TEXT, topic_c TEXT, related_topics TEXT,
  access_type TEXT, license TEXT, license_url TEXT, license_source TEXT, oa_status TEXT, version TEXT,
  citations INTEGER, citation_percentile REAL, is_preprint INTEGER, is_retracted INTEGER, is_non_paper INTEGER,
  databases TEXT, downloaded TEXT, download_source TEXT, download_url TEXT, download_date TEXT, pages INTEGER,
  sha1 TEXT, si TEXT, notes TEXT, date_added TEXT, last_checked TEXT
);
CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT NOT NULL, orcid TEXT, openalex_id TEXT);
CREATE TABLE paper_authors (paper_id INTEGER, author_id INTEGER, position INTEGER, institutions TEXT, countries TEXT,
  PRIMARY KEY (paper_id, position));
CREATE TABLE collections (slug TEXT PRIMARY KEY, topic TEXT, created_at TEXT, last_index TEXT, last_update TEXT,
  papers INTEGER, in_scope INTEGER, out_of_scope INTEGER, downloaded INTEGER, folder TEXT);
CREATE TABLE paper_collections (paper_id INTEGER, collection TEXT, relevance INTEGER, relevance_note TEXT,
  relevance_method TEXT, in_scope INTEGER, pdf_path TEXT, si_paths TEXT, date_added TEXT,
  PRIMARY KEY (paper_id, collection));
CREATE TABLE subjects (term TEXT PRIMARY KEY, label TEXT, name TEXT, facet TEXT, related TEXT);
CREATE TABLE paper_subjects (paper_id INTEGER, term TEXT, label TEXT, kind TEXT, rank INTEGER, method TEXT, score REAL,
  PRIMARY KEY (paper_id, term));
CREATE TABLE sources (name TEXT PRIMARY KEY, label TEXT);
CREATE TABLE paper_sources (paper_id INTEGER, source TEXT, PRIMARY KEY (paper_id, source));
CREATE TABLE identifiers (paper_id INTEGER, scheme TEXT, value TEXT);
CREATE TABLE files (paper_id INTEGER, collection TEXT, kind TEXT, path TEXT);
CREATE TABLE supplements (paper_id INTEGER, doi TEXT, url TEXT, title TEXT, source TEXT);
CREATE TABLE extractions (paper_id INTEGER, collection TEXT, kg TEXT, status TEXT, schema_version TEXT, nodes INTEGER,
  edges INTEGER, date TEXT, note TEXT);
CREATE TABLE about (name TEXT PRIMARY KEY, value TEXT);
"""
POST = """
CREATE INDEX ix_p_year ON papers(year);
CREATE INDEX ix_p_venue ON papers(venue COLLATE NOCASE);
CREATE INDEX ix_p_doctype ON papers(doc_type);
CREATE INDEX ix_p_access ON papers(access_type);
CREATE INDEX ix_p_topica ON papers(topic_a);
CREATE INDEX ix_p_doi ON papers(doi);
CREATE INDEX ix_pc_coll ON paper_collections(collection);
CREATE INDEX ix_ps_term ON paper_subjects(term);
CREATE INDEX ix_ps_label ON paper_subjects(label);
CREATE INDEX ix_pa_author ON paper_authors(author_id);
CREATE INDEX ix_a_name ON authors(name COLLATE NOCASE);
CREATE INDEX ix_a_orcid ON authors(orcid);
CREATE INDEX ix_id_value ON identifiers(value);
CREATE INDEX ix_ps_src ON paper_sources(source);
CREATE INDEX ix_sup_paper ON supplements(paper_id);
CREATE VIEW v_papers AS
  SELECT p.*, (SELECT group_concat(collection, '; ') FROM paper_collections c WHERE c.paper_id = p.id) AS collections
  FROM papers p;
CREATE VIEW v_collection_papers AS
  SELECT c.collection, c.relevance, c.relevance_note, c.in_scope, c.pdf_path, c.date_added AS added_to_collection, p.*
  FROM paper_collections c JOIN papers p ON p.id = c.paper_id;
"""
COLUMN_HELP = {
    "papers.identifier": "DOI, else the best other identifier (patent number, arXiv:..., OSTI:...)",
    "papers.topic_a": "the paper's main topic (Topic A); topic_b / topic_c are the next two — labels from `subjects`",
    "papers.related_topics": "related topics ('; '-separated labels): other topics the paper touches + vocabulary neighbours",
    "papers.access_type": "OA (open license allowing derivatives) / OA+ND (no derivatives) / Free-to-read (no reuse "
                          "license) / Paywalled (subscription)",
    "papers.license": "exact license with version when stated (CC BY 4.0, CC BY-NC-ND 4.0, Elsevier user license ...)",
    "papers.license_source": "where the license came from (PDF printed statement wins over metadata)",
    "papers.version": "Published version / Accepted manuscript / Preprint (of the downloaded or best open copy)",
    "papers.downloaded": "Yes / No / n/a (datasets and software are indexed, never downloaded)",
    "papers.abstract_source": "metadata source of the abstract, or 'pdf' when read from the downloaded paper",
    "paper_collections.relevance": "0-5 relevance to that collection's topic (blank = not screened); in_scope 1/0",
    "paper_subjects.kind": "'main' (rank 1-3 = Topic A/B/C) or 'related'",
    "identifiers.scheme": "doi (every DOI incl. preprint/version aliases), patent (every number of the same invention: "
                          "WO, EP, US ... merged into one row), pmid, pmcid, arxiv, osti, supplement_to ...",
    "supplements": "SI deposits found by the search for a paper (doi, url, title, source); files holds the SI actually "
                   "downloaded",
}
EXAMPLES = [
    "-- papers of a topic, newest first\nSELECT id, title, year, venue FROM v_collection_papers WHERE collection = 'co2rr' "
    "AND in_scope = 1 ORDER BY year DESC;",
    "-- by venue and year range\nSELECT title, year FROM papers WHERE venue LIKE '%ACS Catal%' AND year BETWEEN 2020 AND 2026;",
    "-- by subject (Topic A/B/C or related)\nSELECT p.title, s.kind FROM papers p JOIN paper_subjects s ON s.paper_id = p.id "
    "WHERE s.label = 'Single-atom catalysts';",
    "-- open-access PDFs on disk\nSELECT p.title, f.path FROM papers p JOIN files f ON f.paper_id = p.id WHERE f.kind = 'pdf' "
    "AND p.access_type IN ('OA', 'OA+ND');",
    "-- full text search (title, abstract, keywords)\nSELECT p.id, p.title FROM papers_fts JOIN papers p ON p.id = papers_fts.rowid "
    "WHERE papers_fts MATCH 'copper AND ethylene';",
    "-- papers by an author (ORCID or name)\nSELECT p.title FROM papers p JOIN paper_authors pa ON pa.paper_id = p.id "
    "JOIN authors a ON a.id = pa.author_id WHERE a.name LIKE '%Sargent%';",
    "-- SI deposits known for papers not downloaded yet\nSELECT p.title, s.doi, s.url FROM supplements s JOIN papers p "
    "ON p.id = s.paper_id WHERE p.downloaded = 'No';",
    "-- every number of one patented invention\nSELECT p.title, i.value FROM identifiers i JOIN papers p ON p.id = i.paper_id "
    "WHERE i.scheme = 'patent' AND p.title LIKE '%co-catalyzed%';",
]


def _fts_ok(con):
    try:
        con.execute("CREATE VIRTUAL TABLE temp._probe USING fts5(x)")
        con.execute("DROP TABLE temp._probe")
        return True
    except sqlite3.OperationalError:
        return False


def run_dates(st):
    """(last full index, last update) finish dates from a topic's state.json search runs."""
    runs = st.get("search_runs") or {}
    full = (runs.get("full") or {}).get("finished_at")
    upd = sorted((v.get("finished_at") or "") for k, v in runs.items() if k.startswith(("since-", "citing")))
    return full, (upd[-1] or None) if upd else None


def _norm_name(n):
    return re.sub(r"[^a-z]", "", (n or "").lower())


def build_published_db(led, vocab):
    import _ledger as L
    proj = led.proj
    path = proj.db
    tmp = proj.tmp / "papers.db.tmp"
    for f in (tmp, proj.tmp / "papers.db.tmp-journal"):
        if f.exists():
            f.unlink()
    con = sqlite3.connect(str(tmp))
    con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;" + DDL)
    ext = led._extraction_map()
    full_ext = {(r["paper_id"], r["topic"], r["kg"]): dict(r) for r in led.q("SELECT * FROM extractions")}
    authors_ids, next_author = {}, 1
    n_papers, sources_seen, slugs, last_id = 0, set(), set(), 0
    # papers stream in id order, CHUNK at a time, with their subjects/topics/aliases/SI deposits read for the same id
    # range — a ledger of millions of papers never sits in memory
    CHUNK = 20000
    while True:
        chunk = [led.row(r) for r in led.q("SELECT * FROM papers WHERE id > ? ORDER BY id LIMIT ?", (last_id, CHUNK))]
        if not chunk:
            break
        lo, hi = chunk[0]["id"], chunk[-1]["id"]
        last_id = hi
        subj, meta, topics, alias, si_n, sup = {}, {}, {}, {}, {}, {}
        for r in led.q("SELECT paper_id, term, kind, rank, method, score FROM paper_subjects WHERE paper_id BETWEEN ? AND ? "
                       "ORDER BY paper_id, kind DESC, rank", (lo, hi)):
            d = subj.setdefault(r[0], {"main": [], "related": []})
            d["main" if r[2] == "main" else "related"].append(r[1])
            meta[(r[0], r[1])] = (r[4], r[5])
        for r in led.q("SELECT * FROM paper_topics WHERE paper_id BETWEEN ? AND ? ORDER BY topic", (lo, hi)):
            topics.setdefault(r["paper_id"], []).append(dict(r))
        for r in led.q("SELECT doi, paper_id FROM dois WHERE paper_id BETWEEN ? AND ?", (lo, hi)):
            alias.setdefault(r[1], []).append(r[0])
        for r in led.q("SELECT d.paper_id, l.si_doi, l.url, l.title, l.source FROM si_links l JOIN dois d "
                       "ON d.doi = l.parent_doi WHERE d.paper_id BETWEEN ? AND ?", (lo, hi)):
            sup.setdefault(r[0], {})[r[1]] = (r[0], r[1], r[2], r[3], r[4])
        p_rows, pa_rows, pc_rows, ps_rows, src_rows, id_rows, file_rows, ex_rows, sup_rows = [], [], [], [], [], [], [], [], []
        for p in chunk:
            ts = topics.get(p["id"])
            if not ts:
                continue
            n_papers += 1
            al = alias.get(p["id"], [])
            fam = sorted(a[len("patent:"):] for a in al if a.startswith("patent:") and len(a) > len("patent:"))
            p["_si_links"], p["_family"] = len(sup.get(p["id"], {})), fam
            s = subj.get(p["id"]) or {"main": [], "related": []}
            main = [vocab.label(t) for t in s["main"]] + [None, None, None]
            lic, lic_url, lic_src = L.license_cells(p)
            ver = p.get("version") if p.get("downloaded") else next(
                (v.get("version") for v in p.get("versions") or [] if v.get("access") == p.get("access_type") and v.get("version")), None)
            p_rows.append((p["id"], p.get("doi"), L.identifier(p), p.get("title"), L.fmt_authors(p.get("authors"), cap=0),
                           p.get("year"), p.get("journal"), p.get("publisher"), p.get("doc_type"), L.url_of(p),
                           export_abstract(p.get("abstract") or "") or None, p.get("abstract_source"),
                           "; ".join(p.get("keywords") or []),
                           main[0], main[1], main[2], "; ".join(vocab.label(t) for t in s["related"]),
                           p.get("access_type"), lic or None, lic_url or None, lic_src or None, p.get("oa_status"),
                           L.VERSION_LABEL.get(ver or "", ver), p.get("cited_by"), p.get("percentile"),
                           p.get("is_preprint"), p.get("retracted"), p.get("is_erratum"),
                           "; ".join(SOURCE_LABEL.get(d, d) for d in p.get("databases") or []), L.downloaded_cell(p),
                           p.get("download_source"), p.get("download_url"), p.get("download_date"), p.get("page_count"),
                           p.get("sha1"), L.si_cell(p) or None, L.notes_for(p) or None, p.get("date_added"),
                           p.get("last_checked")))
            # authors
            detail = p.get("authors_detail") or []
            names = p.get("authors") or []
            if not detail:
                detail = [{"name": n} for n in names]
            for pos, a in enumerate(detail, 1):
                name = (a.get("name") or "").strip()
                if not name:
                    continue
                k = ("orcid", a["orcid"]) if a.get("orcid") else (("oa", a["openalex"]) if a.get("openalex") else ("name", _norm_name(name)))
                aid = authors_ids.get(k)
                if aid is None:
                    aid = authors_ids[k] = next_author
                    next_author += 1
                    con.execute("INSERT INTO authors VALUES (?,?,?,?)", (aid, name, a.get("orcid"), a.get("openalex")))
                pa_rows.append((p["id"], aid, pos, "; ".join(a.get("institutions") or []) or None,
                                "; ".join(a.get("countries") or []) or None))
            for t in ts:
                slugs.add(t["topic"])
                pc_rows.append((p["id"], t["topic"], t.get("relevance"), t.get("relevance_note"), t.get("relevance_method"),
                                t.get("in_scope"), t.get("path"), t.get("si_paths"), t.get("date_added")))
                if t.get("path"):
                    file_rows.append((p["id"], t["topic"], "pdf", t["path"]))
                for sp in json.loads(t.get("si_paths") or "[]"):
                    file_rows.append((p["id"], t["topic"], "si", sp))
            for kind in ("main", "related"):
                for i, term in enumerate(s[kind], 1):
                    m = meta.get((p["id"], term)) or (None, None)
                    ps_rows.append((p["id"], term, vocab.label(term), kind, i, m[0], m[1]))
            for d in p.get("databases") or []:
                src_rows.append((p["id"], d))
                sources_seen.add(d)
            for d in sorted(set([a for a in al if not a.startswith(("patent:", "nodoi:"))] + ([p["doi"]] if p.get("doi") else []))):
                id_rows.append((p["id"], "doi", d))
            for num in fam:
                id_rows.append((p["id"], "patent", num))
            for k, v in (p.get("external_ids") or {}).items():
                if v and not isinstance(v, (dict, list)):
                    id_rows.append((p["id"], k, str(v)))
            for e in ext.get(p["id"], []):
                f_ = full_ext.get((p["id"], e["topic"], e["kg"])) or {}
                ex_rows.append((p["id"], e["topic"], e["kg"], e["status"], f_.get("schema_version"), f_.get("nodes"),
                                f_.get("edges"), e.get("date"), e.get("note")))
            sup_rows += list(sup.get(p["id"], {}).values())
        con.executemany(f"INSERT INTO papers VALUES ({','.join('?' * 39)})", p_rows)
        con.executemany("INSERT OR IGNORE INTO paper_authors VALUES (?,?,?,?,?)", pa_rows)
        con.executemany("INSERT INTO paper_collections VALUES (?,?,?,?,?,?,?,?,?)", pc_rows)
        con.executemany("INSERT OR IGNORE INTO paper_subjects VALUES (?,?,?,?,?,?,?)", ps_rows)
        con.executemany("INSERT OR IGNORE INTO paper_sources VALUES (?,?)", src_rows)
        con.executemany("INSERT INTO identifiers VALUES (?,?,?)", id_rows)
        con.executemany("INSERT INTO files VALUES (?,?,?,?)", file_rows)
        con.executemany("INSERT INTO extractions VALUES (?,?,?,?,?,?,?,?,?)", ex_rows)
        con.executemany("INSERT INTO supplements VALUES (?,?,?,?,?)", sup_rows)
    con.executemany("INSERT INTO sources VALUES (?,?)", [(k, SOURCE_LABEL.get(k, k)) for k in sorted(sources_seen)])
    con.executemany("INSERT INTO subjects VALUES (?,?,?,?,?)",
                    [(t, vocab.terms[t]["label"], vocab.terms[t].get("name"), vocab.terms[t].get("facet"),
                      "; ".join(vocab.label(x) for x in vocab.terms[t].get("related") or [])) for t in vocab.order])
    # collections
    for slug in sorted(slugs):
        cfg = json_read(proj.topic_dir(slug) / "config.json", {}) or {}
        st = json_read(proj.topic_dir(slug) / "state.json", {}) or {}
        c = led.q("SELECT COUNT(*), SUM(CASE WHEN t.in_scope=1 AND p.is_erratum=0 AND COALESCE(p.retracted,0)=0 THEN 1 ELSE 0 END), "
                  "SUM(CASE WHEN t.in_scope=0 AND p.is_erratum=0 THEN 1 ELSE 0 END), "
                  "SUM(CASE WHEN t.path IS NOT NULL THEN 1 ELSE 0 END) FROM paper_topics t JOIN papers p ON p.id=t.paper_id "
                  "WHERE t.topic=?", (slug,))[0]
        li, lu = run_dates(st)
        con.execute("INSERT INTO collections VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (slug, cfg.get("topic"), cfg.get("created_at"), li, lu, c[0], c[1] or 0, c[2] or 0, c[3] or 0,
                     proj.rel(proj.pub / slug)))
    con.executescript(POST)
    if _fts_ok(con):
        con.executescript("CREATE VIRTUAL TABLE papers_fts USING fts5(title, abstract, keywords, content='papers', "
                          "content_rowid='id'); INSERT INTO papers_fts(rowid, title, abstract, keywords) "
                          "SELECT id, title, abstract, keywords FROM papers;")
    about = {"built_at": now_iso(), "papers": str(n_papers), "authors": str(next_author - 1),
             "source_of_truth": ".scripts/ledger.sqlite (this file is a snapshot; edits here are overwritten)",
             "vocabulary": vocab.name, "examples": "\n\n".join(EXAMPLES)}
    about.update({f"column:{k}": v for k, v in COLUMN_HELP.items()})
    con.executemany("INSERT INTO about VALUES (?,?)", sorted(about.items()))
    con.commit()
    con.execute("VACUUM")
    con.close()
    os.replace(tmp, path)
    return n_papers
