"""The vector store: the downloaded papers' text cut into passages, with their vectors, to search by meaning and by
words (library module — not run directly; vectors.py is the command).

publications/vectors.db (SQLite; local, since it holds the papers' text: it is shared no more than the PDFs are)
  papers        one row per paper in the store: the signature of the files it was read from (the PDF's sha1, the SI
                files), the pages read and those without a text layer, its passages, when, and why when unreadable
  passages      id '<paper ID>/p<page>/<k>' (supporting-information pages are S1, S2 ... after the paper's, as
                curate-corpus reads them), paper_id, page, k, start / end in the page's text, the text and its sha1
  vectors       one int8 vector per passage text and embedder: a text is embedded once per embedder, whatever paper
                or page holds it, and kept while a passage holds it
  passages_fts  the passages' words (FTS5, BM25) for keyword and hybrid search
  about         the embedders the store keeps up to date, the passage cutter, when it was built and updated
The paper index (papers.db and the ledger) keeps every record; the store keeps only what a search needs, and a
search joins its hits to the index by paper ID.

Updates are incremental: a paper is read again only when its files changed (its signature), and then only passages
whose text is new are embedded; a paper that leaves (no longer downloaded, merged into another ID, out of scope,
retracted) leaves the store with its passages, and a vector no passage holds is dropped. Passages are cut as SCALE's
tools/passages.py cuts source pages (split_page: paragraphs joined up to 900 characters, a longer paragraph cut at a
sentence end), and the embedders keep SCALE's names: scale-hash-v1 (SCALE's default: deterministic, lexical with
chemistry aliases, no download; the code below is SCALE's, so the vectors are the same), fastembed:<model>, and
sentence-transformers:<model> for a local neural model (e.g. BAAI/bge-small-en-v1.5). A neural model is fetched only
by `vectors.py init`; updates and searches run offline.
"""
import hashlib
import json
import math
import os
import re
import sqlite3
from collections import Counter
from pathlib import Path

from _common import log, now_iso

CUTTER = "scale-split_page-900"        # how passages are cut (a change re-reads every paper)
DEFAULT_EMBEDDER = "scale-hash-v1"
MIN_PASSAGE = 25                          # characters: shorter spans (page numbers, running heads) are not stored
BATCH = 1024                              # passage texts per embedding call

# ------------------------------------------------------------------ SCALE's passages and hash embedder
# copied from SCALE's tools/passages.py (WORD ... split_page), so passages and scale-hash-v1 vectors are SCALE's own


def _np():
    try:
        import numpy
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("the vector store needs numpy: pip install numpy") from e
    return numpy


WORD = re.compile(r"[0-9a-zà-öø-ÿα-ω]+(?:[.,][0-9]+)?", re.I)
PASSAGE_CHARS = 900


FORMULAS = {"Cu": "copper", "Zn": "zinc", "Cr": "chromium", "Al": "aluminum", "Fe": "iron", "Ni": "nickel", "Co": "cobalt",
            "Mn": "manganese", "Th": "thorium", "Mg": "magnesium", "Ag": "silver", "Pd": "palladium", "Pt": "platinum",
            "ZnO": "zinc oxide", "CuO": "copper oxide", "Cu2O": "copper oxide", "Cr2O3": "chromium oxide",
            "CrO3": "chromium oxide", "Al2O3": "alumina", "CO": "carbon monoxide", "CO2": "carbon dioxide",
            "H2": "hydrogen", "H2O": "water", "CH3OH": "methanol", "CH4": "methane", "H2S": "hydrogen sulfide",
            "HCHO": "formaldehyde", "N2": "nitrogen", "NH3": "ammonia"}
