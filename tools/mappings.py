"""SCALE's terms mapped to terms of other ontologies (docs/mappings.md).

SCALE does not take its meaning from an ontology. A mapping says how a SCALE term relates to a term someone else
defines (the same, nearly the same, broader, narrower or only related, as SKOS mapping relations say), so that
data can be found and exchanged across both. The mappings are kept beside the schema, one set per layer
(``core/mappings/kernel.yaml`` for the science kernel, ``domain/mappings/catalysis.yaml`` for the catalysis
domain), with the registry of the ontologies they cite (``core/mappings/ontologies.yaml``). A mapping changes
nothing that SCALE validates or queries, so it is corrected without a new schema version; :func:`check` keeps
every mapping on a term the head schema declares and on a term of a registered ontology.

    scale schema mappings [--layer kernel|catalysis] [--format text|json|sssom] [--subdomains] [--check]

A mapping's subject is written as a SCALE term: a label (``Catalyst``) or an edge type (``HAS_INPUT``), a
property (``Label.property``) or a value of one (``Label.property=value``). Its ``term`` is a CURIE of a registered
ontology.

The catalysis set also carries ``subdomains``: the subdomains of catalysis research by which Ontologies4Cat
classifies ontologies (Behr, Borgelt and Kockmann 2024), with the SCALE labels and edge types that record each and
how the authors' collection rates the ontologies it holds for it (:func:`subdomains`).
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from urllib.parse import quote

import yaml

from . import layout
from .util import ScaleError, load_yaml

# how a SCALE term relates to the other term, by the SKOS mapping relation each word stands for
MATCHES = {"exact": "skos:exactMatch", "close": "skos:closeMatch", "broad": "skos:broadMatch",
           "narrow": "skos:narrowMatch", "related": "skos:relatedMatch"}
REGISTRY_KEYS = {"name": True, "iri": True, "pattern": True, "homepage": False, "licence": False, "checked": True,
                 "ontologies4cat": False}
SET_KEYS = {"mapping_set": True, "title": True, "maps": True, "checked": True, "mappings": True,
            "subdomains": False}
MAPPING_KEYS = {"match": True, "term": True, "label": True, "note": False}
SUBDOMAIN_KEYS = {"title": True, "scale": True, "gap": False, "ontologies4cat": True}
# how the Ontologies4Cat collection rates an ontology for a subdomain ("related: narrower" and "related: broader"
# in its words); an ontology it rates missing is not listed
RATINGS = ("contained", "related_narrower", "related_broader")
# the subdomains of catalysis research of Ontologies4Cat (Behr, Borgelt and Kockmann, J. Cheminform. 2024, 16,
# 16), in the order of its classification scheme
SUBDOMAINS = ("biocatalysis", "heterogeneous_catalysis", "homogeneous_catalysis", "photocatalysis",
              "electrocatalysis", "chemical_substance_modelling", "material_modelling", "process_modelling",
              "synthesis_data", "operando_data", "performance_data", "characterisation_data",
              "heat_transport_and_kinetic_data", "process_design_energy_and_cost_data")
CURIE = re.compile(r"^(?P<prefix>[A-Za-z][A-Za-z0-9_-]*):(?P<local>\S+)$")
# the layers, the file of each set, the module a label or edge type of it is declared by, and the SSSOM prefix
# of its terms (expanded to the schema file that declares them)
LAYERS = {"kernel": (layout.KERNEL_MAPPINGS, "kernel", "scalekernel", layout.KERNEL),
          "catalysis": (layout.DOMAIN_MAPPINGS, "catalysis", "scalecatal", "domain/graph/catalysis.yaml")}
# the file that declares each layer's set (`mappings:`); a declared set must exist
DECLARED_BY = {"kernel": layout.CORE_MANIFEST, "catalysis": layout.DOMAIN_DECLARATION}


class _UniqueKeys(yaml.SafeLoader):
    """A safe loader that refuses a key given twice in one mapping: ``yaml.safe_load`` keeps the second and drops
    the first silently, which would lose a subject's mappings or a registry entry."""


def _unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict:
    loader.flatten_mapping(node)
    seen = set()
    for k, _ in node.value:
        key = loader.construct_object(k, deep=True)
        try:
            if key in seen:
                raise ScaleError(f"line {k.start_mark.line + 1}: {key!r} is given twice; the second would hide "
                                 "the first")
            seen.add(key)
        except TypeError:          # an unhashable key: construct_mapping says why
            pass
    return loader.construct_mapping(node, deep=True)


