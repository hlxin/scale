"""SCALE's terms mapped to terms of other ontologies (docs/mappings.md).

SCALE does not take its meaning from an ontology. A mapping says how a SCALE term relates to a term someone else
defines (the same, nearly the same, broader, narrower or only related, as SKOS mapping relations say), so that
data can be found and exchanged across both. The mappings are kept beside the schema, one set per layer
(``core/mappings/kernel.yaml`` for the science kernel, ``domain/mappings/catalysis.yaml`` for the catalysis
domain), with the registry of the ontologies they cite (``core/mappings/ontologies.yaml``). A mapping changes
nothing that SCALE validates or queries, so it is corrected without a new schema version; :func:`check` keeps
every mapping on a term the head schema declares and on a term of a registered ontology.

    scale schema mappings [--layer kernel|catalysis] [--format text|json|sssom] [--areas] [--check]

A mapping's subject is written as a SCALE term: a label (``Catalyst``) or an edge type (``HAS_INPUT``), a
property (``Label.property``) or a value of one (``Label.property=value``). The kernel's set also maps the quantity
kinds (``kinds``, by name) and the units its unit vocabulary reads (``units``, spelled as SCALE reads them). A
mapping's ``term`` is a CURIE of a registered ontology.

The catalysis set also carries ``areas``: the areas of catalysis research by which Ontologies4Cat classifies
ontologies (Behr, Borgelt and Kockmann 2024), with the SCALE labels and edge types that record each area and the
ontologies the collection classifies under it (:func:`areas`).
"""

from __future__ import annotations

import re
from pathlib import Path

from . import layout
from .util import ScaleError, load_yaml

# how a SCALE term relates to the other term, by the SKOS mapping relation each word stands for
MATCHES = {"exact": "skos:exactMatch", "close": "skos:closeMatch", "broad": "skos:broadMatch",
           "narrow": "skos:narrowMatch", "related": "skos:relatedMatch"}
REGISTRY_KEYS = {"name": True, "iri": True, "pattern": True, "homepage": False, "licence": False, "checked": True,
                 "ontologies4cat": False}
SET_KEYS = {"mapping_set": True, "title": True, "maps": True, "checked": True, "mappings": True, "kinds": False,
            "units": False, "areas": False}
# a set's sections of mappings and how rows show their subjects: terms as written, quantity kinds and units tagged
SECTIONS = (("mappings", ""), ("kinds", "kind:"), ("units", "unit:"))
MAPPING_KEYS = {"match": True, "term": True, "label": True, "note": False}
AREA_KEYS = {"title": True, "scale": True, "gap": False, "ontologies4cat": True}
# the areas of catalysis research of Ontologies4Cat (Behr, Borgelt and Kockmann, J. Cheminform. 2024, 16, 16),
# in the order of its classification scheme
AREAS = ("biocatalysis", "heterogeneous_catalysis", "homogeneous_catalysis", "photocatalysis", "electrocatalysis",
         "chemical_substance_modelling", "material_modelling", "process_modelling", "synthesis_data",
         "operando_data", "performance_data", "characterisation_data", "heat_transport_and_kinetic_data",
         "process_design_energy_and_cost_data")
CURIE = re.compile(r"^(?P<prefix>[A-Za-z][A-Za-z0-9_-]*):(?P<local>\S+)$")
# the layers, the file of each set, the module a label or edge type of it is declared by, and the SSSOM prefix
# of its terms (expanded to the schema file that declares them)
LAYERS = {"kernel": (layout.KERNEL_MAPPINGS, "kernel", "scalekernel", layout.KERNEL),
          "catalysis": (layout.DOMAIN_MAPPINGS, "catalysis", "scalecatal", "domain/graph/catalysis.yaml")}


def registry(repo: Path) -> dict:
    """The registered ontologies by prefix (``core/mappings/ontologies.yaml``)."""
    p = Path(repo) / layout.ONTOLOGY_REGISTRY
    if not p.is_file():
        raise ScaleError(f"{layout.ONTOLOGY_REGISTRY} is missing: the registry of the ontologies mappings cite")
    return (load_yaml(p) or {}).get("ontologies") or {}


def load_set(repo: Path, layer: str) -> dict | None:
    """A layer's mapping set (None when the layer has none)."""
    p = Path(repo) / LAYERS[layer][0]
    return (load_yaml(p) or {}) if p.is_file() else None