SPELLING = {"sulphur": "sulfur", "sulphide": "sulfide", "sulphides": "sulfides", "aluminium": "aluminum",
            "vapour": "vapor", "catalyser": "catalyst", "katalysator": "catalyst", "katalysatoren": "catalysts",
            "methanol": "methanol", "methylalkohol": "methanol", "kupfer": "copper", "zink": "zinc", "zinkoxyd": "zinc oxide",
            "chromoxyd": "chromium oxide", "wasserstoff": "hydrogen", "kohlenoxyd": "carbon monoxide",
            "kohlensaure": "carbon dioxide", "kohlensäure": "carbon dioxide", "schwefel": "sulfur", "alumina": "alumina"}
FORMULA = re.compile(r"\b(" + "|".join(sorted(map(re.escape, FORMULAS), key=len, reverse=True)) + r")\b")


def tokens(text: str) -> list[str]:
    """Lower-cased words, with formula aliases and spelling variants added (so Cu also matches copper)."""
    out = []
    for w in WORD.findall(FORMULA.sub(lambda m: f"{m.group(1)} {FORMULAS[m.group(1)]}", text)):
        lw = w.lower()
        out.append(lw)
        alt = SPELLING.get(lw)
        if alt and alt != lw:
            out.extend(alt.split())
    return out


class HashEmbedder:
    name = "scale-hash-v1"

    id = name
    dim = 512

    def features(self, text: str, grams: dict | None = None) -> Counter:
        """Weighted features: each word (1), its character 4-grams with < and > as ends (0.5 each) and each word pair
        (1). ``grams`` caches each word's 4-grams across calls; the weights are multiples of 0.5, so the sums are exact
        in any order."""
        ws = tokens(text)
        grams = {} if grams is None else grams
        f: Counter = Counter()
        for w, c in Counter(ws).items():
            f["w:" + w] += float(c)
            g = grams.get(w)
            if g is None:
                padded = f"<{w}>"
                g = grams[w] = ["c:" + padded[i:i + 4] for i in range(len(padded) - 3)] if len(padded) > 4 else []
            for x in g:
                f[x] += 0.5 * c
        for a, b in zip(ws, ws[1:]):
            f["b:" + a + " " + b] += 1.0
        return f

    def encode(self, texts: list[str]):
        np = _np()
        out = np.zeros((len(texts), self.dim), dtype=np.float64)
        slots: dict[str, tuple[int, float]] = {}    # each feature hashed once per call (words and 4-grams recur)
        grams: dict[str, list[str]] = {}
        for r, t in enumerate(texts):
            for feat, tf in sorted(self.features(t, grams).items()):
                slot = slots.get(feat)
                if slot is None:
                    h = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
                    slot = slots[feat] = (int.from_bytes(h[:4], "little") % self.dim, 1.0 if h[4] & 1 else -1.0)
                idx, sign = slot
                out[r, idx] += sign * (1.0 + math.log(tf)) if tf >= 1 else sign * tf
        return out


def quantize(mat):
    """Row-wise L2 normalization, then int8 (cosine similarity is unchanged by the row scale)."""
    np = _np()
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = mat / norms
    peak = np.abs(unit).max(axis=1, keepdims=True)
    peak[peak == 0] = 1.0
    return np.rint(unit / peak * 127).astype(np.int8)


def split_page(text: str, limit: int = PASSAGE_CHARS) -> list[tuple[int, int]]:
    """Character spans of the passages of one page: paragraphs joined up to ``limit`` characters,
    and a paragraph longer than the limit cut at sentence ends."""
    spans, start, n = [], None, len(text)
    paras = [(m.start(), m.end()) for m in re.finditer(r"\S(?:.*?\S)?(?=\s*\n\s*\n|\s*\Z)", text, re.S)]
    pieces = []
    for a, b in paras:
        while b - a > limit:
            cut = text.rfind(". ", a, a + limit)
            cut = cut + 1 if cut > a + limit // 3 else a + limit
            pieces.append((a, cut))
            a = cut
            while a < b and text[a].isspace():
                a += 1
        if b > a:
            pieces.append((a, b))
    end = None
    for a, b in pieces:
        if start is None:
            start, end = a, b
        elif b - start <= limit:
            end = b
        else:
            spans.append((start, end))
            start, end = a, b
    if start is not None and end is not None and end <= n:
        spans.append((start, end))
    return spans



