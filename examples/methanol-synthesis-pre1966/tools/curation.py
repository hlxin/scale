"""Curate the frozen methanol-synthesis corpus into scale-graph (the head version), one source at a time.

    python curation.py brief SLUG              # what a curator needs for one source (writes work/briefs/SLUG/)
    python curation.py check FRAGMENT.json     # validate one curated fragment against the schema and the source text
    python curation.py assemble [--out G.json] # merge every fragment into the graph, with the evidence and passage indexes
    python curation.py status                  # which in-scope sources have a fragment, and whether it passes
    python curation.py bundle [--previous DIR] # the GALAXY knowledge-graph bundle (galaxy/methanol-synthesis_v<version>/)

A **fragment** is the curation of one source (``curation/fragments/<slug>.json``)::

    {"source": "<slug>", "schema_version": "0.1.0", "domain": "thermocatalysis",
     "coverage": {"pages_read": "1-6", "not_read": "…", "notes": "…"},
     "nodes": [...], "links": [...],                  # scale-graph node-link records
     "gaps": [{"kind": "absent_source_information | ambiguous_source_information | missing_concept | extraction_error",
               "about": "<record id or topic>", "locator": "p. 3", "text": "…",
               "status": "open | resolved", "resolved_by": "scale-graph 0.1.0 | NNNNNN (a proposal id) | re-curation YYYY-MM-DD",
               "resolution": "how the records now say it"}]}

Records follow the scale-graph schema (``scale graph describe``). Ids start with ``ex:msyn/``:
shared chemistry (``ex:msyn/species/<formula>``, ``ex:msyn/reaction/<name>`` for the canonical
reactions in SHARED_REACTIONS) is merged across sources; everything else is scoped to its source
(``ex:msyn/<slug>/<kind>/<local>``). Every evidence item names the Source node, a locator that
starts with the PDF page (``p. 3``, optionally ``p. 3, Table II``) and, for a quote, text found
verbatim in the page texts. The Source node, the authors and the REPORTED_IN links are added by
the tools, not by the curator.

Deterministic for the same fragments and page texts.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

sys.dont_write_bytecode = True


def _repo_root(*starts: Path) -> Path:
    """The SCALE checkout (scale-release.yaml and releases/), searched upward from each start in turn."""
    for p in (q for s in starts for q in (s, *s.parents)):
        if (p / "scale-release.yaml").exists() and (p / "releases").is_dir():
            return p
    raise SystemExit("run inside a SCALE repository checkout: no scale-release.yaml and releases/ above "
                     + ", ".join(map(str, starts)))


HERE = Path(__file__).resolve().parent
EX = HERE.parent
REPO = _repo_root(HERE, Path.cwd())
sys.path.insert(0, str(REPO / "tools"))
from scale import layout, pgraph  # noqa: E402
from scale.passages import Index, evidence_items, locate, passages_of  # noqa: E402
from scale import sourcetext  # noqa: E402
from scale.util import ScaleError, dump_canonical, load_yaml, match_text  # noqa: E402

P = "ex:msyn"
# the curated data (fragments, second readings, the corpus manifest, the graphs, the GALAXY bundles) and the local work/
# are read from and written to the restricted copy, at the path the restricted copy holds it at
# (scale.layout.restricted_path). The partners cleared the curated data for publication: the public
# graph in this folder is the assembled graph moved to today's schema and capped (scale evidence cap), see README.md
DATA = layout.restricted_path(REPO, EX.relative_to(REPO))
SPEC = REPO / layout.DOMAIN / layout.DOMAIN_GRAPH_MANIFEST   # the catalysis layer's schema
WORK = DATA / "work"
FRAGMENTS = DATA / "curation" / "fragments"
MANIFEST = DATA / "corpus" / "manifest.json"
# the checklist every record follows: the one catalysis checklist of the head schema (scale-graph 0.4.0 on, proposal 000008); the
# fragments were curated under the consortium schema repository's scale-graph 0.1.0 (following its thermocatalysis@0.1.0
# profile); the public graph was moved to its 0.5.0 with that repository's tools and re-pinned to this repository's 0.1.0
DOMAIN = "catalysis"
STEWARDSHIP = {"access": "public", "project": "scale:project/arpa-e-catalyst",
               "contributed_by": ["scale:org/virginia-tech", "scale:org/alchemic-ai"],
               "note": "Curated by agents under the curate-source skill from the frozen corpus (corpus/manifest.json); "
                       "checked by the deterministic tools in tools/."}


def registry_nodes() -> tuple[list[dict], list[dict]]:
    import yaml
    reg = yaml.safe_load((REPO / layout.STEWARDSHIP).read_text())
    return pgraph.registry_records(reg, set(STEWARDSHIP["contributed_by"]) | {STEWARDSHIP["project"]})

SHARED_REACTIONS = {
    "co-hydrogenation-to-methanol": ("CO + 2 H2 -> CH3OH", "Methanol synthesis from carbon monoxide"),
    "co2-hydrogenation-to-methanol": ("CO2 + 3 H2 -> CH3OH + H2O", "Methanol synthesis from carbon dioxide"),
    "water-gas-shift": ("CO + H2O -> CO2 + H2", "Water-gas shift"),
    "reverse-water-gas-shift": ("CO2 + H2 -> CO + H2O", "Reverse water-gas shift"),
    "methanol-decomposition": ("CH3OH -> CO + 2 H2", "Methanol decomposition"),
    "methanol-dehydrogenation-to-formaldehyde": ("CH3OH -> HCHO + H2", "Methanol dehydrogenation to formaldehyde"),
    "dimethyl-ether-formation": ("2 CH3OH -> CH3OCH3 + H2O", "Dimethyl ether formation from methanol"),
    "co-methanation": ("CO + 3 H2 -> CH4 + H2O", "Methanation of carbon monoxide"),
    "co2-methanation": ("CO2 + 4 H2 -> CH4 + 2 H2O", "Methanation of carbon dioxide"),
    "boudouard": ("2 CO -> C + CO2", "Boudouard reaction"),
}
SHARED_SPECIES = {  # formula -> name; others may be added under ex:msyn/species/<formula slug>
    "H2": "hydrogen", "CO": "carbon monoxide", "CO2": "carbon dioxide", "CH3OH": "methanol", "H2O": "water",
    "CH4": "methane", "HCHO": "formaldehyde", "CH3OCH3": "dimethyl ether", "N2": "nitrogen", "H2S": "hydrogen sulfide",
    "ZnO": "zinc oxide", "CuO": "copper(II) oxide", "Cu2O": "copper(I) oxide", "Cu": "copper", "Zn": "zinc", "O2": "oxygen",
    "Cu(NO3)2": "copper(II) nitrate", "Zn(NO3)2": "zinc nitrate", "Cr(NO3)3": "chromium(III) nitrate", "NH3": "ammonia",
    "Al(NO3)3": "aluminium nitrate", "NH4OH": "ammonium hydroxide", "(NH4)2CrO4": "ammonium chromate",
    "(NH4)2Cr2O7": "ammonium dichromate", "Fe(CO)5": "iron pentacarbonyl", "Ni(CO)4": "nickel tetracarbonyl", "HCOOCH3": "methyl formate",
    "Cr2O3": "chromium(III) oxide", "CrO3": "chromium trioxide", "Al2O3": "aluminium oxide", "MnO": "manganese(II) oxide",
    "Fe": "iron", "Ni": "nickel", "Co": "cobalt", "ThO2": "thorium dioxide", "MgO": "magnesium oxide", "C": "carbon",
    "S": "sulfur", "COS": "carbonyl sulfide", "CS2": "carbon disulfide", "C2H5OH": "ethanol", "HCOOH": "formic acid",
}
LOCATOR = re.compile(r"^p\. ?(\d+)(?:[-–](\d+))?\b")


ELEMENTS = {"H": "hydrogen", "C": "carbon", "N": "nitrogen", "O": "oxygen", "S": "sulfur", "Cu": "copper", "Zn": "zinc",
            "Cr": "chromium", "Al": "aluminium", "Fe": "iron", "Ni": "nickel", "Co": "cobalt", "Mn": "manganese",
            "Th": "thorium", "Mg": "magnesium", "Ag": "silver", "Pd": "palladium", "Pt": "platinum", "Mo": "molybdenum",
            "W": "tungsten", "V": "vanadium", "Ti": "titanium", "Zr": "zirconium", "Ce": "cerium", "U": "uranium",
            "Ba": "barium", "Ca": "calcium", "K": "potassium", "Na": "sodium", "Li": "lithium", "Si": "silicon",
            "Sn": "tin", "Pb": "lead", "Cd": "cadmium", "Be": "beryllium", "Sr": "strontium", "B": "boron", "P": "phosphorus",
            "Cl": "chlorine", "Hg": "mercury", "Bi": "bismuth", "Sb": "antimony", "As": "arsenic", "Ru": "ruthenium",
            "Rh": "rhodium", "Os": "osmium", "Ir": "iridium", "Au": "gold", "Ge": "germanium", "La": "lanthanum"}


def formula_slug(f: str) -> str:
    """The shared species key: an element by its name (Co is cobalt, CO carbon monoxide), a compound by
    its formula lower-cased, letters and digits only."""
    if f in ELEMENTS:
        return ELEMENTS[f]
    return re.sub(r"[^a-z0-9]+", "", f.lower())


def schema_version() -> str:
    return load_yaml(SPEC)["version"]


def manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def in_scope() -> dict[str, dict]:
    return {s["slug"]: s for s in manifest()["sources"] if s["status"] == "in_scope"}


def source_id(slug: str) -> str:
    return f"{P}/source/{slug}"


def load_pages(slug: str) -> list[dict]:
    return json.loads((WORK / "texts" / f"{slug}.json").read_text())["pages"]


# ------------------------------------------------------------------------------------------ Source nodes
def source_node(s: dict) -> dict:
    kind = {"article": "article", "patent": "patent"}.get(s["kind"], "thesis" if "thesis" in (s.get("title", "") + s.get("note", "")).lower() else "report")
    if s["kind"] == "thesis_or_report":
        kind = "thesis" if re.search(r"thesis|proefschrift", json.dumps(s), re.I) else "report"
    year = int(s["published"][:4])
    props = {"name": s["title"], "title": s["title"], "kind": kind, "year": year, "origin": "curated",
             "stewardship": {"access": "public", "note": "bibliographic record"},
             "licence": ("US patent; not subject to copyright" if s["kind"] == "patent" and s["patent"].startswith("US") else
                         "no verified licence; short excerpts quoted as evidence under fair use" if s["kind"] == "patent" else
                         "no verified publisher licence; short excerpts quoted as evidence under fair use"),
             "description": (f"Published {s['published']} ({s['date_basis']}); in scope: before the {manifest()['cutoff']['date']} cutoff. "
                             f"Text: {', '.join(f'{v} pages {k}' for k, v in sorted(s['text']['page_text_origins'].items()))}"
                             + (f" ({s['text']['ocr_engine']})" if s['text'].get('ocr_engine') else "") + ". Text not redistributed.")}
    if s.get("doi"):
        props["doi"], props["url"] = s["doi"], f"https://doi.org/{s['doi']}"
    if s.get("venue"):
        props["venue"] = s["venue"]
    if s["kind"] == "patent":
        props["identifiers"] = {"patent": s["patent"]}
        props["url"] = f"https://patents.google.com/patent/{s['patent']}"
    return {"id": source_id(s["slug"]), "label": "Source", "props": props}


def person_slug(name: str) -> str:
    """ASCII slug of a name; a name in another script (富田 彰) keeps its letters."""
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", n.lower()).strip("-") or re.sub(r"\W+", "-", name.lower()).strip("-")


# Records merged into another (retired id -> surviving id), kept so that a bundle can list the retired
# released ids in the survivor's replaced_ids. Species: a source-scoped record that is the shared species of
# the same formula (tools/revise_units_species_names.py), and the duplicate shared carbon.
MERGED_SPECIES = {
    f"{P}/10.1098-rspa.1923.0036/species/palladium": f"{P}/species/palladium",
    f"{P}/10.1098-rspa.1923.0036/species/platinum": f"{P}/species/platinum",
    f"{P}/hid-20037/species/sodium-hydroxide": f"{P}/species/naoh",
    f"{P}/us2014883a/species/chromium": f"{P}/species/chromium",
    f"{P}/us2014883a/species/sodium-carbonate": f"{P}/species/na2co3",
    f"{P}/us2061470a/species/chromium": f"{P}/species/chromium",
    f"{P}/us2281228a/species/sodium-carbonate": f"{P}/species/na2co3",
    f"{P}/us2281228a/species/sodium-hydroxide": f"{P}/species/naoh",
    f"{P}/species/c": f"{P}/species/carbon",
    # the hydrocarbon the OCR printed "C,H" in US 1,836,085 reads C₂H₄ on the page image (re-curation 2026-09-29)
    f"{P}/us1836085a/species/c2hx-printed-hydrocarbon": f"{P}/species/c2h4",
}

# Bylines that name an organization, not a person.
CORPORATE_AUTHORS = {"FIAT (Field Information Agency, Technical)": "other"}   # a US Army agency

# A byline form -> the person's fullest byline form in the corpus, where the curators judged them one person.
SAME_PERSON = {
    "K. Frölich": "Per K. Frölich",     # Ind. Eng. Chem. 1929 (MIT, with Fenske); Per K. Frölich in 1928
    "R. L. Brown": "Ralph L. Brown",    # Ind. Eng. Chem. 1928 (Bureau of Mines, with Fieldner); Brown and Galloway
    "富田 彰": "Akira Tomita",           # Nippon Kagaku Zasshi 1951, byline in Japanese; the same series in romaji
}


def people(sources: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    links, seen = [], {}
    for slug, s in sorted(sources.items()):
        names = [(a, "author") for a in s.get("authors") or []]
        if s["kind"] == "patent":
            names = [(a.strip(), "inventor") for a in re.split(r";|,(?![^()]*\))", s.get("inventors") or "") if a.strip()]
        for pos, (printed, role) in enumerate(names, 1):
            name = SAME_PERSON.get(printed, printed)
            if name in CORPORATE_AUTHORS:
                pid = f"{P}/institution/{person_slug(name)}"
                if pid not in seen:
                    seen[pid] = {"id": pid, "label": "Institution", "props": {"name": name, "institution_kind": CORPORATE_AUTHORS[name], "origin": "curated"}}
            else:
                name = re.sub(r"\s*\((?:University|Univ\.)[^)]*\)$", "", name)   # "Hart (University of Cape Town)"
                pid = f"{P}/person/{person_slug(name)}"
            if pid not in seen:
                seen[pid] = {"id": pid, "label": "Person", "props": {"name": name, "origin": "curated"}}
            props = {"role": role, "position": pos, "origin": "curated"}
            if printed != name:
                props["note"] = f"byline: {printed}"
            links.append({"id": f"{source_id(slug)}/authored-by/{pos}", "source": source_id(slug), "target": pid, "type": "AUTHORED_BY",
                          "props": props})
        if s["kind"] == "patent" and s.get("assignee"):
            name = re.sub(r"\s*\(.*?\)\s*", " ", s["assignee"]).strip()
            iid = f"{P}/institution/{person_slug(name)}"
            if iid not in seen:
                seen[iid] = {"id": iid, "label": "Institution", "props": {"name": name, "institution_kind": "company", "origin": "curated"}}
            links.append({"id": f"{source_id(slug)}/assignee", "source": source_id(slug), "target": iid, "type": "AUTHORED_BY",
                          "props": {"role": "assignee", "origin": "curated"}})
    return sorted(seen.values(), key=lambda n: n["id"]), links


# ------------------------------------------------------------------------------------------ brief
def page_text_file(slug: str) -> Path:
    out = WORK / "briefs" / slug / "text.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(f"\n===== PDF page {p['page']} ({p['origin']}) =====\n{p['text']}" for p in load_pages(slug)))
    return out


def checklist(slug: str, s: dict, corpus: Path | None) -> dict:
    """Earlier extractions of this source, to look for — never evidence."""
    out = {"note": "Earlier extractions of this source, a checklist of what to look for. Not evidence: find every item in the text "
                   "again and quote it, or leave it out.", "bundle_claims": [], "table_rows": []}
    if not corpus:
        return out
    key = s.get("doi") or (f"patent:{s['patent'].lower()}" if s.get("patent") else None)
    g = corpus / "methanol-synthesis-curation-kit/methanol-synthesis_v1.0.0/kg/graph.json"
    if g.exists() and key:
        for e in json.loads(g.read_text())["links"]:
            if e.get("type") == "REPORTED_IN" or key not in (e["props"].get("source_paper_ids") or []):
                continue
            out["bundle_claims"].append({"type": e["type"], "from": e["source"], "to": e["target"], "statement_kind": e["props"].get("_statement"),
                                         "quotes": [ev.get("quote") for ev in e["props"].get("_evidence") or []]})
    import csv
    t = corpus / "methanol_pre1965_dataset_curated.csv"
    if t.exists():
        for r in csv.DictReader(open(t, encoding="utf-8")):
            if (s.get("doi") and r["doi"] == s["doi"]) or (s.get("patent") and r["patent_number"].replace(" ", "").upper().startswith(s["patent"][:-1].upper())):
                out["table_rows"].append({k: v for k, v in r.items() if v and k not in ("pdf_link", "pdf_path")})
    return out


def cmd_brief(a) -> int:
    srcs = in_scope()
    if a.slug not in srcs:
        raise ScaleError(f"{a.slug} is not an in-scope source (see corpus/manifest.json)")
    s = srcs[a.slug]
    spec = pgraph.load_spec(SPEC)
    d = WORK / "briefs" / a.slug
    d.mkdir(parents=True, exist_ok=True)
    txt = page_text_file(a.slug)
    labels = ["Catalyst", "CatalystSample", "Preparation", "Treatment", "CatalyticTest", "Feed", "Reactor", "Reaction",
              "ChemicalSpecies", "Material", "Characterization", "Analysis", "Computation", "Claim", "Hypothesis", "Mechanism",
              "ElementaryStep", "Operation", "ActiveSite", "Model", "Instrument", "Descriptor", "TimeSeries", "Variable",
              "Sample", "Procedure"] + (["ProcessUnit"] if "ProcessUnit" in spec["nodes"] else [])
    (d / "schema.json").write_text(json.dumps({**pgraph.describe(spec, labels + sorted(e for e in spec["edges"] if e != "REPORTED_IN"),
                                                                  profile=DOMAIN),
                                                "common_properties": {k: list((v.get("properties") or v)) for k, v in spec["common"].items()},
                                                "value_object_fields": sorted(spec["value"]["fields"]),
                                                "evidence_fields": sorted(spec["evidence"]["fields"]),
                                                "checklist": spec["profiles"][DOMAIN]["effective"]}, indent=1, ensure_ascii=False))
    (d / "checklist.json").write_text(json.dumps(checklist(a.slug, s, a.corpus), indent=1, ensure_ascii=False))
    brief = {"source_slug": a.slug, "source_id": source_id(a.slug), "metadata": s, "text_file": str(txt),
             "schema_file": str(d / "schema.json"), "checklist_file": str(d / "checklist.json"),
             "fragment_file": str(FRAGMENTS / f"{a.slug}.json"),
             "shared_reactions": {f"{P}/reaction/{k}": {"equation": v[0], "name": v[1]} for k, v in SHARED_REACTIONS.items()},
             "shared_species": {f"{P}/species/{formula_slug(f)}": {"formula": f, "name": n} for f, n in SHARED_SPECIES.items()}}
    (d / "brief.json").write_text(json.dumps(brief, indent=1, ensure_ascii=False))
    print(json.dumps({k: brief[k] for k in ("source_id", "text_file", "schema_file", "checklist_file", "fragment_file")}, indent=1))
    return 0


# ------------------------------------------------------------------------------------------ check
def fragment_doc(frag: dict, s: dict) -> dict:
    rn, rl = registry_nodes()
    nodes = [source_node(s)] + rn + [n for n in frag.get("nodes") or [] if n.get("label") != "Source"]
    links = rl + [e for e in frag.get("links") or [] if e.get("type") != "REPORTED_IN"]
    doc = {"directed": True, "multigraph": True,
           "graph": {"schema": "scale-graph", "schema_version": schema_version(), "graph_id": f"{P}/fragment/{s['slug']}",
                     "title": f"Curation of {s['title']}", "data_status": "research_data", "follows_domains": [DOMAIN],
                     "stewardship": STEWARDSHIP},
           "nodes": nodes, "links": links}
    doc["links"] = links + pgraph.derive_reported_in(doc)
    return doc


# ------------------------------------------------------------------------------------------ vision + OCR
# Two independent readers of a scanned page: the curator reads the page image (a vision-capable model
# or a person), Tesseract reads the same page with word positions and confidences. A value read from
# the image carries evidence with reading vision_ocr, the region it was read in and the curator's
# transcription; the tool (never the curator) records whether OCR reads the same numbers there
# (agreement). Where OCR is illegible or disagrees, an independent second reading of the same region
# by another curator who has not seen the first transcription must give the same numbers.
PAGES = WORK / "pages"                  # page images and crops for the curator's eyes (not committed)
OCR = DATA / "curation" / "ocr"          # the OCR the agreement is computed from (local): page words, region words
SECOND = DATA / "curation" / "second-readings"
VISION = ("vision", "vision_ocr")


def corpus_dir() -> Path:
    if not os.environ.get("SCALE_METHANOL_CORPUS"):
        raise ScaleError("set SCALE_METHANOL_CORPUS to the corpus directory (the PDFs)")
    return Path(os.environ["SCALE_METHANOL_CORPUS"])


def pdf_of(slug: str) -> Path:
    return corpus_dir() / in_scope()[slug]["pdf"]


def ocr_engine() -> str:
    """The OCR that runs here: Tesseract's version and language, and the renderer that makes its images."""
    import pymupdf
    return f"{sourcetext.tesseract_version()} (eng); pymupdf {pymupdf.__version__}"


