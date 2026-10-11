"""The ``scale`` command-line interface."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from . import __version__, layout
from .util import ScaleError, find_repo_root, list_docs, load_doc, load_yaml, to_json, write_json
from .versions import normalize_release_id


# ---------------------------------------------------------------- helpers

def _repo(args) -> Path:
    return Path(args.repo).resolve() if getattr(args, "repo", None) else find_repo_root()


def _emit(data, args, markdown: str | None = None) -> None:
    fmt = getattr(args, "format", "json")
    text = markdown if (fmt == "markdown" and markdown is not None) else (to_json(data) if not isinstance(data, str) else data)
    if getattr(args, "out", None):
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)


def _source_texts(pairs: list[str] | None) -> dict[str, str]:
    import html
    out = {}
    for p in pairs or []:
        sid, _, path = p.partition("=")
        if not path:
            raise ScaleError(f"--source-text expects <source-id>=<file>, got {p!r}")
        out[sid] = html.unescape(Path(path).read_text(encoding="utf-8", errors="ignore"))
    return out


# ---------------------------------------------------------------- commands

def cmd_graph_migrate(args):
    from . import pgraph
    from .pgraph_migrate import STEPS, raise_version
    from .util import write_canonical
    doc = load_doc(args.file)
    manifest = pgraph.spec_path(_repo(args), args.spec, doc)
    spec = pgraph.load_spec(manifest)
    have = (doc.get("graph") or {}).get("schema_version")
    if have == spec["version"]:
        raise ScaleError(f"{args.file} is already at scale-catal {have}")
    if have not in STEPS:
        raise ScaleError(f"{args.file} pins scale-catal {have}; migrations run along the steps {sorted(STEPS) or '(none yet)'} "
                         f"to {spec['version']}")
    new, rep = raise_version(doc, spec["version"], spec)
    rep["validation"] = pgraph.validate(new, spec).as_dict()["summary"]
    write_canonical(Path(args.dest), new)
    rep["written"] = args.dest
    _emit(rep, args)
    return 0 if rep["validation"]["error"] == 0 else 1


def cmd_graph_validate(args):
    from . import pgraph
    reports, versions = {}, {}
    for f in args.files:
        doc = load_doc(f)
        spec = pgraph.load_spec(pgraph.spec_for(_repo(args), doc.get("graph", {}).get("schema_version"), args.spec, doc))
        versions[f] = spec
        rep = pgraph.validate(doc, spec, _source_texts(args.source_text))
        reports[f] = rep.as_dict()
    if args.format == "json":
        _emit(reports if len(reports) > 1 else next(iter(reports.values())), args)
    else:
        for f, r in reports.items():
            spec = versions[f]
            print(f"{f}: {spec.get('schema', 'scale-catal')} {spec['version']} ({spec['status']}): {'VALID' if r['valid'] else 'INVALID'} "
                  f"{ {k: r['summary'][k] for k in ('error', 'warning')} } {r['counts']}")
            for i in r["errors"][:50] + (r["warnings"][:20] if args.verbose else []):
                print(f"  {i['record']}: {i['message']}")
            lc = r["summary"].get("source_lifecycle")
            if lc:                                  # notices recorded: what rests on retracted sources (flagged, not rewritten)
                print(f"  source lifecycle: sources {lc['sources_by_status'] or 'with no notice'}, {lc['sources_checked']} checked; "
                      f"records resting on retracted sources: {lc['rests_on_retracted_source']} only, "
                      f"{lc['partially_rests_on_retracted_source']} in part")
            what = "domain" if (r.get("conformance") or {}).get("declared_by") == "follows_domains" else "profile"
            for ref, c in ((r.get("conformance") or {}).get("profiles") or {}).items():
                rec = c["recommended"]
                frac = "n/a" if rec["fraction"] is None else f"{rec['fraction']:.0%}"
                print(f"  {what} {ref}: {'CONFORMANT' if c['conformant'] else 'NOT CONFORMANT'}, "
                      f"{c['nodes_checked']} nodes checked, {len(c['violations'])} violations, "
                      f"{'should' if what == 'domain' else 'recommended'} filled {rec['filled']}/{rec['expected']} ({frac})")
                for v in c["violations"][:20 if args.verbose else 5]:
                    print(f"    {v['record']}: {v['message']}")
    if not all(r["valid"] for r in reports.values()):
        raise SystemExit(1)


def cmd_graph_stats(args):
    from . import pgraph
    doc = load_doc(args.file)
    _emit(pgraph.stats(doc), args)


def _viewer_doc(args, doc=None):
    from . import pgraph
    doc = load_doc(args.file) if doc is None else doc
    if args.viewer is None and not args.public:
        return doc
    # embargoes are read on --date or today (the earlier of the local and UTC dates), whichever is earlier: a later
    # date never opens one still in force
    return pgraph.filter_for(doc, args.viewer or [], pgraph.embargo_day(args.date, pgraph.embargo_today(), "--date"))


def _bundle_audience(args, doc) -> dict | None:
    """The audience a kg-bundle declares (kgbundle.export's ``access``): public with --public; with --as, the
    viewer's own, one project ({access: project, project}) or institutions ({access: institution, contributed_by});
    otherwise None, the graph's stewardship. A person, several projects, a mix or an id the graph does not hold has
    no stewardship to declare, so it is refused."""
    from . import pgraph
    if args.public and args.viewer:
        raise ScaleError("a kg-bundle has one audience: give --public or --as, not both")
    if args.public:
        return {"access": "public"}
    if args.viewer is None:
        return None
    declared = pgraph.view_audience(doc, args.viewer)          # the same audience scale graph filter's view declares
    if declared is not None:
        return declared
    labels = {n["id"]: n["label"] for n in doc["nodes"]}
    named = ", ".join(f"{v} ({labels.get(v) or 'not in the graph'})" for v in sorted(set(args.viewer)))
    raise ScaleError(f"--as {named}: a kg-bundle declares its audience as a stewardship, so name one project or "
                     "one or more institutions of the graph (for a person, their institution), or use --public; "
                     "scale graph filter --as filters for any viewer")


def cmd_graph_filter(args):
    if args.viewer is None and not args.public:
        raise ScaleError("name a viewer with --as <agent-or-project-id> (repeatable) or use --public")
    args.format = "json"
    _emit(_viewer_doc(args), args)


def cmd_graph_export(args):
    from . import pgraph
    if args.to == "kg-bundle":
        from . import kgbundle
        if not args.out:
            raise ScaleError("a kg-bundle is a folder: give --out DIR")
        doc = load_doc(args.file)
        # the bundle declares its audience: the graph's stewardship, the public (--public) or the viewer's own (--as)
        access = _bundle_audience(args, doc)
        doc = _viewer_doc(args, doc)
        spec = pgraph.load_spec(pgraph.spec_for(_repo(args), doc["graph"].get("schema_version"), args.spec, doc))
        texts = {}
        for t in args.text or []:
            sid, _, rest = t.partition("=")
            fname, _, licence = rest.partition(":")
            if not licence.strip():      # shipping a text redistributes it: its licence is stated, never assumed
                raise ScaleError(f"--text {t}: name the text's licence, <source id>=<file>:<licence> (an SPDX id or the "
                                 "source's own licence statement; 'unknown' when it is not known)")
            texts[sid] = (Path(fname).name, Path(fname).read_text(encoding="utf-8"), licence.strip())
        bid = args.bundle_id or (doc["graph"].get("graph_id") or "scale-catal").split(":")[-1].replace("/", "-")
        lineage = _bundle_lineage(args)
        unshipped: list[str] = []
        m = kgbundle.export(doc, spec, Path(args.out), bid, lineage.pop("version"), texts or None, created=args.created,
                          access=access, keep_less_open=args.keep_less_open, unshipped=unshipped, title=args.title,
                          **lineage)
        kgbundle.seal(Path(args.out))
        if m["export_report"].get("access_warning"):
            print(f"scale: warning: {m['export_report']['access_warning']}", file=sys.stderr)
        if m["export_report"].get("title_shortened"):
            print(f"scale: note: the bundle's title is {m['topic']!r}, the graph's title shortened (a host shows it as "
                  "the graph's name); give --title to name it, or a shorter graph title", file=sys.stderr)
        if unshipped:                    # named here only: bundle.json counts them
            print(f"scale: warning: --text not shipped for {', '.join(unshipped)}: the bundle does not "
                  "hold that source (withheld as less open than the bundle, filtered out, or not in the graph)", file=sys.stderr)
        print(json.dumps({"bundle": args.out, "counts": m["counts"], "export_report": m["export_report"]}, indent=1))
        return 0
    args.format = "json"
    doc = _viewer_doc(args)
    _emit(pgraph.to_neo4j_jsonl(doc), args)


def _bundle_lineage(args) -> dict:
    """The release lineage of a kg-bundle export from its options: the previous release (ids frozen, recorded as the
    predecessor) or an earlier build whose ids to keep, the merge map of retired records and the corpus block."""
    from . import corpus as corpus_mod
    if args.previous and args.ids_from:
        raise ScaleError("give --previous (the previous release, recorded) or --ids-from (an earlier build whose ids to keep, "
                         "not recorded), not both")
    out: dict = {"version": args.version or "1.0.0"}
    for opt, key in ((args.previous, "previous"), (args.ids_from, "ids_from")):
        if opt:
            d = Path(opt)
            if not (d / "bundle.json").is_file():
                raise ScaleError(f"{d}: not a kg-bundle folder (no bundle.json)")
            out[key] = d
    if args.previous and not args.version:
        prev = json.loads((Path(args.previous) / "bundle.json").read_text()).get("version")
        raise ScaleError(f"a release after {prev} needs its own version: give --version (later than {prev})")
    if args.replaced:
        if not (args.previous or args.ids_from):
            raise ScaleError("--replaced lists retired records by their released ids: give --previous or --ids-from too")
        rmap = load_doc(args.replaced)
        if not isinstance(rmap, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in rmap.items()):
            raise ScaleError(f"{args.replaced}: a map of retired scale-catal id to the id of the record it was merged into")
        out["replaced"] = rmap
    if args.corpus:
        res = corpus_mod.check(corpus_mod.load(args.corpus))
        if not res["ok"]:
            raise ScaleError(f"{args.corpus}: the corpus manifest does not add up ({'; '.join(res['problems'][:5])}); "
                             "see scale corpus check")
        out["corpus"] = res["corpus"]
    return out


def cmd_corpus_check(args):
    from . import corpus
    res = corpus.check(corpus.load(args.manifest), tuple(args.included or corpus.INCLUDED), frozen_at=args.frozen_at,
                       description=args.description)
    args.format = "json"
    _emit(res, args)
    if not res["ok"]:
        raise SystemExit(1)


def cmd_pages_render(args):
    from . import pagereading
    only = [int(x) for x in args.only.split(",")] if args.only else None
    _emit(pagereading.render(args.pdf, args.source, args.pages, args.dpi, only), args)


def cmd_pages_region(args):
    from . import pagereading
    _emit(pagereading.region(args.pages, args.source, args.page, [args.x0, args.y0, args.x1, args.y1], args.dpi,
                             args.transcription), args)


def cmd_pages_agree(args):
    from . import pagereading
    from .util import write_canonical
    doc = pagereading.load(args.doc)
    res = pagereading.agree(doc, args.pages)
    write_canonical(args.doc, doc)
    _emit({"document": args.doc, **res}, args)


def cmd_pages_check(args):
    from . import pagereading
    second = load_doc(args.second) if args.second else None
    warnings: list[str] = []
    errors = pagereading.check(pagereading.load(args.doc), args.pages, second, warnings)
    _emit({"document": args.doc, "ok": not errors, "errors": errors, "warnings": warnings}, args)
    if errors:
        raise SystemExit(1)


def cmd_pages_pending(args):
    from . import pagereading
    items = pagereading.pending(pagereading.load(args.doc), args.pages, crops=not args.no_crops)
    _emit({"document": args.doc, "pending": len(items), "regions": items}, args)


def cmd_pages_merge_second(args):
    from . import pagereading
    from .util import write_canonical
    doc = pagereading.load(args.doc)
    n = pagereading.merge_second(doc, load_doc(args.second))
    write_canonical(args.doc, doc)
    _emit({"document": args.doc, "second_readings": n}, args)


def cmd_pages_import(args):
    from . import pagereading
    _emit(pagereading.import_words(args.cache, args.pages, args.overwrite, args.written_here), args)


def _graph_spec(args, doc):
    from . import pgraph
    return pgraph.load_spec(pgraph.spec_for(_repo(args), doc["graph"].get("schema_version"), args.spec, doc))


def cmd_graph_describe(args):
    from . import pgraph
    hint = {"graph": {"follows_domains": [args.profile]}} if args.profile else None   # picks the domain that has it
    spec = pgraph.load_spec(pgraph.spec_path(_repo(args), args.spec, hint))
    _emit(pgraph.describe(spec, args.names or None, args.profile), args)


def cmd_graph_verify(args):
    """The catalysis scale-catal manifest (domain/graph/scale-catal.yaml) and each of its frozen versions
    assemble, every frozen directory (the core's kernels, the catalysis versions) matches its SHA256SUMS,
    and every version's spec document keeps the digest the releases published for it (``spec_digests``)."""
    from . import pgraph
    from .schema_change import verify_frozen
    from .releases import spec_digest_stability
    repo = _repo(args)
    res = {"heads": [], "frozen": [], "sums": verify_frozen(repo)}
    digests: dict[tuple[str, str], str] = {}
    for name, man in layout.graph_manifests(repo, experimental=True).items():
        head = pgraph.load_spec(man)
        digests[(name, head["version"])] = pgraph.spec_sha256(head)
        res["heads"].append({"domain": name, "manifest": man.relative_to(repo).as_posix(), "version": head["version"],
                             "labels": len(head["nodes"]), "edges": len(head["edges"]),
                             "extension_prefixes": sorted(head.get("extension_prefixes") or {}),
                             "spec_sha256": digests[(name, head["version"])]})
        for m in sorted(layout.frozen_graph_dir(man).glob("scale-catal-*.yaml")):
            spec = pgraph.load_spec(m)
            want = m.stem.removeprefix("scale-catal-")
            digests[(name, spec["version"])] = pgraph.spec_sha256(spec)
            res["frozen"].append({"domain": name, "manifest": m.relative_to(repo).as_posix(), "version": spec["version"],
                                  "spec_sha256": digests[(name, spec["version"])], "ok": spec["version"] == want})
    res["spec_digests"] = spec_digest_stability(repo, digests)
    res["ok"] = res["sums"]["ok"] and bool(res["heads"]) and all(f["ok"] for f in res["frozen"]) and res["spec_digests"]["ok"]
    _emit(res, args)
    return 0 if res["ok"] else 1


def cmd_graph_spec(args):
    """Write the spec document of one version (or, with --all, of every version of the catalysis schema) as canonical JSON,
    with its sha256: the digest a reader binds a schema by, the same for a version as the head or frozen. With --expect,
    check that the version (the head unless --version) is the schema of that digest here (pgraph.identify): a version
    pinned with its digest is this repository's, or the command says it is not and exits 1."""
    from . import pgraph
    repo = _repo(args)
    if args.all and args.version:
        raise ScaleError("give --version or --all, not both")
    if args.expect:
        if args.all:
            raise ScaleError("--expect checks one version: give --version (default: the head), not --all")
        man = Path(pgraph.spec_path(repo, args.spec))
        res = pgraph.identify(man, args.version or str(load_yaml(man).get("version")), args.expect)
        print(to_json(res))
        return 0 if res["matches"] else 1
    every = layout.graph_manifests(repo, experimental=True)
    if args.domain:
        if args.domain not in every:
            raise ScaleError(f"no scale-catal schema for {args.domain!r}; use {', '.join(sorted(every))}")
        mans = {args.domain: every[args.domain]}
    elif args.spec or not args.all:
        man = Path(pgraph.spec_path(repo, args.spec))
        # a frozen version, a release's or a candidate's manifest is named by the domain it belongs to (catalysis)
        mans = {next((n for n, m in every.items() if m.resolve() == man.resolve()), layout.manifest_layer(man)): man}
    else:
        mans = every
    out = Path(args.out) if args.out else None
    rows = []
    for name, man in mans.items():
        held = dict(pgraph.spec_versions(man))
        if args.version and args.version not in held:
            raise ScaleError(f"{name} has no scale-catal {args.version} (versions: {', '.join(held)})")
        wanted = list(held) if args.all else [args.version or str(load_yaml(man).get("version"))]
        for v in wanted:
            spec = pgraph.load_spec(held[v])
            data = pgraph.spec_bytes(spec)
            row = {"domain": name, "version": v, "manifest": _rel(repo, held[v]), "sha256": hashlib.sha256(data).hexdigest(),
                   "bytes": len(data)}
            if out:
                dest = out / name / f"scale-catal-{v}.json" if args.all else out
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                row["written"] = str(dest)
            rows.append(row)
    if out and args.all:                       # the digests beside the files, as in a frozen directory
        (out / "SHA256SUMS").write_text("".join(f"{r['sha256']}  {r['domain']}/scale-catal-{r['version']}.json\n"
                                                for r in rows))
    print(to_json(rows if args.all else rows[0]))


def _positive(text: str) -> int:
    """A whole number of at least 1 (a count of hits)."""
    try:
        n = int(text)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"a whole number of at least 1 (got {text!r})")
    return n


def _rel(repo: Path, p: Path) -> str:
    try:
        return Path(p).resolve().relative_to(Path(repo).resolve()).as_posix()
    except ValueError:
        return str(p)


def _index_stem(graph: str, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    g = Path(graph)
    return g.with_name(g.name.removesuffix(".json").removesuffix(".graph") + ".evidence")


def cmd_graph_index(args):
    from .passages import Index, evidence_items, graph_sha256
    doc = load_doc(args.file)
    ix = Index.build(evidence_items(doc), args.embedder, graph_sha256(doc))     # bound to this document
    stem = _index_stem(args.file, args.index)
    ix.save(stem)
    _emit({"index": f"{stem}.jsonl", "vectors": f"{stem}.i8", "terms": f"{stem}.terms", "items": len(ix.items), "embedder": ix.embedder_id,
           "dim": int(ix.vectors.shape[1]) if len(ix.items) else 0, "graph_sha256": ix.graph_sha256}, args)


def cmd_graph_search(args):
    from . import pgraph
    from .passages import index_for
    from .pgraph_query import document_access
    doc = load_doc(args.file)
    ix = index_for(_index_stem(args.file, args.index), doc)     # only an index of this document, else built from it
    nodes = {n["id"]: n for n in doc["nodes"]}
    links = {e["id"]: e for e in doc["links"]}
    years = {n["id"]: n["props"].get("year") for n in doc["nodes"] if n["label"] == "Source"}
    before = int(args.published_before[:4]) if args.published_before else None
    where = (lambda it: years.get(it.get("source")) is not None and years[it["source"]] < before) if before else None
    hits = ix.search(args.query, k=args.k, mode=args.mode, where=where)
    for h in hits:
        rec = nodes.get(h["record"]) or links.get(h["record"])
        h["record_name"] = (rec or {}).get("props", {}).get("name") or (rec or {}).get("type")
        h["source_year"] = years.get(h.get("source"))
    # the hits are the document's verbatim quotes: they go only where the whole document may go, as a query's answer
    access = document_access(doc, pgraph.embargo_today())       # the day every path reads embargoes on
    res = {"query": args.query, "mode": args.mode, "embedder": ix.embedder_id, "hits": hits, "access": access}
    md = "\n".join([f"# {args.query}", "", f"access: **{access['level']}**"
                     + (f" · {access['note']}" if access["level"] != "public" else ""), ""]
                    + [f"{i}. [{h['score']}] {h['label']} {h['record_name']} — {h['source_year']}, "
                       f"{h['locator']}: “{h['text']}”" for i, h in enumerate(hits, 1)]) + "\n"
    _emit(res, args, md)


def cmd_graph_query(args):
    from . import pgraph_query
    from .passages import index_for
    doc = load_doc(args.file)
    spec = _graph_spec(args, doc)
    plan = load_doc(args.plan)
    ix = None
    if plan.get("text"):
        ix = index_for(_index_stem(args.file, args.index), doc)    # only an index of this document, else built from it
    res = pgraph_query.run(doc, spec, plan, ix)
    _emit(res, args, pgraph_query.render_markdown(res))
    return 0 if res["status"] in ("answered", "no_matching_record", "missing_context", "schema_gap") else 1


def cmd_gap_issue(args):
    from .gaps import not_public, render_issue, submit_issue
    gap = load_doc(args.gap)
    closed = not_public(gap)
    if closed:                       # loud, before anything is printed or sent
        print(f"scale: warning: {gap.get('id')} is not for a public tracker ({closed})", file=sys.stderr)
    if args.submit:
        _emit(submit_issue(gap, repo=args.github_repo, dry_run=False), args)
    else:
        print(render_issue(gap))
        print(to_json(submit_issue(gap, repo=args.github_repo, dry_run=True)), file=sys.stderr)


def cmd_gap_list(args):
    rows = []
    for p in list_docs(args.directory, "GAP-*"):
        g = load_doc(p)
        if isinstance(g, dict) and g.get("kind"):
            rows.append({"id": g["id"], "kind": g["kind"], "about": g["about"], "records": g["records"], "action": g["recommended_action"],
                         **({"access": (g["access"] or {}).get("level")} if "access" in g else {})})
    _emit(rows, args)


def cmd_gap_from_query(args):
    from .gaps import UNSTATED_ACCESS, gaps_from_query, write_gaps
    res = json.loads(Path(args.result).read_text(encoding="utf-8"))
    gaps = gaps_from_query(res)
    written = write_gaps(gaps, Path(args.out_dir))
    print(to_json({"gaps": [{"id": g["id"], "kind": g["kind"], "about": g["about"]} for g in gaps], "written": [str(p) for p in written],
                   "access": res["access"] if isinstance(res.get("access"), dict) else UNSTATED_ACCESS}))


def cmd_release_list(args):
    """The releases, oldest first (none until the first is built)."""
    from .releases import list_releases, release_root
    repo = _repo(args)
    out = []
    for r in list_releases(repo):
        m = load_yaml(release_root(repo, r) / "RELEASE.yaml")
        out.append({"release": r, "date": m.get("date"),
                    "schema_version": ((m.get("component_versions") or {}).get("schema") or {}).get("version"),
                    "previous": m.get("previous")})
    _emit(out, args)


def cmd_release_build(args):
    from .releases import build_release
    dest = build_release(_repo(args), args.version, Path(args.out_root) if args.out_root else None,
                         date=args.date, override_version=args.override_version)
    print(f"built {dest}")


def cmd_release_verify(args):
    """Every release (from list_releases), or one id or directory. No release built yet is in order: nothing to
    verify."""
    from .releases import list_releases, release_root, verify_release
    repo = _repo(args)
    if args.target and Path(args.target).is_dir():
        targets = [(Path(args.target), None)]
    else:
        ids = [args.target] if args.target else list_releases(repo)
        targets = [(release_root(repo, r), normalize_release_id(r)) for r in ids]
    res = [verify_release(t, rid) for t, rid in targets]
    _emit(res, args)
    return 0 if all(r["ok"] for r in res) else 1


def cmd_schema_diff(args):
    from .schema_change import check, summary
    res = check(_repo(args), args.base)
    print(to_json(res) if args.json else summary(res))
    return 0


def cmd_schema_bump(args):
    from .schema_change import bump
    _emit(bump(_repo(args), args.base, args.note), args)


def cmd_schema_check(args):
    from .schema_change import check, summary
    res = check(_repo(args), args.base)
    text = summary(res)
    if args.comment:
        Path(args.comment).write_text(text, encoding="utf-8")
    print(to_json(res) if args.json else text)
    return 0 if res["ok"] else 1


def cmd_review_sample(args):
    from .policy import load_policy, sample_records
    pol = load_policy(_repo(args))
    frac = args.fraction if args.fraction is not None else \
        ((pol.get("records") or {}).get("agent_extracted_records") or {}).get("sample_fraction", 0.1)
    doc = load_doc(args.graph)
    flagged = []
    if args.include_flagged:
        from . import pgraph
        rep = pgraph.validate(doc, _graph_spec(args, doc))
        ids = {n["id"] for n in doc.get("nodes", [])}
        nonconf = [v["record"] for c in ((rep.conformance or {}).get("profiles") or {}).values() for v in c["violations"]]
        flagged = sorted({w["record"] for w in rep.warnings} | set(nonconf) & ids)
    _emit({"fraction": frac, "seed": args.seed, "sample": sample_records(doc, 1.0 if args.full else frac, args.seed, flagged)}, args)


def cmd_check(args):
    from .devcheck import run_checks
    return 0 if run_checks(_repo(args), fast=args.fast) else 1


def cmd_mcp(args):
    from .mcp_server import main as serve
    serve(workspace=args.workspace)


def cmd_call(args):
    """The universal entry point: ``scale call <tool> '<json>'`` — JSON in, JSON out."""
    from .api import ScaleToolkit
    if not args.tool:
        print(to_json({"usage": "scale call <tool> '<json arguments>'   (use - to read arguments from stdin)",
                       "tools": ScaleToolkit.schemas()}))
        return 0
    raw = sys.stdin.read() if args.arguments == "-" else (args.arguments or "{}")
    try:
        arguments = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(to_json({"error": f"arguments are not valid JSON: {exc}"}))
        return 1
    if not isinstance(arguments, dict):
        print(to_json({"error": "arguments must be a JSON object"}))
        return 1
    tk = ScaleToolkit(workspace=args.workspace, repo=getattr(args, "repo", None))
    result = tk.call(args.tool, arguments)
    print(json.dumps(result, ensure_ascii=False, indent=None if args.compact else 2, default=str))
    return 1 if isinstance(result, dict) and "error" in result else 0


def cmd_serve(args):
    from .http_server import serve
    serve(args.host, args.port, workspace=args.workspace)


def cmd_tools(args):
    from .api import ScaleToolkit
    if args.format == "openapi":
        data = ScaleToolkit.openapi()
    elif args.format == "mcp":
        data = [{"name": t["name"], "description": t["description"], "inputSchema": t["parameters"]} for t in ScaleToolkit.schemas()]
    else:
        data = ScaleToolkit.schemas()
    args.format = "json"
    _emit(data, args)


def cmd_skills_install(args):
    import shutil
    from .releases import list_releases, release_root, skill_files, skill_folder
    repo = _repo(args)
    main = list_releases(repo)
    rid = normalize_release_id(args.release) if args.release else (main[-1] if main else None)
    # no release built yet: the skills of the head (the repository or the installed package)
    rel = release_root(repo, rid) if rid else repo
    rid = rid or "head (no release built yet)"
    target = Path(args.target).expanduser()
    installed, files = [], {}
    for skill in skill_files(rel):
        dest = target / f"scale-{skill.parent.name}"
        if dest.exists() and not args.force:
            raise ScaleError(f"{dest} exists; use --force to overwrite")
        for f in skill_folder(skill):          # the whole folder: SKILL.md and the references it points to
            out = dest / f.relative_to(skill.parent)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, out)
            files.setdefault(dest.name, []).append(out.relative_to(dest).as_posix())
        installed.append(str(dest / "SKILL.md"))
    print(to_json({"release": rid, "installed": installed, "files": files}))


def _project(args) -> dict:
    repo = _repo(args)
    for base in (Path.cwd(), repo):
        p = base / ".github" / "scale-project.yml"
        if p.exists():
            return load_yaml(p) or {}
    return {}


def _slug(args) -> str:
    slug = getattr(args, "github_repo", None) or _project(args).get("github_repo")
    if not slug:
        raise ScaleError("no GitHub repository: pass --github-repo owner/name or set github_repo in .github/scale-project.yml")
    return slug


def cmd_triage_ingest(args):
    from . import intake
    slug, out = _slug(args), Path(args.out)
    since = args.since
    if since == "auto":
        st = None if args.from_file else intake.last_state(slug)
        since = st["since"] if st else None
    raw = json.loads(Path(args.from_file).read_text(encoding="utf-8")) if args.from_file else \
        intake.fetch_github(slug, since, discussions=_project(args).get("triage", {}).get("include_discussions", True))
    queue = intake.ingest(raw, intake.Vocabulary.from_repo(_repo(args)))
    queue.update({"github_repo": slug, "since": since})
    write_json(out / "raw.json", raw)
    write_json(out / "queue.json", queue)
    print(to_json({"queue": str(out / "queue.json"), "items": len(queue["items"]), "topics": len(queue["clusters"]),
                   "by_category": {k: v for k, v in queue["summary"].items() if v}}))


def cmd_triage_propose(args):
    from . import intake
    qdir = Path(args.dir)
    queue = load_doc(qdir / "queue.json")
    if args.agent_command:
        import shlex
        import subprocess as sp_
        target = qdir / "agent-proposals.json"
        proc = sp_.run([*shlex.split(args.agent_command), str(qdir / "queue.json"), str(target)], capture_output=True, text=True)
        if proc.returncode != 0 or not target.exists():
            print(to_json({"warning": "agent command failed; using rule-based proposals", "stderr": proc.stderr[-500:]}), file=sys.stderr)
        else:
            args.proposals = str(target)
    external = load_doc(args.proposals) if args.proposals else None
    if isinstance(external, dict):
        external = external.get("proposals", [])
    proposals, rejected = intake.merge_proposals(queue, external)
    write_json(qdir / "proposals.json", {"proposals": proposals, "rejected": rejected})
    digest = intake.render_digest(queue, proposals, queue.get("github_repo", ""), queue.get("since"), rejected)
    (qdir / "digest.md").write_text(digest, encoding="utf-8")
    print(to_json({"digest": str(qdir / "digest.md"), "proposals": len(proposals), "rejected": rejected,
                   "decisions_needed": sum(1 for p in proposals if p.get("decision_needed"))}))
    return 1 if rejected and args.strict else 0


def cmd_triage_publish(args):
    from . import intake
    qdir = Path(args.dir)
    queue = load_doc(qdir / "queue.json")
    if not queue["items"]:
        print(to_json({"published": False, "reason": "no new feedback"}))
        return 0
    print(to_json(intake.publish_digest(queue.get("github_repo") or _slug(args), (qdir / "digest.md").read_text(encoding="utf-8"),
                                        queue, dry_run=not args.publish)))


def cmd_catalogue(args):
    from .intake import catalogue_markdown
    md = catalogue_markdown(load_doc(args.graph), _slug(args))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(md, encoding="utf-8")
    print(f"wrote {args.out}")


def cmd_thread(args):
    """An issue or pull request with everything said on it, line comments of reviews included (read-only)."""
    from .thread import fetch, markdown
    t = fetch(args.number, _slug(args))
    _emit(t, args, markdown(t))


def cmd_suggest(args):
    from .intake import suggest_url
    print(suggest_url(_slug(args), args.record, args.text or "", args.title))


FMT_TARGETS = ["core", "domain", "governance", "tools/tests/fixtures", "docs/decisions"]


def _verbatim(p: Path, root: Path) -> bool:
    """Files under a directory holding a `.scale-verbatim` marker are adopted as-is (never reformatted).
    The search stops at the root, so a marker outside the repository never hides it."""
    for d in p.parents:
        if (d / ".scale-verbatim").exists():
            return True
        if d == root:
            return False
    return False


def _json_docs(root: Path, targets: list[str]) -> list[Path]:
    """JSON documents under the targets, minus what ``layout.is_excluded`` names and adopted verbatim
    files. A missing target is an error.

    Exclusions are tested on the path relative to every repository that holds the file (and to
    ``root`` when it does), not relative to the working directory: ``scale fmt v0.1.0`` run inside
    ``releases/`` must still leave the release alone. Outside any repository only the file
    name is tested."""
    root = root.resolve()
    out = []
    for t in targets:
        p = (root / t if not Path(t).is_absolute() else Path(t)).resolve()
        if not p.exists():
            raise ScaleError(f"fmt target {t} does not exist under {root}")
        out += [p] if p.is_file() else sorted(p.rglob("*.json"))

    roots: dict[Path, list[Path]] = {}

    def enclosing(d: Path) -> list[Path]:
        """``root`` (if it holds d) and every repository root at or above d, outermost last."""
        if d not in roots:
            roots[d] = ([root] if d.is_relative_to(root) else []) + [a for a in [d, *d.parents] if layout.is_root(a)]
        return roots[d]

    def keep(p: Path) -> bool:
        rs = enclosing(p.parent)
        if not rs:
            return not layout.is_excluded(Path(p.name)) and not _verbatim(p, root)
        return not any(layout.is_excluded(p.relative_to(r)) for r in rs) and not _verbatim(p, max(rs, key=lambda r: len(p.relative_to(r).parts)))
    return [p for p in out if keep(p)]


def cmd_fmt(args):
    from .style import fmt_file
    root = _repo(args) if not args.paths else Path.cwd()
    msgs = [m for p in _json_docs(root, args.paths or FMT_TARGETS) if (m := fmt_file(p, check=args.check))]
    print("\n".join(msgs) if msgs else "all JSON documents canonical")
    return 1 if (msgs and args.check) else 0


def cmd_lint(args):
    from . import pgraph
    from .style import fmt_file, lint_yaml_file, machine_yaml_docs, naming_problems, yaml_files
    root = _repo(args)
    problems = [p for f in yaml_files(root) for p in lint_yaml_file(f)]
    for name, man in layout.graph_manifests(root, experimental=True).items():
        problems += [f"naming: {name}: {p}" for p in naming_problems(pgraph.load_spec(man))]
    problems += [f"{p}: machine-written document stored as YAML; convert to canonical JSON" for p in machine_yaml_docs(root)]
    problems += [m for p in _json_docs(root, FMT_TARGETS) if (m := fmt_file(p, check=True))]
    print("\n".join(problems) if problems else "lint clean: YAML block style, naming rules, canonical JSON")
    return 1 if problems else 0


def cmd_links(args):
    from .style import broken_links
    problems = broken_links(_repo(args))
    print("\n".join(problems) if problems else "every relative Markdown link resolves")
    return 1 if problems else 0


def inventory_markdown(inv: dict) -> str:
    """Render docs/implementation-status.md from the machine-readable inventory."""
    L = ["# Implementation-status inventory", "",
         "This page distinguishes **functioning** capabilities (executable and covered by the cited tests), **mocked** ones "
         "(the interface and checks run, but a component is simulated or supplied by hand) and **planned** ones (described in "
         "the manuscript or docs, not implemented).",
         "It is generated from [`implementation-status.yaml`](implementation-status.yaml) by `scale status --format markdown`; "
         "`test_inventory_references_real_tests` checks that every functioning entry cites tests that exist.", "",
         f"Release **{inv['release']}** · tool **{inv['tool_version']}** · environment used for the included tests: Python 3.13 "
         "and 3.10 on macOS; CI on Python 3.10–3.13 (Ubuntu).", ""]
    for status in ("functioning", "mocked", "planned"):
        L += [f"## {status.capitalize()}", "", "| capability | where | tests / notes |", "|---|---|---|"]
        for c in inv["capabilities"]:
            if c["status"] != status:
                continue
            cell = ", ".join(f"`{t}`" for t in c.get("tests") or [])
            if c.get("notes"):
                cell = f"{cell}<br>{c['notes']}" if cell else c["notes"]
            L.append(f"| {c['name']} | {'`' + c['where'] + '`' if c.get('where') else ''} | {cell} |")
        L.append("")
    return "\n".join(L)


def cmd_status(args):
    repo = _repo(args)
    inv = load_yaml(repo / layout.IMPLEMENTATION_STATUS)
    if args.format == "json":
        _emit(inv, args)
        return
    if args.format == "markdown":
        text = inventory_markdown(inv)
        if args.out:                     # written as generated, so the page test compares byte for byte
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"wrote {args.out}")
        else:
            print(text, end="")
        return
    for sec in inv["capabilities"]:
        print(f"[{sec['status']:>10}] {sec['name']}")


