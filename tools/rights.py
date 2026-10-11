"""Publication rights of committed documents: who may see them, and how much of a source they quote.

Two rules, both run by ``scale check``:

* **Access.** Every scale-catal document committed to the repository is public: the effective stewardship
  access of its graph and of each record (the graph's default overridden field by field by the record's own,
  ``pgraph.effective_stewardship``) is ``public``, stated explicitly. A missing access is not public: SCALE's
  visibility rule (``pgraph.visible``) reads it as ``institution``, so a document without one would be hidden
  from the public by the tools while the repository publishes it. Project data is never
  committed: it stays outside the repository until it is cleared for publication.
* **Copyright cap.** A document holding research data (``data_status`` other than ``synthetic_example``) quotes
  its sources only as far as their rights allow. Each folder with such documents has a ``rights.yaml`` (the
  nearest one in the document's folder or above, within the repository)::

      sources:
        <source id>: {class: public_domain | open | restricted | in_copyright | synthetic,
                      licence: <SPDX id or text>, basis: <why>, text_chars: <int, optional>}

  A source without an entry counts as ``in_copyright``. For ``restricted`` and ``in_copyright`` sources each
  quoted text (``quote``, ``transcription``, ``second_reading``) is at most 300 characters, and the distinct
  quoted characters of one source are at most 4,000 and at most 10 % of ``text_chars`` when it is known.
  Public-domain, open and synthetic sources have no cap (their quotes are still only text found verbatim).

A text beyond the cap is **withheld**: the evidence item keeps its source, locator, kind (and passage, region);
the text field is removed and ``note`` records ``<field> withheld: sha256:<hex> chars:<n>``, the digest and length
of the text under the verbatim checker's normalization (``util.match_text``), appended with ``"; "`` to a note
it already has. The encoding is valid under every schema version (no kernel change), and anyone holding the
source text restores the text (``rehydrate``) by sliding a window of that length over the normalized text.

Distinct characters: each quoted text counts once per source (equal under the normalization), a text contained
in a longer quoted text of the same source counts nothing, and a text counts its length as written.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import re
import unicodedata
from pathlib import Path

from . import layout
from .util import ScaleError, load_doc, load_yaml, match_text

RIGHTS_FILE = "rights.yaml"
CLASSES = ("public_domain", "open", "restricted", "in_copyright", "synthetic")
CAPPED = ("restricted", "in_copyright")
UNKNOWN_CLASS = "in_copyright"
TEXT_FIELDS = ("quote", "transcription", "second_reading")
ITEM_MAX = 300              # characters of one quoted text
SOURCE_MAX = 4000           # distinct quoted characters of one source
SHARE_MAX = 0.10            # of the source's text_chars, when known
WITHHELD = re.compile(r"\b(quote|transcription|second_reading) withheld: sha256:([0-9a-f]{64}) chars:(\d+)")


# ---------------------------------------------------------------- rights files
def load_rights(path: str | Path) -> dict[str, dict]:
    """The ``sources`` of a rights file, checked: every entry names a known class, a licence and a basis."""
    data = load_yaml(Path(path)) or {}
    if not isinstance(data, dict) or set(data) - {"sources"} or not isinstance(data.get("sources"), dict):
        raise ScaleError(f"{path}: a rights file holds one key, sources: {{<source id>: {{class, licence, basis}}}}")
    out = {}
    for sid, e in data["sources"].items():
        where = f"{path}: sources.{sid}"
        if not isinstance(e, dict) or set(e) - {"class", "licence", "basis", "text_chars"}:
            raise ScaleError(f"{where}: keys are class, licence, basis and (optional) text_chars")
        if e.get("class") not in CLASSES:
            raise ScaleError(f"{where}: class must be one of {', '.join(CLASSES)}")
        for k in ("licence", "basis"):
            if not isinstance(e.get(k), str) or not e[k].strip():
                raise ScaleError(f"{where}: {k} is required (an SPDX id or a text for the licence; why for the basis)")
        if "text_chars" in e and (not isinstance(e["text_chars"], int) or isinstance(e["text_chars"], bool) or e["text_chars"] <= 0):
            raise ScaleError(f"{where}: text_chars is a positive integer (the characters of the source's text)")
        out[str(sid)] = dict(e)
    return out


def rights_file(doc_path: str | Path, repo: str | Path | None = None) -> Path | None:
    """The rights file that covers a document: the nearest ``rights.yaml`` in its folder or above (not above the
    repository root, when one is given)."""
    p = Path(doc_path).resolve().parent
    stop = Path(repo).resolve() if repo else None
    for d in [p, *p.parents]:
        if (d / RIGHTS_FILE).is_file():
            return d / RIGHTS_FILE
        if stop is not None and d == stop:
            break
    return None


def source_rights(rights: dict[str, dict], sid: str) -> dict:
    return rights.get(sid) or {"class": UNKNOWN_CLASS, "licence": "unknown", "basis": "no rights entry: in copyright"}


def limit(entry: dict) -> int | None:
    """The distinct-character cap of a source (None: no cap)."""
    if entry["class"] not in CAPPED:
        return None
    return min(SOURCE_MAX, int(SHARE_MAX * entry["text_chars"])) if entry.get("text_chars") else SOURCE_MAX


# ---------------------------------------------------------------- quoted text
def digest(text: str) -> tuple[str, int]:
    """sha256 and length of a text under the verbatim checker's normalization."""
    n = match_text(text)
    return hashlib.sha256(n.encode("utf-8")).hexdigest(), len(n)


