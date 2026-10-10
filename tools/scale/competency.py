"""Competency questions: what the catalysis schema must let people ask, checked against public examples.

The catalysis domain keeps its questions in ``domain/competency/*.yaml``, one question per file::

    id: CQ-01
    question: Which ammonia Faradaic efficiencies were measured in nitrate electroreduction, and how?
    documents:                     # public example documents (among the domain's example_documents.graph),
      - examples/scale-graph/driving-force-examples/electro.json        # relative to domain/
    plan:                          # a scale-graph query plan (docs/querying.md)
      match: {label: CatalyticTest, as: test, where: [{prop: faradaic_efficiency, op: exists}]}
      return: [test.name, test.faradaic_efficiency]
    expect:                        # what the answer must be
      status: answered             # answered | no_matching_record | missing_context | schema_gap
      min_rows: 3                  # optional: min_rows, max_rows
      values:                      # optional: values the rows must return (all of them, in any row)
        test.control_mode: [potentiostatic, pulsed]
      schema_gaps: [...]           # optional, with status schema_gap: what the schema cannot express
      excluded:                    # optional: how many records were left out, by reason code (exactly; all of
        rests_on_retracted_source: 1   # them, each once, as the result's coverage counts them, not only the listed)
      source_statuses: [retracted] # optional: publication statuses the rows' evidence must carry (plan evidence: true)
    variants:                      # optional: the same question with plan keys changed, and what it must answer then
      - description: With include_retracted, the row resting on a retracted source comes back, labelled.
        plan:
          include_retracted: true
        expect: {...}

A variant shows what changes when one plan key changes (the opt-in that brings back rows resting on
retracted sources, for example); it runs on the same documents and counts with its question.

``run`` executes the plan on each document under the schema version the document pins (the domain's
manifest, or its frozen copy) and compares the combined answer with the expectation. A question
without ``plan`` is a stub (the template's): it is listed, never counted as answered. ``scale domains
cq`` runs the domain's questions; ``scale domains check`` counts only the questions that run and
meet their expectation towards the domain's stewardship targets.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from . import layout
from .util import ScaleError, load_doc, load_yaml

STATUSES = ("answered", "no_matching_record", "missing_context", "schema_gap")
EXPECT_KEYS = ("status", "min_rows", "max_rows", "values", "schema_gaps", "excluded", "source_statuses")
KEYS = ("id", "question", "description", "documents", "plan", "expect", "variants")
VARIANT_KEYS = ("description", "plan", "expect")


def _declared_examples(domain_dir: Path, m: dict) -> list[str]:
    """The domain's example documents (``example_documents.graph``, globs allowed), domain-relative."""
    return [str(g) for g in (m.get("example_documents") or {}).get("graph") or []]


def _combine(results: list[dict]) -> dict:
    """One answer over several documents: rows add up; the status is ``answered`` when any document
    answers, else the most telling absence (a schema gap, then missing context, then no match)."""
    statuses = [r["status"] for r in results]
    status = "answered" if "answered" in statuses else next(
        (s for s in ("schema_gap", "missing_context", "no_matching_record") if s in statuses), "no_matching_record")
    values: dict[str, list] = {}
    excluded: dict[str, int] = {}
    statuses: set[str] = set()
    from .pgraph_query import reason_code
    for r in results:
        for row in r.get("rows") or []:
            for k, v in (row.get("values") or {}).items():
                values.setdefault(k, []).append(v)
            statuses |= {ev["source_status"] for ev in row.get("evidence") or [] if ev.get("source_status")}
        by_reason = ((r.get("coverage") or {}).get("excluded") or {}).get("by_reason")
        if by_reason is None:                      # a result without coverage: count the listed records by reason code
            by_reason = {}
            for x in r.get("excluded") or []:
                code = reason_code(x.get("reason"))
                by_reason[code] = by_reason.get(code, 0) + 1
        for code, n in by_reason.items():          # counted in full, not only the records excluded lists
            excluded[code] = excluded.get(code, 0) + n
    gaps = sorted({g for r in results for g in r.get("schema_gaps") or []})
    return {"status": status, "rows": sum(r.get("row_count") or 0 for r in results), "values": values, "schema_gaps": gaps,
            "excluded": excluded, "source_statuses": sorted(statuses)}


def _scalar(v):
    if isinstance(v, dict):
        for k in ("value", "text_value", "ref_value", "boolean_value", "status"):
            if k in v:
                return v[k]
    return v


