"""Shared API answer caches (library module — not run directly): .scripts/enrich/<api>.sqlite, one row per DOI,
PMCID or arXiv id, shared by every topic of the project.

On disk, not in memory: a project that classifies millions of sources over many topics reads only the answers a run
needs. An older .scripts/enrich/<api>.jsonl cache is imported once and left where it is.
"""
import datetime as _dt
import json
import sqlite3
import threading

from _common import jsonl_iter, log, now_iso

MEMO_MAX = 50000   # recently read answers kept in memory (a decision reads each source's answers several times)


class Cache:
    """Answers of one API per key. With max_age_days, answers older than that (or undated) count as missing and are
    fetched again; get() still returns them until then."""

    def __init__(self, proj, name, key="doi", max_age_days=None):
        d = proj.scr / "enrich"
        d.mkdir(parents=True, exist_ok=True)
        self.path, self.key, self.name = d / f"{name}.sqlite", key, name
        self.cutoff = ((_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=max_age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
                       if max_age_days is not None else None)
        self.lock = threading.RLock()
        self.memo = {}
        self.db = sqlite3.connect(str(self.path), timeout=120, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=120000")
        self.db.execute("CREATE TABLE IF NOT EXISTS answers (k TEXT PRIMARY KEY, fetched_at TEXT, rec TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT)")
        legacy = d / f"{name}.jsonl"
        if legacy.exists() and not self._meta("imported_jsonl"):
            self._import(legacy)

    def _meta(self, name):
        r = self.db.execute("SELECT value FROM meta WHERE name=?", (name,)).fetchone()
        return r[0] if r else None

    def _import(self, legacy):
        n, rows = 0, []
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                if self._meta("imported_jsonl"):          # another process imported it meanwhile
                    self.db.execute("COMMIT")
                    return
                for r in jsonl_iter(legacy):              # later lines win, as in the old in-memory cache
                    k = r.get(self.key)
                    if k:
                        rows.append((k, r.get("fetched_at"), json.dumps(r, ensure_ascii=False)))
                    if len(rows) >= 5000:
                        self.db.executemany("INSERT OR REPLACE INTO answers VALUES (?,?,?)", rows)
                        n += len(rows)
                        rows = []
                self.db.executemany("INSERT OR REPLACE INTO answers VALUES (?,?,?)", rows)
                n += len(rows)
                self.db.execute("INSERT OR REPLACE INTO meta VALUES ('imported_jsonl', ?)", (now_iso(),))
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
        log(f"{legacy.name}: {n} cached answers moved to {self.path.name}")

    def missing(self, keys):
        keys = sorted({k for k in keys if k})
        have = set()
        for i in range(0, len(keys), 900):
            ch = keys[i:i + 900]
            with self.lock:
                rows = self.db.execute(f"SELECT k, fetched_at FROM answers WHERE k IN ({','.join('?' * len(ch))})",
                                       ch).fetchall()
            have.update(k for k, f in rows if not self.cutoff or (f or "") >= self.cutoff)
        return [k for k in keys if k not in have]

    def add(self, recs):
        ts = now_iso()
        rows = [(r[self.key], ts, json.dumps(dict(r, fetched_at=ts), ensure_ascii=False))
                for r in recs if r and r.get(self.key)]
        if not rows:
            return
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.executemany("INSERT OR REPLACE INTO answers VALUES (?,?,?)", rows)
            self.db.execute("COMMIT")
            for k, _, _ in rows:
                self.memo.pop(k, None)

    def get(self, k):
        if not k:
            return None
        with self.lock:
            if k in self.memo:
                return self.memo[k]
            row = self.db.execute("SELECT rec FROM answers WHERE k=?", (k,)).fetchone()
            rec = json.loads(row[0]) if row else None
            if len(self.memo) >= MEMO_MAX:
                self.memo.clear()
            self.memo[k] = rec
            return rec

    def summary(self, keys, paths):
        """{key: (value at each JSON path, ...)} for the cached answers among `keys` — extracted by SQLite, so millions of
        answers can be scanned without loading them into Python. paths like '$.found', '$.ids.pmcid'."""
        out, keys = {}, [k for k in keys if k]
        cols = ", ".join(f"json_extract(rec, '{p}')" for p in paths)
        for i in range(0, len(keys), 900):
            ch = keys[i:i + 900]
            with self.lock:
                for row in self.db.execute(f"SELECT k, {cols} FROM answers WHERE k IN ({','.join('?' * len(ch))})", ch):
                    out[row[0]] = row[1:]
        return out

    def get_many(self, keys, drop=()):
        """{key: answer} for the cached answers among `keys` (stale ones included, as get()), read 900 per query.
        drop: JSON paths left out of each answer ('$.authors_detail') so that big answers stay small in memory."""
        out, keys = {}, sorted({k for k in keys if k})
        col = "json_remove(rec, " + ", ".join(f"'{p}'" for p in drop) + ")" if drop else "rec"
        for i in range(0, len(keys), 900):
            ch = keys[i:i + 900]
            with self.lock:
                rows = self.db.execute(f"SELECT k, {col} FROM answers WHERE k IN ({','.join('?' * len(ch))})",
                                       ch).fetchall()
            for k, rec in rows:
                out[k] = json.loads(rec)
        return out

    def iter_all(self, like=None):
        """Every cached answer (optionally only those whose JSON contains `like`, an SQL LIKE pattern), 5,000 at a time."""
        last = ""
        while True:
            with self.lock:
                rows = self.db.execute("SELECT k, rec FROM answers WHERE k > ?" + (" AND rec LIKE ?" if like else "") +
                                       " ORDER BY k LIMIT 5000", (last, like) if like else (last,)).fetchall()
            if not rows:
                return
            last = rows[-1][0]
            for _, rec in rows:
                yield json.loads(rec)
