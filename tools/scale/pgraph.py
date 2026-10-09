"""SCALE graph schema (scale-graph): labeled property graphs in node-link JSON.

A document is ``{"directed", "multigraph", "graph", "nodes", "links"}``; a node is
``{"id", "label", "props"}`` and a link ``{"id", "source", "target", "type", "props"}``. The
catalysis schema (``domain/graph/scale-graph.yaml``: the science kernel plus the catalysis domain's
files) declares node labels, edge types with their endpoint labels, and a typed property set for
each, plus the value object and the evidence item. "scale-graph" names the format and schema family
that documents pin (``schema: scale-graph``, ``schema_version``); a domain's schema version is the
version of its manifest.

This module loads the schema, validates documents against it (errors for malformed records,
warnings for advisory issues), checks evidence quotes verbatim against supplied source texts,
summarizes a graph, and flattens it for property-graph databases that accept only primitive
property values.

The schema has one version for the kernel and the catalysis domain together: the manifest's ``version``,
numbered from 0.1.0. A version number names a schema only within this repository's numbering, so a version is
identified by its **spec document** (:func:`spec_document`, written by ``scale graph spec``): the assembled
schema as canonical JSON, without where or in what state this repository holds it, so a version has one
digest (:func:`spec_sha256`) whether it is the head or frozen. A reader binds a schema by that digest
(:func:`identify`): a document pinning a version this repository does not hold, or a version and digest that
are not this repository's, is reported as such (README.md, "Schema versions"); nothing is guessed about it.
"""

from __future__ import annotations

import calendar
import copy
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import layout
from .util import ScaleError, dump_canonical, load_yaml, match_text

ID = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:\S+$")
KEY = re.compile(r"^([a-z][a-z0-9_]*|pH)$")   # pH: the established-symbol exception (docs/style.md)
NO_EVIDENCE_NEEDED = {"Source", "Dataset", "Person", "Institution", "Software", "Project"}
# Plausibility advisories (warnings, never errors: literature is curated as reported). A percent-valued
# selectivity, conversion, yield or balance above 100 %, and selectivities of one record to distinct products, on one
# basis and in one unit spelling, summing above 100 % by more than the rounding of the printed numbers.
PERCENT_NAME = re.compile(r"(?:^|_)(?:selectivity|selectivities|conversion|yield|balance)(?:_|$)")
SELECTIVITY_NAME = re.compile(r"(?:^|_)selectivit(?:y|ies)(?:_|$)")
PERCENT_UNIT = re.compile(r"^\s*(?:(?:mol|mole|molar|wt|mass|vol|c|carbon|atom|at)\s*\.?\s*-?\s*)?(?:%|percent|per\s*cent)"
                          r"(?:\s*\((?:mol|mole|molar|wt|mass|vol|c|carbon|atom|at)\.?\))?\s*$", re.I)
DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")   # ISO 8601 at the source's precision: YYYY, YYYY-MM, YYYY-MM-DD
DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$")
OPENNESS = ["public", "consortium", "project", "institution"]
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# the stewardship keys that say who may see a record (the others, licence, note and curated_by, do not)
AUDIENCE_KEYS = ("access", "project", "contributed_by", "embargo_until", "access_after_embargo")
# kernel structures (beyond the value object, evidence, record reference and stewardship) that a property may
# name as its type: a top-level block with fields and required
STRUCTURES = ("status_check",)


def follows(doc: dict | None) -> set[str]:
    """The checklists a document follows (the graph's ``follows_domains`` and its nodes' own): a domain's
    name (``catalysis``, or ``catalysis@<version>``)."""
    doc = doc or {}
    names = list((doc.get("graph") or {}).get("follows_domains") or [])
    for n in doc.get("nodes") or []:
        names += ((n or {}).get("props") or {}).get("follows_domains") or []
    return {str(x).partition("@")[0] for x in names}            # name or name@version


def spec_path(repo: Path, explicit: str | None = None, doc: dict | None = None) -> Path:
    """The schema manifest to use: an explicit one as given; else the catalysis domain's
    ``domain/graph/scale-graph.yaml`` (the one domain for now; there is no repository-wide schema).
    ``doc`` is accepted for the callers that pass the document; the one manifest needs no choosing."""
    if explicit:
        return Path(explicit)
    mans = layout.graph_manifests(repo)
    if len(mans) == 1:
        return next(iter(mans.values()))
    raise ScaleError(f"no scale-graph schema found: no released domain declares graph.manifest in "
                     f"{layout.DOMAIN_DECLARATION} (pass --spec)")


def spec_for(repo: Path, version: str | None, explicit: str | None = None, doc: dict | None = None) -> Path:
    """The schema a document pins: the domain's current manifest if its version matches, else the
    frozen ``frozen/scale-graph-<version>.yaml`` beside it; the current manifest when the document pins
    nothing. An explicit spec is used as given."""
    main = spec_path(repo, explicit, doc)
    return main if explicit else pinned(main, version, doc)


def pinned(manifest: Path, version: str | None, doc: dict | None = None) -> Path:
    """A domain's manifest at ``version``: the manifest itself when it is at that version (or none is
    pinned), else its frozen copy ``frozen/scale-graph-<version>.yaml``. The error for a version with neither says
    what the ``doc`` pinning it may be (:func:`_unknown`)."""
    if not version or load_yaml(manifest).get("version") == version:
        return Path(manifest)
    frozen = frozen_spec(manifest, version)
    if frozen.exists():
        return frozen
    raise ScaleError(f"document pins scale-graph {version}, which is not a version this repository holds (no "
                     f"{frozen.name} in {frozen.parent}){_unknown(manifest, version, doc)}")


def galaxy_bundle_graph(doc: Any) -> bool:
    """Whether ``doc`` is the graph of a GALAXY bundle (its ``kg/graph.json``, as ``scale graph export --to galaxy``
    writes it): a header naming the bundle (``bundle_id``) and the bundle's own schema (``schema_id``), whose
    ``schema_version`` is the bundle's version, not a scale-graph version."""
    g = doc.get("graph") if isinstance(doc, dict) else None
    return isinstance(g, dict) and isinstance(g.get("bundle_id"), str) and isinstance(g.get("schema_id"), str)


def _unknown(manifest: Path, version: str, doc: dict | None = None) -> str:
    """What a version this repository does not hold may be: the graph of a GALAXY bundle, whose ``schema_version``
    is the bundle's own version (:func:`galaxy_bundle_graph`); a version newer than the head (the tools are older
    than the document, or it is a proposal's candidate); else a version of another numbering, which only its spec
    digest could tell. Only this suffix of the error says so; the error and the validity are those of a version the
    tools do not hold."""
    from .versions import parse_version
    if galaxy_bundle_graph(doc):
        return (f"; the document is the graph of a GALAXY bundle (its header names a bundle_id and a schema_id), whose "
                f"schema_version {version} is the bundle's own version, not a scale-graph version; validate the "
                "scale-graph it was exported from (the bundle's bundle.json names that schema in scale_header)")
    held = sorted(public_versions(manifest), key=parse_version)
    head = str(load_yaml(manifest).get("version"))
    try:
        newer = parse_version(str(version)) > parse_version(head)
    except ScaleError:                       # not a semantic version: nothing more to say
        return f"; it holds {', '.join(held)}"
    if newer:
        return (f"; {version} is newer than this schema's head {head} (update the tools, or pass --spec with that "
                "version's manifest, e.g. a proposal's candidate)")
    return (f"; it holds {', '.join(held)}. A version is identified by its spec digest (`scale graph spec`): a document "
            "written under another numbering is curated again, not read under a version of the same number")


def kernel_only_spec(repo: Path, version: str | None) -> dict:
    """The science kernel alone at a schema version, for documents that use only kernel labels and edges (the core's
    examples): the kernel-only example manifest (``core/examples/science-kernel-only.yaml``) at the head version (or
    when none is pinned), else the kernel frozen with that version (``core/graph/frozen/kernel-<version>.yaml``)."""
    from .pgraph_schema import assemble_manifest
    ko = Path(repo) / layout.KERNEL_ONLY_MANIFEST
    if not version or str(load_yaml(ko).get("version")) == str(version):
        return load_spec(ko)
    fk = Path(repo) / layout.KERNEL_FROZEN / f"kernel-{version}.yaml"
    if not fk.is_file():
        raise ScaleError(f"document pins scale-graph {version}; neither {layout.KERNEL_ONLY_MANIFEST} (at "
                         f"{load_yaml(ko).get('version')}) nor a frozen {fk.name} in {layout.KERNEL_FROZEN}/ is that version")
    return assemble_manifest({"schema": "scale-graph", "version": str(version), "status": "frozen", "kernel": fk.name,
                              "domains": []}, fk.parent)


def frozen_spec(manifest: Path, version: str) -> Path:
    """Where the frozen copy of version ``version`` of a domain's schema lives (whether or not it exists)."""
    return layout.frozen_graph_dir(manifest) / f"scale-graph-{version}.yaml"


def load_spec(path: Path) -> dict:
    """A schema file as written, or a manifest (a domain's scale-graph.yaml) assembled from its parts."""
    spec = load_yaml(path)
    if spec.get("schema") != "scale-graph":
        raise ScaleError(f"{path} is not a scale-graph schema")
    from .pgraph_schema import assemble, is_manifest
    return assemble(Path(path)) if is_manifest(spec) else spec


