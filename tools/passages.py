"""Passages and their vectors, for searching evidence by meaning and by words.

Two things are indexed:

* **evidence items** — the short verbatim quotes on nodes and links (shippable with the graph);
* **source passages** — pages of the local source texts cut into short passages (kept local,
  since the full texts are not redistributed).

Each gets a vector from an **embedder** and BM25 term statistics. The default embedder,
``scale-hash-v1``, needs no model download and is deterministic: lower-cased word unigrams and
bigrams plus character 4-grams of each word (robust to OCR errors) are hashed into 512 signed
dimensions with sublinear term weights, L2-normalized and stored as int8. Another embedder (a
neural sentence model) can be registered with :func:`register_embedder`; every index records the
embedder that built it, and a search refuses to mix embedders.

An evidence item that quotes a passage carries the passage id in ``evidence.passage``, so a
passage hit leads to the records that cite it.

An evidence index records the digest of the document it was built from (``graph_sha256``, the digest a query
result names). :func:`load_for` uses an index for a document only when it holds exactly the document's evidence
items, whatever digest it records (an index built before an edit that changed no quote is still the document's): an
index built from another document, a less open one or a stale copy, is refused, so no text the document does not hold
is searched or chooses a query's rows. :func:`index_for` builds the index in memory
when none is saved beside the document, since it is derived from the document alone.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Callable

from .util import ScaleError, match_text

WORD = re.compile(r"[0-9a-zà-öø-ÿα-ω]+(?:[.,][0-9]+)?", re.I)
PASSAGE_CHARS = 900


def _np():
    try:
        import numpy
    except ImportError as e:  # pragma: no cover
        raise ScaleError("vector search needs numpy: pip install numpy") from e
    return numpy


# Case-sensitive formula and symbol aliases (CO is carbon monoxide, Co cobalt), then spelling variants.
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


# ------------------------------------------------------------------------------------------ embedders
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


EMBEDDERS: dict[str, Callable[[], object]] = {"scale-hash-v1": HashEmbedder}


def register_embedder(name: str, factory: Callable[[], object]) -> None:
    """Register an embedder: a factory returning an object with ``id`` and ``encode(texts) -> float array``."""
    EMBEDDERS[name] = factory


def get_embedder(name: str = "scale-hash-v1"):
    if name.startswith("fastembed:"):  # pragma: no cover - optional
        return _fastembed(name.split(":", 1)[1])
    if name not in EMBEDDERS:
        raise ScaleError(f"unknown embedder {name!r}; known: {sorted(EMBEDDERS)} or fastembed:<model>")
    return EMBEDDERS[name]()


def _fastembed(model: str):  # pragma: no cover - optional dependency
    try:
        from fastembed import TextEmbedding
    except ImportError as e:
        raise ScaleError("fastembed embedders need: pip install fastembed") from e
    np = _np()

    class FE:
        id = f"fastembed:{model}"

        def __init__(self):
            self.m = TextEmbedding(model_name=model)

        def encode(self, texts):
            return np.array(list(self.m.embed(texts)), dtype=np.float64)
    return FE()


def quantize(mat):
    """Row-wise L2 normalization, then int8 (cosine similarity is unchanged by the row scale)."""
    np = _np()
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = mat / norms
    peak = np.abs(unit).max(axis=1, keepdims=True)
    peak[peak == 0] = 1.0
    return np.rint(unit / peak * 127).astype(np.int8)


# ------------------------------------------------------------------------------------------ passages
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


def passages_of(slug: str, source_id: str, pages: list[dict]) -> list[dict]:
    out = []
    for p in pages:
        for k, (a, b) in enumerate(split_page(p["text"]), start=1):
            out.append({"id": f"{slug}/p{p['page']}/{k}", "source": source_id, "page": p["page"], "origin": p["origin"],
                        "start": a, "end": b, "text": p["text"][a:b]})
    return out


def locate(quote: str, passages: list[dict]) -> dict | None:
    """The passage a quote is found in (whitespace- and case-insensitive), else the page holding it."""
    q = match_text(quote)
    for p in passages:
        if q in match_text(p["text"]):
            return p
    head = q[:60]            # a quote across two passages belongs to the passage it starts in
    for p in passages:
        if len(head) >= 20 and head in match_text(p["text"]):
            return p
    return None


# ------------------------------------------------------------------------------------------ index
MODES = ("hybrid", "vector", "keyword", "rrf")
RRF_K = 60            # reciprocal rank fusion: an item scores 1 / (RRF_K + its rank) in each ranking it is in
RRF_DEPTH = 1000      # how deep each ranking is read for rrf (at least twice the hits asked for)
BLOCK = 65536         # rows of the vectors converted at a time for the cosine, bounding its working memory
CACHE_BYTES = 2 << 30  # vectors up to this size (as float32) are converted once and kept for the next queries
TERMS_MAGIC = b"SCALE-TERMS-1\n"


def _terms(items: list[dict]):
    """The BM25 statistics of ``items`` as an inverted index: the words in sorted order, and for each word the items
    that hold it (in item order) with their counts (``indptr`` delimits each word's run), and each item's length."""
    np = _np()
    first: dict[str, int] = {}
    words, rows, counts = [], [], []
    lengths = np.zeros(len(items), dtype=np.int64)
    for i, it in enumerate(items):
        c = Counter(tokens(it["text"]))
        lengths[i] = sum(c.values())
        for w, f in c.items():
            words.append(first.setdefault(w, len(first)))
            rows.append(i)
            counts.append(f)
    vocab = sorted(first)
    remap = np.empty(len(first), dtype=np.int64)
    for new_id, w in enumerate(vocab):
        remap[first[w]] = new_id
    term = remap[np.asarray(words, dtype=np.int64)]
    rows_a = np.asarray(rows, dtype=np.int32)
    order = np.lexsort((rows_a, term))
    indptr = np.zeros(len(vocab) + 1, dtype=np.int64)
    np.cumsum(np.bincount(term, minlength=len(vocab)), out=indptr[1:])
    return vocab, indptr, rows_a[order], np.asarray(counts, dtype=np.int32)[order], lengths


class Index:
    """Items ({id, text, ...}) with int8 vectors and BM25 statistics.

    A search is exact and reads each item once: BM25 reads only the postings of the query's words (an inverted index,
    saved beside the index as ``<stem>.terms``), the cosine is the int8 product computed in float32 blocks (exact, since
    the integer sums of int8 products stay below 2**24) over vector norms computed once (the float32 vectors are kept
    for the next queries when they fit CACHE_BYTES), and only the best candidates are sorted. Scores and order are those of the plain definitions, ties broken by item id."""

    def __init__(self, items: list[dict], vectors, embedder_id: str, graph_sha256: str | None = None, terms=None):
        np = _np()
        self.items, self.vectors, self.embedder_id = items, vectors, embedder_id
        self.graph_sha256 = graph_sha256            # the document it was built from, when recorded
        self.vocab, self.indptr, self.post_item, self.post_count, self.lengths = terms or _terms(items)
        self.term_id = {w: i for i, w in enumerate(self.vocab)}
        n = len(items)
        self.avg = (int(self.lengths.sum()) / n) if n else 0.0
        self.norms = np.ones(n)
        for lo in range(0, n, BLOCK):
            self.norms[lo:lo + BLOCK] = np.linalg.norm(vectors[lo:lo + BLOCK].astype(np.float64), axis=1)
        self.norms[self.norms == 0] = 1.0
        self._id_rank = None
        self._converted = None                      # the vectors as float32, kept after a first cosine when they fit

    @classmethod
    def build(cls, items: list[dict], embedder="scale-hash-v1", graph_sha256: str | None = None) -> "Index":
        emb = get_embedder(embedder) if isinstance(embedder, str) else embedder
        vec = quantize(emb.encode([i["text"] for i in items])) if items else _np().zeros((0, getattr(emb, "dim", 1)), dtype="int8")
        return cls(items, vec, emb.id, graph_sha256)

    def save(self, stem: Path) -> None:
        np = _np()
        stem.parent.mkdir(parents=True, exist_ok=True)
        vec_bytes = np.ascontiguousarray(self.vectors, dtype=np.int8).tobytes()
        lines = [json.dumps({"embedder": self.embedder_id, "count": len(self.items),
                             "dim": int(self.vectors.shape[1]) if len(self.items) else 0,
                             "vectors_sha256": hashlib.sha256(vec_bytes).hexdigest(),   # binds the .i8 rows to these items
                             **({"graph_sha256": self.graph_sha256} if self.graph_sha256 else {})}, sort_keys=True)]
        lines += [json.dumps(it, ensure_ascii=False, sort_keys=True) for it in self.items]
        raw = ("\n".join(lines) + "\n").encode("utf-8")
        Path(f"{stem}.jsonl").write_bytes(raw)
        Path(f"{stem}.i8").write_bytes(vec_bytes)
        payload = b"".join(np.ascontiguousarray(a, dtype=t).tobytes() for a, t in (
            (self.indptr, np.int64), (self.post_item, np.int32), (self.post_count, np.int32), (self.lengths, np.int64)))
        head = json.dumps({"items_sha256": hashlib.sha256(raw).hexdigest(), "count": len(self.items),
                           "words": len(self.vocab), "postings": int(len(self.post_item)), "vocab": self.vocab,
                           "payload_sha256": hashlib.sha256(payload).hexdigest()},
                          ensure_ascii=False, sort_keys=True).encode("utf-8")
        with open(f"{stem}.terms", "wb") as f:
            f.write(TERMS_MAGIC + len(head).to_bytes(8, "little") + head + payload)

    @classmethod
    def load(cls, stem: Path) -> "Index":
        np = _np()
        raw = Path(f"{stem}.jsonl").read_bytes()
        lines = raw.decode("utf-8").splitlines()
        head, items = json.loads(lines[0]), [json.loads(x) for x in lines[1:]]
        vec_bytes = Path(f"{stem}.i8").read_bytes() if Path(f"{stem}.i8").exists() else b""
        count, dim = len(items), int(head.get("dim") or 0)
        if head.get("vectors_sha256") == hashlib.sha256(vec_bytes).hexdigest() and len(vec_bytes) == count * dim:
            raw_vec = np.frombuffer(vec_bytes, dtype=np.int8)
            vec = raw_vec.reshape(count, dim) if count else raw_vec.reshape(0, max(dim, 1))
        else:       # vectors that are not the ones saved with these items (or a file saved before the digest): rebuilt
            emb = get_embedder(head["embedder"])
            vec = quantize(emb.encode([i["text"] for i in items])) if items else _np().zeros((0, getattr(emb, "dim", 1)), dtype="int8")
        return cls(items, vec, head["embedder"], head.get("graph_sha256"), _read_terms(stem, raw, len(items)))

    def check_for(self, doc: dict, where: str = "the evidence index") -> "Index":
        """This index, when it may be searched for ``doc``: one holding exactly its evidence items
        (:func:`evidence_items`), whatever digest its header records (a header is no proof of what the index holds);
        otherwise a :class:`ScaleError` that says to rebuild it."""
        if self.items == evidence_items(doc):
            return self
        digest = graph_sha256(doc)
        built = ("records this document's digest but not its quotes" if self.graph_sha256 == digest else
                 f"was built from another document (graph_sha256 {self.graph_sha256[:12]}, this one {digest[:12]})"
                 if self.graph_sha256 else "records no document digest")
        raise ScaleError(f"{where} {built} and does not hold exactly this document's evidence quotes, so it is not "
                         "searched for it (its text could be another document's, or stale); rebuild it with `scale graph "
                         "index <document>`")

    def bm25(self, query: str, k1: float = 1.2, b: float = 0.75):
        np = _np()
        n = len(self.items)
        s = np.zeros(n)
        for w in sorted(set(tokens(query))):
            t = self.term_id.get(w)
            if t is None:
                continue
            lo, hi = int(self.indptr[t]), int(self.indptr[t + 1])
            df = hi - lo
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            rows, f = self.post_item[lo:hi], self.post_count[lo:hi].astype(np.float64)
            s[rows] += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * self.lengths[rows] / (self.avg or 1)))
        return s

    def cosine(self, query: str, embedder=None):
        np = _np()
        emb = embedder or get_embedder(self.embedder_id)
        if emb.id != self.embedder_id:
            raise ScaleError(f"index built with {self.embedder_id}, query embedder is {emb.id}")
        qv = quantize(emb.encode([query]))[0]
        n, dim = self.vectors.shape
        # int8 products summed in float32 are exact while every partial sum stays below 2**24
        exact = np.float32 if dim * 127 * 127 < 2 ** 24 else np.float64
        q = qv.astype(exact)
        if self._converted is None and exact is np.float32 and n * dim * 4 <= CACHE_BYTES:
            self._converted = self.vectors.astype(np.float32)
        if self._converted is not None:
            dots = (self._converted @ q).astype(np.float64)
        else:
            dots = np.empty(n)
            for lo in range(0, n, BLOCK):
                dots[lo:lo + BLOCK] = self.vectors[lo:lo + BLOCK].astype(exact) @ q
        return dots / (self.norms * (np.linalg.norm(qv.astype(np.float64)) or 1.0))

    def _ids(self):
        """Each item's position in item-id order (the tie-break of every ranking), computed once."""
        np = _np()
        if self._id_rank is None:
            order = sorted(range(len(self.items)), key=lambda i: self.items[i]["id"])
            self._id_rank = np.empty(len(self.items), dtype=np.int64)
            self._id_rank[order] = np.arange(len(self.items))
        return self._id_rank

    def ranked(self, score, m: int):
        """The (at most) ``m`` items of positive score, best first and ties by item id, exactly the head of a full sort:
        every item tied with the m-th best is a candidate before the candidates are sorted."""
        np = _np()
        pos = np.flatnonzero(score > 0)
        if m < 1:
            return pos[:0]
        if m < len(pos):
            cut = np.partition(score[pos], len(pos) - m)[len(pos) - m]
            pos = pos[score[pos] >= cut]
        return pos[np.lexsort((self._ids()[pos], -score[pos]))][:m]

    def search(self, query: str, k: int = 10, mode: str = "hybrid", where: Callable[[dict], bool] | None = None) -> list[dict]:
        """The best ``k`` items for ``query`` that ``where`` keeps. hybrid: the mean of BM25 scaled to its best and the
        cosine (negative counted as 0); vector, keyword: one of them; rrf: reciprocal rank fusion of the BM25 and
        cosine rankings (each read to RRF_DEPTH, or twice ``k``, among the items ``where`` keeps), sum of
        1 / (RRF_K + rank), at most 2 / 61."""
        np = _np()
        if not isinstance(k, int) or isinstance(k, bool) or k < 1:
            raise ScaleError(f"k is how many hits to return, a whole number of at least 1 (got {k!r})")
        if not self.items:
            return []
        if mode not in MODES:
            raise ScaleError("mode is hybrid, vector, keyword or rrf")
        n = len(self.items)
        kw = self.bm25(query) if mode != "vector" else np.zeros(n)
        vc = self.cosine(query) if mode != "keyword" else np.zeros(n)
        if mode == "rrf":
            score = np.zeros(n)
            # with a filter, both rankings are of the items it keeps: read to a depth, a ranking of every item could
            # hold none of them though some match
            keep = np.fromiter((bool(where(it)) for it in self.items), dtype=bool, count=n) if where else None
            for s in (kw, vc):
                top = self.ranked(np.where(keep, s, 0.0) if where else s, max(RRF_DEPTH, 2 * k))
                score[top] += 1.0 / (RRF_K + np.arange(1, len(top) + 1))
        elif mode == "hybrid":
            kwn = kw / kw.max() if kw.max() > 0 else kw
            score = 0.5 * kwn + 0.5 * np.clip(vc, 0, None)
        else:
            score = vc if mode == "vector" else kw
        m = k
        while True:                                 # widen until k items pass where, or every positive item is read
            top = self.ranked(score, m)
            out = []
            for i in top:
                if where and not where(self.items[i]):
                    continue
                out.append({**self.items[i], "score": round(float(score[i]), 4), "keyword": round(float(kw[i]), 4),
                            "cosine": round(float(vc[i]), 4)})
                if len(out) >= k:
                    return out
            if len(top) < m:
                return out
            m *= 4


