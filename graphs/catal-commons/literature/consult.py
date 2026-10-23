#!/usr/bin/env python3
"""consult.py - answer questions about the catalysis catalog (index.db). Read-only, standard library only.

Run from this folder (CONSULT.md explains every definition). index.db is not in the hlxin/scale repository
(10.9 GB): pass --db /path/to/index.db, set CATALYSIS_SOURCES_DB, or put index.db next to this file.
  python3 -I consult.py count     --concept co2-reduction --driver electro
  python3 -I consult.py breakdown --concept co2-reduction --by driver
  python3 -I consult.py breakdown --concept co2-reduction --driver electro --by year
  python3 -I consult.py list      --concept co2-reduction --driver electro --year 2024-2026 --limit 20 [--format csv]
  python3 -I consult.py terms     co2rr,pec,pulsed,electrolyzer,metal-air,bioelectro --with-co2   (per term, Topic A-C)
  python3 -I consult.py source     10.1002/adma.202202952          (a DOI, an ID, or title words)
  python3 -I consult.py concepts | drivers | topics | schema
  python3 -I consult.py sql       "SELECT doc_type, COUNT(*) FROM sources GROUP BY 1"

Filters (count / breakdown / list; all combine with AND, a comma means "any of"):
  --concept NAME     built-in concept (`concepts` lists them; every vocabulary id is one too)
  --driver NAME      what drives the catalysis: electro, photo, photoelectro, thermal, plasma, bio, electrified-heat, mechano
  --topic LABEL      vocabulary topic (label or id) as Topic A/B/C; add --related to also match related topics (looser:
                     related topics include vocabulary neighbours)
  --text EXPR        SQLite FTS5 query on title + abstract + keywords, e.g. 'copper AND (ethylene OR "c2h4")'
  --title EXPR       the same, title only
  --author NAME      author name contains NAME
  --year 2020-2026 | 2024   --doc-type article,review   --access OA,OA+ND   --venue "ACS Catal,Nature Catalysis"
  --include-notices      also count errata, ChemInform digests, cover pages and retracted sources (excluded by default)
Concepts and drivers are answered at two levels: strict (title or Topic A/B/C) and broad (anywhere in title, abstract
or keywords). Report both; strict is the conservative number.
"""
import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# index.db is not in the repository (10.9 GB): --db, $CATALYSIS_SOURCES_DB, next to this file, or a project layout
_ENV_DB = os.environ.get("CATALYSIS_SOURCES_DB") or os.environ.get("CATALYSIS_PAPERS_DB")      # (its earlier name)
DB_CANDIDATES = ([Path(_ENV_DB)] if _ENV_DB else []) + [
    ROOT / "co2-reduction-electricity.db", ROOT / "index.db", ROOT / "sources" / "index.db", ROOT.parent / "sources" / "index.db",
    ROOT / "papers.db", ROOT / "publications" / "papers.db", ROOT.parent / "publications" / "papers.db"]   # their earlier names
DEFAULT_DB = next((p for p in DB_CANDIDATES if p.exists()), ROOT / "index.db")
VOCAB_FILES = [ROOT / "vocabulary.json",                                       # catal commons (hlxin/scale layout)
               ROOT / ".scripts" / "vocab.json",                                 # a project folder
               ROOT / ".scripts" / "vocab_custom.json"]
CHUNK = 30000


# ----------------------------------------------------------------------------- FTS5 helpers
def q(p):
    """an exact phrase"""
    return '"' + p.replace('"', '""') + '"'


def qp(p):
    """a phrase whose last word is a prefix ("co2 reduc" * matches CO2 reduction, CO2-reducing ...)"""
    return q(p) + " *"


def any_of(*parts):
    return "(" + " OR ".join(parts) + ")"


CO2 = ["co2", "co₂", "co 2", "carbon dioxide"]
CO2_ANY = any_of("co2", "co₂", q("co 2"), q("carbon dioxide"))
CO2_REDUCTION = any_of(
    "co2rr", "eco2rr", "co2err", "co2er",
    *[qp(f"{c} {w}") for c in CO2 for w in ("reduc", "electroreduc", "photoreduc", "hydrogenat", "methanat",
                                            "electrolys", "electrolyz")],
    *[q(f"{w} of {c}") for c in CO2 for w in ("reduction", "electroreduction", "photoreduction", "hydrogenation",
                                              "methanation", "electrolysis")],
    *[q(f"{c} to {p}") for c in ("co2", "co₂") for p in ("co", "formate", "formic acid", "methanol", "methane",
                                                         "ethylene", "ethanol", "multicarbon", "c2", "c2+", "fuels",
                                                         "hydrocarbons", "syngas", "oxalate", "acetate")])
CO2_CONVERSION = any_of(
    CO2_REDUCTION, *[qp(f"{c} conver") for c in CO2], *[qp(f"{c} utili") for c in CO2],
    *[q(f"conversion of {c}") for c in CO2], *[q(f"cycloaddition of {c}") for c in ("co2", "carbon dioxide")],
    q("co2 cycloaddition"), q("co2 fixation"), q("co2 capture and conversion"), q("dry reforming"),
    q("co2 reforming"), qp("co2 carboxyl"))