def page_words(slug: str, page: int) -> dict:
    """{text_layer: [...], ocr: [...], ocr_engine} words of a page with their boxes, from the committed OCR
    that ``pages`` writes (``ocr-import`` brings in a cache written before the OCR was committed)."""
    f = OCR / slug / f"p{page}.words.json"
    if not f.exists():
        raise ScaleError(f"no page words for {slug} p. {page}: run `curation.py pages {slug}` "
                         f"(or `curation.py ocr-import` for a cache under work/pages)")
    return json.loads(f.read_text())


def words_engine(pw: dict) -> str | None:
    """The engine recorded with cached words; files written before the renderer was recorded give only
    Tesseract's version and dpi."""
    return pw.get("ocr_engine")


def region_key(page: int, region: list[float]) -> str:
    return f"p{page}_" + "_".join(f"{x:.3f}" for x in region)


def region_words(slug: str, page: int, region: list[float]) -> list[dict]:
    """The words OCR and the text layer place in a region: the page's words there, and a fresh 400 dpi
    OCR of the region itself (cached), mapped back to page coordinates."""
    return region_reading(slug, page, region)["words"]


def region_reading(slug: str, page: int, region: list[float]) -> dict:
    """{words, engines}: the words of region_words and the OCR engines that produced them (the page's and
    the region's; None where a cache was written without recording its engine)."""
    pw = page_words(slug, page)
    words = sourcetext.in_region(pw.get("text_layer") or [], region) + sourcetext.in_region(pw.get("ocr") or [], region)
    cache = OCR / slug / "regions" / f"{region_key(page, region)}.json"
    if cache.exists():
        got = json.loads(cache.read_text())
        crop, crop_engine = (got, None) if isinstance(got, list) else (got["words"], got.get("ocr_engine"))
    else:
        x0, y0, x1, y1 = region
        raw = sourcetext.ocr_words(sourcetext.render_page(pdf_of(slug), page, 400, tuple(region)), psm="6")
        crop = [{**w, "box": [round(x0 + w["box"][0] * (x1 - x0), 4), round(y0 + w["box"][1] * (y1 - y0), 4),
                              round(x0 + w["box"][2] * (x1 - x0), 4), round(y0 + w["box"][3] * (y1 - y0), 4)]} for w in raw]
        crop_engine = ocr_engine()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(dump_canonical({"ocr_engine": crop_engine, "words": crop}))
    return {"words": words + crop, "engines": sorted({str(words_engine(pw)), str(crop_engine)})}