# ------------------------------------------------------------------ spec documents: one digest per version
# the numbering a spec document belongs to: this repository's (github.com/hlxin/scale), counted from 0.1.0 on
# 2026-10-08. Earlier repositories numbered other schemas with the same numbers; the digest tells them apart
SPEC_LINEAGE = "scale"
# where and in what state this repository holds a version (and the extension-prefix registry, which is
# repository state): left out of the spec document, so that a version's digest is the same as the head and frozen
SPEC_LOCAL_KEYS = ("status", "extension_prefixes")
SPEC_PART_INDEXES = ("modules", "domains", "profiles")      # their entries name the part's file (path): left out


def spec_versions(manifest: Path) -> list[tuple[str, Path]]:
    """Every version of a domain's schema this repository holds, oldest first: (version, the manifest or its
    frozen copy). The head comes last."""
    from .versions import parse_version
    frozen = [(m.stem.removeprefix("scale-graph-"), m) for m in layout.frozen_graph_dir(manifest).glob("scale-graph-*.yaml")]
    head = str(load_yaml(manifest).get("version"))
    return sorted(frozen, key=lambda x: parse_version(x[0])) + [(head, Path(manifest))]


def public_versions(manifest: Path) -> set[str]:
    """The scale-graph versions of a domain's schema in this repository (the head and its frozen copies)."""
    return {v for v, _ in spec_versions(manifest)}


def spec_document(spec: dict) -> dict:
    """An assembled schema as published: everything a validator reads, with ``lineage: scale``, and
    without the keys that say where and in what state this repository holds the version (``status``, each
    part's ``path``, the extension-prefix registry). A version's spec document is therefore the same whether
    the version is the head or frozen, and in a release (`scale graph spec`, `scale release build`)."""
    out = {k: copy.deepcopy(v) for k, v in spec.items() if k not in SPEC_LOCAL_KEYS}
    for block in SPEC_PART_INDEXES:
        for entry in (out.get(block) or {}).values():
            if isinstance(entry, dict):
                entry.pop("path", None)
    out["lineage"] = SPEC_LINEAGE
    return out


def spec_bytes(spec: dict) -> bytes:
    """The spec document as canonical JSON (UTF-8), the bytes whose sha256 names the version."""
    return dump_canonical(spec_document(spec)).encode("utf-8")


def spec_sha256(spec: dict) -> str:
    return hashlib.sha256(spec_bytes(spec)).hexdigest()


def identify(manifest: Path, version: str | None, sha256: str | None = None) -> dict:
    """Whether a pinned schema version (and, when given, the spec digest it is named with) is one this repository
    holds: ``known`` (the version is the head or frozen here), ``sha256`` (its spec digest here), ``matches`` (the
    digest given equals it; None without one) and a message when it is not. The generic check of a pinned
    version: a number alone names a schema only in this repository's numbering, the digest everywhere."""
    held = dict(spec_versions(manifest))
    if version not in held:
        return {"version": version, "known": False, "sha256": None, "matches": False if sha256 else None,
                "message": f"scale-graph {version} is not a version this repository holds{_unknown(manifest, str(version))}"}
    digest = spec_sha256(load_spec(held[version]))
    ok = None if sha256 is None else sha256 == digest
    return {"version": version, "known": True, "sha256": digest, "matches": ok,
            **({"message": f"scale-graph {version} here has spec digest {digest}, not {sha256}: the schema named is "
                           "another one of the same number"} if ok is False else {})}


@dataclass
class Report:
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    conformance: dict | None = None
    lifecycle: dict | None = None          # source lifecycle counts (lifecycle.summary); None: no notice, no check

    def add(self, severity: str, record: str, message: str) -> None:
        (self.errors if severity == "error" else self.warnings).append({"record": record, "message": message})

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        summary = {"error": len(self.errors), "warning": len(self.warnings)}
        if self.lifecycle:
            summary["source_lifecycle"] = self.lifecycle
        return {"valid": self.ok, "summary": summary,
                "counts": self.counts, "errors": self.errors, "warnings": self.warnings,
                **({"conformance": self.conformance} if self.conformance is not None else {})}