# ------------------------------------------------------------------ neural embedders (local)
QUERY_PREFIX = {"BAAI/bge-": "Represent this sentence for searching relevant passages: ", "intfloat/e5-": "query: ",
                "nomic-ai/nomic-embed": "search_query: "}
DOC_PREFIX = {"intfloat/e5-": "passage: ", "nomic-ai/nomic-embed": "search_document: "}


def _prefix(table, model):
    return next((v for k, v in table.items() if model.startswith(k)), "")


class SentenceTransformersEmbedder:
    """A sentence-transformers model on this machine (Apple GPU when there is one). Loaded from the local cache only,
    unless `download` (vectors.py init) — so an update or a search never fetches anything."""

    def __init__(self, model, download=False):
        if not download:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError("sentence-transformers embedders need: pip install sentence-transformers") from e
        device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
        try:
            self.m = SentenceTransformer(model, device=device, trust_remote_code=model.startswith("nomic-ai/"))
        except OSError as e:
            raise RuntimeError(f"model {model} is not on this machine: fetch it once with "
                               f"vectors.py init --embedder sentence-transformers:{model}") from e
        if device != "cpu":
            self.m.half()            # half precision on a GPU: the same vectors (cosine 1.0000 on test passages), faster
        self.model, self.id = model, f"sentence-transformers:{model}"
        self.dim = self.m.get_sentence_embedding_dimension()

    def encode(self, texts, query=False):
        pre = _prefix(QUERY_PREFIX if query else DOC_PREFIX, self.model)
        t = self.m.encode([pre + x for x in texts], batch_size=128, convert_to_tensor=True, normalize_embeddings=True,
                          show_progress_bar=False)
        return _np().array(t.float().cpu().tolist(), dtype=_np().float64)   # tolist: no numpy ABI between torch, numpy


class FastEmbedEmbedder:
    """SCALE's other neural option (fastembed, ONNX on the CPU)."""

    def __init__(self, model, download=False):
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise RuntimeError("fastembed embedders need: pip install fastembed") from e
        self.m, self.model, self.id = TextEmbedding(model_name=model), model, f"fastembed:{model}"
        self.dim = None

    def encode(self, texts, query=False):
        return _np().array(list(self.m.embed(texts)), dtype=_np().float64)


_EMBEDDERS = {}


def _embedder(name):
    """One loaded embedder per process (a neural model loads once for many searches)."""
    if name not in _EMBEDDERS:
        _EMBEDDERS[name] = get_embedder(name)
    return _EMBEDDERS[name]


def get_embedder(name, download=False):
    if name == "scale-hash-v1":
        return HashEmbedder()
    kind, _, model = name.partition(":")
    if kind == "sentence-transformers" and model:
        return SentenceTransformersEmbedder(model, download)
    if kind == "fastembed" and model:
        return FastEmbedEmbedder(model, download)
    raise RuntimeError(f"unknown embedder {name!r}: scale-hash-v1, sentence-transformers:<model> or fastembed:<model>")


def encode(emb, texts, query=False):
    """The embedder's vectors; SCALE's hash embedder takes no `query`."""
    return emb.encode(texts, query=query) if not isinstance(emb, HashEmbedder) else emb.encode(texts)


# ------------------------------------------------------------------ the store
SCHEMA = """
CREATE TABLE IF NOT EXISTS about (name TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS papers (paper_id INTEGER PRIMARY KEY, signature TEXT NOT NULL, pdf TEXT, si_files INTEGER,
  pages INTEGER, pages_without_text INTEGER, passages INTEGER, chars INTEGER, read_at TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS passages (id TEXT PRIMARY KEY, paper_id INTEGER NOT NULL, page TEXT, k INTEGER, start INTEGER,
  "end" INTEGER, text_sha1 TEXT NOT NULL, text TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_passages_paper ON passages(paper_id);
CREATE INDEX IF NOT EXISTS ix_passages_sha ON passages(text_sha1);
CREATE TABLE IF NOT EXISTS vectors (text_sha1 TEXT NOT NULL, embedder TEXT NOT NULL, vec BLOB NOT NULL,
  PRIMARY KEY (embedder, text_sha1)) WITHOUT ROWID;
"""
FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(text, content='passages', content_rowid='rowid');
CREATE TRIGGER IF NOT EXISTS passages_fts_ai AFTER INSERT ON passages BEGIN
  INSERT INTO passages_fts(rowid, text) VALUES (new.rowid, new.text); END;