def items(doc: dict):
    """Every evidence item of a document: (record, record id, index, item)."""
    for rec in doc.get("nodes", []) + doc.get("links", []):
        for i, ev in enumerate((rec.get("props") or {}).get("evidence") or []):
            if isinstance(ev, dict):
                yield rec, str(rec.get("id")), i, ev


def distinct_chars(texts: list[str]) -> int:
    """Distinct quoted characters: equal texts (normalized) once, texts inside a longer one not at all."""
    by_norm: dict[str, str] = {}
    for t in texts:
        by_norm.setdefault(match_text(t), t)
    keys = sorted(by_norm, key=len, reverse=True)
    kept: list[str] = []
    for k in keys:
        if not any(k in o for o in kept):
            kept.append(k)
    return sum(len(by_norm[k]) for k in kept)


def _numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _values(o):
    """The value objects (status + a number) inside a record's properties."""
    if isinstance(o, dict):
        if "status" in o and any(_numeric(o.get(k)) for k in ("value", "lower", "upper")):
            yield o
        for k, v in o.items():
            if k != "evidence":
                yield from _values(v)
    elif isinstance(o, list):
        for v in o:
            yield from _values(v)


def quantitative(rec: dict, ev: dict) -> bool:
    """Whether an evidence item supports a quantitative value: a value of its record cites it (``evidence_ids``),
    or, where no value of the record names its evidence, the record states a value at all."""
    vals = list(_values(rec.get("props") or {}))
    named = [v for v in vals if v.get("evidence_ids")]
    if named:
        return bool(ev.get("id")) and any(ev["id"] in (v.get("evidence_ids") or []) for v in named)
    return bool(vals)


def withheld(ev: dict) -> list[tuple[str, str, int]]:
    """The withheld texts an evidence item records in its note: (field, sha256, normalized length)."""
    return [(m.group(1), m.group(2), int(m.group(3))) for m in WITHHELD.finditer(str(ev.get("note") or ""))]


