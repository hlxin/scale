"""publications/papers.db — the project's paper database, kept up to date in place (library module — not run directly).

The database evolves; it is not rebuilt. The working ledger (.scripts/ledger.sqlite) marks every paper a step touches
(triggers fill its publish_queue), and sync_published_db() rewrites only those papers' rows here — the paper, its
authors, topics, identifiers, files, SI and curation results, and its full-text entry — records what changed
(`changes`) and the step that changed it (`runs`), and keeps the working state the ledger needs (`_paper_state`, and
the topics' settings, queries and decisions in `project_files`). So the ledger can be rebuilt from this file alone
(adopt_ledger: anyone with the skill and papers.db can carry on), and saved filters (`filters`, `filter_members`;
_filters.py) are refreshed when papers' text, topics or retractions change. Open it with any SQLite tool (DB Browser
for SQLite, `sqlite3`, pandas, R) while scripts keep working; change data through the skill's scripts, since a sync
rewrites the rows of the papers it touches. A full rebuild (export.py --rebuild) is only a fallback, and it keeps the
history.

Tables
  papers             one row per paper: bibliographic data, abstract, Topic A/B/C, access, license, download state
  authors            one row per author (merged by ORCID / OpenAlex id, else by name; ids stay the same across updates)
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
  about              creation and update times, counts, column descriptions and example queries
  papers_fts         full-text index over title, abstract and keywords (when the SQLite build has FTS5)
  runs               every step that changed the database: when, which step and topics, papers added/updated/removed
  changes            what changed per paper and run: added, removed (merged into / SI of), access, license, version,
                     retraction, download, SI, Topic A, DOI, a topic's scope
  filters            saved filters (a definition in JSON) and filter_members, their papers with a label and level
  _paper_state, project_files, author_keys, _si_links_unattached   the working state behind the tables above
                     (see adopt_ledger)
Views: v_papers (papers + collections + authors as text), v_collection_papers (one row per paper and topic).
"""
import hashlib
import json
import os
import re
import sqlite3
import sys
import uuid
import zlib
from pathlib import Path

from _common import (PREPRINT_HOST_RX, SOURCE_LABEL, export_abstract, file_lock, json_read, log, now_iso,
                     preprint_links)

FORMAT = "evolving-2"          # evolving-2: papers.preprint_url (columns are only ever added, in place)
DDL = """
CREATE TABLE papers (
  id INTEGER PRIMARY KEY, doi TEXT, identifier TEXT, title TEXT, authors TEXT, year INTEGER, venue TEXT,
  publisher TEXT, doc_type TEXT, url TEXT, abstract TEXT, abstract_source TEXT, keywords TEXT,
  topic_a TEXT, topic_b TEXT, topic_c TEXT, related_topics TEXT,
  access_type TEXT, license TEXT, license_url TEXT, license_source TEXT, oa_status TEXT, version TEXT,
  citations INTEGER, citation_percentile REAL, is_preprint INTEGER, is_retracted INTEGER, is_non_paper INTEGER,
  databases TEXT, downloaded TEXT, download_source TEXT, download_url TEXT, download_date TEXT, pages INTEGER,
  sha1 TEXT, si TEXT, notes TEXT, date_added TEXT, last_checked TEXT, preprint_url TEXT
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
# history, working state and saved filters (added in place to an older database)
STATE_DDL = """
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, at TEXT, step TEXT, topics TEXT, added INTEGER,
  updated INTEGER, removed INTEGER, papers INTEGER, note TEXT, uid TEXT);