CREATE TRIGGER IF NOT EXISTS passages_fts_ad AFTER DELETE ON passages BEGIN
  INSERT INTO passages_fts(passages_fts, rowid, text) VALUES ('delete', old.rowid, old.text); END;
"""


def store_path(proj):
    return proj.pub / "vectors.db"


def open_store(proj, create=False):
    path = store_path(proj)
    if not path.exists() and not create:
        raise RuntimeError(f"no vector store: {proj.rel(path)} (vectors.py init)")
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=300)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA + FTS)
    _key_by_embedder(con)
    return con


def _key_by_embedder(con):
    """A store built before 2026-10-22 kept vectors in text order, each embedder's scattered among the others': kept
    in embedder order, a search reads one embedder's vectors in one pass. Rebuilt once, in place (then compacted)."""
    if {r[1]: r[5] for r in con.execute("PRAGMA table_info(vectors)")}.get("embedder") == 1:
        return
    log("vectors: ordering the vectors by embedder (once) ...")
    with con:
        con.execute("CREATE TABLE vectors_by_embedder (text_sha1 TEXT NOT NULL, embedder TEXT NOT NULL, vec BLOB NOT "
                    "NULL, PRIMARY KEY (embedder, text_sha1)) WITHOUT ROWID")
        con.execute("INSERT INTO vectors_by_embedder SELECT text_sha1, embedder, vec FROM vectors ORDER BY embedder, "
                    "text_sha1")
        con.execute("DROP TABLE vectors")
        con.execute("ALTER TABLE vectors_by_embedder RENAME TO vectors")
    con.execute("VACUUM")


def about(con):
    return dict(con.execute("SELECT name, value FROM about").fetchall())


def embedders_of(con):
    return json.loads(about(con).get("embedders") or json.dumps([DEFAULT_EMBEDDER]))


def set_about(con, **kv):
    with con:
        con.executemany("INSERT OR REPLACE INTO about VALUES (?,?)",
                        [(k, v if isinstance(v, str) else json.dumps(v)) for k, v in kv.items()])


# ------------------------------------------------------------------ what the store should hold
def wanted(led):
    """{paper_id: (pdf sha1, pdf path, [SI PDF paths])}: the downloaded research papers, in scope in a topic, whose
    PDF is on disk (the topic folders hold the same PDF as clones; the first one is read)."""
    root, out = led.proj.root, {}
    # the topic rows with a PDF first (a few thousand), then each one's paper: never a scan of every paper
    rows = led.q("SELECT p.id, p.sha1, t.path, t.si_paths FROM paper_topics t CROSS JOIN papers p ON p.id = t.paper_id "
                 "WHERE t.path IS NOT NULL AND COALESCE(t.in_scope, 1) = 1 AND p.downloaded = 1 AND p.is_erratum = 0 "
                 "AND COALESCE(p.retracted, 0) = 0 ORDER BY p.id, t.topic")
    for pid, sha, path, si in rows:
        cur = out.get(pid)
        if cur is None and (root / path).is_file():
            cur = out[pid] = [sha, path, {}]
        if cur is not None:
            for s in json.loads(si or "[]"):
                if s.lower().endswith(".pdf") and Path(s).name not in cur[2] and (root / s).is_file():
                    cur[2][Path(s).name] = s
    return {pid: (sha, path, [si[k] for k in sorted(si)]) for pid, (sha, path, si) in out.items()}