# ---------------------------------------------------------------- report
def report(doc: dict, rights: dict[str, dict]) -> dict:
    """Per source: its class and licence, its quoted texts and the withheld ones, its distinct quoted characters
    against its cap, and the violations. Sources without a rights entry are listed apart (an error for a check)."""
    by_src: dict[str, list[str]] = {}
    held: dict[str, int] = {}
    longest: dict[str, int] = {}
    for _, _, _, ev in items(doc):
        sid = str(ev.get("source"))
        for f in TEXT_FIELDS:
            if isinstance(ev.get(f), str) and ev[f]:
                by_src.setdefault(sid, []).append(ev[f])
                longest[sid] = max(longest.get(sid, 0), len(ev[f]))
        if withheld(ev):
            held[sid] = held.get(sid, 0) + len(withheld(ev))
    sources = sorted({n["id"] for n in doc.get("nodes", []) if n.get("label") == "Source"} | set(by_src) | set(held))
    rows, problems = {}, []
    for sid in sources:
        e = source_rights(rights, sid)
        texts = by_src.get(sid, [])
        cap = limit(e)
        row = {"class": e["class"], "licence": e["licence"], "quoted_items": len(texts), "withheld_items": held.get(sid, 0),
               "distinct_chars": distinct_chars(texts), "longest": longest.get(sid, 0), "cap": cap,
               **({"text_chars": e["text_chars"]} if e.get("text_chars") else {}), "violations": []}
        if cap is not None:
            over = [t for t in texts if len(t) > ITEM_MAX]
            if over:
                row["violations"].append(f"{len(over)} quoted texts longer than {ITEM_MAX} characters (longest {max(map(len, over))})")
            if row["distinct_chars"] > cap:
                row["violations"].append(f"{row['distinct_chars']} distinct quoted characters; the cap is {cap}")
        problems += [f"{sid}: {v}" for v in row["violations"]]
        rows[sid] = row
    unlisted = [s for s in sources if s not in rights]
    return {"sources": rows, "unlisted": unlisted, "violations": problems, "ok": not problems}


# ---------------------------------------------------------------- cap
def _note_with(ev: dict, field: str, text: str) -> None:
    h, n = digest(text)
    mark = f"{field} withheld: sha256:{h} chars:{n}"
    ev["note"] = f"{ev['note']}; {mark}" if ev.get("note") else mark


def cap(doc: dict, rights: dict[str, dict], texts: dict[str, str] | None = None) -> tuple[dict, dict]:
    """The document with every quoted text of a capped source kept only while it fits the caps, in a stable
    priority order (evidence of quantitative values first, then shorter texts first, then by record id, item and
    field); the rest is withheld. Nothing is trimmed. ``texts`` (source id -> text) supply ``text_chars`` a rights
    entry lacks. Returns the document and a report per source."""
    out = copy.deepcopy(doc)
    texts = texts or {}
    cands: dict[str, list[tuple]] = {}
    for rec, rid, i, ev in items(out):
        sid = str(ev.get("source"))
        for f in TEXT_FIELDS:
            if isinstance(ev.get(f), str) and ev[f]:
                cands.setdefault(sid, []).append(((0 if quantitative(rec, ev) else 1), len(ev[f]), rid, i, TEXT_FIELDS.index(f), ev, f))
    summary = {}
    for sid in sorted(cands):
        e = dict(source_rights(rights, sid))
        if not e.get("text_chars") and sid in texts:
            e["text_chars"] = len(texts[sid])
        cap_chars = limit(e)
        rows = sorted(cands[sid], key=lambda c: c[:5])
        before = distinct_chars([ev[f] for *_, ev, f in rows])
        kept: list[str] = []
        n_kept = n_held = 0
        for *_, ev, f in rows:
            t = ev[f]
            if cap_chars is None or (len(t) <= ITEM_MAX and distinct_chars(kept + [t]) <= cap_chars):
                kept.append(t)
                n_kept += 1
            else:
                _note_with(ev, f, t)
                del ev[f]
                n_held += 1
        summary[sid] = {"class": e["class"], "cap": cap_chars, "kept": n_kept, "withheld": n_held,
                        "distinct_chars_before": before, "distinct_chars_after": distinct_chars(kept)}
    return out, {"sources": summary, "kept": sum(r["kept"] for r in summary.values()),
                 "withheld": sum(r["withheld"] for r in summary.values())}


# ---------------------------------------------------------------- rehydrate
def _clusters(text: str):
    """The text in pieces that normalize independently: a character with the combining marks that follow it (and
    any character that composes with the one before it, as Hangul jamo do), since NFKC composes across them."""
    start = 0
    for i in range(1, len(text) + 1):
        if i < len(text) and (unicodedata.combining(text[i])
                              or len(unicodedata.normalize("NFC", text[i - 1] + text[i])) == 1):
            continue
        yield start, text[start:i]
        start = i