_UniqueKeys.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _load(repo: Path, rel: str):
    """A mapping file (YAML), refusing a key given twice."""
    try:
        with open(Path(repo) / rel, encoding="utf-8") as fh:
            return yaml.load(fh, Loader=_UniqueKeys)      # a safe loader
    except ScaleError as exc:
        raise ScaleError(f"{rel}: {exc}") from None
    except yaml.YAMLError as exc:
        raise ScaleError(f"{rel}: not valid YAML ({' '.join(str(exc).split())})") from None


def _section(doc: dict, key: str = "mappings") -> dict:
    """A section of a set keyed by subject (or subdomain); empty when missing or malformed, which :func:`check`
    reports."""
    s = doc.get(key)
    return s if isinstance(s, dict) else {}


def _listed(ms) -> list[dict]:
    """The well-formed mappings of one subject; :func:`check` reports the others."""
    return [m for m in ms if isinstance(m, dict)] if isinstance(ms, list) else []


def registry(repo: Path) -> dict:
    """The registered ontologies by prefix (``core/mappings/ontologies.yaml``)."""
    p = Path(repo) / layout.ONTOLOGY_REGISTRY
    if not p.is_file():
        raise ScaleError(f"{layout.ONTOLOGY_REGISTRY} is missing: the registry of the ontologies mappings cite")
    doc = _load(repo, layout.ONTOLOGY_REGISTRY)
    reg = doc.get("ontologies") if isinstance(doc, dict) else None
    if not isinstance(reg, dict):
        raise ScaleError(f"{layout.ONTOLOGY_REGISTRY}: `ontologies` is a mapping of prefixes to their entries")
    return reg


def load_set(repo: Path, layer: str) -> dict | None:
    """A layer's mapping set (None when the layer has none)."""
    rel = LAYERS[layer][0]
    if not (Path(repo) / rel).is_file():
        return None
    doc = _load(repo, rel)
    if not isinstance(doc, dict):
        raise ScaleError(f"{rel}: a mapping set is a mapping of {', '.join(SET_KEYS)}")
    return doc


def declared(repo: Path) -> dict[str, str]:
    """The layers whose declaration (core/CORE.yaml, domain/DOMAIN.yaml) names a mapping set, with that file."""
    out = {}
    for layer, rel in DECLARED_BY.items():
        p = Path(repo) / rel
        doc = load_yaml(p) if p.is_file() else None
        if isinstance(doc, dict) and doc.get("mappings"):
            out[layer] = rel
    return out


def iri(term: str, reg: dict) -> str | None:
    """The IRI a CURIE of a registered ontology stands for (None for an unregistered prefix)."""
    m = CURIE.match(term or "")
    e = reg.get(m["prefix"]) if m else None
    if not isinstance(e, dict) or not e.get("iri"):
        return None
    return f"{e['iri']}{m['local']}"


def head_spec(repo: Path) -> dict:
    from . import pgraph
    return pgraph.load_spec(Path(repo) / layout.DOMAIN / layout.DOMAIN_GRAPH_MANIFEST)


def subject_problem(spec: dict, subject: str, layer: str | None = None) -> str | None:
    """Why ``subject`` names no term of ``spec`` (None when it does). A label or edge type of a layer's set is one
    that layer declares; a property or value may be one a domain adds to a kernel label."""
    m = re.fullmatch(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\.(?P<prop>[A-Za-z_][A-Za-z0-9_]*)(?:=(?P<value>.+))?)?",
                     subject)
    if not m:
        return "not a term (Label, EDGE, Label.property or Label.property=value)"
    d = spec["nodes"].get(m["name"]) or spec["edges"].get(m["name"])
    if d is None:
        return f"no label or edge type {m['name']}"
    if layer and not m["prop"] and d.get("module") != LAYERS[layer][1]:
        return f"{m['name']} is declared by {d.get('module')}, not by the {layer} layer"
    if not m["prop"]:
        return None
    p = (d.get("properties") or {}).get(m["prop"])
    if p is None:
        return f"{m['name']} has no property {m['prop']}"
    if m["value"] is None:
        return None
    items = p.get("items") if isinstance(p.get("items"), dict) else {}
    values = p.get("values") or items.get("values")
    if not values:
        return f"{m['name']}.{m['prop']} is not an enumeration"
    return None if m["value"] in values else f"{m['name']}.{m['prop']} has no value {m['value']!r}"