def signature(root, sha, pdf, si):
    """What the paper's passages depend on: the cutter, the PDF (its sha1) and each SI file (name and size)."""
    parts = [CUTTER, sha or os.path.getsize(root / pdf)] + [(Path(s).name, os.path.getsize(root / s)) for s in si]
    return hashlib.sha1(json.dumps(parts).encode("utf-8")).hexdigest()


def pages_of(root, pdf, si):
    """[(page label, text)]: the PDF's pages 1, 2 ..., then the SI PDFs' pages S1, S2 ... (text layer only)."""
    import fitz
    out = []
    with fitz.open(root / pdf) as doc:
        out += [(str(i), page.get_text()) for i, page in enumerate(doc, 1)]
    n = 0
    for s in si:
        try:
            with fitz.open(root / s) as doc:
                for page in doc:
                    n += 1
                    out.append((f"S{n}", page.get_text()))
        except Exception as e:          # an unreadable SI file leaves the paper's own pages in
            log(f"vectors: SI file skipped ({s}: {e})")
    return out


def passages_of(pid, pages):
    """SCALE's passages of each page: (id, page, k, start, end, text sha1, text); spans too short to mean anything are
    not stored (their k is kept, so ids stay SCALE's)."""
    out = []
    for label, text in pages:
        for k, (a, b) in enumerate(split_page(text), start=1):
            t = text[a:b]
            if len(t.strip()) >= MIN_PASSAGE:
                out.append((f"{pid}/p{label}/{k}", label, k, a, b, hashlib.sha1(t.encode("utf-8")).hexdigest(), t))
    return out


def _embed_missing(con, emb, progress=None):
    """Vectors for every passage text this embedder has none for, in one pass over the passages added since its last
    pass (a passage is never changed in place: a paper read again gets new rows); returns how many were made."""
    mark = f"checked:{emb.id}"
    n, shown = 0, 0
    last = int(about(con).get(mark) or 0)
    while True:
        rows = con.execute("SELECT rowid, text_sha1, text FROM passages WHERE rowid > ? ORDER BY rowid LIMIT ?",
                           (last, BATCH * 4)).fetchall()
        if not rows:
            set_about(con, **{mark: str(last)})
            return n
        last = rows[-1][0]
        need = {}
        for _, sha, text in rows:
            need.setdefault(sha, text)
        have = {r[0] for r in con.execute(f"SELECT text_sha1 FROM vectors WHERE embedder = ? AND text_sha1 IN "
                                          f"({','.join('?' * len(need))})", [emb.id, *need])}
        todo = [(sha, text) for sha, text in need.items() if sha not in have]
        for i in range(0, len(todo), BATCH):
            part = todo[i:i + BATCH]
            vec = quantize(encode(emb, [t for _, t in part]))
            with con:
                con.executemany("INSERT OR REPLACE INTO vectors VALUES (?,?,?)",
                                [(sha, emb.id, vec[j].tobytes()) for j, (sha, _) in enumerate(part)])
            n += len(part)
        set_about(con, **{mark: str(last)})
        if progress and n - shown >= 20000:
            shown = n
            progress(f"vectors: {emb.id}: {n} passages embedded")


