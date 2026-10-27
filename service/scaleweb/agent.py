"""The two model loops: curate one source, and answer a question from a graph.

Both run the model (the Claude Messages API, through a client the caller passes) over tools that call the scale-catal
code itself: the curation loop reads the page texts, describes the schema, writes records into the working graph and
runs ``scale source check`` until it passes; the question loop runs ``describe``, ``stats``, ``search`` and ``query``
exactly as the CLI and the MCP server do. The skills (``skills/curate-corpus``, ``skills/query-graph``) are the system
prompts, so the procedure is the one an agent follows anywhere else. Each loop stops at its turn limit or token budget.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from scale import curate, pgraph
from scale.api import ScaleToolkit
from scale.util import find_repo_root, load_doc, write_canonical

RESULT_CHARS = 40_000          # the longest tool result handed back to the model


def _skill(repo: Path, name: str) -> str:
    text = (repo / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)         # the procedure, without its front matter


def _clip(obj) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    return s if len(s) <= RESULT_CHARS else s[:RESULT_CHARS] + f"\n… ({len(s) - RESULT_CHARS} more characters cut)"


def _tool(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": properties or {}, "required": required or []}}


class Loop:
    """A tool-use loop over one conversation, with its token count and a log the page shows."""

    def __init__(self, client, model: str, system: str, tools: list[dict], handlers: dict[str, Callable[[dict], object]],
                 max_turns: int, max_tokens: int, log: Callable[[str], None] = lambda s: None):
        self.client, self.model, self.tools, self.handlers = client, model, tools, handlers
        self.system = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        self.max_turns, self.max_tokens, self.log = max_turns, max_tokens, log
        self.tokens = 0

    def run(self, first: str, stop_tool: str | None = None) -> tuple[str, dict | None]:
        """Run to an answer (the model's last text) or to ``stop_tool``'s input; the reason when it ran out."""
        messages = [{"role": "user", "content": first}]
        for turn in range(self.max_turns):
            r = self.client.messages.create(model=self.model, max_tokens=16000, system=self.system,
                                            tools=self.tools, messages=messages)
            u = getattr(r, "usage", None)
            self.tokens += (getattr(u, "input_tokens", 0) or 0) + (getattr(u, "output_tokens", 0) or 0) \
                + (getattr(u, "cache_creation_input_tokens", 0) or 0)
            blocks = [b if isinstance(b, dict) else b.model_dump() for b in r.content]
            messages.append({"role": "assistant", "content": blocks})
            text = "\n".join(b["text"] for b in blocks if b["type"] == "text").strip()
            calls = [b for b in blocks if b["type"] == "tool_use"]
            if not calls:
                return text, None
            results = []
            for c in calls:
                if c["name"] == stop_tool:
                    return text, c["input"]
                self.log(f"{c['name']} {_clip(c['input'])[:160]}")
                try:
                    out = self.handlers[c["name"]](c["input"])
                    results.append({"type": "tool_result", "tool_use_id": c["id"], "content": _clip(out)})
                except Exception as e:                        # a tool's failure goes back to the model as data
                    results.append({"type": "tool_result", "tool_use_id": c["id"], "is_error": True,
                                    "content": f"{type(e).__name__}: {e}"})
            messages.append({"role": "user", "content": results})
            if self.tokens >= self.max_tokens:
                return text, {"stopped": f"token budget reached ({self.tokens} tokens)"}
        return "", {"stopped": f"turn limit reached ({self.max_turns} turns)"}


# ------------------------------------------------------------------------------------------------- curation


def _upsert(path: Path, nodes: list[dict], links: list[dict]) -> dict:
    doc = load_doc(path)
    for key, recs in (("nodes", nodes), ("links", links)):
        have = {r["id"]: i for i, r in enumerate(doc[key])}
        for r in recs or []:
            if not isinstance(r, dict) or not r.get("id"):
                raise ValueError(f"every {key[:-1]} needs an id")
            if r["id"] in have:
                doc[key][have[r["id"]]] = r
            else:
                have[r["id"]] = len(doc[key])
                doc[key].append(r)
    write_canonical(path, doc)
    return {"nodes": len(doc["nodes"]), "links": len(doc["links"])}


def _remove(path: Path, ids: list[str], keep: set[str]) -> dict:
    doc = load_doc(path)
    gone = set(ids) - keep
    doc["nodes"] = [n for n in doc["nodes"] if n["id"] not in gone]
    doc["links"] = [e for e in doc["links"] if e["id"] not in gone and e["source"] not in gone and e["target"] not in gone]
    write_canonical(path, doc)
    return {"removed": sorted(gone), "kept": sorted(set(ids) & keep), "nodes": len(doc["nodes"]), "links": len(doc["links"])}


def _summary(path: Path) -> dict:
    doc = load_doc(path)
    by: dict[str, list[str]] = {}
    for n in doc["nodes"]:
        by.setdefault(n["label"], []).append(n["id"])
    types: dict[str, int] = {}
    for e in doc["links"]:
        types[e["type"]] = types.get(e["type"], 0) + 1
    return {"graph": doc["graph"], "nodes_by_label": by, "links_by_type": types}


def _pages(folder: Path, first: int, last: int) -> str:
    texts = sorted((folder / "work" / "texts").glob("*.txt"))
    if not texts:
        return "no page texts: the source had no readable text"
    text = texts[0].read_text(encoding="utf-8")
    chunks = re.split(r"^\[page (\d+)\]\n", text, flags=re.M)[1:]
    pages = {int(chunks[i]): chunks[i + 1] for i in range(0, len(chunks), 2)}
    keep = [f"[page {p}]\n{pages[p]}" for p in sorted(pages) if first <= p <= last]
    return "".join(keep) or f"no pages {first}-{last}; the source has pages {min(pages)}-{max(pages)}"


def curate_folder(folder: Path, client, model: str, max_turns: int, max_tokens: int,
                  log: Callable[[str], None] = lambda s: None, repo: Path | None = None) -> dict:
    """Fill the graph of a ``scale source start`` folder by the curate-corpus skill until ``scale source check``
    passes (or the loop runs out); returns the check, the model's summary and the tokens spent."""
    repo = Path(repo) if repo else find_repo_root()
    info = load_doc(folder / "source.json")
    gpath = folder / f"{info['slug']}.graph.json"
    fixed = {n["id"] for n in load_doc(gpath)["nodes"]}          # the Source, steward and project the folder starts with
    kit = ScaleToolkit(workspace=folder, repo=repo)
    npages = info.get("read", {}).get("pages") or len(re.findall(r"^\[page \d+\]$", _pages(folder, 0, 10**6), re.M))
    tools = [
        _tool("read_pages", "The source's page texts, pages first to last (inclusive). Quote evidence verbatim from them.",
              {"first": {"type": "integer"}, "last": {"type": "integer"}}, ["first", "last"]),
        _tool("describe", "The schema: labels and edge types with their properties and the catalysis checklist "
              "(scale describe). No names: an overview of every label and edge type.",
              {"names": {"type": "array", "items": {"type": "string"}}}),
        _tool("graph_summary", "The working graph's header, its node ids by label and its link counts by type."),
        _tool("get_records", "Records of the working graph by id, in full.",
              {"ids": {"type": "array", "items": {"type": "string"}}}, ["ids"]),
        _tool("upsert", "Add records to the working graph, or replace those with the same id. Nodes are "
              "{id, label, props}; links are {id, type, source, target, props}. Ids start with the source's prefix "
              f"({info['source_id'].replace('/source/', '/')}/…) unless they are shared records.",
              {"nodes": {"type": "array", "items": {"type": "object"}},
               "links": {"type": "array", "items": {"type": "object"}}}),
        _tool("remove", "Remove records (and the links touching them) by id. The Source, steward and project stay.",
              {"ids": {"type": "array", "items": {"type": "string"}}}, ["ids"]),
        _tool("check", "scale source check --derive-links: the graph valid under its schema, every quote found in "
              "the page texts, conformance, gaps and the copyright cap. Run it after writing and fix every error."),
        _tool("done", "Finish: the graph checks without error and holds what the source reports. Say what was curated, "
              "what was left out and why.", {"summary": {"type": "string"}}, ["summary"]),
    ]
    handlers = {
        "read_pages": lambda a: _pages(folder, int(a["first"]), int(a["last"])),
        "describe": lambda a: kit.call("describe", {"names": a.get("names") or [], "domain": "catalysis"}),
        "graph_summary": lambda a: _summary(gpath),
        "get_records": lambda a: [r for r in load_doc(gpath)["nodes"] + load_doc(gpath)["links"] if r["id"] in set(a["ids"])],
        "upsert": lambda a: _upsert(gpath, a.get("nodes") or [], a.get("links") or []),
        "remove": lambda a: _remove(gpath, a["ids"], fixed),
        "check": lambda a: _short_check(curate.check(folder, repo, derive_links=True)),
    }
    system = (_skill(repo, "curate-corpus") + "\n\n# Working here\n\nYou curate in a web service, through the tools "
              "given (no shell; the scale commands named above are run for you: `check` is `scale source check "
              "--derive-links`). Read every page before you finish. Write records with `upsert`, run `check` and "
              "fix what it reports, then call `done`.")
    first = (folder / "BRIEF.md").read_text(encoding="utf-8") + f"\n\nThe source has {npages} pages of text."
    loop = Loop(client, model, system, tools, handlers, max_turns, max_tokens, log)
    text, stop = loop.run(first, stop_tool="done")
    final = curate.check(folder, repo, derive_links=True)
    return {"check": _short_check(final), "summary": (stop or {}).get("summary") or text,
            "stopped": (stop or {}).get("stopped"), "tokens": loop.tokens}


def _short_check(res: dict) -> dict:
    out = {k: res[k] for k in ("ok", "records", "quotes_checked_against_text", "gaps", "cap") if k in res}
    out["errors"] = res.get("errors", [])[:40]
    out["warnings"] = res.get("warnings", [])[:20]
    if len(res.get("errors", [])) > 40:
        out["errors_not_shown"] = len(res["errors"]) - 40
    return out


# ------------------------------------------------------------------------------------------------- questions


def answer(graph_path: Path, question: str, client, model: str, max_turns: int, max_tokens: int,
           log: Callable[[str], None] = lambda s: None, repo: Path | None = None) -> dict:
    """Answer a question from one graph by the query-graph skill: plans run by ``scale query``, evidence by
    ``scale search``; returns the answer, the plans run with their results' kinds, and the tokens spent."""
    repo = Path(repo) if repo else find_repo_root()
    kit = ScaleToolkit(workspace=graph_path.parent, repo=repo)
    plans: list[dict] = []

    def run_query(a: dict):
        res = kit.call("query", {"path": graph_path.name, "plan": a["plan"]})
        plans.append({"plan": a["plan"], "status": res.get("status") or res.get("error"),
                      "rows": res.get("row_count", 0)})
        return res

    tools = [
        _tool("describe", "The schema: labels and edge types with their properties (scale describe).",
              {"names": {"type": "array", "items": {"type": "string"}}}),
        _tool("stats", "The graph's units in use per property and its link patterns (scale graph stats)."),
        _tool("search", "Search the graph's evidence by words and meaning (scale graph search); hits lead to the "
              "records that cite them.", {"query": {"type": "string"}, "k": {"type": "integer"},
                                          "published_before": {"type": "string"}}, ["query"]),
        _tool("query", "Run a graph query plan (scale graph query): match, steps, where, return, evidence, order_by, "
              "limit, text, published_before. Returns rows, the kind of answer and the coverage.",
              {"plan": {"type": "object"}}, ["plan"]),
    ]
    handlers = {
        "describe": lambda a: kit.call("describe", {"names": a.get("names") or [], "domain": "catalysis"}),
        "stats": lambda a: pgraph.stats(load_doc(graph_path)),
        "search": lambda a: kit.call("search", {"path": graph_path.name, "query": a["query"], "k": int(a.get("k") or 10),
                                                **({"published_before": a["published_before"]}
                                                   if a.get("published_before") else {})}),
        "query": run_query,
    }
    system = (_skill(repo, "query-graph") + "\n\n# Working here\n\nYou answer in a web page, through the tools given "
              "(no shell). The graph is the one the user is viewing. Write the answer in Markdown: every factual "
              "sentence from returned rows, citing record ids and evidence locators in brackets, then a **Limits** "
              "line. Keep your own extrapolations in a separate, labelled paragraph.")
    loop = Loop(client, model, system, tools, handlers, max_turns, max_tokens, log)
    text, stop = loop.run(question)
    return {"answer": text, "plans": plans, "stopped": (stop or {}).get("stopped"), "tokens": loop.tokens}