def _read_terms(stem: Path, items_raw: bytes, count: int):
    """The inverted index saved at ``<stem>.terms``, or None (then it is rebuilt from the items) when there is none, it
    was not saved with exactly these items, its arrays do not match the digest it records, or they do not form an
    inverted index of these items (offsets that run up to the postings, rows within the items, counts above zero)."""
    np = _np()
    p = Path(f"{stem}.terms")
    if not p.exists():
        return None
    data = p.read_bytes()
    if not data.startswith(TERMS_MAGIC):
        return None
    at = len(TERMS_MAGIC)
    try:
        size = int.from_bytes(data[at:at + 8], "little")
        head = json.loads(data[at + 8:at + 8 + size].decode("utf-8"))
        words, postings, vocab = int(head["words"]), int(head["postings"]), head["vocab"]
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return None
    if head.get("count") != count or head.get("items_sha256") != hashlib.sha256(items_raw).hexdigest():
        return None
    at += 8 + size
    if head.get("payload_sha256") != hashlib.sha256(data[at:]).hexdigest():
        return None                                   # the arrays changed since they were saved (or an older file)
    out = []
    for t, length in ((np.int64, words + 1), (np.int32, postings), (np.int32, postings), (np.int64, count)):
        nbytes = length * np.dtype(t).itemsize
        out.append(np.frombuffer(data[at:at + nbytes], dtype=t))
        at += nbytes
    indptr, rows, counts, lengths = out
    if at != len(data) or not isinstance(vocab, list) or len(vocab) != words or vocab != sorted(set(vocab)):
        return None
    if words + 1 != len(indptr) or indptr[0] != 0 or indptr[-1] != postings or (np.diff(indptr) < 0).any():
        return None
    if postings and (rows.min() < 0 or rows.max() >= count or counts.min() < 1):
        return None
    return (vocab, *out)