class Validator:
    def __init__(self, spec: dict):
        self.spec = spec
        self.nodes = spec["nodes"]
        self.edges = spec["edges"]
        self.value_fields = spec["value"]["fields"]
        self.evidence_fields = spec["evidence"]["fields"]
        self.stewardship_fields = spec["stewardship"]["fields"]
        self.evidence_required = spec["evidence"].get("required") or ["source", "locator", "kind"]
        self.record_ref = spec.get("record_ref")
        self.link_ids: set[str] = set()

    # ------------------------------------------------------------ typed values
    def check(self, v: Any, d: dict, where: str, rid: str, rep: Report, ids: dict) -> None:
        t = d["type"]
        bad = lambda msg: rep.add("error", rid, f"{where}: {msg}")  # noqa: E731
        if t in ("string", "text"):
            if not isinstance(v, str) or not v:
                bad("expected a non-empty string")
        elif t == "integer":
            if not isinstance(v, int) or isinstance(v, bool):
                bad("expected an integer")
        elif t == "number":
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                bad("expected a number")
        elif t == "boolean":
            if not isinstance(v, bool):
                bad("expected true or false")
        elif t == "enum":
            if v not in d["values"]:
                bad(f"{v!r} is not one of {d['values']}")
        elif t == "ref":
            lab = ids.get(v) if isinstance(v, str) else None      # a list or an object is no id: reported, not raised
            if lab is None:
                bad(f"reference {v!r} does not resolve")
            elif lab not in d["targets"]:
                bad(f"reference {v!r} is a {lab}, expected {d['targets']}")
        elif t == "list":
            if not isinstance(v, list):
                bad("expected a list")
            else:
                for i, x in enumerate(v):
                    self.check(x, d["items"], f"{where}[{i}]", rid, rep, ids)
        elif t == "map":
            if not isinstance(v, dict):
                bad("expected an object")
            else:
                pat = re.compile(d["key_pattern"]) if d.get("key_pattern") else KEY
                for k, x in v.items():
                    if not pat.match(k):
                        bad(f"key {k!r} does not match {pat.pattern}")
                    self.check(x, d["items"], f"{where}.{k}", rid, rep, ids)
        elif t == "value":
            self.check_value(v, where, rid, rep, ids)
        elif t == "evidence":
            self.check_evidence(v, where, rid, rep, ids)
        elif t == "stewardship":
            self.check_stewardship(v, where, rid, rep, ids)
        elif t in STRUCTURES and isinstance(self.spec.get(t), dict) and "fields" in self.spec[t]:
            self.check_structure(v, t, where, rid, rep, ids)
        elif t == "record_ref":
            if not self.record_ref:
                bad("record_ref is not defined by this kernel")
            elif self.check_fields(v, self.record_ref["fields"], where, rid, rep, ids):
                for k in self.record_ref.get("required") or []:
                    if k not in v:
                        bad(f"a record_ref needs {k}")
                r = v.get("record")
                if isinstance(r, str) and r not in ids and r not in self.link_ids:
                    bad(f"record_ref {r!r} does not resolve to a node or link")
                if "path" in v and not str(v["path"]).startswith("/"):
                    bad("record_ref path is a JSON pointer starting with '/'")
        elif t == "date":
            if not isinstance(v, str) or not DATE.match(v):
                bad("expected an ISO date: YYYY, YYYY-MM or YYYY-MM-DD")
        elif t == "datetime":
            if not isinstance(v, str) or not DATETIME.match(v):
                bad("expected an ISO 8601 date-time with a time zone, e.g. 2026-09-27T14:05:00Z")
        else:
            bad(f"unknown property type {t!r} in the schema")

    def check_fields(self, v: Any, fields: dict, where: str, rid: str, rep: Report, ids: dict) -> bool:
        if not isinstance(v, dict):
            rep.add("error", rid, f"{where}: expected an object")
            return False
        for k, x in v.items():
            if k not in fields:
                rep.add("error", rid, f"{where}: unknown field {k!r}")
            else:
                self.check(x, fields[k], f"{where}.{k}", rid, rep, ids)
        return True

    def check_value(self, v: Any, where: str, rid: str, rep: Report, ids: dict) -> None:
        if not self.check_fields(v, self.value_fields, where, rid, rep, ids):
            return
        err = lambda msg: rep.add("error", rid, f"{where}: {msg}")  # noqa: E731
        num = lambda k: isinstance(v.get(k), (int, float)) and not isinstance(v.get(k), bool)  # noqa: E731
        st = v.get("status")
        numeric = "value" in v or "lower" in v or "upper" in v
        reps = [numeric] + [k in v for k in ("text_value", "boolean_value", "ref_value")]
        if st is None:
            err("a value needs a status")
        elif st == "present":
            if sum(reps) != 1:
                err("a present value needs exactly one of: a number (value, or lower and upper), text_value, "
                    "boolean_value, ref_value")
            elif numeric and "unit" not in v:
                err("a present number needs a unit")
        elif st in ("below_detection_limit", "below_quantification_limit"):
            if not ("value" in v and "unit" in v):
                err(f"{st} needs the limit as value, with a unit")
        elif any(reps):
            err(f"status {st} carries no value")
        if "missing_reason" in v and st != "not_reported":
            err("missing_reason goes only with status not_reported")
        if ("lower" in v) != ("upper" in v):
            err("lower and upper come together")
        if "value" in v and ("lower" in v or "upper" in v):
            err("give either value or a lower-upper range, not both")
        if num("lower") and num("upper") and v["lower"] > v["upper"]:
            err("lower exceeds upper")
        if "bound" in v and "value" not in v:
            err("a bound needs a value")
        # uncertainty (science kernel)
        if num("uncertainty") and v["uncertainty"] < 0:
            err("uncertainty must not be negative")
        if ("uncertainty" in v or "interval_lower" in v or "interval_upper" in v) and "uncertainty_kind" in self.value_fields \
                and "uncertainty_kind" not in v:
            err("an uncertainty needs uncertainty_kind")
        if ("interval_lower" in v) != ("interval_upper" in v):
            err("interval_lower and interval_upper come together")
        if num("interval_lower") and num("interval_upper") and v["interval_lower"] > v["interval_upper"]:
            err("interval_lower exceeds interval_upper")
        kind = v.get("uncertainty_kind")
        if kind == "confidence_interval" and "confidence_level" not in v:
            err("a confidence_interval needs confidence_level")
        if kind == "expanded_uncertainty" and not ("coverage_factor" in v or "confidence_level" in v):
            err("an expanded_uncertainty needs coverage_factor or confidence_level")
        if num("confidence_level") and not 0 < v["confidence_level"] < 1:
            err("confidence_level is between 0 and 1")
        if "replicates" in v and isinstance(v["replicates"], int) and v["replicates"] < 1:
            err("replicates is at least 1")
        if v.get("origin") in ("derived", "computed", "fitted") and "produced_by" not in v:
            err(f"a {v.get('origin')} value names the experiment that produced it (produced_by)")

    def check_evidence(self, v: Any, where: str, rid: str, rep: Report, ids: dict) -> None:
        if not self.check_fields(v, self.evidence_fields, where, rid, rep, ids):
            return
        for k in self.evidence_required:
            if k not in v:
                rep.add("error", rid, f"{where}: evidence needs {k}")

    def check_stewardship(self, v: Any, where: str, rid: str, rep: Report, ids: dict) -> None:
        if not self.check_fields(v, self.stewardship_fields, where, rid, rep, ids):
            return
        emb = v.get("access") == "embargoed"
        if emb and not ("embargo_until" in v and "access_after_embargo" in v):
            rep.add("error", rid, f"{where}: embargoed access needs embargo_until and access_after_embargo")
        if not emb and ("embargo_until" in v or "access_after_embargo" in v) and "access" in v:
            rep.add("error", rid, f"{where}: embargo_until and access_after_embargo apply only to embargoed access")

    def check_structure(self, v: Any, t: str, where: str, rid: str, rep: Report, ids: dict) -> None:
        """A kernel structure named as a property type (``status_check``): its fields, typed, and
        the ones it requires."""
        if not self.check_fields(v, self.spec[t]["fields"], where, rid, rep, ids):
            return
        for k in self.spec[t].get("required") or []:
            if k not in v:
                rep.add("error", rid, f"{where}: a {t} needs {k}")

    def check_props(self, props: Any, declared: dict, required: list, rid: str, rep: Report, ids: dict) -> None:
        if not isinstance(props, dict):
            rep.add("error", rid, "props must be an object")
            return
        for k in required:
            if k not in props:
                rep.add("error", rid, f"missing required property {k!r}")
        ext = self.spec.get("extensions")
        for k, v in props.items():
            if k not in declared and ext and k.startswith("_"):
                if not re.match(ext["key_pattern"], k):
                    rep.add("error", rid, f"extension key {k!r} must be _<prefix>_<name> ({ext['key_pattern']})")
                elif k.split("_")[1] not in (self.spec.get("extension_prefixes") or {}):
                    rep.add("warning", rid, f"extension key {k!r} uses an unregistered prefix {k.split('_')[1]!r}")
            elif k not in declared:
                rep.add("error", rid, f"property {k!r} is not declared for this type")
            else:
                self.check(v, declared[k], k, rid, rep, ids)

    # ------------------------------------------------------------ document
    def validate(self, doc: dict, source_texts: dict[str, str] | None = None) -> Report:
        rep = Report()
        if not isinstance(doc, dict) or not isinstance(doc.get("nodes"), list) or not isinstance(doc.get("links"), list):
            rep.add("error", "<document>", "expected a node-link document with nodes and links")
            return rep
        if doc.get("directed") is not True or doc.get("multigraph") is not True:
            rep.add("error", "<document>", "a scale-graph document is directed and a multigraph")
        g = doc.get("graph") or {}
        ids: dict[str, str] = {}
        for n in doc["nodes"]:
            nid = n.get("id")
            if not isinstance(nid, str) or not ID.match(nid):
                rep.add("error", str(nid), "node id must be a CURIE-like 'prefix:path'")
                continue
            if nid in ids:
                rep.add("error", nid, "duplicate id")
            ids[nid] = n.get("label")
        gp = self.spec["format"]["graph_props"]
        self.check_props(g, gp["properties"], gp["required"], "<graph>", rep, ids)
        if g.get("schema_version") and g["schema_version"] != self.spec["version"]:
            rep.add("error", "<graph>", f"document pins scale-graph {g['schema_version']}; this schema is {self.spec['version']}")
        if g.get("data_status") == "research_data":
            st = stewardship_of(g.get("stewardship"))         # not an object: reported above, read as institution
            missing = [k for k in ("contributed_by", "project", "access") if not st.get(k)]
            if missing:
                rep.add("error", "<graph>", f"a research_data graph declares stewardship {missing}")
        link_ids = set()
        for e in doc["links"]:
            if e.get("id") in ids or e.get("id") in link_ids:
                rep.add("error", str(e.get("id")), "duplicate id")
            link_ids.add(e.get("id"))
        self.link_ids = {x for x in link_ids if isinstance(x, str)}
        common_n = self.spec["common"]["node"]
        common_l = self.spec["common"]["link"]
        synthetic_doc = g.get("data_status") == "synthetic_example"
        for n in doc["nodes"]:
            nid, lab = n.get("id"), n.get("label")
            if set(n) - {"id", "label", "props"}:
                rep.add("error", str(nid), f"unexpected node keys {sorted(set(n) - {'id', 'label', 'props'})}")
            if lab not in self.nodes:
                rep.add("error", str(nid), f"unknown node label {lab!r}")
                continue
            nd = self.nodes[lab]
            declared = {**common_n["properties"], **(nd.get("properties") or {})}
            self.check_props(n.get("props"), declared, common_n["required"] + (nd.get("required") or []), nid, rep, ids)
            for k, v in (nd.get("fixed") or {}).items():
                if k in (n.get("props") or {}) and n["props"][k] != v:
                    rep.add("error", str(nid), f"{lab} fixes {k} = {v!r}; got {n['props'][k]!r}")
            self.advise(n.get("props") or {}, lab, nid, rep, synthetic_doc)
        for e in doc["links"]:
            rid, t = str(e.get("id")), e.get("type")
            if set(e) - {"id", "source", "target", "type", "props"}:
                rep.add("error", rid, f"unexpected link keys {sorted(set(e) - {'id', 'source', 'target', 'type', 'props'})}")
            if t not in self.edges:
                rep.add("error", rid, f"unknown edge type {t!r}")
                continue
            ed = self.edges[t]
            for end, allowed in (("source", ed["from"]), ("target", ed["to"])):
                lab = ids.get(e.get(end))
                if lab is None:
                    rep.add("error", rid, f"{end} {e.get(end)!r} does not resolve")
                elif lab not in allowed:
                    rep.add("error", rid, f"{t} {end} must be {allowed}, got {lab}")
            declared = {**common_l["properties"], **(ed.get("properties") or {})}
            self.check_props(e.get("props", {}), declared, ed.get("required") or [], rid, rep, ids)
            p = e.get("props") or {}
            if synthetic_doc and p.get("origin") != "synthetic":
                rep.add("error", rid, "synthetic-example documents label every origin synthetic")
        self.check_reported_in(doc, rep)
        plausibility(doc, rep)
        if "Hypothesis" in self.nodes and "TESTS" in self.edges:
            from .pgraph_science import science_checks
            science_checks(doc, self.spec, rep)
        for nid, inputs in outdated(doc).items():
            rep.add("warning", nid, f"outdated: inputs {inputs} were recorded after it finished")
        if source_texts:
            self.check_quotes(doc, source_texts, rep)
        rep.counts = {"nodes": len(doc["nodes"]), "links": len(doc["links"])}
        declared = any(g.get(k) or any((n.get("props") or {}).get(k) for n in doc["nodes"]) for k in ("conforms_to", "follows_domains"))
        if declared and self.spec.get("profiles") is not None:
            from .pgraph_profiles import conformance
            rep.conformance = conformance(doc, self.spec)
            for msg in rep.conformance.pop("problems"):
                rep.add("error", "<graph>", msg)
            if rep.lifecycle:                 # conformance says nothing about retractions; the counts sit beside it
                rep.conformance["source_lifecycle"] = rep.lifecycle
        return rep

    def advise(self, p: dict, lab: str, nid: str, rep: Report, synthetic_doc: bool) -> None:
        origin = p.get("origin")
        if synthetic_doc and origin != "synthetic":
            rep.add("error", nid, "synthetic-example documents label every origin synthetic")
        if not synthetic_doc and origin == "synthetic":
            rep.add("error", nid, "synthetic record inside a research document")
        if lab not in NO_EVIDENCE_NEEDED and origin in ("reported", "derived") and not p.get("evidence"):
            rep.add("warning", nid, "reported record has no evidence")
        if origin == "recorded" and not p.get("recorded_at"):
            rep.add("error", nid, "a recorded record carries recorded_at")
        for um in p.get("unmodeled") or []:
            rep.add("warning", nid, f"unmodeled context: {um[:120]}")

    def check_reported_in(self, doc: dict, rep: Report) -> None:
        """REPORTED_IN links are derived from evidence: each node links once to each source its evidence cites."""
        want = expected_reported_in(doc)
        have: dict[str, set] = {}
        for e in doc["links"]:
            if e.get("type") == "REPORTED_IN":
                if e["target"] in have.get(e["source"], set()):
                    rep.add("error", str(e.get("id")), "duplicate REPORTED_IN link")
                have.setdefault(e["source"], set()).add(e["target"])
        for nid in sorted(set(want) | set(have)):
            missing, extra = want.get(nid, set()) - have.get(nid, set()), have.get(nid, set()) - want.get(nid, set())
            if missing:
                rep.add("error", nid, f"no REPORTED_IN link to {sorted(missing)}, which its evidence cites")
            if extra:
                rep.add("error", nid, f"REPORTED_IN link to {sorted(extra)} is not backed by its evidence")

    def check_quotes(self, doc: dict, texts: dict[str, str], rep: Report) -> None:
        norm = {k: match_text(v) for k, v in texts.items()}
        for rec in doc["nodes"] + doc["links"]:
            for i, ev in enumerate((rec.get("props") or {}).get("evidence") or []):
                q, src = ev.get("quote"), ev.get("source")
                if q and src in norm and match_text(q) not in norm[src]:
                    rep.add("error", rec.get("id"), f"evidence[{i}] quote not found verbatim in the text of {src}")