def iri(term: str, reg: dict) -> str | None:
    """The IRI a CURIE of a registered ontology stands for (None for an unregistered prefix)."""
    m = CURIE.match(term or "")
    if not m or m["prefix"] not in reg:
        return None
    return f"{reg[m['prefix']]['iri']}{m['local']}"


def entries(doc: dict) -> list[tuple[str, str, str, object]]:
    """A set's subjects in file order: (section, the subject as listed, the subject as rows show it, its mappings)."""
    return [(section, str(subject), f"{tag}{subject}", ms)
            for section, tag in SECTIONS for subject, ms in (doc.get(section) or {}).items()]


def quantity_problem(spec: dict, section: str, name: str) -> str | None:
    """Why ``name`` is no quantity kind (``kinds``) or no unit the unit vocabulary reads (``units``); None when it is."""
    from .quantities import contracts
    qc = contracts(spec)
    if qc is None:
        return "the schema has no quantity contracts"
    if section == "kinds":
        return None if name in qc.kinds else f"no quantity kind {name!r}"
    reading = qc.read_unit(name)
    return None if reading.read and not reading.unread else f"the unit vocabulary does not read {name!r}"


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
    every match a known word, no term twice for one subject; the areas known and naming existing labels and edge
    types. Errors fail ``scale domains check``; warnings inform."""
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
    for layer, (rel, _, _, _) in LAYERS.items():
        doc = load_set(repo, layer)
        if doc is None:
            continue
        for k in sorted(set(doc) - set(SET_KEYS)):
            err(rel, f"unknown key {k!r} ({', '.join(SET_KEYS)})")
        for k, req in SET_KEYS.items():
            if req and k not in doc:
                err(rel, f"{k} is required")
        if doc.get("areas") and layer != "catalysis":
            err(rel, "areas are areas of catalysis research; they belong to the catalysis set")
        n = 0
        for section, name, subject, ms in entries(doc):
            if section == "mappings":
                why = subject_problem(spec, name, layer)
            elif layer != "kernel":
                why = f"quantity kinds and units are the kernel's; map them in {layout.KERNEL_MAPPINGS}"
            else:
                why = quantity_problem(spec, section, name)
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
        areas_ = doc.get("areas") or {}
        for a in sorted(set(areas_) - set(AREAS)):
            err(rel, f"areas: unknown area {a!r} (the areas of Ontologies4Cat: {', '.join(AREAS)})")
        for a, d in areas_.items():
            if not isinstance(d, dict):
                err(rel, f"areas.{a}: an area is a mapping of title, scale, gap and ontologies4cat")
                continue
            for k in sorted(set(d) - set(AREA_KEYS)):
                err(rel, f"areas.{a}: unknown key {k!r} ({', '.join(AREA_KEYS)})")
            for k, req in AREA_KEYS.items():
                if req and k not in d:
                    err(rel, f"areas.{a}: {k} is required")
            for t in d.get("scale") or []:
                if t not in spec["nodes"] and t not in spec["edges"]:
                    err(rel, f"areas.{a}: {t} is no label or edge type of the schema")
            o4c = d.get("ontologies4cat") or {}
            for k in sorted(set(o4c) - {"contained", "related"}):
                err(rel, f"areas.{a}.ontologies4cat: unknown key {k!r} (contained, related)")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "counts": counts}


def index(repo: Path, layers: tuple[str, ...] = ("kernel", "catalysis")) -> dict[str, list[dict]]:
    """Every mapping by its subject, each with the IRI its term stands for (what ``describe`` shows)."""
    reg = registry(repo)
    out: dict[str, list[dict]] = {}
    for layer in layers:
        doc = load_set(repo, layer) or {}
        for _, _, subject, ms in entries(doc):
            for m in ms or []:
                out.setdefault(subject, []).append(
                    {"match": m.get("match"), "term": m.get("term"), "label": m.get("label"),
                     "iri": iri(str(m.get("term") or ""), reg), **({"note": m["note"]} if m.get("note") else {})})
    return out


def rows(repo: Path, layer: str | None = None) -> list[dict]:
    """The mappings as rows (layer, subject, match, term, label, iri, note), set by set in file order."""
    reg = registry(repo)
    out = []
    for lay in ([layer] if layer else list(LAYERS)):
        doc = load_set(repo, lay) or {}
        for _, _, subject, ms in entries(doc):
            for m in ms or []:
                out.append({"layer": lay, "subject": subject, "match": m.get("match"), "term": m.get("term"),
                            "label": m.get("label"), "iri": iri(str(m.get("term") or ""), reg),
                            "note": m.get("note")})
    return out


def text(repo: Path, layer: str | None = None) -> str:
    """The mappings as a reader scans them: subject, match, term and its label."""
    lines = []
    for r in rows(repo, layer):
        lines.append(f"{r['subject']:<46} {r['match']:<8} {r['term']:<30} {r['label']}")
    return "\n".join(lines)


def sssom(repo: Path, layer: str, version: str | None = None) -> str:
    """A layer's set in the SSSOM TSV form (Simple Standard for Sharing Ontological Mappings): its metadata as
    commented YAML, then one row per mapping. A SCALE term's identifier is the schema file that declares it
    followed by the term (``scalecatal:Treatment.treatment_kind=calcination``)."""
    reg = registry(repo)
    rel, _, prefix, schema_file = LAYERS[layer]
    doc = load_set(repo, layer)
    if doc is None:
        raise ScaleError(f"the {layer} layer has no mapping set ({rel})")
    used = sorted({CURIE.match(str(m.get("term")))["prefix"] for _, _, _, ms in entries(doc)
                   for m in ms or [] if CURIE.match(str(m.get("term") or ""))})
    base = f"{layout.REPOSITORY_URL}/blob/main"
    curie_map = {prefix: f"{base}/{schema_file}#", "semapv": "https://w3id.org/semapv/vocab/",
                 "skos": "http://www.w3.org/2004/02/skos/core#", **{p: reg[p]["iri"] for p in used if p in reg}}
    head = [f"mapping_set_id: {base}/{rel}", f"mapping_set_title: {doc.get('title')}",
            "license: https://creativecommons.org/licenses/by/4.0/", f"mapping_date: '{doc.get('checked')}'",
            f"subject_source: {base}/{schema_file}", *([f"subject_source_version: {version}"] if version else []),
            "curie_map:", *[f"  {k}: {v}" for k, v in curie_map.items()]]
    cols = ("subject_id", "subject_label", "predicate_id", "object_id", "object_label", "mapping_justification",
            "comment")
    clean = lambda s: " ".join(str(s or "").split())     # noqa: E731  (no tab or line break inside a cell)
    out = [f"# {h}" for h in head] + ["\t".join(cols)]
    for section, name, _, ms in entries(doc):
        local = name if section == "mappings" else f"{section[:-1]}/{name}"      # kind/temperature, unit/kPa
        for m in ms or []:
            out.append("\t".join([f"{prefix}:{local}", clean(name), MATCHES.get(m.get("match"), ""),
                                  clean(m.get("term")), clean(m.get("label")), "semapv:ManualMappingCuration",
                                  clean(m.get("note"))]))
    return "\n".join(out) + "\n"


def areas(repo: Path) -> list[dict]:
    """The areas of catalysis research: for each, the SCALE labels and edge types that record it, what SCALE
    lacks for it, the ontologies Ontologies4Cat classifies under it, and those of them SCALE's mappings cite."""
    reg = registry(repo)
    cited = {CURIE.match(str(r["term"]))["prefix"] for r in rows(repo) if CURIE.match(str(r["term"] or ""))}
    cited_o4c = {reg[p].get("ontologies4cat") for p in cited if p in reg and reg[p].get("ontologies4cat")}
    doc = load_set(repo, "catalysis") or {}
    out = []
    for a in AREAS:
        d = (doc.get("areas") or {}).get(a)
        if d is None:
            continue
        o4c = d.get("ontologies4cat") or {}
        named = [*(o4c.get("contained") or []), *(o4c.get("related") or [])]
        out.append({"area": a, "title": d.get("title"), "scale": list(d.get("scale") or []), "gap": d.get("gap"),
                    "contained": list(o4c.get("contained") or []), "related": list(o4c.get("related") or []),
                    "mapped": [o for o in named if o in cited_o4c]})
    return out


def areas_text(repo: Path) -> str:
    lines = []
    for r in areas(repo):
        lines.append(f"{r['title']}")
        lines.append(f"  SCALE:       {', '.join(r['scale']) or 'nothing yet'}")
        if r["gap"]:
            lines.append(f"  gap:         {' '.join(str(r['gap']).split())}")
        lines.append(f"  contains it: {', '.join(r['contained']) or 'no ontology (Ontologies4Cat)'}")
        lines.append(f"  related:     {', '.join(r['related']) or 'none'}")
        lines.append(f"  SCALE maps to: {', '.join(r['mapped']) or 'none of them'}")
    return "\n".join(lines)