# --------------------------------------------------------------------------- built-in concepts
# topics: vocabulary ids (Topic A/B/C = strict, related = broad); topics_if_co2: count only when CO2 is mentioned;
# fts: text phrases (title = strict, title/abstract/keywords = broad)
CONCEPTS = {
    "co2-reduction": dict(
        about="Reduction of CO2 by any route: electrochemical, photocatalytic, photoelectrochemical, thermocatalytic "
              "hydrogenation/methanation/RWGS, plasma, enzymatic. Not cycloaddition or other non-reductive uses.",
        topics=["co2rr", "photo-co2rr", "co2-hydrogenation", "co2-conversion", "rwgs"],
        topics_if_co2=["methanation", "co2-methanol", "metal-air", "plasma", "bioelectro"],
        fts=CO2_REDUCTION),
    "co2-conversion": dict(
        about="Any catalytic CO2 conversion or utilization: co2-reduction plus cycloaddition/carboxylation, dry "
              "reforming, integrated capture and conversion.",
        topics=["co2rr", "photo-co2rr", "co2-hydrogenation", "co2-conversion", "rwgs", "ccu"],
        topics_if_co2=["methanation", "co2-methanol", "reforming", "metal-air", "plasma", "bioelectro"],
        fts=CO2_CONVERSION),
    "co-reduction": dict(
        about="CO (carbon monoxide) electroreduction and CO-to-C2+ (text match needs the full words, since 'CO' "
              "and 'Co' are the same token).",
        topics=["corr"], topics_if_co2=[],
        fts=any_of(q("carbon monoxide reduction"), q("carbon monoxide electroreduction"),
                   q("electroreduction of carbon monoxide"), q("reduction of carbon monoxide"),
                   qp("co electroreduc"), q("electroreduction of co"))),
    "nitrogen-to-ammonia": dict(
        about="N2 fixation to ammonia by any route (electrochemical NRR, Li-mediated, photocatalytic, Haber-Bosch).",
        topics=["nrr", "li-nrr", "photo-n2", "nh3-synthesis"], topics_if_co2=[],
        fts=any_of(qp("nitrogen reduc"), qp("n2 reduc"), q("reduction of nitrogen"), q("reduction of n2"),
                   qp("nitrogen fixat"), qp("n2 fixat"), q("ammonia synthesis"), q("ammonia electrosynthesis"),
                   q("haber bosch"), qp("dinitrogen reduc"), q("nh3 synthesis"))),
    "nitrate-reduction": dict(
        about="Nitrate / nitrite / NO reduction (mostly to ammonia).",
        topics=["no3rr", "no2rr", "norr"], topics_if_co2=[],
        fts=any_of(qp("nitrate reduc"), qp("nitrate electroreduc"), q("reduction of nitrate"),
                   q("electroreduction of nitrate"), qp("nitrite reduc"), q("reduction of nitrite"),
                   "no3rr", q("no3 rr"), qp("nitric oxide reduc"), qp("nitric oxide electroreduc"))),
    "ammonia": dict(
        about="Ammonia in any role: synthesis (N2, nitrate, NO), decomposition/cracking, oxidation.",
        topics=["nrr", "li-nrr", "no3rr", "no2rr", "norr", "photo-n2", "nh3-synthesis", "nh3-decomp", "aor"],
        topics_if_co2=[], fts=any_of("ammonia", "nh3")),
    "water-splitting": dict(
        about="Water splitting and its half reactions (HER, OER) by electrolysis, photocatalysis or PEC.",
        topics=["her", "oer", "water-electrolysis", "seawater", "photo-h2"], topics_if_co2=[],
        fts=any_of(q("water splitting"), q("hydrogen evolution"), q("oxygen evolution"), q("water electrolysis"),
                   q("water oxidation"), q("h2 evolution"), q("o2 evolution"), q("seawater electrolysis"))),
    "hydrogen-production": dict(
        about="H2 production by any route (water splitting, reforming, ammonia cracking, photocatalysis).",
        topics=["her", "water-electrolysis", "seawater", "photo-h2", "h2-production", "reforming", "nh3-decomp",
                "oxygenate-reforming"], topics_if_co2=[],
        fts=any_of(q("hydrogen production"), q("h2 production"), q("hydrogen generation"), q("h2 generation"),
                   q("hydrogen evolution"), q("green hydrogen"))),
    "oxygen-reduction": dict(
        about="Oxygen reduction (4e- to water for fuel cells/metal-air, 2e- to H2O2).",
        topics=["orr", "h2o2-electro"], topics_if_co2=[],
        fts=any_of(q("oxygen reduction"), q("o2 reduction"), q("reduction of oxygen"), q("reduction of o2"),
                   q("oxygen electroreduction"))),
    "methane-conversion": dict(
        about="Methane activation, reforming, partial oxidation, coupling, methane to methanol.",
        topics=["reforming", "methane-oxidation", "ocm", "methane-electro"], topics_if_co2=[],
        fts=any_of(qp("methane conver"), qp("methane activat"), qp("methane oxid"), q("methane reforming"),
                   q("dry reforming"), q("steam methane reforming"), q("methane coupling"),
                   q("methane to methanol"), q("oxidative coupling of methane"))),
    "biomass-conversion": dict(
        about="Catalytic conversion of biomass and its platform molecules (lignin, cellulose, HMF, glycerol ...).",
        topics=["biomass", "biomass-electro", "oxygenate-reforming"], topics_if_co2=[],
        fts=any_of("biomass", "lignin", "lignocellulos*", "cellulose", "hemicellulose", q("5 hydroxymethylfurfural"),
                   "hmf", "furfural", "glycerol", "levulinic")),
    "plastics-upcycling": dict(
        about="Catalytic plastic upcycling, depolymerization and chemical recycling.",
        topics=["plastics"], topics_if_co2=[],
        fts=any_of(q("plastic upcycling"), q("plastic waste"), q("plastics upcycling"), q("chemical recycling"),
                   qp("polyolefin hydrogenoly"), qp("pet depolymeri"), qp("plastic depolymeri"), q("waste plastics"))),
    "pollutant-degradation": dict(
        about="Catalytic degradation of pollutants and advanced oxidation processes (water treatment).",
        topics=["aop", "remediation"], topics_if_co2=[],
        fts=any_of(q("advanced oxidation"), "peroxymonosulfate", "persulfate", qp("fenton"),
                   q("pollutant degradation"), q("dye degradation"), q("degradation of"), q("antibiotic degradation"))),
    "organic-synthesis": dict(
        about="Catalytic organic synthesis: cross-coupling, C-H activation, asymmetric, organo- and photoredox "
              "catalysis, hydroformylation, electrosynthesis.",
        topics=["cross-coupling", "asymmetric", "organocatalysis", "photoredox", "hydroformylation",
                "organic-synthesis", "electrosynthesis"], topics_if_co2=[],
        fts=any_of(q("cross coupling"), q("c h activation"), q("c h functionalization"), "enantioselective",
                   q("asymmetric catalysis"), "organocatalytic", "organocatalysis", q("photoredox catalysis"))),
}

