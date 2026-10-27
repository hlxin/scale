"""The inbox: publications that wait, on the computer that runs the service, for Claude Code to curate them.

With ``SCALE_WEB_INBOX`` set, the service's own model curates nothing. ``POST /jobs`` puts the publication in the
inbox and answers at once; the runner (``python -m scaleweb.runner``, runner.py), which the operating system starts
whenever the queue holds something (service/launchd/), curates each one with Claude Code by the curate-corpus skill.
The graph comes back to its owner only (``GET /jobs/{id}``, with the service's receipt), and nothing is published
unless they contribute it, a separate click (``POST /contribute``). A PDF dropped into ``queue/`` by hand is curated the
same way for ``SCALE_WEB_INBOX_LOGIN``. The folder::

    queue/<id>/            waiting: the PDF (or a kept paper's text; none for a DOI alone) and request.json (who, the
                           DOI, the file name, whether they agreed to keep the paper)
    work/<id>/             being curated: the same, and source/, the ``scale source start`` folder
    jobs/<id>.json         what the page shows: the state, the log, the source's rights, or the error
    jobs/<id>.graph.json   the curated graph, its quotes capped by the source's rights, for its owner only
    rejected/              what was dropped into the queue and is not a PDF

When the job ends, the PDF and its page texts are kept in the service's archive (archive.py) as the page says (always
under an open licence, otherwise only when the owner ticked the box) and deleted from the inbox: only ``jobs/`` stays,
and a job is forgotten after JOB_DAYS days. A publication is moved, never copied, from one folder to the next.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path

JOB_DAYS = 14            # a job (its state and its capped graph) is forgotten after this many days
ATTEMPTS = 2             # a job the runner was stopped in the middle of is started again once
SETTLE_S = 10            # a PDF dropped by hand is taken once it has not changed for this long (it may be copying)
FINAL = ("done", "curated", "failed")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write(path: Path, doc: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def pdf_name(filename: str | None) -> str:
    """The file name a PDF is kept under while it waits: its own name made safe (its stem names the source)."""
    stem = "".join(c if c.isalnum() or c in "._-" else "-" for c in Path(filename or "paper.pdf").stem)[:80].strip(".")
    return f"{stem or 'paper'}.pdf"


class Inbox:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.queue, self.work, self.jobs = self.root / "queue", self.root / "work", self.root / "jobs"
        self.incoming, self.rejected = self.root / "incoming", self.root / "rejected"
        for d in (self.queue, self.work, self.jobs, self.incoming):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------------------------------ the service's side
    def add(self, owner: str, doi: str | None = None, pdf: bytes | None = None, filename: str | None = None,
            again: bool = False, keep: bool = False, text: str | None = None, recurate: str | None = None) -> str:
        """Queue a publication (its PDF, a kept paper's page texts, or a DOI alone) for the runner; ``keep``: its owner
        agreed to keep it (archive.py); ``recurate``: the archive key of a kept paper curated again. Returns the id."""
        jid = uuid.uuid4().hex
        tmp = self.incoming / jid                         # written whole, then moved into the queue in one step
        tmp.mkdir()
        if pdf is not None:
            (tmp / pdf_name(filename)).write_bytes(pdf)
        elif text is not None:
            (tmp / pdf_name(filename)).with_suffix(".txt").write_text(text, encoding="utf-8")
        _write(tmp / "request.json", {"id": jid, "owner": owner, "doi": doi, "filename": filename, "again": again,
                                      "keep": keep, "recurate": recurate, "created": _now(), "attempts": 0})
        self._save({"id": jid, "owner": owner, "doi": doi, "filename": filename, "state": "queued", "created": _now(),
                    "created_s": time.time(), "updated": _now(), "log": [{"t": 0.0, "msg": "waiting in the inbox"}]})
        os.replace(tmp, self.queue / jid)
        return jid

    def view(self, jid: str, owner: str) -> dict | None:
        """The job as its owner sees it (anyone else sees nothing), with its capped graph once it is curated. A job
        stays readable until it is forgotten, so that the page can come back to it."""
        job = self._load(jid)
        if not job or job.get("owner") != owner:
            return None
        out = {k: v for k, v in job.items() if k not in ("owner", "created_s")}
        if job["state"] == "queued":
            out["position"] = self.position(jid)
        graph = self.jobs / f"{jid}.graph.json"
        if job["state"] in ("done", "curated") and graph.is_file():
            out["graph"] = json.loads(graph.read_text(encoding="utf-8"))
        return out

    def mine(self, owner: str) -> list[dict]:
        """The owner's jobs, newest first, without their graphs or logs: what the page lists."""
        jobs = [j for j in map(self._load, self._ids()) if j and j.get("owner") == owner]
        keep = ("id", "state", "doi", "filename", "created", "updated", "known", "kept", "error")
        return [{k: j[k] for k in keep if k in j} for j in sorted(jobs, key=lambda j: j.get("created_s", 0), reverse=True)]

    def same_source(self, probe: dict, exclude: str, owner: str) -> dict | None:
        """Another job of the same owner whose publication is the probe's (the same DOI, identifier or PDF digest, as
        commons.find matches): ``{"same_as": {...}}``, else None. Another reader's job never counts, since a graph comes
        back to its owner only; nor a job that failed, so a publication can be sent again."""
        from scale import commons
        held = {}
        for jid in self._ids():
            job = self._load(jid) if jid != exclude else None
            if job and job.get("owner") == owner and job.get("source_record") and job.get("state") not in ("failed", "queued", "reading"):
                held[jid] = {"nodes": [job["source_record"]]}
        hits = commons.find(probe, {"sources": held}) if held else []
        if not hits:
            return None
        jid = hits[0]["file"].removeprefix("parts/sources/").removesuffix(".json")
        job = self._load(jid)
        return {"same_as": {"job": jid, "state": job["state"], "by": hits[0]["by"]}}

    def position(self, jid: str) -> int:
        """How many publications wait before this one (0: it is next)."""
        ids = [p.name for p in self._waiting()]
        return ids.index(jid) if jid in ids else 0

    # ------------------------------------------------------------------------------------------- the runner's side
    def lock(self):
        """One runner at a time: an exclusive lock on runner.lock, held while the returned file stays open (None when
        another runner holds it)."""
        import fcntl
        f = open(self.root / "runner.lock", "w")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return None
        return f

    def adopt(self, login: str | None) -> list[str]:
        """Queue the PDFs dropped into the queue by hand (a file, not a job's folder), credited to ``login``. Anything
        else there is moved to rejected/: a queue that never empties would start the runner again and again."""
        out = []
        for p in sorted(self.queue.iterdir()):
            if p.is_dir() and (p / "request.json").is_file():
                continue                                    # a job the service queued
            if p.name == ".DS_Store":
                p.unlink(missing_ok=True)
                continue
            if p.is_file() and p.suffix.lower() == ".pdf" and login:
                if time.time() - p.stat().st_mtime < SETTLE_S:
                    continue                                # still being copied: a later start takes it
                data = p.read_bytes()
                if data.startswith(b"%PDF"):
                    out.append(self.add(login, pdf=data, filename=p.name))
                    p.unlink()
                    continue
            self.rejected.mkdir(exist_ok=True)
            shutil.move(str(p), str(self.rejected / f"{time.strftime('%Y%m%d-%H%M%S')}-{p.name}"))
        return out

    def claim(self) -> dict | None:
        """Take the publication that has waited longest, moved from the queue into work/ (None when none waits)."""
        for p in self._waiting():
            dest = self.work / p.name
            try:
                os.replace(p, dest)
            except OSError:
                continue                                    # taken by another runner
            return {**json.loads((dest / "request.json").read_text(encoding="utf-8")), "folder": dest}
        return None

    def update(self, jid: str, msg: str | None = None, **fields) -> dict:
        """Change the job's state for the page; ``msg`` adds a line to its log."""
        job = self._load(jid) or {"id": jid, "created_s": time.time()}
        job.update(fields, updated=_now())
        if msg:
            job.setdefault("log", []).append({"t": round(time.time() - job.get("created_s", time.time()), 1), "msg": msg})
            del job["log"][:-200]
        self._save(job)
        return job

    def keep_graph(self, jid: str, graph: dict) -> None:
        """The curated graph, its quotes already capped by the source's rights, for the page to show."""
        (self.jobs / f"{jid}.graph.json").write_text(json.dumps(graph, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    def finish(self, jid: str) -> None:
        """The job has ended: its PDF, its page texts and its working folder are deleted."""
        shutil.rmtree(self.work / jid, ignore_errors=True)

    def recover(self) -> list[str]:
        """The jobs a stopped runner left in work/: queued again (ATTEMPTS starts in all), else failed; the PDF of a
        failed one is deleted."""
        out = []
        for d in sorted(p for p in self.work.iterdir() if p.is_dir()):
            req_path = d / "request.json"
            req = json.loads(req_path.read_text(encoding="utf-8")) if req_path.is_file() else {"attempts": ATTEMPTS}
            req["attempts"] = int(req.get("attempts") or 0) + 1
            shutil.rmtree(d / "source", ignore_errors=True)
            if req["attempts"] < ATTEMPTS:
                _write(req_path, req)
                os.replace(d, self.queue / d.name)
                self.update(d.name, msg="the curating computer stopped in the middle: queued again", state="queued")
            else:
                shutil.rmtree(d, ignore_errors=True)
                self.update(d.name, msg="failed: the curating computer stopped in the middle twice", state="failed",
                            error="the curating computer stopped in the middle of curating it twice")
            out.append(d.name)
        return out

    def sweep(self) -> None:
        """Forget the jobs older than JOB_DAYS, and anything a stopped service left half written in incoming/."""
        now = time.time()
        for p in self.jobs.iterdir():
            if now - p.stat().st_mtime > JOB_DAYS * 86400:
                p.unlink(missing_ok=True)
        for p in self.incoming.iterdir():
            if now - p.stat().st_mtime > 3600:
                shutil.rmtree(p, ignore_errors=True)

    # --------------------------------------------------------------------------------------------------- the files
    def _ids(self) -> list[str]:
        return [p.name[:-5] for p in self.jobs.glob("*.json") if p.name[:-5].isalnum()]

    def _load(self, jid: str) -> dict | None:
        p = self.jobs / f"{jid}.json"
        return json.loads(p.read_text(encoding="utf-8")) if jid.isalnum() and p.is_file() else None

    def _save(self, job: dict) -> None:
        _write(self.jobs / f"{job['id']}.json", job)

    def _waiting(self) -> list[Path]:
        items = [p for p in self.queue.iterdir() if p.is_dir() and (p / "request.json").is_file()]
        return sorted(items, key=lambda p: (p / "request.json").stat().st_mtime)
