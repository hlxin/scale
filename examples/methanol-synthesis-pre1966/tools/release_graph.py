"""Build or verify a release of this example's knowledge graph: an immutable, digested snapshot.

    python tools/release_graph.py build v1.0.0 [--date YYYY-MM-DD]   # writes releases/v1.0.0/; refuses an existing one
    python tools/release_graph.py verify [v1.0.0]                    # every release (or one): digests and answers

A release holds the graph, the corpus list (corpus/sources.json), the rights file and the query plans, copied as
they are, with RELEASE.yaml (the schema version and its spec digest, the graph's digest, counts, and each plan's
status and row count) and SHA256SUMS (every file's digest). It is built only from a graph that validates with no
error, keeps every quote within the cap and is public. Nothing in a release is edited afterwards: a new graph is a
new release.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
EX = HERE.parent


def _repo_root(*starts: Path) -> Path:
    for p in (q for s in starts for q in (s, *s.parents)):
        if (p / "scale-release.yaml").exists() and (p / "releases").is_dir():
            return p
    raise SystemExit("run inside a SCALE repository checkout")


REPO = _repo_root(HERE, Path.cwd())
sys.path.insert(0, str(REPO / "tools"))
from scale import layout, pgraph, pgraph_query, rights  # noqa: E402
from scale.passages import Index, evidence_items, graph_sha256  # noqa: E402
from scale.util import dump_yaml, load_doc, load_yaml  # noqa: E402

GRAPH = "methanol-synthesis.graph.json"
RELEASES = EX / "releases"
SUMS = "SHA256SUMS"
MANIFEST = "RELEASE.yaml"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def answers(doc: dict, plans: list[Path]) -> dict[str, dict]:
    """Each plan's status and row count on the graph (the evidence index built in memory, embedder scale-hash-v1)."""
    spec = pgraph.load_spec(REPO / layout.DOMAIN / layout.DOMAIN_GRAPH_MANIFEST)
    ix = Index.build(evidence_items(doc), graph_sha256=graph_sha256(doc))
    out = {}
    for p in sorted(plans):
        plan = load_yaml(p)
        res = pgraph_query.run(doc, spec, plan, ix if plan.get("text") else None)
        out[p.stem] = {"status": res["status"], "rows": res["row_count"]}
    return out


def build(version: str, date: str) -> Path:
    out = RELEASES / version
    if out.exists():
        raise SystemExit(f"{out.relative_to(REPO)} exists: a release is never rebuilt; choose a new version")
    doc = load_doc(EX / GRAPH)
    g = doc["graph"]
    ident = pgraph.identify(REPO / layout.DOMAIN / layout.DOMAIN_GRAPH_MANIFEST, g["schema_version"])
    if not ident["known"]:
        raise SystemExit(ident["message"])
    rep = pgraph.validate(doc, pgraph.load_spec(REPO / layout.DOMAIN / layout.DOMAIN_GRAPH_MANIFEST))
    cap = rights.report(doc, rights.load_rights(EX / "rights.yaml"))
    access = rights.access_problems(REPO, [EX / GRAPH])
    if rep.errors or not cap["ok"] or access:
        raise SystemExit(f"not releasable: {len(rep.errors)} errors, cap ok {cap['ok']}, access {access[:1]}")
    out.mkdir(parents=True)
    (out / "queries").mkdir()
    shutil.copyfile(EX / GRAPH, out / GRAPH)
    shutil.copyfile(EX / "corpus/sources.json", out / "sources.json")
    shutil.copyfile(EX / "rights.yaml", out / "rights.yaml")
    plans = sorted((EX / "queries/scale-graph").glob("*.yaml"))
    for p in plans:
        shutil.copyfile(p, out / "queries" / p.name)
    ev = [e for r in doc["nodes"] + doc["links"] for e in r["props"].get("evidence") or []]
    labels = Counter(n["label"] for n in doc["nodes"])
    manifest = {
        "release": version,
        "date": date,
        "title": g["title"],
        "graph_id": g["graph_id"],
        "data_status": g["data_status"],
        "access": g["stewardship"]["access"],
        "schema": {"name": "scale-graph", "version": g["schema_version"], "spec_sha256": ident["sha256"],
                   "follows_domains": g["follows_domains"]},
        "graph": {"file": GRAPH, "sha256": _sha(out / GRAPH), "graph_sha256": graph_sha256(doc)},
        "corpus": {"file": "sources.json", "sha256": _sha(out / "sources.json"),
                   "sources": len(load_doc(out / "sources.json")["sources"]), "cutoff": "1966-01-01"},
        "counts": {"nodes": len(doc["nodes"]), "links": len(doc["links"]), "sources": labels["Source"],
                   "catalytic_tests": labels["CatalyticTest"], "claims": labels["Claim"], "evidence_items": len(ev),
                   "withheld_quotes": sum("withheld" in (e.get("note") or "") for e in ev)},
        "validation": {"errors": 0, "warnings": len(rep.warnings)},
        "queries": answers(doc, [out / "queries" / p.name for p in plans]),
    }
    (out / MANIFEST).write_text(dump_yaml(manifest), encoding="utf-8")
    files = sorted(p for p in out.rglob("*") if p.is_file())
    (out / SUMS).write_text("".join(f"{_sha(p)}  {p.relative_to(out).as_posix()}\n" for p in files), encoding="utf-8")
    return out


def verify(version: str | None = None) -> list[str]:
    """Problems with the releases (or one): a file whose digest changed, a file added or missing, a manifest whose
    graph digest or answers no longer hold."""
    problems = []
    for rel in sorted(p for p in RELEASES.iterdir() if p.is_dir()) if version is None else [RELEASES / version]:
        sums = dict(reversed(line.split("  ", 1)) for line in (rel / SUMS).read_text().splitlines())
        files = {p.relative_to(rel).as_posix() for p in rel.rglob("*") if p.is_file()} - {SUMS}
        problems += [f"{rel.name}: {f} added" for f in sorted(files - set(sums))]
        problems += [f"{rel.name}: {f} missing" for f in sorted(set(sums) - files)]
        problems += [f"{rel.name}: {f} changed" for f in sorted(files & set(sums)) if _sha(rel / f) != sums[f]]
        m = load_yaml(rel / MANIFEST)
        doc = load_doc(rel / GRAPH)
        if graph_sha256(doc) != m["graph"]["graph_sha256"]:
            problems.append(f"{rel.name}: the graph's content digest is not the manifest's")
        got = answers(doc, list((rel / "queries").glob("*.yaml")))
        problems += [f"{rel.name}: {q} answers {got.get(q)}, not {a}" for q, a in m["queries"].items() if got.get(q) != a]
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("version")
    b.add_argument("--date", default=datetime.date.today().isoformat())
    v = sub.add_parser("verify")
    v.add_argument("version", nargs="?")
    a = ap.parse_args()
    if a.cmd == "build":
        print(build(a.version, a.date).relative_to(REPO))
    else:
        problems = verify(a.version)
        print("\n".join(problems) or "ok")
        sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