def update(proj, led, embedders=None, ids=None, limit=None, progress=log):
    """Bring the store in line with the downloaded papers: read the new and changed ones, drop the ones that left,
    embed the passage texts each embedder lacks, drop the vectors no passage holds."""
    con = open_store(proj, create=True)
    names = list(dict.fromkeys(embedders or embedders_of(con)))
    if not about(con).get("created_at"):
        set_about(con, created_at=now_iso(), cutter=CUTTER)
    set_about(con, embedders=list(dict.fromkeys(embedders_of(con) + names)) if embedders else names)
    root = proj.root
    want = wanted(led)
    if ids:
        want = {k: v for k, v in want.items() if k in set(ids)}
    have = dict(con.execute("SELECT paper_id, signature FROM papers").fetchall())
    gone = [] if ids else [pid for pid in have if pid not in want]
    st = Counter()
    with con:
        for pid in gone:
            con.execute("DELETE FROM passages WHERE paper_id = ?", (pid,))
            con.execute("DELETE FROM papers WHERE paper_id = ?", (pid,))
    st["papers_removed"] = len(gone)
    todo = []
    for pid, (sha, pdf, si) in sorted(want.items()):
        sig = signature(root, sha, pdf, si)
        if have.get(pid) == sig:
            st["papers_unchanged"] += 1
        else:
            todo.append((pid, sig, pdf, si))
    if limit is not None:
        st["papers_left_for_later"] = max(0, len(todo) - limit)
        todo = todo[:limit]
    for i, (pid, sig, pdf, si) in enumerate(todo, 1):
        note, pages = None, []
        try:
            pages = pages_of(root, pdf, si)
        except Exception as e:           # recorded with its signature: read again only when the file changes
            note = f"unreadable: {str(e)[:200]}"
            st["papers_unreadable"] += 1
        ps = passages_of(pid, pages)
        known = {r[0] for r in con.execute("SELECT DISTINCT text_sha1 FROM passages WHERE paper_id = ?", (pid,))}
        with con:
            con.execute("DELETE FROM passages WHERE paper_id = ?", (pid,))
            con.executemany("INSERT INTO passages (id, paper_id, page, k, start, \"end\", text_sha1, text) "
                            "VALUES (?,?,?,?,?,?,?,?)", [(p[0], pid, *p[1:]) for p in ps])
            con.execute("INSERT OR REPLACE INTO papers VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (pid, sig, pdf, len(si), len(pages), sum(1 for _, t in pages if len(t.strip()) < MIN_PASSAGE),
                         len(ps), sum(len(p[6]) for p in ps), now_iso(), note))
        st["papers_read"] += 1
        st["passages_added"] += len(ps)
        st["passages_already_known"] += sum(1 for p in ps if p[5] in known)
        if progress and i % 200 == 0:
            progress(f"vectors: {i}/{len(todo)} papers read")
    embedded = {}
    for name in names:
        emb = get_embedder(name)
        embedded[name] = _embed_missing(con, emb, progress)
    n_drop = 0
    if st["papers_removed"] or st["papers_read"]:              # only then can a text have lost its last passage
        with con:
            n_drop = con.execute("DELETE FROM vectors WHERE NOT EXISTS (SELECT 1 FROM passages p WHERE "
                                 "p.text_sha1 = vectors.text_sha1)").rowcount
    set_about(con, updated_at=now_iso())
    keys = ("papers_read", "papers_unchanged", "papers_removed", "papers_unreadable", "passages_added",
            "passages_already_known")
    res = {**{k: st[k] for k in keys}, **{k: v for k, v in st.items() if k not in keys}, "embedded": embedded,
           "vectors_dropped": n_drop, **counts(con)}
    con.close()
    return res


def counts(con):
    return {"papers": con.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
            "passages": con.execute("SELECT COUNT(*) FROM passages").fetchone()[0],
            "vectors": dict(con.execute("SELECT embedder, COUNT(*) FROM vectors GROUP BY embedder").fetchall())}


def status(proj, led):
    con = open_store(proj)
    want = wanted(led)
    have = dict(con.execute("SELECT paper_id, signature FROM papers").fetchall())
    stale = sum(1 for pid, (sha, pdf, si) in want.items() if have.get(pid) != signature(proj.root, sha, pdf, si))
    texts = con.execute("SELECT COUNT(DISTINCT text_sha1) FROM passages").fetchone()[0]
    out = {"store": proj.rel(store_path(proj)), **about(con), **counts(con), "downloaded_papers": len(want),
           "papers_to_read": stale, "papers_to_remove": sum(1 for pid in have if pid not in want),
           "passage_texts": texts, "unreadable": con.execute("SELECT COUNT(*) FROM papers WHERE note IS NOT NULL").fetchone()[0],
           "megabytes": round(store_path(proj).stat().st_size / 1e6, 1)}
    out["embedders"] = embedders_of(con)
    out["texts_without_vector"] = {e: texts - out["vectors"].get(e, 0) for e in out["embedders"]}
    con.close()
    return out