# ---------------------------------------------------------------------------- drivers
# topics: vocabulary ids that imply the driver; fts: marker words; competitors: drivers whose markers in the TITLE
# (or whose topics as Topic A/B/C) rule this one out as the MAIN driver (e.g. "photoelectrochemical" is not electro)
ELECTRO_FTS = any_of(
    "electroreduc*", "electrocatal*", "electrolys*", "electrolyz*", "electrolyser*", "electrosynth*", "electrooxid*",
    q("electro oxidation"), q("electro reduction"), "faradaic*", "overpotential*", q("membrane electrode"),
    q("gas diffusion electrode"), q("zero gap"), q("flow cell"), q("h cell"), "potentiostatic*",
    "chronoamperometr*", q("electrochemical reduction"), q("electrochemical conversion"),
    q("electrochemical synthesis"), q("electrochemical oxidation"), q("electrochemical production"),
    q("electrochemical hydrogenation"), q("electrochemical co2"), q("electrochemical nitrogen"),
    q("electrochemical nitrate"), q("electrochemical ammonia"), q("electrochemical water"),
    q("electrochemical hydrogen"), q("electrochemical oxygen"), q("fuel cell"), q("fuel cells"), q("zinc air"),
    q("metal air"), "co2rr", "eco2rr")
PHOTO_FTS = any_of(
    "photocatal*", "photoreduc*", "photochem*", "photoinduc*", "photoexcit*", "photogenerat*", "photoactiv*",
    "photoredox", "photosensitiz*", "photothermal*", "plasmon*", q("visible light"), q("light driven"),
    q("light irradiation"), q("uv light"), q("solar light"), "sunlight", q("artificial photosynthesis"))
PHOTOELECTRO_FTS = any_of("photoelectro*", "photoelectrode*", "photocathod*", "photoanod*",
                          q("photo electrochemical"), q("photo electrocatalytic"), q("photo assisted electro"))