def _normalized_with_positions(text: str) -> tuple[str, list[tuple[int, int]]]:
    """The source text under the checker's normalization, with the span of the raw text each normalized character
    comes from (so a match maps back to the text as written). Pieces are normalized one by one; when the
    whole text normalizes to the same length (it differs only where case mapping depends on context, as for a final
    sigma), its own characters are used, so a window matches exactly what the verbatim checker matches."""
    chars, pos = [], []
    for i, piece in _clusters(text):
        n = match_text(piece)
        chars.append(n)
        pos += [(i, i + len(piece))] * len(n)
    whole = match_text(text)
    return (whole if len(whole) == len(pos) else "".join(chars)), pos


def _without(note: str, mark: str) -> str:
    """A note with one withheld mark taken out, and the ``"; "`` that joined it (the rest of the note as written)."""
    for joined in (f"; {mark}", f"{mark}; ", mark):
        if joined in note:
            return note.replace(joined, "", 1)
    return note


def rehydrate(doc: dict, texts: dict[str, str]) -> tuple[dict, dict]:
    """Restore the withheld texts from the sources' texts: for each, a window of the recorded length over the
    normalized text whose sha256 matches; the text is the raw span it comes from (whitespace runs as one space).
    Withheld texts whose source text is missing or holds no match are reported, and their notes kept."""
    out = copy.deepcopy(doc)
    want: dict[str, dict[int, set[str]]] = {}            # source -> length -> the digests sought
    for _, _, _, ev in items(out):
        for _, h, n in withheld(ev):
            want.setdefault(str(ev.get("source")), {}).setdefault(n, set()).add(h)
    found: dict[str, dict[tuple[str, int], str]] = {}
    for sid, by_len in want.items():
        if sid not in texts:
            continue
        norm, pos = _normalized_with_positions(texts[sid])
        table: dict[tuple[str, int], str] = {}
        for n, sought in sorted(by_len.items()):
            for s in range(0, len(norm) - n + 1):
                h = hashlib.sha256(norm[s:s + n].encode("utf-8")).hexdigest()
                if h in sought and (h, n) not in table:      # the first occurrence in the text
                    table[(h, n)] = " ".join(texts[sid][pos[s][0]:pos[s + n - 1][1]].split())
        found[sid] = table
    restored, unresolved = 0, []
    for _, rid, i, ev in items(out):
        marks = withheld(ev)
        if not marks:
            continue
        sid = str(ev.get("source"))
        note = str(ev.get("note") or "")
        for f, h, n in marks:
            t = found.get(sid, {}).get((h, n))
            if t is None:
                unresolved.append({"record": rid, "evidence": i, "field": f, "source": sid,
                                   "why": "no source text" if sid not in texts else "not found in the source text"})
                continue
            ev[f] = t
            note = _without(note, f"{f} withheld: sha256:{h} chars:{n}")
            restored += 1
        if note:
            ev["note"] = note
        else:
            ev.pop("note", None)
    return out, {"restored": restored, "unresolved": unresolved, "ok": not unresolved}


def read_texts(directory: str | Path | None = None, pairs: list[str] | None = None, doc: dict | None = None) -> dict[str, str]:
    """Source texts by source id: ``DIR/<last segment of the id>.txt`` for each Source the document cites, and
    ``ID=FILE`` pairs (HTML entities unescaped, as for the verbatim check)."""
    out: dict[str, str] = {}
    if directory is not None:
        d = Path(directory)
        if not d.is_dir():
            raise ScaleError(f"--texts {d}: not a directory")
        ids = {str(ev.get("source")) for _, _, _, ev in items(doc or {})} | \
              {n["id"] for n in (doc or {}).get("nodes", []) if n.get("label") == "Source"}
        for sid in sorted(ids):
            f = d / f"{sid.rstrip('/').rsplit('/', 1)[-1]}.txt"
            if f.is_file():
                out[sid] = html.unescape(f.read_text(encoding="utf-8", errors="ignore"))
    for p in pairs or []:
        sid, _, path = p.partition("=")
        if not path:
            raise ScaleError(f"--source-text expects <source-id>=<file>, got {p!r}")
        out[sid] = html.unescape(Path(path).read_text(encoding="utf-8", errors="ignore"))
    return out