def graph_sha256(doc: dict) -> str:
    """The digest of a document as a query result names it (``graph_sha256``) and an index records it."""
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_for(stem: Path, doc: dict) -> Index:
    """The evidence index at ``stem`` (``<stem>.jsonl``, ``<stem>.i8``, ``<stem>.terms``) for ``doc``, refused unless it may be searched
    for it (:meth:`Index.check_for`)."""
    return Index.load(stem).check_for(doc, f"the evidence index {Path(f'{stem}.jsonl').name}")


def index_for(stem: Path, doc: dict) -> Index:
    """The evidence index of ``doc``: the one saved at ``stem`` (:func:`load_for`, refused unless it is ``doc``'s), or,
    when none is saved there, one built in memory from ``doc`` with the default embedder (deterministic, so the same as
    ``scale graph index`` would save; nothing is written)."""
    if Path(f"{stem}.jsonl").exists():
        return load_for(stem, doc)
    return Index.build(evidence_items(doc), graph_sha256=graph_sha256(doc))


def evidence_items(doc: dict) -> list[dict]:
    """One item per evidence quote on a node or link: {id, record, evidence, source, locator, passage, text}."""
    out = []
    for rec in sorted(doc.get("nodes", []) + doc.get("links", []), key=lambda r: str(r["id"])):
        for i, ev in enumerate((rec.get("props") or {}).get("evidence") or []):
            text = ev.get("quote") or ""
            if not text:
                continue
            item = {"id": f"{rec['id']}#evidence/{i}", "record": rec["id"], "label": rec.get("label") or rec.get("type"),
                    "evidence": i, "source": ev.get("source"), "locator": ev.get("locator"), "text": text}
            if ev.get("passage"):
                item["passage"] = ev["passage"]
            out.append(item)
    return out