def stewardship_of(v: Any) -> dict:
    """A stewardship as the access rules read it: an object as it is, none as ``{}`` (a missing access is
    institution), and anything else (a string, a list, a number, which the validator reports) as institution:
    malformed, it fails closed rather than open, and rather than stopping a filter, an export or a query."""
    if v is None:
        return {}
    return v if isinstance(v, dict) else {"access": "institution"}


def _decimals_tolerance(x: float) -> float:
    """Half a unit of the last printed digit of a number (0.5 for 50, 0.05 for 33.4)."""
    t = repr(float(x)) if not isinstance(x, int) else str(x)
    if "e" in t or "E" in t:
        return 0.0
    frac = t.split(".")[1].rstrip("0") if "." in t else ""
    return 0.5 * 10 ** -len(frac)


def plausibility(doc: dict, rep: Report) -> None:
    """Advisory warnings (:data:`PERCENT_NAME`): a percent-valued selectivity, conversion, yield or balance above
    100 %; selectivities of one record, each naming its product in ``target``, on one ``basis`` and in one unit
    spelling, summing above 100 % beyond the rounding of the printed numbers (entries that repeat a product are a
    series, not a distribution, and are not summed; the basis and the unit are compared as a query compares them,
    :func:`pgraph_query.unit_key`, so ``mol%``, ``C%``, ``wt%`` and ``%`` are never added together); and the count of second-hand evidence items (ECO:0000033 and its child ECO:0000304: a result the
    source reports from another work). The values stay as reported.

    A one-sided bound or a range is never read as one number, as the query engine reads it: a value warns only
    when every number it allows is above 100 % (a lower bound "at least 101 %", a range whose lower end is above
    100; never an upper bound "< 1 %"), and the selectivity sum adds the exact values and the lower bounds only, so it
    warns only when the total is surely above 100 % (an upper bound adds at least nothing)."""
    from .pgraph_query import SECOND_HAND_ECO, _eco, unit_key

    def entries(props: dict):
        """(path, name, value object) of every value, map entry and list entry of a record."""
        for k, v in props.items():
            if k in ("evidence", "stewardship") or k.startswith("_"):
                continue
            if isinstance(v, dict) and "status" in v:
                yield k, k, v
            elif isinstance(v, dict):
                for key, x in v.items():
                    if isinstance(x, dict) and "status" in x:
                        yield f"{k}.{key}", str(key), x
            elif isinstance(v, list):
                for i, x in enumerate(v):
                    if isinstance(x, dict) and "status" in x:
                        yield f"{k}.{i}", k, x

    def num(x) -> bool:
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    def least(v: dict):
        """The smallest number a value allows: its value (exact, or a lower bound), a range's lower end; None for an
        upper bound, which allows any number below it."""
        if v.get("bound") == "upper":
            return None
        for f in ("value", "lower"):
            if num(v.get(f)):
                return v[f]
        return None

    for n in doc.get("nodes") or []:
        props = n.get("props") or {}
        if not isinstance(props, dict):
            continue
        groups: dict[tuple[str, str], list[tuple[str, float | None, str, str | None]]] = {}   # by (basis, unit)
        for path, name, v in entries(props):
            if v.get("status") != "present" or not PERCENT_NAME.search(name.lower()) \
                    or not PERCENT_UNIT.match(str(v.get("unit") or "")):
                continue
            x = least(v)
            if x is not None and x > 100:
                said = (f"at least {x}" if v.get("bound") == "lower" or not (num(v.get("value")) or num(v.get("upper")))
                        else f"{x}" if num(v.get("value")) else f"{x}-{v.get('upper')}")
                rep.add("warning", str(n.get("id")), f"{path}: {said} {v.get('unit')} is above 100 % for a selectivity, "
                                                     "conversion, yield or balance; check the reading (it stays as reported)")
            if SELECTIVITY_NAME.search(name.lower()) and v.get("target") and num(v.get("value")):
                # an upper bound adds at least nothing to the sum: only exact values and lower bounds are summed
                key = (unit_key(str(v.get("basis") or "")), unit_key(str(v["unit"])))   # as a query keeps them apart
                groups.setdefault(key, []).append(
                    (str(v["target"]), None if v.get("bound") == "upper" else float(v["value"]), path, v.get("bound")))
        for (basis, unit), sel in groups.items():
            targets = [t for t, _, _, _ in sel]
            if len(sel) < 2 or len(set(targets)) < len(targets):
                continue
            summed = [(x, p, b) for _, x, p, b in sel if x is not None]
            total = sum(x for x, _, _ in summed)
            surely = len(summed) < len(sel) or any(b == "lower" for _, _, b in summed)
            if summed and total > 100 + sum(_decimals_tolerance(x) for x, _, _ in summed):
                rep.add("warning", str(n.get("id")),
                        f"selectivities to {len(sel)} products{f' on the basis {basis!r}' if basis else ''} sum to "
                        f"{'at least ' if surely else ''}{round(total, 6)} {unit}, above 100 % ({', '.join(p for _, p, _ in summed)}"
                        f"{'; one-sided bounds read as the least they allow' if surely else ''}); check the readings and "
                        "their bases (they stay as reported)")
    second = sum(1 for rec in (doc.get("nodes") or []) + (doc.get("links") or [])
                 for ev in (rec.get("props") or {}).get("evidence") or []
                 if isinstance(ev, dict) and _eco(ev.get("evidence_type")) in SECOND_HAND_ECO)
    if second:
        rep.add("warning", "<graph>", f"{second} evidence item{'s are' if second != 1 else ' is'} second-hand (ECO:0000033: "
                                      "a result the source reports from another work); queries name such evidence, and "
                                      "own_work_only leaves rows resting only on it out")


def effective_stewardship(doc: dict, record: dict) -> dict:
    """The graph's default stewardship, overridden field by field by the record's own (each read by
    :func:`stewardship_of`; a record whose props are not an object reads as institution)."""
    graph = doc.get("graph")
    st = dict(stewardship_of(graph.get("stewardship") if isinstance(graph, dict) else None))
    props = record.get("props")
    own = stewardship_of(props.get("stewardship")) if isinstance(props, dict) else stewardship_of(props or None)
    if own.get("access") and own["access"] != "embargoed":
        st.pop("embargo_until", None)
        st.pop("access_after_embargo", None)
    st.update(own)
    return st


def memberships(doc: dict, viewer: list[str]) -> tuple[set, set]:
    """Institutions and projects a viewer belongs to: the given person or institution ids, the institutions they are
    MEMBER_OF (transitively), and the projects those PARTICIPATE_IN."""
    agents, frontier = set(viewer), list(viewer)
    member = [(l["source"], l["target"]) for l in doc["links"] if l["type"] == "MEMBER_OF"]
    while frontier:
        a = frontier.pop()
        for s, t in member:
            if s == a and t not in agents:
                agents.add(t)
                frontier.append(t)
    projects = {l["target"] for l in doc["links"] if l["type"] == "PARTICIPATES_IN" and l["source"] in agents}
    projects |= {v for v in viewer if any(n["id"] == v and n["label"] == "Project" for n in doc["nodes"])}
    return agents, projects


def embargo_end(until: Any) -> str | None:
    """The last day an embargo holds (YYYY-MM-DD): ``embargo_until`` read to the end of the period its precision
    names (YYYY: 31 December of that year; YYYY-MM: the last day of that month; a full date: that day). None when it
    is not such a date: the embargo then never lapses (it fails closed)."""
    if not isinstance(until, str) or not DATE.match(until):
        return None
    try:
        if len(until) == 4:
            return f"{until}-12-31"
        if len(until) == 7:
            return f"{until}-{calendar.monthrange(int(until[:4]), int(until[5:]))[1]:02d}"
        datetime.strptime(until, "%Y-%m-%d")
    except ValueError:                      # a month 13, a 30 February
        return None
    return until


