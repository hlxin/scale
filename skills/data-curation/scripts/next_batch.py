"""Phase 2 — the next papers to dispatch, with ready-to-use subagent prompts (one paper per subagent).

  python3 -I next_batch.py --topic co2rr --name co2rr-catalysts --role extract --n 5   # extraction prompts
  python3 -I next_batch.py --topic co2rr --name co2rr-catalysts --role review --n 5    # reviewer prompts
  python3 -I next_batch.py --topic co2rr --name co2rr-catalysts --role fix --n 5       # one corrective pass
  python3 -I next_batch.py ... --role extract --all     # re-extract every paper (after --replace-schema)
  python3 -I next_batch.py ... --role alias              # the alias-review prompt (after merge_graph.py)

Prints one JSON line per paper: {"paper_id", "prompt", "output", "model"}. Launch one Agent per line in ONE message
with the prompt "Read <prompt> and follow it exactly." Prompts live in .scripts/<topic>/kg/<name>/batches/; a paper
handed out in the last 2 hours is not handed out again (use --redispatch after a crash). Prints nothing when there is
no work for that role.
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _kgcommon import SKILL, Run, add_root_arg, read_json, write_json

STALE_SEC = 2 * 3600
SCRIPTS = Path(__file__).resolve().parent


def dispatched(run, role):
    p = run.work / f"dispatched_{role}.json"
    return p, (read_json(p, {}) or {})


def render(name, values):
    t = (SKILL / "templates" / name).read_text(encoding="utf-8")
    for k, v in values.items():
        t = t.replace("{{" + k + "}}", str(v))
    return t


def common(run, p, schema, st):
    opts = st.get("options") or {}
    si = p.get("si") or []
    rules = schema.get("faithfulness_rules") or []
    return {
        "PAPER_ID": p["paper_id"], "SCHEMA_PATH": str(run.schema), "PDF_PATH": p["pdf"],
        "PAGE_COUNT": p.get("pages") or "unknown", "SI_PATHS": "\n".join(f"   - {x}" for x in si) or "   - (none on disk)",
        "SI_STATUS": f"{len(si)} file(s)" if si else "no SI file was downloaded",
        "FIGURES_DIR": str(run.figures), "VALIDATE_SCRIPT": str(SCRIPTS / "validate_kg.py"),
        "EXTRACT_FIGURES_SCRIPT": str(SCRIPTS / "extract_figures.py"), "SI_TEXT_SCRIPT": str(SCRIPTS / "si_text.py"),
        "PAPER_META": json.dumps({k: p.get(k) for k in ("doi", "title", "year", "venue", "doc_type")}, ensure_ascii=False),
        "SCOPE": schema.get("scope") or "(the schema states no scope: every paper of the run is in scope)",
        "TOPIC": schema.get("topic") or run.topic,
        "DOMAIN_RULES": "\n".join(f"- {r}" for r in rules) or "- (none beyond the defaults)",
        "FIGURES_ON": "yes" if opts.get("figures", True) else "no",
        "ABSTRACT_TASK": ("The index has NO abstract for this paper: copy the paper's abstract VERBATIM into "
                          "`paper.abstract` (the full abstract paragraph as printed; no paraphrase)."
                          if (opts.get("fill_abstracts", True) and not p.get("has_abstract")) else
                          "The index already has this paper's abstract: leave `paper.abstract` out."),
    }


def main():
    ap = add_root_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--role", choices=["extract", "review", "fix", "alias"], required=True)
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--all", action="store_true", help="extract: re-extract papers that already have a fragment")
    ap.add_argument("--redispatch", action="store_true", help="ignore the 2-hour hand-out memory")
    a = ap.parse_args()
    run = Run(a.project, a.topic, a.name).ensure()
    schema = read_json(run.schema)
    if not schema:
        print(json.dumps({"error": "no schema — run prepare_run.py first"}))
        return 2
    st = run.state()
    if a.role == "alias":
        nm = schema.get("never_merge") or []
        text = render("alias_review_subagent.md", {
            "CLUSTERS_PATH": str(run.work / "alias_candidates.json"), "HUBS_PATH": str(run.work / "hubs.json"),
            "SCHEMA_PATH": str(run.schema), "OUTPUT_PATH": str(run.work / "alias_map.proposed.json"),
            "NEVER_MERGE": "\n".join(f"  - {x}" for x in nm) or "  - (the schema lists none)"})
        prompt = run.batches / "alias_review.md"
        prompt.write_text(text, encoding="utf-8")
        print(json.dumps({"role": "alias", "prompt": str(prompt), "output": str(run.work / "alias_map.proposed.json"),
                          "model": "sonnet"}))
        return 0
    papers = run.papers()
    final = run.statuses()
    dpath, disp = dispatched(run, a.role)
    now = time.time()
    fresh = {int(k) for k, t in disp.items() if now - t < STALE_SEC and not a.redispatch}
    out = []
    from validate_kg import validate_target_file
    sch_dir = run.schema.parent

    for pid, p in papers.items():
        if len(out) >= a.n:
            break
        if not p.get("pdf") or pid in fresh:
            continue
        frag, rev = run.fragment(pid), run.review(pid)
        if a.role == "extract":
            if pid in final and not a.all:
                continue
            if frag.exists():
                if not a.all:
                    continue
                shutil.move(str(frag), str(run.frag / "superseded" / f"paper_{pid}.{int(now)}.json"))
            vals = common(run, p, schema, st)
            vals.update({"OUTPUT_PATH": str(frag), "FIXES": "(first extraction — no reviewer feedback yet)"})
            text, model = render("extraction_subagent.md", vals), "sonnet"
        elif a.role == "review":
            if pid in final or not frag.exists() or rev.exists():
                continue
            ok, errs, _ = validate_target_file(frag, schema, sch_dir, False)
            if not ok:
                continue          # invalid fragments are handled by review_status.py (re-extraction)
            vals = common(run, p, schema, st)
            vals.update({"FRAGMENT_PATH": str(frag), "OUTPUT_PATH": str(rev)})
            text, model = render("review_subagent.md", vals), "sonnet"
        else:  # fix
            if pid in final or not rev.exists():
                continue
            r = read_json(rev, {}) or {}
            if r.get("status") != "needs_fix":
                continue
            attempts = ((st.get("papers") or {}).get(str(pid)) or {}).get("fix_attempts", 0)
            if attempts >= 1:
                continue          # one corrective pass only; review_status.py --apply settles it
            if frag.exists():
                shutil.move(str(frag), str(run.frag / "superseded" / f"paper_{pid}.{int(now)}.json"))
            shutil.move(str(rev), str(run.reviews / f"paper_{pid}.needs_fix.{int(now)}.json"))
            fixes = [f"- {i.get('target')}: {i.get('problem')} -> {i.get('fix')}" for i in r.get("text_issues") or []]
            fixes += [f"- {i.get('fig_id')}: {i.get('verdict')} — {i.get('reason')} {i.get('recrop_hint') or ''}".rstrip()
                      for i in r.get("figure_issues") or [] if i.get("verdict") != "ok"]
            vals = common(run, p, schema, st)
            vals.update({"OUTPUT_PATH": str(frag),
                         "FIXES": "A reviewer checked your earlier extraction of this paper and found these problems. "
                                  "Re-extract the whole paper and fix every one:\n" + ("\n".join(fixes) or "- (see summary) "
                                  + str(r.get("summary") or ""))})
            text, model = render("extraction_subagent.md", vals), "sonnet"
            papers_state = st.setdefault("papers", {})
            papers_state.setdefault(str(pid), {})["fix_attempts"] = attempts + 1
            run.update_state(papers=papers_state)
        bdir = run.batches / a.role
        bdir.mkdir(parents=True, exist_ok=True)
        prompt = bdir / f"paper_{pid}.md"
        prompt.write_text(text, encoding="utf-8")
        disp[str(pid)] = now
        out.append({"paper_id": pid, "prompt": str(prompt), "output": str(rev if a.role == "review" else frag),
                    "model": model, "pages": p.get("pages")})
    write_json(dpath, disp)
    if out:
        run.update_state(phase="extraction", next=f"wait for {len(out)} {a.role} subagents, then review_status.py --apply")
    for o in out:
        print(json.dumps(o))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
