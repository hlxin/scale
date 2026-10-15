"""Shared helpers for the data-curation scripts (library module — not run directly).

One run = one knowledge graph built from one topic's papers with one given schema:
  publications/<topic>/kg/<name>/      deliverables: schema.json, graph.json, manifest.json, figures/, tables/, views/,
                                       answers/, README.md
  .scripts/<topic>/kg/<name>/          working files: worklist.jsonl, fragments/, reviews/, batches/, state.json,
                                       validation_report.jsonl, errors.jsonl, accepted.txt, alias_candidates.json,
                                       hubs.json, alias_map.json, index.sqlite, extraction_status.jsonl
The papers come from paper-acquisition: publications/papers.db (or publications/<topic>/index/merged.csv).
"""
import csv
import datetime as _dt
import json
import os
import re
import sqlite3
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
FINAL = {"extracted", "rejected", "failed", "no_data"}


def now_iso():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today():
    return _dt.date.today().isoformat()


def slug(text, maxlen=50):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:maxlen].strip("-") or "kg"


def read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8-sig"))


def write_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def read_jsonl(path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def append_jsonl(path, recs):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        for r in recs if isinstance(recs, list) else [recs]:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


class Run:
    def __init__(self, root, topic, name):
        self.root = Path(root or os.getcwd()).resolve()
        self.topic, self.name = topic, name
        self.out = self.root / "publications" / topic / "kg" / name
        self.work = self.root / ".scripts" / topic / "kg" / name
        self.schema = self.out / "schema.json"
        self.graph = self.out / "graph.json"
        self.figures = self.out / "figures"
        self.frag = self.work / "fragments"
        self.reviews = self.work / "reviews"
        self.batches = self.work / "batches"
        self.state_path = self.work / "state.json"
        self.worklist = self.work / "worklist.jsonl"
        self.status_log = self.work / "extraction_status.jsonl"
        self.vreport = self.work / "validation_report.jsonl"
        self.errors = self.work / "errors.jsonl"
        self.accepted = self.work / "accepted.txt"
        self.index_db = self.work / "index.sqlite"

    def ensure(self):
        for d in (self.out, self.figures, self.out / "tables", self.out / "views", self.out / "answers", self.frag,
                  self.frag / "superseded", self.frag / "rejected", self.reviews, self.batches):
            d.mkdir(parents=True, exist_ok=True)
        return self

    def state(self):
        return read_json(self.state_path, {}) or {}

    def update_state(self, **kw):
        st = self.state()
        for k, v in kw.items():
            if isinstance(v, dict) and isinstance(st.get(k), dict):
                st[k].update(v)
            else:
                st[k] = v
        st["updated_at"] = now_iso()
        write_json(self.state_path, st)
        return st

    def rel(self, p):
        try:
            return str(Path(p).resolve().relative_to(self.root))
        except ValueError:
            return str(p)

    def papers(self):
        return {int(r["paper_id"]): r for r in read_jsonl(self.worklist)}

    def statuses(self):
        """Latest status per paper from extraction_status.jsonl."""
        out = {}
        for r in read_jsonl(self.status_log):
            try:
                out[int(r["paper_id"])] = r
            except (KeyError, TypeError, ValueError):
                pass
        return out

    def fragment(self, pid):
        return self.frag / f"paper_{pid}.json"

    def review(self, pid):
        return self.reviews / f"paper_{pid}.json"


def add_root_arg(ap):
    ap.add_argument("--project", default=None, help="project root (default: current directory)")
    return ap


# ---------------------------------------------------------------- the paper index (paper-acquisition)
def topic_papers(root, topic):
    """Papers of a topic as dicts (from publications/papers.db, else the topic's merged.csv)."""
    root = Path(root)
    db = root / "publications" / "papers.db"
    if db.exists():
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute(
            "SELECT p.*, c.relevance, c.in_scope, c.pdf_path, c.si_paths, c.date_added AS added_to_collection "
            "FROM paper_collections c JOIN papers p ON p.id = c.paper_id WHERE c.collection = ?", (topic,))]
        con.close()
        for r in rows:
            r["si"] = json.loads(r.get("si_paths") or "[]")
        return rows, "papers.db"
    csvp = root / "publications" / topic / "index" / "merged.csv"
    if not csvp.exists():
        return [], None
    rows = []
    with open(csvp, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            rows.append({"id": int(r["ID"]), "title": r["Title"], "doi": r["DOI/ID"] if r["DOI/ID"].startswith("10.") else None,
                         "identifier": r["DOI/ID"], "year": int(r["Year"]) if r["Year"].isdigit() else None,
                         "venue": r["Venue"], "doc_type": r["Doc type"], "access_type": r["Access type"],
                         "license": r["License"], "abstract": r["Abstract"], "topic_a": r["Topic A"],
                         "topic_b": r["Topic B"], "topic_c": r["Topic C"], "authors": r["Authors"],
                         "relevance": int(r["Relevance"]) if r["Relevance"].isdigit() else None, "in_scope": 1,
                         "pdf_path": r["Path"] or None, "si": [], "pages": None, "url": r["URL"]})
    return rows, "merged.csv"


def publication_meta(root):
    """doi/id -> Publication properties for the merge (from papers.db)."""
    db = Path(root) / "publications" / "papers.db"
    out = {}
    if not db.exists():
        return out
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    for r in con.execute("SELECT id, doi, identifier, title, year, venue, authors, doc_type, access_type, license, url, "
                         "topic_a, topic_b, topic_c, citations FROM papers"):
        d = dict(r)
        meta = {"title": d["title"], "year": d["year"], "journal": d["venue"], "venue": d["venue"],
                "authors": [a.strip() for a in (d["authors"] or "").split(";") if a.strip()][:10],
                "record_type": d["doc_type"], "access": d["access_type"], "license": d["license"], "url": d["url"],
                "topics": [t for t in (d["topic_a"], d["topic_b"], d["topic_c"]) if t], "citations": d["citations"],
                "internal_id": str(d["id"])}
        out[str(d["id"])] = dict(meta, doi=d["doi"])
        if d["doi"]:
            out[d["doi"].lower()] = dict(meta, doi=d["doi"])
    con.close()
    return out