def clock() -> datetime:
    """The one clock every embargo read takes (the filter, a query, a search, the exports): the local time, with its
    offset. Tests fix it."""
    return datetime.now().astimezone()


def embargo_today() -> str:
    """The day embargoes are read on when no earlier day is given (YYYY-MM-DD): the local date or the UTC date of
    :func:`clock`, whichever is earlier. Every path then closes an embargo at the earlier of the two midnights, so no
    path ships a record another still withholds."""
    now = clock()
    return min(now.date(), now.astimezone(timezone.utc).date()).isoformat()


def embargo_day(day: Any, today: str, what: str = "the date") -> str:
    """The day embargoes are read on: ``day`` (an ISO date, YYYY-MM-DD; None is ``today``) or ``today``, whichever is
    earlier. An embargo then counts as lapsed only when it has lapsed both on the given day and today: a later day (a
    query's ``as_of``, ``scale graph filter --date``, a GALAXY bundle's ``created``) never opens one still in force; an
    earlier one may keep one closed. A day that is not a date of the calendar is refused, naming ``what`` it is."""
    if day is None:
        return today
    if not isinstance(day, str) or not DAY.match(day):
        raise ScaleError(f"{what} must be a date, YYYY-MM-DD (got {day!r}); it is the day embargoes are read on, "
                         "never later than today")
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError as exc:
        raise ScaleError(f"{what} {day!r} is not a date of the calendar") from exc
    return min(day, today)


def embargo_lapsed(st: dict, today: str) -> bool:
    """Whether an embargo has lapsed on ``today`` (YYYY-MM-DD): the day after its :func:`embargo_end`. An
    ``embargo_until`` that is not a date, or a ``today`` that is not a day, never lapses one."""
    end = embargo_end(st.get("embargo_until"))
    return end is not None and isinstance(today, str) and bool(DAY.match(today)) and today > end


def visible(st: dict, agents: set, projects: set, today: str) -> bool:
    access = st.get("access", "institution")
    if access == "embargoed":
        if embargo_lapsed(st, today):
            access = st.get("access_after_embargo", "institution")
        else:
            access = "institution"
    if access == "public":
        return True
    if access == "consortium":
        return bool(projects)
    if access == "project":
        return isinstance(st.get("project"), str) and st["project"] in projects
    return bool(set(institutions(st)) & agents)


def institutions(st: dict) -> list[str]:
    """The contributing institutions a stewardship names (``contributed_by``; anything there that is not an id
    names none)."""
    v = st.get("contributed_by")
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


_GONE, _EMPTIED, _WITHHELD = object(), object(), object()   # a reference to a record left out; a container left empty
#                                                             by removing them; a value object that names a record left out
_HELD = "held"      # tags the pointer of a value withheld in its place (a record_ref to it goes; nothing after it moves)
VALUE_STATUSES = ("present", "not_reported", "not_measured", "not_applicable", "below_detection_limit",
                  "below_quantification_limit")
# the references a value object makes (kernel `value`)
VALUE_REFS = ("ref_value", "target", "variable", "produced_by", "calibration")
# what a value naming a withheld record becomes: the kernel's own missing reason, "known but not shared"
WITHHELD_VALUE = {"status": "not_reported", "missing_reason": "withheld"}


def _held(v: dict, gone: set) -> dict:
    """What a withheld value leaves in its place: :data:`WITHHELD_VALUE`, with the ``target`` and ``variable`` it
    names when those records are kept (what it was a value of, so that a query's ``[target=…]`` still selects it and
    reads it as withheld)."""
    return {**WITHHELD_VALUE, **{k: v[k] for k in ("target", "variable") if isinstance(v.get(k), str) and v[k] not in gone}}


def _esc(key: str) -> str:
    """A key as one step of a JSON pointer."""
    return key.replace("~", "~0").replace("/", "~1")


def _drop_refs(v: Any, gone: set, n: list[int], at: str = "", dropped: set | None = None,
               lost_evidence: set | frozenset = frozenset(), moved=None, untraced: bool = False,
               kept_evidence: set | frozenset = frozenset()) -> Any:
    """``v`` without its references to the records left out (``gone``): a string that is such an id (a ref, an entry
    of a ref list), a record_ref whose ``record`` is one, a map entry keyed by one. A value object is one unit: when
    any of its references (``ref_value``, ``target``, ``variable``, ``produced_by``, ``calibration``) names such a
    record, it is returned as ``_WITHHELD`` and stays in its place as the withheld marker (:func:`_held`:
    :data:`WITHHELD_VALUE`, with the target and variable it names that are kept): an entry of a list keeps its
    position, an entry of a map its key (the curator's words on the kept record, as its name and note are; only a key
    that is itself a withheld id goes), and a property becomes the marker (:func:`_strip`). So a query reads it as
    withheld, never as not curated. A value never loses a reference alone, which could leave a present value with no
    value. ``n[0]`` counts the references removed (a value withheld included); a list or map left empty by removing
    references goes too.

    ``at`` is ``v``'s JSON pointer in its record's props; each part removed is added to ``dropped`` by its pointer
    there, and each value withheld in its place as ``(_HELD, pointer)``, so that a record_ref into the record can
    follow it. ``moved(record, path)`` gives a record_ref's ``path`` in that record as filtered (a list position after a
    removed entry moves up; nothing moves behind a value withheld in its place), or None when the path names a part
    removed or withheld, or a part of one: the record_ref then goes, as one to a record left out does, and is counted.
    ``lost_evidence``: the ids of the record's evidence items removed (their source is left out), which a value's
    ``evidence_ids`` then no longer names; ``kept_evidence``: the ids of those that remain. A value whose
    ``evidence_ids`` name none of the evidence that remains (only items removed, or ids that name no item of the
    record) is stated by no source the view keeps and is returned as ``_WITHHELD`` too (it is not left standing on
    the evidence that remains).
    ``untraced``: the record lost evidence items. A value with no ``evidence_ids`` on such a record cannot be traced
    to the evidence that remains (it may rest on a source left out alone), so it is ``_WITHHELD`` as well: the
    reading fails closed, and a value is never left cited to a kept source that may not state it (:func:`_subset`).
    A value already withheld stays as it is."""
    dropped = set() if dropped is None else dropped
    if isinstance(v, str):
        return _GONE if v in gone else v
    if isinstance(v, list):
        kept = []
        for i, x in enumerate(v):
            y = _drop_refs(x, gone, n, f"{at}/{i}", dropped, lost_evidence, moved, untraced, kept_evidence)
            if y is _WITHHELD:                          # withheld in its place: the entries after it keep their positions
                n[0] += 1
                dropped.add((_HELD, f"{at}/{i}"))
                kept.append(_held(x, gone))
                continue
            if y is _GONE:
                n[0] += 1
            if y is _GONE or y is _EMPTIED:
                dropped.add(f"{at}/{i}")
            else:
                kept.append(y)
        return _EMPTIED if v and not kept else kept
    if isinstance(v, dict):
        if isinstance(v.get("record"), str):              # a record_ref
            if v["record"] in gone:
                return _GONE
            if moved is not None and isinstance(v.get("path"), str):
                path = moved(v["record"], v["path"])
                if path is None:
                    return _GONE
                v = {k: (path if k == "path" else x) for k, x in v.items()}
        if v.get("status") in VALUE_STATUSES:          # a value object: its other fields hold no record id
            if any(isinstance(v.get(k), str) and v[k] in gone for k in VALUE_REFS):
                return _WITHHELD
            ids = v.get("evidence_ids")
            if isinstance(ids, list) and ids:           # traced: the evidence items that state it
                if not any(isinstance(x, str) and x in kept_evidence for x in ids):
                    return _WITHHELD                    # stated by none of the evidence left: withheld, as a whole
                if lost_evidence and any(isinstance(x, str) and x in lost_evidence for x in ids):
                    left = [x for x in ids if not (isinstance(x, str) and x in lost_evidence)]
                    dropped.update(f"{at}/evidence_ids/{i}" for i, x in enumerate(ids)
                                   if isinstance(x, str) and x in lost_evidence)
                    v = {k: (left if k == "evidence_ids" else x) for k, x in v.items()}
            elif untraced and not (v.get("status") == "not_reported" and v.get("missing_reason") == "withheld"):
                return _WITHHELD                        # its record lost evidence, and nothing says it rests on the rest
            return v
        kept = {}
        for k, x in v.items():
            ptr = f"{at}/{_esc(k)}"
            y = _GONE if k in gone else _drop_refs(x, gone, n, ptr, dropped, lost_evidence, moved, untraced,
                                                   kept_evidence)
            if y is _WITHHELD:                          # withheld under its key
                n[0] += 1
                dropped.add((_HELD, ptr))
                kept[k] = _held(x, gone)
                continue
            if y is _GONE:
                n[0] += 1
            if y is _GONE or y is _EMPTIED:
                dropped.add(ptr)
            else:
                kept[k] = y
        return _EMPTIED if v and not kept else kept
    return v