def cmd_domains_list(args):
    from .domains import list_domains
    rows = list_domains(_repo(args))
    if args.format == "json":
        _emit(rows, args)
        return
    for r in rows:
        print(f"{r['domain']:<20} {r['status'] or '?':<13} {r['version'] or '?':<8} {r['team'] or '?':<44} "
              f"stewards: {', '.join(r['stewards']) or 'none'}{'; founding: true' if r['founding'] else ''}")


def cmd_domains_check(args):
    from .domains import check
    res = check(_repo(args), args.names or None, examples=not args.no_examples)
    if args.json:
        print(to_json(res))
    else:
        doms = ", ".join(f"{d['domain']} {d['version']} ({d['status']})" for d in res["domains"])
        print(f"core {res['core']['name']} {res['core']['version']}; domains: {doms or 'none'}")
        for e in res["errors"]:
            print(f"error   {e['where']}: {e['message']}")
        for w in res["warnings"]:
            print(f"warning {w['where']}: {w['message']}")
        print("domain and core manifests are complete, compatible and redeclare no identifier" if res["ok"]
              else f"{len(res['errors'])} error(s)")
    return 0 if res["ok"] else 1


def cmd_domains_cq(args):
    from .competency import run, text
    res = run(_repo(args), args.names or None)
    print(to_json(res) if args.json else text(res))
    return 0 if res["ok"] else 1