DRIVERS = {
    "electro": dict(
        about="Electricity drives the reaction: electrocatalysis/electrolysis (incl. fuel cells, metal-air and "
              "Li-S batteries, bioelectrocatalysis).",
        topics=["co2rr", "corr", "her", "hor", "oer", "orr", "h2o2-electro", "nrr", "li-nrr", "no3rr", "no2rr",
                "norr", "n-oxidation", "cn-coupling", "aor", "uor", "mor", "eor", "faor", "biomass-electro", "ech",
                "electrosynthesis", "cer", "seawater", "water-electrolysis", "methane-electro", "metal-air", "li-s",
                "fuel-cell", "sofc-soec", "electrolyzer", "pulsed", "microenvironment", "bioelectro"],
        fts=ELECTRO_FTS, competitors=["photo", "photoelectro"]),
    "photo": dict(
        about="Light drives the reaction: photocatalysis, photoredox, photothermal/plasmonic catalysis.",
        topics=["photo-co2rr", "photo-h2", "photo-n2", "photo-h2o2", "photoredox", "photocatalysis",
                "photothermal"],
        fts=PHOTO_FTS, competitors=["electro", "photoelectro"]),
    "photoelectro": dict(
        about="Light and electricity together: photoelectrochemical cells, photoelectrodes, PEC.",
        topics=["pec"], fts=PHOTOELECTRO_FTS, competitors=[]),
    "thermal": dict(
        about="Conventional heat-driven catalysis (thermocatalysis: hydrogenation, reforming, methanation, FT ...; "
              "most heterogeneous and homogeneous catalysis).",
        topics=["co2-hydrogenation", "co2-methanol", "rwgs", "wgs", "methanation", "fts", "nh3-synthesis",
                "nh3-decomp", "reforming", "oxygenate-reforming", "methane-oxidation", "ocm", "dehydrogenation",
                "hydrogenation", "selective-oxidation", "co-oxidation", "emission-control", "refining", "mth", "coal"],
        fts=any_of("thermocatal*", q("thermal catalysis"), q("thermal catalytic"), "thermochemical",
                   q("fixed bed"), "ghsv", "whsv", q("space velocity"), q("reverse water gas shift"), "rwgs",
                   q("fischer tropsch"), "methanat*", q("dry reforming"), q("steam reforming"), "sabatier",
                   "hydrogenat*"),
        competitors=["electro", "photo", "photoelectro", "plasma"]),
    "plasma": dict(
        about="Non-thermal plasma (electric discharge) drives the reaction.",
        topics=["plasma"],
        fts=any_of(q("plasma catalysis"), q("plasma catalytic"), q("plasma assisted"), q("plasma driven"),
                   q("non thermal plasma"), q("nonthermal plasma"), q("dielectric barrier discharge"), "dbd",
                   q("gliding arc"), q("glow discharge"), q("microwave plasma"), q("plasma reactor")),
        competitors=[]),
    "bio": dict(
        about="Enzymes or living cells drive the reaction: biocatalysis, whole-cell, biohybrid and "
              "bioelectrocatalysis.",
        topics=["biocatalysis", "enzymes", "bioelectro"],
        fts=any_of("biocatal*", "enzymat*", q("enzyme catalyzed"), q("whole cell"), "biohybrid*",
                   q("formate dehydrogenase"), q("carbonic anhydrase"), "cyanobacteri*", "microbial"),
        competitors=[]),
    "electrified-heat": dict(
        about="Electricity used as the heat source of a thermal reaction (Joule, induction, microwave heating).",
        topics=["electrified-thermal"],
        fts=any_of(q("joule heating"), q("induction heating"), q("electrified heating"), q("resistive heating"),
                   q("electrically heated"), "electrothermal", q("microwave heating"), q("electrified reactor")),
        competitors=[]),
    "mechano": dict(
        about="Mechanical energy (ball milling) drives the catalysis.",
        topics=["mechanocatalysis"], fts=any_of("mechanocatal*", q("mechanochemical catalysis")), competitors=[]),
}
ACRONYM = re.compile(r"^[A-Za-z]{2,5}s?$")


def load_vocab():
    terms = {}
    for f in VOCAB_FILES:
        if f.exists():
            d = json.loads(f.read_text(encoding="utf-8"))
            for t in (d.get("terms") if isinstance(d, dict) else d) or []:
                terms[t["id"]] = t
    return terms


def vocab_concept(t):
    """every vocabulary term is also a concept: its topic + its multi-word synonyms as phrases (short acronyms such
    as HER or SAC are left to the topic match, since full-text search cannot tell HER from 'her')"""
    phrases = []
    for s in [t.get("label", "")] + list(t.get("synonyms") or []):
        s = (s or "").strip()
        if not s or s.startswith("re:") or (ACRONYM.match(s) and not s.islower()):
            continue
        phrases.append(q(s.lower()))
    return dict(about=f"Vocabulary term '{t['label']}': {t.get('name', '')}", topics=[t["id"]], topics_if_co2=[],
                fts=any_of(*dict.fromkeys(phrases)) if phrases else None)


