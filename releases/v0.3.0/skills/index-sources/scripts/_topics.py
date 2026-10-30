"""Topic vocabulary: each source's Topic A/B/C (its three main topics) and Related topics (library module).

The vocabulary is the domain's, not the skill's (vocab_path: a path given, $INDEX_SOURCES_VOCAB, the project's
.scripts/vocab.json, else SCALE's catalysis vocabulary in graphs/catal-commons/literature/vocabulary.json when the
skill runs from a checkout of hlxin/scale). A project can add or override terms in .scripts/vocab_custom.json (same shape: {"terms": [{"id", "label", "name", "facet", "synonyms", "related", "weight"}]}).

Deterministic assignment (no model): synonyms are matched on word tokens of the title (x3), keywords (x2) and abstract
(x1); a longer synonym consumes its words so "electrochemical ammonia synthesis" counts for NRR, not for thermal
ammonia synthesis. Topic A/B/C = the three best-scoring terms with score >= 1. Related topics = other terms the source
matches plus the vocabulary neighbours of A/B/C (CO2RR -> CORR, OER -> ORR ...).
Claude / API screening assigns A/B/C itself from the same vocabulary; Related topics are completed the same way.
"""
import json
import os
import re
from pathlib import Path

from _common import clean_text, json_read

SKILL = Path(__file__).resolve().parents[1]
COMMONS = SKILL.parents[1] / "graphs" / "catal-commons" / "literature" / "vocabulary.json"   # SCALE's catalysis one
FIELD_W = {"title": 3.0, "keywords": 2.0, "abstract": 1.0}
MIN_SCORE = 1.0
MAX_RELATED = 6
FACET_ORDER = {"reaction": 0, "material": 1, "method": 2, "system": 3}
FACET_W = {"reaction": 1.15, "material": 1.0, "method": 0.9, "system": 0.9}   # near-ties: what is catalyzed comes first
METHOD_RANK = {"vocab": 0, "api": 1, "claude": 2, "manual": 3}   # a better method is never overwritten by a lesser one

_DASHES = str.maketrans({"–": "-", "—": "-", "‐": "-", "‑": "-", "−": "-", "₂": "2", "₃": "3", "₄": "4", "₅": "5",
                         "₆": "6", "⁺": "+", "⁻": "-", " ": " "})
_TOK = re.compile(r"[A-Za-z0-9]+")


def norm_text(t):
    return re.sub(r"\s+", " ", clean_text(t or "").translate(_DASHES)).strip()


def _tok_cs(tok):
    """Case-sensitive token: element symbols and other short capitalized tokens (Cu, Co, M), anything with an inner
    capital (CO2, MOF, Ti3C2) or a digit. Ordinary words (Electrochemical, water) compare case-insensitively."""
    return (len(tok) <= 2 and tok[0].isupper()) or any(c.isupper() for c in tok[1:]) or any(c.isdigit() for c in tok)


def _tok_match(want, got, last):
    if _tok_cs(want):
        if got == want:
            return True
        if want.isupper() and len(want) >= 2 and got == want + "s":      # MOFs, SACs, CNTs
            return True
        if last and got.startswith(want) and len(got) > len(want) and got[len(want)].isupper():  # Ti3C2 -> Ti3C2Tx
            return True
        return False
    g, w = got.lower(), want.lower()
    if g == w:
        return True
    return last and len(w) >= 4 and g.startswith(w)                       # frameworks, zeolites, alloying


def vocab_path(proj=None, path=None):
    """The topic vocabulary to use: `path`, else $INDEX_SOURCES_VOCAB, else the project's .scripts/vocab.json, else the
    catalysis vocabulary of the SCALE checkout the skill runs from."""
    for cand in (path, os.environ.get("INDEX_SOURCES_VOCAB"), proj.scr / "vocab.json" if proj is not None else None,
                 COMMONS):
        if cand and Path(cand).is_file():
            return Path(cand)
    raise FileNotFoundError("no topic vocabulary: put one at .scripts/vocab.json or name it in INDEX_SOURCES_VOCAB "
                            "(SCALE's catalysis vocabulary: graphs/catal-commons/literature/vocabulary.json)")