def _moved(props: dict, path: str, dropped: set) -> str | None:
    """A JSON pointer into a record's props (``path``) in the record as filtered, given the pointers of the parts
    removed from it (``dropped``; a value withheld in its place as ``(_HELD, pointer)``): a list position after a
    removed entry moves up (not after a value withheld in its place), and a pointer to a part removed or withheld, or
    into one, is None. A pointer that does not resolve in the record is returned as it is (the validator reports
    it)."""
    if not dropped:
        return path
    cur: Any = props
    at, out = "", []
    for part in path.split("/")[1:]:
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            i = int(part)
            out.append(str(i - sum(1 for j in range(i) if f"{at}/{j}" in dropped)))
            at, cur = f"{at}/{i}", cur[i]
        elif isinstance(cur, dict) and key in cur:
            out.append(part)
            at, cur = f"{at}/{_esc(key)}", cur[key]
        else:
            return path
        if at in dropped or (_HELD, at) in dropped:
            return None
    return "/" + "/".join(out) if out else path


def _strip(props: dict, keep: set, gone: set, dropped: set, moved, removed: list[int], cut: list[int]) -> dict:
    """A kept record's props as :func:`_subset` leaves them; the parts removed go to ``dropped``, and ``cut[0]`` counts
    the record when it loses evidence items (their source is left out); its values then stay only where their
    ``evidence_ids`` name evidence that remains (:func:`_drop_refs`)."""
    lost: set = set()
    kept_ev: set = set()                   # the ids of the evidence items that remain
    untraced = False                       # the record lost evidence items: a value not traced to the rest is withheld
    if "evidence" in props:
        ev = []
        for i, e in enumerate(props["evidence"]):
            if e.get("source") in keep:
                ev.append(e)
            else:
                dropped.add(f"/evidence/{i}")
                lost.add(e.get("id"))
        if len(ev) < len(props["evidence"]):
            cut[0] += 1
            untraced = True
        kept_ev = {e.get("id") for e in ev if isinstance(e.get("id"), str)}
        lost = {x for x in lost if isinstance(x, str)} - kept_ev
        if not ev:
            dropped.add("/evidence")
        props = {**props, "evidence": ev} if ev else {k: v for k, v in props.items() if k != "evidence"}
    if not gone:
        return props
    out = {}
    for k, v in props.items():
        ptr = f"/{_esc(k)}"
        y = v if k in ("evidence", "stewardship") else _drop_refs(v, gone, removed, ptr, dropped, lost, moved, untraced,
                                                                  kept_ev)
        if y is _GONE or y is _WITHHELD:
            removed[0] += 1
        if y is _WITHHELD:
            dropped.add((_HELD, ptr))
            out[k] = _held(v, gone)
        elif y is _GONE or y is _EMPTIED:
            dropped.add(ptr)
        else:
            out[k] = y
    return out


def _subset_pass(kept_nodes: list[dict], links_kept: list[dict], keep: set, gone: set, original: dict,
                 drops: dict[str, set]) -> tuple[list[dict], list[dict], int, int, dict[str, set], set[str]]:
    """One pass of :func:`_subset`, reading record_ref paths against ``drops`` (the parts removed from each record,
    as the previous pass found them). Returns the nodes, the links, the references removed, the records that lost
    evidence items, the parts removed now and the records a path was read against."""
    now: dict[str, set] = {}
    read: set[str] = set()
    removed, cut = [0], [0]

    def moved(rid: str, path: str) -> str | None:
        if rid not in original:
            return path
        read.add(rid)
        return _moved(original[rid], path, drops.get(rid, set()))

    def strip(r: dict) -> dict:
        rid = r.get("id")
        return _strip(r.get("props") or {}, keep, gone, now.setdefault(rid, set()) if isinstance(rid, str) else set(),
                      moved, removed, cut)
    nodes = [{**n, "props": strip(n)} for n in kept_nodes]
    links = [{**e, "props": strip(e)} for e in links_kept]
    return nodes, links, removed[0], cut[0], now, read


def _subset(doc: dict, keep_record) -> tuple[list[dict], list[dict], int, int]:
    """The nodes and links ``keep_record(record)`` keeps; links go with their endpoints, evidence that points at a
    source left out is removed (and a value's ``evidence_ids`` naming it; a value whose ``evidence_ids`` name only
    such evidence is withheld), and so is every other reference a kept record makes to a record left out
    (:func:`_drop_refs`: a value that names one is withheld in its place, as not_reported with missing_reason
    withheld, whether it is a property or an entry of a list or map; a ref, a ref-list entry, a record_ref or a map
    key naming one goes; its stewardship is left as it is), so no id of a withheld record remains and no present
    value is left without its value. A record_ref into a kept record follows what was removed from it: its ``path``
    moves with a list entry (or an evidence item) whose position changed, and a record_ref to a part removed or
    withheld goes and is counted, as one to a record left out does, so it never names another value than the one it
    named.

    Only ``evidence_ids`` tie a value to the evidence items that state it, so on a kept record that lost evidence
    items the reading fails closed: a value whose ``evidence_ids`` name none of the evidence left, and a value with
    no ``evidence_ids`` (the curated corpora give none), may rest on a source left out alone, and is withheld in its
    place; a value is never left cited to a kept source that may not state it. The record keeps its own words (its
    name, a claim's statement), which its stewardship governs. The records that lost evidence are counted. Returns
    the nodes, the links, the number of references removed (a value withheld included) and the number of kept
    records that lost evidence items."""
    keep = {n["id"] for n in doc["nodes"] if keep_record(n)}
    links_kept = [e for e in doc["links"] if e["source"] in keep and e["target"] in keep and keep_record(e)]
    gone = ({n["id"] for n in doc["nodes"]} - keep) | ({e.get("id") for e in doc["links"]} - {e.get("id") for e in links_kept})
    gone.discard(None)
    kept_nodes = [n for n in doc["nodes"] if n["id"] in keep]
    original = {r["id"]: r.get("props") or {} for r in kept_nodes + links_kept if isinstance(r.get("id"), str)}
    # removing a record_ref changes its own record in turn: repeat until the parts removed from every record a path
    # was read against are the ones the pass read them with (the parts removed only grow, so this ends)
    drops: dict[str, set] = {}
    while True:
        nodes, links, removed, cut, now, read = _subset_pass(kept_nodes, links_kept, keep, gone, original, drops)
        if all(now.get(rid, set()) == drops.get(rid, set()) for rid in read):
            return nodes, links, removed, cut
        drops = now


def view_audience(doc: dict, viewer: list[str]) -> dict | None:
    """The stewardship that names a viewer as an audience: the public for ``[]`` (``{access: public}``), one project
    (``{access: project, project}``) or institutions (``{access: institution, contributed_by}``); None for a person,
    several projects, a mix or an id the graph does not hold, which no stewardship names."""
    if not viewer:
        return {"access": "public"}
    labels = {n["id"]: n["label"] for n in doc["nodes"]}
    ids = sorted(set(viewer))
    kinds = {labels.get(v) for v in ids}
    if kinds == {"Project"} and len(ids) == 1:
        return {"access": "project", "project": ids[0]}
    if kinds == {"Institution"}:
        return {"access": "institution", "contributed_by": ids}
    return None


def _own_audience(doc: dict, r: dict, header: dict) -> dict:
    """``r`` with the audience keys (:data:`AUDIENCE_KEYS`) it inherits from ``doc``'s header written on its own
    stewardship wherever ``header`` (the view's) would give it another one, so that its access, project,
    institutions and embargo stay what they were (a missing access is written as institution)."""
    before = effective_stewardship(doc, r)
    after = effective_stewardship({"graph": {"stewardship": header}}, r)
    props = r.get("props") if isinstance(r.get("props"), dict) else {}
    own = dict(stewardship_of(props.get("stewardship")))
    for k in AUDIENCE_KEYS:
        if before.get(k) == after.get(k):
            continue
        if k in before:
            own[k] = before[k]
        elif k == "access":
            own[k] = "institution"
        elif k == "contributed_by":
            own[k] = []
    if own == stewardship_of(props.get("stewardship")):
        return r
    return {**r, "props": {**props, "stewardship": own}}


def filter_for(doc: dict, viewer: list[str], today: str) -> dict:
    """The part of a graph a viewer may see. ``viewer`` lists institution, person or project ids ([] = the public).
    Links go with their endpoints; evidence that points at a hidden source is removed, and so are the other
    references to hidden records (:func:`_subset`). ``graph.filtered_for`` says for whom and when, and counts what
    was withheld, the references removed (a value withheld included) and the kept records that lost evidence items
    (whose values not traced by ``evidence_ids`` to the evidence left are withheld in their place).

    When the viewer may not see the graph's header stewardship (a public view of a project graph) and a stewardship
    can name the viewer (:func:`view_audience`: the public, one project, institutions), the view's header declares
    the viewer as its audience, as a GALAXY bundle's does: its access becomes the view's (an embargo goes; the
    project or institutions the viewer is; its other keys stay). A kept record first gets the audience keys it
    inherited from the graph's header written on its own stewardship, so its access is what it was
    (:func:`_own_audience`). A query of the view then has the access of what it holds (a public view of a project
    graph answers publicly). Otherwise (the viewer may see the header, or is a person or a mix) the header stays."""
    agents, projects = memberships(doc, viewer)
    nodes, links, refs, cut = _subset(doc, lambda r: visible(effective_stewardship(doc, r), agents, projects, today))
    graph = dict(doc.get("graph") or {})
    note = (f"viewer {', '.join(sorted(viewer)) or 'public'} on {today}: "
            f"{len(doc['nodes']) - len(nodes)} nodes and {len(doc['links']) - len(links)} links withheld"
            + (f", and {refs} references to them removed" if refs else "")
            + (f"; {cut} kept records lost evidence citing them" if cut else ""))
    header = stewardship_of(graph.get("stewardship"))
    declared = view_audience(doc, viewer)
    if declared is not None and not visible(header, agents, projects, today):
        view = {**{k: v for k, v in header.items() if k not in ("access", "embargo_until", "access_after_embargo")},
                **declared}
        nodes = [_own_audience(doc, n, view) for n in nodes]
        links = [_own_audience(doc, e, view) for e in links]
        graph["stewardship"] = view
        note += f"; the header declares the view's audience, {declared['access']} (the graph's: {openness(header, today)})"
    graph["filtered_for"] = note
    return {**doc, "graph": graph, "nodes": nodes, "links": links}