# --------------------------------------------------------------------------------- catalog
class Catalog:
    def __init__(self, db):
        if not Path(db).exists():
            sys.exit(f"no database at {db}. index.db is not in the repository (10.9 GB): pass --db /path/to/index.db "
                     f"or set CATALYSIS_SOURCES_DB, or put co2-reduction-electricity.db in this folder "
                     f"(the CO2 subset, README.md).")
        self.db = Path(db)
        self.c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        if self.c.execute("SELECT 1 FROM sqlite_master WHERE name = 'papers'").fetchone():
            sys.exit(f"{db} names its tables as before the sources were so named (papers, paper_id ...). Upgrade it "
                     f"once, where it can be written:\n  python3 -I skills/index-sources/scripts/upgrade.py --db {db}")
        self.c.execute("PRAGMA query_only=1")
        self.vocab = load_vocab()
        self.cache = {}
        self.tables = {r[0] for r in self.c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}

    def built_at(self):
        try:
            r = self.c.execute("SELECT value FROM about WHERE name='built_at'").fetchone()
            return r[0] if r else None
        except sqlite3.Error:
            return None

    def fts(self, expr, title_only=False):
        if not expr:
            return set()
        key = ("fts", expr, title_only)
        if key not in self.cache:
            e = f"{{title}} : ({expr})" if title_only else expr
            try:
                self.cache[key] = {r[0] for r in self.c.execute(
                    "SELECT rowid FROM sources_fts WHERE sources_fts MATCH ?", (e,))}
            except sqlite3.OperationalError as err:
                sys.exit(f"full-text query not understood ({err}): {e}\nSyntax: words, \"exact phrase\", prefix*, "
                         f"AND / OR / NOT, parentheses, NEAR(a b, 5). See CONSULT.md.")
        return self.cache[key]

    def term_ids(self, names):
        """vocabulary ids for labels or ids (case-insensitive)"""
        by_label = {t["label"].lower(): i for i, t in self.vocab.items()}
        if "subjects" in self.tables:
            for term, label in self.c.execute("SELECT term, label FROM subjects"):
                by_label.setdefault((label or "").lower(), term)
        out = []
        for n in names:
            k = n.strip().lower()
            if k in self.vocab or k in {v for v in by_label.values()}:
                out.append(k)
            elif k in by_label:
                out.append(by_label[k])
            else:
                sys.exit(f"unknown topic '{n}'. `python3 -I consult.py topics` lists the vocabulary.")
        return out

    def topic(self, terms, main_only):
        if not terms:
            return set()
        key = ("topic", tuple(sorted(terms)), main_only)
        if key not in self.cache:
            sql = (f"SELECT source_id FROM source_subjects WHERE term IN ({','.join('?' * len(terms))})"
                   + (" AND kind='main'" if main_only else ""))
            self.cache[key] = {r[0] for r in self.c.execute(sql, terms)}
        return self.cache[key]

    def author(self, name):
        return {r[0] for r in self.c.execute(
            "SELECT pa.source_id FROM authors au JOIN source_authors pa ON pa.author_id = au.id WHERE au.name LIKE ?",
            (f"%{name}%",))}

    def concept(self, name, level):
        spec = CONCEPTS.get(name) or (vocab_concept(self.vocab[name]) if name in self.vocab else None)
        if not spec:
            sys.exit(f"unknown concept '{name}'. `python3 -I consult.py concepts` lists them.")
        strict = self.topic(spec["topics"], True) | self.fts(spec["fts"], True)
        if spec.get("topics_if_co2"):
            strict |= self.topic(spec["topics_if_co2"], True) & self.fts(CO2_ANY)
        if level == "strict":
            return strict
        # broad adds text matches in the abstract/keywords; related topics are NOT used here: they include the
        # vocabulary neighbours of Topic A/B/C (an ORR source gets CO2RR as a related topic), which is too loose
        return strict | self.fts(spec["fts"])

    def driver(self, name, level):
        spec = DRIVERS.get(name)
        if not spec:
            sys.exit(f"unknown driver '{name}'. Drivers: {', '.join(DRIVERS)}")
        pos = self.topic(spec["topics"], True) | self.fts(spec["fts"], True)
        if level == "broad":
            pos = pos | self.fts(spec["fts"])
        for comp in spec["competitors"]:
            cs = DRIVERS[comp]
            pos = pos - (self.fts(cs["fts"], True) | self.topic(cs["topics"], True))
        return pos

    def rows(self, ids, where, args, cols):
        """sources rows for these ids (None = every source) that pass the SQL filters"""
        base = f"SELECT {cols} FROM sources WHERE {' AND '.join(where) if where else '1'}"
        if ids is None:
            yield from self.c.execute(base, args)
            return
        ids = sorted(ids)
        for i in range(0, len(ids), CHUNK):
            part = ids[i:i + CHUNK]
            yield from self.c.execute(base + f" AND id IN ({','.join('?' * len(part))})", list(args) + part)


# ---------------------------------------------------------------------------------- queries
def split(v):
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def source_filters(a):
    w, args = [], []
    if not a.include_notices:
        w.append("COALESCE(is_notice,0)=0 AND COALESCE(is_retracted,0)=0")
    if a.year:
        y = a.year.split("-")
        w.append("year BETWEEN ? AND ?")
        args += [int(y[0]), int(y[-1] or 9999)]
    for col, val in (("doc_type", a.doc_type), ("access_type", a.access)):
        if val:
            vals = split(val)
            w.append(f"{col} IN ({','.join('?' * len(vals))})")
            args += vals
    if a.venue:
        vs = split(a.venue)
        w.append("(" + " OR ".join("venue LIKE ?" for _ in vs) + ")")
        args += [f"%{v}%" for v in vs]
    return w, args


