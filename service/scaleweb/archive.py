"""The sources (sources, patents, reports) the service keeps, so that a source can be curated again (after a schema change) without anyone
uploading it again.

What is kept is the copy the contributor gave: the PDF they uploaded (or the open-access copy fetched for a DOI) and
its page texts. An embedding cannot be read back into the numbers and quotes a curation needs, so the source itself is
what is kept. It is kept in a private folder of the service (``SCALE_WEB_ARCHIVE``), never published, never committed
and never sent to a page:

* a source under an open licence (rights class ``open`` or ``public_domain``) is kept, as its licence allows;
* any other source only when the contributor agreed when they started the job (``keep_text``), which is recorded with
  their login and the time; they can withdraw it (``forget``), and the source goes when no agreement is left.

Each source is a folder named by the sha256 of its page texts: ``paper.pdf`` (when there was a PDF), ``pages.txt`` (as
``scale source start`` writes them) and ``meta.json`` (its DOI and title, its rights entry, why it is kept, who agreed, and every curation of it with the schema
version it was curated under). ``recurate`` curates the kept sources again under the commons' schema, from the PDF
when there is one (so a better reading of its tables and figures counts), else from the texts.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

KEPT_BY_LICENCE = ("open", "public_domain")


class Archive:
    def __init__(self, root: str | Path | None):
        self.root = Path(root) if root else None

    @property
    def on(self) -> bool:
        return self.root is not None

    def _meta(self, sha: str) -> dict:
        p = self.root / sha / "meta.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}

    def _write(self, sha: str, meta: dict) -> None:
        (self.root / sha / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True),
                                                    encoding="utf-8")

    @staticmethod
    def why(rights_class: str | None, consent: bool) -> str | None:
        """Why a source's text may be kept: its licence, the contributor's agreement, or not at all (None)."""
        return "open_licence" if rights_class in KEPT_BY_LICENCE else "consent" if consent else None

    def keep(self, pages: Path, *, doi: str | None, title: str | None, rights: dict, login: str, consent: bool,
             schema_version: str | None, graph_sha256: str | None, pdf: Path | None = None) -> str | None:
        # pages is ``work/texts/<slug>.txt``: the slug is kept so that curating it again gives the same source id
        """Keep a curated source (its PDF, when there was one, and its page texts) when its licence or the contributor's
        agreement allows; returns the key (the sha256 of the texts), or None when nothing was kept."""
        if not self.on or not pages.is_file():
            return None
        why = self.why(rights.get("class"), consent)
        if why is None:
            return None
        text = pages.read_text(encoding="utf-8")
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        folder = self.root / sha
        folder.mkdir(parents=True, exist_ok=True)
        if not (folder / "pages.txt").is_file():
            (folder / "pages.txt").write_text(text, encoding="utf-8")
        if pdf is not None and pdf.is_file() and not (folder / "paper.pdf").is_file():
            shutil.copyfile(pdf, folder / "paper.pdf")
        meta = self._meta(sha) or {"sha256": sha, "consents": [], "curations": []}
        meta.update({"doi": doi or meta.get("doi"), "title": title or meta.get("title"), "rights": rights,
                     "slug": meta.get("slug") or pages.stem,
                     "kept_because": "open_licence" if why == "open_licence" or meta.get("kept_because") == "open_licence"
                     else "consent"})
        if why == "consent" and not any(c["github"] == login for c in meta["consents"]):
            meta["consents"].append({"github": login, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        meta["curations"].append({"schema_version": schema_version, "graph_sha256": graph_sha256, "by": login,
                                  "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        self._write(sha, meta)
        return sha

    def mine(self, login: str) -> list[dict]:
        """The sources kept because this login agreed: what a contributor sees and can withdraw."""
        return [{**{k: m.get(k) for k in ("sha256", "doi", "title")}, "pdf": self.pdf(m["sha256"]) is not None}
                for m in self.entries()
                if any(c["github"] == login for c in m.get("consents") or [])]

    def forget(self, sha: str, login: str) -> bool:
        """Withdraw a login's agreement; the source (PDF and texts) goes when it is kept by agreement and none is left."""
        if not self.on or not (self.root / sha).is_dir() or "/" in sha or ".." in sha:
            return False
        meta = self._meta(sha)
        left = [c for c in meta.get("consents") or [] if c["github"] != login]
        if len(left) == len(meta.get("consents") or []):
            return False
        meta["consents"] = left
        if meta.get("kept_because") == "consent" and not left:
            shutil.rmtree(self.root / sha)
        else:
            self._write(sha, meta)
        return True

    def entries(self) -> list[dict]:
        if not self.on or not self.root.is_dir():
            return []
        return [self._meta(p.name) for p in sorted(self.root.iterdir()) if (p / "meta.json").is_file()]

    def pages(self, sha: str, into: Path) -> Path:
        """A copy of a kept source's page texts under its own name (``<slug>.txt``) in ``into``, to curate it from."""
        into.mkdir(parents=True, exist_ok=True)
        out = into / f"{self._meta(sha).get('slug') or 'source'}.txt"
        shutil.copyfile(self.root / sha / "pages.txt", out)
        return out

    def pdf(self, sha: str) -> Path | None:
        """The kept PDF of a source, or None (a source kept from its texts alone)."""
        p = self.root / sha / "paper.pdf" if self.on else None
        return p if p is not None and p.is_file() else None

    def stale(self, version: str) -> list[dict]:
        """The kept sources whose latest curation is under another schema version than ``version``."""
        return [m for m in self.entries() if (m.get("curations") or [{}])[-1].get("schema_version") != version]

    def record(self, sha: str, version: str, graph: dict, by: str) -> Path:
        """Keep a curation made from the kept text: ``graphs/<version>.json``, listed in meta.json."""
        out = self.root / sha / "graphs" / f"{version}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(graph, ensure_ascii=False, sort_keys=True)
        out.write_text(data, encoding="utf-8")
        meta = self._meta(sha)
        meta.setdefault("curations", []).append({"schema_version": version, "by": by,
                                                 "graph_sha256": hashlib.sha256(data.encode()).hexdigest(),
                                                 "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        self._write(sha, meta)
        return out