def after_step(proj, led):
    """Keep the store in step after a step that changed what is downloaded (download_open, download_paywalled,
    fetch_si, dedup, merge_db): only when the project has a store; never fails the step."""
    if not store_path(proj).exists():
        return None
    try:
        return update(proj, led)
    except Exception as e:
        log(f"vector store not updated ({e}): run vectors.py update")
        return {"error": str(e)}


# ------------------------------------------------------------------ search
def _fts_query(text):
    words = [w for w in re.findall(r"[\w][\w\-]*", text.lower()) if len(w) > 1]
    return " OR ".join('"' + w.replace('"', "") + '"' for w in dict.fromkeys(words))


# a reference list's passages match almost any query on the titles they cite: a search leaves them out unless asked
_REF = [(re.compile(r"\bet al\b"), 2), (re.compile(r"(?<![\d.])(19[5-9]\d|20[0-4]\d)[a-z]?(?=[,;.)\s])"), 1),
        (re.compile(r"\b\d{1,5}\s?[-–−]\s?\d{1,5}\b"), 1),
        (re.compile(r"(^|\s)(\[\d{1,3}\]|\(\d{1,3}\)|\d{1,3}\.)\s+[A-Z][a-z]+,?\s"), 2), (re.compile(r"10\.\d{4,9}/"), 2),
        (re.compile(r"\b[A-Z][a-zà-ÿ'-]+,?\s(?:[A-Z]\.\s?-?){1,3}[,;]"), 2),
        (re.compile(r"\b(?:J\.|Chem\.|Phys\.|Soc\.|Catal\.|Mater\.|Lett\.|Rev\.|Nat\.|Angew\.|Commun\.|Sci\.|Eng\.|Int\.|"
                    r"Appl\.|Energy|Environ\.)\s"), 1)]


def is_reference_list(text):
    """A passage of a reference list: dense with citations (authors' initials, et al., years, volumes and pages, DOIs,
    journal abbreviations) — at least 4 such marks and 2.5 per 100 characters."""
    hits = sum(w * len(rx.findall(text)) for rx, w in _REF)
    return hits >= 4 and hits * 100 / max(1, len(text)) >= 2.5


_MATRIX = {}         # (store, embedder) -> (when the store changed, rowids, paper ids, text rows, int8 vectors, norms)
BLOCK = 65536        # vectors converted to float32 at a time for the cosine, bounding the working memory


def _matrix(con, path, emb_id):
    """This embedder's vectors (one per passage text, read in one pass: the table is ordered by embedder) and, for
    every passage, its row; read once per process while the store does not change."""
    np = _np()
    stamp = about(con).get("updated_at")
    cached = _MATRIX.get((str(path), emb_id))
    if cached and cached[0] == stamp:
        return cached[1:]
    pos, blobs = {}, []
    for sha, vec in con.execute("SELECT text_sha1, vec FROM vectors WHERE embedder = ?", (emb_id,)):
        pos[sha] = len(blobs)
        blobs.append(vec)
    rows = [(r, pid, pos[sha]) for r, pid, sha in con.execute("SELECT rowid, paper_id, text_sha1 FROM passages ORDER BY "
                                                              "rowid") if sha in pos]
    rowids = np.array([r[0] for r in rows], dtype=np.int64)
    pids = np.array([r[1] for r in rows], dtype=np.int64)
    which = np.array([r[2] for r in rows], dtype=np.int64)
    m = np.frombuffer(b"".join(blobs), dtype=np.int8).reshape(len(blobs), -1) if blobs else np.zeros((0, 1), np.int8)
    norms = np.ones(len(m), dtype=np.float32)
    for lo in range(0, len(m), BLOCK):
        norms[lo:lo + BLOCK] = np.linalg.norm(m[lo:lo + BLOCK].astype(np.float32), axis=1)
    norms[norms == 0] = 1.0
    _MATRIX[(str(path), emb_id)] = (stamp, rowids, pids, which, m, norms)
    return rowids, pids, which, m, norms


