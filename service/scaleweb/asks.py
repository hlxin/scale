"""The questions in words that Claude Code answers on the computer that runs the service (``SCALE_WEB_ASK=claude-code``).

They join one line: ``SCALE_WEB_ASK_WORKERS`` are answered at once (runner.answer), the oldest first, and the others
wait their turn; none is turned away. Each question's graph waits with it in a folder of its own, deleted once it is
answered. ``POST /ask`` with ``"wait": false`` returns the question's id and place in the line at once, and the page
follows it (``GET /ask/{id}``: waiting with the questions before it, answering, then the answer); a client that does not
send it waits for the answer, as before the line. Only the reader who asked reads a question, for an hour after it is
answered; the line lives in the service's memory.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from scale.util import write_canonical

KEEP_S = 3600                   # an answer stays readable for an hour


class Asks:
    def __init__(self, workers: int, answer: Callable[[Path, str], dict]):
        self.answer = answer                                  # (graph path, question) -> the answer (runner.answer)
        self.pool = ThreadPoolExecutor(max(1, workers), thread_name_prefix="scale-ask")
        self.lock = threading.Lock()
        self.line: list[str] = []                             # the questions waiting, the oldest first
        self.items: dict[str, dict] = {}

    def add(self, owner: str, graph: dict, question: str, done: Callable[[dict], None] | None = None) -> str:
        """Put a question in the line with the graph it is about; ``done`` gets its answer. Returns its id."""
        path = Path(tempfile.mkdtemp(prefix="scale-web-q-")) / "graph.graph.json"
        write_canonical(path, graph)
        qid = uuid.uuid4().hex
        with self.lock:
            now = time.time()
            for k in [k for k, v in self.items.items() if v["ended"] and now - v["ended"] > KEEP_S]:
                del self.items[k]
            self.items[qid] = {"owner": owner, "state": "waiting", "ended": 0.0, "event": threading.Event()}
            self.line.append(qid)
        self.pool.submit(self._run, qid, path, question, done)
        return qid

    def _run(self, qid: str, path: Path, question: str, done: Callable[[dict], None] | None) -> None:
        item = self.items[qid]
        with self.lock:
            self.line.remove(qid)
            item["state"] = "answering"
        try:
            res = self.answer(path, question)
            if done:
                done(res)
            item.update(state="done", result=res)
        except Exception as e:                                # told to the reader without a traceback
            print(f"error answering a question: {type(e).__name__}: {e}", file=sys.stderr)
            item.update(state="failed", error="the service could not answer the question")
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)
            item["ended"] = time.time()
            item["event"].set()

    def view(self, qid: str, owner: str) -> dict | None:
        """The question as the reader who asked sees it: waiting (``position``: the questions before it), answering,
        done (the answer) or failed (why); anyone else sees nothing."""
        with self.lock:
            item = self.items.get(qid)
            if not item or item["owner"] != owner:
                return None
            out = {"ask": qid, "state": item["state"]}
            if item["state"] == "waiting":
                out["position"] = self.line.index(qid)
            elif item["state"] == "done":
                out.update(item["result"])
            elif item["state"] == "failed":
                out["error"] = item["error"]
            return out

    def wait(self, qid: str) -> dict:
        """Wait for a question's answer: the answer, or ``{"error": …}``."""
        item = self.items[qid]
        item["event"].wait()
        return item["result"] if item["state"] == "done" else {"error": item["error"]}