def check(repo: Path, spec: dict | None = None) -> dict:
    """The registry and each layer's set: every key known, every subject a term of the head schema (for a layer's
    labels and edge types, one that layer declares), every term a CURIE of a registered ontology in its pattern,
    every match a known word, no term twice for one subject; the subdomains known, naming existing labels and edge
    types, and rating each ontology once. Errors fail ``scale domains check``; warnings inform."""
    repo = Path(repo)
    errors: list[dict] = []
    warnings: list[dict] = []
    err = lambda where, msg: errors.append({"where": where, "message": msg})      # noqa: E731
    warn = lambda where, msg: warnings.append({"where": where, "message": msg})   # noqa: E731
    try:
        reg = registry(repo)
    except ScaleError as e:
        return {"ok": False, "errors": [{"where": layout.ONTOLOGY_REGISTRY, "message": str(e)}], "warnings": [],
                "counts": {}}
    rw = layout.ONTOLOGY_REGISTRY
    patterns: dict[str, re.Pattern] = {}
    for prefix, e in sorted(reg.items()):
        if not isinstance(e, dict):
            err(rw, f"{prefix}: an entry is a mapping of name, iri, pattern, checked, …")
            continue
        for k in sorted(set(e) - set(REGISTRY_KEYS)):
            err(rw, f"{prefix}: unknown key {k!r} ({', '.join(REGISTRY_KEYS)})")
        for k, req in REGISTRY_KEYS.items():
            if req and not e.get(k):
                err(rw, f"{prefix}: {k} is required")
        if e.get("iri") and not re.match(r"^https?://\S+$", str(e["iri"])):
            err(rw, f"{prefix}: iri {e['iri']!r} is not an http(s) IRI")
        try:
            pat = re.compile(str(e.get("pattern") or ""))
            if not str(e.get("pattern") or "").startswith(f"^{prefix}:") or not str(e["pattern"]).endswith("$"):
                err(rw, f"{prefix}: pattern must match a whole CURIE, ^{prefix}:…$")
            patterns[prefix] = pat
        except re.error as x:
            err(rw, f"{prefix}: pattern does not compile ({x})")
    spec = spec if spec is not None else head_spec(repo)
    counts = {}
    must = declared(repo)
    for layer, (rel, _, _, _) in LAYERS.items():
        try:
            doc = load_set(repo, layer)
        except ScaleError as exc:
            err(rel, str(exc))
            continue
        if doc is None:
            if layer in must:
                err(rel, f"is missing; {must[layer]} declares it (mappings)")
            continue
        for k in sorted(set(doc) - set(SET_KEYS)):
            err(rel, f"unknown key {k!r} ({', '.join(SET_KEYS)})")
        for k, req in SET_KEYS.items():
            if req and k not in doc:
                err(rel, f"{k} is required")
        for k in ("mappings", "subdomains"):
            if doc.get(k) is not None and not isinstance(doc[k], dict):
                err(rel, f"{k} is a mapping keyed by {'subject' if k == 'mappings' else 'subdomain'}")
        if doc.get("subdomains") and layer != "catalysis":
            err(rel, "subdomains are subdomains of catalysis research; they belong to the catalysis set")
        n = 0
        for subject, ms in _section(doc).items():
            why = subject_problem(spec, str(subject), layer)
            if why:
                err(rel, f"{subject}: {why}")
            if not isinstance(ms, list) or not ms:
                err(rel, f"{subject}: a subject lists its mappings (match, term, label)")
                continue
            seen: set[str] = set()
            exact: dict[str, str] = {}
            for i, m in enumerate(ms):
                n += 1
                where = f"{subject}[{i}]"
                if not isinstance(m, dict):
                    err(rel, f"{where}: a mapping is a mapping of match, term, label and an optional note")
                    continue
                for k in sorted(set(m) - set(MAPPING_KEYS)):
                    err(rel, f"{where}: unknown key {k!r} ({', '.join(MAPPING_KEYS)})")
                for k, req in MAPPING_KEYS.items():
                    if req and not m.get(k):
                        err(rel, f"{where}: {k} is required")
                if m.get("match") and m["match"] not in MATCHES:
                    err(rel, f"{where}: match {m['match']!r} is not one of {', '.join(MATCHES)}")
                term = str(m.get("term") or "")
                c = CURIE.match(term)
                if term and not c:
                    err(rel, f"{where}: term {term!r} is not a CURIE (prefix:local)")
                elif c and c["prefix"] not in reg:
                    err(rel, f"{where}: {c['prefix']} is not a registered ontology ({rw})")
                elif c and c["prefix"] in patterns and not patterns[c["prefix"]].match(term):
                    err(rel, f"{where}: {term} does not look like a {c['prefix']} term ({reg[c['prefix']]['pattern']})")
                if term in seen:
                    err(rel, f"{where}: {term} is mapped twice for {subject}")
                seen.add(term)
                if c and m.get("match") == "exact":
                    if c["prefix"] in exact:
                        warn(rel, f"{subject}: two exact matches in {c['prefix']} ({exact[c['prefix']]} and {term}); "
                                  "an exact match is the one term of that ontology meaning the same")
                    exact[c["prefix"]] = term
        counts[layer] = n
        subdomains_ = _section(doc, "subdomains")
        for a in sorted(set(subdomains_) - set(SUBDOMAINS)):
            err(rel, f"subdomains: unknown subdomain {a!r} (the subdomains of Ontologies4Cat: {', '.join(SUBDOMAINS)})")
        for a, d in subdomains_.items():
            where = f"subdomains.{a}"
            if not isinstance(d, dict):
                err(rel, f"{where}: a subdomain is a mapping of title, scale, gap and ontologies4cat")
                continue
            for k in sorted(set(d) - set(SUBDOMAIN_KEYS)):
                err(rel, f"{where}: unknown key {k!r} ({', '.join(SUBDOMAIN_KEYS)})")
            for k, req in SUBDOMAIN_KEYS.items():
                if req and k not in d:
                    err(rel, f"{where}: {k} is required")
            if not isinstance(d.get("scale") or [], list):
                err(rel, f"{where}: scale is a list of labels and edge types")
            for t in d.get("scale") if isinstance(d.get("scale"), list) else []:
                if t not in spec["nodes"] and t not in spec["edges"]:
                    err(rel, f"{where}: {t} is no label or edge type of the schema")
            o4c = d.get("ontologies4cat") or {}
            if not isinstance(o4c, dict):
                err(rel, f"{where}.ontologies4cat: a mapping of {', '.join(RATINGS)}")
                o4c = {}
            for k in sorted(set(o4c) - set(RATINGS)):
                err(rel, f"{where}.ontologies4cat: unknown key {k!r} ({', '.join(RATINGS)})")
            rated: dict[str, str] = {}
            for k in RATINGS:
                names = o4c.get(k) or []
                if not isinstance(names, list):
                    err(rel, f"{where}.ontologies4cat.{k}: a list of ontology acronyms")
                    continue
                for o in names:
                    if o in rated:
                        err(rel, f"{where}.ontologies4cat: {o} is rated twice ({rated[o]} and {k})")
                    rated[o] = k
    return {"ok": not errors, "errors": errors, "warnings": warnings, "counts": counts}


