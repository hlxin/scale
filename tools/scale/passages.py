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
result names). :func:`load_for` uses an index for a document only when it was built from that document, or (an
index built before the digest was recorded, or before an edit that changed no quote) when it holds exactly the
document's evidence items: an index built from another document, a less open one or a stale copy, is refused, so no
text the document does not hold is searched or chooses a query's rows.
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

    def features(self, text: str) -> Counter:
        ws = tokens(text)
        f: Counter = Counter()
        for w in ws:
            f["w:" + w] += 1.0
            padded = f"<{w}>"
            if len(padded) > 4:
                for i in range(len(padded) - 3):
                    f["c:" + padded[i:i + 4]] += 0.5
        for a, b in zip(ws, ws[1:]):
            f["b:" + a + " " + b] += 1.0
        return f

    def encode(self, texts: list[str]):
        np = _np()
        out = np.zeros((len(texts), self.dim), dtype=np.float64)
        for r, t in enumerate(texts):
            for feat, tf in sorted(self.features(t).items()):
                h = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
                idx = int.from_bytes(h[:4], "little") % self.dim
                sign = 1.0 if h[4] & 1 else -1.0
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
class Index:
    """Items ({id, text, ...}) with int8 vectors and BM25 statistics."""

    def __init__(self, items: list[dict], vectors, embedder_id: str, graph_sha256: str | None = None):
        self.items, self.vectors, self.embedder_id = items, vectors, embedder_id
        self.graph_sha256 = graph_sha256            # the document it was built from, when recorded
        self.tf = [Counter(tokens(i["text"])) for i in items]
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = (sum(self.len) / len(self.len)) if self.len else 0.0
        self.df: Counter = Counter()
        for c in self.tf:
            self.df.update(c.keys())

    @classmethod
    def build(cls, items: list[dict], embedder="scale-hash-v1", graph_sha256: str | None = None) -> "Index":
        emb = get_embedder(embedder) if isinstance(embedder, str) else embedder
        vec = quantize(emb.encode([i["text"] for i in items])) if items else _np().zeros((0, getattr(emb, "dim", 1)), dtype="int8")
        return cls(items, vec, emb.id, graph_sha256)

    def save(self, stem: Path) -> None:
        np = _np()
        stem.parent.mkdir(parents=True, exist_ok=True)
        with open(f"{stem}.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps({"embedder": self.embedder_id, "count": len(self.items),
                                "dim": int(self.vectors.shape[1]) if len(self.items) else 0,
                                **({"graph_sha256": self.graph_sha256} if self.graph_sha256 else {})},
                               sort_keys=True) + "\n")
            for it in self.items:
                f.write(json.dumps(it, ensure_ascii=False, sort_keys=True) + "\n")
        with open(f"{stem}.i8", "wb") as f:
            f.write(np.ascontiguousarray(self.vectors, dtype=np.int8).tobytes())

    @classmethod
    def load(cls, stem: Path) -> "Index":
        np = _np()
        lines = Path(f"{stem}.jsonl").read_text(encoding="utf-8").splitlines()
        head, items = json.loads(lines[0]), [json.loads(x) for x in lines[1:]]
        raw = np.frombuffer(Path(f"{stem}.i8").read_bytes(), dtype=np.int8)
        vec = raw.reshape(head["count"], head["dim"]) if head["count"] else raw.reshape(0, max(head["dim"], 1))
        return cls(items, vec, head["embedder"], head.get("graph_sha256"))

    def check_for(self, doc: dict, where: str = "the evidence index") -> "Index":
        """This index, when it may be searched for ``doc``: built from it (its ``graph_sha256``), or holding exactly its
        evidence items (:func:`evidence_items`); otherwise a :class:`ScaleError` that says to rebuild it."""
        if self.graph_sha256 and self.graph_sha256 == graph_sha256(doc):
            return self
        if self.items == evidence_items(doc):
            return self
        built = (f"was built from another document (graph_sha256 {self.graph_sha256[:12]}, this one "
                 f"{graph_sha256(doc)[:12]})" if self.graph_sha256 else "records no document digest")
        raise ScaleError(f"{where} {built} and does not hold exactly this document's evidence quotes, so it is not "
                         "searched for it (its text could be another document's, or stale); rebuild it with `scale graph "
                         "index <document>`")

    def bm25(self, query: str, k1: float = 1.2, b: float = 0.75):
        np = _np()
        q = tokens(query)
        n = len(self.items)
        s = np.zeros(n)
        for w in set(q):
            if not self.df.get(w):
                continue
            idf = math.log(1 + (n - self.df[w] + 0.5) / (self.df[w] + 0.5))
            for i, c in enumerate(self.tf):
                f = c.get(w)
                if f:
                    s[i] += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * self.len[i] / (self.avg or 1)))
        return s

    def cosine(self, query: str, embedder=None):
        np = _np()
        emb = embedder or get_embedder(self.embedder_id)
        if emb.id != self.embedder_id:
            raise ScaleError(f"index built with {self.embedder_id}, query embedder is {emb.id}")
        qv = quantize(emb.encode([query])).astype(np.float64)[0]
        m = self.vectors.astype(np.float64)
        norms = np.linalg.norm(m, axis=1)
        norms[norms == 0] = 1.0
        return m @ qv / (norms * (np.linalg.norm(qv) or 1.0))

    def search(self, query: str, k: int = 10, mode: str = "hybrid", where: Callable[[dict], bool] | None = None) -> list[dict]:
        np = _np()
        if not self.items:
            return []
        if mode not in ("hybrid", "vector", "keyword"):
            raise ScaleError("mode is hybrid, vector or keyword")
        kw = self.bm25(query) if mode != "vector" else np.zeros(len(self.items))
        vc = self.cosine(query) if mode != "keyword" else np.zeros(len(self.items))
        kwn = kw / kw.max() if kw.max() > 0 else kw
        score = {"hybrid": 0.5 * kwn + 0.5 * np.clip(vc, 0, None), "vector": vc, "keyword": kw}[mode]
        order = sorted(range(len(self.items)), key=lambda i: (-score[i], self.items[i]["id"]))
        out = []
        for i in order:
            if where and not where(self.items[i]):
                continue
            if score[i] <= 0:
                break
            out.append({**self.items[i], "score": round(float(score[i]), 4), "keyword": round(float(kw[i]), 4),
                        "cosine": round(float(vc[i]), 4)})
            if len(out) >= k:
                break
        return out


def graph_sha256(doc: dict) -> str:
    """The digest of a document as a query result names it (``graph_sha256``) and an index records it."""
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_for(stem: Path, doc: dict) -> Index:
    """The evidence index at ``stem`` (``<stem>.jsonl``, ``<stem>.i8``) for ``doc``, refused unless it may be searched
    for it (:meth:`Index.check_for`)."""
    return Index.load(stem).check_for(doc, f"the evidence index {Path(f'{stem}.jsonl').name}")


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