CREATE TABLE IF NOT EXISTS changes (run_id INTEGER, paper_id INTEGER, change TEXT, field TEXT, old TEXT, new TEXT);
CREATE TABLE IF NOT EXISTS author_keys (kind TEXT, value TEXT, author_id INTEGER, PRIMARY KEY (kind, value));
CREATE TABLE IF NOT EXISTS _paper_state (paper_id INTEGER PRIMARY KEY, state BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS project_files (path TEXT PRIMARY KEY, content TEXT, sha256 TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS _si_links_unattached (parent_doi TEXT, si_doi TEXT, url TEXT, title TEXT, source TEXT,
  date_added TEXT, PRIMARY KEY (parent_doi, si_doi));
CREATE TABLE IF NOT EXISTS filters (name TEXT PRIMARY KEY, description TEXT, definition TEXT NOT NULL,
  created_at TEXT, updated_at TEXT, refreshed_at TEXT, members INTEGER);
CREATE TABLE IF NOT EXISTS filter_members (filter TEXT, paper_id INTEGER, label TEXT, level TEXT,
  PRIMARY KEY (filter, paper_id, label));
"""
STATE_INDEXES = """
CREATE INDEX IF NOT EXISTS ix_fm_paper ON filter_members(paper_id);
CREATE INDEX IF NOT EXISTS ix_id_paper ON identifiers(paper_id);
CREATE INDEX IF NOT EXISTS ix_files_paper ON files(paper_id);
CREATE INDEX IF NOT EXISTS ix_ext_paper ON extractions(paper_id);
CREATE INDEX IF NOT EXISTS ix_changes_paper ON changes(paper_id);
CREATE INDEX IF NOT EXISTS ix_changes_run ON changes(run_id);
"""
FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS papers_fts_ai AFTER INSERT ON papers BEGIN
  INSERT INTO papers_fts(rowid, title, abstract, keywords) VALUES (new.id, new.title, new.abstract, new.keywords); END;
CREATE TRIGGER IF NOT EXISTS papers_fts_ad AFTER DELETE ON papers BEGIN
  INSERT INTO papers_fts(papers_fts, rowid, title, abstract, keywords)
  VALUES ('delete', old.id, old.title, old.abstract, old.keywords); END;
CREATE TRIGGER IF NOT EXISTS papers_fts_au AFTER UPDATE ON papers BEGIN
  INSERT INTO papers_fts(papers_fts, rowid, title, abstract, keywords)
  VALUES ('delete', old.id, old.title, old.abstract, old.keywords);
  INSERT INTO papers_fts(rowid, title, abstract, keywords) VALUES (new.id, new.title, new.abstract, new.keywords); END;
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
    "papers.url": "the paper's link: its published (journal) version when there is one, else the preprint or landing page",
    "papers.preprint_url": "links of the paper's preprint versions ('; '-separated): the preprint DOIs merged into it "
                           "(ChemRxiv, SSRN, Research Square, bioRxiv ...) and its arXiv record, else copies on "
                           "preprint servers; for a preprint, its own link",
    "papers.is_retracted": "1 = the paper is retracted (OpenAlex / Retraction Watch, Crossref); a retraction notice "
                           "is a non-paper (is_non_paper = 1) whose identifiers name the paper it retracts "
                           "(scheme retraction_of); the retracted paper names its notice (scheme retraction_notice)",
    "papers.downloaded": "Yes / No / n/a (datasets and software are indexed, never downloaded)",
    "papers.abstract_source": "metadata source of the abstract, or 'pdf' when read from the downloaded paper",
    "paper_collections.relevance": "0-5 relevance to that collection's topic (blank = not screened); in_scope 1/0",
    "paper_subjects.kind": "'main' (rank 1-3 = Topic A/B/C) or 'related'",
    "identifiers.scheme": "doi (every DOI incl. preprint/version aliases), patent (every number of the same invention: "
                          "WO, EP, US ... merged into one row), pmid, pmcid, arxiv, osti, supplement_to, "
                          "retraction_notice / retraction_of (a retracted paper and its notice) ...",
    "supplements": "SI deposits found by the search for a paper (doi, url, title, source); files holds the SI actually "
                   "downloaded",
    "runs": "one row per step that changed the database (at, step, topics, papers added / updated / removed)",
    "changes": "per paper and run: change = added | removed | changed | collection; field, old and new value",
    "filters": "saved filters: name, definition (JSON), last refresh, members; filter_members lists their papers",
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
    "-- what is new since a date\nSELECT p.title, r.at, r.step FROM changes c JOIN runs r ON r.id = c.run_id JOIN papers p "
    "ON p.id = c.paper_id WHERE c.change = 'added' AND r.at >= '2026-06-01';",
    "-- papers that became open access\nSELECT p.title, c.old, c.new, r.at FROM changes c JOIN runs r ON r.id = c.run_id "
    "JOIN papers p ON p.id = c.paper_id WHERE c.field = 'access_type' AND c.new IN ('OA', 'OA+ND');",
    "-- a saved filter's papers\nSELECT p.title, m.label, m.level FROM filter_members m JOIN papers p ON p.id = m.paper_id "
    "WHERE m.filter = 'co2-reduction-electricity';",
    "-- retracted papers, with their retraction notice\nSELECT p.title, p.doi, i.value AS notice FROM papers p LEFT JOIN "
    "identifiers i ON i.paper_id = p.id AND i.scheme = 'retraction_notice' WHERE p.is_retracted = 1;",
    "-- journal articles that also have a preprint\nSELECT title, url, preprint_url FROM papers WHERE preprint_url IS NOT "
    "NULL AND is_preprint = 0;",
    "-- a patent by its number\nSELECT p.title, p.year, p.url FROM identifiers i JOIN papers p ON p.id = i.paper_id "
    "WHERE i.scheme = 'patent' AND i.value LIKE 'US-1681751%';",
]
# the papers table's columns, as the ledger's papers columns they copy unchanged (the rest is in _paper_state)
COPIED = {"id": "id", "doi": "doi", "title": "title", "year": "year", "venue": "journal", "publisher": "publisher",
          "doc_type": "doc_type", "abstract_source": "abstract_source", "access_type": "access_type",
          "oa_status": "oa_status", "citations": "cited_by", "citation_percentile": "percentile",
          "is_preprint": "is_preprint", "is_retracted": "retracted", "is_non_paper": "is_erratum",
          "download_source": "download_source", "download_url": "download_url", "download_date": "download_date",
          "pages": "page_count", "sha1": "sha1", "date_added": "date_added", "last_checked": "last_checked"}
STATE_SKIP = set(COPIED.values()) | {"abstract"}
TRACKED = ("doi", "access_type", "license", "version", "is_preprint", "is_retracted", "downloaded", "si", "topic_a",
           "preprint_url")
ADDED_COLUMNS = {"preprint_url": "TEXT"}    # papers columns added after a database's first build (filled in place)
TEXTUAL = ("title", "abstract", "keywords", "topic_a", "topic_b", "topic_c", "related_topics", "is_retracted",
           "is_non_paper")
BY_PAPER = ("paper_authors", "paper_collections", "paper_subjects", "paper_sources", "identifiers", "files",
            "supplements", "extractions", "_paper_state")
PROJECT_FILES = ("config.json", "queries.json", "state.json", "criteria.md", "keywords.json")
CHUNK = 20000


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


def pack_state(state):
    """A paper's working state as stored: compact JSON, compressed (empty fields left out: the ledger's defaults)."""
    keep = {k: v for k, v in state.items() if v is not None and v != [] and v != {}}
    return zlib.compress(json.dumps(keep, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"), 6)


def unpack_state(blob):
    if isinstance(blob, (bytes, memoryview)):
        return json.loads(zlib.decompress(bytes(blob)).decode("utf-8"))
    return json.loads(blob)


def _tables(con):
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}


def has_state(path):
    """True when the database at `path` is an evolving one (it carries its history and working state)."""
    if not Path(path).is_file():
        return False
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return {"runs", "_paper_state", "project_files"} <= _tables(con)
        finally:
            con.close()
    except sqlite3.Error:
        return False


def ensure_state(con):
    """The history and state tables, added in place to an older evolving database (columns are only ever added)."""
    con.executescript(STATE_DDL)
    if "uid" not in {r[1] for r in con.execute("PRAGMA table_info(runs)")}:
        con.execute("ALTER TABLE runs ADD COLUMN uid TEXT")      # a run's identity across copies (merge_db.py)
    con.executescript(STATE_INDEXES)


def _add_columns(con, led):
    """Columns the papers table gained after this database was first built: added in place (never dropped or
    renamed) and filled from the ledger for every paper, as a run of its own."""
    missing = [c for c in ADDED_COLUMNS if c not in {r[1] for r in con.execute("PRAGMA table_info(papers)")}]
    if not missing:
        return
    with con:
        for c in missing:
            con.execute(f"ALTER TABLE papers ADD COLUMN {c} {ADDED_COLUMNS[c]}")
    n, last, pre = 0, 0, led._preprint_alias_map()
    hint = re.compile(r'"arxiv"|osf\.io|' + PREPRINT_HOST_RX.pattern.replace("^", ""), re.I)
    while "preprint_url" in missing:
        rows = led.q("SELECT id, doi, link, is_preprint, external_ids, versions FROM papers WHERE id > ? ORDER BY id "
                     "LIMIT ?", (last, CHUNK))
        if not rows:
            break
        last, ups = rows[-1][0], []
        for pid, doi, link, isp, ext, ver in rows:
            if not (isp or pid in pre or hint.search(ext or "") or hint.search(ver or "")):
                continue                     # most papers: no preprint anywhere in their record
            links = preprint_links({"doi": doi, "link": link, "is_preprint": isp, "external_ids": json.loads(ext or "{}"),
                                    "versions": json.loads(ver or "[]")}, pre.get(pid, []))
            if links:
                ups.append(("; ".join(links), pid))
        with con:
            con.executemany("UPDATE papers SET preprint_url=? WHERE id=?", ups)
        n += len(ups)
    with con:
        run = new_run(con, _step_name()[0], "", f"papers gained {', '.join(missing)}; {n} papers have a preprint link")
        con.execute("UPDATE runs SET added=0, updated=?, removed=0, papers=(SELECT COUNT(*) FROM papers) WHERE id=?",
                    (n, run))
    log(f"papers.db: column {', '.join(missing)} added; {n} papers have a preprint link")


def new_run(con, step, topics, note):
    return con.execute("INSERT INTO runs(at, step, topics, note, uid) VALUES (?,?,?,?,?)",
                       (now_iso(), step, topics, note, uuid.uuid4().hex)).lastrowid


def _step_name(topics=None):
    step = Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else "python"
    return step, ", ".join(topics or [])


# ------------------------------------------------------------------ rows of one paper
def _side(led, where, args):
    """Everything a paper's rows need besides its ledger row, for the papers `where` selects (BETWEEN or IN)."""
    subj, meta, topics, alias, sup, links, ext = {}, {}, {}, {}, {}, {}, {}
    for r in led.q(f"SELECT paper_id, term, kind, rank, method, score FROM paper_subjects WHERE paper_id {where} "
                   "ORDER BY paper_id, kind DESC, rank", args):
        d = subj.setdefault(r[0], {"main": [], "related": []})
        d["main" if r[2] == "main" else "related"].append(r[1])
        meta[(r[0], r[1])] = (r[4], r[5])
    for r in led.q(f"SELECT * FROM paper_topics WHERE paper_id {where} ORDER BY topic", args):
        topics.setdefault(r["paper_id"], []).append(dict(r))
    for r in led.q(f"SELECT doi, paper_id FROM dois WHERE paper_id {where}", args):
        alias.setdefault(r[1], []).append(r[0])
    for r in led.q("SELECT d.paper_id, l.parent_doi, l.si_doi, l.url, l.title, l.source, l.date_added FROM si_links l "
                   f"JOIN dois d ON d.doi = l.parent_doi WHERE d.paper_id {where}", args):
        sup.setdefault(r[0], {})[r[2]] = (r[0], r[2], r[3], r[4], r[5])
        links.setdefault(r[0], []).append({"parent_doi": r[1], "si_doi": r[2], "url": r[3], "title": r[4],
                                           "source": r[5], "date_added": r[6]})
    for r in led.q(f"SELECT * FROM extractions WHERE paper_id {where}", args):
        ext.setdefault(r["paper_id"], []).append(dict(r))
    return {"subj": subj, "meta": meta, "topics": topics, "alias": alias, "sup": sup, "links": links, "ext": ext}


class _Authors:
    """Author ids that stay the same across updates: one id per ORCID, else OpenAlex id, else normalized name."""

    def __init__(self, con, cache=True):
        self.con, self.cache = con, {} if cache else None
        self.next = (con.execute("SELECT MAX(id) FROM authors").fetchone()[0] or 0) + 1

    def id_for(self, a, name):
        k = ("orcid", a["orcid"]) if a.get("orcid") else (("oa", a["openalex"]) if a.get("openalex") else
                                                          ("name", _norm_name(name)))
        if self.cache is not None and k in self.cache:
            return self.cache[k]
        r = self.con.execute("SELECT author_id FROM author_keys WHERE kind=? AND value=?", k).fetchone()
        if r:
            aid = r[0]
        else:
            aid, self.next = self.next, self.next + 1
            self.con.execute("INSERT INTO authors VALUES (?,?,?,?)", (aid, name, a.get("orcid"), a.get("openalex")))
            self.con.execute("INSERT INTO author_keys VALUES (?,?,?)", (*k, aid))
        if self.cache is not None:
            self.cache[k] = aid
        return aid


def _rows(p, side, vocab, authors, L):
    """The rows of one paper in every table, or None when the paper is in no topic (it is not published)."""
    pid = p["id"]
    ts = side["topics"].get(pid)
    if not ts:
        return None
    al = side["alias"].get(pid, [])
    sup = side["sup"].get(pid, {})
    fam = sorted(a[len("patent:"):] for a in al if a.startswith("patent:") and len(a) > len("patent:"))
    p["_si_links"], p["_family"] = len(sup), fam
    s = side["subj"].get(pid) or {"main": [], "related": []}
    main = [vocab.label(t) for t in s["main"]] + [None, None, None]
    lic, lic_url, lic_src = L.license_cells(p)
    ver = p.get("version") if p.get("downloaded") else next(
        (v.get("version") for v in p.get("versions") or [] if v.get("access") == p.get("access_type") and v.get("version")),
        None)
    abstract = export_abstract(p.get("abstract") or "") or None
    out = {t: [] for t in ("papers",) + BY_PAPER}
    out["papers"].append((pid, p.get("doi"), L.identifier(p), p.get("title"), L.fmt_authors(p.get("authors"), cap=0),
                          p.get("year"), p.get("journal"), p.get("publisher"), p.get("doc_type"), L.url_of(p),
                          abstract, p.get("abstract_source"), "; ".join(p.get("keywords") or []),
                          main[0], main[1], main[2], "; ".join(vocab.label(t) for t in s["related"]),
                          p.get("access_type"), lic or None, lic_url or None, lic_src or None, p.get("oa_status"),
                          L.VERSION_LABEL.get(ver or "", ver), p.get("cited_by"), p.get("percentile"),
                          p.get("is_preprint"), p.get("retracted"), p.get("is_erratum"),
                          "; ".join(SOURCE_LABEL.get(d, d) for d in p.get("databases") or []), L.downloaded_cell(p),
                          p.get("download_source"), p.get("download_url"), p.get("download_date"), p.get("page_count"),
                          p.get("sha1"), L.si_cell(p) or None, L.notes_for(p) or None, p.get("date_added"),
                          p.get("last_checked"), "; ".join(preprint_links(p, al)) or None))
    detail = p.get("authors_detail") or [{"name": n} for n in p.get("authors") or []]
    for pos, a in enumerate(detail, 1):
        name = (a.get("name") or "").strip()
        if not name:
            continue
        out["paper_authors"].append((pid, authors.id_for(a, name), pos, "; ".join(a.get("institutions") or []) or None,
                                     "; ".join(a.get("countries") or []) or None))
    for t in ts:
        out["paper_collections"].append((pid, t["topic"], t.get("relevance"), t.get("relevance_note"),
                                         t.get("relevance_method"), t.get("in_scope"), t.get("path"), t.get("si_paths"),
                                         t.get("date_added")))
        if t.get("path"):
            out["files"].append((pid, t["topic"], "pdf", t["path"]))
        for sp in json.loads(t.get("si_paths") or "[]"):
            out["files"].append((pid, t["topic"], "si", sp))
    for kind in ("main", "related"):
        for i, term in enumerate(s[kind], 1):
            m = side["meta"].get((pid, term)) or (None, None)
            out["paper_subjects"].append((pid, term, vocab.label(term), kind, i, m[0], m[1]))
    for d in dict.fromkeys(p.get("databases") or []):
        out["paper_sources"].append((pid, d))
    for d in sorted(set([a for a in al if not a.startswith(("patent:", "nodoi:"))] + ([p["doi"]] if p.get("doi") else []))):
        out["identifiers"].append((pid, "doi", d))
    for num in fam:
        out["identifiers"].append((pid, "patent", num))
    for k, v in (p.get("external_ids") or {}).items():
        if v and not isinstance(v, (dict, list)):
            for x in (str(v).split("; ") if k in ("retraction_of", "retraction_notice") else [str(v)]):
                out["identifiers"].append((pid, k, x))
    for e in side["ext"].get(pid, []):
        out["extractions"].append((pid, e["topic"], e["kg"], e["status"], e.get("schema_version"), e.get("nodes"),
                                   e.get("edges"), e.get("date"), e.get("note")))
    out["supplements"] += list(sup.values())
    state = {k: v for k, v in p.items() if k not in STATE_SKIP and not k.startswith(("_", "t_"))}
    if (p.get("abstract") or None) != abstract:
        state["abstract"] = p.get("abstract")
    state["_aliases"] = sorted(al)
    if side["links"].get(pid):
        state["_si_links"] = side["links"][pid]
    out["_paper_state"].append((pid, pack_state(state)))
    return out


INSERT = {"papers": f"INSERT INTO papers VALUES ({','.join('?' * 40)})",
          "paper_authors": "INSERT OR IGNORE INTO paper_authors VALUES (?,?,?,?,?)",
          "paper_collections": "INSERT INTO paper_collections VALUES (?,?,?,?,?,?,?,?,?)",
          "paper_subjects": "INSERT OR IGNORE INTO paper_subjects VALUES (?,?,?,?,?,?,?)",
          "paper_sources": "INSERT OR IGNORE INTO paper_sources VALUES (?,?)",
          "identifiers": "INSERT INTO identifiers VALUES (?,?,?)",
          "files": "INSERT INTO files VALUES (?,?,?,?)",
          "supplements": "INSERT INTO supplements VALUES (?,?,?,?,?)",
          "extractions": "INSERT INTO extractions VALUES (?,?,?,?,?,?,?,?,?)",
          "_paper_state": "INSERT INTO _paper_state VALUES (?,?)"}


def _insert(con, rows):
    for t, sql in INSERT.items():
        if rows.get(t):
            con.executemany(sql, rows[t])


# ------------------------------------------------------------------ the small tables, the project files
def _contrib(state):
    """What one paper adds to each of its topics' counts in `collections`: (papers, in scope, out of scope, PDFs)."""
    if not state:
        return {}
    np_, rt = bool(state.get("is_non_paper")), bool(state.get("is_retracted"))
    pdf = state.get("_pdf") or {}
    return {c: (1, int(s == 1 and not np_ and not rt), int(s == 0 and not np_), int(bool(pdf.get(c))))
            for c, s in (state.get("_collections") or {}).items()}


def _collections_full(con):
    rows = {}
    for (slug,) in con.execute("SELECT DISTINCT collection FROM paper_collections ORDER BY collection").fetchall():
        c = con.execute("SELECT COUNT(*), SUM(CASE WHEN c.in_scope=1 AND COALESCE(p.is_non_paper,0)=0 AND "
                        "COALESCE(p.is_retracted,0)=0 THEN 1 ELSE 0 END), SUM(CASE WHEN c.in_scope=0 AND "
                        "COALESCE(p.is_non_paper,0)=0 THEN 1 ELSE 0 END), SUM(CASE WHEN c.pdf_path IS NOT NULL THEN 1 "
                        "ELSE 0 END) FROM paper_collections c JOIN papers p ON p.id = c.paper_id WHERE c.collection=?",
                        (slug,)).fetchone()
        rows[slug] = tuple(x or 0 for x in c)
    con.execute("DELETE FROM collections")
    con.executemany("INSERT INTO collections (slug, papers, in_scope, out_of_scope, downloaded) VALUES (?,?,?,?,?)",
                    [(s, *v) for s, v in rows.items()])


def _collections_delta(con, deltas):
    """Apply what the synced papers changed to the topics' counts (exact, and independent of the catalogue's size)."""
    for slug, d in deltas.items():
        if not any(d):
            continue
        if con.execute("SELECT 1 FROM collections WHERE slug=?", (slug,)).fetchone():
            con.execute("UPDATE collections SET papers=papers+?, in_scope=in_scope+?, out_of_scope=out_of_scope+?, "
                        "downloaded=downloaded+? WHERE slug=?", (*d, slug))
        else:
            con.execute("INSERT INTO collections (slug, papers, in_scope, out_of_scope, downloaded) VALUES (?,?,?,?,?)",
                        (slug, *d))
    con.execute("DELETE FROM collections WHERE papers <= 0")


def _refresh_small(con, led, vocab, created_at=None, deltas=None):
    """The tables that describe the whole database: sources, subjects, the topics (counts in full on a build, by the
    synced papers' deltas on a sync), the project files, the unattached SI links and `about`."""
    proj = led.proj
    sources = {r[0] for r in con.execute("SELECT DISTINCT source FROM paper_sources")}
    con.execute("DELETE FROM sources")
    con.executemany("INSERT INTO sources VALUES (?,?)", [(k, SOURCE_LABEL.get(k, k)) for k in sorted(sources)])
    con.execute("DELETE FROM subjects")
    con.executemany("INSERT INTO subjects VALUES (?,?,?,?,?)",
                    [(t, vocab.terms[t]["label"], vocab.terms[t].get("name"), vocab.terms[t].get("facet"),
                      "; ".join(vocab.label(x) for x in vocab.terms[t].get("related") or [])) for t in vocab.order])
    if deltas is None:
        _collections_full(con)
    else:
        _collections_delta(con, deltas)
    for (slug,) in con.execute("SELECT slug FROM collections").fetchall():
        cfg = json_read(proj.topic_dir(slug) / "config.json", {}) or {}
        st = json_read(proj.topic_dir(slug) / "state.json", {}) or {}
        li, lu = run_dates(st)
        con.execute("UPDATE collections SET topic=?, created_at=?, last_index=?, last_update=?, folder=? WHERE slug=?",
                    (cfg.get("topic"), cfg.get("created_at"), li, lu, proj.rel(proj.pub / slug), slug))
    _capture_project_files(con, proj, [r[0] for r in con.execute("SELECT slug FROM collections")])
    old = dict(con.execute("SELECT name, value FROM about").fetchall())
    # SI links whose parent DOI is no indexed paper (an issue DOI ...): kept so the ledger can be rebuilt whole;
    # looked for again only when the ledger's SI links or DOIs changed
    fp = json.dumps([tuple(r) for r in led.q("SELECT COUNT(*), MAX(rowid) FROM si_links")] +
                    [tuple(r) for r in led.q("SELECT COUNT(*), MAX(rowid) FROM dois")])
    if deltas is None or old.get("_si_links_seen") != fp:
        con.execute("DELETE FROM _si_links_unattached")
        con.executemany("INSERT OR IGNORE INTO _si_links_unattached VALUES (?,?,?,?,?,?)", [tuple(r) for r in led.q(
            "SELECT * FROM si_links l WHERE NOT EXISTS (SELECT 1 FROM dois d WHERE d.doi = l.parent_doi)")])
    n_papers = con.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    now = now_iso()
    about = {"format": FORMAT, "created_at": created_at or old.get("created_at") or now, "updated_at": now,
             "built_at": now, "papers": str(n_papers),
             "authors": str(con.execute("SELECT COUNT(*) FROM authors").fetchone()[0]), "_si_links_seen": fp,
             "source_of_truth": "this file: it evolves in place (runs, changes), and the skill's working ledger "
                                "(.scripts/ledger.sqlite) is rebuilt from it when missing",
             "vocabulary": vocab.name, "examples": "\n\n".join(EXAMPLES)}
    about.update({f"column:{k}": v for k, v in COLUMN_HELP.items()})
    con.execute("DELETE FROM about")
    con.executemany("INSERT INTO about VALUES (?,?)", sorted(about.items()))
    return n_papers


def _capture_project_files(con, proj, slugs):
    """The small files that say what a topic searches and where its last run stopped, and the project's decisions:
    kept in the database so the working folder can be rebuilt from it."""
    paths = [f"{slug}/{n}" for slug in slugs for n in PROJECT_FILES] + ["dedup_decisions.jsonl", "vocab_custom.json"]
    have = dict(con.execute("SELECT path, sha256 FROM project_files").fetchall())
    for rel in paths:
        f = proj.scr / rel
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if have.get(rel) != h:
            con.execute("INSERT OR REPLACE INTO project_files VALUES (?,?,?,?)", (rel, text, h, now_iso()))


# ------------------------------------------------------------------ in-place sync
def _snapshot(con, ids):
    """The current published state of these papers, for the change log: tracked fields, text and topic scope."""
    marks = ",".join("?" * len(ids))
    cols = sorted(set(TRACKED) | set(TEXTUAL))
    out = {r[0]: dict(zip(["id"] + cols, r)) for r in
           con.execute(f"SELECT id, {', '.join(cols)} FROM papers WHERE id IN ({marks})", ids)}
    for pid, coll, scope, pdf in con.execute(f"SELECT paper_id, collection, in_scope, pdf_path FROM paper_collections "
                                             f"WHERE paper_id IN ({marks})", ids):
        if pid in out:
            out[pid].setdefault("_collections", {})[coll] = scope
            out[pid].setdefault("_pdf", {})[coll] = pdf
    return out


def _why_removed(led, old):
    doi = old.get("doi")
    if doi:
        r = led.q("SELECT paper_id FROM dois WHERE doi=?", (doi,))
        if r:
            return f"merged into {r[0][0]}"
        r = led.q("SELECT d.paper_id FROM si_links l JOIN dois d ON d.doi = l.parent_doi WHERE l.si_doi=? LIMIT 1", (doi,))
        if r:
            return f"supporting information of {r[0][0]}"
    return "removed from every topic"


def _changes(run_id, pid, old, new, led):
    """Change-log rows for one paper, and whether its text, topics or exclusion changed (saved filters re-run)."""
    rows = []
    if old is None and new is None:
        return rows, False
    if old is None:
        return [(run_id, pid, "added", None, None, ", ".join(sorted(new.get("_collections") or {})))], True
    if new is None:
        return [(run_id, pid, "removed", None, old.get("doi"), _why_removed(led, old))], True
    for f in TRACKED:
        if str(old.get(f)) != str(new.get(f)):
            rows.append((run_id, pid, "changed", f, None if old.get(f) is None else str(old[f]),
                         None if new.get(f) is None else str(new[f])))
    oc, nc = old.get("_collections") or {}, new.get("_collections") or {}
    for c in sorted(set(oc) | set(nc)):
        if oc.get(c, "-") != nc.get(c, "-"):
            rows.append((run_id, pid, "collection", c, None if c not in oc else str(oc[c]),
                         None if c not in nc else str(nc[c])))
    textual = any(str(old.get(f)) != str(new.get(f)) for f in TEXTUAL)
    return rows, textual


def sync_published_db(led, vocab, topics=None, note=None):
    """Publish the papers the ledger marked since the last sync, in place; record the run and what changed."""
    import _ledger as L
    proj = led.proj
    with file_lock(proj.scr / "publish"):
        if not has_state(proj.db):
            return build_published_db(led, vocab, note=note or "the first evolving build of this database")
        max_seq = led.q("SELECT MAX(seq) FROM publish_queue")[0][0] or 0
        ids = [r[0] for r in led.q("SELECT DISTINCT paper_id FROM publish_queue WHERE seq <= ? ORDER BY paper_id",
                                   (max_seq,))]
        con = sqlite3.connect(str(proj.db), timeout=300)
        con.execute("PRAGMA busy_timeout=300000")
        ensure_state(con)
        _add_columns(con, led)
        cols = [d[0] for d in con.execute("SELECT * FROM papers LIMIT 0").description]
        step, tnames = _step_name(topics)
        counts = {"added": 0, "updated": 0, "removed": 0}
        refilter, deltas = set(), {}
        with con:
            run_id = new_run(con, step, tnames, note)
        authors = _Authors(con, cache=False)
        for i in range(0, len(ids), 5000):
            part = ids[i:i + 5000]
            marks = ",".join("?" * len(part))
            ledger_rows = {r["id"]: led.row(r) for r in led.q(f"SELECT * FROM papers WHERE id IN ({marks})", part)}
            side = _side(led, f"IN ({marks})", part)
            old = _snapshot(con, part)
            old_full = {r[0]: r for r in con.execute(f"SELECT * FROM papers WHERE id IN ({marks})", part)}
            old_authors = {r[0] for r in con.execute(f"SELECT author_id FROM paper_authors WHERE paper_id IN ({marks})",
                                                     part)}
            with con:
                con.execute(f"DELETE FROM papers WHERE id IN ({marks})", part)
                for t in BY_PAPER:
                    con.execute(f"DELETE FROM {t} WHERE paper_id IN ({marks})", part)
                change_rows = []
                for pid in part:
                    rows = _rows(ledger_rows[pid], side, vocab, authors, L) if pid in ledger_rows else None
                    new = None
                    if rows:
                        _insert(con, rows)
                        r = rows["papers"][0]
                        new = dict(zip(cols, r))
                        new["_collections"] = {c[1]: c[5] for c in rows["paper_collections"]}
                        new["_pdf"] = {c[1]: c[6] for c in rows["paper_collections"]}
                        if pid in old_full and tuple(old_full[pid]) != tuple(r):
                            counts["updated"] += 1
                    o = old.get(pid)
                    if o is not None and new is None:
                        counts["removed"] += 1
                    elif o is None and new is not None:
                        counts["added"] += 1
                    for c, v in _contrib(new).items():
                        deltas[c] = [a + b for a, b in zip(deltas.get(c, (0, 0, 0, 0)), v)]
                    for c, v in _contrib(o).items():
                        deltas[c] = [a - b for a, b in zip(deltas.get(c, (0, 0, 0, 0)), v)]
                    cr, textual = _changes(run_id, pid, o, new, led)
                    change_rows += cr
                    if textual:
                        refilter.add(pid)
                con.executemany("INSERT INTO changes VALUES (?,?,?,?,?,?)", change_rows)
                if old_authors:                       # authors left with no paper (their papers merged away)
                    con.execute("CREATE TEMP TABLE IF NOT EXISTS _old_authors (id INTEGER PRIMARY KEY)")
                    con.execute("DELETE FROM _old_authors")
                    con.executemany("INSERT OR IGNORE INTO _old_authors VALUES (?)", [(x,) for x in old_authors])
                    con.execute("DELETE FROM author_keys WHERE author_id IN (SELECT o.id FROM _old_authors o WHERE NOT "
                                "EXISTS (SELECT 1 FROM paper_authors pa WHERE pa.author_id = o.id))")
                    con.execute("DELETE FROM authors WHERE id IN (SELECT o.id FROM _old_authors o WHERE NOT EXISTS "
                                "(SELECT 1 FROM paper_authors pa WHERE pa.author_id = o.id))")
        with con:
            n_papers = _refresh_small(con, led, vocab, deltas=deltas)
            con.execute("UPDATE runs SET added=?, updated=?, removed=?, papers=? WHERE id=?",
                        (counts["added"], counts["updated"], counts["removed"], n_papers, run_id))
            if not ids and not note:
                con.execute("DELETE FROM runs WHERE id=?", (run_id,))     # a sync that changed nothing is no run
        led.x("DELETE FROM publish_queue WHERE seq <= ?", (max_seq,))
        refreshed = {}
        if refilter:                          # the saved filters, for the papers whose text, topics or flags changed
            from _filters import refresh_papers
            refreshed = refresh_papers(con, sorted(refilter))
        con.close()
        res = {**counts, "papers": n_papers, "synced": len(ids)}
        if refreshed:
            res["filters"] = refreshed
        if ids:
            log(f"papers.db: {counts['added']} added, {counts['updated']} updated, {counts['removed']} removed "
                f"({len(ids)} papers synced; {n_papers} in the database)")
        return res


# ------------------------------------------------------------------ a full build (the first one, or the fallback)
def build_published_db(led, vocab, note=None):
    """Build papers.db from the ledger in one pass: the first build of an evolving database, or the fallback
    (export.py --rebuild). The history, saved filters and project files of an existing database are carried over."""
    import _ledger as L
    proj = led.proj
    path = proj.db
    tmp = proj.tmp / "papers.db.tmp"
    for f in (tmp, proj.tmp / "papers.db.tmp-journal"):
        if f.exists():
            f.unlink()
    max_seq = led.q("SELECT MAX(seq) FROM publish_queue")[0][0] or 0
    con = sqlite3.connect(str(tmp))
    con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;" + DDL + STATE_DDL)
    created = None
    if has_state(path):          # carry over the history and the saved filters
        con.execute("ATTACH DATABASE ? AS old", (str(path),))       # only read
        for t in ("runs", "changes", "filters", "project_files", "authors", "author_keys"):
            mine = [r[1] for r in con.execute(f"PRAGMA main.table_info({t})")]
            theirs = {r[1] for r in con.execute(f"PRAGMA old.table_info({t})")}
            cols = ", ".join(c for c in mine if c in theirs)
            con.execute(f"INSERT INTO main.{t} ({cols}) SELECT {cols} FROM old.{t}")
        created = (con.execute("SELECT value FROM old.about WHERE name='created_at'").fetchone() or [None])[0]
        con.commit()
        con.execute("DETACH DATABASE old")
    elif path.exists():           # an older snapshot: the earlier exports were not recorded
        note = note or "rebuilt from the ledger"
    step, tnames = _step_name()
    run_id = new_run(con, step, tnames, note or "full rebuild from the ledger")
    authors = _Authors(con, cache=True)
    n_papers, last_id = 0, 0
    while True:
        chunk = [led.row(r) for r in led.q("SELECT * FROM papers WHERE id > ? ORDER BY id LIMIT ?", (last_id, CHUNK))]
        if not chunk:
            break
        lo, hi = chunk[0]["id"], chunk[-1]["id"]
        last_id = hi
        side = _side(led, "BETWEEN ? AND ?", (lo, hi))
        for p in chunk:
            rows = _rows(p, side, vocab, authors, L)
            if rows:
                _insert(con, rows)
                n_papers += 1
        con.commit()
    con.executescript(POST + STATE_INDEXES)
    con.execute("DELETE FROM authors WHERE id NOT IN (SELECT DISTINCT author_id FROM paper_authors)")
    con.execute("DELETE FROM author_keys WHERE author_id NOT IN (SELECT id FROM authors)")
    if _fts_ok(con):
        con.executescript("CREATE VIRTUAL TABLE papers_fts USING fts5(title, abstract, keywords, content='papers', "
                          "content_rowid='id'); INSERT INTO papers_fts(rowid, title, abstract, keywords) "
                          "SELECT id, title, abstract, keywords FROM papers;" + FTS_TRIGGERS)
    n_papers = _refresh_small(con, led, vocab, created_at=created)
    con.execute("UPDATE runs SET papers=? WHERE id=?", (n_papers, run_id))
    con.commit()
    from _filters import refresh
    refresh(con)
    con.commit()
    con.close()                   # written once, in id order: nothing to compact
    os.replace(tmp, path)
    led.x("DELETE FROM publish_queue WHERE seq <= ?", (max_seq,))
    log(f"papers.db built: {n_papers} papers")
    return {"added": 0, "updated": 0, "removed": 0, "papers": n_papers, "synced": n_papers, "rebuilt": True}


# ------------------------------------------------------------------ the ledger from the database
def adopt_ledger(led):
    """Rebuild an empty working ledger (and the topics' working files) from publications/papers.db, so that a
    project received as papers.db alone can be updated. Returns the number of papers adopted."""
    import _ledger as L
    proj = led.proj
    pub = sqlite3.connect(f"file:{proj.db}?mode=ro", uri=True)
    pub.row_factory = sqlite3.Row
    cols = [r[1] for r in led.q("PRAGMA table_info(papers)")]
    n, last = 0, 0
    while True:
        rows = pub.execute("SELECT p.*, s.state FROM papers p JOIN _paper_state s ON s.paper_id = p.id WHERE p.id > ? "
                           "ORDER BY p.id LIMIT ?", (last, CHUNK)).fetchall()
        if not rows:
            break
        last = rows[-1]["id"]
        with led.tx():
            for r in rows:
                st = unpack_state(r["state"])
                row = {k: v for k, v in st.items() if k in cols}
                for pub_col, led_col in COPIED.items():
                    row[led_col] = r[pub_col]
                row["abstract"] = st["abstract"] if "abstract" in st else r["abstract"]
                for k in L.JSON_COLS:
                    if k in row and not isinstance(row[k], str):
                        row[k] = json.dumps(row[k], ensure_ascii=False)
                keys = [k for k in cols if k in row]
                led.db.execute(f"INSERT OR REPLACE INTO papers ({', '.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                               [row[k] for k in keys])
                led.db.executemany("INSERT OR IGNORE INTO dois VALUES (?,?)", [(a, r["id"]) for a in st.get("_aliases") or []])
                led.db.executemany("INSERT OR IGNORE INTO si_links VALUES (?,?,?,?,?,?)",
                                   [(s["parent_doi"], s["si_doi"], s.get("url"), s.get("title"), s.get("source"),
                                     s.get("date_added")) for s in st.get("_si_links") or []])
                n += 1
            ids = [r["id"] for r in rows]
            marks = ",".join("?" * len(ids))
            led.db.executemany("INSERT OR REPLACE INTO paper_topics VALUES (?,?,?,?,?,?,?,?,?)", [tuple(x) for x in pub.execute(
                "SELECT paper_id, collection, relevance, relevance_note, relevance_method, in_scope, pdf_path, "
                f"COALESCE(si_paths, '[]'), date_added FROM paper_collections WHERE paper_id IN ({marks})", ids)])
            led.db.executemany("INSERT OR REPLACE INTO paper_subjects VALUES (?,?,?,?,?,?)", [tuple(x) for x in pub.execute(
                f"SELECT paper_id, term, kind, rank, method, score FROM paper_subjects WHERE paper_id IN ({marks})", ids)])
            led.db.executemany("INSERT OR REPLACE INTO extractions VALUES (?,?,?,?,?,?,?,?,?)", [tuple(x) for x in pub.execute(
                "SELECT paper_id, collection, kg, status, schema_version, nodes, edges, date, note FROM extractions "
                f"WHERE paper_id IN ({marks})", ids)])
    if "_si_links_unattached" in _tables(pub):
        with led.tx():
            led.db.executemany("INSERT OR IGNORE INTO si_links VALUES (?,?,?,?,?,?)",
                               [tuple(x) for x in pub.execute("SELECT * FROM _si_links_unattached")])
    for rel, content in pub.execute("SELECT path, content FROM project_files"):
        f = proj.scr / rel
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content, encoding="utf-8")
    pub.close()
    led.x("DELETE FROM publish_queue")          # the ledger now mirrors the database
    return n