def valid_region(r) -> bool:
    return (isinstance(r, list) and len(r) == 4 and all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in r)
            and r[0] < r[2] and r[1] < r[3])


def evidence_page(ev: dict) -> int | None:
    m = LOCATOR.match(ev.get("locator") or "")
    return int(m.group(1)) if m else None


def record_numbers(props: dict) -> list[str]:
    """The numbers of a record's value objects (its own properties and results/conditions maps), unsigned: a
    printed sign ("-", "−", "–") is not part of the numbers read from a transcription or quote. A value
    printed in words (as_reported without digits, e.g. "atmospheric pressure" recorded as 1 atm) has no
    printed number and is left out."""
    out = []

    def take(v):
        if isinstance(v, dict) and v.get("status", "present") == "present":
            words = v.get("as_reported")
            if isinstance(words, str) and words.strip() and not re.search(r"\d", words):
                return                  # printed in words ("atmospheric pressure", "Nil"): no printed number to find
            out.extend(str(abs(v[k])) for k in ("value", "lower", "upper") if isinstance(v.get(k), (int, float)))
    for k, v in props.items():
        if k in ("results", "conditions", "properties") and isinstance(v, dict):
            for x in v.values():
                take(x)
        elif k not in ("evidence",):
            take(v)
    return out


def same_number(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except ValueError:
        return a == b


SECOND_MARGIN = 0.02                # page fraction added around a region in the second reader's crop
FIGURE_TOLERANCE = (0.05, 0.3)      # a figure point: two readings agree within 5 % or 0.3 (grid reading)


def readings_match(a: list[str], b: list[str], figure: bool = False) -> bool:
    """The second reading confirms the first: every number of the first transcription is also read by the
    second reader (each matched once; for a figure point within FIGURE_TOLERANCE). The second reader may
    read more (a row label, the composition and temperature a figure point stands for)."""
    rel, ab = FIGURE_TOLERANCE if figure else (0.0, 0.0)
    pool = [float(v) for v in b]
    for v in sorted({float(x) for x in a}):        # a number written twice is one reading
        hit = next((i for i, q in enumerate(pool) if abs(v - q) <= max(rel * abs(v), ab) + 1e-9), None)
        if hit is None:
            return False
        pool.pop(hit)
    return True


def vision_checks(frag: dict, s: dict, warnings: list[str] | None = None) -> list[str]:
    """The rules for evidence read from page images (reading vision or vision_ocr). An agreement the OCR
    here does not reproduce is an error when the fragment records the same OCR engines as the cached
    words (``ocr_engines``, written by ``agree``), and a warning (into ``warnings``) when the engines differ
    or were not recorded: another engine may read a region differently, and the recorded agreement stands."""
    errs, waiting = [], {}
    recorded = frag.get("ocr_engines")
    second = json.loads((SECOND / f"{s['slug']}.json").read_text()) if (SECOND / f"{s['slug']}.json").exists() else {}
    for rec in (frag.get("nodes") or []) + (frag.get("links") or []):
        rid, props = str(rec.get("id")), rec.get("props") or {}
        evs = props.get("evidence") or []
        vis = [(i, ev) for i, ev in enumerate(evs) if ev.get("reading") in VISION]
        for i, ev in vis:
            page = evidence_page(ev)
            if not valid_region(ev.get("region")):
                errs.append(f"{rid}: evidence[{i}] read from the image needs region [x0, y0, x1, y1] (page fractions)")
                continue
            if not ev.get("transcription"):
                errs.append(f"{rid}: evidence[{i}] read from the image needs a transcription")
                continue
            try:
                rr = region_reading(s["slug"], page, ev["region"])
                got = sourcetext.region_agreement(ev["transcription"], rr["words"], ev.get("kind"))
            except ScaleError as e:
                errs.append(f"{rid}: evidence[{i}]: {e}")
                continue
            if ev.get("agreement") != got["agreement"]:
                same_engine = recorded is not None and set(rr["engines"]) <= set(recorded)
                if same_engine or warnings is None or ev.get("agreement") is None:
                    errs.append(f"{rid}: evidence[{i}] agreement is {ev.get('agreement')!r}, the tool computes {got['agreement']!r} "
                                f"(run `curation.py agree`; the agreement is never written by hand)")
                else:
                    warnings.append(f"{rid}: evidence[{i}] agreement {ev.get('agreement')!r} was computed with "
                                    f"{recorded or 'an OCR engine the fragment does not record'}; the OCR here "
                                    f"({', '.join(rr['engines'])}) computes {got['agreement']!r}. The recorded agreement stands; "
                                    f"commit the OCR it was computed from (`curation.py ocr-import`) or re-run `agree` with it")
                    got = {**got, "agreement": ev["agreement"]}
            if got["agreement"] != "agree":
                sr = ev.get("second_reading") or second.get(f"{rid}#{i}") or second.get(region_key(page, ev["region"]))
                if not sr:
                    waiting.setdefault(region_key(page, ev["region"]), []).append(f"{rid}#{i}")
                else:
                    # notation written in sub/superscripts (H₂, cm³, d²⁰₄) is not a reading of a value; a
                    # composition (Zn₆₆.₆) is
                    a_ = sourcetext.numbers_in(re.sub(r"(?<=[A-Za-z)\]])[₀-₉⁰¹²³⁴⁵⁶⁷⁸⁹]{1,3}(?![₀-₉⁰¹²³⁴⁵⁶⁷⁸⁹.·])", "",
                                                      ev["transcription"]))
                    b_ = sourcetext.numbers_in(re.sub(r"(?<![A-Za-z])[oO](?=[.,]\d)", "0", sr))   # a typed "o,45" is 0,45
                    if not readings_match(a_, b_, ev.get("kind") == "figure"):
                        errs.append(f"{rid}: evidence[{i}] the second reading {b_} does not give the numbers of the transcription {a_}")
        if vis:        # every number of a record read from an image is backed by a transcription or a quote
            backed = [abs(x) for ev in evs for x in sourcetext.values_in((ev.get("transcription") or "") + " " + (ev.get("quote") or ""))]
            for n in record_numbers(props):
                if not any(abs(float(n) - b) <= 1e-9 * max(1.0, abs(b)) for b in backed):
                    errs.append(f"{rid}: value {n} is in no transcription or quote of the record")
    for rk, keys in sorted(waiting.items()):     # one error per region: a second reader reads a region once
        errs.append(f"region {rk}: OCR does not confirm the reading of {len(keys)} evidence item(s) ({keys[0]}"
                    f"{', …' if len(keys) > 1 else ''}); it needs an independent second reading (curation.py pending)")
    return errs


def own_checks(frag: dict, s: dict, pages: list[dict]) -> list[str]:
    errs, sid = [], source_id(s["slug"])
    page_norm = {p["page"]: match_text(p["text"]) for p in pages}
    shared = {f"{P}/reaction/{k}" for k in SHARED_REACTIONS}
    for rec in (frag.get("nodes") or []) + (frag.get("links") or []):
        rid = str(rec.get("id"))
        if not rid.startswith(f"{P}/"):
            errs.append(f"{rid}: ids start with {P}/")
        elif not (rid.startswith(f"{P}/{s['slug']}/") or rid.startswith(f"{P}/species/") or rid.startswith(f"{P}/material/")
                  or rid in shared):
            errs.append(f"{rid}: source-specific ids start with {P}/{s['slug']}/")
        if rid in shared and rec.get("label") == "Reaction":
            want = SHARED_REACTIONS[rid.rsplit("/", 1)[1]][0]
            if rec["props"].get("equation") not in (None, want):
                errs.append(f"{rid}: the shared reaction's equation is {want!r}")
        for i, ev in enumerate((rec.get("props") or {}).get("evidence") or []):
            if ev.get("source") != sid:
                errs.append(f"{rid}: evidence[{i}] source must be {sid}")
            m = LOCATOR.match(ev.get("locator") or "")
            if not m:
                errs.append(f"{rid}: evidence[{i}] locator must start with the PDF page, e.g. 'p. 3' or 'p. 3, Table II'")
                continue
            lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
            q = ev.get("quote")
            if q:
                nq = match_text(q)
                found = [pg for pg, t in page_norm.items() if nq in t]
                if not found:
                    joined = match_text(" ".join(p["text"] for p in pages if lo <= p["page"] <= hi + 1))
                    if nq not in joined:
                        errs.append(f"{rid}: evidence[{i}] quote not found in the page texts: {q[:80]!r}")
                elif not any(lo <= pg <= hi for pg in found):
                    errs.append(f"{rid}: evidence[{i}] quote is on PDF page {found}, locator says {ev['locator']!r}")
                if len(q) > 600:
                    errs.append(f"{rid}: evidence[{i}] quote is {len(q)} characters; keep quotes short (≤ 600)")
    for g in frag.get("gaps") or []:
        if g.get("status", "open") not in ("open", "resolved"):
            errs.append(f"gap {str(g)[:80]}: status is open or resolved")
        elif g.get("status") == "resolved" and not (re.fullmatch(r"\d{6}|scale-graph \d+\.\d+\.\d+|re-curation \d{4}-\d{2}-\d{2}", str(g.get("resolved_by")))
                                                    and g.get("resolution")):
            errs.append(f"gap {str(g)[:80]}: a resolved gap names resolved_by (a proposal's six-digit id such as 000009, the schema version 'scale-graph X.Y.Z' whose concepts answer it, or 're-curation "
                        f"YYYY-MM-DD' when a new reading of the source answers it) and a resolution")
        if g.get("kind") not in ("absent_source_information", "ambiguous_source_information", "missing_concept", "extraction_error"):
            errs.append(f"gap {g}: kind must be absent_source_information, ambiguous_source_information, missing_concept or extraction_error")
    return errs


def check(path: Path, spec=None) -> dict:
    frag = json.loads(path.read_text())
    srcs = in_scope()
    slug = frag.get("source")
    if slug != path.name.removesuffix(".json"):
        return {"file": str(path), "ok": False, "errors": [f"fragment source {slug!r} does not match its file name"], "warnings": []}
    if slug not in srcs:
        return {"file": str(path), "ok": False, "errors": [f"source {slug!r} is not in scope"], "warnings": []}
    s, pages = srcs[slug], load_pages(slug)
    spec = spec or pgraph.load_spec(SPEC)
    doc = fragment_doc(frag, s)
    rep = pgraph.validate(doc, spec, {source_id(slug): "\n".join(p["text"] for p in pages)})
    warnings = [f"{m['record']}: {m['message']}" for m in rep.warnings]
    errors = [f"{m['record']}: {m['message']}" for m in rep.errors] + own_checks(frag, s, pages) + vision_checks(frag, s, warnings)
    conf = (rep.conformance or {}).get("profiles", {}).get(DOMAIN, {})
    labels = {}
    for n in frag.get("nodes") or []:
        labels[n.get("label")] = labels.get(n.get("label"), 0) + 1
    return {"file": str(path), "source": slug, "ok": not errors, "errors": errors, "warnings": warnings, "labels": labels,
            "links": len(frag.get("links") or []), "gaps": len(frag.get("gaps") or []),
            "checklist": {"name": DOMAIN, "conformant": conf.get("conformant"), "violations": [v["message"] for v in conf.get("violations", [])][:15],
                        "recommended_filled": (conf.get("recommended") or {}).get("fraction")}}


def cmd_check(a) -> int:
    r = check(Path(a.fragment))
    print(json.dumps(r, indent=1, ensure_ascii=False))
    return 0 if r["ok"] else 1


def cmd_status(a) -> int:
    spec = pgraph.load_spec(SPEC)
    rows = []
    for slug in sorted(in_scope()):
        f = FRAGMENTS / f"{slug}.json"
        if not f.exists():
            rows.append((slug, "missing", 0))
            continue
        r = check(f, spec)
        rows.append((slug, "ok" if r["ok"] else f"{len(r['errors'])} errors", sum(r["labels"].values())))
    for row in rows:
        print(f"{row[0]:45s} {row[1]:12s} {row[2]:5d} nodes")
    print(f"{sum(1 for r in rows if r[1] == 'ok')} of {len(rows)} in-scope sources pass")
    return 0


# ------------------------------------------------------------------------------------------ assemble
def merge_node(have: dict, new: dict, conflicts: list) -> None:
    hp, np_ = have["props"], new["props"]
    if have["label"] != new["label"]:
        conflicts.append(f"{have['id']}: label {have['label']} vs {new['label']}")
    for k, v in np_.items():
        if k == "evidence":
            for ev in v:
                if ev not in hp.setdefault("evidence", []):
                    hp["evidence"].append(ev)
        elif k not in hp:
            hp[k] = v
        elif hp[k] != v and k not in ("description", "note"):
            conflicts.append(f"{have['id']}: {k} {json.dumps(hp[k])[:60]} vs {json.dumps(v)[:60]} (first kept)")


def cmd_assemble(a) -> int:
    spec = pgraph.load_spec(SPEC)
    m = manifest()
    srcs = in_scope()
    nodes: dict[str, dict] = {}
    links: dict[str, dict] = {}
    report = {"cutoff": m["cutoff"], "sources_in_scope": len(srcs), "curated": [], "not_curated": [], "failing": [],
              "merge_conflicts": [], "gaps": [], "coverage": {}}
    for n in [source_node(s) for s in srcs.values()]:
        nodes[n["id"]] = n
    rn, rl = registry_nodes()
    for n in rn:
        nodes[n["id"]] = n
    for e in rl:
        links[e["id"]] = e
    pn, pl = people(srcs)
    for n in pn:
        nodes[n["id"]] = n
    for e in pl:
        links[e["id"]] = e
    passages: dict[str, list[dict]] = {}
    for slug in sorted(srcs):
        f = FRAGMENTS / f"{slug}.json"
        if not f.exists():
            report["not_curated"].append(slug)
            continue
        r = check(f, spec)
        if not r["ok"]:
            report["failing"].append({"source": slug, "errors": r["errors"][:20]})
            continue
        frag = json.loads(f.read_text())
        report["curated"].append(slug)
        report["coverage"][slug] = frag.get("coverage") or {}
        for g in frag.get("gaps") or []:
            report["gaps"].append({"source": slug, **g})
        passages[slug] = passages_of(slug, source_id(slug), load_pages(slug))
        for n in frag.get("nodes") or []:
            if n.get("label") == "Source":
                continue
            n = json.loads(json.dumps(n))
            if n["id"] in nodes:
                merge_node(nodes[n["id"]], n, report["merge_conflicts"])
            else:
                nodes[n["id"]] = n
        for e in frag.get("links") or []:
            if e.get("type") == "REPORTED_IN":
                continue
            if e["id"] in links:
                report["merge_conflicts"].append(f"{e['id']}: link id used twice")
                continue
            links[e["id"]] = json.loads(json.dumps(e))
    # passage ids on evidence
    unplaced = 0
    for rec in list(nodes.values()) + list(links.values()):
        for ev in (rec.get("props") or {}).get("evidence") or []:
            if ev.get("quote") and ev.get("source", "").startswith(f"{P}/source/"):
                slug = ev["source"].rsplit("/", 1)[1]
                hit = locate(ev["quote"], passages.get(slug, []))
                if hit:
                    ev["passage"] = hit["id"]
                else:
                    unplaced += 1
    report["quotes_across_passage_boundaries"] = unplaced
    cur = [srcs[s] for s in report["curated"]]
    years = sorted(int(s["published"][:4]) for s in cur) or [0]
    doc = {"directed": True, "multigraph": True,
           "graph": {"schema": "scale-graph", "schema_version": schema_version(), "graph_id": f"{P}/graph", "data_status": "research_data",
                     "follows_domains": [DOMAIN], "domains": ["heterogeneous catalysis", "thermal catalysis", "methanol synthesis"],
                     "title": (f"Methanol synthesis, historical literature published before {m['cutoff']['date']} "
                               f"({len(cur)} sources, {years[0]}–{years[-1]}), curated from the source texts under scale-graph {schema_version()}"),
                     "description": (f"Cutoff: {m['cutoff']['rule']}. {m['cutoff']['why']} {m['cutoff']['caution']} "
                                     "Each source was read and curated from its page texts (PDF text layer, or Tesseract OCR where the "
                                     "PDF has none); every quote is checked verbatim against those texts. Earlier extractions were used "
                                     "only as checklists."),
                     "stewardship": STEWARDSHIP},
           "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
           "links": sorted(links.values(), key=lambda e: e["id"])}
    doc["links"] = sorted(doc["links"] + pgraph.derive_reported_in(doc), key=lambda e: e["id"])
    texts = {source_id(s): "\n".join(p["text"] for p in load_pages(s)) for s in report["curated"]}
    rep = pgraph.validate(doc, spec, texts)
    report["validation"] = {"errors": len(rep.errors), "warnings": len(rep.warnings),
                            "first_errors": [f"{x['record']}: {x['message']}" for x in rep.errors[:30]]}
    conf = (rep.conformance or {}).get("profiles", {}).get(DOMAIN, {})
    report["conformance"] = {k: v for k, v in conf.items() if k != "violations"}
    report["counts"] = pgraph.stats(doc)
    out = Path(a.out)
    out.write_text(dump_canonical(doc))
    ev = Index.build(evidence_items(doc))
    ev.save(out.with_suffix("").with_suffix(".evidence"))
    allp = [p for s in sorted(passages) for p in passages[s]]
    Index.build(allp).save(WORK / "index" / "passages")
    report["indexes"] = {"evidence": {"items": len(ev.items), "embedder": ev.embedder_id, "file": out.with_suffix("").with_suffix(".evidence").name + ".jsonl/.i8"},
                         "passages": {"items": len(allp), "embedder": ev.embedder_id, "file": "work/index/passages.jsonl/.i8 (local; texts not redistributed)"}}
    (DATA / "curation" / "assembly-report.json").write_text(dump_canonical(report))
    print(json.dumps({k: report[k] for k in ("sources_in_scope", "validation", "indexes")} |
                     {"curated": len(report["curated"]), "not_curated": len(report["not_curated"]), "failing": len(report["failing"]),
                      "merge_conflicts": len(report["merge_conflicts"])}, indent=1))
    return 0 if not rep.errors and not report["failing"] else 1


BUNDLE_VERSION = "1.1.0"

# What each release changed; the entry of the release being built heads the changelog, and the
# previous release's changelog follows unchanged (released bundles are immutable).
RELEASE_NOTES = {
    "1.0.0": """First public release, exported from the SCALE graph (scale-graph {doc_version}) with `scale graph export --to galaxy`.
Node ids are those of the internal builds that preceded it (up to 4.1.1): a record that was imported from one of them
keeps its id, and ids retired in them are listed on the surviving record in `replaced_ids`.
""",
    "1.1.0": """Narrower scope: CO and CO2 hydrogenation to methanol (CO + D2 included). Ids of 1.0.0 are kept; the records
left out are listed as removed in `bundle.json`.

- **Left out: a reaction whose source does not name the reactants** (Bull. Chem. Soc. Jpn. 33, 358, 1960: "methanol
  synthesis", reactants only in an earlier paper), with its tests, catalysts, samples and the claims resting on them.
- **Left out: records that only looked in scope.** Reactions that no kept test or claim is about (ortho-para hydrogen
  conversion, catalyst glow, formaldehyde from H atoms, methanol decomposition, ...) and claims and hypotheses resting only
  on records already left out. Three sources no longer contribute a record: 10.1021/j150284a006,
  10.1246/nikkashi1898.54.446 and 10.1246/nikkashi1898.54.448. They stay in the corpus and in the SCALE graph.
""",
}


def changelog(m: dict, rep: dict, manifest_: dict, previous: Path | None = None) -> str:
    doc_version = schema_version()
    head = f"# Changelog\n\n## {BUNDLE_VERSION}\n\n" + RELEASE_NOTES[BUNDLE_VERSION].format(doc_version=doc_version) + "\n"
    prev = Path(previous) / "CHANGELOG.md" if previous else None
    history = prev.read_text().split("\n", 2)[2] if prev and prev.exists() else ""
    return head + history.lstrip("\n") if history else head + _first_entry(m, rep, manifest_, doc_version)


def _first_entry(m: dict, rep: dict, manifest_: dict, doc_version: str) -> str:
    cut = m["cutoff"]
    return f"""- **Corpus and cutoff.** {cut['rule']} ({cut['patents']}). {cut['why']} {manifest_['counts'].get('in_scope', 0)} sources are in
  scope and curated; sources published on or after the cutoff are held out (corpus/manifest.json in the SCALE repository).
- **Caution.** {cut['caution']}
- **Curation.** Every source was read from its page texts (PDF text layer, or Tesseract OCR for scanned patents and
  reports) and curated by agents under the SCALE curate-source skill; every quote was checked verbatim against those
  texts. The 69 sources on CO and CO2 hydrogenation were also read from their page images: each reading of a scanned
  table, figure or garbled passage carries its page region and transcription, and is confirmed by positioned OCR in
  that region or by an independent second reader. Readings neither confirms are not recorded; they are listed as gaps.
  An earlier curation kit (methanol-synthesis-curation-kit) was used only as a checklist of what to look for, never as
  evidence.
- **Ids.** Node ids are `<Label>:<slug of name>-<hash of the scale-graph id>`; each node keeps its scale-graph id in
  `scale_id`.
- **Not exported:** {json.dumps(rep['not_exported_links'])} links without a verbatim quote (bibliographic links), and
  {rep.get('nodes_not_exported_no_source', 0)} nodes that no source reports.
- **Units.** Temperatures, pressures, times, space velocities and percentages are converted to one unit per property (K, MPa,
  h, h-1, %) with the reported text in `as_reported`; values in other or unstated units are kept as text in
  `<property>_as_reported`.
- **Page images.** A reading of a page image is cited in `_evidence` by its transcription, marked `"reading": "vision_ocr"`.
  A transcription corrects the OCR text shipped under text/, so the validator's text check reports it as not found
  verbatim (a warning).

### Schema

The schema is generated from scale-graph {doc_version} (`extends`): every label and edge type used, with their properties.
The role a substance plays (support, promoter, binder) is on HAS_COMPONENT edges, not a type.
"""


# The GALAXY bundle covers CO and CO2 hydrogenation to methanol; the graph keeps everything curated.
METHANOL_SYNTHESIS = {f"{P}/reaction/co-hydrogenation-to-methanol", f"{P}/reaction/co2-hydrogenation-to-methanol",
                      f"{P}/10.1246-bcsj.37.1817/reaction/methanol-synthesis-from-co-and-d2"}  # CO + D2
# Left out: 10.1246-bcsj.33.358/reaction/methanol-synthesis, whose paper does not name the reactants (from bundle 1.1.0).
DATA_LABELS = {"CatalystSample", "Catalyst", "Feed", "Reactor", "Preparation", "Treatment", "Characterization", "ChemicalSpecies",
               "Material", "Variable", "Operation", "ProcessUnit", "Instrument", "Sample", "ActiveSite", "TimeSeries", "Procedure"}
LEAF_LABELS = {"ChemicalSpecies", "Material", "Variable", "Instrument"}
KNOWLEDGE_LABELS = {"Claim", "Hypothesis", "Analysis", "Computation", "Mechanism", "ElementaryStep", "Model", "Descriptor"}
BIBLIO_LABELS = {"Source", "Person", "Institution", "Project"}


def scope_methanol_synthesis(doc: dict) -> tuple[dict, dict]:
    """CO and CO2 hydrogenation to methanol only: leave out the tests of other reactions (methanol
    decomposition, formaldehyde, formate, Fischer-Tropsch, ...), the records that only those tests use
    (their samples, catalysts, feeds, reactors, preparations, characterizations), the claims and hypotheses
    that rest only on them, and the other reactions no kept claim is about. Everything else stays: catalysts
    and characterizations of methanol catalysts, patents' process units, general claims."""
    N = {n["id"]: n for n in doc["nodes"]}
    nbr = collections.defaultdict(list)
    for e in doc["links"]:
        nbr[e["source"]].append((e["target"], e["type"]))
        nbr[e["target"]].append((e["source"], e["type"]))
    lab = lambda i: N[i]["label"]                                                         # noqa: E731
    tests = {i for i, n in N.items() if n["label"] == "CatalyticTest"}
    kept_tests = {t for t in tests if any(o in METHANOL_SYNTHESIS for o, ty in nbr[t] if ty == "OF_REACTION")}
    dropped_tests = tests - kept_tests

    def closure(seeds):
        seen, stack = set(seeds), list(seeds)
        while stack:
            x = stack.pop()
            if lab(x) in LEAF_LABELS or x in METHANOL_SYNTHESIS:
                continue
            for o, ty in nbr[x]:
                if o not in seen and lab(o) in DATA_LABELS:
                    seen.add(o)
                    stack.append(o)
        return seen
    ms_catalysts = {c for c in N if lab(c) == "Catalyst" and any(o in METHANOL_SYNTHESIS for o, ty in nbr[c] if ty == "CATALYZES")}
    k_data = closure(kept_tests | ms_catalysts)
    d_data = closure(dropped_tests) - k_data - {i for i in N if lab(i) in LEAF_LABELS}
    other_reactions = {i for i in N if lab(i) == "Reaction"} - METHANOL_SYNTHESIS
    drop = set(dropped_tests) | d_data
    anchored = kept_tests | METHANOL_SYNTHESIS | k_data
    knowledge = {i for i in N if lab(i) in KNOWLEDGE_LABELS}
    ties = {k: {o for o, ty in nbr[k] if lab(o) not in BIBLIO_LABELS and lab(o) not in LEAF_LABELS} for k in knowledge}
    drop |= {k for k in knowledge if ties[k] & (drop | other_reactions) and not ties[k] & anchored}
    while True:   # until stable: claims resting only on dropped records, reactions nothing kept is about (species do not count)
        about = {o for k in knowledge - drop for o, ty in nbr[k]}
        more = {k for k in knowledge - drop if ties[k] and ties[k] <= drop}
        more |= {r for r in other_reactions - drop if r not in about and not any(
            o not in drop and lab(o) not in BIBLIO_LABELS | LEAF_LABELS | {"Reaction"} for o, ty in nbr[r])}
        if not more:
            break
        drop |= more
    keep = {i for i in N if i not in drop}
    used = {x for e in doc["links"] if e["source"] in keep and e["target"] in keep and e["type"] != "REPORTED_IN"
            for x in (e["source"], e["target"])}
    keep -= {i for i in keep if lab(i) in LEAF_LABELS and i not in used}                  # species nothing kept refers to
    reporters = {e["target"] for e in doc["links"] if e["type"] == "REPORTED_IN" and e["source"] in keep and lab(e["source"]) not in BIBLIO_LABELS}
    keep -= {i for i in keep if lab(i) == "Source" and i not in reporters}
    authors = {e["target"] for e in doc["links"] if e["type"] == "AUTHORED_BY" and e["source"] in keep}
    keep -= {i for i in keep if lab(i) == "Person" and i not in authors}
    keep -= {i for i in keep if lab(i) == "Institution" and i.startswith(f"{P}/institution/") and i not in authors}
    def refs(o):
        if isinstance(o, str):
            if o in N:
                yield o
        elif isinstance(o, dict):
            for k, v in o.items():
                if k != "evidence":
                    yield from refs(v)
        elif isinstance(o, list):
            for v in o:
                yield from refs(v)
    kept_recs = [n for n in doc["nodes"] if n["id"] in keep] + [e for e in doc["links"] if e["source"] in keep and e["target"] in keep]
    keep |= {r for rec in kept_recs for r in refs(rec.get("props")) if lab(r) in LEAF_LABELS}   # variables a control names

    def prune(o):
        """Drop references to records outside the scope (e.g. a CATALYZES context listing a decomposition test)."""
        if isinstance(o, dict):
            return {k: (v if k == "evidence" else prune(v)) for k, v in o.items()
                    if not (isinstance(v, str) and v in N and v not in keep)
                    and not (isinstance(v, list) and v and all(isinstance(x, str) and x in N and x not in keep for x in v))}
        if isinstance(o, list):
            return [prune(v) for v in o if not (isinstance(v, str) and v in N and v not in keep)]
        return o
    out = {**doc, "nodes": [{**n, "props": prune(n.get("props") or {})} for n in doc["nodes"] if n["id"] in keep],
           "links": [{**e, "props": prune(e.get("props") or {})} for e in doc["links"] if e["source"] in keep and e["target"] in keep]}
    removed = collections.Counter(N[i]["label"] for i in N if i not in keep)
    report = {"kept_tests": len(kept_tests), "dropped_tests": len(dropped_tests), "removed": dict(sorted(removed.items())),
              "sources_kept": sum(1 for n in out["nodes"] if n["label"] == "Source")}
    return out, report


def cmd_scope(a) -> int:
    """Write the graph scoped to CO and CO2 hydrogenation to methanol (the records GALAXY bundles carry), validated."""
    doc, report = scope_methanol_synthesis(json.loads((DATA / "methanol-synthesis.graph.json").read_text()))
    doc = {**doc, "graph": {**doc["graph"], "graph_id": f"{P}/graph/co-co2-hydrogenation",
                            "title": doc["graph"]["title"].replace("Methanol synthesis,", "Methanol synthesis (CO and CO2 hydrogenation to methanol),", 1),
                            "description": doc["graph"]["description"] + (" Scoped to CO and CO2 hydrogenation to methanol: tests of other reactions, "
                                                                           "the records only they use and the claims resting only on them are left out "
                                                                           "(tools/curation.py scope_methanol_synthesis).")}}
    rep = pgraph.validate(doc, pgraph.load_spec(SPEC))
    out = Path(a.out)
    out.write_text(dump_canonical(doc))
    print(json.dumps({"file": str(out), "nodes": len(doc["nodes"]), "links": len(doc["links"]), "errors": len(rep.errors),
                      "warnings": len(rep.warnings), **report}, indent=1))
    return 0 if not rep.errors else 1


def cmd_bundle(a) -> int:
    from scale import galaxy
    graph = DATA / "methanol-synthesis.graph.json"
    doc, scope_report = scope_methanol_synthesis(json.loads(graph.read_text()))
    spec = pgraph.load_spec(SPEC)
    m = manifest()
    srcs = in_scope()
    texts = {}
    for slug, s in sorted(srcs.items()):
        if s["kind"] == "patent" and s["slug"].startswith("us"):
            pages = load_pages(slug)
            texts[f"patent:{slug}"] = (f"{slug}.txt", "".join(f"\n===== page {p['page']} ({p['origin']}) =====\n{p['text']}" for p in pages),
                                       "US patent, not subject to copyright")
    out = Path(a.out)
    if out.exists():
        import shutil
        shutil.rmtree(out)
    corpus = {"description": (f"Historical methanol-synthesis corpus (ARPA-E CATALYST), frozen for SCALE curation: {m['cutoff']['rule']}. "
                              f"{len(srcs)} sources in scope (articles, theses, reports and patents with retrieved PDFs)."),
              "frozen_at": a.frozen_at, "n_screened": sum(m["counts"].values()), "n_included": len(srcs)}
    man = galaxy.export(doc, spec, out, "methanol-synthesis", BUNDLE_VERSION, texts, created=a.created,
                        scope=("CO and CO2 hydrogenation to methanol: catalysts, preparations, catalytic tests, feeds, reactors, "
                               f"characterizations, claims and hypotheses in the historical corpus published before {m['cutoff']['date']}."),
                        corpus=corpus, previous=a.previous, ids_from=a.ids_from,
                        replaced={**MERGED_SPECIES, **{f"{P}/person/{person_slug(a_)}": f"{P}/person/{person_slug(b_)}"
                                                       for a_, b_ in SAME_PERSON.items()},
                                  f"{P}/person/": f"{P}/person/{person_slug(SAME_PERSON['富田 彰'])}"})   # 2.1.0 gave 富田 彰 an empty slug
    rep = {**man["export_report"], "scope": scope_report}
    (out / "CHANGELOG.md").write_text(changelog(m, rep, m, a.previous))
    (out / "README.md").write_text(f"# methanol-synthesis {BUNDLE_VERSION}\n\nGALAXY knowledge-graph bundle exported from the SCALE "
                                   f"scale-graph document `methanol-synthesis.graph.json` ({doc['graph']['title']}).\n")
    galaxy.seal(out)
    print(json.dumps({"bundle": str(out), "counts": man["counts"], "changes": man["changes"], "export_report": rep}, indent=1))
    return 0


def cmd_pages(a) -> int:
    """Page images for the curator's eyes (200 dpi PNG) and positioned words for the check: the text
    layer's words and Tesseract's words with confidences (300 dpi), per page."""
    pdf = pdf_of(a.slug)
    import pymupdf
    n = len(pymupdf.open(pdf))
    out, ocr = PAGES / a.slug, OCR / a.slug
    out.mkdir(parents=True, exist_ok=True)
    ocr.mkdir(parents=True, exist_ok=True)
    pages = [int(x) for x in a.pages.split(",")] if a.pages else range(1, n + 1)
    for pg in pages:
        png, words = out / f"p{pg}.png", ocr / f"p{pg}.words.json"
        if not png.exists():
            png.write_bytes(sourcetext.render_page(pdf, pg, a.dpi))
        if not words.exists():
            words.write_text(dump_canonical({"page": pg, "text_layer": sourcetext.text_layer_words(pdf, pg),
                                         "ocr": sourcetext.ocr_words(sourcetext.render_page(pdf, pg, 300)),
                                         "ocr_engine": ocr_engine()}))
    print(json.dumps({"source": a.slug, "pages": len(list(pages)), "images": str(out)}, indent=1))
    return 0


def cmd_region(a) -> int:
    """A zoomed image of a region (for a close visual reading) and what OCR reads there."""
    region = [a.x0, a.y0, a.x1, a.y1]
    if not valid_region(region):
        raise ScaleError("a region is x0 y0 x1 y1, page fractions with x0 < x1 and y0 < y1")
    crop = PAGES / a.slug / "crops" / f"{region_key(a.page, region)}.png"
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(sourcetext.render_page(pdf_of(a.slug), a.page, a.dpi, tuple(region)))
    words = region_words(a.slug, a.page, region)
    confs = [w["conf"] for w in words if w.get("conf") is not None]
    res = {"crop": str(crop), "ocr_text": " ".join(w["text"] for w in words), "ocr_numbers": sourcetext.numbers_in(
        " ".join(w["text"] for w in words), lenient=True), "ocr_mean_conf": round(sum(confs) / len(confs), 1) if confs else None}
    if a.transcription:
        res["agreement"] = sourcetext.region_agreement(a.transcription, words)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0


def cmd_agree(a) -> int:
    """Write the tool-computed agreement onto every evidence item read from an image."""
    f = Path(a.fragment)
    frag = json.loads(f.read_text())
    slug, counts, pending, engines = frag["source"], {}, [], set()
    for rec in (frag.get("nodes") or []) + (frag.get("links") or []):
        for i, ev in enumerate((rec.get("props") or {}).get("evidence") or []):
            if ev.get("reading") in VISION and valid_region(ev.get("region")) and ev.get("transcription"):
                rr = region_reading(slug, evidence_page(ev), ev["region"])
                engines |= set(rr["engines"])
                got = sourcetext.region_agreement(ev["transcription"], rr["words"], ev.get("kind"))
                ev["agreement"] = got["agreement"]
                counts[got["agreement"]] = counts.get(got["agreement"], 0) + 1
                if got["agreement"] != "agree" and not ev.get("second_reading"):
                    pending.append(f"{rec['id']}#{i}")
    if engines:
        frag["ocr_engines"] = sorted(engines)       # the OCR every agreement above was computed with
    f.write_text(dump_canonical(frag))
    print(json.dumps({"source": slug, "agreement": counts, "need_second_reading": len(pending), "ocr_engines": sorted(engines)}, indent=1))
    return 0


def cmd_ocr_import(a) -> int:
    """Copy page words and region words from the uncommitted cache (work/pages, written before the OCR was
    committed) into curation/ocr. Existing files are kept unless --overwrite: the machine whose OCR the
    agreements were computed with overwrites, so that every machine checks against that OCR."""
    copied, kept = 0, 0
    for src in sorted(PAGES.glob("*/p*.words.json")) + sorted(PAGES.glob("*/regions/*.json")):
        dest = OCR / src.relative_to(PAGES)
        if dest.exists() and not a.overwrite:
            kept += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        got = json.loads(src.read_text())
        if src.parent.name == "regions" and isinstance(got, list):
            got = {"ocr_engine": None, "words": got}         # a region cache written before engines were recorded
        if a.written_here:                                   # the curator states the cache was written by the OCR here
            stated = got.get("ocr_engine")
            if stated and not stated.startswith(str(sourcetext.tesseract_version())):
                raise ScaleError(f"{src} records {stated!r}, not the OCR here ({ocr_engine()}); import it without --written-here")
            got["ocr_engine"] = ocr_engine()
        dest.write_text(dump_canonical(got))
        copied += 1
    print(json.dumps({"copied": copied, "kept": kept, "into": str(OCR)}, indent=1))
    return 0


def cmd_pending(a) -> int:
    """The regions a second reader must read: crops and locators only, never the first transcription."""
    frag = json.loads(Path(a.fragment).read_text())
    slug, by_region = frag["source"], {}
    for rec in (frag.get("nodes") or []) + (frag.get("links") or []):
        for i, ev in enumerate((rec.get("props") or {}).get("evidence") or []):
            if ev.get("reading") in VISION and ev.get("agreement") not in (None, "agree") and not ev.get("second_reading"):
                page = evidence_page(ev)
                rk = region_key(page, ev["region"])
                crop = PAGES / slug / "crops" / f"{rk}.second.png"
                if not crop.exists():      # with a margin: a tight region must not cut off what the second reader needs
                    crop.parent.mkdir(parents=True, exist_ok=True)
                    x0, y0, x1, y1 = ev["region"]
                    padded = (max(0.0, x0 - SECOND_MARGIN), max(0.0, y0 - SECOND_MARGIN), min(1.0, x1 + SECOND_MARGIN), min(1.0, y1 + SECOND_MARGIN))
                    crop.write_bytes(sourcetext.render_page(pdf_of(slug), page, 400, padded))
                item = by_region.setdefault(rk, {"region_key": rk, "page": page, "locator": ev.get("locator"), "region": ev["region"],
                                                 "crop": str(crop), "kind": ev.get("kind"), "keys": []})
                item["keys"].append(f"{rec['id']}#{i}")
    items = sorted(by_region.values(), key=lambda x: x["region_key"])
    out = WORK / "second" / f"{slug}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(items, ensure_ascii=False, indent=1))
    print(json.dumps({"source": slug, "pending": len(items), "file": str(out)}, indent=1))
    return 0


def cmd_merge_second(a) -> int:
    """Copy the second readings (curation/second-readings/<slug>.json: {key: reading}) onto the evidence."""
    f = FRAGMENTS / f"{a.slug}.json"
    frag = json.loads(f.read_text())
    sf = SECOND / f"{a.slug}.json"
    second = json.loads(sf.read_text()) if sf.exists() else {}      # no region needed a second reader
    n = 0
    for rec in (frag.get("nodes") or []) + (frag.get("links") or []):
        for i, ev in enumerate((rec.get("props") or {}).get("evidence") or []):
            key = f"{rec['id']}#{i}"
            rk = region_key(evidence_page(ev), ev["region"]) if ev.get("region") else None
            reading = second.get(key) or (second.get(rk) if rk else None)
            if reading and ev.get("reading") in VISION:
                ev["second_reading"] = reading
                n += 1
    f.write_text(dump_canonical(frag))
    print(json.dumps({"source": a.slug, "second_readings": n}, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("brief")
    b.add_argument("slug")
    b.add_argument("--corpus", type=Path, default=Path(os.environ["SCALE_METHANOL_CORPUS"]) if os.environ.get("SCALE_METHANOL_CORPUS") else None,
                   help="the corpus directory, for the checklist of earlier extractions (default: $SCALE_METHANOL_CORPUS)")
    c = sub.add_parser("check")
    c.add_argument("fragment")
    s = sub.add_parser("assemble")
    s.add_argument("--out", default=str(DATA / "methanol-synthesis.graph.json"))
    sub.add_parser("status")
    pg = sub.add_parser("pages")
    pg.add_argument("slug")
    pg.add_argument("--dpi", type=int, default=200)
    pg.add_argument("--pages", help="comma-separated PDF pages (default: all)")
    rg = sub.add_parser("region")
    rg.add_argument("slug")
    rg.add_argument("page", type=int)
    for k in ("x0", "y0", "x1", "y1"):
        rg.add_argument(k, type=float)
    rg.add_argument("--dpi", type=int, default=400)
    rg.add_argument("--transcription", help="what you read there, to see OCR's agreement")
    ag = sub.add_parser("agree")
    ag.add_argument("fragment")
    oi = sub.add_parser("ocr-import")
    oi.add_argument("--overwrite", action="store_true", help="replace committed OCR files with the cache's")
    oi.add_argument("--written-here", action="store_true",
                    help="the cache was written on this machine: record this machine's OCR engine with every file")
    pe = sub.add_parser("pending")
    pe.add_argument("fragment")
    ms = sub.add_parser("merge-second")
    ms.add_argument("slug")
    sc = sub.add_parser("scope")
    sc.add_argument("--out", default=str(DATA / "methanol-synthesis.co-co2-hydrogenation.graph.json"))
    bu = sub.add_parser("bundle")
    bu.add_argument("--out", default=str(DATA / "galaxy" / f"methanol-synthesis_v{BUNDLE_VERSION}"))
    bu.add_argument("--previous", type=Path, help="the previous release folder (none for the first release)")
    bu.add_argument("--ids-from", type=Path, help="an earlier build whose ids to keep, not recorded as the previous release")
    bu.add_argument("--created", default="2026-09-29T00:00:00Z")
    bu.add_argument("--frozen-at", default="2026-09-28")
    a = ap.parse_args(argv)
    try:
        return {"brief": cmd_brief, "check": cmd_check, "assemble": cmd_assemble, "status": cmd_status, "pages": cmd_pages, "region": cmd_region, "agree": cmd_agree, "ocr-import": cmd_ocr_import,
                "pending": cmd_pending, "merge-second": cmd_merge_second, "scope": cmd_scope, "bundle": cmd_bundle}[a.cmd](a)
    except ScaleError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