def index(repo: Path, layers: tuple[str, ...] = ("kernel", "catalysis")) -> dict[str, list[dict]]:
    """Every mapping by its subject, each with the IRI its term stands for (what ``describe`` shows)."""
    reg = registry(repo)
    out: dict[str, list[dict]] = {}
    for layer in layers:
        doc = load_set(repo, layer) or {}
        for subject, ms in _section(doc).items():
            for m in _listed(ms):
                out.setdefault(str(subject), []).append(
                    {"match": m.get("match"), "term": m.get("term"), "label": m.get("label"),
                     "iri": iri(str(m.get("term") or ""), reg), **({"note": m["note"]} if m.get("note") else {})})
    return out


def rows(repo: Path, layer: str | None = None) -> list[dict]:
    """The mappings as rows (layer, subject, match, term, label, iri, note), set by set in file order."""
    reg = registry(repo)
    out = []
    for lay in ([layer] if layer else list(LAYERS)):
        doc = load_set(repo, lay) or {}
        for subject, ms in _section(doc).items():
            for m in _listed(ms):
                out.append({"layer": lay, "subject": str(subject), "match": m.get("match"), "term": m.get("term"),
                            "label": m.get("label"), "iri": iri(str(m.get("term") or ""), reg),
                            "note": m.get("note")})
    return out


def text(repo: Path, layer: str | None = None) -> str:
    """The mappings as a reader scans them: subject, match, term and its label."""
    lines = []
    for r in rows(repo, layer):
        lines.append(f"{r['subject']:<46} {r['match']:<8} {r['term']:<30} {r['label']}")
    return "\n".join(lines)


def _local(subject: str) -> str:
    """A SCALE term as the local part of a CURIE: what an IRI does not allow (a space, %, a non-ASCII letter) is
    percent-encoded; the term itself is the row's label."""
    return quote(subject, safe="/=()")


