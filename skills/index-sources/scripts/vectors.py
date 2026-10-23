"""The vector store of the downloaded sources (sources/vectors.db): passages of their text with vectors, to search
by meaning and by words. The source index keeps the records; the store keeps the passages' text and vectors only, and
every search joins its hits to the index by source ID; passages of reference lists (dense with citations) are left
out unless --with-references. Details: references/database.md ("The vector store").

  python3 -I vectors.py init [--embedder sentence-transformers:BAAI/bge-small-en-v1.5]   # create; fetch a model once
  python3 -I vectors.py update [--embedder E] [--ids 12,57] [--limit N]   # new and changed sources only
  python3 -I vectors.py search "Cu/ZnO methanol synthesis deactivation" [--k 10] [--mode hybrid|vector|keyword]
                               [--embedder E] [--topic <slug>] [--year 2020-2026] [--ids 12,57] [--with-references]
  python3 -I vectors.py search "..." --by-source [--k 20] [--ids-out ids.txt]   # the best sources, not passages
  python3 -I vectors.py get <ID or DOI> [--text]     # one source as the store holds it: its record and passages in order
  python3 -I vectors.py status
  python3 -I vectors.py drop --embedder E          # stop keeping an embedder; its vectors are removed

Embedders: scale-hash-v1 (SCALE's default: lexical with chemistry aliases, no download), sentence-transformers:<model>
(a local neural model, e.g. BAAI/bge-small-en-v1.5, 133 MB, or sentence-transformers/all-MiniLM-L6-v2, 91 MB) and
fastembed:<model>. A store keeps every embedder it was given up to date; `init --embedder` adds one (a neural model
is fetched here, once — updates and searches never fetch anything). Nothing is embedded twice: a vector belongs to a
passage's text and embedder, a source is read again only when its files change, and then only new text is embedded.
Every step that changes the downloads (download_open, download_paywalled, fetch_si, dedup, merge_db) updates the store
when the project has one. Prints one JSON object.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import Project, add_project_arg, die, log  # noqa: E402
from _ledger import Ledger  # noqa: E402
import _vectors as V  # noqa: E402


def allowed_ids(proj, a):
    """The sources a search may return (--topic, --year, --ids), from the index; None = all."""
    if not (a.topic or a.year or a.ids):
        return None
    where, args = [], []
    if a.topic:
        where.append("id IN (SELECT source_id FROM source_collections WHERE collection = ? AND COALESCE(in_scope, 1) = 1)")
        args.append(a.topic)
    if a.year:
        lo, _, hi = a.year.partition("-")
        where.append("year BETWEEN ? AND ?")
        args += [int(lo), int(hi or lo)]
    if a.ids:
        ids = [int(x) for x in a.ids.split(",") if x.strip().isdigit()]
        where.append(f"id IN ({','.join('?' * len(ids))})")
        args += ids
    con = sqlite3.connect(f"file:{proj.db}?mode=ro", uri=True)
    out = {r[0] for r in con.execute(f"SELECT id FROM sources WHERE {' AND '.join(where)}", args)}
    con.close()
    return out


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("cmd", choices=["init", "update", "search", "get", "status", "drop"])
    ap.add_argument("query", nargs="?")
    ap.add_argument("--embedder")
    ap.add_argument("--ids")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--mode", choices=["hybrid", "vector", "keyword"], default="hybrid")
    ap.add_argument("--topic")
    ap.add_argument("--year")
    ap.add_argument("--with-references", action="store_true", help="search: keep the passages of reference lists")
    ap.add_argument("--by-source", "--by-paper", dest="by_source", action="store_true", help="search: rank sources (by their best passage), not passages")
    ap.add_argument("--ids-out", help="search --by-source: write the sources' IDs, one per line (curate_run.py --ids-file)")
    ap.add_argument("--text", action="store_true", help="get: print the source's text page by page instead of JSON")
    a = ap.parse_args()
    try:
        run(a)
    except RuntimeError as e:               # a missing store, source or model: say what to do
        die(str(e))


def run(a):
    proj = Project(a.project)
    if a.cmd == "init":
        name = a.embedder or V.DEFAULT_EMBEDDER
        emb = V.get_embedder(name, download=True)          # a neural model is fetched (once) here only
        con = V.open_store(proj, create=True)
        have = V.embedders_of(con) if V.about(con).get("embedders") else []
        V.set_about(con, embedders=list(dict.fromkeys(have + [emb.id])), cutter=V.CUTTER,
                    **({} if V.about(con).get("created_at") else {"created_at": V.now_iso()}))
        con.close()
        res = {"store": proj.rel(V.store_path(proj)), "embedders": list(dict.fromkeys(have + [emb.id])),
               "dim": int(V.encode(emb, ["test"]).shape[1]), "next": "vectors.py update"}
    elif a.cmd == "update":
        ids = [int(x) for x in a.ids.split(",") if x.strip().isdigit()] if a.ids else None
        res = V.update(proj, Ledger(proj), embedders=[a.embedder] if a.embedder else None, ids=ids, limit=a.limit)
    elif a.cmd == "search":
        if not a.query:
            die("search needs a query")
        if a.by_source:
            res = V.by_source(proj, a.query, k=a.k, mode=a.mode, embedder=a.embedder, allowed=allowed_ids(proj, a),
                             references=a.with_references)
            if a.ids_out:
                Path(a.ids_out).write_text("".join(f"{p['source_id']}\n" for p in res["sources"]))
                res["ids_file"] = a.ids_out
        else:
            res = V.search(proj, a.query, k=a.k, mode=a.mode, embedder=a.embedder, allowed=allowed_ids(proj, a),
                           references=a.with_references)
    elif a.cmd == "get":
        if not a.query:
            die("get needs a source ID or DOI")
        res = V.source_text(proj, a.query)
        if a.text:
            pages, cur = [], None
            for t in res["text"]:
                if t["page"] != cur:
                    cur = t["page"]
                    pages.append(f"\n[page {cur}]")
                pages.append(t["text"])
            print(f"{res.get('title') or ''} ({res.get('year') or ''}) {res.get('doi') or ''} — source {res['source_id']}")
            print("\n".join(pages))
            return
    elif a.cmd == "status":
        res = V.status(proj, Ledger(proj))
    else:
        if not a.embedder:
            die("drop needs --embedder")
        con = V.open_store(proj)
        keep = [e for e in V.embedders_of(con) if e != a.embedder]
        with con:
            n = con.execute("DELETE FROM vectors WHERE embedder = ?", (a.embedder,)).rowcount
            con.execute("DELETE FROM about WHERE name = ?", (f"checked:{a.embedder}",))
        V.set_about(con, embedders=keep or [V.DEFAULT_EMBEDDER])
        con.close()
        res = {"dropped": a.embedder, "vectors_removed": n, "embedders": keep or [V.DEFAULT_EMBEDDER]}
        log(f"vectors: {a.embedder} dropped ({n} vectors)")
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