def candidate_ids(cat, a, level):
    sets = []
    if a.concept:
        sets.append(set().union(*(cat.concept(c, level) for c in split(a.concept))))
    if a.driver:
        sets.append(set().union(*(cat.driver(d, level) for d in split(a.driver))))
    if a.topic:
        sets.append(cat.topic(cat.term_ids(split(a.topic)), not a.related))
    if a.text:
        sets.append(cat.fts(a.text))
    if a.title:
        sets.append(cat.fts(a.title, True))
    if a.author:
        sets.append(cat.author(a.author))
    if not sets:
        return None
    sets.sort(key=len)
    return sets[0].intersection(*sets[1:])


def levels(a):
    return ["strict", "broad"] if (a.concept or a.driver) else ["any"]


def header(cat, a, command):
    filt = {k: v for k, v in vars(a).items() if k not in ("cmd", "db", "format", "func") and v not in (None, False, "")}
    defs = {}
    for c in split(a.concept):
        spec = CONCEPTS.get(c) or (vocab_concept(cat.vocab[c]) if c in cat.vocab else {})
        defs[f"concept:{c}"] = spec.get("about")
    for d in split(a.driver):
        defs[f"driver:{d}"] = DRIVERS.get(d, {}).get("about")
    return {"command": command, "filters": filt, "definitions": defs, "db": str(cat.db), "db_built_at": cat.built_at(),
            "asked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


NOT_LITERATURE = {"patent", "dataset", "software"}
NOTES = ["strict = the concept/driver is in the title or in Topic A/B/C; broad = anywhere in title, abstract or "
         "keywords (more recall, some noise). Report both.",
         "records = every matching row; papers = records minus patents, datasets and software (see by_doc_type).",
         "Errata, ChemInform digests, cover pages and retracted sources are excluded unless --include-notices.",
         "Access type and license are the metadata verdict (classify_access.py); a downloaded PDF can still change it."]


def cmd_count(cat, a):
    out = header(cat, a, "count")
    w, args = source_filters(a)
    for lv in levels(a):
        ids = candidate_ids(cat, a, "broad" if lv == "any" else lv)
        by = Counter(r[0] for r in cat.rows(ids, w, args, "doc_type"))
        out[lv] = {"records": sum(by.values()),
                   "papers": sum(v for k, v in by.items() if k not in NOT_LITERATURE),
                   "by_doc_type": dict(by.most_common())}
    out["notes"] = NOTES
    return out


def cmd_breakdown(cat, a):
    out = header(cat, a, "breakdown")
    w, args = source_filters(a)
    for lv in levels(a):
        lvl = "broad" if lv == "any" else lv
        ids = candidate_ids(cat, a, lvl)
        if a.by == "driver":
            res, seen = {}, set()
            base = {r[0] for r in cat.rows(ids, w, args, "id")}
            for d in DRIVERS:
                s = base & cat.driver(d, lvl)
                res[d] = len(s)
                seen |= s
            res["no_driver_detected"] = len(base - seen)
            out[lv] = {"total": len(base), "by_driver": res,
                       "note": "drivers overlap (a source can have two); no_driver_detected = none found"}
        else:
            col = {"year": "year", "doc_type": "doc_type", "venue": "venue", "topic_a": "topic_a",
                   "access_type": "access_type", "publisher": "publisher"}[a.by]
            by = Counter(r[0] for r in cat.rows(ids, w, args, col))
            items = sorted(by.items(), key=lambda kv: (kv[0] is None, kv[0])) if a.by == "year" else by.most_common(a.limit)
            out[lv] = {"total": sum(by.values()), f"by_{a.by}": {str(k): v for k, v in items}}
    out["notes"] = NOTES
    return out


LIST_COLS = "id, doi, identifier, year, title, venue, doc_type, topic_a, topic_b, topic_c, access_type, licence, citations, url"


def cmd_list(cat, a):
    w, args = source_filters(a)
    lv = a.level if (a.concept or a.driver) else "broad"
    ids = candidate_ids(cat, a, lv)
    strict = candidate_ids(cat, a, "strict") if (a.concept or a.driver) and lv == "broad" else None
    rows = [dict(zip([c.strip() for c in LIST_COLS.split(",")], r)) for r in cat.rows(ids, w, args, LIST_COLS)]
    key = {"citations": lambda r: -(r["citations"] or 0), "year": lambda r: -(r["year"] or 0),
           "id": lambda r: r["id"]}[a.sort]
    rows.sort(key=key)
    total = len(rows)
    rows = rows[:a.limit] if a.limit else rows
    for r in rows:
        r["match"] = ("strict" if strict is None or r["id"] in strict else "broad") if (a.concept or a.driver) else "-"
    if a.format in ("csv", "tsv"):
        wr = csv.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()) if rows else ["id"],
                            delimiter="," if a.format == "csv" else "\t")
        wr.writeheader()
        wr.writerows(rows)
        return None
    out = header(cat, a, "list")
    out.update({"level": lv, "matching": total, "shown": len(rows), "sort": a.sort, "sources": rows})
    return out


