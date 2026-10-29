"""The frozen corpus a fetch works on (library module — not run directly).

A corpus is frozen by index-sources (freeze_corpus.py: sources/<topic>/corpora/<name>/sources.json): its included
sources are the ones to fetch. --corpus gives the download steps that list and its topic; without it they work on a
whole topic (--topic), as before.
"""
import json
from pathlib import Path

import _core  # noqa: F401  (index-sources' scripts: the shared core)
from _common import die

INCLUDED = ("in_scope", "included")


def add_corpus_arg(ap, topic_required=False):
    ap.add_argument("--corpus", default=None, help="a frozen corpus (sources.json): fetch only its included sources "
                                                   "(the topic is the corpus's)")
    ap.add_argument("--topic", default=None, help="a whole topic instead of a corpus" +
                    (" (one of --corpus, --topic)" if topic_required else ""))
    return ap


def load(path):
    p = Path(path)
    if not p.is_file():
        die(f"no corpus manifest at {p}")
    m = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(m.get("sources"), list) or not m.get("topic"):
        die(f"{p} is not a corpus frozen by index-sources (freeze_corpus.py): it names no topic or no sources")
    return m


def source_id(entry):
    """A manifest entry's index ID (source_id; paper_id in a manifest frozen before the rename)."""
    v = entry.get("source_id", entry.get("paper_id"))
    return int(v) if v is not None else None


def included_ids(m, statuses=INCLUDED + ("not_retrieved",)):
    """The IDs a fetch works on: the included sources, and those a fetch could not get yet (a new try may)."""
    return {source_id(s) for s in m["sources"] if s.get("status") in statuses and source_id(s) is not None}


def scope(a, topic_required=False):
    """(topic, ids or None) from --corpus / --topic."""
    if a.corpus:
        m = load(a.corpus)
        if a.topic and a.topic != m["topic"]:
            die(f"--topic {a.topic} is not the corpus's topic ({m['topic']})")
        return m["topic"], included_ids(m)
    if topic_required and not a.topic:
        die("give --corpus <sources.json> (a frozen corpus) or --topic <slug>")
    return a.topic, None
