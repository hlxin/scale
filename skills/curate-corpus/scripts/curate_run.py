"""Curate a frozen corpus into scale-catal documents: one SCALE working folder per source, curated by a subagent that
follows the curate-source skill, read a second time by another, and checked by SCALE's tools.

  python3 -I curate_run.py prepare --corpus <sources.json> --run <dir> [--ids 12,57 | --ids-file F] [--max 50]
                                   [--contributor <id>] [--project <id>] [--version <v>] [--no-si] [--scale "<command>"]
  python3 -I curate_run.py next    --run <dir> --role curate|review|fix [--n 5]
  python3 -I curate_run.py status  --run <dir> [--apply]
  python3 -I curate_run.py finish  --run <dir> [--public] [--bundle]
  python3 -I curate_run.py assemble --run <dir> [--out <folder>]        (a local graph of the run, to query)
  python3 -I curate_run.py contribute --run <dir> --to <folder>          (a dry run: what would change)

prepare   checks the manifest with `scale corpus check`, picks its included sources whose PDF is on disk, and starts
          a working folder for each: `scale source start --doi <doi> --pdf <pdf> --out <run>/sources/<id>` (the
          graph to fill, pinned to the schema, with its Source; the page texts; rights.yaml; BRIEF.md). The SI files'
          text is appended to the page texts as pages [page S1], [page S2] …: supporting information belongs to its
          paper's Source. Re-running it skips folders that exist.
next      writes the prompt of the next N sources for a role (from ../templates) and prints one JSON line per source:
          {"id", "role", "prompt"}. Launch one subagent per line. A handed-out source is not handed out again for
          3 hours unless its report arrives.
status    runs `scale source check <folder>` on every folder (cached while the graph is unchanged), reads the
          curator's report (work/curation.json) and the second reading (work/review.json), and gives each source a
          state; --apply records the settled ones in state.jsonl and hands their result to the paper index
          (<project>/.scripts/<topic>/kg/<run>/extraction_status.jsonl), then runs paper-acquisition's export so
          the index shows them at once (its Extracted column; papers.db table extractions).
finish    `scale source finish <folder>` for every passed source (--public: the copy with quoted text capped).
assemble  a local graph kept as parts (<run>/graph by default) with every passed document, added by `scale graph
          contribute --write` into that local folder, and built (`scale graph build`) into one document to query.
contribute  `scale graph contribute <graph> --to <folder>` for every passed source, without --write: writing is a
          person's decision, then a pull request on an agent/… branch.

States: prepared → (curator) curated → (second reading) passed | needs_fix → (fix) curated … ; check_failed when the
curator's document does not pass the check; failed after 3 fixes; rejected when the second reading finds the wrong
paper or an unreadable text. Settled: passed (extracted or no_data), rejected, failed. The scripts never read or write
a document's records: the curator writes them, SCALE's tools check them. Prints one JSON object on stdout.
"""
import argparse
import datetime as _dt
import json
import os
import re
import shlex
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from string import Template

sys.path.insert(0, str(Path(__file__).resolve().parent))
import si_pages  # noqa: E402

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parent / "templates"
LEASE_S = 3 * 3600
MAX_FIXES = 3
INCLUDED = ("in_scope", "included")
SETTLED = {"passed", "rejected", "failed"}


# ------------------------------------------------------------------ small helpers
def now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(*a):
    print(f"[{_dt.datetime.now():%H:%M:%S}]", *a, file=sys.stderr, flush=True)


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(2)


