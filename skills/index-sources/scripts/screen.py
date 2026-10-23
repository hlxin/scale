"""Index step — relevance screening (curation) of a topic's sources and their Topic A/B/C, BEFORE anything is downloaded.

Methods (config['screening']['method']):
  claude    Claude subagents score batches of title+abstract:   prep -> next N -> (subagents) -> merge
  api       an OpenAI-compatible endpoint scores the batches:  prep -> api -> merge
  keywords  deterministic include/exclude term list (.scripts/<topic>/keywords.json): keywords
  none      no screening; every source that passed the topic gate stays in scope: none
Every method writes Relevance (0-5, blank for none), a short note, and the in/out decision (score >= threshold,
default 3) into the ledger; a manual decision (an imported list's, import_list.py --scope file / in) is never
re-scored. claude / api also choose each source's three main topics from the topic vocabulary
(the topic vocabulary, _topics.vocab_path, + .scripts/vocab_custom.json); keywords / none keep the deterministic vocabulary topics that
build_list / classify_access assigned (sources without topics get them; topics.py assign redoes them all after a
vocabulary change). keywords and none work block by block (20,000 sources), so a topic of millions takes minutes.
Then the topic's index CSVs and sources/index.db are refreshed.

usage:
  python3 -I screen.py --topic <slug> prep [--stage fulltext] [--size N]
  python3 -I screen.py --topic <slug> next 5 [--stage fulltext]      # prints: batch  batch_path  output_path
  python3 -I screen.py --topic <slug> api [--stage fulltext]
  python3 -I screen.py --topic <slug> merge [--stage fulltext]
  python3 -I screen.py --topic <slug> keywords [--no-export]
  python3 -I screen.py --topic <slug> none [--no-export]
  python3 -I screen.py --topic <slug> status
Stage `abstract` (default) screens sources not yet screened; stage `fulltext` re-scores DOWNLOADED sources from the
text of PDF pages 1-3 and moves sources that fall below the threshold to .scripts/<topic>/out_of_scope/.
"""
import argparse
import json
import os
import random
import re
import shutil
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (Gate, Project, _compile_terms, add_project_arg, clean_text, die, json_read, load_config, load_keys,
                     log, now_iso, unify_dashes, update_state)
from _ledger import Ledger
from _topics import Vocab, apply_vocab

SKILL = Path(__file__).resolve().parents[1]
DEFAULT_SIZE = {"claude": 100, "api": 25}
BLOCK = 20000           # sources per transaction in keywords / none (a topic may hold millions)
NOT_MANUAL = "COALESCE(t.relevance_method, '') != 'manual'"     # a person's decision: never re-scored


