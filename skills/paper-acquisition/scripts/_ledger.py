"""The paper ledger and its exports (library module — not run directly).

Working ledger: .scripts/ledger.sqlite (WAL mode, safe for a background downloader plus foreground scripts). One row
per paper across ALL topics:
  papers          one row per paper (ID = file name stem: publications/<topic>/papers/<ACCESS>/<ID>.pdf)
  paper_topics    one row per (paper, topic = index collection): relevance, scope decision, file paths in that topic
  paper_subjects  the paper's Topic A/B/C (kind 'main', rank 1-3) and Related topics (kind 'related')
  extractions     curation results per (paper, topic, graph), synced from
                  .scripts/<topic>/kg/<name>/extraction_status.jsonl
  dois            every DOI known for a paper (canonical + preprint/version aliases) -> paper id

  publish_queue   every paper a write touched since the last publish (filled by triggers on the tables above)

Publishing (every step does it at the end; _publish.py):
  publications/papers.db   the paper database: each step updates, in place, only the papers it changed, and records
                           the run and what changed; it also holds what this ledger needs, so a missing ledger is
                           rebuilt from it (adopt_ledger)
  publications/<topic>/index/{OA,OA+ND,Free-to-read,Paywalled,merged,excluded}.csv   only on request (export.py --csv)
"""
import csv
import json
import os
import sqlite3
import threading
from pathlib import Path

from _common import (ACCESS_TYPES, LICENSE_LABEL, NOT_DOWNLOADED_TYPES, PREPRINT_PREFIXES, SOURCE_LABEL, access_rank,
                     clean_name, clean_title, file_lock, jsonl_iter, json_read, license_detail, log, norm_doc_type,
                     norm_doi, export_abstract, normalize_abstract, now_iso, preprint_links, title_hash, today)

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
  id INTEGER PRIMARY KEY,
  key TEXT UNIQUE NOT NULL,                 -- canonical DOI, 'patent:<number>', or 'nodoi:<title hash>'
  doi TEXT UNIQUE,
  title TEXT, authors TEXT NOT NULL DEFAULT '[]', authors_detail TEXT NOT NULL DEFAULT '[]',
  year INTEGER, journal TEXT, publisher TEXT, type TEXT, doc_type TEXT,
  abstract TEXT, abstract_source TEXT, keywords TEXT NOT NULL DEFAULT '[]', link TEXT,
  databases TEXT NOT NULL DEFAULT '[]', external_ids TEXT NOT NULL DEFAULT '{}',
  cited_by INTEGER, percentile REAL,
  is_preprint INTEGER NOT NULL DEFAULT 0, is_erratum INTEGER NOT NULL DEFAULT 0, retracted INTEGER NOT NULL DEFAULT 0,
  access_type TEXT, access_basis TEXT, license TEXT, license_evidence TEXT, oa_status TEXT,
  license_label TEXT, license_url TEXT, license_source TEXT,
  versions TEXT NOT NULL DEFAULT '[]',     -- known copies [{url,pdf_url,license,access,version,src,host_type}]
  downloaded INTEGER NOT NULL DEFAULT 0, version TEXT, download_source TEXT, download_url TEXT, download_date TEXT,
  sha1 TEXT, page_count INTEGER,
  dl_status TEXT, dl_note TEXT,            -- why it is not downloaded (failed / queued / no copy / not selected)
  si_status TEXT, si_files TEXT NOT NULL DEFAULT '[]',
  extracted TEXT NOT NULL DEFAULT 'No',
  date_added TEXT, updated_at TEXT, last_checked TEXT
);
CREATE TABLE IF NOT EXISTS paper_topics (
  paper_id INTEGER NOT NULL, topic TEXT NOT NULL,
  relevance INTEGER, relevance_note TEXT, relevance_method TEXT, in_scope INTEGER,
  path TEXT, si_paths TEXT NOT NULL DEFAULT '[]', date_added TEXT,
  PRIMARY KEY (paper_id, topic)
);
CREATE TABLE IF NOT EXISTS paper_subjects (
  paper_id INTEGER NOT NULL, term TEXT NOT NULL, kind TEXT NOT NULL, rank INTEGER NOT NULL,
  method TEXT, score REAL, PRIMARY KEY (paper_id, term)
);
CREATE TABLE IF NOT EXISTS extractions (
  paper_id INTEGER NOT NULL, topic TEXT NOT NULL, kg TEXT NOT NULL, status TEXT NOT NULL,
  schema_version TEXT, nodes INTEGER, edges INTEGER, date TEXT, note TEXT,
  PRIMARY KEY (paper_id, topic, kg)
);
CREATE TABLE IF NOT EXISTS dois (doi TEXT PRIMARY KEY, paper_id INTEGER NOT NULL);
-- dois also holds non-DOI aliases of merged records: 'patent:WO2008004088', 'nodoi:<title hash>'
CREATE TABLE IF NOT EXISTS si_links (
  parent_doi TEXT NOT NULL, si_doi TEXT NOT NULL, url TEXT, title TEXT, source TEXT, date_added TEXT,
  PRIMARY KEY (parent_doi, si_doi)
);
CREATE INDEX IF NOT EXISTS ix_pt_topic ON paper_topics(topic);
CREATE INDEX IF NOT EXISTS ix_papers_sha1 ON papers(sha1);
CREATE INDEX IF NOT EXISTS ix_ps_paper ON paper_subjects(paper_id);
CREATE INDEX IF NOT EXISTS ix_dois_paper ON dois(paper_id);
CREATE TABLE IF NOT EXISTS publish_queue (seq INTEGER PRIMARY KEY, paper_id INTEGER NOT NULL);
CREATE TRIGGER IF NOT EXISTS pq_papers_i AFTER INSERT ON papers BEGIN
  INSERT INTO publish_queue(paper_id) VALUES (NEW.id); END;