def read_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def append_jsonl(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")


def jsonl(p):
    out = []
    if Path(p).exists():
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def mtime(p):
    try:
        return Path(p).stat().st_mtime
    except FileNotFoundError:
        return 0.0


def scale_text(cmd, *args, timeout=900):
    """Run the scale command; (exit code, stdout, stderr)."""
    try:
        r = subprocess.run([*shlex.split(cmd), *map(str, args)], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", f"{type(e).__name__}: {e}"
    return r.returncode, r.stdout, r.stderr


def scale(cmd, *args, timeout=900):
    """Run a scale command that prints JSON; (exit code, the parsed JSON or None, the tail of its messages)."""
    rc, out, err = scale_text(cmd, *args, timeout=timeout)
    try:
        parsed = json.loads(out) if out.strip() else None
    except json.JSONDecodeError:
        parsed = None
    return rc, parsed, (err or out or "").strip()[-600:]


def contribute(cmd, graph, folder, write=False):
    """`scale graph contribute` (it prints text): ("added" | "dry_run" | "already" | "refused", its message)."""
    rc, out, err = scale_text(cmd, "graph", "contribute", graph, "--to", folder, *(["--write"] if write else []))
    msg = (out.strip() or err.strip())[-800:]
    if rc == 1 and "already in " in out:
        return "already", msg
    if rc == 0:
        return ("added" if write else "dry_run"), msg
    return "refused", (err.strip() or out.strip())[-400:]


def project_root(start):
    """The paper-acquisition project that holds the manifest (its working ledger, or its papers.db alone), if any."""
    for d in [Path(start).resolve(), *Path(start).resolve().parents]:
        if (d / ".scripts" / "ledger.sqlite").is_file() or (d / "publications" / "papers.db").is_file():
            return d
    return None


def index_export(root):
    """paper-acquisition's export for the project, so the paper index shows the results now; what it said."""
    for cand in (HERE.parents[1] / "paper-acquisition" / "scripts" / "export.py",
                 root / ".claude" / "skills" / "paper-acquisition" / "scripts" / "export.py"):
        if cand.is_file():
            r = subprocess.run([sys.executable, "-I", str(cand), "--project", str(root)], capture_output=True, text=True)
            if r.returncode:
                return {"exported": False, "error": r.stderr.strip()[-300:]}
            try:
                return {"exported": True, "database": json.loads((r.stdout.strip().splitlines() or ["{}"])[-1])}
            except ValueError:
                return {"exported": True}
    return {"exported": False, "error": "paper-acquisition not found: run its export.py --project <project>"}


def folder_id(src):
    if src.get("paper_id") is not None:
        return str(src["paper_id"])
    return "".join(c if c.isalnum() or c in "._-" else "-" for c in str(src.get("slug") or src.get("id"))).strip("-.")


# ------------------------------------------------------------------ the run
class Run:
    def __init__(self, d):
        self.d = Path(d).resolve()
        self.cfg = read_json(self.d / "run.json")
        if not self.cfg:
            die(f"{self.d}: no run.json (start the run with: curate_run.py prepare --corpus … --run {self.d})")
        self.cmd = self.cfg["scale"]

    def folder(self, i):
        return self.d / "sources" / i

    def source(self, i):
        return self.cfg["sources"][i]

    def ids(self):
        return list(self.cfg["sources"])

    def graph(self, i):
        info = read_json(self.folder(i) / "source.json") or {}
        return self.folder(i) / f"{info.get('slug', '')}.graph.json", info.get("slug")

    def check(self, i):
        """`scale source check` of a folder, cached in work/check.json while the graph is unchanged."""
        g, _ = self.graph(i)
        cache = self.folder(i) / "work" / "check.json"
        c = read_json(cache)
        if c and c.get("graph_mtime") == mtime(g) and c.get("rights_mtime") == mtime(self.folder(i) / "rights.yaml"):
            return c
        rc, out, err = scale(self.cmd, "source", "check", self.folder(i))
        c = {"graph_mtime": mtime(g), "rights_mtime": mtime(self.folder(i) / "rights.yaml"), "exit": rc,
             "checked_at": now()}
        if out is None:
            c.update(ok=False, errors=[{"message": f"scale source check did not run: {err}"}], tool_error=True)
        else:
            c.update(ok=bool(out.get("ok")), errors=out.get("errors") or [], warnings=out.get("warnings") or [],
                     records=out.get("records") or {}, gaps=out.get("gaps") or 0, cap=out.get("cap") or {},
                     conformant=all((p or {}).get("conformant") for p in
                                    ((out.get("conformance") or {}).get("profiles") or {}).values()))
        write_json(cache, c)
        return c

    def gap_files(self, i):
        """The gap reports a curator wrote for this source (work/gaps/GAP-*.json, SCALE's gap format; a subfolder
        such as superseded/ is not counted)."""
        out = []
        for g in sorted((self.folder(i) / "work" / "gaps").glob("GAP-*.json")):
            d = read_json(g) or {}
            if d.get("kind"):
                out.append({"id": d.get("id") or g.stem, "kind": d["kind"], "about": (d.get("about") or "")[:200]})
        return out

    def handouts(self):
        out = {}
        for h in jsonl(self.d / "handouts.jsonl"):
            out.setdefault(h["id"], []).append(h)
        return out

    def state(self, i, hand):
        """(state, detail) of one source; see the module docstring."""
        f = self.folder(i)
        if not (f / "source.json").is_file():
            return "not_started", "no working folder (run prepare)"
        g, _ = self.graph(i)
        cur, rev = f / "work" / "curation.json", f / "work" / "review.json"
        fix_t = [h["t"] for h in hand.get(i, []) if h["role"] == "fix"]
        out_of_fixes = len(fix_t) >= MAX_FIXES and mtime(cur) > max(fix_t)     # the last allowed fix has reported
        latest = max(mtime(g), mtime(cur), mtime(f / "rights.yaml"))
        if not cur.exists():
            return "prepared", "waiting for the curator"
        chk = self.check(i)
        review = read_json(rev) or {}
        review_current = rev.exists() and mtime(rev) >= latest
        if review_current and review.get("verdict") == "reject":
            return "rejected", review.get("note") or "the second reading rejected it"
        if not chk.get("ok"):
            return ("failed", "the check still fails after 3 fixes") if out_of_fixes else \
                ("check_failed", f"{len(chk.get('errors') or [])} errors in scale source check")
        if review_current and review.get("verdict") == "pass":
            return "passed", (read_json(cur) or {}).get("result") or "curated"
        if review_current and review.get("verdict") == "needs_fix":
            return ("failed", "issues remain after 3 fixes") if out_of_fixes else \
                ("needs_fix", f"{len(review.get('issues') or [])} issues from the second reading")
        return "curated", "waiting for the second reading"


ROLE_STATES = {"curate": ("prepared",), "review": ("curated",), "fix": ("check_failed", "needs_fix")}


# ------------------------------------------------------------------ prepare
def cmd_prepare(a):
    manifest_path = Path(a.corpus).resolve()
    m = read_json(manifest_path)
    if not isinstance(m, dict) or not isinstance(m.get("sources"), list):
        die(f"{manifest_path}: not a corpus manifest (an object with a list of sources)")
    cmd = a.scale or os.environ.get("SCALE_CMD") or "scale"
    rc, chk, err = scale(cmd, "corpus", "check", manifest_path)
    if chk is None:
        die(f"scale corpus check did not run ({err}); give the scale command with --scale")
    if not chk.get("ok"):
        die("the corpus does not pass scale corpus check: " + "; ".join(chk.get("problems", [])[:5]))
    included = tuple(m.get("included_status", "").split(",")) if m.get("included_status") else INCLUDED
    want = None
    if a.ids or a.ids_file:
        raw = (a.ids or "").split(",") + (Path(a.ids_file).read_text().split() if a.ids_file else [])
        want = {x.strip() for x in raw if x.strip()}
    run_dir = Path(a.run).resolve()
    cfg = read_json(run_dir / "run.json") or {
        "name": run_dir.name, "corpus": str(manifest_path), "topic": m.get("topic"), "scale": cmd,
        "created_at": now(), "contributor": a.contributor, "project": a.project, "version": a.version,
        "si": not a.no_si, "sources": {}}
    if cfg["corpus"] != str(manifest_path):
        die(f"{run_dir} curates {cfg['corpus']}; give another --run for another corpus")
    root = project_root(manifest_path.parent)
    cfg["project_root"] = str(root) if root else None
    picked = []
    for s in m["sources"]:
        if s.get("status") not in included or not s.get("pdf"):
            continue
        if want is not None and not ({str(s.get("paper_id")), s.get("slug")} & want):
            continue
        pdf = (manifest_path.parent / s["pdf"]).resolve()
        if not pdf.is_file():
            continue
        picked.append((s, pdf))
    if a.max:
        picked = picked[:a.max]
    if not picked:
        die("no included source with its PDF on disk matches")
    started, skipped, notes = 0, 0, Counter()
    for s, pdf in picked:
        i = folder_id(s)
        f = run_dir / "sources" / i
        entry = cfg["sources"].setdefault(i, {})
        entry.update({k: s.get(k) for k in ("slug", "paper_id", "doi", "title", "year", "doc_type", "access_type",
                                            "licence", "licence_url", "text_version") if s.get(k) is not None})
        if (f / "source.json").is_file():
            skipped += 1
            continue
        entry.pop("start_error", None)
        entry.pop("note", None)
        args = ["source", "start", *(["--doi", s["doi"]] if s.get("doi") else []), "--pdf", pdf, "--out", f,
                *(["--contributor", a.contributor] if a.contributor else []),
                *(["--project", a.project] if a.project else []), *(["--version", a.version] if a.version else [])]
        rc, out, err = scale(cmd, *args)
        if rc != 0 and "invalid choice: 'source'" in err:
            die("this SCALE has no `scale source` (it came after release v0.2.0): use a checkout of hlxin/scale, "
                'e.g. --scale "uv run --project <checkout> scale"')
        if rc != 0 and s.get("doi"):            # one more try after a pause: this is often a network blip
            time.sleep(5)
            rc, out, err = scale(cmd, *args)
        if rc != 0 and s.get("doi"):            # the DOI did not resolve (offline, unknown to Crossref): the PDF alone
            notes["started without the DOI lookup"] += 1
            rc, out, err = scale(cmd, *[x for x in args if x not in ("--doi", s["doi"])])
            entry["note"] = ("started from the PDF alone (the DOI lookup failed): the Source has no "
                                         "metadata from Crossref; fill its title, doi, year, venue and licence from "
                                         "the copy")
        if rc != 0 or not out:
            notes["start failed"] += 1
            entry["start_error"] = err[-300:]
            log(f"  {i}: scale source start failed: {err[-200:]}")
            continue
        cfg["schema_version"] = out.get("schema_version") or cfg.get("schema_version")
        si = [(manifest_path.parent / p).resolve() for p in s.get("si") or []]
        si = [p for p in si if p.is_file()]
        if si and cfg["si"]:
            write_json(f / "work" / "si.json", {"appended_to": out.get("page_texts"),
                                                "files": si_pages.append(f / out["page_texts"], si)
                                                if out.get("page_texts") else [{"file": p.name, "left_out": "no page texts"}
                                                                               for p in si]})
        started += 1
        if s.get("doi"):
            time.sleep(1.0)                    # Crossref's polite pace: one DOI lookup per second
        if started % 25 == 0:
            write_json(run_dir / "run.json", cfg)
            log(f"  {started} folders started")
    write_json(run_dir / "run.json", cfg)
    print(json.dumps({"run": str(run_dir), "picked": len(picked), "started": started, "already_there": skipped,
                      "notes": dict(notes), "schema_version": cfg.get("schema_version"),
                      "next": f"curate_run.py next --run {run_dir} --role curate --n 5"}))


# ------------------------------------------------------------------ next
def bullet(items, empty):
    return "\n".join(f"- {x}" for x in items) if items else f"- {empty}"


def cmd_next(a):
    run = Run(a.run)
    hand = run.handouts()
    t = time.time()
    tpl = Template((TEMPLATES / f"{a.role}.md").read_text(encoding="utf-8"))
    out = []
    for i in run.ids():
        if len(out) >= a.n:
            break
        st, _ = run.state(i, hand)
        if st not in ROLE_STATES[a.role]:
            continue
        last = max((h for h in hand.get(i, []) if h["role"] == a.role), key=lambda h: h["t"], default=None)
        f = run.folder(i)
        report = f / "work" / ("review.json" if a.role == "review" else "curation.json")
        if last and t - last["t"] < LEASE_S and mtime(report) < last["t"]:
            continue                            # handed out recently and its report has not arrived
        g, slug = run.graph(i)
        src = run.source(i)
        si = (read_json(f / "work" / "si.json") or {}).get("files") or []
        si_read = [f"{x['file']} (pages {x['pages']})" for x in si if x.get("pages")]
        si_left = [f"{x['file']}: {x['left_out']}" for x in si if x.get("left_out")]
        chk = run.check(i) if a.role == "fix" else {}
        review = read_json(f / "work" / "review.json") or {}
        fixes = sum(1 for h in hand.get(i, []) if h["role"] == "fix")
        text = tpl.substitute(
            scale=run.cmd, folder=str(f), graph=g.name, slug=slug, title=src.get("title") or slug,
            year=src.get("year") or "year unknown", doi=src.get("doi") or "none", licence=src.get("licence") or "unknown",
            text_version=src.get("text_version") or "not known", attempt=fixes + 1,
            start_note=("**Note:** " + src["note"] + ".") if src.get("note") else "",
            si_read=bullet(si_read, "none appended"), si_left=bullet(si_left, "none"),
            check_errors=bullet([e.get("message") or json.dumps(e) for e in chk.get("errors") or []], "none"),
            issues=bullet([f"{x.get('record', '?')} ({x.get('locator', '')}): {x.get('problem', '')} → {x.get('fix', '')}"
                           for x in review.get("issues") or []] if st == "needs_fix" else [], "none"))
        p = run.d / "prompts" / a.role / f"{i}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        append_jsonl(run.d / "handouts.jsonl", {"id": i, "role": a.role, "t": t, "at": now()})
        out.append({"id": i, "role": a.role, "prompt": str(p)})
    for o in out:
        print(json.dumps(o))
    if not out:
        print(json.dumps({"role": a.role, "handed_out": 0, "next": "curate_run.py status --run " + str(run.d)}))


# ------------------------------------------------------------------ status
def cmd_status(a):
    run = Run(a.run)
    hand = run.handouts()
    states, by_state, gaps, nodes, kinds, concepts = {}, {}, 0, 0, Counter(), []
    for i in run.ids():
        st, detail = run.state(i, hand)
        states[i] = (st, detail)
        by_state.setdefault(st, []).append(i)
        chk = read_json(run.folder(i) / "work" / "check.json") or {}
        gaps += chk.get("gaps") or 0                      # gaps recorded on the document's records
        nodes += max(0, ((chk.get("records") or {}).get("nodes") or 3) - 3)
        for g in run.gap_files(i):                        # gap reports written as files
            kinds[g["kind"]] += 1
            if g["kind"] == "missing_concept":
                concepts.append({"source": i, "gap": g["id"], "about": g["about"]})
    applied = 0
    if a.apply:
        last = {r["id"]: r for r in jsonl(run.d / "state.jsonl")}
        root = Path(run.cfg["project_root"]) if run.cfg.get("project_root") else None
        topic = run.cfg.get("topic")
        handoff = root / ".scripts" / topic / "kg" / run.cfg["name"] / "extraction_status.jsonl" \
            if root and topic else None
        for i, (st, detail) in states.items():
            if st not in SETTLED:
                continue
            result = {"passed": "extracted" if detail != "no_data" else "no_data", "rejected": "rejected",
                      "failed": "failed"}[st]
            if last.get(i, {}).get("result") == result:
                continue
            chk = read_json(run.folder(i) / "work" / "check.json") or {}
            rec = chk.get("records") or {}
            row = {"id": i, "state": st, "result": result, "detail": detail, "at": now(),
                   "schema_version": run.cfg.get("schema_version"), "nodes": rec.get("nodes"), "links": rec.get("links")}
            append_jsonl(run.d / "state.jsonl", row)
            pid = run.source(i).get("paper_id")
            if handoff and pid is not None:
                append_jsonl(handoff, {"paper_id": pid, "topic": topic, "kg": run.cfg["name"], "status": result,
                                       "schema_version": run.cfg.get("schema_version"), "nodes": rec.get("nodes"),
                                       "edges": rec.get("links"), "date": now()[:10],
                                       "note": f"scale-catal document: {run.folder(i)}" if result == "extracted" else detail})
            applied += 1
        index = index_export(root) if applied and handoff else None
    counts = Counter(st for st, _ in states.values())
    todo = [f"next --role {r} ({sum(counts[s] for s in ss)})" for r, ss in ROLE_STATES.items()
            if sum(counts[s] for s in ss)]
    print(json.dumps({"run": str(run.d), "sources": len(states), "states": dict(sorted(counts.items())),
                      "settled": sum(counts[s] for s in SETTLED), "nodes_added": nodes,
                      "gaps": {"on_records": gaps, "reports": dict(sorted(kinds.items())),
                               "missing_concept": concepts[:20]},
                      "lists": {k: v[:50] for k, v in sorted(by_state.items()) if k != "passed"},
                      "applied": applied if a.apply else None, "index": index if a.apply else None,
                      "next": todo or (["finish"] if counts["passed"] else ["nothing left to do"])}))


# ------------------------------------------------------------------ finish / contribute
def passed(run):
    """The sources settled as passed whose document holds what they report (not no_data)."""
    hand = run.handouts()
    return [i for i in run.ids() if run.state(i, hand) == ("passed", "curated")]


def cmd_finish(a):
    run = Run(a.run)
    res, bad = {}, {}
    for i in passed(run):
        rc, out, err = scale(run.cmd, "source", "finish", run.folder(i), *(["--public"] if a.public else []),
                             *(["--bundle"] if a.bundle else []))
        (res if rc == 0 and out else bad)[i] = out if rc == 0 and out else err[-300:]
    write_json(run.d / "finish.json", {"at": now(), "public": a.public, "bundle": a.bundle, "finished": res,
                                       "failed": bad})
    print(json.dumps({"run": str(run.d), "finished": len(res), "failed": bad, "report": str(run.d / "finish.json")}))


def cmd_contribute(a):
    run = Run(a.run)
    res = {}
    for i in passed(run):
        g, _ = run.graph(i)
        outcome, msg = contribute(run.cmd, g, a.to)
        res[i] = {"outcome": outcome, "report": msg}
    write_json(run.d / "contribute-dry-run.json", {"at": now(), "to": a.to, "sources": res})
    print(json.dumps({"run": str(run.d), "would_add": sum(r["outcome"] == "dry_run" for r in res.values()),
                      "already_there": [i for i, r in res.items() if r["outcome"] == "already"],
                      "refused": [i for i, r in res.items() if r["outcome"] == "refused"],
                      "report": str(run.d / "contribute-dry-run.json"),
                      "next": "a person reviews the report; writing is `scale graph contribute <graph> --to <folder> "
                              "--write` on an agent/… branch, then a pull request"}))


def cmd_assemble(a):
    """A local graph kept as parts holding every passed document of the run (scale graph contribute --write into a
    folder of the run, never the repository), built into one document that query-graph can query."""
    run = Run(a.run)
    out = Path(a.out).resolve() if a.out else run.d / "graph"
    name = re.sub(r"[^a-z0-9-]+", "-", run.cfg["name"].lower()).strip("-") or "run"
    ns, version = f"ex:{name}", run.cfg.get("schema_version")
    contributor = run.cfg.get("contributor") or "scale:org/scale-researchers"
    project = run.cfg.get("project") or f"{ns}/project/{name}"
    if not (out / "parts" / "header.json").is_file():
        stew = {"contributed_by": [contributor], "project": project, "access": "public"}
        write_json(out / "parts" / "header.json", {"directed": True, "multigraph": True, "graph": {
            "schema": "scale-catal", "schema_version": version, "graph_id": f"{ns}/graph/{name}",
            "title": (a.title or f"Curation run {name}")[:40], "data_status": "research_data",
            "description": f"The scale-catal documents of the curation run {name}, one part per source, assembled "
                           f"locally with scale graph contribute from {run.cfg['corpus']}.",
            "follows_domains": ["catalysis"], "stewardship": stew}})
        write_json(out / "parts" / "shared.json", {"schema_version": version, "nodes": [
            {"id": contributor, "label": "Institution", "props": {"name": contributor.rsplit("/", 1)[-1], "origin": "curated"}},
            {"id": project, "label": "Project", "props": {"name": f"Curation run {name}", "origin": "curated"}}],
            "links": [{"id": f"{project}/participant/{contributor.rsplit('/', 1)[-1]}", "type": "PARTICIPATES_IN",
                       "source": contributor, "target": project, "props": {"origin": "curated", "role": "data_provider"}}]})
        (out / "rights.yaml").write_text("# Rights of the sources of this local graph, one entry per source, added with "
                                         "the source (scale graph contribute).\nsources: {}\n", encoding="utf-8")
        (out / "stewardship.yaml").write_text(f"default:\n  contributed_by: [{json.dumps(contributor)}]\n"
                                              f"  project: {json.dumps(project)}\n  access: public\n", encoding="utf-8")
    added, already, refused = [], [], {}
    for i in passed(run):
        g, _ = run.graph(i)
        outcome, msg = contribute(run.cmd, g, out, write=True)
        {"added": added, "already": already}.get(outcome, []).append(i)
        if outcome == "refused":
            refused[i] = msg
    rc, _, err = scale(run.cmd, "graph", "build", out)
    built = sorted(out.glob("*.graph.json"))
    print(json.dumps({"graph": str(out), "built": str(built[0]) if rc == 0 and built else None, "added": len(added),
                      "already_there": len(already), "refused": refused, "build_error": None if rc == 0 else err[-300:],
                      "next": f"query-graph: scale graph query {out} <plan.yaml>"}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--corpus", required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--ids", help="comma list of paper IDs or slugs to curate (default: every included source)")
    p.add_argument("--ids-file", help="a file of paper IDs or slugs, one per line")
    p.add_argument("--max", type=int, help="at most this many sources (in manifest order)")
    p.add_argument("--contributor", help="who curates: a stewardship registry id (scale source start --contributor)")
    p.add_argument("--project", help="the project the documents belong to (scale source start --project)")
    p.add_argument("--version", help="the schema version to pin (default: SCALE's head; the version of the graph the "
                                     "documents will be contributed to, e.g. graphs/catal-commons)")
    p.add_argument("--no-si", action="store_true", help="do not append the SI files' text to the page texts")
    p.add_argument("--scale", help='the scale command (default: $SCALE_CMD or "scale"; e.g. "uv run --project <checkout> scale")')
    p = sub.add_parser("next")
    p.add_argument("--run", required=True)
    p.add_argument("--role", required=True, choices=sorted(ROLE_STATES))
    p.add_argument("--n", type=int, default=5)
    p = sub.add_parser("status")
    p.add_argument("--run", required=True)
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("finish")
    p.add_argument("--run", required=True)
    p.add_argument("--public", action="store_true")
    p.add_argument("--bundle", action="store_true")
    p = sub.add_parser("assemble")
    p.add_argument("--run", required=True)
    p.add_argument("--out", help="the local graph folder (default: <run>/graph)")
    p.add_argument("--title", help="the graph's title (at most 40 characters)")
    p = sub.add_parser("contribute")
    p.add_argument("--run", required=True)
    p.add_argument("--to", required=True, help="a graph kept as parts, e.g. <hlxin/scale checkout>/graphs/catal-commons")
    a = ap.parse_args()
    {"prepare": cmd_prepare, "next": cmd_next, "status": cmd_status, "finish": cmd_finish, "assemble": cmd_assemble,
     "contribute": cmd_contribute}[a.cmd](a)


if __name__ == "__main__":
    main()
