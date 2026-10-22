"""(library module) MDPI: www.mdpi.com refuses scripted clients (Akamai), but MDPI serves its CC BY article PDFs and SI
files from its public CDN, mdpi-res.com (no robots.txt; verified 2026-10-09):
  https://mdpi-res.com/d_attachment/{slug}/{slug}-{vol:02d}-{art:05d}/article_deploy/{slug}-{vol:02d}-{art:05d}.pdf
  ...-s001.zip / -s002.pdf ... for supplementary materials
"""
import re

# DOI abbreviation -> journal URL slug (only where they differ from a simple lower-case of the title)
ABBREV_SLUG = {
    "catal": "catalysts", "nano": "nanomaterials", "ma": "materials", "en": "energies", "pr": "processes",
    "polym": "polymers", "app": "applsci", "su": "sustainability", "cryst": "crystals", "s": "sensors",
    "mi": "micromachines", "met": "metals", "molecules": "molecules", "ijms": "ijms", "coatings": "coatings",
    "inorganics": "inorganics", "membranes": "membranes", "chemengineering": "chemengineering",
    "batteries": "batteries", "separations": "separations", "gels": "gels", "electrochem": "electrochem",
    "suschem": "suschem", "nanoenergyadv": "nanoenergyadv", "hydrogen": "hydrogen", "chemistry": "chemistry",
    "reactions": "reactions", "colloids": "colloids", "c": "c", "fuels": "fuels", "cleantechnol": "cleantechnol",
    "ijerph": "ijerph", "eng": "eng", "solar": "solar", "methane": "methane", "physchem": "physchem",
    "surfaces": "surfaces", "chemosensors": "chemosensors", "environments": "environments", "applnano": "applnano",
    "compounds": "compounds", "chemproc": "chemproc", "materproc": "materproc", "engproc": "engproc",
    "jcs": "jcs", "ceramics": "ceramics", "j": "j", "sci": "sci", "biomolecules": "biomolecules",
    "bioengineering": "bioengineering", "microorganisms": "microorganisms", "fermentation": "fermentation",
    "water": "water", "atmosphere": "atmosphere", "applchem": "applchem", "gases": "gases", "powders": "powders",
    "nanomanufacturing": "nanomanufacturing", "condensedmatter": "condensedmatter", "energies": "energies",
    "crystals": "crystals", "materials": "materials", "processes": "processes", "polymers": "polymers",
    "jmmp": "jmmp", "micro": "micro", "electronics": "electronics", "entropy": "entropy", "magnetochemistry": "magnetochemistry",
    "nanomaterials": "nanomaterials", "sustainability": "sustainability", "chemsensors": "chemosensors",
    "ecm": "ecm", "csac": "csac", "ecsoc": "ecsoc", "proceedings": "proceedings",
}


def parse_doi(doi):
    m = re.match(r"^10\.3390/([a-z]+)(\d+)$", (doi or "").lower())
    if not m:
        return None, None, None
    abbrev, digits = m.groups()
    if len(digits) < 7:
        return abbrev, None, None
    vol = int(digits[:-6]) if digits[:-6] else None
    art = int(digits[-4:])
    if vol is not None and vol > 40 and len(digits) >= 8:  # 5-digit article numbers (e.g. IJMS)
        vol, art = int(digits[:-7]), int(digits[-5:])
    return abbrev, vol, art


def slug_candidates(doi, journal_title=None):
    abbrev, _, _ = parse_doi(doi)
    out = []
    if abbrev and abbrev in ABBREV_SLUG:
        out.append(ABBREV_SLUG[abbrev])
    if journal_title:
        t = re.sub(r"[^a-z]", "", journal_title.lower())
        if t and t not in out:
            out.append(t)
    if abbrev and abbrev not in out:
        out.append(abbrev)
    return out[:3]


def article_base(doi, cr=None, journal_title=None):
    """Return candidate CDN base names like 'catalysts-09-00683' (most likely first)."""
    abbrev, vol, art = parse_doi(doi)
    if cr:
        try:
            vol = int(str(cr.get("volume")).strip()) if cr.get("volume") else vol
        except ValueError:
            pass
        an = cr.get("article_number") or cr.get("page")
        if an and str(an).strip().isdigit():
            art = int(str(an).strip())
    if vol is None or art is None:
        return []
    return [(s, f"{s}-{vol:02d}-{art:05d}") for s in slug_candidates(doi, journal_title or (cr or {}).get("journal"))]


def pdf_urls(doi, cr=None, journal_title=None):
    return [f"https://mdpi-res.com/d_attachment/{s}/{b}/article_deploy/{b}.pdf" for s, b in article_base(doi, cr, journal_title)]


def si_base(pdf_url):
    """From a working CDN PDF URL to the SI prefix: .../article_deploy/catalysts-09-00683-s"""
    return pdf_url[:-4] + "-s" if pdf_url.endswith(".pdf") else None
