"""Agent-facing toolkit: one small, safe, vendor-neutral tool surface over scale-graph documents.

The same tools are reachable in every way an agentic system can call software, all from
one install and none tied to a model provider:

* command line — ``scale call <tool> '<json>'`` (JSON in, JSON out; see ``cli.py``);
* HTTP — ``scale serve`` with an OpenAPI description (see ``http_server.py``);
* MCP — ``scale mcp`` over stdio (see ``mcp_server.py``);
* Python — ``ScaleToolkit().call(name, arguments)``.

Tool definitions are plain JSON Schema (``schemas()``), the common denominator of
function-calling formats; ``openapi()`` describes the HTTP form.

Design rules
------------
* **Zero configuration.** Documents live in a working directory (``$SCALE_WORKSPACE`` or
  ``~/.scale/workspace``), created when a tool first writes there. There is no lock and nothing to
  upgrade: a scale-graph document pins its schema version itself (``graph.schema_version``) and is
  read under that version; ``scale_migrate`` moves it to a newer one when asked.
* **Agents propose, people decide.** Approving proposals, applying them, building releases and
  filing GitHub issues are deliberately *not* agent tools; they stay in the CLI for humans
  (``status.human_only_actions`` lists the commands).
* **Writes stay inside the working directory.** Only ``scale_example`` and ``scale_migrate`` (with
  ``save_as``) write, and only a sanitized file name there.
* **Results are data.** Every tool returns JSON-serializable dicts; failures return
  ``{"error": ...}`` rather than raising, so an agent can read and recover.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Callable

from . import __version__, layout
from .util import ScaleError, find_repo_root, load_doc, load_yaml, write_canonical

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")


def default_workspace() -> Path:
    return Path(os.environ.get("SCALE_WORKSPACE") or Path.home() / ".scale" / "workspace").expanduser().resolve()


# ---------------------------------------------------------------- tool definitions (JSON Schema)

_DOC = {
    "document": {"type": "object", "description": "A scale-graph document (node-link JSON), inline."},
    "path": {"type": "string", "description": "Or a document file: a path relative to the working directory, or absolute."},
}
_DOMAIN = {"domain": {"type": "string", "description": "Whose schema to use: catalysis (the catalysis domain, "
                                                       "domain/), or core for the science kernel alone. "
                                                       "Default: catalysis."}}

TOOLS: list[dict] = [
    {
        "name": "scale_status",
        "description": "Start here. Returns the tool version, the latest release, the schema version (one for the science "
                       "kernel and the catalysis domain together), the domain, the working directory and the documents in "
                       "it, the skills, which capabilities are functioning, mocked or planned, and the actions only a "
                       "person takes.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "scale_domains",
        "description": "The catalysis domain (domain/): its status, the schema version (and any "
                       "frozen versions), checklist, maintainers, example query plans (its competency questions) "
                       "and public examples.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "scale_describe",
        "description": "Describe labels and edge types (properties, types, descriptions) and, with domain catalysis, "
                       "the catalysis checklist for them: what a record must and should report. With no names, an "
                       "overview of every label and edge type. Use before writing records or query plans.",
        "input_schema": {"type": "object", "properties": {
            "names": {"type": "array", "items": {"type": "string"}, "description": "Labels or edge types, e.g. CatalyticTest."},
            **_DOMAIN,
            "schema_version": {"type": "string", "description": "A frozen schema version to describe (default: current)."}}},
    },
    {
        "name": "scale_template",
        "description": "A minimal valid scale-graph document for the catalysis domain (or, with domain core, the "
                       "science kernel alone): the graph header with stewardship, a Source, one evidenced record and "
                       "its REPORTED_IN link, with notes on what to fill in.",
        "input_schema": {"type": "object", "properties": {**_DOMAIN}},
    },
    {
        "name": "scale_validate",
        "description": "Validate a scale-graph document under the schema version it pins. Returns errors (invalid), "
                       "warnings, and conformance to the catalysis checklist it follows (must items missing make a "
                       "record non-conformant, not invalid). Writes nothing.",
        "input_schema": {"type": "object", "properties": {**_DOC, **_DOMAIN,
            "source_texts": {"type": "object", "additionalProperties": {"type": "string"},
                             "description": "Map source id -> full source text, to check quotes verbatim."}}},
    },
    {
        "name": "scale_query",
        "description": "Run a scale-graph query plan (match, steps, where, return, evidence, order_by, limit) over a "
                       "document. Returns rows with the values as reported and their evidence (each item with its "
                       "source's kind, peer review and publication status, and whether it is second-hand), records left "
                       "out and why, a coverage block (candidates, each stage's rows in and out, everything left out by "
                       "reason, the values compared, whether the plan narrows nothing) and the kind of answer: answered, "
                       "no_matching_record, missing_context or schema_gap. A numeric filter (eq, ne and in with numbers too) "
                       "states its unit and compares only values in that unit (spelled the same, case included: mPa is "
                       "not MPa) and on the basis it states; nothing is converted. 'not stated' is no unit (the "
                       "placeholder for a number printed without one): never filter in it. Absences are answers; never "
                       "fill them with typical values.",
        "input_schema": {"type": "object", "required": ["plan"], "properties": {
            "plan": {"type": "object", "description": "Query plan; see the query-graph skill and example_plans in scale_domains."},
            **_DOC, **_DOMAIN,
            "format": {"type": "string", "enum": ["json", "markdown"], "description": "markdown adds a readable rendering."}}},
    },
    {
        "name": "scale_search",
        "description": "Search a document's evidence by words and meaning (its evidence index: the one saved beside it "
                       "by `scale graph index`, or built in memory from the document when none is); hits lead to the records that cite each passage. The "
                       "result's access says where the hits may go: the whole document's, as scale_query's.",
        "input_schema": {"type": "object", "required": ["path", "query"], "properties": {
            "path": _DOC["path"], "query": {"type": "string"}, "k": {"type": "integer", "default": 10},
            "mode": {"type": "string", "enum": ["hybrid", "vector", "keyword", "rrf"], "default": "hybrid"},
            "published_before": {"type": "string", "description": "Only evidence from sources published before this year."}}},
    },
    {
        "name": "scale_migrate",
        "description": "Move a document along the schema's version steps to a newer schema version (default: the "
                       "current one); record ids are kept. Returns the migrated document, the steps and rules "
                       "applied, and its validation. With save_as, writes it into the working directory.",
        "input_schema": {"type": "object", "properties": {**_DOC, **_DOMAIN,
            "to_version": {"type": "string", "description": "Target schema version (default: the current one)."},
            "save_as": {"type": "string", "description": "File name in the working directory (letters, digits, . _ -)."}}},
    },
    {
        "name": "scale_example",
        "description": "List the public synthetic example documents, or copy one into the working directory so it "
                       "can be validated and queried at once.",
        "input_schema": {"type": "object", "properties": {
            "name": {"type": "string", "description": "An example's name from the list (default: list them)."}}},
    },
    {
        "name": "scale_skills",
        "description": "List the SCALE skills (versioned procedures: curate-source, query-graph, evolve-schema, "
                       "triage-feedback, scan-conflicts, map-coverage, curate-dataset, export-graph), or return one "
                       "skill's text, or one of the reference files its text points to (e.g. curate-source's "
                       "references/recipes.md).",
        "input_schema": {"type": "object", "properties": {
            "name": {"type": "string", "description": "A skill's name (default: list them)."},
            "reference": {"type": "string", "description": "A file of the skill's folder as the skill lists it in "
                                                           "`references` (e.g. references/recipes.md)."}}},
    },
]

HUMAN_ONLY = {
    "approve a pull request (one reviewer other than the author approves every change, once a reviewer besides the "
    "owner has joined; governance/GOVERNANCE.md, Bootstrap, until then)": "gh pr review NUMBER --approve",
    "merge an approved pull request (a merged proposal is then applied with the apply-proposals workflow)":
        "gh pr merge NUMBER --squash",
    "apply a merged proposal (manual workflow; it needs a token configured for this repository)":
        "gh workflow run apply-proposals.yml --repo hlxin/scale -f proposal=<id> -f pr=<number>",
    "fill a reviewer seat (replace a placeholder)": "edit governance/review-policy.yaml, core/CORE.yaml, "
                                                    "domain/DOMAIN.yaml and .github/CODEOWNERS in a pull request",
    "move a data repository's documents to the latest schema": "scale kg update --data DIR",
    "build a release": "scale release build vX.Y.Z --proposal ID  (one --proposal per proposal applied since the last release)",
    "publish a release to PyPI (once the trusted publisher is configured)": "gh release create vX.Y.Z --repo hlxin/scale",
    "register the PyPI trusted publisher for scale-schema": "pypi.org, project scale-schema: add the GitHub publisher "
                                                            "hlxin/scale, workflow publish.yml, environment pypi "
                                                            "(governance/repository-settings.md)",
    "apply the repository settings (ruleset, environments, secrets)": "governance/repository-settings.md (gh api commands)",
    "file a GitHub issue": "scale gap issue GAP-....json --submit",
}


def template(domain: str | None, version: str) -> dict:
    """A minimal valid scale-graph document: header and stewardship, the institution and project the
    stewardship names, a Source, one evidenced Claim (a kernel label, valid with or without the catalysis checklist) and its
    REPORTED_IN link."""
    ev = {"source": "ex:source/1", "locator": "Results, paragraph 2", "kind": "text",
          "quote": "a short verbatim excerpt that states the claim"}
    return {
        "directed": True, "multigraph": True,
        "graph": {"schema": "scale-graph", "schema_version": version, "graph_id": "ex:my-graph",
                  "title": "State what was curated and what was left out (e.g. main text only; SI not examined).",
                  "data_status": "research_data", **({"follows_domains": [domain]} if domain else {}),
                  "stewardship": {"contributed_by": ["ex:org/my-lab"], "project": "ex:project/my-project",
                                  "access": "public"}},
        "nodes": [
            {"id": "ex:org/my-lab", "label": "Institution", "props": {"name": "My laboratory", "origin": "curated"}},
            {"id": "ex:project/my-project", "label": "Project", "props": {"name": "My project", "origin": "curated"}},
            {"id": "ex:source/1", "label": "Source",
             "props": {"name": "Author et al. 2025", "kind": "article", "title": "The article's title", "year": 2025,
                       "doi": "10.xxxx/xxxx", "origin": "curated"}},
            {"id": "ex:claim/1", "label": "Claim",
             "props": {"name": "The authors' main finding", "statement": "What the source states, in one sentence.",
                       "claim_kind": "finding", "claim_status": "proposed", "origin": "reported", "evidence": [ev]}},
        ],
        "links": [{"id": "ex:claim/1/reported-in/1", "type": "REPORTED_IN", "source": "ex:claim/1", "target": "ex:source/1",
                   "props": {"origin": "derived", "locators": ["Results, paragraph 2"]}}],
    }


class ScaleToolkit:
    """SCALE tools for an agent. ``call(name, arguments)`` never raises; errors come back as data."""

    def __init__(self, workspace: str | os.PathLike | None = None, repo: str | os.PathLike | None = None):
        self.repo = Path(repo).resolve() if repo else find_repo_root()
        self.workspace = Path(workspace).expanduser().resolve() if workspace else default_workspace()
        self._specs: dict[str, dict] = {}
        self._loaded: dict[str, dict] = {}      # documents by path, kept while their file is unchanged (_load)
        self._handlers: dict[str, Callable[..., dict]] = {t["name"]: getattr(self, "_" + t["name"]) for t in TOOLS}

    # ------------------------------------------------------------ tool schemas
    @staticmethod
    def schemas() -> list[dict]:
        """Neutral tool definitions: ``{name, description, parameters}`` with JSON Schema parameters."""
        return [{"name": t["name"], "description": t["description"], "parameters": t["input_schema"]} for t in TOOLS]

    @staticmethod
    def openapi(server_url: str = "http://127.0.0.1:8765") -> dict:
        """OpenAPI 3.1 description of the HTTP form (``scale serve``): ``POST /tools/{name}``."""
        paths = {"/tools": {"get": {"operationId": "list_tools", "summary": "List tool definitions",
                                    "responses": {"200": {"description": "Tool definitions (JSON Schema)."}}}}}
        for t in TOOLS:
            paths[f"/tools/{t['name']}"] = {"post": {
                "operationId": t["name"], "summary": t["description"].split(". ")[0],
                "description": t["description"],
                "requestBody": {"required": False, "content": {"application/json": {"schema": t["input_schema"]}}},
                "responses": {"200": {"description": "Tool result (JSON). Errors are returned as {\"error\": ...}.",
                                      "content": {"application/json": {"schema": {"type": "object"}}}}}}}
        return {"openapi": "3.1.0",
                "info": {"title": "SCALE tools", "version": __version__,
                         "description": "SCALE — Shared Concepts, Attributes, and Links with Evidence — agent tools."},
                "servers": [{"url": server_url}], "paths": paths}

    def call(self, name: str, arguments: dict | None = None) -> dict:
        name = name if name.startswith("scale_") else f"scale_{name}"
        handler = self._handlers.get(name)
        if handler is None:
            return {"error": f"unknown tool {name!r}", "available": list(self._handlers)}
        try:
            return handler(**(arguments or {}))
        except TypeError as exc:
            return {"error": f"bad arguments for {name}: {exc}"}
        except ScaleError as exc:
            return {"error": str(exc)}
        except FileNotFoundError as exc:
            return {"error": f"file not found: {exc.filename}"}

    # ------------------------------------------------------------ helpers
    def _path(self, path: str) -> Path:
        """A document path: absolute as given, else relative to the working directory."""
        p = Path(path).expanduser()
        return p if p.is_absolute() else self.workspace / p

    def _doc(self, document: dict | None, path: str | None) -> dict:
        if document is not None:
            if not isinstance(document, dict):
                raise ScaleError("document must be a JSON object (a scale-graph document)")
            return document
        if path:
            return load_doc(self._path(path))
        raise ScaleError("give a document (inline) or a path")

    def _load(self, path: str) -> dict:
        """The document at ``path`` with what its queries reuse: ``{doc, graphs (a query Graph per schema), index}``,
        kept while the file's modification time and size are unchanged (a long-running server loads a large graph and
        indexes it once). The tools never change a loaded document; a few recent documents are kept."""
        p = self._path(path).resolve()
        st = p.stat()
        key = (st.st_mtime_ns, st.st_size)
        hit = self._loaded.get(str(p))
        if hit is None or hit["key"] != key:
            hit = {"key": key, "doc": load_doc(p), "graphs": {}, "index": None, "index_key": None}
            self._loaded.pop(str(p), None)
            self._loaded[str(p)] = hit
            while len(self._loaded) > 4:
                self._loaded.pop(next(iter(self._loaded)))
        return hit

    def _manifest(self, domain: str | None, doc: dict | None = None) -> Path:
        """The schema manifest: the catalysis domain's (by its name, or by default), or the kernel alone for ``core``."""
        from . import pgraph
        if domain == "core":
            return self.repo / layout.KERNEL_ONLY_MANIFEST
        if domain:
            mans = layout.graph_manifests(self.repo, experimental=True)
            if domain not in mans:
                raise ScaleError(f"no scale-graph schema for {domain!r}; use {', '.join(mans)} (or core)")
            return mans[domain]
        return pgraph.spec_path(self.repo, None, doc)

    def _spec(self, manifest: Path, version: str | None = None, doc: dict | None = None) -> dict:
        from . import pgraph
        p = pgraph.pinned(manifest, version, doc)
        if str(p) not in self._specs:
            self._specs[str(p)] = pgraph.load_spec(p)
        return self._specs[str(p)]

    def _doc_spec(self, doc: dict, domain: str | None) -> dict:
        """The schema a document pins (a version this repository does not hold is an error that says so)."""
        return self._spec(self._manifest(domain, doc), (doc.get("graph") or {}).get("schema_version"), doc)

    def _examples(self) -> dict[str, Path]:
        """The public synthetic examples by name: the kernel's and the catalysis domain's documents whose
        ``data_status`` is ``synthetic_example`` (curated research data is not served here)."""
        out: dict[str, Path] = {}
        for root in layout.example_roots(self.repo):
            for p in sorted(root.rglob("*.json")):
                if layout.is_excluded(p.relative_to(self.repo)):
                    continue
                try:
                    g = load_doc(p).get("graph") or {}
                except Exception:
                    continue
                if g.get("schema") == "scale-graph" and g.get("data_status") == "synthetic_example" \
                        and (g.get("stewardship") or {}).get("access") == "public":    # missing: not public
                    out.setdefault(p.stem, p)
        return out

    def _skills(self) -> dict[str, dict]:
        from .releases import skill_files, skill_folder
        out = {}
        for p in skill_files(self.repo):
            text = p.read_text(encoding="utf-8")
            fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
            import yaml
            meta = (yaml.safe_load(fm.group(1)) if fm else {}) or {}
            refs = {f.relative_to(p.parent).as_posix(): f for f in skill_folder(p)[1:]}
            out[meta.get("name", p.parent.name)] = {"version": str(meta.get("version")), "description": meta.get("description"),
                                                    "path": p.relative_to(self.repo).as_posix(), "text": text,
                                                    "references": refs}
        return out

    # ------------------------------------------------------------ tools
    def _scale_status(self) -> dict:
        from .releases import list_releases
        from .updates import tool_status
        inventory: dict[str, list] = {}
        inv_path = self.repo / layout.IMPLEMENTATION_STATUS
        if inv_path.exists():
            for c in load_yaml(inv_path)["capabilities"]:
                inventory.setdefault(c["status"], []).append(c["name"])
        rels = list_releases(self.repo)
        docs = sorted(p.name for p in self.workspace.glob("*.json")) if self.workspace.is_dir() else []
        mans = layout.graph_manifests(self.repo)
        version = sorted({str(load_yaml(m).get("version")) for m in mans.values()})
        return {
            "scale_version": __version__,
            "latest_release": rels[-1] if rels else None,
            "schema_version": version[0] if len(version) == 1 else version,
            "kernel": {"file": layout.KERNEL, "schema_version": version[0] if len(version) == 1 else version},
            "domains": self._scale_domains()["domains"],
            "workspace": str(self.workspace), "documents": docs,
            "skills": {k: v["version"] for k, v in self._skills().items()},
            "capabilities": inventory,
            "human_only_actions": HUMAN_ONLY,
            "updates": tool_status(self.workspace / ".cache" if self.workspace.is_dir() else None),
            "next_steps": ["scale_skills curate-source (curating) or query-graph (asking)",
                           "scale_describe <Label> --domain before writing records or plans",
                           "scale_template for a valid starting document; scale_validate after every edit",
                           "scale_example to try scale_query on a public example"],
        }

    def _scale_domains(self) -> dict:
        from .domains import list_domains
        mans = layout.graph_manifests(self.repo, experimental=True)
        rows = []
        for r in list_domains(self.repo):
            man = mans.get(r["domain"])
            g = load_yaml(man) if man and man.is_file() else {}
            frozen = sorted(p.stem.removeprefix("scale-graph-") for p in layout.frozen_graph_dir(man).glob("scale-graph-*.yaml")) \
                if man else []
            plans = {}
            for q in sorted((self.repo / r["path"] / layout.DOMAIN_COMPETENCY).glob("*.yaml")):
                cq = load_yaml(q) or {}
                if isinstance(cq, dict) and cq.get("plan"):
                    plans[str(cq.get("id"))] = {"question": cq.get("question"), "documents": cq.get("documents"),
                                                "plan": cq["plan"]}
            rows.append({**{k: r[k] for k in ("domain", "title", "status", "version", "team", "stewards")},
                         "schema": {"manifest": man.relative_to(self.repo).as_posix(), "version": g.get("version"),
                                    "frozen_versions": frozen} if man else None,
                         "example_plans": plans})
        return {"domains": rows, "examples": sorted(self._examples())}

    def _scale_describe(self, names: list[str] | None = None, domain: str | None = None,
                        schema_version: str | None = None) -> dict:
        from . import pgraph
        hint = {"graph": {"follows_domains": [domain]}} if domain and domain != "core" else None
        spec = self._spec(self._manifest(domain, hint), schema_version)
        profile = domain if domain and domain in (spec.get("profiles") or {}) else None
        if names:
            return pgraph.describe(spec, list(names), profile)
        first = lambda t: (t or "").strip().split("\n")[0]   # noqa: E731
        return {"schema_version": spec["version"], "domain": domain,
                "labels": {n: {"is_a": d.get("ancestors") or [], "description": first(d.get("description"))}
                           for n, d in sorted(spec["nodes"].items())},
                "edges": {n: {"from": d.get("from"), "to": d.get("to"), "description": first(d.get("description"))}
                          for n, d in sorted(spec["edges"].items())},
                "checklists": sorted(spec.get("profiles") or {}),
                "value_fields": sorted(spec["value"]["fields"]), "evidence_fields": sorted(spec["evidence"]["fields"]),
                "next": "scale_describe with names (and domain) for properties and the checklist items"}

    def _scale_template(self, domain: str | None = None) -> dict:
        from . import pgraph
        man = self._manifest(domain)
        spec = self._spec(man)
        name = None if domain == "core" else (domain or next((n for n, m in layout.graph_manifests(self.repo).items()
                                                               if m == man), None))
        doc = template(name if name in (spec.get("profiles") or {}) else None, spec["version"])
        rep = pgraph.validate(doc, spec).as_dict()
        return {"document": doc, "valid": rep["valid"], "schema_version": spec["version"],
                "notes": ["Replace every ex: id with your own prefix (a CURIE: prefix:path); ids are unique across nodes and links.",
                          "Each record that states something from a source carries evidence: source, locator, kind and a short "
                          "verbatim quote; derive REPORTED_IN links from the evidence.",
                          "Record values as {status, value, unit} as reported; declare unknown values with a status "
                          "(not_reported, with missing_reason not_curated if you did not look) instead of filling them in.",
                          "Context the schema cannot express goes in the record's unmodeled list (a gap), never in an "
                          "invented property.",
                          "A research_data graph names its stewardship (contributed_by, project, access).",
                          "access public: a document meant for the repository is public (scale check requires it); project "
                          "data not yet cleared for publication takes access project and stays outside the repository.",
                          "scale_describe <Label> with domain lists the properties and the checklist items to report."]}

    def _scale_validate(self, document: dict | None = None, path: str | None = None, domain: str | None = None,
                        source_texts: dict | None = None) -> dict:
        from . import pgraph
        doc = self._doc(document, path)
        spec = self._doc_spec(doc, domain)
        rep = pgraph.validate(doc, spec, source_texts).as_dict()
        return {"schema_version": spec["version"], **rep}

    def _scale_query(self, plan: dict, document: dict | None = None, path: str | None = None, domain: str | None = None,
                     format: str = "json") -> dict:
        from . import pgraph_query
        if document is None and path:
            hit = self._load(path)
            doc = hit["doc"]
            spec = self._doc_spec(doc, domain)
            g = hit["graphs"].get(id(spec))
            if g is None:
                g = hit["graphs"][id(spec)] = pgraph_query.Graph(doc, spec)
            res = pgraph_query.run(doc, spec, plan, self._index(path, doc, hit) if plan.get("text") else None, g)
        else:
            doc = self._doc(document, path)
            res = pgraph_query.run(doc, self._doc_spec(doc, domain), plan, self._index(path, doc) if plan.get("text") else None)
        if format == "markdown":
            res["markdown"] = pgraph_query.render_markdown(res)
        return res

    def _index(self, path: str | None, doc: dict, hit: dict | None = None):
        """The evidence index beside ``path``, refused unless it is ``doc``'s, or built in memory from ``doc`` when none is
        saved there or the document came inline (:func:`passages.index_for`); kept with a loaded document (``hit``)
        while the saved index files are unchanged."""
        from .passages import Index, evidence_items, graph_sha256, index_for
        if not path:
            return Index.build(evidence_items(doc), graph_sha256=graph_sha256(doc))
        p = self._path(path)
        stem = p.with_name(p.name.removesuffix(".json").removesuffix(".graph") + ".evidence")
        if hit is None:
            return index_for(stem, doc)
        key = tuple((f.stat().st_mtime_ns, f.stat().st_size) if f.exists() else None
                    for f in (Path(f"{stem}{x}") for x in (".jsonl", ".i8", ".terms")))
        if hit["index"] is None or hit["index_key"] != key:
            hit["index"], hit["index_key"] = index_for(stem, doc), key
        return hit["index"]

    def _scale_search(self, path: str, query: str, k: int = 10, mode: str = "hybrid",
                      published_before: str | None = None) -> dict:
        from . import pgraph
        from .pgraph_query import document_access
        hit = self._load(path)
        doc = hit["doc"]
        ix = self._index(path, doc, hit)
        nodes = {n["id"]: n for n in doc["nodes"]}
        links = {e["id"]: e for e in doc["links"]}
        years = {n["id"]: n["props"].get("year") for n in doc["nodes"] if n["label"] == "Source"}
        before = int(str(published_before)[:4]) if published_before else None
        where = (lambda it: years.get(it.get("source")) is not None and years[it["source"]] < before) if before else None
        hits = ix.search(query, k=k, mode=mode, where=where)
        for h in hits:
            rec = nodes.get(h["record"]) or links.get(h["record"])
            h["record_name"] = (rec or {}).get("props", {}).get("name") or (rec or {}).get("type")
            h["source_year"] = years.get(h.get("source"))
        # the hits are the document's verbatim quotes: they go only where the whole document may go (scale_query's access)
        return {"query": query, "mode": mode, "embedder": ix.embedder_id, "hits": hits,
                "access": document_access(doc, pgraph.embargo_today())}

    def _scale_migrate(self, document: dict | None = None, path: str | None = None, domain: str | None = None,
                       to_version: str | None = None, save_as: str | None = None) -> dict:
        from . import pgraph
        from .pgraph_migrate import STEPS, raise_version
        doc = self._doc(document, path)
        man = self._manifest(domain, doc)
        target = to_version or load_yaml(man).get("version")
        spec = self._spec(man, target)
        have = (doc.get("graph") or {}).get("schema_version")
        if have == target:
            return {"error": f"the document is already at scale-graph {have}"}
        if have not in STEPS:
            return {"error": f"the document pins scale-graph {have}; migrations run along the steps {sorted(STEPS) or '(none yet)'}"}
        new, rep = raise_version(doc, target, spec)
        rep["validation"] = pgraph.validate(new, spec).as_dict()["summary"]
        written = None
        if save_as:
            if not _NAME.match(save_as):
                return {"error": "save_as must be 1-80 characters: letters, digits, '.', '_' or '-'"}
            target_path = self.workspace / (save_as if save_as.endswith(".json") else f"{save_as}.json")
            write_canonical(target_path, new)
            written = str(target_path)
        return {"from_version": have, "to_version": target, **rep, "written": written, "document": new}

    def _scale_example(self, name: str | None = None) -> dict:
        ex = self._examples()
        if not name:
            return {"examples": [{"name": n, "path": p.relative_to(self.repo).as_posix(),
                                  "title": (load_doc(p).get("graph") or {}).get("title")} for n, p in ex.items()]}
        if name not in ex:
            return {"error": f"no public example {name!r}", "available": sorted(ex)}
        self.workspace.mkdir(parents=True, exist_ok=True)
        target = self.workspace / f"{name}.json"
        shutil.copy2(ex[name], target)
        return {"written": str(target), "path": target.name,
                "try": [{"tool": "scale_validate", "arguments": {"path": target.name}},
                        {"tool": "scale_query", "arguments": {"path": target.name,
                                                               "plan": {"match": {"label": "Source", "as": "source"},
                                                                        "return": ["source.name", "source.year"]}}}]}

    def _scale_skills(self, name: str | None = None, reference: str | None = None) -> dict:
        skills = self._skills()
        if not name:
            return {"skills": [{"name": n, "version": s["version"], "description": s["description"],
                                "references": sorted(s["references"])} for n, s in skills.items()]}
        if name not in skills:
            return {"error": f"no skill {name!r}", "available": sorted(skills)}
        s = skills[name]
        if reference is not None:              # only a file the skill's folder holds, named as listed
            if reference not in s["references"]:
                return {"error": f"skill {name!r} has no reference {reference!r}", "available": sorted(s["references"])}
            return {"name": name, "version": s["version"], "reference": reference,
                    "text": s["references"][reference].read_text(encoding="utf-8")}
        return {"name": name, "version": s["version"], "text": s["text"], "references": sorted(s["references"])}


def tools(**kwargs) -> ScaleToolkit:
    """Shorthand: ``scale.api.tools()`` returns a ready toolkit."""
    return ScaleToolkit(**kwargs)