# ---------------------------------------------------------------- the repository
def committed_documents(repo: str | Path) -> list[Path]:
    """Every scale-catal document in the repository tree (the files a clone has: no local or build material)."""
    repo = Path(repo).resolve()
    out = []
    for p in sorted(repo.rglob("*.json")):
        rel = p.relative_to(repo)
        if any(x.startswith(".") or x == "__pycache__" for x in rel.parts) or rel.parts[0] in layout.BUILD_DIRS \
                or layout.is_local(rel):
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="ignore")
            if '"scale-catal"' not in head:
                continue
            doc = json.loads(head)
        except ValueError:
            continue
        if isinstance(doc, dict) and isinstance(doc.get("graph"), dict) and doc["graph"].get("schema") == "scale-catal":
            out.append(p)
    return out


def access_problems(repo: str | Path, docs: list[Path] | None = None) -> list[str]:
    """Committed documents whose graph or any record is not explicitly public (effective stewardship access;
    a missing access counts as not public, as ``pgraph.visible`` reads it)."""
    from .pgraph import effective_stewardship
    repo = Path(repo).resolve()
    out = []
    for p in docs if docs is not None else committed_documents(repo):
        doc = load_doc(p)
        rel = p.relative_to(repo).as_posix() if p.is_relative_to(repo) else str(p)
        g = (doc.get("graph") or {}).get("stewardship") or {}
        if g.get("access") != "public":
            out.append(f"{rel}: the graph's stewardship access is {g['access']}" if g.get("access") else
                       f"{rel}: the graph states no stewardship access (read as institution); declare access: public")
        bad = [r.get("id") for r in doc.get("nodes", []) + doc.get("links", [])
               if effective_stewardship(doc, r).get("access") != "public"]
        if bad:
            out.append(f"{rel}: {len(bad)} records are not public (e.g. {bad[0]})")
    return out


def copyright_check(repo: str | Path) -> dict:
    """The cap over every committed document that holds research data (any ``data_status`` but
    ``synthetic_example``, so ``mixed`` too): each needs a rights file, every Source it names a rights entry, and its
    quoted text must respect the caps."""
    repo = Path(repo).resolve()
    rows, problems = [], []
    for p in committed_documents(repo):
        doc = load_doc(p)
        if (doc.get("graph") or {}).get("data_status") == "synthetic_example":
            continue
        rel = p.relative_to(repo).as_posix()
        rf = rights_file(p, repo)
        if rf is None:
            problems.append(f"{rel}: research data without a {RIGHTS_FILE} in its folder or above")
            continue
        rep = report(doc, load_rights(rf))
        problems += [f"{rel}: {v}" for v in rep["violations"]]
        problems += [f"{rel}: source {s} has no entry in {rf.relative_to(repo).as_posix()}" for s in rep["unlisted"]]
        rows.append({"document": rel, "rights": rf.relative_to(repo).as_posix(), "sources": len(rep["sources"]),
                     "quoted_items": sum(r["quoted_items"] for r in rep["sources"].values()),
                     "withheld_items": sum(r["withheld_items"] for r in rep["sources"].values())})
    return {"documents": rows, "problems": problems, "ok": not problems}


# ---------------------------------------------------------------- gap reports leaving a data repository
GAP_TEXT_MAX = 1000         # characters of a theme's own words (title, what is missing, why it matters)
GAP_THEME_KEYS = {"title": True, "cannot_express": True, "why_it_matters": True, "instances": True}
GAP_INSTANCE_KEYS = {"source": True, "locator": True, "quote": False}


def _plain(text: str) -> str:
    """A text for an issue body: one line, no @-mentions (they would notify people or call an agent)."""
    return " ".join(str(text).split()).replace("@", "@​")


