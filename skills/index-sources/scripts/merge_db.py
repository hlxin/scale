"""Merge another copy of the paper database into this project's: what the other copy found, checked or downloaded
joins this one, and both histories are kept. The copies converge: share the merged papers.db afterwards.

  python3 -I merge_db.py --from <their papers.db> [--files <their project folder>] [--dry-run]

When two people update separate copies of papers.db (Update, downloads, screening, curation), one of them runs this
with the other's papers.db. Only that file is read (and, with --files, the other project's PDFs and SI); nothing in
the other copy changes. Run it again after either copy moves on: a merge that finds nothing new changes nothing.

Papers are matched by identity, never by ID (each copy numbers its new papers on its own): the same key (canonical
DOI, patent number or title hash) or any DOI or patent alias the two records share. A paper only the other copy has
is added under a new ID here. When one paper of the other copy matches two here, the other copy merged them, and they
are merged here too (dedup's merge: files move with them). Values are merged so that nothing is lost and nothing this
copy holds is removed:

  bibliographic fields   kept here; filled from the other copy where empty here (an abstract also where this one is
                         shorter than 80 characters); citations: the larger count
  retraction, erratum    either copy's flag holds
  access and licence     a verdict read from a downloaded PDF wins over metadata; otherwise the more recently
                         checked record's (last_checked)
  known copies, sources, identifiers, DOI aliases, SI links: the union
  downloads              this copy's files stay this copy's: a paper downloaded only in the other copy stays
                         undownloaded here, and its download URL joins the known copies (download_open.py fetches it
                         from there), unless --files gives the other project's folder: its PDF and SI are then copied
                         in under this copy's ID
  topics and relevance   the union of topics; in a topic both copies hold, the better screening method's decision
                         (manual > claude > api > keywords > none)
  Topic A/B/C            the better method's (manual > claude > api > vocab)
  curation results       the union; for the same graph, the later date
  searches and decisions the topics' search runs, queries, merge decisions and project terms: the union, so Update
                         knows every window either copy searched
  history                the other copy's runs since the copies parted are added with their changes, and the merge
                         is a run of its own
Afterwards run dedup.py --apply (automatic): it merges papers the two copies indexed under different keys.
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import Project, add_project_arg, die, json_write_atomic, log, now_iso  # noqa: E402
from _ledger import JSON_COLS, Ledger  # noqa: E402
from _vectors import after_step  # noqa: E402
from _publish import COPIED, _tables, has_state, unpack_state  # noqa: E402
from _topics import METHOD_RANK  # noqa: E402

SCREEN_RANK = {"none": 1, "keywords": 2, "api": 3, "claude": 4, "manual": 5}
BIB = ("title", "authors", "authors_detail", "year", "journal", "publisher", "type", "doc_type", "link", "keywords",
       "percentile")
ACCESS = ("access_type", "access_basis", "license", "license_evidence", "oa_status", "license_label", "license_url",
          "license_source")
DOWNLOAD = ("downloaded", "version", "download_source", "download_url", "download_date", "sha1", "page_count",
            "dl_status", "dl_note", "si_status", "si_files")
CHUNK = 5000


def _empty(v):
    return v is None or v == "" or v == [] or v == {}


def _screen_rank(m):
    return SCREEN_RANK.get(str(m or "").split(":", 1)[0].lower(), 0)


def _pdf_based(p):
    return p.get("access_basis") in ("pdf", "pdf_differs")


def _vkey(v):
    return v.get("pdf_url") or v.get("url")


class Other:
    """The other copy, read through its papers.db alone (the public tables and the working state)."""

    def __init__(self, path):
        if not has_state(path):
            die(f"{path} is not an evolving papers.db (paper-acquisition 3.4 or later, now index-sources); nothing to merge from")
        self.path = Path(path).resolve()
        self.con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        self.con.row_factory = sqlite3.Row
        self.tables = _tables(self.con)

    def ids(self):
        last = 0
        while True:
            ids = [r[0] for r in self.con.execute("SELECT id FROM papers WHERE id > ? ORDER BY id LIMIT ?", (last, CHUNK))]
            if not ids:
                return
            last = ids[-1]
            yield ids

    def _q(self, sql, ids):
        return self.con.execute(sql.format(",".join("?" * len(ids))), ids).fetchall()

    def papers(self, ids):
        out = {}
        for r in self._q("SELECT p.*, s.state FROM papers p JOIN _paper_state s ON s.paper_id = p.id "
                         "WHERE p.id IN ({})", ids):
            st = unpack_state(r["state"])
            row = {k: v for k, v in st.items() if not k.startswith("_")}
            for pub_col, led_col in COPIED.items():
                row[led_col] = r[pub_col]
            row["abstract"] = st["abstract"] if "abstract" in st else r["abstract"]
            for k in JSON_COLS - {"si_paths"}:
                row.setdefault(k, {} if k == "external_ids" else [])
            row.setdefault("extracted", "No")
            row["_aliases"], row["_si_links"] = st.get("_aliases") or [], st.get("_si_links") or []
            out[r["id"]] = row
        return out

    def by_paper(self, sql, ids):
        out = {}
        for r in self._q(sql, ids):
            out.setdefault(r[0], []).append(dict(r))
        return out

    def fingerprints(self, ids, cols=None):
        """What a paper is in this copy, to tell untouched papers from changed ones quickly."""
        return _fingerprints(self.con, ids, cols)


def _fingerprints(con, ids, cols=None):
    """cols: the papers columns both copies have (a copy of an older format lacks the newer ones)."""
    marks = ",".join("?" * len(ids))
    fp = {r[0]: [tuple(r)] for r in con.execute(f"SELECT {', '.join(cols) if cols else '*'} FROM papers "
                                                f"WHERE id IN ({marks})", ids)}
    for sql in (f"SELECT paper_id, state FROM _paper_state WHERE paper_id IN ({marks})",
                f"SELECT * FROM paper_collections WHERE paper_id IN ({marks}) ORDER BY paper_id, collection",
                f"SELECT * FROM paper_subjects WHERE paper_id IN ({marks}) ORDER BY paper_id, term",
                f"SELECT * FROM extractions WHERE paper_id IN ({marks}) ORDER BY paper_id, collection, kg"):
        for r in con.execute(sql, ids):
            if r[0] in fp:
                fp[r[0]].append(tuple(r))
    return fp


class Merge:
    def __init__(self, proj, led, other, files=None, dry=False):
        self.proj, self.led, self.other, self.dry = proj, led, other, dry
        self.files = Path(files).resolve() if files else None
        self.cols = [r[1] for r in led.q("PRAGMA table_info(papers)")]
        self.id_map = {}
        self.n = Counter()
        self.empty_here = not led.q("SELECT 1 FROM papers LIMIT 1")

    # ---------------------------------------------------------------- matching
    def match(self, o):
        found = set()
        for a in dict.fromkeys([o.get("key"), o.get("doi")] + list(o["_aliases"])):
            if a:
                found |= {r[0] for r in self.led.q("SELECT paper_id FROM dois WHERE doi=?", (a,))}
        found |= {r[0] for r in self.led.q("SELECT id FROM papers WHERE key=?", (o.get("key"),))}
        if o.get("doi"):
            found |= {r[0] for r in self.led.q("SELECT id FROM papers WHERE doi=?", (o["doi"],))}
        return found

    def fold(self, ids, o):
        """The other copy holds as one paper what this copy holds as several: merge them here too."""
        import dedup
        keyed = [i for i in ids if (self.led.get(i) or {}).get("key") == o.get("key")]
        keep = keyed[0] if keyed else min(ids)
        for x in sorted(i for i in ids if i != keep):
            if not self.dry:
                dedup.merge(self.proj, self.led, self.led.get(keep), self.led.get(x), "merged_copy")
            self.n["merged_here"] += 1
        return keep

    # ---------------------------------------------------------------- one paper
    def fields(self, L, o):
        upd = {}
        for f in BIB:
            if _empty(L.get(f)) and not _empty(o.get(f)):
                upd[f] = o[f]
        la, oa = L.get("abstract") or "", o.get("abstract") or ""
        if len(la) < 80 and len(oa) > len(la):
            upd["abstract"], upd["abstract_source"] = oa, o.get("abstract_source")
        if (o.get("cited_by") or 0) > (L.get("cited_by") or 0):
            upd["cited_by"] = o["cited_by"]
        for f in ("retracted", "is_erratum"):
            if o.get(f) and not L.get(f):
                upd[f] = o[f]
        newer = (o.get("last_checked") or "") > (L.get("last_checked") or "")
        if o.get("is_preprint") != L.get("is_preprint") and newer:
            upd["is_preprint"] = o.get("is_preprint")
        take = (_pdf_based(o) and not _pdf_based(L)) or (_pdf_based(o) == _pdf_based(L) and newer) or \
            (_empty(L.get("access_type")) and not _empty(o.get("access_type")))
        if take:
            upd.update({f: o.get(f) for f in ACCESS if o.get(f) != L.get(f)})
        if (o.get("last_checked") or "") > (L.get("last_checked") or ""):
            upd["last_checked"] = o["last_checked"]
        versions = list(L.get("versions") or [])
        seen = {_vkey(v) for v in versions}
        extra = [v for v in o.get("versions") or [] if _vkey(v) not in seen]
        if o.get("downloaded") and not L.get("downloaded") and o.get("download_url") and o["download_url"] not in seen:
            extra.append({"url": o["download_url"], "pdf_url": o["download_url"], "access": o.get("access_type"),
                          "version": o.get("version"), "src": "merged copy"})
        if extra:
            upd["versions"] = versions + [v for i, v in enumerate(extra) if _vkey(v) not in {_vkey(x) for x in extra[:i]}]
        dbs = list(L.get("databases") or []) + [d for d in o.get("databases") or [] if d not in (L.get("databases") or [])]
        if dbs != list(L.get("databases") or []):
            upd["databases"] = dbs
        ext = {**(o.get("external_ids") or {}), **{k: v for k, v in (L.get("external_ids") or {}).items() if v}}
        if ext != (L.get("external_ids") or {}):
            upd["external_ids"] = ext
        if (L.get("extracted") or "No") == "No" and (o.get("extracted") or "No") != "No":
            upd["extracted"] = o["extracted"]
        if o.get("date_added") and (not L.get("date_added") or o["date_added"] < L["date_added"]):
            upd["date_added"] = o["date_added"]
        return upd

    def related(self, lid, o, otopics, osubj, oext):
        led, n = self.led, 0
        aliases = [a for a in dict.fromkeys(list(o["_aliases"]) + [o.get("key"), o.get("doi")]) if a]
        have = set(led.aliases(lid))
        new_aliases = [a for a in aliases if a not in have and not led.q("SELECT 1 FROM dois WHERE doi=?", (a,))]
        links = [s for s in o["_si_links"] if not led.q("SELECT 1 FROM si_links WHERE parent_doi=? AND si_doi=?",
                                                          (s["parent_doi"], s["si_doi"]))]
        local_t = {t["topic"]: t for t in led.topics_of(lid)}
        t_new = [t for t in otopics if t["collection"] not in local_t]
        t_better = [t for t in otopics if t["collection"] in local_t and
                    _screen_rank(t.get("relevance_method")) > _screen_rank(local_t[t["collection"]].get("relevance_method"))]
        cur = led.q("SELECT method FROM paper_subjects WHERE paper_id=? AND kind='main' LIMIT 1", (lid,))
        omain = [s for s in osubj if s["kind"] == "main"]
        subj = bool(osubj) and (not led.q("SELECT 1 FROM paper_subjects WHERE paper_id=?", (lid,)) or (
            omain and METHOD_RANK.get(omain[0].get("method") or "vocab", 0) >
            METHOD_RANK.get((cur[0][0] if cur else None) or "vocab", 0)))
        lext = {(e["topic"], e["kg"]): e for e in led.q("SELECT * FROM extractions WHERE paper_id=?", (lid,))}
        e_new = [e for e in oext if (e["collection"], e["kg"]) not in lext or
                 (e.get("date") or "") > (lext[(e["collection"], e["kg"])]["date"] or "")]
        n = len(new_aliases) + len(links) + len(t_new) + len(t_better) + int(bool(subj)) + len(e_new)
        if self.dry or not n:
            return n
        led.add_dois(lid, new_aliases)
        for s in links:
            led.x("INSERT OR IGNORE INTO si_links VALUES (?,?,?,?,?,?)", (s["parent_doi"], s["si_doi"], s.get("url"),
                                                                          s.get("title"), s.get("source"), s.get("date_added")))
        for t in t_new:
            led.x("INSERT OR IGNORE INTO paper_topics VALUES (?,?,?,?,?,?,?,?,?)",
                  (lid, t["collection"], t.get("relevance"), t.get("relevance_note"), t.get("relevance_method"),
                   t.get("in_scope"), None, "[]", t.get("date_added")))
            self.n["topics_added"] += 1
        for t in t_better:
            led.set_topic(lid, t["collection"], relevance=t.get("relevance"), relevance_note=t.get("relevance_note"),
                          relevance_method=t.get("relevance_method"), in_scope=t.get("in_scope"))
            self.n["relevance_taken"] += 1
        if subj:
            main = [s["term"] for s in sorted(omain, key=lambda s: s["rank"])]
            rel = [s["term"] for s in sorted((s for s in osubj if s["kind"] != "main"), key=lambda s: s["rank"])]
            led.set_subjects(lid, main, rel, (omain[0].get("method") if omain else None) or "vocab",
                             {s["term"]: s.get("score") for s in osubj if s.get("score") is not None}, force=True)
            self.n["topics_abc_taken"] += 1
        for e in e_new:
            led.x("INSERT OR REPLACE INTO extractions VALUES (?,?,?,?,?,?,?,?,?)",
                  (lid, e["collection"], e["kg"], e["status"], e.get("schema_version"), e.get("nodes"), e.get("edges"),
                   e.get("date"), e.get("note")))
        return n

    def import_files(self, lid, o, otopics):
        """The other copy's PDF and SI of a paper this copy has not downloaded, copied in under this copy's ID."""
        from _download import clone_or_copy
        if not (self.files and o.get("downloaded")):
            return False
        oid, done, si_names = str(o["id"]), False, []

        def renamed(rel):
            p = Path(rel)
            name = str(lid) + p.name[len(oid):] if p.name.startswith(oid) else p.name
            return p.with_name(name)

        for t in otopics:
            pdf, new_si = None, []
            if t.get("pdf_path") and (self.files / t["pdf_path"]).is_file():
                dst = self.proj.root / renamed(t["pdf_path"])
                if not self.dry:
                    clone_or_copy(self.files / t["pdf_path"], dst)
                pdf = self.proj.rel(dst)
            for s in json.loads(t.get("si_paths") or "[]"):
                if (self.files / s).is_file():
                    dst = self.proj.root / renamed(s)
                    if not self.dry:
                        clone_or_copy(self.files / s, dst)
                    new_si.append(self.proj.rel(dst))
                    si_names.append(dst.name)
            if pdf and not self.dry:
                self.led.set_topic(lid, t["collection"], path=pdf, si_paths=new_si)
            done = done or bool(pdf)
        if done and not self.dry:
            self.led.set(lid, **{f: o.get(f) for f in DOWNLOAD if f not in ("si_files", "dl_status", "dl_note")},
                         si_files=list(dict.fromkeys(si_names)), dl_status=None, dl_note=None)
        if done:
            self.n["files_imported"] += 1
        return done

    def add(self, o, otopics, osubj, oext):
        led = self.led
        nid = o["id"] if self.empty_here and not led.get(o["id"]) else led.next_id()
        row = {k: v for k, v in o.items() if not k.startswith("_") and k in self.cols}
        row["id"] = nid
        if row.get("downloaded"):                  # the other copy's files are the other copy's
            url = row.get("download_url")
            seen = {_vkey(v) for v in row.get("versions") or []}
            if url and url not in seen:
                row["versions"] = list(row.get("versions") or []) + [
                    {"url": url, "pdf_url": url, "access": row.get("access_type"), "version": row.get("version"),
                     "src": "merged copy"}]
            for f in DOWNLOAD:
                row[f] = 0 if f == "downloaded" else ([] if f == "si_files" else None)
            row["dl_note"] = "downloaded in the merged copy, not in this one"
        for k in JSON_COLS:
            if k in row and not isinstance(row[k], str):
                row[k] = json.dumps(row[k], ensure_ascii=False)
        if self.dry:
            self.n["added"] += 1
            return nid
        keys = [k for k in self.cols if k in row]
        led.x(f"INSERT INTO papers ({', '.join(keys)}) VALUES ({','.join('?' * len(keys))})", [row[k] for k in keys])
        self.related(nid, o, otopics, osubj, oext)
        self.n["added"] += 1
        return nid

    # ---------------------------------------------------------------- the whole copy
    def run(self):
        local_db = sqlite3.connect(f"file:{self.proj.db}?mode=ro", uri=True) if has_state(self.proj.db) else None
        cols = None
        if local_db:
            theirs = {r[1] for r in self.other.con.execute("PRAGMA table_info(papers)")}
            cols = [r[1] for r in local_db.execute("PRAGMA table_info(papers)") if r[1] in theirs]
        for ids in self.other.ids():
            ofp = self.other.fingerprints(ids, cols)
            lfp = _fingerprints(local_db, ids, cols) if local_db else {}
            changed = [i for i in ids if ofp.get(i) != lfp.get(i)]
            for i in ids:
                if i not in changed:
                    self.id_map[i] = i
            self.n["unchanged"] += len(ids) - len(changed)
            if not changed:
                continue
            ops = self.other.papers(changed)
            otop = self.other.by_paper("SELECT * FROM paper_collections WHERE paper_id IN ({})", changed)
            osub = self.other.by_paper("SELECT * FROM paper_subjects WHERE paper_id IN ({})", changed)
            oext = self.other.by_paper("SELECT * FROM extractions WHERE paper_id IN ({})", changed)
            for oid in changed:
                o = ops.get(oid)
                if not o:
                    continue
                found = self.match(o)
                if not found:
                    lid = self.add(o, otop.get(oid, []), osub.get(oid, []), oext.get(oid, []))
                    self.import_files(lid, o, otop.get(oid, []))
                    self.id_map[oid] = lid
                    continue
                lid = self.fold(found, o) if len(found) > 1 else next(iter(found))
                self.id_map[oid] = lid
                L = self.led.get(lid) or {}
                upd = self.fields(L, o)
                if upd and not self.dry:
                    self.led.set(lid, **upd)
                n = self.related(lid, o, otop.get(oid, []), osub.get(oid, []), oext.get(oid, []))
                if not L.get("downloaded"):
                    n += int(self.import_files(lid, o, otop.get(oid, [])))
                self.n["updated" if (upd or n) else "matched_same"] += 1
        if local_db:
            local_db.close()

    # ---------------------------------------------------------------- project files, history
    def project_files(self):
        if "project_files" not in self.other.tables:
            return
        for rel, content in self.other.con.execute("SELECT path, content FROM project_files"):
            f = self.proj.scr / rel
            if not f.exists():
                if not self.dry:
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_text(content, encoding="utf-8")
                self.n["project_files_added"] += 1
                continue
            mine = f.read_text(encoding="utf-8", errors="replace")
            if mine == content:
                continue
            merged = None
            if rel.endswith("/state.json"):
                a, b = json.loads(mine), json.loads(content)
                runs = dict(a.get("search_runs") or {})
                for k, v in (b.get("search_runs") or {}).items():
                    if k not in runs or (v.get("finished_at") or "") > (runs[k].get("finished_at") or ""):
                        runs[k] = v
                if runs != (a.get("search_runs") or {}):
                    a["search_runs"] = runs
                    merged = a
            elif rel.endswith("/queries.json"):
                a, b = json.loads(mine), json.loads(content)
                for src, qs in b.items():
                    if not isinstance(qs, dict):
                        continue
                    mine_q = a.setdefault(src, {})
                    have = {json.dumps(v, sort_keys=True) for v in mine_q.values()}
                    for qid, q in qs.items():
                        if json.dumps(q, sort_keys=True) not in have:
                            mine_q[qid if qid not in mine_q else f"{qid}-merged"] = q
                if a != json.loads(mine):
                    merged = a
            elif rel == "dedup_decisions.jsonl":
                have = set(mine.splitlines())
                extra = [ln for ln in content.splitlines() if ln.strip() and ln not in have]
                if extra and not self.dry:
                    f.write_text(mine.rstrip("\n") + "\n" + "\n".join(extra) + "\n", encoding="utf-8")
                self.n["decisions_added"] += len(extra)
            elif rel == "vocab_custom.json":
                a, b = json.loads(mine), json.loads(content)
                ids = {t.get("id") for t in a.get("terms") or []}
                extra = [t for t in b.get("terms") or [] if t.get("id") not in ids]
                if extra:
                    a["terms"] = (a.get("terms") or []) + extra
                    merged = a
            if merged is not None:
                if not self.dry:
                    json_write_atomic(f, merged)
                self.n["project_files_merged"] += 1

    def history(self, tag):
        """The other copy's runs since the copies parted, with their changes (paper IDs as this copy numbers them)."""
        if self.dry or "runs" not in self.other.tables:
            return 0
        from _publish import ensure_state
        con = sqlite3.connect(str(self.proj.db), timeout=300)
        ensure_state(con)

        def key(r):                         # a run's identity: its uid; for runs older than uids, when and what
            return r["uid"] if r["uid"] else (r["at"], r["step"], r["topics"] or "")

        con.row_factory = sqlite3.Row
        have = {key(r) for r in con.execute("SELECT at, step, topics, uid FROM runs")}
        theirs = {r[1] for r in self.other.con.execute("PRAGMA table_info(runs)")}
        n = 0
        with con:
            for r in self.other.con.execute("SELECT * FROM runs ORDER BY id"):
                r = {**dict(r), "uid": dict(r).get("uid") if "uid" in theirs else None}
                if key(r) in have:
                    continue
                rid = con.execute("INSERT INTO runs(at, step, topics, added, updated, removed, papers, note, uid) "
                                  "VALUES (?,?,?,?,?,?,?,?,?)", (r["at"], r["step"], r["topics"], r["added"], r["updated"],
                                                                 r["removed"], r["papers"],
                                                                 ((r["note"] or "") + f" [from {tag}]").strip(),
                                                                 r["uid"])).lastrowid
                for c in self.other.con.execute("SELECT * FROM changes WHERE run_id=?", (r["id"],)):
                    pid = self.id_map.get(c["paper_id"])
                    if pid is None and c["old"]:            # a paper the other copy has since merged away
                        hit = con.execute("SELECT id FROM papers WHERE id=? AND doi=?", (c["paper_id"], c["old"])).fetchone()
                        pid = hit[0] if hit else None
                    con.execute("INSERT INTO changes VALUES (?,?,?,?,?,?)",
                                (rid, pid, c["change"], c["field"], c["old"], c["new"]))
                n += 1
        con.close()
        return n


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--from", dest="src", required=True, help="the other copy's papers.db")
    ap.add_argument("--files", help="the other project's folder (it holds publications/): copy in its PDFs and SI")
    ap.add_argument("--dry-run", action="store_true", help="say what would change; write nothing")
    a = ap.parse_args()
    proj = Project(a.project)
    src = Path(a.src).resolve()
    if src == proj.db.resolve():
        die("--from is this project's own papers.db")
    led = Ledger(proj)
    if not a.dry_run:
        led.export()                                   # this copy's own pending changes first, as their own run
    other = Other(src)
    m = Merge(proj, led, other, a.files, a.dry_run)
    log(f"merging {src} ...")
    m.run()
    m.project_files()
    res = {"from": str(src), "dry_run": a.dry_run, **dict(sorted(m.n.items()))}
    if not a.dry_run:
        led.export()
        tag = f"{src.parent.parent.name}/{src.name}" if src.parent.name == "publications" else src.name
        con = sqlite3.connect(str(proj.db))
        last = con.execute("SELECT MAX(id) FROM runs").fetchone()[0]
        note = (f"merged {tag}: {m.n['added']} papers added, {m.n['updated']} updated, {m.n['merged_here']} merged "
                f"here, {m.n['files_imported']} downloads copied in")
        with con:
            if last and con.execute("SELECT step FROM runs WHERE id=?", (last,)).fetchone()[0] == "merge_db":
                con.execute("UPDATE runs SET note=? WHERE id=?", (note, last))
        con.close()
        res["runs_from_other"] = m.history(tag)
        res["database"] = led.last_publish
        res["vector_store"] = after_step(proj, led)     # downloads copied in (--files) are read and embedded
        res["next"] = "dedup.py --apply (it merges papers the two copies indexed under different keys)"
    print(json.dumps(res, default=str))


if __name__ == "__main__":
    main()