def cmd_ci_spec_changes(args):
    from .ci import spec_changes, spec_changes_text
    res = spec_changes(_repo(args), args.base, args.head)
    print(to_json(res) if args.json else spec_changes_text(res))
    return 0 if res["ok"] else 1


def cmd_kg_update(args):
    from .kg import update, update_text
    res = update(_repo(args), Path(args.data), args.domain, args.to, dry_run=args.dry_run, reindex=not args.no_index)
    if args.out:
        Path(args.out).write_text(to_json(res) + "\n", encoding="utf-8")
    print(update_text(res))
    return 0 if res["ok"] else 1


def _rights(args, doc_path):
    from . import rights
    rf = Path(args.rights) if args.rights else rights.rights_file(doc_path)
    if rf is None:
        raise ScaleError(f"no {rights.RIGHTS_FILE} for {doc_path}: pass --rights")
    return rights.load_rights(rf)


def cmd_evidence_cap(args):
    from . import rights
    from .util import write_canonical
    doc = load_doc(args.file)
    capped, rep = rights.cap(doc, _rights(args, args.file), rights.read_texts(args.texts, None, doc))
    if args.output:
        write_canonical(Path(args.output), capped)
        rep["written"] = args.output
    print(to_json(rep))
    return 0


def cmd_evidence_rehydrate(args):
    from . import rights
    from .util import write_canonical
    doc = load_doc(args.file)
    texts = rights.read_texts(args.texts, args.source_text, doc)
    if not texts:
        raise ScaleError("no source text: give --texts DIR (<source id's last segment>.txt) or --source-text ID=FILE")
    full, rep = rights.rehydrate(doc, texts)
    if args.output:
        write_canonical(Path(args.output), full)
        rep["written"] = args.output
    print(to_json(rep))
    return 0 if rep["ok"] else 1


