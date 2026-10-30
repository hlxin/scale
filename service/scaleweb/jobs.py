"""Curation jobs: one source each, run in the background, kept only until their owner has the result or they expire.

A job is ``scale source start`` (the DOI resolved, the PDF read into page texts), the curation loop, then ``scale
source finish --public``: the result is the graph with every quote capped by the source's rights (the uploaded PDF and
its page texts never leave the service), its check and the model's summary. The job's working files are deleted
when the job ends; its result stays in memory until the page says it has it (``done``) or an hour after the job ends,
so that a reply lost on the way can be asked for again. Before the files go, a finished job's source (the PDF and its
page texts) is kept in the archive when the source's licence or the contributor's agreement allows (archive.py).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from scale import curate, rights
from scale.util import ScaleError, load_doc

from . import agent, auth
from .archive import Archive
from .auth import Budget
from .config import Config


class Jobs:
    def __init__(self, cfg: Config, budget: Budget, client_factory: Callable[[], object], repo: Path,
                 run_inline: bool = False):
        self.cfg, self.budget, self.client_factory, self.repo = cfg, budget, client_factory, repo
        self.root = Path(cfg.workdir or tempfile.mkdtemp(prefix="scale-web-"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.slots = threading.Semaphore(cfg.concurrent_jobs)
        self.run_inline = run_inline               # tests: run the job in the calling thread
        self.archive = Archive(cfg.archive or None)

    def submit(self, owner: str, doi: str | None = None, pdf: bytes | None = None, filename: str | None = None,
               keep_text: bool = False, text: Path | None = None, recurating: bool = False) -> str:
        self.sweep()
        jid = uuid.uuid4().hex
        folder = self.root / jid
        folder.mkdir()
        pdf_path = None
        if pdf is not None:
            stem = "".join(c if c.isalnum() or c in "._-" else "-" for c in Path(filename or "source.pdf").stem)[:80] or "source"
            pdf_path = folder / "upload" / f"{stem}.pdf"
            pdf_path.parent.mkdir()
            pdf_path.write_bytes(pdf)
        job = {"id": jid, "owner": owner, "state": "queued", "log": [], "created": time.time(), "folder": folder,
               "doi": doi, "keep_text": bool(keep_text), "text": text,
               "recurating": recurating}
        with self.lock:
            self.jobs[jid] = job
        if self.run_inline:
            self._run(job, doi, pdf_path)
        else:
            threading.Thread(target=self._run, args=(job, doi, pdf_path), daemon=True).start()
        return jid

    def version(self) -> str | None:
        """The schema version of catal-commons, so that every graph curated here can be contributed to it."""
        header = self.repo / self.cfg.commons / "parts" / "header.json"
        return load_doc(header)["graph"].get("schema_version") if header.is_file() else None

    def _log(self, job: dict, line: str) -> None:
        job["log"].append({"t": round(time.time() - job["created"], 1), "msg": line})
        del job["log"][:-200]

    def _run(self, job: dict, doi: str | None, pdf_path: Path | None) -> None:
        with self.slots:
            work = job["folder"] / "work-folder"
            try:
                job["state"] = "reading"
                self._log(job, "resolving the DOI and reading the PDF" if doi and pdf_path else
                          "resolving the DOI" if doi else "reading the PDF")
                started = curate.start(work, doi=doi, pdf=pdf_path, email=self.cfg.contact_email or None,
                                       repo=self.repo, version=self.version(),
                                       **({"text": job["text"]} if job.get("text") else {}))
                job["source"] = {k: started.get(k) for k in ("source_id", "rights_class", "pages", "schema_version", "notes")}
                if not started.get("pages"):
                    raise ScaleError("no text could be read: give the PDF (an open-access copy was not found or not "
                                     "openly licensed)" if doi and not pdf_path else "no text could be read from the PDF")
                job["state"] = "curating"
                self._log(job, f"{started['pages']} pages read; rights: {started['rights_class']}; curating")
                left = min(self.cfg.tokens_per_job, self.budget.left())
                res = agent.curate_folder(work, self.client_factory(), self.cfg.model, self.cfg.max_turns, left,
                                          log=lambda s: self._log(job, s), repo=self.repo)
                self.budget.spend(res["tokens"])
                job.update(check=res["check"], summary=res["summary"], stopped=res["stopped"], tokens=res["tokens"])
                if not res["check"]["ok"]:
                    raise ScaleError(f"the graph still has {len(res['check']['errors'])} errors"
                                     + (f" ({res['stopped']})" if res["stopped"] else ""))
                fin = curate.finish(work, public=True, repo=self.repo)
                job["graph"] = load_doc(work / fin["public"]["graph"])
                job["withheld"] = fin["public"]["withheld"]
                job["rights"] = rights.load_rights(work / "rights.yaml")[started["source_id"]]
                job["receipt"] = auth.receipt(self.cfg, job["owner"], job["graph"], job["rights"])
                if started.get("page_texts") and not job["recurating"]:
                    src = next(n for n in job["graph"]["nodes"] if n.get("label") == "Source")["props"]
                    digest = hashlib.sha256(json.dumps(job["graph"], sort_keys=True).encode()).hexdigest()
                    kept = self.archive.keep(work / started["page_texts"], doi=doi or src.get("doi"),
                                             title=src.get("title"), rights=job["rights"], login=job["owner"],
                                             consent=job["keep_text"], schema_version=started.get("schema_version"),
                                             graph_sha256=digest,
                                             pdf=pdf_path or (work / started["pdf"] if started.get("pdf") else None))
                    job["kept"] = {"sha256": kept, "because": Archive.why(job["rights"].get("class"), job["keep_text"])} if kept else None
                    if kept:
                        self._log(job, "source kept for curating again after a schema change"
                                  + (" (open licence)" if job["kept"]["because"] == "open_licence" else " (you agreed)"))
                job["state"] = "done"
                self._log(job, "done")
            except Exception as e:                       # the job reports its failure; the service goes on
                job["state"], job["error"] = "failed", f"{e}" if isinstance(e, ScaleError) else f"{type(e).__name__}: {e}"
                self._log(job, f"failed: {job['error']}")
            finally:
                shutil.rmtree(job["folder"] / "upload", ignore_errors=True)
                shutil.rmtree(work, ignore_errors=True)          # the page texts and the PDF go now; the result stays in memory
                job["ended"] = time.time()

    def view(self, jid: str, owner: str) -> dict | None:
        """The job as its owner sees it, as often as they ask, until they say they have it (``done``) or it expires."""
        with self.lock:
            job = self.jobs.get(jid)
            if not job or job["owner"] != owner:
                return None
            return {k: v for k, v in job.items() if k not in ("folder", "owner", "created", "ended", "text", "recurating")}

    def done(self, jid: str, owner: str) -> bool:
        """The owner has a finished job's result: forget it now. A job still running is not stopped."""
        with self.lock:
            job = self.jobs.get(jid)
            if not job or job["owner"] != owner or job["state"] not in ("done", "failed"):
                return False
            self.jobs.pop(jid)
        shutil.rmtree(job["folder"], ignore_errors=True)
        return True

    def sweep(self) -> None:
        now = time.time()
        with self.lock:
            for jid, job in list(self.jobs.items()):
                if job["state"] in ("done", "failed") and now - job.get("ended", job["created"]) > self.cfg.job_ttl_s:
                    self.jobs.pop(jid)
                    shutil.rmtree(job["folder"], ignore_errors=True)
