"""Topic A/B/C and Related topics: the vocabulary, assignment, proposed new terms and manual corrections.

  python3 -I topics.py vocab                                  # the vocabulary (bundled + .scripts/vocab_custom.json)
  python3 -I topics.py summary --topic <slug>                 # how the topic's papers spread over Topic A/B/C
  python3 -I topics.py assign --topic <slug>                  # deterministic match for papers without Claude/API topics
  python3 -I topics.py proposed [--topic <slug>]              # labels Claude/API used that are not in the vocabulary
  python3 -I topics.py set --ids 12,57 --main "CO2RR,Copper catalysts" [--related "CORR"]   # correct by hand
  python3 -I topics.py set --ids 12,57 --main "Methanol synthesis" --add    # in front of each paper's own topics
To extend the vocabulary, add terms to .scripts/vocab_custom.json (format in references/topics.md) and run `assign`.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import Project, add_project_arg, die
from _ledger import Ledger
from _topics import FACET_ORDER, Vocab, apply_vocab


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("cmd", choices=["vocab", "summary", "assign", "proposed", "set"])
    ap.add_argument("--topic")
    ap.add_argument("--ids")
    ap.add_argument("--main")
    ap.add_argument("--related", default="")
    ap.add_argument("--add", action="store_true",
                    help="set: put --main in front of each paper's own Topic A/B/C (three in all) instead of replacing them")
    ap.add_argument("--no-export", action="store_true", help="assign: do not refresh the index CSVs and papers.db")
    a = ap.parse_args()
    proj = Project(a.project)
    vocab = Vocab(proj)
    if a.cmd == "vocab":
        out = {}
        for tid in vocab.order:
            t = vocab.terms[tid]
            out.setdefault(t.get("facet", "?"), []).append(f"{t['label']} [{tid}]")
        print(json.dumps({"vocabulary": vocab.name, "terms": len(vocab.order),
                          "by_facet": dict(sorted(out.items(), key=lambda kv: FACET_ORDER.get(kv[0], 9)))}, indent=1))
        return
    led = Ledger(proj)
    if a.cmd == "assign":
        if not a.topic:
            die("assign needs --topic")
        n = 0
        for rows in led.iter_topic(a.topic):      # 20,000 papers at a time: a topic may hold millions
            n += apply_vocab(led, vocab, rows)
        if not a.no_export:
            led.export(topics=[a.topic])
        print(json.dumps({"assigned": n, "topic": a.topic}))
        return
    if a.cmd == "set":
        if not (a.ids and a.main):
            die("set needs --ids and --main")
        main_ids = [vocab.resolve(x) or ("new:" + x.strip()) for x in a.main.split(",") if x.strip()]
        rel = [vocab.resolve(x) for x in a.related.split(",") if x.strip()]
        ids = [int(x) for x in a.ids.split(",") if x.strip().isdigit()]
        with led.tx():
            for i in ids:
                mains, extra = main_ids, [r for r in rel if r]
                if a.add:                   # the paper's own topics follow; the ones pushed out become related
                    own = led.subjects_of(i)
                    own_main = [x["term"] for x in sorted(own, key=lambda x: x["rank"]) if x["kind"] == "main"]
                    mains = list(dict.fromkeys(main_ids + own_main))[:3]
                    extra += [t for t in own_main if t not in mains] + [x["term"] for x in own if x["kind"] == "related"]
                led.set_subjects(i, mains, vocab.related_for(mains, extra), "manual", force=True)
        led.export(topics=[a.topic] if a.topic else None)
        print(json.dumps({"set": len(ids), "main": [vocab.label(t) for t in main_ids]}))
        return
    # counted by SQLite (a topic may hold millions of papers)
    src = "paper_subjects s" + (" JOIN paper_topics t ON t.paper_id = s.paper_id AND t.topic = ?" if a.topic else "")
    targs = (a.topic,) if a.topic else ()

    def grouped(col, where):
        return led.q(f"SELECT {col}, COUNT(*) FROM {src} WHERE {where} GROUP BY 1 ORDER BY 2 DESC, 1", targs)

    if a.cmd == "proposed":
        out = []
        for term, cnt in grouped("s.term", "s.term LIKE 'new:%'")[:40]:
            ids = [r[0] for r in led.q(f"SELECT s.paper_id FROM {src} WHERE s.term = ? ORDER BY s.paper_id LIMIT 3",
                                       (*targs, term))]
            out.append({"label": term[4:], "papers": cnt,
                        "examples": [((led.get(i) or {}).get("title") or "")[:100] for i in ids]})
        print(json.dumps({"proposed": out}, indent=1, ensure_ascii=False))
        return
    # summary
    n_papers = led.q(f"SELECT COUNT(DISTINCT s.paper_id) FROM {src}", targs)[0][0]

    def labels(rows):
        c = Counter()
        for term, cnt in rows:
            c[vocab.label(term)] += cnt
        return c
    by_rank = {i: labels(grouped("s.term", f"s.kind = 'main' AND s.rank = {i}")) for i in (1, 2, 3)}
    any_main = labels(grouped("s.term", "s.kind = 'main'"))
    methods = Counter(dict(grouped("s.method", "s.kind = 'main' AND s.rank = 1")))
    total = led.q("SELECT COUNT(*) FROM paper_topics WHERE topic = ?", (a.topic,))[0][0] if a.topic else None
    print(json.dumps({"topic": a.topic, "papers": total, "with_topics": n_papers, "method": dict(methods),
                      "topic_a": dict(by_rank[1].most_common(15)), "any_of_a_b_c": dict(any_main.most_common(25))},
                     indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