def cmd_evidence_report(args):
    from . import rights
    if args.all:
        res = rights.copyright_check(_repo(args))
        print(to_json(res))
        return 0 if res["ok"] else 1
    if not args.file:
        raise ScaleError("give a document (with --rights, or a rights.yaml in its folder or above) or --all")
    res = rights.report(load_doc(args.file), _rights(args, args.file))
    print(to_json(res))
    return 0 if res["ok"] and not res["unlisted"] else 1


def cmd_evidence_gap_report(args):
    """Check a gap report (JSON) against the copyright cap and its sources' rights; write it as Markdown only when
    it passes (the find-gaps workflow of the data repository posts that Markdown as an issue)."""
    from . import rights
    if args.rights:
        rf = Path(args.rights)
    elif args.corpus:
        c = Path(args.corpus)
        rf = rights.rights_file(c / "_" if c.is_dir() else c, Path.cwd())
    else:
        raise ScaleError("give --rights R or --corpus PATH (its nearest rights.yaml in its folder or above)")
    if rf is None:
        raise ScaleError(f"no {rights.RIGHTS_FILE} for {args.corpus}: every quoted source needs a rights entry; pass --rights")
    res = rights.gap_report(load_doc(args.file), rights.load_rights(rf))
    md = res.pop("markdown")
    res["rights"] = str(rf)
    if md is not None and args.output:
        Path(args.output).write_text(md)
        res["written"] = args.output
    print(to_json(res))
    return 0 if res["ok"] else 1