def filtered_for_public(doc: dict) -> bool:
    """Whether ``doc`` is a view :func:`filter_for` made for the public (``graph.filtered_for``)."""
    return str(((doc.get("graph") or {}).get("filtered_for")) or "").startswith("viewer public on ")


def openness(st: dict, today: str) -> str:
    """The access level a stewardship grants on ``today``, as :func:`visible` reads it: a missing access is
    institution; an embargo in force is institution, and a lapsed one its access_after_embargo."""
    access = st.get("access") or "institution"
    if access == "embargoed":
        access = (st.get("access_after_embargo") or "institution") if embargo_lapsed(st, today) else "institution"
    return access if isinstance(access, str) and access in OPENNESS else "institution"


def access_key(st: dict, today: str) -> tuple:
    """Who may see a record, as far as stewardship says: its level, with the project (project level) or the
    contributing institutions (institution level) that bound it."""
    level = openness(st, today)
    if level == "project":
        return level, st.get("project") if isinstance(st.get("project"), str) else None
    if level == "institution":
        return level, tuple(sorted(institutions(st)))
    return level, None


# a viewer in some project, unknown which (the least a consortium audience is sure to include): not an id
SOME_PROJECT = "<a project of the consortium>"


def audience(doc: dict, declared: dict, today: str) -> list[tuple[set, set]]:
    """The least-privileged viewers a declared stewardship admits, as (institutions and people, projects) pairs that
    :func:`visible` reads: whatever each of them may see, everyone in the audience may. Public: a viewer in no
    project. Consortium: a viewer in one project, unknown which. Project: a member of that project only. Institution
    (and an embargo in force): each contributing institution with what it belongs to (:func:`memberships`), so a
    record of a project the institution is not in, or a consortium record when it is in none, is not for all of it.
    An institution stewardship that names no institution (or none at all) admits no one by name: only what the
    public may see is for all of its audience, besides the records with that very stewardship (:func:`restrict_to`)."""
    level = openness(declared, today)
    if level == "public":
        return [(set(), set())]
    if level == "consortium":
        return [(set(), {SOME_PROJECT})]
    if level == "project":                  # a project that is not an id names none: some project, unknown which
        p = declared.get("project")
        return [(set(), {p if isinstance(p, str) and p else SOME_PROJECT})]
    return [memberships(doc, [i]) for i in institutions(declared)] or [(set(), set())]


def less_open(st: dict, viewers: list[tuple[set, set]], today: str) -> bool:
    """Whether a record with stewardship ``st`` is hidden from part of an audience (``viewers``, from
    :func:`audience`): some least-privileged viewer of it may not see the record, by the rules of :func:`filter_for`."""
    return not all(visible(st, agents, projects, today) for agents, projects in viewers)


def restrict_to(doc: dict, declared: dict, today: str) -> tuple[dict, dict]:
    """The part of a graph that everyone a declared stewardship admits may see (what :func:`filter_for` keeps
    for a viewer, here for every viewer of an audience, :func:`audience`): records less open than ``declared``
    are left out, links with their endpoints, and evidence pointing at a source left out is removed, as is every other
    reference to a record left out (:func:`_subset`). Returns the document and the counts withheld (nodes, links,
    references when some were removed, and ``evidence_cut``, the kept records that lost evidence items, when some
    did)."""
    viewers, own = audience(doc, declared, today), access_key(declared, today)

    def keep(r: dict) -> bool:             # the bundle's own audience (by construction), or visible to all of it
        st = effective_stewardship(doc, r)
        return access_key(st, today) == own or not less_open(st, viewers, today)
    nodes, links, refs, cut = _subset(doc, keep)
    withheld = {"nodes": len(doc["nodes"]) - len(nodes), "links": len(doc["links"]) - len(links),
                **({"references": refs} if refs else {}), **({"evidence_cut": cut} if cut else {})}
    return {**doc, "nodes": nodes, "links": links}, withheld


def registry_records(registry: dict, used: set[str]) -> tuple[list[dict], list[dict]]:
    """Nodes and links for the registry entries a graph uses: the institutions, people, software and
    projects it names, the projects' funders and participants, and their PARTICIPATES_IN and FUNDED_BY links."""
    kinds = {"institutions": "Institution", "persons": "Person", "software": "Software"}
    entries = {e["id"]: (label, e) for key, label in kinds.items() for e in registry.get(key) or []}
    projects = {p["id"]: p for p in registry.get("projects") or []}
    want = set(used)
    for pid in [u for u in used if u in projects]:
        pr = projects[pid]
        want |= {pr["funded_by"]} if pr.get("funded_by") else set()
        want |= {x["member"] for x in pr.get("participants") or []}
    unknown = sorted(u for u in want if u not in entries and u not in projects)
    if unknown:
        raise ScaleError(f"not in the stewardship registry: {unknown}")
    nodes, links = [], []
    for i in sorted(want):
        if i in entries:
            label, e = entries[i]
            nodes.append({"id": i, "label": label, "props": {**{k: v for k, v in e.items() if k != "id"},
                                                               "origin": "curated"}})
            continue
        p = projects[i]
        props = {k: v for k, v in p.items() if k in ("name", "award_id", "url", "start_date", "end_date", "note")}
        nodes.append({"id": i, "label": "Project", "props": {**props, "origin": "curated"}})
        if p.get("funded_by"):
            links.append({"id": f"{i}/funded-by", "source": i, "target": p["funded_by"], "type": "FUNDED_BY",
                          "props": {"origin": "curated", **({"award_id": p["award_id"]} if p.get("award_id") else {})}})
        for x in p.get("participants") or []:
            links.append({"id": f"{i}/participant/{x['member'].rsplit('/', 1)[-1]}", "source": x["member"],
                          "target": i, "type": "PARTICIPATES_IN", "props": {"origin": "curated", "role": x["role"]}})
    return nodes, links


def expected_reported_in(doc: dict) -> dict[str, set]:
    """Node id -> the sources its evidence cites (Source nodes themselves excluded)."""
    out: dict[str, set] = {}
    for n in doc.get("nodes") or []:
        if n.get("label") == "Source":
            continue
        srcs = {ev.get("source") for ev in (n.get("props") or {}).get("evidence") or [] if ev.get("source")}
        srcs.discard(n.get("id"))
        if srcs:
            out[n["id"]] = srcs
    return out


def derive_reported_in(doc: dict) -> list[dict]:
    """REPORTED_IN links for a document, one per node and cited source, listing the locators cited."""
    links = []
    for n in sorted(doc.get("nodes") or [], key=lambda n: n["id"]):
        if n.get("label") == "Source":
            continue
        by: dict[str, set] = {}
        for ev in (n.get("props") or {}).get("evidence") or []:
            if ev.get("source") and ev["source"] != n["id"]:
                by.setdefault(ev["source"], set()).add(ev.get("locator", ""))
        for src in sorted(by):
            links.append({"id": f"{n['id']}/reported-in/{src.rsplit('/', 1)[-1]}", "source": n["id"], "target": src,
                          "type": "REPORTED_IN", "props": {"origin": "curated",
                                                            "locators": sorted(x for x in by[src] if x)}})
    return links


def outdated(doc: dict) -> dict[str, list[str]]:
    """Activities whose USES_INPUT inputs were recorded after they finished (TWA OntoDerivation's
    outdated check), unless their status already says outdated."""
    def ts(v):
        if not isinstance(v, str):
            return None
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    props = {n["id"]: n.get("props") or {} for n in doc["nodes"]}
    out: dict[str, list[str]] = {}
    for e in doc["links"]:
        if e.get("type") != "USES_INPUT":
            continue
        act, inp = props.get(e["source"], {}), props.get(e["target"], {})
        done, seen = ts(act.get("finished_at")), ts(inp.get("recorded_at"))
        if done and seen and seen > done and act.get("status") != "outdated":
            out.setdefault(e["source"], []).append(e["target"])
    return {k: sorted(v) for k, v in sorted(out.items())}


def validate(doc: dict, spec: dict, source_texts: dict[str, str] | None = None) -> Report:
    return Validator(spec).validate(doc, source_texts)


NO_UNIT = "(no unit)"
#: The unit a curator writes for a number the source prints without one (curate-source, docs/curation.md): a
#: placeholder that states no unit, read in any case and spacing (:func:`states_no_unit`). Never a unit to plan on.
UNIT_NOT_STATED = "not stated"


def states_no_unit(u: Any) -> bool:
    """Whether a value object's ``unit`` states none: absent (None), text that is empty once trimmed, or
    :data:`UNIT_NOT_STATED` in any case and spacing (``Not  Stated``)."""
    return u is None or (isinstance(u, str) and " ".join(u.split()).casefold() in ("", UNIT_NOT_STATED))