def qdir(proj, slug, stage):
    d = proj.topic_dir(slug) / "screen" / stage
    for sub in ("pending", "out", "done"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def threshold(cfg):
    return int((cfg.get("screening") or {}).get("threshold", 3))


def criteria_text(proj, slug, cfg):
    p = proj.topic_dir(slug) / "criteria.md"
    if p.exists():
        return p.read_text().strip()
    return f"Topic: {cfg.get('topic')}"


def render_instructions(proj, slug, cfg, stage):
    tpl = (SKILL / "templates" / "screen_instructions.md").read_text()
    basis = ("Each item has `title`, `abstract` (may be empty), `venue` and `year`. Judge from these only."
             if stage == "abstract" else
             "Each item has `title` and `text` = the extracted text of the source's pages 1-3. If `text_quality` is "
             "\"poor\" or the text is garbled, read the PDF itself: Read(file_path=<pdf_path>, pages=\"1-3\"). "
             "Score 0 if the text is clearly a different source than the title.")
    vocab = Vocab(proj)
    out = (tpl.replace("{{CRITERIA}}", criteria_text(proj, slug, cfg)).replace("{{BASIS}}", basis)
           .replace("{{READ_PDF}}", "" if stage == "abstract" else ", and a PDF from the batch when its text is poor")
           .replace("{{VOCAB}}", "Vocabulary (labels by facet):\n" + vocab.compact_list()))
    path = qdir(proj, slug, stage) / "instructions.md"
    path.write_text(out)
    return path


def queued_keys(d):
    keys = set()
    for sub in ("pending",):
        for f in (d / sub).glob("batch_*.json"):
            keys.update(it["key"] for it in json.load(open(f)))
    return keys


def page_text(path, pages=3, cap=9000):
    import fitz
    fitz.TOOLS.mupdf_display_errors(False)
    try:
        with fitz.open(path) as doc:
            txt = "\n".join(doc[i].get_text("text") for i in range(min(pages, doc.page_count)))
            n = doc.page_count
    except Exception:
        return "", 0, "unreadable"
    txt = re.sub(r"-\n(?=[a-z])", "", txt)
    txt = re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", txt)).strip()
    letters = sum(ch.isalpha() for ch in txt[:5000])
    quality = "ok" if len(txt) >= 1500 and letters / max(1, len(txt[:5000])) > 0.55 else "poor"
    return txt[:cap], n, quality


def prep_rows(led, slug, stage):
    """The sources to batch, most cited first (abstract stage), read 900 at a time (a topic may hold millions)."""
    if stage == "abstract":
        ids = [r[0] for r in led.q("SELECT p.id FROM source_topics t JOIN sources p ON p.id = t.source_id WHERE t.topic = ? "
                                   "AND t.relevance IS NULL AND p.is_erratum = 0 "
                                   "ORDER BY COALESCE(p.cited_by, 0) DESC, t.rowid", (slug,))]
        cond = ""
    else:
        ids = [r[0] for r in led.q("SELECT t.source_id FROM source_topics t JOIN sources p ON p.id = t.source_id "
                                   "WHERE t.topic = ? AND p.downloaded = 1 AND t.path IS NOT NULL AND "
                                   "(t.relevance_method IS NULL OR t.relevance_method NOT LIKE '%fulltext%') "
                                   f"AND {NOT_MANUAL} "
                                   "ORDER BY t.rowid", (slug,))]
        cond = ""
    for i in range(0, len(ids), 900):
        part = ids[i:i + 900]
        got = {r["id"]: r for r in led.topic_rows(slug, f"AND p.id IN ({','.join('?' * len(part))}) {cond}", tuple(part))}
        for pid in part:
            if pid in got:
                yield got[pid]


def prep(proj, slug, cfg, led, stage, size):
    d = qdir(proj, slug, stage)
    render_instructions(proj, slug, cfg, stage)
    queued = queued_keys(d)
    existing = [int(re.search(r"(\d+)", f.stem).group(1)) for sub in ("pending", "done") for f in (d / sub).glob("batch_*.json")]
    n = max(existing or [0]) + 1
    made, total, buf = 0, 0, []

    def flush():
        nonlocal n, made
        for j, it in enumerate(buf, 1):
            it["id"] = str(j)
        (d / "pending" / f"batch_{n:05d}.json").write_text(json.dumps(buf, ensure_ascii=False, indent=0))
        n += 1
        made += 1
        buf.clear()

    for r in prep_rows(led, slug, stage):      # batches are written as they fill: never every item in memory
        if r["id"] in queued:
            continue
        if stage == "abstract":
            it = {"key": r["id"], "title": (r.get("title") or "")[:400],
                  "abstract": clean_text(r.get("abstract") or "")[:1500], "venue": (r.get("journal") or "")[:100],
                  "year": r.get("year"), "keywords": "; ".join((r.get("keywords") or [])[:8]),
                  "type": r.get("doc_type") or ""}
        else:
            pdf = proj.root / r["t_path"]
            if not pdf.exists():
                continue
            txt, pages, q = page_text(pdf)
            it = {"key": r["id"], "title": (r.get("title") or "")[:400], "pdf_path": str(pdf), "pages": pages,
                  "text_quality": q, "text": txt}
        buf.append(it)
        total += 1
        if len(buf) >= size:
            flush()
    if buf:
        flush()
    print(json.dumps({"stage": stage, "items": total, "batches": made, "batch_size": size,
                      "instructions": str(d / "instructions.md")}))


def next_batches(proj, slug, stage, n):
    d = qdir(proj, slug, stage)
    disp = d / "dispatched.txt"
    sent = set(disp.read_text().split()) if disp.exists() else set()
    todo = [f for f in sorted((d / "pending").glob("batch_*.json")) if f.stem not in sent]
    pick = todo[:n]
    with open(disp, "a") as fh:
        for f in pick:
            fh.write(f.stem + "\n")
    for f in pick:
        print(f"{f.stem}\t{f}\t{d / 'out' / (f.stem + '.jsonl')}")
    if not pick:
        print("(no undispatched batches — run prep, or merge finished outputs)")


def parse_out(text):
    got = {}
    for line in text.splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("{"):
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        got[str(o.get("id", "")).strip()] = o
    return got


def apply_fulltext_move(proj, slug, led, pid, row_path):
    """Score fell below threshold after reading the source: move its files out of sources/ (never deleted)."""
    src = proj.root / row_path
    dst_dir = proj.topic_dir(slug) / "out_of_scope"
    dst_dir.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.move(str(src), str(dst_dir / src.name))
    moved_si = []
    t = next((x for x in led.topics_of(pid) if x["topic"] == slug), {})
    for sp in json.loads(t.get("si_paths") or "[]"):
        s = proj.root / sp
        if s.exists():
            shutil.move(str(s), str(dst_dir / s.name))
            moved_si.append(proj.rel(dst_dir / s.name))
    return proj.rel(dst_dir / src.name), moved_si


def merge(proj, slug, cfg, led, stage, export=True):
    d = qdir(proj, slug, stage)
    thr = threshold(cfg)
    method = (cfg.get("screening") or {}).get("method", "claude")
    label = f"{method}:{stage}"
    merged, scored, bad, moved = 0, 0, Counter(), 0
    vocab, new_terms = Vocab(proj), Counter()
    for f in sorted((d / "pending").glob("batch_*.json")):
        out = d / "out" / (f.stem + ".jsonl")
        if not out.exists():
            continue
        items = {it["id"]: it for it in json.load(open(f))}
        got = parse_out(out.read_text(errors="ignore"))
        with led.tx():
            for i, it in items.items():
                o = got.get(i)
                try:
                    s = int(o.get("score"))
                    assert 0 <= s <= 5
                except Exception:
                    bad[f.stem] += 1
                    continue  # stays unscored -> re-batched by the next prep
                reason = clean_text(str(o.get("reason", "")))[:300]
                upd = {"relevance": s, "relevance_note": reason, "relevance_method": label, "in_scope": int(s >= thr)}
                if stage == "fulltext" and s < thr:
                    t = next((x for x in led.topics_of(it["key"]) if x["topic"] == slug), {})
                    if t.get("path"):
                        newp, new_si = apply_fulltext_move(proj, slug, led, it["key"], t["path"])
                        upd.update({"path": newp, "si_paths": new_si,
                                    "relevance_note": f"full text: {reason} (files moved to .scripts/{slug}/out_of_scope/)"})
                        moved += 1
                led.set_topic(it["key"], slug, **upd)
                if stage == "abstract":
                    row = led.get(it["key"]) or {}
                    tp = o.get("topics") if isinstance(o.get("topics"), list) else []
                    rl = o.get("related") if isinstance(o.get("related"), list) else []
                    a = vocab.from_model(tp, rl, row.get("title"), row.get("abstract"), row.get("keywords"))
                    led.set_subjects(it["key"], a["main"], a["related"], method if tp else "vocab", a["scores"])
                    new_terms.update(t[4:] for t in a["main"] if t.startswith("new:"))
                scored += 1
        f.rename(d / "done" / f.name)
        merged += 1
    if export:
        led.export(topics=[slug])
    res = {"stage": stage, "batches_merged": merged, "sources_scored": scored, "unparsed_items": sum(bad.values()),
           "moved_out_of_scope": moved, "proposed_new_topics": dict(new_terms.most_common(20))}

    def fn(st):
        st.setdefault("screen", {})[stage] = {**res, "merged_at": now_iso()}
    update_state(proj, slug, fn)
    print(json.dumps(res))


# ---------------------------------------------------------------- OpenAI-compatible API
def api_key(proj, scfg):
    env = scfg.get("key_env")
    if env and os.environ.get(env):
        return os.environ[env]
    keys = load_keys(proj)
    if keys.get(scfg.get("key_name", "llm_api_key")):
        return keys[scfg.get("key_name", "llm_api_key")]
    envf = proj.scr / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            if "=" in line and line.split("=", 1)[0].strip() in ("LLM_API_KEY", "ARC_API_KEY"):
                return line.split("=", 1)[1].strip()
    return None


def chat(base, key, model, messages, max_tokens=6000, tries=6, extra=None):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, **(extra or {})}
    last = None
    for attempt in range(tries):
        try:
            r = requests.post(f"{base.rstrip('/')}/chat/completions", json=body, timeout=600,
                              headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        except requests.RequestException as e:
            last = f"network {e!r}"[:200]
            r = None
        if r is not None:
            if r.status_code == 200:
                try:
                    content = r.json()["choices"][0]["message"].get("content") or ""
                    if content.strip():
                        return content
                    last = "empty content"
                    body["max_tokens"] = int(body["max_tokens"] * 1.5)
                except (ValueError, KeyError, IndexError) as e:
                    last = f"bad response {e!r}"
            elif r.status_code in (400, 401, 403, 404):
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
            else:
                last = f"HTTP {r.status_code}: {r.text[:200]}"
        time.sleep(min(120, 5 * 2 ** attempt) + random.random() * 3)
    raise RuntimeError(last or "unknown error")


def run_api(proj, slug, cfg, stage):
    scfg = cfg.get("screening") or {}
    base, model = scfg.get("base_url"), scfg.get("model")
    if not base or not model:
        die("config['screening'] needs base_url and model for the api method")
    key = api_key(proj, scfg)
    if not key:
        die("no API key: add `llm_api_key: <key>` to ~/.scale/sources/keys.txt (see the skill's README.md), or "
            "set the env var named in screening.key_env")
    d = qdir(proj, slug, stage)
    instr = (d / "instructions.md").read_text() if (d / "instructions.md").exists() else render_instructions(proj, slug, cfg, stage).read_text()
    todo = [f for f in sorted((d / "pending").glob("batch_*.json")) if not (d / "out" / (f.stem + ".jsonl")).exists()]
    log(f"api: {len(todo)} batches -> {base} ({model})")
    lock = threading.Lock()
    done = Counter()

    def one(f):
        items = json.load(open(f))
        msgs = [{"role": "system", "content": "You screen scientific sources for a literature collection. Follow the "
                                              "instructions exactly and answer with JSON Lines only."},
                {"role": "user", "content": instr + "\n\n## Items\n" +
                 "\n".join(json.dumps(it, ensure_ascii=False) for it in items) +
                 "\n\nReturn the JSON Lines now (one line per item, nothing else)."}]
        try:
            text = chat(base, key, model, msgs, extra=scfg.get("extra_body"))
        except RuntimeError as e:
            log(f"{f.stem}: {e}")
            with lock:
                done["failed"] += 1
            return
        text = re.sub(r"^```\w*\s*|\s*```$", "", text.strip())
        (d / "out" / (f.stem + ".jsonl")).write_text(text)
        with lock:
            done["ok"] += 1
            if sum(done.values()) % 20 == 0:
                log(f"api: {dict(done)}")

    with ThreadPoolExecutor(int(scfg.get("concurrency", 4))) as ex:
        list(ex.map(one, todo))
    print(json.dumps({"api_batches": dict(done)}))


# ---------------------------------------------------------------- deterministic keywords
def _show(term):
    """Readable form of a keyword ('re:\\bTi3C2T' -> 'Ti3C2T')."""
    t = str(term)
    if t.startswith("re:"):
        t = re.sub(r"\\[bBsSdDwW]|[\^\$\?\*\+\(\)\[\]\{\}\|\\]", "", t[3:])
    return t


class _Term:
    """One keyword: its regex, the term as written, and the words any match must contain (a cheap test that skips the
    regex for most sources; None for 're:' regexes, which always run)."""
    __slots__ = ("rx", "raw", "lits")

    def __init__(self, rx, raw):
        t = unify_dashes(str(raw))
        self.rx, self.raw = rx, raw
        self.lits = None if t.startswith("re:") else \
            sorted({p for w in t.casefold().split() for p in w.split("-") if p}, key=len, reverse=True)

    def found(self, text, low):
        if self.lits is not None and not all(x in low for x in self.lits):
            return False
        return self.rx.search(text) is not None


class KeywordScorer:
    """keywords.json -> relevance 0-5 and a short note per source; a topic of millions of sources is scored in minutes."""

    def __init__(self, kw):
        raw_groups = [g for g in kw.get("include_groups") or [] if g]
        self.groups = [[_Term(rx, raw) for rx, raw in zip(_compile_terms(g), g)] for g in raw_groups]
        self.terms = raw_groups
        ex = kw.get("exclude") or []
        self.excl = [_Term(rx, raw) for rx, raw in zip(_compile_terms(ex), ex)]

    def score(self, title, abstract):
        title, abstract = unify_dashes(title or ""), unify_dashes(abstract or "")
        both = f"{title} . {abstract}"
        low_t, low_a, low_b = title.casefold(), abstract.casefold(), both.casefold()
        n = len(self.groups)
        in_title = sum(1 for g in self.groups if any(t.found(title, low_t) for t in g))
        hit_both = [any(t.found(both, low_b) for t in g) for g in self.groups]
        in_both = sum(hit_both)
        if in_title == n:
            s = 5
        elif in_both == n:
            s = 4
        elif in_both:
            s = 2
        else:
            s = 0
        ex_t = [t.raw for t in self.excl if t.found(title, low_t)]
        ex_a = [t.raw for t in self.excl if t.found(abstract, low_a)]
        if ex_t:
            s = min(s, 1)
        elif ex_a and in_title < n:
            s = min(s, 2)
        missing = [terms for terms, hit in zip(self.terms, hit_both) if not hit]
        parts = []
        if ex_t or ex_a:
            parts.append("mentions " + ", ".join(_show(t) for t in (ex_t or ex_a)[:3]))
        if missing:
            parts.append("no mention of " + " / ".join("(" + ", ".join(_show(t) for t in terms[:3]) + ")"
                                                       for terms in missing))
        if parts:
            note = "; ".join(parts)
        else:
            hits = sorted({t.raw for g in self.groups for t in g if t.found(both, low_b)})
            note = "all concepts: " + ", ".join(_show(t) for t in hits[:5])
        return s, note[:300]


def topic_count(led, slug, where=""):
    return led.q("SELECT COUNT(*) FROM source_topics t JOIN sources p ON p.id = t.source_id WHERE t.topic = ? " + where,
                 (slug,))[0][0]


def progress(label, done, total, t0):
    if total > BLOCK:
        el = time.time() - t0
        log(f"{label}: {done:,}/{total:,} sources ({el / 60:.1f} min, ~{el / max(done, 1) * (total - done) / 60:.0f} min left)")


def run_keywords(proj, slug, cfg, led, export=True):
    kw = json_read(proj.topic_dir(slug) / "keywords.json")
    if not kw:
        die(f"missing .scripts/{slug}/keywords.json (format: references/screening.md)")
    sc = KeywordScorer(kw)
    thr = int(kw.get("threshold", threshold(cfg)))
    if not sc.groups:
        die("keywords.json needs at least one include group")
    cnt, changed, vocab, done, t0 = Counter(), 0, Vocab(proj), 0, time.time()
    total = topic_count(led, slug, f"AND p.is_erratum = 0 AND {NOT_MANUAL}")
    for rows in led.iter_topic(slug, f"AND p.is_erratum = 0 AND {NOT_MANUAL}", chunk=BLOCK):   # notices: never scored
        with led.tx():
            for r in rows:
                s, note = sc.score(r.get("title"), r.get("abstract"))
                led.set_topic(r["id"], slug, relevance=s, relevance_note=note, relevance_method="keywords",
                              in_scope=int(s >= thr))
                cnt[s] += 1
        apply_vocab(led, vocab, rows, only_missing=True)     # sources that have no topics yet
        changed += getattr(apply_vocab, "changed", 0)
        done += len(rows)
        progress("keywords", done, total, t0)
    if export:
        led.export(topics=[slug])
    res = {"method": "keywords", "topics_changed": changed, "scores": {str(k): cnt[k] for k in sorted(cnt)},
           "in_scope": sum(v for k, v in cnt.items() if k >= thr), "threshold": thr}
    update_state(proj, slug, lambda st: st.setdefault("screen", {}).update({"abstract": {**res, "merged_at": now_iso()}}))
    print(json.dumps(res))


def run_none(proj, slug, led, export=True):
    n, vocab, t0 = 0, Vocab(proj), time.time()
    total = topic_count(led, slug, f"AND t.relevance IS NULL AND p.is_erratum = 0 AND {NOT_MANUAL}")
    for rows in led.iter_topic(slug, f"AND t.relevance IS NULL AND p.is_erratum = 0 AND {NOT_MANUAL}", chunk=BLOCK):
        with led.tx():
            for r in rows:
                led.set_topic(r["id"], slug, relevance=None, relevance_note=None, relevance_method="none", in_scope=1)
        apply_vocab(led, vocab, rows, only_missing=True)     # sources that have no topics yet
        n += len(rows)
        progress("none", n, total, t0)
    if export:
        led.export(topics=[slug])
    update_state(proj, slug, lambda st: st.setdefault("screen", {}).update({"abstract": {"method": "none", "sources": n}}))
    print(json.dumps({"method": "none", "sources_kept_in_scope": n}))


def status(proj, slug, led, stage):
    d = qdir(proj, slug, stage)
    disp = d / "dispatched.txt"
    sent = set(disp.read_text().split()) if disp.exists() else set()
    pend = sorted(f.stem for f in (d / "pending").glob("batch_*.json"))
    outs = {f.stem for f in (d / "out").glob("batch_*.jsonl")}
    papers, screened, in_scope, out_scope = led.q(
        "SELECT COUNT(*), COUNT(t.relevance), "
        "COALESCE(SUM(t.in_scope = 1 AND COALESCE(p.is_erratum, 0) = 0 AND COALESCE(p.retracted, 0) = 0), 0), "
        "COALESCE(SUM(t.in_scope = 0 AND COALESCE(p.is_erratum, 0) = 0), 0) "
        "FROM source_topics t JOIN sources p ON p.id = t.source_id WHERE t.topic = ?", (slug,))[0]
    print(json.dumps({"stage": stage, "pending_batches": len(pend),
                      "dispatched_waiting": len([p for p in pend if p in sent and p not in outs]),
                      "undispatched": len([p for p in pend if p not in sent]),
                      "outputs_ready_to_merge": len([p for p in pend if p in outs]),
                      "sources": papers, "screened": screened, "in_scope": in_scope, "out_of_scope": out_scope}))


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic", required=True)
    ap.add_argument("cmd", choices=["prep", "next", "api", "merge", "keywords", "none", "status"])
    ap.add_argument("n", nargs="?", type=int, default=5)
    ap.add_argument("--stage", choices=["abstract", "fulltext"], default="abstract")
    ap.add_argument("--size", type=int, default=None, help="items per batch (default 100 claude / 25 api)")
    ap.add_argument("--no-export", action="store_true",
                    help="keywords / none / merge: do not refresh the index CSVs and index.db (export.py later)")
    a = ap.parse_args()
    proj = Project(a.project)
    cfg = load_config(proj, a.topic)
    led = Ledger(proj)
    method = (cfg.get("screening") or {}).get("method", "claude")
    if a.cmd == "prep":
        size = a.size or (10 if a.stage == "fulltext" else DEFAULT_SIZE.get(method, 100))
        prep(proj, a.topic, cfg, led, a.stage, size)
    elif a.cmd == "next":
        next_batches(proj, a.topic, a.stage, a.n)
    elif a.cmd == "api":
        run_api(proj, a.topic, cfg, a.stage)
    elif a.cmd == "merge":
        merge(proj, a.topic, cfg, led, a.stage, export=not a.no_export)
    elif a.cmd == "keywords":
        run_keywords(proj, a.topic, cfg, led, export=not a.no_export)
    elif a.cmd == "none":
        run_none(proj, a.topic, led, export=not a.no_export)
    else:
        status(proj, a.topic, led, a.stage)


if __name__ == "__main__":
    main()