CREATE TRIGGER IF NOT EXISTS pq_papers_u AFTER UPDATE ON papers BEGIN
  INSERT INTO publish_queue(paper_id) VALUES (NEW.id); END;
CREATE TRIGGER IF NOT EXISTS pq_papers_d AFTER DELETE ON papers BEGIN
  INSERT INTO publish_queue(paper_id) VALUES (OLD.id); END;
CREATE TRIGGER IF NOT EXISTS pq_topics_i AFTER INSERT ON paper_topics BEGIN
  INSERT INTO publish_queue(paper_id) VALUES (NEW.paper_id); END;
CREATE TRIGGER IF NOT EXISTS pq_topics_u AFTER UPDATE ON paper_topics BEGIN
  INSERT INTO publish_queue(paper_id) VALUES (OLD.paper_id); INSERT INTO publish_queue(paper_id) VALUES (NEW.paper_id); END;
CREATE TRIGGER IF NOT EXISTS pq_topics_d AFTER DELETE ON paper_topics BEGIN
  INSERT INTO publish_queue(paper_id) VALUES (OLD.paper_id); END;
CREATE TRIGGER IF NOT EXISTS pq_subjects_i AFTER INSERT ON paper_subjects BEGIN
  INSERT INTO publish_queue(paper_id) VALUES (NEW.paper_id); END;
CREATE TRIGGER IF NOT EXISTS pq_subjects_u AFTER UPDATE ON paper_subjects BEGIN
  INSERT INTO publish_queue(paper_id) VALUES (OLD.paper_id); INSERT INTO publish_queue(paper_id) VALUES (NEW.paper_id); END;
CREATE TRIGGER IF NOT EXISTS pq_subjects_d AFTER DELETE ON paper_subjects BEGIN
  INSERT INTO publish_queue(paper_id) VALUES (OLD.paper_id); END;
CREATE TRIGGER IF NOT EXISTS pq_ext_i AFTER INSERT ON extractions BEGIN
  INSERT INTO publish_queue(paper_id) VALUES (NEW.paper_id); END;
CREATE TRIGGER IF NOT EXISTS pq_ext_u AFTER UPDATE ON extractions BEGIN
  INSERT INTO publish_queue(paper_id) VALUES (OLD.paper_id); INSERT INTO publish_queue(paper_id) VALUES (NEW.paper_id); END;
CREATE TRIGGER IF NOT EXISTS pq_ext_d AFTER DELETE ON extractions BEGIN
  INSERT INTO publish_queue(paper_id) VALUES (OLD.paper_id); END;
CREATE TRIGGER IF NOT EXISTS pq_dois_i AFTER INSERT ON dois BEGIN
  INSERT INTO publish_queue(paper_id) VALUES (NEW.paper_id); END;
CREATE TRIGGER IF NOT EXISTS pq_dois_u AFTER UPDATE ON dois BEGIN
  INSERT INTO publish_queue(paper_id) VALUES (OLD.paper_id); INSERT INTO publish_queue(paper_id) VALUES (NEW.paper_id); END;
CREATE TRIGGER IF NOT EXISTS pq_dois_d AFTER DELETE ON dois BEGIN
  INSERT INTO publish_queue(paper_id) VALUES (OLD.paper_id); END;
CREATE TRIGGER IF NOT EXISTS pq_si_i AFTER INSERT ON si_links BEGIN
  INSERT INTO publish_queue(paper_id) SELECT paper_id FROM dois WHERE doi = NEW.parent_doi; END;
CREATE TRIGGER IF NOT EXISTS pq_si_u AFTER UPDATE ON si_links BEGIN
  INSERT INTO publish_queue(paper_id) SELECT paper_id FROM dois WHERE doi IN (OLD.parent_doi, NEW.parent_doi); END;
CREATE TRIGGER IF NOT EXISTS pq_si_d AFTER DELETE ON si_links BEGIN
  INSERT INTO publish_queue(paper_id) SELECT paper_id FROM dois WHERE doi = OLD.parent_doi; END;