def search(proj, query, k=10, mode="hybrid", embedder=None, allowed=None, depth=1000, references=False):
    """The best `k` passages for `query` (hybrid: the mean of BM25 scaled to its best and the cosine; vector;
    keyword), among the papers in `allowed` (a set of IDs) when given, reference lists left out unless `references`,
    joined to their records in the index."""
    np = _np()
    con = open_store(proj)
    emb_id = embedder or embedders_of(con)[0]
    cos, kw = {}, {}
    if mode in ("hybrid", "vector"):
        q = encode(_embedder(emb_id), [query], query=True)[0].astype(np.float32)
        q /= (np.linalg.norm(q) or 1.0)
        rowids, pids, which, m, norms = _matrix(con, store_path(proj), emb_id)
        if len(rowids):
            per_text = np.empty(len(m), dtype=np.float32)
            for lo in range(0, len(m), BLOCK):
                per_text[lo:lo + BLOCK] = m[lo:lo + BLOCK].astype(np.float32) @ q
            s = (per_text / norms)[which]
            if allowed is not None:
                s = np.where(np.isin(pids, np.fromiter(allowed, dtype=np.int64)), s, -np.inf)
            top = [i for i in np.argpartition(-s, min(depth, len(s) - 1))[:depth] if np.isfinite(s[i])]
            cos = {int(rowids[i]): float(s[i]) for i in top}
    if mode in ("hybrid", "keyword"):
        fq = _fts_query(query)
        if fq:
            for rowid, pid, score in con.execute("SELECT f.rowid, p.paper_id, -bm25(passages_fts) FROM passages_fts f "
                                                 "JOIN passages p ON p.rowid = f.rowid WHERE passages_fts MATCH ? "
                                                 "ORDER BY bm25(passages_fts) LIMIT ?", (fq, depth)):
                if allowed is None or pid in allowed:
                    kw[rowid] = float(score)
    best = max(kw.values()) if kw else 1.0
    if mode == "vector":
        scored = cos
    elif mode == "keyword":
        scored = {r: s / best for r, s in kw.items()}
    else:
        scored = {r: 0.5 * (kw.get(r, 0.0) / best) + 0.5 * max(cos.get(r, 0.0), 0.0) for r in set(cos) | set(kw)}
    out, left_out = [], 0
    for rowid, score in sorted(scored.items(), key=lambda x: (-x[1], x[0])):
        pid_, pas, page, text = con.execute("SELECT paper_id, id, page, text FROM passages WHERE rowid = ?",
                                            (rowid,)).fetchone()
        if not references and is_reference_list(text):
            left_out += 1
            continue
        out.append({"score": round(score, 4), "passage": pas, "paper_id": pid_, "page": page, "text": text})
        if len(out) == k:
            break
    con.close()
    _join_records(proj, out)
    return {"query": query, "mode": mode, "embedder": emb_id, "hits": out,
            "reference_passages_left_out": None if references else left_out}


def _join_records(proj, hits):
    """The paper records of the hits, from the index (papers.db, else the ledger)."""
    ids = sorted({h["paper_id"] for h in hits})
    if not ids:
        return
    marks = ",".join("?" * len(ids))
    recs = {}
    if proj.db.exists():
        con = sqlite3.connect(f"file:{proj.db}?mode=ro", uri=True)
        recs = {r[0]: r[1:] for r in con.execute(f"SELECT id, title, year, venue, doi, url, access_type FROM papers "
                                                 f"WHERE id IN ({marks})", ids)}
        con.close()
    for h in hits:
        r = recs.get(h["paper_id"])
        if r:
            h.update(zip(("title", "year", "venue", "doi", "url", "access_type"), r))