def meets(answer: dict, expect: dict) -> list[str]:
    """What in ``answer`` falls short of ``expect`` (empty: it meets it)."""
    out = []
    if expect.get("status") and answer["status"] != expect["status"]:
        out.append(f"status {answer['status']}, expected {expect['status']}")
    if "min_rows" in expect and answer["rows"] < int(expect["min_rows"]):
        out.append(f"{answer['rows']} rows, expected at least {expect['min_rows']}")
    if "max_rows" in expect and answer["rows"] > int(expect["max_rows"]):
        out.append(f"{answer['rows']} rows, expected at most {expect['max_rows']}")
    for field, wanted in (expect.get("values") or {}).items():
        got = {str(_scalar(x)) for x in answer["values"].get(field, [])}
        absent = [w for w in wanted if str(w) not in got]
        if absent:
            out.append(f"{field} never returns {absent} (returned: {sorted(got)[:8]})")
    for g in expect.get("schema_gaps") or []:
        if g not in answer["schema_gaps"]:
            out.append(f"schema gap {g!r} not reported (reported: {answer['schema_gaps']})")
    for reason, n in (expect.get("excluded") or {}).items():
        got = (answer.get("excluded") or {}).get(reason, 0)
        if got != int(n):
            out.append(f"{got} rows excluded for {reason}, expected {n}")
    absent = [s for s in expect.get("source_statuses") or [] if s not in (answer.get("source_statuses") or [])]
    if absent:
        out.append(f"the evidence never carries source_status {absent} (carried: {answer.get('source_statuses') or []})")
    return out


def _expect_problems(expect, where: str = "expect") -> list[str]:
    if not isinstance(expect, dict) or not expect.get("status"):
        return [f"{where}.status is required (what the answer must be)"]
    if expect["status"] not in STATUSES:
        return [f"{where}.status {expect['status']!r} is not one of {STATUSES}"]
    if any(k not in EXPECT_KEYS for k in expect):
        return [f"{where}: unknown key(s) {[k for k in expect if k not in EXPECT_KEYS]} (known: {EXPECT_KEYS})"]
    return []