def sssom(repo: Path, layer: str, version: str | None = None) -> str:
    """A layer's set in the SSSOM TSV form (Simple Standard for Sharing Ontological Mappings): its metadata as
    commented YAML, then one row per mapping, cells quoted where a value holds a double quote. A SCALE term's
    identifier is the schema file that declares it followed by the term
    (``scalecatal:Treatment.treatment_kind=calcination``); every identifier is a CURIE of the ``curie_map``."""
    reg = registry(repo)
    rel, _, prefix, schema_file = LAYERS[layer]
    doc = load_set(repo, layer)
    if doc is None:
        raise ScaleError(f"the {layer} layer has no mapping set ({rel})")
    used = sorted({CURIE.match(str(m.get("term")))["prefix"] for ms in _section(doc).values()
                   for m in _listed(ms) if CURIE.match(str(m.get("term") or ""))})
    base = f"{layout.REPOSITORY_URL}/blob/main"
    curie_map = {prefix: f"{base}/{schema_file}#", "scale": f"{base}/", "semapv": "https://w3id.org/semapv/vocab/",
                 "skos": "http://www.w3.org/2004/02/skos/core#",
                 **{p: reg[p]["iri"] for p in used if isinstance(reg.get(p), dict) and reg[p].get("iri")}}
    meta = {"mapping_set_id": f"{base}/{rel}", "mapping_set_title": str(doc.get("title") or ""),
            "license": "https://creativecommons.org/licenses/by/4.0/", "mapping_date": str(doc.get("checked")),
            "subject_source": f"scale:{schema_file}",
            **({"subject_source_version": str(version)} if version else {}), "curie_map": curie_map}
    head = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=10_000).splitlines()
    cols = ("subject_id", "subject_label", "predicate_id", "object_id", "object_label", "mapping_justification",
            "comment")
    clean = lambda s: " ".join(str(s or "").split())     # noqa: E731  (no tab or line break inside a cell)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t", lineterminator="\n")     # quotes a cell holding a double quote
    w.writerow(cols)
    for subject, ms in _section(doc).items():
        for m in _listed(ms):
            w.writerow([f"{prefix}:{_local(str(subject))}", clean(subject), MATCHES.get(m.get("match"), ""),
                        clean(m.get("term")), clean(m.get("label")), "semapv:ManualMappingCuration",
                        clean(m.get("note"))])
    return "".join(f"# {h}\n" for h in head) + buf.getvalue()


def subdomains(repo: Path) -> list[dict]:
    """The subdomains of catalysis research: for each, the SCALE labels and edge types that record it, what SCALE
    lacks for it, how the Ontologies4Cat collection rates the ontologies it holds for it, and those of them SCALE's
    mappings cite."""
    reg = registry(repo)
    cited = {CURIE.match(str(r["term"]))["prefix"] for r in rows(repo) if CURIE.match(str(r["term"] or ""))}
    cited_o4c = {reg[p].get("ontologies4cat") for p in cited if isinstance(reg.get(p), dict)
                 and reg[p].get("ontologies4cat")}
    doc = load_set(repo, "catalysis") or {}
    out = []
    for a in SUBDOMAINS:
        d = _section(doc, "subdomains").get(a)
        if not isinstance(d, dict):
            continue
        o4c = d.get("ontologies4cat") if isinstance(d.get("ontologies4cat"), dict) else {}
        rated = {k: [str(o) for o in o4c.get(k)] if isinstance(o4c.get(k), list) else [] for k in RATINGS}
        out.append({"subdomain": a, "title": d.get("title"), "scale": list(d.get("scale") or []),
                    "gap": d.get("gap"), **rated,
                    "mapped": [o for k in RATINGS for o in rated[k] if o in cited_o4c]})
    return out


def subdomains_text(repo: Path) -> str:
    lines = []
    for r in subdomains(repo):
        lines.append(f"{r['title']}")
        lines.append(f"  SCALE:             {', '.join(r['scale']) or 'nothing yet'}")
        if r["gap"]:
            lines.append(f"  gap:               {' '.join(str(r['gap']).split())}")
        lines.append(f"  contains it:       {', '.join(r['contained']) or 'no ontology (Ontologies4Cat)'}")
        lines.append(f"  related, narrower: {', '.join(r['related_narrower']) or 'none'}")
        lines.append(f"  related, broader:  {', '.join(r['related_broader']) or 'none'}")
        lines.append(f"  SCALE maps to:     {', '.join(r['mapped']) or 'none of them'}")
    return "\n".join(lines)