def cmd_source(cat, a):
    key = a.query.strip()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", key, flags=re.I).lower()
    ids = []
    if key.isdigit():
        ids = [int(key)]
    if not ids and doi.startswith("10."):
        ids = [r[0] for r in cat.c.execute("SELECT DISTINCT source_id FROM identifiers WHERE value = ?", (doi,))]
        ids += [r[0] for r in cat.c.execute("SELECT id FROM sources WHERE doi = ?", (doi,)) if r[0] not in ids]
    if not ids:
        ids = [r[0] for r in cat.c.execute("SELECT DISTINCT source_id FROM identifiers WHERE value = ?", (key,))]
    if not ids:
        words = " AND ".join(q(t) for t in re.findall(r"\w+", key.lower()))
        hits = cat.fts(words, True) if words else set()
        ids = [r[0] for r in cat.c.execute(
            f"SELECT id FROM sources WHERE id IN ({','.join('?' * len(hits))}) ORDER BY citations DESC LIMIT 5",
            sorted(hits))] if hits else []
    out = header(cat, a, "source")
    out["matches"] = []
    for pid in ids[:5]:
        cur = cat.c.execute("SELECT * FROM sources WHERE id = ?", (pid,))
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        if not row:
            continue
        p = dict(zip(cols, row))
        p.pop("sha1", None)
        p["authors_detail"] = [dict(zip(["position", "name", "orcid", "institutions", "countries"], r)) for r in cat.c.execute(
            "SELECT pa.position, au.name, au.orcid, pa.institutions, pa.countries FROM source_authors pa "
            "JOIN authors au ON au.id = pa.author_id WHERE pa.source_id = ? ORDER BY pa.position", (pid,))]
        p["identifiers"] = [f"{s}={v}" for s, v in cat.c.execute(
            "SELECT scheme, value FROM identifiers WHERE source_id = ?", (pid,))]
        p["databases"] = [r[0] for r in cat.c.execute("SELECT database FROM source_databases WHERE source_id = ?", (pid,))]
        p["topics"] = [dict(zip(["label", "kind", "rank", "method"], r)) for r in cat.c.execute(
            "SELECT label, kind, rank, method FROM source_subjects WHERE source_id = ? ORDER BY kind, rank", (pid,))]
        for t in ("supplements", "si_links"):
            if t in cat.tables:
                cur = cat.c.execute(f"SELECT * FROM {t} WHERE source_id = ?", (pid,))
                p[t] = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        p["topics"] = [dict(zip(["topic", "relevance", "in_scope"], r)) for r in cat.c.execute(
            "SELECT topic, relevance, in_scope FROM source_topics WHERE source_id = ?", (pid,))]
        out["matches"].append(p)
    return out


def cmd_terms(cat, a):
    """the skill's vocabulary-first answer (references/database.md): sources per term as Topic A/B/C, each term
    separately so the asker decides what to include, plus how many of them mention CO2 and the union"""
    out = header(cat, a, "terms")
    w, args = source_filters(a)
    base = candidate_ids(cat, a, "broad")
    co2 = cat.fts(CO2_ANY) if a.with_co2 else None
    res, union = {}, set()
    for t in cat.term_ids(split(a.terms)):
        ids = cat.topic([t], True)
        if base is not None:
            ids = ids & base
        ids = {r[0] for r in cat.rows(ids, w, args, "id")}
        entry = {"term": t, "sources_with_it_as_topic_A-C": len(ids)}
        if co2 is not None:
            entry["of_which_mention_co2"] = len(ids & co2)
        res[cat.vocab.get(t, {}).get("label", t)] = entry
        union |= ids
    out["terms"] = res
    out["union_all_terms"] = len(union)
    if co2 is not None:
        out["union_mentioning_co2"] = len(union & co2)
    out["notes"] = ["Counts Topic A/B/C only (source_subjects.kind = 'main'); errata/retracted excluded.",
                    "Report each term separately; the union removes sources counted under two terms."]
    return out


def cmd_concepts(cat, a):
    out = {"concepts": {k: {"about": v["about"], "topics": v["topics"], "topics_if_co2_mentioned": v["topics_if_co2"],
                            "fts": v["fts"]} for k, v in CONCEPTS.items()},
           "vocabulary_concepts": "every vocabulary id is also a concept: " + ", ".join(sorted(cat.vocab)),
           "drivers": {k: {"about": v["about"], "topics": v["topics"], "fts": v["fts"],
                           "not_main_driver_if_title_or_topic_A-C_is": v["competitors"]} for k, v in DRIVERS.items()}}
    if a.name:
        n = a.name
        spec = CONCEPTS.get(n) or (vocab_concept(cat.vocab[n]) if n in cat.vocab else None) or DRIVERS.get(n)
        return {n: spec} if spec else {"error": f"unknown concept or driver '{n}'"}
    return out