def run_question(repo: Path, domain: str, path: Path, m: dict | None = None, cache: dict | None = None) -> dict:
    """Run one competency question of the domain ``domain`` (its name, catalysis) and compare it with its
    expectation."""
    from . import pgraph, pgraph_query
    from .passages import index_for
    repo = Path(repo)
    cache = {} if cache is None else cache
    base = layout.domain_layers(repo).get(domain) or repo / layout.DOMAIN
    m = m if m is not None else (load_yaml(base / layout.DOMAIN_MANIFEST) or {})
    q = load_yaml(path) or {}
    out = {"domain": domain, "file": path.relative_to(repo).as_posix(), "id": q.get("id") if isinstance(q, dict) else None,
           "question": q.get("question") if isinstance(q, dict) else None, "stub": False, "ok": False, "problems": []}
    if not isinstance(q, dict):
        out["problems"].append("a competency question is a mapping")
        return out
    unknown = [k for k in q if k not in KEYS]
    if unknown:
        out["problems"].append(f"unknown key(s) {unknown} (known: {', '.join(KEYS)})")
    if not q.get("id") or not q.get("question"):
        out["problems"].append("a competency question has an id and states its question")
    if not q.get("plan"):
        out["stub"] = True                                   # listed, not answered: nothing to run yet
        return out
    expect = q.get("expect") or {}
    out["problems"] += _expect_problems(expect)
    variants = q.get("variants") or []
    if not isinstance(variants, list):
        out["problems"].append("variants is a list of {description, plan, expect}")
        variants = []
    for i, v in enumerate(variants):
        if not isinstance(v, dict) or not isinstance(v.get("plan"), dict) or not v["plan"]:
            out["problems"].append(f"variants[{i}]: a variant names the plan keys it changes (plan)")
            continue
        if any(k not in VARIANT_KEYS for k in v):
            out["problems"].append(f"variants[{i}]: unknown key(s) {[k for k in v if k not in VARIANT_KEYS]} (known: {VARIANT_KEYS})")
        out["problems"] += _expect_problems(v.get("expect") or {}, f"variants[{i}].expect")
    docs = q.get("documents") or []
    if not docs:
        out["problems"].append("documents: name the public example documents the question runs on")
    declared = _declared_examples(base, m)
    manifest = layout.graph_manifests(repo, experimental=True).get(domain)
    if manifest is None:
        out["problems"].append(f"{domain} has no scale-graph schema (DOMAIN.yaml graph.manifest)")
    if out["problems"]:
        return out
    plans = [q["plan"]] + [{**q["plan"], **v["plan"]} for v in variants]
    results: list[list[dict]] = [[] for _ in plans]
    for rel in docs:
        if not any(fnmatch.fnmatch(str(rel), g) for g in declared):
            out["problems"].append(f"{rel} is not one of the domain's example documents (example_documents.graph)")
            continue
        p = base / rel
        if not p.is_file():
            out["problems"].append(f"{rel} does not exist")
            continue
        try:
            doc = load_doc(p)
            access = ((doc.get("graph") or {}).get("stewardship") or {}).get("access")   # missing: institution,
            if access != "public":                                                        # as pgraph.visible reads it
                out["problems"].append(f"{rel} is not public (stewardship access {access or 'not stated'}): competency questions "
                                       "run on public examples, so that anyone can rerun them")
                continue
            spec_path = pgraph.pinned(manifest, (doc.get("graph") or {}).get("schema_version"), doc)
            if str(spec_path) not in cache:
                cache[str(spec_path)] = pgraph.load_spec(spec_path)
            stem = p.with_name(p.name.removesuffix(".json").removesuffix(".graph") + ".evidence")
            ix = index_for(stem, doc) if q["plan"].get("text") else None
            for i, plan in enumerate(plans):
                results[i].append(pgraph_query.run(doc, cache[str(spec_path)], plan, ix))
        except (ScaleError, OSError, ValueError, KeyError, TypeError) as exc:
            out["problems"].append(f"{rel}: the plan does not run: {exc}")
    if out["problems"]:
        return out
    answer = _combine(results[0])
    out.update(answer={k: answer[k] for k in ("status", "rows", "schema_gaps")}, expect=expect)
    out["problems"] = meets(answer, expect)
    for i, v in enumerate(variants):
        va = _combine(results[i + 1])
        out.setdefault("variants", []).append({"plan": v["plan"], "answer": {k: va[k] for k in ("status", "rows", "schema_gaps")},
                                               "expect": v["expect"]})
        out["problems"] += [f"variant {i} ({', '.join(f'{k}: {x}' for k, x in v['plan'].items())}): {m}"
                            for m in meets(va, v["expect"])]
    out["ok"] = not out["problems"]
    return out


def run(repo: Path, names: list[str] | None = None) -> dict:
    """Run every competency question of the domain (``names``: its name, catalysis; default: it)."""
    repo = Path(repo)
    rows, cache = [], {}
    layers = layout.domain_layers(repo)
    unknown = [n for n in names or [] if n not in layers]
    if unknown:
        raise ScaleError(f"no domain {', '.join(unknown)}; domains: {', '.join(layers)}")
    for name, d in layers.items():
        if names and name not in names:
            continue
        m = load_yaml(d / layout.DOMAIN_MANIFEST) if (d / layout.DOMAIN_MANIFEST).is_file() else {}
        for p in sorted((d / layout.DOMAIN_COMPETENCY).glob("*.yaml")):
            rows.append(run_question(repo, name, p, m or {}, cache))
    ran = [r for r in rows if not r["stub"]]
    # over the whole repository, a run that answers nothing checks nothing: that fails
    return {"ok": (bool(ran) or bool(names)) and all(r["ok"] for r in ran) and not any(r["problems"] for r in rows),
            "questions": rows, "answered_as_expected": sum(r["ok"] for r in ran), "stubs": sum(r["stub"] for r in rows)}


def text(res: dict) -> str:
    lines = []
    for r in res["questions"]:
        mark = "stub" if r["stub"] and not r["problems"] else "ok  " if r["ok"] else "FAIL"
        ans = r.get("answer") or {}
        lines.append(f"{mark} {r['domain']} {r['id'] or r['file']}: {r['question'] or ''}"
                     + (f" -> {ans['status']}, {ans['rows']} rows" if ans else ""))
        lines += [f"     {x}" for x in r["problems"]]
    lines.append(f"{res['answered_as_expected']} question(s) answered as expected, {res['stubs']} stub(s); "
                 + ("all competency questions answer as expected" if res["ok"] else "some competency questions fail"))
    return "\n".join(lines)