"""
# columns added after v2 — added in place to an older ledger (never dropped or renamed)
V3_COLUMNS = {"authors_detail": "TEXT NOT NULL DEFAULT '[]'", "doc_type": "TEXT", "abstract_source": "TEXT",
              "keywords": "TEXT NOT NULL DEFAULT '[]'", "license_label": "TEXT", "license_url": "TEXT",
              "license_source": "TEXT", "last_checked": "TEXT"}

JSON_COLS = {"authors", "authors_detail", "keywords", "databases", "external_ids", "versions", "si_files", "si_paths"}

INDEX_COLUMNS = ["ID", "Title", "Authors", "Year", "Venue", "Publisher", "Doc type", "Retracted", "DOI/ID", "URL",
                 "Preprint link", "Abstract", "Keywords", "Topic A", "Topic B", "Topic C", "Related topics", "Relevance",
                 "Relevance note", "Access type", "License", "License URL", "License source", "Version", "Database",
                 "Index", "Citations", "Downloaded", "Path", "SI", "Extracted", "Notes", "Date added", "Last checked"]
INDEX_FILES = ACCESS_TYPES + ["merged", "excluded"]
MAX_AUTHORS = 10
VERSION_LABEL = {"publishedVersion": "Published version", "acceptedVersion": "Accepted manuscript",
                 "submittedVersion": "Preprint"}
EVIDENCE_LABEL = {"pdf_article_license_statement": "PDF (printed license statement)", "pmc_license_code": "PubMed Central",
                  "unpaywall": "Unpaywall", "openalex": "OpenAlex", "crossref": "Crossref", "crossref_vor": "Crossref",
                  "europepmc": "Europe PMC", "s2": "Semantic Scholar", "datacite": "DataCite", "arxiv": "arXiv",
                  "pmc_aws": "PubMed Central", "preprint": "Preprint server", "openaire": "OpenAIRE",
                  "metadata": "Metadata", "patent": "Patent office", "source": "Search source"}


def _j(v):
    return json.dumps(v, ensure_ascii=False)


def _scalar(v):
    """Sources sometimes return lists or numbers for text fields (type, journal...): store them as text."""
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v if x not in (None, "")) or None
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return v


def _year(y):
    """Plausible publication year or None (sources carry typos such as 2915)."""
    import datetime
    try:
        y = int(str(y)[:4])
        return y if 1600 <= y <= datetime.date.today().year + 2 else None
    except (TypeError, ValueError):
        return None


def _keywords(v):
    if not v:
        return []
    if isinstance(v, str):
        v = [x for x in v.replace(";", ",").split(",")]
    out = []
    for x in v:
        x = clean_title(str(x)).strip(" ;,")
        if x and len(x) <= 120 and x.lower() not in {o.lower() for o in out}:
            out.append(x)
    return out[:25]


class Ledger:
    def __init__(self, proj, adopt=True):
        self.proj = proj
        self.path = proj.ledger_db
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), timeout=120, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=120000")
        self.db.executescript(SCHEMA)
        have = {r[1] for r in self.db.execute("PRAGMA table_info(papers)")}
        for col, decl in V3_COLUMNS.items():
            if col not in have:
                self.db.execute(f"ALTER TABLE papers ADD COLUMN {col} {decl}")
        self.last_publish = None
        if adopt and not self.q("SELECT 1 FROM papers LIMIT 1"):
            self._adopt()

    def _adopt(self):
        """A project received as publications/papers.db alone: rebuild this ledger and the topics' working files from
        it, so every step (Update included) carries on where the database stopped."""
        from _publish import adopt_ledger, has_state
        if not has_state(self.proj.db):
            return
        with file_lock(self.proj.scr / "publish"):
            if self.q("SELECT 1 FROM papers LIMIT 1"):
                return
            log(f"no working ledger: rebuilding {self.proj.rel(self.path)} from {self.proj.rel(self.proj.db)} ...")
            n = adopt_ledger(self)
            log(f"ledger rebuilt from the database: {n} papers")

    # ------------------------------------------------------------ low level
    def q(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def x(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args)

    def tx(self):
        """Use as `with led.tx():` for a batch of writes (one transaction)."""
        return _Tx(self)

    @staticmethod
    def row(r):
        if r is None:
            return None
        d = dict(r)
        for k in JSON_COLS:
            if k in d and isinstance(d[k], str):
                try:
                    d[k] = json.loads(d[k])
                except json.JSONDecodeError:
                    d[k] = [] if k != "external_ids" else {}
        return d

    def get(self, pid):
        return self.row((self.q("SELECT * FROM papers WHERE id=?", (pid,)) or [None])[0])

    def find_id(self, doi=None, key=None):
        if doi:
            r = self.q("SELECT paper_id FROM dois WHERE doi=?", (doi,))
            if r:
                return r[0][0]
        if key:
            r = self.q("SELECT id FROM papers WHERE key=?", (key,))
            if r:
                return r[0][0]
            r = self.q("SELECT paper_id FROM dois WHERE doi=?", (key,))
            if r:
                return r[0][0]
        return None

    def set(self, pid, **f):
        if not f:
            return
        if f.get("abstract"):
            f["abstract"] = normalize_abstract(f["abstract"]) or None
        f["updated_at"] = now_iso()
        cols = ", ".join(f"{k}=?" for k in f)
        vals = [(_j(v) if k in JSON_COLS else _scalar(v)) for k, v in f.items()]
        self.x(f"UPDATE papers SET {cols} WHERE id=?", (*vals, pid))

    def set_topic(self, pid, topic, **f):
        self.x("INSERT OR IGNORE INTO paper_topics(paper_id, topic, date_added) VALUES (?,?,?)", (pid, topic, now_iso()))
        if f:
            cols = ", ".join(f"{k}=?" for k in f)
            vals = [(_j(v) if k in JSON_COLS else v) for k, v in f.items()]
            self.x(f"UPDATE paper_topics SET {cols} WHERE paper_id=? AND topic=?", (*vals, pid, topic))

    def topics_of(self, pid):
        return [dict(r) for r in self.q("SELECT * FROM paper_topics WHERE paper_id=? ORDER BY date_added, topic", (pid,))]

    def add_dois(self, pid, dois):
        for d in dois:
            if d:
                self.x("INSERT OR IGNORE INTO dois(doi, paper_id) VALUES (?,?)", (d, pid))

    def aliases(self, pid):
        return [r[0] for r in self.q("SELECT doi FROM dois WHERE paper_id=?", (pid,))]

    # ------------------------------------------------------------ supplementary-information deposits
    def add_si_links(self, links):
        """links: [{parent_doi, si_doi, url, title, source}] — SI deposits found by the search (Figshare, DataCite,
        ACS '.s001' DOIs ...), kept as links of the paper they belong to instead of separate papers."""
        n = 0
        for l in links:
            if l.get("parent_doi") and l.get("si_doi") and l["parent_doi"] != l["si_doi"]:
                cur = self.x("INSERT OR IGNORE INTO si_links VALUES (?,?,?,?,?,?)",
                             (l["parent_doi"], l["si_doi"], l.get("url"), l.get("title"), l.get("source"), today()))
                n += cur.rowcount or 0
        return n

    def si_links_of(self, pid):
        return [dict(r) for r in self.q("SELECT l.* FROM si_links l JOIN dois d ON d.doi = l.parent_doi "
                                        "WHERE d.paper_id=? ORDER BY l.si_doi", (pid,))]

    def _si_link_counts(self):
        return {r[0]: r[1] for r in self.q("SELECT d.paper_id, COUNT(DISTINCT l.si_doi) FROM si_links l "
                                           "JOIN dois d ON d.doi = l.parent_doi GROUP BY d.paper_id")}

    def _preprint_alias_map(self):
        """paper -> the preprint DOIs merged into it (one range scan per preprint server's DOI prefix)."""
        out = {}
        for pre in PREPRINT_PREFIXES:
            for r in self.q("SELECT paper_id, doi FROM dois WHERE doi >= ? AND doi < ?", (pre, pre[:-1] + "0")):
                out.setdefault(r[0], []).append(r[1])
        return out

    def _family_map(self):
        """paper -> patent numbers of the same invention merged into it (aliases 'patent:...')."""
        out = {}
        for r in self.q("SELECT paper_id, doi FROM dois WHERE doi LIKE 'patent:_%'"):
            out.setdefault(r[0], []).append(r[1][len("patent:"):])
        return out

    # ------------------------------------------------------------ retractions
    def record_retraction(self, notice_id, targets):
        """A retraction notice and the papers it retracts (DOIs): the notice is a non-paper that names them, and each
        of them is retracted and names its notice (external ids retraction_of / retraction_notice). Returns how many
        papers became retracted."""
        notice = self.get(notice_id)
        if not notice or not targets:
            return 0
        ext = dict(notice["external_ids"], retraction_of="; ".join(targets))
        upd = {k: v for k, v in (("external_ids", ext), ("is_erratum", 1), ("retracted", 0))
               if v != notice.get(k)}
        if upd:
            self.set(notice_id, **upd)
        n = 0
        for t in targets:
            tid = self.find_id(doi=t)
            if not tid or tid == notice_id:
                continue
            tr = self.get(tid)
            have = [x for x in str(tr["external_ids"].get("retraction_notice") or "").split("; ") if x]
            text = dict(tr["external_ids"], retraction_notice="; ".join(dict.fromkeys(have + [notice["doi"]])))
            upd = {k: v for k, v in (("external_ids", text), ("retracted", 1)) if v != tr.get(k)}
            if upd:
                self.set(tid, **upd)
            n += not tr.get("retracted")
        return n

    # ------------------------------------------------------------ subjects (Topic A/B/C + related)
    def subjects_of(self, pid):
        return [dict(r) for r in self.q("SELECT * FROM paper_subjects WHERE paper_id=? ORDER BY kind DESC, rank", (pid,))]

    def set_subjects(self, pid, main, related, method, scores=None, force=False):
        """Replace a paper's Topic A/B/C and Related topics — unless they came from a better method
        (manual > claude > api > vocab) and `force` is not set. Returns True when written."""
        from _topics import METHOD_RANK
        cur = self.q("SELECT method FROM paper_subjects WHERE paper_id=? AND kind='main' LIMIT 1", (pid,))
        if cur and not force and METHOD_RANK.get(cur[0][0] or "vocab", 0) > METHOD_RANK.get(method, 0):
            return False
        self.x("DELETE FROM paper_subjects WHERE paper_id=?", (pid,))
        for i, t in enumerate(main[:3], 1):
            self.x("INSERT OR REPLACE INTO paper_subjects VALUES (?,?,?,?,?,?)",
                   (pid, t, "main", i, method, (scores or {}).get(t)))
        for i, t in enumerate([r for r in related if r not in main], 1):
            self.x("INSERT OR IGNORE INTO paper_subjects VALUES (?,?,?,?,?,?)", (pid, t, "related", i, method, None))
        return True

    # ------------------------------------------------------------ candidates
    def upsert(self, rec, topic, explicit_id=None):
        """Merge one deduplicated candidate into the ledger and attach it to `topic`.
        rec keys: doi, dois_all, key (optional, e.g. 'patent:US-1234567-B2'), title, authors, authors_detail, year,
        journal, publisher, type, doc_type, abstract, keywords, link, databases, external_ids, cited_by, percentile,
        is_preprint, is_erratum. Returns (paper_id, created)."""
        doi = norm_doi(rec.get("doi"))
        allds = [d for d in {norm_doi(x) for x in (rec.get("dois_all") or [])} | {doi} if d]
        key = doi or rec.get("key") or ("nodoi:" + title_hash(rec.get("title")))
        doc_type = rec.get("doc_type") or norm_doc_type(rec.get("type"), rec.get("is_preprint"))
        ab = normalize_abstract(_scalar(rec.get("abstract")) or "")
        with self.lock:
            pid = None
            for d in [doi] + allds:
                pid = self.find_id(doi=d)
                if pid:
                    break
            if pid is None:
                pid = self.find_id(key=key)
            created = pid is None
            if created:
                cols = {"key": key, "doi": doi, "title": clean_title(rec.get("title")),
                        "authors": _j([clean_name(a) for a in (rec.get("authors") or []) if a and clean_name(a)]),
                        "authors_detail": _j(rec.get("authors_detail") or []),
                        "year": _year(rec.get("year")), "journal": clean_title(_scalar(rec.get("journal"))) or None,
                        "publisher": _scalar(rec.get("publisher")), "type": _scalar(rec.get("type")),
                        "doc_type": doc_type, "abstract": ab or None,
                        "abstract_source": rec.get("abstract_source") if ab else None,
                        "keywords": _j(_keywords(rec.get("keywords"))), "link": _scalar(rec.get("link")),
                        "databases": _j(sorted(set(rec.get("databases") or []))),
                        "external_ids": _j(rec.get("external_ids") or {}), "cited_by": rec.get("cited_by"),
                        "percentile": rec.get("percentile"), "is_preprint": int(bool(rec.get("is_preprint"))),
                        "is_erratum": int(bool(rec.get("is_erratum"))), "date_added": rec.get("date_added") or today(),
                        "updated_at": now_iso()}
                if explicit_id is not None:
                    cols["id"] = explicit_id
                names = ", ".join(cols)
                qs = ", ".join("?" for _ in cols)
                cur = self.x(f"INSERT INTO papers({names}) VALUES ({qs})", tuple(cols.values()))
                pid = cur.lastrowid if explicit_id is None else explicit_id
            else:
                old = self.get(pid)
                upd = {}
                dbs = sorted(set(old["databases"]) | set(rec.get("databases") or []))
                if dbs != old["databases"]:
                    upd["databases"] = dbs
                for k, v in (("title", clean_title(rec.get("title"))), ("year", _year(rec.get("year"))),
                             ("journal", clean_title(_scalar(rec.get("journal"))) or None),
                             ("publisher", _scalar(rec.get("publisher"))), ("type", _scalar(rec.get("type"))),
                             ("link", _scalar(rec.get("link"))), ("cited_by", rec.get("cited_by")),
                             ("percentile", rec.get("percentile"))):
                    if v not in (None, "") and old.get(k) in (None, ""):
                        upd[k] = v
                if not old.get("doc_type") or (old.get("doc_type") in ("other", "article") and doc_type not in ("other", "article")):
                    if doc_type and doc_type != old.get("doc_type"):
                        upd["doc_type"] = doc_type
                if len(ab) > len(old.get("abstract") or "") and not str(old.get("abstract_source") or "").startswith("pdf"):
                    upd["abstract"] = ab
                    upd["abstract_source"] = rec.get("abstract_source")
                if not old["authors"] and rec.get("authors"):
                    upd["authors"] = [clean_name(a) for a in rec["authors"] if a and clean_name(a)]
                if not old.get("authors_detail") and rec.get("authors_detail"):
                    upd["authors_detail"] = rec["authors_detail"]
                kw = _keywords((old.get("keywords") or []) + _keywords(rec.get("keywords")))
                if kw != (old.get("keywords") or []):
                    upd["keywords"] = kw
                ext = dict(old["external_ids"])
                for k, v in (rec.get("external_ids") or {}).items():
                    if v and not ext.get(k):
                        ext[k] = v
                if ext != old["external_ids"]:
                    upd["external_ids"] = ext
                if doi and not old.get("doi") and not self.find_id(doi=doi):
                    upd["doi"] = doi
                if upd:
                    self.set(pid, **upd)
            self.add_dois(pid, allds)
            self.set_topic(pid, topic)
            return pid, created

    # ------------------------------------------------------------ queries
    def topic_rows(self, topic, extra_where="", args=()):
        sql = ("SELECT p.*, t.relevance AS t_relevance, t.relevance_note AS t_relevance_note, "
               "t.relevance_method AS t_relevance_method, t.in_scope AS t_in_scope, t.path AS t_path, "
               "t.si_paths AS t_si_paths, t.date_added AS t_date_added "
               "FROM papers p JOIN paper_topics t ON t.paper_id = p.id WHERE t.topic=? " + extra_where)
        return [self.row(r) for r in self.q(sql, (topic, *args))]

    def topic_block(self, topic, after=0, limit=20000, extra_where="", args=()):
        """The topic's papers with id > after, in id order, `limit` at a time: keyset paging that stays fast on a topic
        of millions (walks paper_topics in id order instead of sorting the whole topic for every block)."""
        sql = ("SELECT p.*, t.relevance AS t_relevance, t.relevance_note AS t_relevance_note, "
               "t.relevance_method AS t_relevance_method, t.in_scope AS t_in_scope, t.path AS t_path, "
               "t.si_paths AS t_si_paths, t.date_added AS t_date_added, t.rowid AS t_rowid "
               "FROM paper_topics t CROSS JOIN papers p ON p.id = t.paper_id WHERE +t.topic=? AND t.paper_id > ? "
               + extra_where + " ORDER BY t.paper_id LIMIT ?")
        return [self.row(r) for r in self.q(sql, (topic, after, *args, limit))]

    def iter_topic(self, topic, extra_where="", args=(), chunk=20000):
        """Blocks of the topic's papers (lists of rows, `chunk` at a time, id order) — never the whole topic in memory."""
        last = 0
        while True:
            rows = self.topic_block(topic, last, chunk, extra_where, args)
            if not rows:
                return
            last = rows[-1]["id"]
            yield rows

    def counts(self, topic):
        rows = self.q("SELECT p.access_type, t.in_scope, p.downloaded, p.dl_status, p.is_erratum, COUNT(*) "
                      "FROM papers p JOIN paper_topics t ON t.paper_id=p.id WHERE t.topic=? "
                      "GROUP BY 1,2,3,4,5", (topic,))
        return [tuple(r) for r in rows]

    def next_id(self):
        r = self.q("SELECT COALESCE(MAX(id), 0) + 1 FROM papers")
        return r[0][0]

    def all_topics(self):
        return [r[0] for r in self.q("SELECT DISTINCT topic FROM paper_topics ORDER BY topic")]

    # ------------------------------------------------------------ curation results
    def set_extraction(self, pid, topic, kg, status, schema_version=None, nodes=None, edges=None, date=None, note=None):
        self.x("INSERT OR REPLACE INTO extractions VALUES (?,?,?,?,?,?,?,?,?)",
               (pid, topic, kg, status, schema_version, nodes, edges, date or today(), note))

    def sync_curation(self):
        """Pick up curation results: .scripts/<topic>/kg/<name>/extraction_status.jsonl (one JSON object per
        paper: paper_id, topic, kg, status, schema_version, nodes, edges, date, note, abstract). A later line wins.
        An abstract read from the PDF fills a paper that has none. Returns the number of status rows applied."""
        n, filled = 0, []
        for f in sorted(self.proj.scr.glob("*/kg/*/extraction_status.jsonl")):
            latest = {}
            for r in jsonl_iter(f):
                try:
                    latest[(int(r["paper_id"]), r.get("topic") or f.parts[-4], r.get("kg") or f.parent.name)] = r
                except (KeyError, TypeError, ValueError):
                    continue
            if not latest:
                continue
            with self.tx():
                for (pid, topic, kg), r in latest.items():
                    if not self.q("SELECT 1 FROM papers WHERE id=?", (pid,)):
                        continue
                    self.set_extraction(pid, topic, kg, str(r.get("status") or "extracted"), r.get("schema_version"),
                                        r.get("nodes"), r.get("edges"), r.get("date"), r.get("note"))
                    ab = (r.get("abstract") or "").strip()
                    if ab and len(ab) > 80:
                        cur = self.q("SELECT abstract FROM papers WHERE id=?", (pid,))
                        if cur and len(cur[0][0] or "") < 80:
                            self.set(pid, abstract=ab, abstract_source="pdf (curation)")
                            filled.append(pid)
                    n += 1
        if filled:   # new abstracts: recompute vocabulary topics (Claude/API/manual topics are kept)
            from _topics import Vocab, apply_vocab
            apply_vocab(self, Vocab(self.proj), [self.get(i) for i in filled])
        return n

    # ------------------------------------------------------------ exports
    def export_progress(self, topics=None, db=True):
        """A progress refresh during a long run (downloads): skipped until at least a minute — and 20 times what the
        last refresh took — has passed. It publishes the papers changed since the last one, so the database keeps up
        with a run that lasts hours."""
        import time
        now = time.time()
        if now - getattr(self, "_progress_at", 0) < max(60, 20 * getattr(self, "_progress_took", 0)):
            return None
        n = self.export(topics=topics, db=db)
        self._progress_at, self._progress_took = time.time(), time.time() - now
        return n

    def export(self, topics=None, db=True, csv=False, rebuild=False):
        """Publish the changed papers into publications/papers.db (db=True; rebuild=True rebuilds it, keeping its
        history) and, only with csv=True, write the topic index CSVs (the given topics, else all). Returns the
        number of papers synced into the database, or of index rows when CSVs were written."""
        try:
            self.sync_curation()
        except Exception as e:  # a malformed status file must never block an export
            log(f"curation status sync skipped: {e}")
        from _topics import Vocab
        vocab = Vocab(self.proj)
        n = 0
        if db:
            self.last_publish = self.publish_db(vocab, topics=topics, rebuild=rebuild)
            n = (self.last_publish or {}).get("synced", 0)
        if csv:
            n = 0
            for t in (topics or self.all_topics()):
                n += self.write_index(t, vocab)
        return n

    def export_csv(self, *_a, **_k):  # v2 name kept for callers
        return self.export()

    def _subject_map(self):
        out = {}
        for r in self.q("SELECT paper_id, term, kind, rank FROM paper_subjects ORDER BY paper_id, kind DESC, rank"):
            d = out.setdefault(r[0], {"main": [], "related": []})
            d["main" if r[2] == "main" else "related"].append(r[1])
        return out

    def _extraction_map(self, topic=None):
        out = {}
        sql = "SELECT paper_id, topic, kg, status, date, note FROM extractions"
        for r in self.q(sql + (" WHERE topic=?" if topic else ""), ((topic,) if topic else ())):
            out.setdefault(r[0], []).append(dict(r))
        return out

    def write_index(self, topic, vocab):
        """publications/<topic>/index/: one CSV per access type, merged.csv (everything in scope or unscreened) and
        excluded.csv (screened out, not research articles, retracted). UTF-8 with BOM so Excel shows accents.
        Rows stream from the ledger in index order (relevance, year, citations, title), so a topic of millions of
        papers never sits in memory. Excel opens at most 1,048,576 rows: bigger files are for papers.db / pandas."""
        subj = self._subject_map()
        ext = self._extraction_map(topic)
        si_n, fam, pre = self._si_link_counts(), self._family_map(), self._preprint_alias_map()
        topics_by_paper = {}
        for r in self.q("SELECT paper_id, topic FROM paper_topics ORDER BY topic"):
            topics_by_paper.setdefault(r[0], []).append(r[1])
        d = self.proj.index_dir(topic)
        d.mkdir(parents=True, exist_ok=True)
        names = ACCESS_TYPES + ["merged", "excluded"]
        sql = ("SELECT p.*, t.relevance AS t_relevance, t.relevance_note AS t_relevance_note, "
               "t.relevance_method AS t_relevance_method, t.in_scope AS t_in_scope, t.path AS t_path, "
               "t.si_paths AS t_si_paths, t.date_added AS t_date_added "
               "FROM papers p JOIN paper_topics t ON t.paper_id = p.id WHERE t.topic=? "
               "ORDER BY COALESCE(t.relevance, 3) DESC, COALESCE(p.year, 0) DESC, COALESCE(p.cited_by, 0) DESC, "
               "lower(COALESCE(p.title, ''))")
        n_keep = 0
        with file_lock(self.proj.scr / f"index_{topic}"):   # lock file lives in .scripts/, not next to the CSVs
            tmps = {n: self.proj.tmp / f"{topic}.{n}.csv.tmp" for n in names}
            fhs = {n: open(tmps[n], "w", encoding="utf-8-sig", newline="") for n in names}
            try:
                ws = {n: csv.DictWriter(fh, fieldnames=INDEX_COLUMNS, quoting=csv.QUOTE_MINIMAL) for n, fh in fhs.items()}
                for w in ws.values():
                    w.writeheader()
                with self.lock:
                    cur = self.db.execute(sql, (topic,))
                    for raw in cur:
                        p = self.row(raw)
                        p["_si_links"], p["_family"] = si_n.get(p["id"], 0), fam.get(p["id"])
                        p["_aliases"] = pre.get(p["id"], [])
                        line = render_row(p, topic, subj.get(p["id"]), ext.get(p["id"]),
                                          topics_by_paper.get(p["id"], []), vocab)
                        if p.get("t_in_scope") == 0 or p.get("is_erratum") or p.get("retracted"):
                            ws["excluded"].writerow(line)
                            continue
                        ws["merged"].writerow(line)
                        n_keep += 1
                        if line["Access type"] in ws:
                            ws[line["Access type"]].writerow(line)
                for fh in fhs.values():
                    fh.flush()
                    os.fsync(fh.fileno())
            finally:
                for fh in fhs.values():
                    fh.close()
            for n in names:
                os.replace(tmps[n], d / f"{n}.csv")
        return n_keep

    def publish_db(self, vocab, topics=None, rebuild=False):
        from _publish import build_published_db, sync_published_db
        from _common import file_lock
        if rebuild:
            with file_lock(self.proj.scr / "publish"):
                return build_published_db(self, vocab, note="full rebuild on request (export.py --rebuild)")
        return sync_published_db(self, vocab, topics=topics)


class _Tx:
    def __init__(self, led):
        self.led = led

    def __enter__(self):
        self.led.lock.acquire()
        self.led.db.execute("BEGIN IMMEDIATE")
        return self.led

    def __exit__(self, et, ev, tb):
        try:
            self.led.db.execute("COMMIT" if et is None else "ROLLBACK")
        finally:
            self.led.lock.release()
        return False


# ---------------------------------------------------------------- row rendering (index CSVs + published DB)
def fmt_authors(names, cap=MAX_AUTHORS):
    names = [n for n in names or [] if n]
    if cap and len(names) > cap:
        return "; ".join(names[:cap]) + "; et al."
    return "; ".join(names)


def identifier(p):
    """DOI, else the best other identifier (patent number, arXiv id, OSTI id ...)."""
    if p.get("doi"):
        return p["doi"]
    ext = p.get("external_ids") or {}
    for k, pre in (("patent", ""), ("arxiv", "arXiv:"), ("osti", "OSTI:"), ("pmcid", ""), ("hal", "HAL:"),
                   ("ntrs", "NTRS:"), ("lens", "Lens:"), ("zenodo", "Zenodo:"), ("jstage", "J-STAGE:"),
                   ("cinii", "CiNii:"), ("eric", "ERIC:"), ("core", "CORE:"), ("openalex", "")):
        if ext.get(k):
            v = str(ext[k])
            return pre + (v.rsplit("/", 1)[-1] if k == "openalex" else v)
    return ""


def url_of(p):
    if p.get("doi"):
        return f"https://doi.org/{p['doi']}"
    return p.get("link") or ""


def license_cells(p):
    """(License, License URL, License source) — exact label with version when known."""
    label = p.get("license_label")
    url = p.get("license_url") or ""
    if not label:
        tok = p.get("license")
        if tok:
            label = license_detail(None, tok)[0] or LICENSE_LABEL.get(tok, tok)
        elif p.get("access_type") == "Paywalled":
            label = "Subscription (no open license)"
    src = p.get("license_source") or EVIDENCE_LABEL.get(p.get("license_evidence") or "", "")
    return label or "", url, src


def retracted_cell(p):
    """Yes (the paper is retracted) · Retraction notice (this record retracts another paper) · No."""
    if p.get("retracted"):
        return "Yes"
    return "Retraction notice" if (p.get("external_ids") or {}).get("retraction_of") else "No"


def notes_for(p, topic=None):
    notes = []
    ext = p.get("external_ids") or {}
    links = lambda v: ", ".join(f"https://doi.org/{x}" for x in str(v or "").split("; ") if x)
    if p.get("retracted"):
        notes.append("RETRACTED" + (f" (notice: {links(ext['retraction_notice'])})" if ext.get("retraction_notice") else ""))
    elif ext.get("retraction_of"):
        notes.append(f"Retraction notice of {links(ext['retraction_of'])}")
    if p.get("is_erratum"):
        notes.append("Not a research article (erratum, correction, peer-review report or cover art)")
    if p.get("t_in_scope") == 0:
        why = (p.get("t_relevance_note") or "").strip()
        notes.append(f"Out of scope: {why}" if why else "Out of scope")
    if (p.get("doc_type") or "") in NOT_DOWNLOADED_TYPES:
        notes.append(f"{p['doc_type'].capitalize()} — indexed, not downloaded")
    elif not p.get("downloaded") and p.get("dl_note"):
        notes.append(p["dl_note"])
    v = p.get("version")
    if p.get("downloaded") and v in ("acceptedVersion", "submittedVersion"):
        notes.append("Copy is the accepted manuscript" if v == "acceptedVersion" else "Copy is a preprint")
    if p.get("access_basis") == "pdf_differs":
        notes.append("License printed in the PDF differs from the metadata")
    if not (p.get("abstract") or "").strip():
        notes.append("No abstract in the metadata")
    if p.get("_family"):
        notes.append("Same invention also published as " + ", ".join(sorted(x for x in p["_family"] if x)))
    return " · ".join(notes)


def extracted_cell(exts):
    if not exts:
        return "No"
    parts = []
    for e in sorted(exts, key=lambda e: (e.get("kg") or "")):
        st = (e.get("status") or "").lower()
        lab = {"extracted": "Yes", "approved": "Yes", "rejected": "Rejected", "failed": "Failed",
               "no_data": "No data"}.get(st, st.capitalize() or "Yes")
        parts.append(f"{lab} — {e.get('kg')} ({e.get('date') or ''})".replace(" ()", ""))
    return "; ".join(parts)


def downloaded_cell(p):
    if (p.get("doc_type") or "") in NOT_DOWNLOADED_TYPES:
        return "n/a"
    return "Yes" if p.get("downloaded") else "No"


def si_cell(p):
    """Downloaded papers: whether their SI was fetched. Others: SI deposits the search found for them, if any."""
    n = p.get("_si_links") or 0
    if not p.get("downloaded"):
        return f"Available ({n} deposit{'s' if n != 1 else ''})" if n else ""
    st = p.get("si_status")
    return {"found": "Yes", "not_found": "No" if not n else f"No ({n} deposit{'s' if n != 1 else ''} known)",
            "queued_paywalled": "Queued"}.get(st, "")


def render_row(p, topic, subj, exts, topics, vocab):
    subj = subj or {"main": [], "related": []}
    main = [vocab.label(t) for t in subj["main"]] + ["", "", ""]
    lic, lic_url, lic_src = license_cells(p)
    dbs = [SOURCE_LABEL.get(d, d) for d in p.get("databases") or []]
    ver = p.get("version") if p.get("downloaded") else next(
        (v.get("version") for v in p.get("versions") or [] if v.get("access") == p.get("access_type") and v.get("version")), None)
    return {
        "ID": p["id"],
        "Title": p.get("title") or "",
        "Authors": fmt_authors(p.get("authors")),
        "Year": p.get("year") or "",
        "Venue": p.get("journal") or "",
        "Publisher": p.get("publisher") or "",
        "Doc type": p.get("doc_type") or norm_doc_type(p.get("type"), p.get("is_preprint")),
        "Retracted": retracted_cell(p),
        "DOI/ID": identifier(p),
        "URL": url_of(p),
        "Preprint link": "; ".join(preprint_links(p, p.get("_aliases") or ())),
        "Abstract": export_abstract(p.get("abstract") or ""),   # clean even when stored by an older version
        "Keywords": "; ".join(p.get("keywords") or []),
        "Topic A": main[0], "Topic B": main[1], "Topic C": main[2],
        "Related topics": "; ".join(vocab.label(t) for t in subj["related"]),
        "Relevance": "" if p.get("t_relevance") is None else p["t_relevance"],
        "Relevance note": p.get("t_relevance_note") or "",
        "Access type": p.get("access_type") or "",
        "License": lic, "License URL": lic_url, "License source": lic_src,
        "Version": VERSION_LABEL.get(ver or "", ver or ""),
        "Database": "; ".join(dbs),
        "Index": "; ".join(topics),
        "Citations": "" if p.get("cited_by") is None else p["cited_by"],
        "Downloaded": downloaded_cell(p),
        "Path": p.get("t_path") or "",
        "SI": si_cell(p),
        "Extracted": extracted_cell(exts),
        "Notes": notes_for(p, topic),
        "Date added": (p.get("t_date_added") or p.get("date_added") or "")[:10],
        "Last checked": p.get("last_checked") or "",
    }


def access_counts(rows):
    out = {a: 0 for a in ACCESS_TYPES}
    for r in rows:
        if r.get("access_type") in out:
            out[r["access_type"]] += 1
    return dict(sorted(out.items(), key=lambda kv: access_rank(kv[0])))