def _units_in(path: str, v: Any, into: dict[str, Counter]) -> None:
    """Count the units of the numeric value objects at a property path: ``temperature``, a map entry
    ``results.methanol_yield``, a list entry ``levels.*`` (the paths a query plan addresses). A value that states
    no unit (:func:`states_no_unit`: none, blank, or the placeholder ``not stated``) counts under :data:`NO_UNIT`."""
    if isinstance(v, dict) and "status" in v:
        if any(isinstance(v.get(k), (int, float)) and not isinstance(v.get(k), bool) for k in ("value", "lower", "upper")):
            u = v.get("unit")
            into.setdefault(path, Counter())[NO_UNIT if states_no_unit(u) else u if isinstance(u, str)
                                             else f"(a unit that is not text: {type(u).__name__})"] += 1
    elif isinstance(v, dict):
        for k, x in v.items():
            _units_in(f"{path}.{k}", x, into)
    elif isinstance(v, list):
        for x in v:
            _units_in(f"{path}.*", x, into)


def stats(doc: dict) -> dict:
    """Counts of node labels, edge types and evidence, the properties in use per label, the units in use per
    label (or edge type) and property path, and the link patterns (source label, edge type, target label)."""
    nodes = doc.get("nodes") or []
    links = doc.get("links") or []
    props: dict[str, Counter] = {}
    used: dict[str, dict[str, Counter]] = {}
    for n in nodes:
        props.setdefault(n["label"], Counter()).update(n.get("props", {}).keys())
    for r, owner in [(n, n["label"]) for n in nodes] + [(e, e["type"]) for e in links]:
        for k, v in (r.get("props") or {}).items():
            if k not in ("evidence", "stewardship"):
                _units_in(k, v, used.setdefault(owner, {}))
    label = {n["id"]: n["label"] for n in nodes}
    patterns = Counter((label.get(e["source"], "?"), e["type"], label.get(e["target"], "?")) for e in links)
    quotes = {ev.get("quote") for r in nodes + links for ev in (r.get("props") or {}).get("evidence", []) if ev.get("quote")}
    return {"graph_id": (doc.get("graph") or {}).get("graph_id"), "nodes": len(nodes), "links": len(links),
            "node_labels": dict(Counter(n["label"] for n in nodes).most_common()),
            "edge_types": dict(Counter(e["type"] for e in links).most_common()),
            "distinct_quotes": len(quotes),
            "properties_by_label": {k: dict(v.most_common()) for k, v in sorted(props.items())},
            "units_in_use": {owner: {path: dict(sorted(c.items(), key=lambda x: (-x[1], x[0]))) for path, c in sorted(paths.items())}
                             for owner, paths in sorted(used.items()) if paths},
            "link_patterns": [{"source": s, "type": t, "target": g, "count": n}
                              for (s, t, g), n in sorted(patterns.items(), key=lambda x: (-x[1], x[0]))]}


# ------------------------------------------------------------------ flat export
def _flatten(props: dict) -> dict:
    """Primitive-valued properties for stores such as Neo4j: a value object becomes <key>_value,
    <key>_unit, … ; maps become <map>_<key>_… ; evidence becomes a JSON string."""
    out: dict[str, Any] = {}

    def put(prefix: str, v: Any) -> None:
        if isinstance(v, dict) and "status" in v:
            for k, x in v.items():
                out[f"{prefix}_{k}"] = x
        elif isinstance(v, dict):
            for k, x in v.items():
                put(f"{prefix}_{k}", x)
        elif isinstance(v, list) and v and isinstance(v[0], (dict, list)):
            out[prefix] = json.dumps(v, ensure_ascii=False, sort_keys=True)
        else:
            out[prefix] = v
    for k, v in props.items():
        put(k, v)
    return out


def to_neo4j_jsonl(doc: dict) -> str:
    """Neo4j/APOC-style JSON lines: one node or relationship per line, primitive properties only."""
    lines = []
    for n in doc["nodes"]:
        lines.append({"type": "node", "id": n["id"], "labels": [n["label"]], "properties": _flatten(n.get("props", {}))})
    for e in doc["links"]:
        lines.append({"type": "relationship", "id": e["id"], "label": e["type"], "start": {"id": e["source"]},
                      "end": {"id": e["target"]}, "properties": _flatten(e.get("props", {}))})
    return "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines)


def _extensions_for(spec: dict, profile: str | None) -> set[str] | None:
    """The extensions or domain files whose driving forces a profile covers (a schema whose checklists are kept
    per driving force); None means all (also for a checklist that declares no driving forces, such as the
    catalysis domain's own: it covers the whole domain)."""
    if not profile:
        return None
    name = profile.split("@")[0]
    if name not in spec["profiles"]:
        raise ScaleError(f"unknown domain or profile {profile!r}; known: {sorted(spec['profiles'])}")
    forces = set(spec["profiles"][name]["driving_forces"])
    if not forces:
        return None
    return {m for m, d in spec["modules"].items() if d.get("kind") in ("extension", "domain")
            and set(d.get("driving_forces") or []) <= forces}


def _ptype(d: dict, spec: dict | None = None) -> str:
    t = d.get("type", "?")
    if t == "enum":
        return "enum[" + "|".join(d.get("values") or []) + "]"
    if t == "list":
        return "list[" + _ptype(d.get("items") or {}, spec) + "]"
    if t == "ref":
        return "ref[" + "|".join(d.get("targets") or []) + "]"
    if t in STRUCTURES and isinstance((spec or {}).get(t), dict):     # a kernel structure, with its fields
        fields = spec[t].get("fields") or {}
        return t + "{" + ", ".join(f"{k}: {_ptype(f, spec)}" for k, f in fields.items()) + "}"
    return t


def _items(c: dict, edge: bool = False, case: bool = False) -> dict:
    """A checklist block as a curator reads it: must, should, edges (labels) and its cases (``when``),
    each with the condition that selects it and the values it narrows."""
    out = {"must": c.get("required") or [], "should": c.get("recommended") or []}
    if not edge:
        ed = c.get("edges") or {}
        if not case or ed.get("required") or ed.get("recommended"):
            out["edges"] = {"must": ed.get("required") or [], "should": ed.get("recommended") or []}
    for k in ("values", "units") if case else ():      # a label's own narrowings are not listed
        if c.get(k):
            out[k] = c[k]
    if c.get("when"):
        out["when"] = [{**x["if"], **_items(x, edge, case=True)} for x in c["when"]]
    return out


def describe(spec: dict, names: list[str] | None = None, profile: str | None = None) -> dict:
    """Labels and edge types with their properties, as an agent or a person reads them before curating.

    With a profile, properties added by extensions of other driving forces are left out."""
    exts = _extensions_for(spec, profile)
    # the file that declares a label ("kernel" or the domain's name); a manifest that lists modules keeps their key
    owner = "module" if any(m.get("kind") == "module" for m in spec.get("modules", {}).values()) else "defined_in"

    def keep(d: dict) -> bool:
        return exts is None or not d.get("added_by") or d["added_by"] in exts

    def lab(n: str) -> dict:
        d = spec["nodes"][n]
        return {"is_a": d.get("ancestors") or [], owner: d.get("module"), "description": d.get("description"),
                **({"maps_to": list(d["maps_to"])} if d.get("maps_to") else {}),
                "required": d.get("required") or [], "fixed": d.get("fixed") or {},
                "properties": {k: _ptype(v, spec) + (f" — {v['description']}" if v.get("description") else "")
                               for k, v in (d.get("properties") or {}).items() if keep(v)}}

    def edge(n: str) -> dict:
        d = spec["edges"][n]
        return {"from": d.get("from"), "to": d.get("to"), "description": d.get("description"), "specializes": d.get("specializes"),
                **({"maps_to": list(d["maps_to"])} if d.get("maps_to") else {}),
                "properties": {k: _ptype(v, spec) + (f" — {v['description']}" if v.get("description") else "")
                               for k, v in (d.get("properties") or {}).items()}}

    wanted = names or sorted(spec["nodes"]) + sorted(spec["edges"])
    unknown = [n for n in wanted if n not in spec["nodes"] and n not in spec["edges"]]
    if unknown:
        raise ScaleError(f"not a label or edge type: {unknown}")
    out = {"schema_version": spec["version"], "profile": profile, "labels": {}, "edges": {}}
    if profile and (spec["profiles"][profile.split("@")[0]] or {}).get("domain"):
        eff = spec["profiles"][profile.split("@")[0]]["effective"]
        out = {"schema_version": spec["version"], "domain": profile, "labels": {}, "edges": {},
               "checklist": {"labels": {lab: {**_items(c), **({"unless": c["unless"]} if c.get("unless") else {})}
                                        for lab, c in eff["constraints"].items()},
                             "edges": {e: _items(c, edge=True) for e, c in eff["edge_constraints"].items()}}}
    for n in wanted:
        if n in spec["nodes"]:
            out["labels"][n] = lab(n)
        else:
            out["edges"][n] = edge(n)
    if not names:
        out["value_fields"] = sorted(spec["value"]["fields"])
        out["evidence_fields"] = sorted(spec["evidence"]["fields"])
        for t in STRUCTURES:                   # a kernel structure that properties use as their type (status_check)
            if isinstance(spec.get(t), dict) and spec[t].get("fields"):
                out[f"{t}_fields"] = sorted(spec[t]["fields"])
    return out