def cmd_evidence_access(args):
    from . import rights
    repo = _repo(args)
    docs = [Path(f).resolve() for f in args.files] if args.files else rights.committed_documents(repo)
    problems = rights.access_problems(repo, docs)
    print(to_json({"documents": len(docs), "problems": problems, "ok": not problems}))
    return 0 if not problems else 1


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scale", description="SCALE — Shared Concepts, Attributes, and Links with Evidence")
    p.add_argument("--version", action="version", version=f"scale {__version__}")
    p.add_argument("--repo", help="path to a SCALE repository checkout (default: discover)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_, parent=sub):
        sp = parent.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        return sp

    WS_HELP = "the agent tools' working directory (default: $SCALE_WORKSPACE, else ~/.scale/workspace)"

    def out_opts(sp, fmt=("json",)):
        sp.add_argument("--out", help="write output to a file")
        sp.add_argument("--format", choices=list(fmt), default=fmt[0])

    gr = sub.add_parser("graph", help="scale-catal property graphs in node-link JSON").add_subparsers(dest="sub", required=True)
    sp = add("validate", cmd_graph_validate, "validate node-link documents against the scale-catal schema", gr)
    sp.add_argument("files", nargs="+"); sp.add_argument("--spec", help="a schema manifest, e.g. domain/graph/scale-catal.yaml (default: the catalysis manifest)")
    sp.add_argument("--source-text", action="append", help="<source-id>=<file> for verbatim quote checks")
    sp.add_argument("-v", "--verbose", action="store_true"); out_opts(sp, ("text", "json"))
    sp = add("stats", cmd_graph_stats, "count labels, edge types, properties and units in use, and link patterns", gr)
    sp.add_argument("file"); out_opts(sp)
    def viewer_opts(sp):
        sp.add_argument("--as", dest="viewer", action="append", metavar="ID",
                        help="viewer: an institution, person or project id (repeatable)")
        sp.add_argument("--public", action="store_true", help="filter for the public (no memberships)")
        sp.add_argument("--date", help="date for embargo checks, YYYY-MM-DD (default: today, the earlier of the "
                        "local and the UTC date; never later than today)")
    sp = add("filter", cmd_graph_filter, "keep only what a viewer may see under each record's stewardship", gr)
    sp.add_argument("file"); sp.add_argument("--out"); viewer_opts(sp)
    sp = add("migrate", cmd_graph_migrate, "move a scale-catal document along the schema's version steps to the current version (ids kept)", gr)
    sp.add_argument("file"); sp.add_argument("dest", help="where to write the migrated document"); sp.add_argument("--spec")
    out_opts(sp)
    sp = add("export", cmd_graph_export, "export: Neo4j/APOC JSON lines, or a knowledge-graph bundle (--to kg-bundle)", gr)
    sp.add_argument("file"); sp.add_argument("--out"); viewer_opts(sp)
    sp.add_argument("--to", choices=["neo4j", "kg-bundle"], default="neo4j"); sp.add_argument("--spec")
    sp.add_argument("--bundle-id"); sp.add_argument("--version", help="the bundle's version (default 1.0.0; with --previous, "
                                                                      "required and later than the previous release's)")
    sp.add_argument("--created", help="ISO timestamp (default: now, in UTC); embargoes are read on its day or today (the "
                    "earlier of the local and the UTC date), whichever is earlier")
    sp.add_argument("--text", action="append", help="<publication source_id>=<file>:<licence> to ship a redistributable text (the licence is required)")
    sp.add_argument("--keep-less-open", action="store_true", help="kg-bundle: export records less open than the bundle's "
                    "access (the graph's stewardship; public with --public; the viewer's, one project or institutions, with "
                    "--as), marked with scale_access and their project or institutions, instead of withholding them")
    sp.add_argument("--previous", metavar="DIR", help="kg-bundle: the previous release's bundle folder: its ids are kept, it is "
                    "recorded as the predecessor (bundle.json previous and changes) and its changelog is carried forward")
    sp.add_argument("--ids-from", metavar="DIR", help="kg-bundle: an earlier build whose ids to keep, without recording it as "
                    "the previous release")
    sp.add_argument("--replaced", metavar="FILE", help="kg-bundle: JSON or YAML map of a retired scale-catal id to the id of the "
                    "record it was merged into; the survivor lists the retired record's released id in replaced_ids")
    sp.add_argument("--corpus", metavar="MANIFEST", help="kg-bundle: the frozen corpus manifest; checked as scale corpus check "
                    "does, it fills bundle.json's corpus block")
    sp.add_argument("--title", help="kg-bundle: the bundle's title, which a host shows as the graph's name (default: the "
                    "graph's title when it has at most 40 characters, else its leading words)")
    sp = add("describe", cmd_graph_describe, "labels and edge types with their properties (what a curator may use)", gr)
    sp.add_argument("names", nargs="*", help="labels or edge types (default: all)"); sp.add_argument("--domain", dest="profile", help="whose checklist to show (catalysis): its items and `when` cases next to each label")
    sp.add_argument("--spec"); out_opts(sp)
    sp = add("verify", cmd_graph_verify, "the catalysis schema manifest and its frozen versions load; every frozen directory matches its "
             "SHA256SUMS; every version's spec document keeps the digest the releases published", gr)
    out_opts(sp)
    sp = add("spec", cmd_graph_spec, "write a version's spec document (the assembled schema as canonical JSON) and print its sha256, "
             "the digest a reader binds the schema by", gr)
    sp.add_argument("--spec", help="a schema manifest (default: the catalysis manifest)")
    sp.add_argument("--domain", help="whose schema to write (catalysis)")
    sp.add_argument("--version", help="the version (default: the head); a frozen one is read from graph/frozen/")
    sp.add_argument("--all", action="store_true", help="every version of the catalysis schema (or of --domain): --out is then a "
                                                      "directory, with <domain>/scale-catal-<version>.json and SHA256SUMS")
    sp.add_argument("--out", help="the file to write (a directory with --all); without it only the digest is printed")
    sp.add_argument("--expect", metavar="SHA256", help="check that the version is the schema of this spec digest here "
                    "(exit 1 when it is not, or when the version is not held here)")
    sp = add("index", cmd_graph_index, "build the evidence index: a vector and term statistics per evidence quote", gr)
    sp.add_argument("file"); sp.add_argument("--index", help="index path stem (default: <graph>.evidence)")
    sp.add_argument("--embedder", default="scale-hash-v1"); out_opts(sp)
    sp = add("search", cmd_graph_search, "search evidence by words and meaning; hits lead to the records that cite them", gr)
    sp.add_argument("file"); sp.add_argument("query"); sp.add_argument("--index"); sp.add_argument("-k", type=_positive, default=10)
    sp.add_argument("--mode", choices=["hybrid", "vector", "keyword", "rrf"], default="hybrid")
    sp.add_argument("--published-before", help="only evidence from sources published before this date (YYYY or YYYY-MM-DD)")
    out_opts(sp, ("json", "markdown"))
    sp = add("query", cmd_graph_query, "run a graph query plan (patterns, filters, evidence search, dated paths)", gr)
    sp.add_argument("file"); sp.add_argument("plan"); sp.add_argument("--index"); sp.add_argument("--spec")
    out_opts(sp, ("json", "markdown"))

    gap = sub.add_parser("gap", help="gap reports and GitHub issues").add_subparsers(dest="sub", required=True)
    sp = add("list", cmd_gap_list, "list gap reports in a directory", gap)
    sp.add_argument("directory"); out_opts(sp)
    sp = add("issue", cmd_gap_issue, "render (or --submit) a GitHub issue for a gap", gap)
    sp.add_argument("gap"); sp.add_argument("--submit", action="store_true"); sp.add_argument("--github-repo"); sp.add_argument("--out"); sp.add_argument("--format", default="json")
    sp = add("from-query", cmd_gap_from_query, "turn the absences of a `scale graph query` result into gap reports", gap)
    sp.add_argument("result"); sp.add_argument("--out-dir", required=True)

    ev = sub.add_parser("evidence", help="quoted evidence and publication rights: the copyright cap, withheld quotes, public access").add_subparsers(dest="sub", required=True)
    RIGHTS_HELP = "the rights file (default: the nearest rights.yaml in the document's folder or above)"
    sp = add("cap", cmd_evidence_cap, "keep each capped source's quoted text within the cap (300 characters a quote; 4,000 "
             "distinct characters and 10%% of the text a source), withholding the rest as sha256 + length in the note", ev)
    sp.add_argument("file"); sp.add_argument("--rights", help=RIGHTS_HELP)
    sp.add_argument("--texts", help="a directory of source texts (<last segment of the source id>.txt), for text_chars")
    sp.add_argument("-o", "--output", help="write the capped document here (default: report only)")
    sp = add("rehydrate", cmd_evidence_rehydrate, "restore withheld quotes from your own copy of the source texts", ev)
    sp.add_argument("file"); sp.add_argument("--texts", help="a directory of source texts (<last segment of the source id>.txt)")
    sp.add_argument("--source-text", action="append", help="<source-id>=<file>")
    sp.add_argument("-o", "--output", help="write the restored document here (default: report only)")
    sp = add("report", cmd_evidence_report, "quoted characters per source against the cap (--all: every committed document that is not a synthetic example)", ev)
    sp.add_argument("file", nargs="?"); sp.add_argument("--rights", help=RIGHTS_HELP)
    sp.add_argument("--all", action="store_true", help="every committed document that is not a synthetic example (research_data, mixed), each with its rights file")
    sp = add("gap-report", cmd_evidence_gap_report, "check a gap report (JSON: corpus, sample, themes with instances: source, "
             "locator, quote) before it leaves a data repository: every source in the rights file, every quote at most 300 "
             "characters, each source within its cap; write it as Markdown only when it passes", ev)
    sp.add_argument("file"); sp.add_argument("--rights", help="the rights file of the corpus's sources")
    sp.add_argument("--corpus", help="the corpus path: its nearest rights.yaml (in it or above, within the working directory)")
    sp.add_argument("-o", "--output", help="write the Markdown here when the report passes")
    sp = add("access", cmd_evidence_access, "every committed scale-catal document (or the given ones) states access public: graph and records (a missing access is not public)", ev)
    sp.add_argument("files", nargs="*")

    cp = sub.add_parser("corpus", help="a frozen corpus manifest").add_subparsers(dest="sub", required=True)
    sp = add("check", cmd_corpus_check, "every candidate source has a status (included, or the reason it was left out) and the "
             "counts add up; prints the bundle corpus block", cp)
    sp.add_argument("manifest", help="the corpus manifest (JSON or YAML: sources with slug and status, optional counts)")
    sp.add_argument("--included", action="append", metavar="STATUS",
                    help="a status that means included (repeatable; default: in_scope, included)")
    sp.add_argument("--frozen-at", help="the date the corpus was frozen (default: the manifest's frozen_at)")
    sp.add_argument("--description", help="the corpus block's description (default: the manifest's corpus and cutoff rule)")
    sp.add_argument("--out", help="write the result here")

    pg = sub.add_parser("pages", help="readings of scanned pages by two readers: page images, positioned OCR words, "
                        "the agreement of each reading with OCR and independent second readings").add_subparsers(dest="sub", required=True)
    PAGES_HELP = "the pages folder (local: page images and OCR words reproduce the source and are never committed)"
    sp = add("render", cmd_pages_render, "page images (PNG) and the positioned words of the text layer and of OCR, per page, "
             "into DIR/<source key>/ (needs pymupdf; OCR needs tesseract)", pg)
    sp.add_argument("pdf"); sp.add_argument("--source", required=True, help="the Source id the PDF is")
    sp.add_argument("--pages", required=True, help=PAGES_HELP)
    sp.add_argument("--dpi", type=int, default=200, help="the page images' resolution (the OCR reads 300 dpi)")
    sp.add_argument("--only", help="comma-separated PDF pages (default: all)"); out_opts(sp)
    sp = add("region", cmd_pages_region, "a 400 dpi crop of a region and what OCR reads there; with --transcription, the "
             "agreement the tool would record", pg)
    sp.add_argument("--pages", required=True, help=PAGES_HELP); sp.add_argument("--source", required=True)
    sp.add_argument("page", type=int)
    for k in ("x0", "y0", "x1", "y1"):
        sp.add_argument(k, type=float, help="page fraction, origin top left")
    sp.add_argument("--dpi", type=int, default=400)
    sp.add_argument("--transcription", help="what you read there, to see whether OCR reads the same numbers"); out_opts(sp)
    sp = add("agree", cmd_pages_agree, "write the tool's agreement onto every evidence item read from a page image, and the "
             "OCR engines used in the document's ocr_engines (never written by hand)", pg)
    sp.add_argument("doc", help="a curated document (scale-catal or a curation fragment)")
    sp.add_argument("--pages", required=True, help=PAGES_HELP); out_opts(sp)
    sp = add("check", cmd_pages_check, "the two-reader rule: each agreement recomputed (a difference from another OCR engine "
             "is a warning), a reading OCR does not confirm has a matching independent second reading, every value of a "
             "record read from an image is in a transcription or quote; exits 1 on an error", pg)
    sp.add_argument("doc"); sp.add_argument("--pages", required=True, help=PAGES_HELP)
    sp.add_argument("--second", help="second readings not yet merged ({record id#i or region id: reading})"); out_opts(sp)
    sp = add("pending", cmd_pages_pending, "the regions a second reader must read: locators and crops with a margin, never "
             "the first transcription", pg)
    sp.add_argument("doc"); sp.add_argument("--pages", required=True, help=PAGES_HELP)
    sp.add_argument("--no-crops", action="store_true", help="list the regions without rendering crops"); out_opts(sp)
    sp = add("merge-second", cmd_pages_merge_second, "copy second readings ({record id#i or region id: reading}) onto the "
             "evidence read from page images", pg)
    sp.add_argument("doc"); sp.add_argument("second"); out_opts(sp)
    sp = add("import", cmd_pages_import, "copy page and region words from another pages folder (an older cache, another "
             "machine's) into DIR; existing files are kept unless --overwrite", pg)
    sp.add_argument("cache"); sp.add_argument("--pages", required=True, help=PAGES_HELP)
    sp.add_argument("--overwrite", action="store_true", help="replace the words already in DIR with the cache's")
    sp.add_argument("--written-here", action="store_true",
                    help="the cache was written on this machine: record this machine's OCR engine with every file"); out_opts(sp)

    rel = sub.add_parser("release", help="releases").add_subparsers(dest="sub", required=True)
    sp = add("list", cmd_release_list, "list the releases", rel)
    out_opts(sp)
    sp = add("build", cmd_release_build, "build an immutable release from the repository head (a human action)", rel)
    sp.add_argument("version")
    sp.add_argument("--out-root"); sp.add_argument("--date")
    sp.add_argument("--override-version", action="store_true",
                    help="build under a version other than scale-release.yaml's `release` (renumbering on purpose)")
    sp = add("verify", cmd_release_verify, "verify the digests of every release, or of one", rel)
    sp.add_argument("target", nargs="?"); out_opts(sp)

    rv = sub.add_parser("review", help="human checks of curated records").add_subparsers(dest="sub", required=True)
    sp = add("sample", cmd_review_sample, "draw a reproducible sample of records for a Tier 1 human check", rv)
    sp.add_argument("graph"); sp.add_argument("--fraction", type=float); sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--full", action="store_true", help="check every record (first batches of a new pipeline)")
    sp.add_argument("--include-flagged", action="store_true", help="add records with warnings or checklist violations")
    sp.add_argument("--spec", help="a schema manifest (default: chosen by the document)"); out_opts(sp)

    sc = sub.add_parser("schema", help="a schema change on a branch: its diff, the version bump, its checks").add_subparsers(
        dest="sub", required=True)
    for name, fn, hlp in (("diff", cmd_schema_diff, "what the branch changes in the schema against the base, its kind "
                           "(breaking or additive) and the version that follows"),
                          ("check", cmd_schema_check, "what a schema change must carry: the version raised by the rule, the "
                           "base frozen, the migration step (and rule, if breaking), tests, a CHANGELOG line (exit 1 if not)"),
                          ("bump", cmd_schema_bump, "freeze the base version, raise the version (breaking: the second number; "
                           "otherwise the third) in every file that states it, and register the migration step")):
        sp = add(name, fn, hlp, sc)
        sp.add_argument("--base", default="origin/main", help="git ref the change merges into (default: origin/main)")
        if name == "bump":
            sp.add_argument("--note", help="the migration step's note (default: the kind of change)"); out_opts(sp)
        else:
            sp.add_argument("--json", action="store_true", help="machine-readable result")
        if name == "check":
            sp.add_argument("--comment", help="also write the reviewer's summary (Markdown) here")

    sp = add("check", cmd_check, "run every check of CI's test jobs (tests, release digests, schemas, domains, "
             "competency questions, style, links, invalid fixtures)")
    sp.add_argument("--fast", action="store_true", help="skip the unit tests")

    sp = add("call", cmd_call, "call an agent tool: scale call <tool> '<json>' (no tool: list tools)")
    sp.add_argument("tool", nargs="?", help="tool name, with or without the scale_ prefix (e.g. status, query)")
    sp.add_argument("arguments", nargs="?", help="JSON object of arguments, or - to read from stdin")
    sp.add_argument("--workspace", help=WS_HELP)
    sp.add_argument("--compact", action="store_true", help="single-line JSON output")

    sp = add("serve", cmd_serve, "serve the agent tools over local HTTP with an OpenAPI description")
    sp.add_argument("--host", default="127.0.0.1"); sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--workspace", help=WS_HELP)

    sp = add("mcp", cmd_mcp, "serve the agent tools and skills over MCP (stdio)")
    sp.add_argument("--workspace", help=WS_HELP)

    sp = add("tools", cmd_tools, "print agent tool definitions (JSON Schema, OpenAPI or MCP form)")
    sp.add_argument("--format", choices=["jsonschema", "openapi", "mcp"], default="jsonschema"); sp.add_argument("--out")

    sk = sub.add_parser("skills", help="agent skills").add_subparsers(dest="sub", required=True)
    sp = add("install", cmd_skills_install, "copy the versioned skills (each SKILL.md with its folder, e.g. references/) into "
             "an agent's skills directory", sk)
    sp.add_argument("target", help="your agent's skills folder")
    sp.add_argument("--release"); sp.add_argument("--force", action="store_true")

    tr = sub.add_parser("triage", help="community feedback → a weekly digest for the reviewers").add_subparsers(dest="sub", required=True)
    sp = add("ingest", cmd_triage_ingest, "fetch and classify feedback into queue.json", tr)
    sp.add_argument("--out", required=True); sp.add_argument("--github-repo")
    sp.add_argument("--since", default="auto", help="ISO time, 'auto' (since last digest) or omit history with a date")
    sp.add_argument("--from-file", help="raw GitHub objects as JSON (offline or exported)")
    sp = add("propose", cmd_triage_propose, "attach proposals (rules and/or an external agent system) and render digest.md", tr)
    sp.add_argument("dir"); sp.add_argument("--proposals", help="proposals.json from any agent system (validated)")
    sp.add_argument("--strict", action="store_true", help="exit 1 if any external proposal is rejected")
    sp.add_argument("--agent-command", help="any program called as: <command> <queue.json> <proposals.json>")
    sp = add("publish", cmd_triage_publish, "open the digest issue and notify threads (dry run unless --publish)", tr)
    sp.add_argument("dir"); sp.add_argument("--github-repo"); sp.add_argument("--publish", action="store_true")

    sp = add("catalogue", cmd_catalogue, "render a readable catalogue of a scale-catal document with a comment link per record")
    sp.add_argument("graph"); sp.add_argument("--out", required=True); sp.add_argument("--github-repo")

    sp = add("thread", cmd_thread, "an issue or pull request with every comment, review and line comment (read-only)")
    sp.add_argument("number", type=int); sp.add_argument("--github-repo"); out_opts(sp, ("markdown", "json"))

    sp = add("suggest", cmd_suggest, "print a pre-filled link for commenting on a record or topic")
    sp.add_argument("--record"); sp.add_argument("--text"); sp.add_argument("--title"); sp.add_argument("--github-repo")

    sp = add("fmt", cmd_fmt, "rewrite JSON documents in canonical form (--check to only report)")
    sp.add_argument("paths", nargs="*"); sp.add_argument("--check", action="store_true")

    sp = add("lint", cmd_lint, "check YAML style, naming rules and canonical JSON (see docs/style.md)")

    sp = add("links", cmd_links, "check that every relative link in the live Markdown documentation resolves")

    # `scale domain …` is the same group (the folder is domain/)
    dm = sub.add_parser("domains", aliases=["domain"], help="the two layers: the science kernel (core/CORE.yaml) and the catalysis "
                        "domain (domain/DOMAIN.yaml, with its schema manifest); also `scale domain`").add_subparsers(
        dest="sub", required=True)
    sp = add("list", cmd_domains_list, "list the declared domain in domain/ (catalysis) with status, the schema version and its maintainers", dm)
    sp.add_argument("--format", choices=["text", "json"], default="text"); sp.add_argument("--out")
    sp = add("check", cmd_domains_check, "check core/CORE.yaml and domain/DOMAIN.yaml: complete, compatible, no redeclared "
             "identifiers, routed in CODEOWNERS, example documents valid (repository checkout root only)", dm)
    sp.add_argument("names", nargs="*", help="the domain's name (catalysis); the core's checks always run")
    sp.add_argument("--json", action="store_true", help="machine-readable result")
    sp.add_argument("--no-examples", action="store_true", help="skip validating the example documents")
    sp = add("cq", cmd_domains_cq, "run the competency questions (domain/competency/*.yaml: a graph query plan "
             "over public examples and its expected answer)", dm)
    sp.add_argument("names", nargs="*", help="the domain's name (catalysis; default: it)")
    sp.add_argument("--json", action="store_true", help="machine-readable result")

    ci = sub.add_parser("ci", help="checks CI runs on pull requests").add_subparsers(dest="sub", required=True)
    sp = add("spec-changes", cmd_ci_spec_changes, "fail when a branch modifies archived releases or frozen versions, "
             "or changes the schema without what it must carry (scale schema check); print who must review", ci)
    sp.add_argument("--base", required=True, help="git ref the pull request targets (e.g. origin/main)")
    sp.add_argument("--head", default="HEAD", help="git ref of the branch (default: HEAD)")
    sp.add_argument("--json", action="store_true", help="machine-readable result")


    kg = sub.add_parser("kg", help="a knowledge-graph data repository (a folder of curated documents kept apart from this repository)").add_subparsers(dest="sub", required=True)
    sp = add("update", cmd_kg_update, "move every catalysis scale-catal document under a directory to the head (or "
             "--to) schema version through the registered steps, validate, and write in place (not with --dry-run)", kg)
    sp.add_argument("--data", default=".", help="the data directory (default: the current directory)")
    sp.add_argument("--domain", default="catalysis", help="whose schema the documents follow (default: catalysis)")
    sp.add_argument("--to", help="the target schema version (default: the head version of the catalysis schema)")
    sp.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    sp.add_argument("--no-index", action="store_true", help="do not rebuild the evidence index of a changed document")
    sp.add_argument("--out", help="also write the report (JSON) here")

    sp = add("status", cmd_status, "print the implementation-status inventory")
    sp.add_argument("--format", choices=["text", "json", "markdown"], default="text"); sp.add_argument("--out")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rc = args.fn(args)
        return int(rc or 0)
    except ScaleError as exc:
        print(f"scale: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