def cmd_drivers(cat, a):
    return {k: {"about": v["about"], "topics": v["topics"], "fts": v["fts"], "competitors": v["competitors"]}
            for k, v in DRIVERS.items()}


def cmd_topics(cat, a):
    counts = Counter()
    for term, kind, n in cat.c.execute("SELECT term, kind, COUNT(*) FROM source_subjects GROUP BY term, kind"):
        counts[(term, kind)] = n
    labels = {t["id"]: (t["label"], t["facet"], t.get("name", "")) for t in cat.vocab.values()}
    out = []
    for tid in sorted(set(labels) | {k[0] for k in counts}):
        lab, facet, name = labels.get(tid, (tid, "?", ""))
        if a.like and a.like.lower() not in f"{tid} {lab} {name}".lower():
            continue
        out.append({"id": tid, "label": lab, "facet": facet, "name": name,
                    "sources_main_A-C": counts.get((tid, "main"), 0), "sources_related": counts.get((tid, "related"), 0)})
    out.sort(key=lambda r: -r["sources_main_A-C"])
    return {"db_built_at": cat.built_at(), "topics": out,
            "note": "topic counts come from the vocabulary match (topics.py); concepts and drivers add text matches"}


def cmd_schema(cat, a):
    out = {}
    for (name,) in cat.c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE "
                                 "'sources_fts_%' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        try:
            out[name] = [r[1] for r in cat.c.execute(f"PRAGMA table_info('{name}')")]
        except sqlite3.Error:
            out[name] = []
    about = {k: v for k, v in cat.c.execute("SELECT name, value FROM about")} if "about" in cat.tables else {}
    return {"db": str(cat.db), "db_built_at": cat.built_at(), "tables": out, "about": about}


def cmd_sql(cat, a):
    cur = cat.c.execute(a.query)
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchmany(a.limit)
    return {"db_built_at": cat.built_at(), "columns": cols, "rows": [list(r) for r in rows], "shown": len(rows),
            "limit": a.limit}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DEFAULT_DB), help="index.db to read (default: $CATALYSIS_SOURCES_DB or index.db next to this file)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def filters(p):
        p.add_argument("--concept")
        p.add_argument("--driver")
        p.add_argument("--topic")
        p.add_argument("--related", action="store_true", help="--topic also matches related topics (looser)")
        p.add_argument("--text")
        p.add_argument("--title")
        p.add_argument("--author")
        p.add_argument("--year")
        p.add_argument("--doc-type")
        p.add_argument("--access")
        p.add_argument("--venue")
        p.add_argument("--include-notices", "--include-non-papers", dest="include_notices", action="store_true")

    p = sub.add_parser("count", help="how many sources match")
    filters(p)
    p.set_defaults(func=cmd_count)
    p = sub.add_parser("breakdown", help="counts per driver / year / doc_type / venue / topic_a / access_type")
    filters(p)
    p.add_argument("--by", required=True, choices=["driver", "year", "doc_type", "venue", "topic_a", "access_type",
                                                   "publisher"])
    p.add_argument("--limit", type=int, default=40, help="top N values (venue, topic_a ...)")
    p.set_defaults(func=cmd_breakdown)
    p = sub.add_parser("list", help="the matching sources")
    filters(p)
    p.add_argument("--level", choices=["strict", "broad"], default="broad")
    p.add_argument("--sort", choices=["citations", "year", "id"], default="citations")
    p.add_argument("--limit", type=int, default=50, help="0 = all")
    p.add_argument("--format", choices=["json", "csv", "tsv"], default="json")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("terms", help="sources per vocabulary term (Topic A/B/C), each term separately")
    p.add_argument("terms", help="comma list of vocabulary ids or labels, e.g. co2rr,pec,pulsed,electrolyzer")
    p.add_argument("--with-co2", action="store_true", help="also count how many of them mention CO2")
    filters(p)
    p.set_defaults(func=cmd_terms)
    p = sub.add_parser("source", aliases=["paper"], help="one source by DOI, ID or title words")
    p.add_argument("query")
    p.set_defaults(func=cmd_source, concept=None, driver=None)
    p = sub.add_parser("concepts", help="the built-in concepts and drivers with their exact definitions")
    p.add_argument("name", nargs="?")
    p.set_defaults(func=cmd_concepts)
    p = sub.add_parser("drivers", help="the drivers and how they are detected")
    p.set_defaults(func=cmd_drivers)
    p = sub.add_parser("topics", help="vocabulary topics with source counts")
    p.add_argument("--like")
    p.set_defaults(func=cmd_topics)
    p = sub.add_parser("schema", help="tables and columns of index.db")
    p.set_defaults(func=cmd_schema)
    p = sub.add_parser("sql", help="any read-only SQL")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=1000)
    p.set_defaults(func=cmd_sql)
    a = ap.parse_args()
    cat = Catalog(a.db)
    res = a.func(cat, a)
    if res is not None:
        json.dump(res, sys.stdout, ensure_ascii=False, indent=1, default=str)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