class Vocab:
    def __init__(self, proj=None, path=None):
        data = json.loads(vocab_path(proj, path).read_text())
        self.name = data.get("name", "vocabulary")
        terms = {t["id"]: dict(t) for t in data["terms"]}
        order = [t["id"] for t in data["terms"]]
        if proj is not None:
            custom = json_read(proj.scr / "vocab_custom.json") or {}
            for t in custom.get("terms") or []:
                if t.get("id") and t.get("label"):
                    if t["id"] not in terms:
                        order.append(t["id"])
                    base = terms.get(t["id"], {"synonyms": [], "related": [], "weight": 1.0, "facet": "reaction"})
                    terms[t["id"]] = {**base, **t}
        self.terms, self.order = terms, order
        self.index = {}
        for tid in order:
            t = terms[tid]
            for key in [tid, t["label"], t.get("name", "")] + [s for s in t.get("synonyms") or [] if not s.startswith("re:")]:
                if key:
                    self.index.setdefault(key.lower(), tid)
        self._compile()

    # ------------------------------------------------------------ lookup
    def resolve(self, x):
        """Term id for an id, label, long name or synonym (case-insensitive); None when unknown."""
        if not x:
            return None
        return self.index.get(str(x).strip().lower())

    def label(self, tid):
        if tid in self.terms:
            return self.terms[tid]["label"]
        return tid.split(":", 1)[1] if tid.startswith("new:") else tid

    def facet(self, tid):
        return (self.terms.get(tid) or {}).get("facet", "")

    def compact_list(self):
        """'label — name' lines grouped by facet, for prompts."""
        out = []
        for facet in FACET_ORDER:
            ids = [i for i in self.order if self.terms[i].get("facet") == facet]
            if ids:
                out.append(f"[{facet}] " + "; ".join(f"{self.terms[i]['label']}" for i in ids))
        return "\n".join(out)

    # ------------------------------------------------------------ matching
    def _compile(self):
        self.first = {}          # first token (lower) -> [(tokens, tid)] longest first
        self.regexes = []
        for tid in self.order:
            for s in self.terms[tid].get("synonyms") or []:
                if s.startswith("re:"):
                    self.regexes.append((re.compile(s[3:]), tid))
                    continue
                toks = _TOK.findall(s.translate(_DASHES))
                if toks:
                    self.first.setdefault(toks[0].lower(), []).append((toks, tid))
        for k in self.first:
            self.first[k].sort(key=lambda x: -sum(len(t) for t in x[0]))

    def _count(self, text):
        counts = {}
        if not text:
            return counts
        toks = _TOK.findall(text)
        i, n = 0, len(toks)
        while i < n:
            best = None
            for want, tid in self.first.get(toks[i].lower(), ()):
                L = len(want)
                if i + L <= n and all(_tok_match(want[k], toks[i + k], k == L - 1) for k in range(L)):
                    best = (L, tid)
                    break
            if best:
                counts[best[1]] = counts.get(best[1], 0) + 1
                i += best[0]
            else:
                i += 1
        for rx, tid in self.regexes:
            c = len(rx.findall(text))
            if c:
                counts[tid] = counts.get(tid, 0) + c
        return counts

    def scores(self, title, abstract="", keywords=None):
        kw = "; ".join(keywords) if isinstance(keywords, (list, tuple)) else (keywords or "")
        sc = {}
        for field, text in (("title", title), ("keywords", kw), ("abstract", abstract)):
            for tid, c in self._count(norm_text(text)).items():
                w = float(self.terms[tid].get("weight", 1.0)) * FACET_W.get(self.terms[tid].get("facet"), 1.0)
                sc[tid] = sc.get(tid, 0.0) + FIELD_W[field] * min(c, 3) * w
        return sc

    def rank(self, sc):
        return sorted((t for t, v in sc.items() if v >= MIN_SCORE),
                      key=lambda t: (-sc[t], FACET_ORDER.get(self.facet(t), 9), self.order.index(t) if t in self.order else 999))

    def related_for(self, main, extra=()):
        out = []
        for t in list(extra) + [r for m in main for r in (self.terms.get(m) or {}).get("related") or []]:
            if t not in main and t not in out:
                out.append(t)
        return out[:MAX_RELATED]

    def assign(self, title, abstract="", keywords=None):
        """-> {"main": [ids up to 3], "related": [ids], "scores": {id: score}}"""
        sc = self.scores(title, abstract, keywords)
        ranked = self.rank(sc)
        main = ranked[:3]
        return {"main": main, "related": self.related_for(main, ranked[3:]), "scores": {t: round(sc[t], 2) for t in ranked}}

    def from_model(self, names, extra=(), title="", abstract="", keywords=None):
        """Topics chosen by Claude / an API model -> ids. Unknown names are kept as 'new:<name>' (proposed terms)."""
        main = []
        for n in names or []:
            tid = self.resolve(n) or ("new:" + clean_text(str(n))[:60] if str(n).strip() else None)
            if tid and tid not in main:
                main.append(tid)
        main = main[:3]
        ext = [self.resolve(n) for n in extra or []]
        sc = self.scores(title, abstract, keywords)
        ranked = [t for t in self.rank(sc) if t not in main]
        if not main:  # the model gave nothing usable: fall back to the vocabulary match
            main, ranked = ranked[:3], ranked[3:]
        return {"main": main, "related": self.related_for(main, [e for e in ext if e] + ranked),
                "scores": {t: round(sc.get(t, 0), 2) for t in main}}


def apply_vocab(led, vocab, rows, only_missing=False):
    """Deterministic Topic A/B/C + Related for `rows` (ledger rows). Sources whose topics came from Claude, an API model
    or a person keep them. Returns the number of sources written."""
    have, before = {}, {}
    ids = [p["id"] for p in rows]
    for i in range(0, len(ids), 900):     # only the given sources (a topic may hold millions)
        ch = ids[i:i + 900]
        qs = ",".join("?" * len(ch))
        for pid, m in led.q(f"SELECT source_id, MAX(method) FROM source_subjects WHERE kind='main' AND source_id IN ({qs}) "
                            "GROUP BY source_id", tuple(ch)):
            have[pid] = m
        for pid, term, rank in led.q(f"SELECT source_id, term, rank FROM source_subjects WHERE kind='main' AND source_id IN "
                                     f"({qs}) ORDER BY source_id, rank", tuple(ch)):
            before.setdefault(pid, []).append(term)
    n = 0
    apply_vocab.changed = 0
    with led.tx():
        for p in rows:
            m = have.get(p["id"])
            if m and (only_missing or METHOD_RANK.get(m, 0) > 0):
                continue
            a = vocab.assign(p.get("title"), p.get("abstract"), p.get("keywords"))
            if led.set_subjects(p["id"], a["main"], a["related"], "vocab", a["scores"]):
                n += 1
                if before.get(p["id"]) and before[p["id"]] != a["main"][:3]:
                    apply_vocab.changed += 1
    return n