def gap_report(data: dict, rights: dict[str, dict]) -> dict:
    """Check a gap report before it leaves a data repository (a data repository's find-gaps workflow posts it as
    an issue in the schema repository, a wider audience than the data's readers), and render it as Markdown.

    The report is JSON: ``{"corpus": str, "sample": int | str, "themes": [{"title", "cannot_express",
    "why_it_matters", "instances": [{"source", "locator", "quote"?}]}]}`` and nothing else, so no record or passage
    rides along in another field. Every source must have an entry in ``rights``; every quote, whatever the source's
    class, is at most 300 characters, and the distinct quoted characters of a source stay within its cap (4,000
    and 10 % of its text for capped sources, 4,000 for the others); a theme's own words are at most 1,000
    characters a field. ``markdown`` is None when anything fails."""
    problems: list[str] = []
    if not isinstance(data, dict) or set(data) - {"corpus", "sample", "themes"}:
        return {"ok": False, "problems": ["a gap report holds corpus, sample and themes, nothing else"], "markdown": None}
    themes = data.get("themes")
    if not isinstance(data.get("corpus"), str) or not isinstance(themes, list) or not themes:
        return {"ok": False, "problems": ["corpus (a path) and a non-empty list of themes are required"], "markdown": None}
    quotes: dict[str, list[str]] = {}
    for i, th in enumerate(themes, 1):
        where = f"theme {i}"
        if not isinstance(th, dict) or set(th) - set(GAP_THEME_KEYS) or any(k not in th for k in GAP_THEME_KEYS):
            problems.append(f"{where}: keys are {', '.join(GAP_THEME_KEYS)}")
            continue
        for k in ("title", "cannot_express", "why_it_matters"):
            if not isinstance(th[k], str) or not th[k].strip():
                problems.append(f"{where}: {k} is a non-empty text")
            elif len(th[k]) > GAP_TEXT_MAX:
                problems.append(f"{where}: {k} has {len(th[k])} characters; at most {GAP_TEXT_MAX} (your own words, no passages)")
        if not isinstance(th["instances"], list) or not th["instances"]:
            problems.append(f"{where}: instances is a non-empty list")
            continue
        for j, ins in enumerate(th["instances"], 1):
            w = f"{where}, instance {j}"
            if not isinstance(ins, dict) or set(ins) - set(GAP_INSTANCE_KEYS) or any(k not in ins for k, req in GAP_INSTANCE_KEYS.items() if req):
                problems.append(f"{w}: keys are source, locator and (optional) quote")
                continue
            if not all(isinstance(ins.get(k, ""), str) for k in GAP_INSTANCE_KEYS):
                problems.append(f"{w}: source, locator and quote are texts")
                continue
            sid = ins["source"]
            if sid not in rights:
                problems.append(f"{w}: source {sid} has no entry in the rights file")
            if len(ins["locator"]) > 200:
                problems.append(f"{w}: the locator has {len(ins['locator'])} characters; at most 200")
            q = ins.get("quote") or ""
            if len(q) > ITEM_MAX:
                problems.append(f"{w}: the quote has {len(q)} characters; at most {ITEM_MAX}")
            if q:
                quotes.setdefault(sid, []).append(q)
    for sid, texts in sorted(quotes.items()):
        cap = limit(source_rights(rights, sid)) or SOURCE_MAX
        n = distinct_chars(texts)
        if n > cap:
            problems.append(f"source {sid}: {n} distinct quoted characters; the cap is {cap}")
    if problems:
        return {"ok": False, "problems": problems, "markdown": None}
    lines = [f"Corpus `{_plain(data['corpus']).replace('`', '')}`, sample {_plain(data.get('sample', '?'))}: "
             f"{len(themes)} gap theme{'s' if len(themes) != 1 else ''}.", ""]
    for i, th in enumerate(themes, 1):
        lines += [f"### {i}. {_plain(th['title'])}", "", f"**Cannot express:** {_plain(th['cannot_express'])}", "",
                  f"**Why it matters:** {_plain(th['why_it_matters'])}", "", "Instances:", ""]
        for ins in th["instances"]:
            q = f": “{_plain(ins['quote'])}”" if ins.get("quote") else ""
            lines.append(f"- `{_plain(ins['source']).replace('`', '')}`, {_plain(ins['locator'])}{q}")
        lines.append("")
    return {"ok": True, "problems": [], "themes": len(themes),
            "quoted_chars": {s: distinct_chars(t) for s, t in sorted(quotes.items())}, "markdown": "\n".join(lines)}
