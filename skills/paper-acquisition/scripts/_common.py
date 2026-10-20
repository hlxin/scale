"""Shared helpers for the paper-acquisition scripts (library module — not run directly).

Project layout (all paths relative to the project root = the directory the scripts run from):
  publications/papers.db                              the paper database (SQLite snapshot, all topics) — open it with
                                                      any SQLite tool; rebuilt by every step from the working ledger
  publications/<topic>/index/{OA,OA+ND,Free-to-read,Paywalled,merged,excluded}.csv
                                                      the topic's index, one CSV per access type + all of them merged
  publications/<topic>/papers/<ACCESS>/<ID>.pdf       downloaded papers, ACCESS in OA, OA+ND, Free-to-read, Paywalled
  publications/<topic>/papers/SI/<ACCESS>/<ID>_SI*    supplementary files, same access folder as the paper
  publications/exports/                               filtered subsets the user asked for (export.py --name ...)
  .scripts/ledger.sqlite                              working ledger (source of truth; WAL mode)
  .scripts/<topic>/                                   per-topic config, queries, raw hits, caches, state, logs
  .scripts/ezproxy/                                   this project's EZproxy outcomes log
  ~/.paper-acquisition/keys.txt                       API keys, one `service: key` per line (README.md)
  ~/.paper-acquisition/ezproxy/                       machine-wide EZproxy config + limiter state (one per computer:
                                                      the limits protect the institution's IP, whatever the project)
"""
import contextlib
import datetime as _dt
import fcntl
import hashlib
import html
import json
import os
import random
import re
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import requests

# ------------------------------------------------------------------ access types (folder names)
ACCESS_TYPES = ["OA", "OA+ND", "Free-to-read", "Paywalled"]  # most open first
ACCESS_HELP = {
    "OA": "Open Access with a license that allows derivatives (CC BY, BY-SA, BY-NC, BY-NC-SA, CC0, public domain)",
    "OA+ND": "Open Access, no derivatives (CC BY-ND, CC BY-NC-ND)",
    "Free-to-read": "free to read online but no reuse license (bronze, publisher terms, unlicensed manuscript)",
    "Paywalled": "subscription only (institutional access through EZproxy / campus network)",
}
OPEN_LICENSES = {"cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa", "cc0", "public-domain"}
ND_LICENSES = {"cc-by-nd", "cc-by-nc-nd"}
LICENSE_LABEL = {"cc-by": "CC BY", "cc-by-sa": "CC BY-SA", "cc-by-nc": "CC BY-NC", "cc-by-nc-sa": "CC BY-NC-SA",
                 "cc-by-nd": "CC BY-ND", "cc-by-nc-nd": "CC BY-NC-ND", "cc0": "CC0", "public-domain": "Public domain",
                 "publisher-specific": "Publisher terms", "other-oa": "Free to read (no license)",
                 "all-rights-reserved": "All rights reserved", "none": "None"}

SOURCE_LABEL = {"openalex": "OpenAlex", "crossref": "Crossref", "crossref_preprints": "Crossref (preprint servers)",
                "s2": "Semantic Scholar", "europepmc": "Europe PMC", "europepmc_patents": "Europe PMC (patents)",
                "pmc": "PubMed Central", "openaire": "OpenAIRE", "openaire_data": "OpenAIRE (datasets)", "osti": "OSTI",
                "arxiv": "arXiv", "doaj": "DOAJ", "hal": "HAL", "zenodo": "Zenodo", "figshare": "Figshare",
                "osf": "OSF Preprints", "plos": "PLOS", "datacite": "DataCite", "dataverse": "Harvard Dataverse",
                "dryad": "Dryad", "ntrs": "NASA NTRS", "jstage": "J-STAGE", "cinii": "CiNii Research",
                "mcloud": "Materials Cloud Archive", "eric": "ERIC", "core": "CORE", "scopus": "Scopus",
                "springer": "Springer Nature", "wos": "Web of Science", "lens": "Lens.org",
                "lens_patents": "Lens.org (patents)", "ieee": "IEEE Xplore", "ads": "NASA ADS", "epo": "EPO (patents)",
                "citations": "Citation chasing (OpenAlex)", "manual": "Imported list", "legacy": "Previous run",
                "scale": "SCALE corpus list"}

# Document types (papers.doc_type). Datasets and software are indexed but never downloaded.
DOC_TYPES = ["article", "review", "preprint", "conference-paper", "book-chapter", "book", "thesis", "report", "patent",
             "dataset", "software", "editorial", "letter", "erratum", "other"]
NOT_DOWNLOADED_TYPES = {"dataset", "software"}
_DOC_RULES = [  # (doc_type, regex on the source's raw type) — first match wins; order matters
    ("erratum", r"erratum|correction|retraction|corrigendum|expression.of.concern"),
    ("patent", r"patent"),
    ("dataset", r"dataset|research.data|^data$|database"),
    ("software", r"software|^code$|computational.notebook"),
    ("thesis", r"dissertation|thesis|^these$|^hdr$|^mem$|^etd$"),
    ("preprint", r"preprint|posted.content|^undefined$|working.paper|accepted.manuscript|submitted"),
    ("review", r"review|meta.?analysis|short.survey"),
    ("conference-paper", r"conference|proceedings|^comm$|poster|presentation|meeting.abstract|^conf"),
    ("book-chapter", r"chapter|book.?section|^section$|^couv$|reference.entry|^part$"),
    ("book", r"^book$|monograph|edited.book|^ouv$|^books$"),
    ("report", r"report|memorandum|deliverable|technical.note|technicalnote|standard|white.?paper|^tm$"),
    ("editorial", r"editorial|news|paratext|^other.?editorial|biography|obituary"),
    ("letter", r"letter|comment|correspondence|^note$"),
    ("article", r"article|journal|^art$|^text$|^study$|research|^publication$|reprint|^jour$|communication"),
]
_DOC_RX = [(t, re.compile(rx, re.I)) for t, rx in _DOC_RULES]


def norm_doc_type(raw, is_preprint=False):
    """Any source's type string(s) -> one of DOC_TYPES. Several raw types (S2 'Review,JournalArticle') resolve to the
    most specific one (review beats article)."""
    vals = raw if isinstance(raw, (list, tuple)) else re.split(r"[,;|]", str(raw or ""))
    vals = [re.sub(r"[_\-]+", " ", str(v)).strip().lower() for v in vals if str(v or "").strip()]
    found = None
    for t, rx in _DOC_RX:
        if any(rx.search(v) or rx.search(v.replace(" ", "")) for v in vals):
            found = t
            break
    if is_preprint and found in (None, "article", "other", "report"):
        return "preprint"
    return found or ("other" if vals else "article")


def access_rank(a):
    return ACCESS_TYPES.index(a) if a in ACCESS_TYPES else len(ACCESS_TYPES)


def license_access(lic):
    """License token -> access type, or None when the token says nothing about reuse rights."""
    if lic in OPEN_LICENSES:
        return "OA"
    if lic in ND_LICENSES:
        return "OA+ND"
    return None


def slugify(text, maxlen=60):
    s = re.sub(r"[^a-z0-9\s-]", "", (text or "").lower())
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return s[:maxlen].strip("-") or "topic"


# ------------------------------------------------------------------ paths
GLOBAL_DIR = Path(os.environ.get("PAPER_ACQ_HOME") or (Path.home() / ".paper-acquisition"))


class Project:
    """All paths of one project (the folder that holds publications/ and .scripts/)."""

    def __init__(self, root=None):
        self.root = Path(root or os.getcwd()).resolve()
        self.pub = self.root / "publications"
        self.scr = self.root / ".scripts"
        self.ledger_db = self.scr / "ledger.sqlite"
        self.db = self.pub / "papers.db"
        self.exports = self.pub / "exports"
        self.logs = self.scr / "logs"
        self.tmp = self.scr / "tmp"
        self.ez = self.scr / "ezproxy"            # per-project outcomes log
        self.ezg = GLOBAL_DIR / "ezproxy"         # machine-wide config.json + limiter_state.json
        for d in (self.pub, self.scr, self.logs, self.tmp, self.ez):   # ezg is created only by the EZproxy scripts
            d.mkdir(parents=True, exist_ok=True)

    def topic_dir(self, slug):
        return self.scr / slug

    def index_dir(self, slug):
        return self.pub / slug / "index"

    def pdf_dir(self, slug, access):
        return self.pub / slug / "papers" / access

    def si_dir(self, slug, access):
        return self.pub / slug / "papers" / "SI" / access

    def rel(self, p):
        try:
            return str(Path(p).resolve().relative_to(self.root))
        except ValueError:
            return str(p)

    def topics(self):
        """Slugs of every topic in this project (one .scripts/<slug>/config.json each)."""
        return sorted(p.parent.name for p in self.scr.glob("*/config.json"))

    def make_topic_folders(self, slug):
        self.index_dir(slug).mkdir(parents=True, exist_ok=True)
        for a in ACCESS_TYPES:
            self.pdf_dir(slug, a).mkdir(parents=True, exist_ok=True)
        td = self.topic_dir(slug)
        for sub in ("raw", "screen"):
            (td / sub).mkdir(parents=True, exist_ok=True)
        return td


def add_project_arg(ap):
    ap.add_argument("--project", default=None, help="project root (default: current directory)")
    return ap


# ------------------------------------------------------------------ logging / time
def now_iso():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today():
    return _dt.date.today().isoformat()


def log(*a):
    """Progress goes to stderr; stdout carries only each script's final JSON result."""
    print(f"[{_dt.datetime.now().strftime('%H:%M:%S')}]", *a, file=sys.stderr, flush=True)


def die(msg, code=2):
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


# ------------------------------------------------------------------ JSON / JSONL
_locks = {}
_locks_guard = threading.Lock()


@contextlib.contextmanager
def file_lock(path):
    """Cross-process (flock) + cross-thread lock keyed on `path`."""
    lp = Path(str(path) + ".lock")
    with _locks_guard:
        tl = _locks.setdefault(str(lp), threading.Lock())
    with tl:
        with open(lp, "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)


def jsonl_append(path, rec_or_recs):
    recs = rec_or_recs if isinstance(rec_or_recs, list) else [rec_or_recs]
    if not recs:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    data = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs)
    with file_lock(path):
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())


def jsonl_iter(path):
    p = Path(path)
    if not p.exists():
        return
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate a torn final line after a crash


def json_write_atomic(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def json_read(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------ topic config / state
def load_config(proj, slug):
    cfg = json_read(proj.topic_dir(slug) / "config.json")
    if cfg is None:
        die(f"no config for topic '{slug}' — run init_topic.py first (looked in {proj.topic_dir(slug)}/config.json)")
    set_contact(cfg.get("polite_email"))
    return cfg


def save_config(proj, slug, cfg):
    json_write_atomic(proj.topic_dir(slug) / "config.json", cfg)


def load_state(proj, slug):
    return json_read(proj.topic_dir(slug) / "state.json", {}) or {}


def update_state(proj, slug, fn):
    """Atomically read-modify-write .scripts/<topic>/state.json under a cross-process lock."""
    path = proj.topic_dir(slug) / "state.json"
    with file_lock(path):
        st = json_read(path, {}) or {}
        fn(st)
        st["updated_at"] = now_iso()
        json_write_atomic(path, st)
        return st


KEY_FILES_HELP = "~/.paper-acquisition/keys.txt (one `service: key` per line; see the skill's README.md)"
KEY_ALIASES = {"semantic_scholar": "s2", "semanticscholar": "s2", "elsevier": "scopus", "sciencedirect": "scopus",
               "springer_nature": "springer", "springernature": "springer", "web_of_science": "wos",
               "clarivate": "wos", "lens.org": "lens", "nasa_ads": "ads", "ieee_xplore": "ieee", "core_api": "core",
               "epo_ops_key": "epo_key", "epo_ops_secret": "epo_secret", "ncbi_api_key": "ncbi", "llm": "llm_api_key",
               "api": "llm_api_key", "crossref_plus": "crossref"}


def key_files(proj=None):
    """Key files in precedence order (later files override earlier ones)."""
    files = [GLOBAL_DIR / "keys.txt"]
    if proj is not None:
        files.append(proj.root / ".claude" / "keys.txt")
    return files


def parse_keys(text):
    keys = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*[:=]\s*(.+?)\s*$", line)
        if not m:
            continue
        name = m.group(1).strip().lower().replace("-", "_")
        val = m.group(2).strip().strip('"').strip("'")
        if val and not val.startswith("<"):
            keys[KEY_ALIASES.get(name, name)] = val
    return keys


def load_keys(proj=None, with_origin=False):
    """API keys from ~/.paper-acquisition/keys.txt and (optional override) <project>/.claude/keys.txt.
    Lines look like `core: abc123` (also accepted: `core = abc123`); `#` starts a comment line. Values are never
    printed or logged by any script."""
    keys, origin = {}, {}
    for f in key_files(proj):
        try:
            text = f.read_text()
        except OSError:
            continue
        for k, v in parse_keys(text).items():
            keys[k] = v
            origin[k] = str(f)
    return (keys, origin) if with_origin else keys


# ------------------------------------------------------------------ text normalization
_INLINE_TAGS = re.compile(r"</?(sub|sup|inf|i|b|em|strong|u|scp|span|small|tt|font|mml:[a-z]+|math|jats:[a-z-]+)"
                          r"(\s[^>]*)?/?>", re.I)
_LATEX_SUB = re.compile(r"\$\s*_\{?\s*([0-9+\-−]+)\s*\}?\s*\$")
_LATEX_WRAP = re.compile(r"\\(?:mathrm|textrm|mathit|text)\{([^{}]*)\}")
# Titles where a subscript became a space ("CO 2 reduction", "Fe 2 O 3"). Rejoin only runs that are clearly
# chemical formulas: >= 2 element+number pairs, or one pair of a common gas/carbon count, or one metal pair
# followed by O/S/N/... (Cu 2 O). Words that are also element symbols ("In 2 steps", "At 2 V") stay untouched.
_ELEMENTS = set("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr "
                "Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb "
                "Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am".split())
_SINGLE_OK = {"CO", "H", "N", "O", "C", "CH", "NH", "NO", "SO", "OH", "HCO", "Cl", "F"}
_METAL_OK = {"Cu", "Ag", "Au", "Zn", "Bi", "Sn", "Fe", "Co", "Ni", "Mn", "Ti", "Mo", "W", "Pd", "Pt", "Ru", "Ir", "Ce",
             "In", "Ga", "V", "Cr", "Nb", "Ta", "Zr", "Al", "Si", "Li", "Na", "K", "Mg", "Ca", "Sr", "Ba", "La", "Y",
             "Cd", "Pb", "Sb", "Te", "Ge", "Rh", "Os", "Re", "Hf", "Sc", "Gd", "Nd", "Sm", "Eu", "Pr"}
_TRAIL_OK = {"O", "N", "S", "C", "H", "F", "P", "Cl", "Br", "I", "Se"}
_NUM_TOK = re.compile(r"^(\d+(?:\.\d+)?)([+\-−]?)([,;:)\]\.]*|\([a-z]{1,3}\)[,;:.]?)$")  # 2, 2+, 2), 2(aq)


def _is_elem_tok(tok):
    if not tok or not tok[0].isupper():
        return False
    i = 0
    while i < len(tok):
        if i + 1 < len(tok) and tok[i + 1].islower() and tok[i:i + 2] in _ELEMENTS:
            i += 2
        elif tok[i] in _ELEMENTS and (i + 1 >= len(tok) or not tok[i + 1].islower()):
            i += 1
        else:
            return False
    return True


def fix_formula_spacing(t):
    if not t or not re.search(r"[A-Z][a-z]? \d", t):
        return t
    toks = t.split(" ")
    out, i = [], 0
    while i < len(toks):
        lead = re.match(r"^(.*[(\[\]\-–‐−—/*,\uf8ff])?(.*)$", toks[i])  # "Li–CO", "Pd/Cu", "*CO", "(CO": formula after the last separator
        prefix, first = lead.group(1) or "", lead.group(2)
        pairs, j, run, ended = 0, i, [], False
        tok = first
        while j + 1 < len(toks) and _is_elem_tok(tok) and _NUM_TOK.match(toks[j + 1]):
            m = _NUM_TOK.match(toks[j + 1])
            run += [tok, m.group(1) + m.group(2)]
            pairs += 1
            j += 2
            if m.group(3) or m.group(2):  # punctuation or a charge sign ends the formula
                run[-1] += m.group(3)
                ended = True
                break
            tok = toks[j] if j < len(toks) else ""
        if pairs:
            head = run[0]
            nxt = toks[j] if (not ended and j < len(toks)) else ""
            tm = re.match(r"^([A-Z][a-z]?)([\-–‐/)\],.;:].*)?$", nxt)  # "O", "O/Cu", "O,"
            trailing = bool(tm and tm.group(1) in _TRAIL_OK)
            if pairs >= 2 or head in _SINGLE_OK or (trailing and head in _METAL_OK):
                joined = prefix + "".join(run)
                if trailing:
                    joined += nxt
                    j += 1
                out.append(joined)
                i = j
                continue
        out.append(toks[i])
        i += 1
    return " ".join(out)


def clean_text(t):
    """HTML/JATS/LaTeX -> plain text. Inline formatting tags are removed WITHOUT a space (CO<sub>2</sub> -> CO2)."""
    if not t:
        return ""
    t = html.unescape(str(t))
    t = _INLINE_TAGS.sub("", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)  # double-escaped entities (&amp;amp;)
    if "$" in t or "\\" in t:
        t = _LATEX_WRAP.sub(r"\1", t)
        t = _LATEX_SUB.sub(r"\1", t)
        t = re.sub(r"\$_\{?(\d+)\}?", r"\1", t)
    t = re.sub(r"\s+", " ", t).strip()
    return fix_formula_spacing(t)


def clean_title(t):
    t = clean_text(t)
    return t.rstrip(" .") if t.endswith(".") and not t.endswith("..") else t


def clean_name(n):
    n = clean_text(n)
    return re.sub(r"\s*,\s*", ", ", n).strip(" ,;")


def norm_doi(doi):
    if not doi:
        return None
    d = urllib.parse.unquote(str(doi).strip())
    d = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", d, flags=re.I)
    d = re.sub(r"^doi:\s*", "", d, flags=re.I)
    d = d.strip().rstrip(".,;)]").lower()
    return d if d.startswith("10.") and "/" in d else None


def norm_title(t):
    t = clean_text(t)
    t = t.replace("₂", "2").replace("₃", "3").replace("₄", "4")
    t = re.sub(r"[^a-z0-9 ]", "", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def title_hash(t):
    return hashlib.sha1(norm_title(t).encode()).hexdigest()[:16]


def reconstruct_abstract(inv):
    """OpenAlex abstract_inverted_index -> plain text."""
    if not inv:
        return ""
    pos = sorted((i, w) for w, idxs in inv.items() for i in idxs)
    return " ".join(w for _, w in pos)


ERRATUM_RX = re.compile(r"^\s*((editorial\s+)?(correction|corrigendum|erratum|addendum|retraction( note| notice)?|"
                        r"expression of concern|retracted( article)?|withdrawn( article)?|withdrawal|publisher'?s? note|"
                        r"author correction)\b(\s+(to|of|for|on)\b|\s*[:.\-–—]|\s*$)|"
                        r"notice of (retraction|concern|withdrawal)\b)", re.I)
# peer-review artefacts that carry their own DOIs (RSC/Wiley/eLife review reports, decision letters, author replies)
REVIEW_TITLE_RX = re.compile(r"^\s*(review for\b|reviewer report|decision letter|author response|response to reviewers|"
                             r"peer review (report|history)\b|cheminform abstract\b|((inside|front|back)\s+){0,2}cover\s+"
                             r"(feature|picture|image|art)\b|((inside|front|back)\s+){0,2}cover\s*:|frontispiece\s*(:|$)|"
                             r"graphical abstract\s*(:|$)|table of contents\s*(:|$))", re.I)
# peer-review DOIs; Wiley ChemInform abstract digests (10.1002/chin.*) reprint other journals' abstracts
REVIEW_DOI_RX = re.compile(r"(/v\d+/(review|decision|reply|response)\d*$|/peer[-_]?review|\.sa\d+$|/review\d+$|"
                           r"^10\.1002/chin\.)", re.I)


def is_erratum(title, ctype=None, doi=None):
    """Not a research article: erratum/correction/retraction notice, or a peer-review report with its own DOI."""
    if ctype and str(ctype).lower() in ("correction", "erratum", "retraction", "expression-of-concern", "peer-review"):
        return True
    if doi and REVIEW_DOI_RX.search(doi):
        return True
    return bool(ERRATUM_RX.search(title or "") or REVIEW_TITLE_RX.search(title or ""))


# Abstract clean-up (every abstract that enters the ledger goes through normalize_abstract):
#  - a leading heading: "Abstract", "ABSTRACT:", "Summary. —", or glued to the text ("AbstractMXenes have...");
#    the next word must start with a capital or digit, so "Abstracting hydrogen..." / "Abstract algebra" stay
#  - ACS graphical-abstract debris ("High Resolution Image Download MS PowerPoint Slide")
#  - the copyright line at the end ("© 2020 Elsevier B.V. All rights reserved.", "(c) 2015 ...", "Copyright © ...")
#  - placeholders ("[No abstract available]") become empty
# a heading glued to the text: "Abstract Electrocatalytic ...", "Abstract: ...", "AbstractThe ...", and before chemistry
# notation that starts in lower case or Greek ("Abstract p‐block metals ...", "Abstract α‐Fe2O3 ...")
_ABS_HEAD_RX = re.compile(r"^\s*(?i:graphical\s+abstract|abstract|summary)"
                          r"(?:(?:\s*[:.\-–—])+\s*|\s+(?=[A-Z0-9(\[“\"α-ωΑ-Ω]|[a-z][\s\-‐‑–])|(?=[A-Z0-9]))")
_ABS_DEBRIS_RX = re.compile(r"\s*High Resolution Image\s*Download MS PowerPoint Slide\s*", re.I)
_ABS_COPYRIGHT_RX = re.compile(r"\s*(©|\(c\)(?=\s*(19|20)\d\d)|\bcopyright\b).{0,300}$", re.I | re.S)
_ABS_PLACEHOLDER_RX = re.compile(r"^\W*(no abstract( is)? available|abstract (is )?not available|no abstract|n/?a)\W*$", re.I)


def normalize_abstract(t, cap=6000):
    """Any source's abstract -> clean plain text ('' for a placeholder). Idempotent."""
    t = clean_text(t)
    if not t or _ABS_PLACEHOLDER_RX.match(t):
        return ""
    t = _ABS_DEBRIS_RX.sub(" ", t).strip()
    for _ in range(2):
        t2 = _ABS_HEAD_RX.sub("", t, count=1)
        if t2 == t:
            break
        t = t2
    m = _ABS_COPYRIGHT_RX.search(t)
    if m:
        t = t[:m.start()].rstrip()
    return "" if _ABS_PLACEHOLDER_RX.match(t) else t[:cap]


def export_abstract(t):
    """normalize_abstract for the index CSVs and papers.db, skipped for the (already clean) abstracts that show none of
    the debris it removes — a catalog of millions is exported without re-cleaning every text."""
    if not t:
        return ""
    head = t[:40].lstrip().lower()
    if len(t) >= 80 and not head.startswith(("abstract", "summary", "graphical")) and "©" not in t and "<" not in t \
            and "&" not in t and "High Resolution" not in t:
        low = t[-400:].lower()                  # a copyright line can only be the tail
        if "copyright" not in low and "(c)" not in low:
            return t
    return normalize_abstract(t)


def norm_license(s):
    """Any license string/URL -> canonical token: cc-by, cc-by-sa, cc-by-nc, cc-by-nc-sa, cc-by-nd, cc-by-nc-nd,
    cc0, public-domain, publisher-specific, other-oa, or None (unknown)."""
    if not s:
        return None
    x = str(s).strip().lower()
    if not x:
        return None
    if "publicdomain/zero" in x or re.search(r"\bcc0\b|cc-zero|cc zero", x):
        return "cc0"
    if "publicdomain/mark" in x or x in ("public-domain", "pd", "public domain"):
        return "public-domain"
    m = re.search(r"creativecommons\.org/licen[cs]es/([a-z\-]+)", x)
    if m:
        toks = [p for p in m.group(1).split("-") if p]
        if not toks or toks[0] != "by":
            return "other-oa"
    else:
        m = re.search(r"\bcc[\s\-_]*by((?:[\s\-_]*(?:nc|nd|sa))*)", x) or \
            re.match(r"^by((?:[\s\-_]*(?:nc|nd|sa))*)\b", x)
        if m:
            toks = ["by"] + re.findall(r"nc|nd|sa", m.group(1))
        elif "creative commons" in x or "attribution" in x:
            toks = ["by"]
            if re.search(r"non[\s\-]?commercial", x):
                toks.append("nc")
            if re.search(r"no[\s\-]?deriv", x):
                toks.append("nd")
            if re.search(r"share[\s\-]?alike", x):
                toks.append("sa")
        else:
            if any(k in x for k in ("publisher-specific", "author-manuscript", "elsevier", "acs", "wiley", "springer",
                                    "tdm", "terms", "policy")):
                return "publisher-specific"
            if "other-oa" in x or "implied-oa" in x or "unspecified-oa" in x:
                return "other-oa"
            return "publisher-specific" if x.startswith("http") else "other-oa"
    has_nc, has_nd, has_sa = "nc" in toks, "nd" in toks, "sa" in toks
    if has_nd:
        return "cc-by-nc-nd" if has_nc else "cc-by-nd"
    if has_nc:
        return "cc-by-nc-sa" if has_sa else "cc-by-nc"
    return "cc-by-sa" if has_sa else "cc-by"


_LIC_VER = re.compile(r"(?<![\d.])([1-4]\.0)(?![\d])")
PUBLISHER_TERMS = [  # license URL fragment -> readable name (publisher-specific terms, not a reuse license)
    ("elsevier.com/tdm/userlicense", "Elsevier TDM user license"),
    ("elsevier.com/open-access/userlicense", "Elsevier open access user license"),
    ("elsevier.com/legal/tdmrep-license", "Elsevier TDM license"), ("elsevier.com", "Elsevier terms"),
    ("onlinelibrary.wiley.com/termsandconditions", "Wiley terms and conditions"),
    ("doi.wiley.com/10.1002/tdm_license", "Wiley TDM license"), ("wiley.com", "Wiley terms"),
    ("pubs.acs.org/page/policy/authorchoice", "ACS AuthorChoice"), ("acs.org", "ACS terms"),
    ("springernature.com/gp/researchers/text-and-data-mining", "Springer Nature TDM"),
    ("springer.com/tdm", "Springer Nature TDM"), ("springernature.com", "Springer Nature terms"),
    ("springer.com", "Springer terms"), ("iopscience.iop.org/info/page/text-and-data-mining", "IOP TDM"),
    ("iop.org", "IOP terms"), ("rsc.org", "RSC terms"), ("academic.oup.com", "Oxford University Press terms"),
    ("aip.org", "AIP terms"), ("aps.org", "APS terms"), ("tandfonline.com", "Taylor & Francis terms"),
    ("sagepub.com", "SAGE terms"), ("ieee.org", "IEEE terms"), ("cambridge.org", "Cambridge University Press terms"),
    ("ecsdl.org", "ECS terms"), ("electrochem.org", "ECS terms"), ("science.org", "AAAS terms"),
    ("thieme", "Thieme terms"), ("degruyter", "De Gruyter terms"), ("pnas.org", "PNAS terms"),
]


def license_detail(raw, token=None):
    """Exact, readable license with its version when the source states one:
    'http://creativecommons.org/licenses/by-nc/4.0/' -> ('CC BY-NC 4.0', url); 'cc-by' -> ('CC BY', None);
    an Elsevier TDM URL -> ('Elsevier TDM user license', url). Returns (label, url) — (None, None) when unknown."""
    if not raw and not token:
        return None, None
    x = str(raw or "").strip()
    url = x if re.match(r"^https?://", x, re.I) else None
    tok = token or norm_license(x)
    if tok in LICENSE_LABEL and tok not in ("publisher-specific", "other-oa"):
        label = LICENSE_LABEL[tok]
        m = _LIC_VER.search(x.replace("_", "."))
        if tok == "cc0":
            label = "CC0 1.0" if ("1.0" in x or "zero" in x.lower()) else "CC0"
        elif m:
            label += " " + m.group(1)
        if tok.startswith("cc-by") and re.search(r"\bigo\b", x, re.I):
            label += " IGO"
        return label, url
    low = x.lower()
    for frag, name in PUBLISHER_TERMS:
        if frag in low:
            return name, url
    if tok == "publisher-specific":
        return (f"Publisher terms ({host_of(url)})" if url else "Publisher terms"), url
    if tok == "other-oa":
        return "Free to read (no license)", url
    return (x[:80] if x else None), url


def host_of(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ HTTP
_CONTACT = {"email": None}


def set_contact(email):
    if email:
        _CONTACT["email"] = email


def polite_email():
    return _CONTACT["email"]


def user_agent():
    # The contact email is sent ONLY as the documented polite-pool parameter of OpenAlex, Unpaywall and Crossref,
    # never in headers that reach publishers, repositories or the library proxy.
    return "paper-acquisition/3.0 (academic literature indexing)"


class HostPacer:
    """Minimum interval between requests to the same host (thread-safe)."""

    def __init__(self, default_interval=1.0):
        self.default = default_interval
        self.intervals = {}
        self.next_ok = {}
        self.lock = threading.Lock()

    def set(self, host, interval):
        self.intervals[host] = interval

    def wait(self, host):
        with self.lock:
            iv = self.intervals.get(host)
            if iv is None:
                for h, v in self.intervals.items():
                    if host.endswith("." + h):
                        iv = v
                        break
            if iv is None:
                iv = self.default
            t = time.time()
            start = max(t, self.next_ok.get(host, 0))
            self.next_ok[host] = start + iv
        if start > t:
            time.sleep(start - t)


PACER = HostPacer(1.0)
# Published or observed polite rates (seconds between requests to the host).
for _h, _iv in {"api.openalex.org": 0.15, "api.crossref.org": 0.25, "api.unpaywall.org": 0.08,
                "api.semanticscholar.org": 3.0, "www.ebi.ac.uk": 0.25, "api.openaire.eu": 0.6, "www.osti.gov": 0.5,
                "export.arxiv.org": 3.2, "arxiv.org": 3.2, "doaj.org": 0.6, "api.archives-ouvertes.fr": 0.5,
                "zenodo.org": 1.1, "eutils.ncbi.nlm.nih.gov": 0.4, "api.figshare.com": 1.2, "api.osf.io": 1.1,
                "api.plos.org": 1.0, "api.datacite.org": 0.2, "pmc-oa-opendata.s3.amazonaws.com": 0.05,
                "doi.org": 0.3, "mdpi-res.com": 2.0, "www.nature.com": 1.0, "link.springer.com": 1.0,
                "iopscience.iop.org": 1.5, "www.frontiersin.org": 1.5, "dataverse.harvard.edu": 1.0,
                "datadryad.org": 1.0, "ntrs.nasa.gov": 1.0, "api.jstage.jst.go.jp": 1.0, "cir.nii.ac.jp": 1.0,
                "archive.materialscloud.org": 1.0, "api.ies.ed.gov": 1.0, "api.core.ac.uk": 6.5,
                "api.elsevier.com": 0.4, "api.springernature.com": 1.1, "api.clarivate.com": 1.1,
                "api.lens.org": 1.1, "ieeexploreapi.ieee.org": 1.1, "api.adsabs.harvard.edu": 0.6,
                "ops.epo.org": 1.0, "image-ppubs.uspto.gov": 2.0, "archive.org": 1.0}.items():
    PACER.set(_h, _iv)

_tls = threading.local()


def session():
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _tls.s = s
    s.headers["User-Agent"] = user_agent()
    return s


# only explicitly DAILY / budget exhaustion; plain "rate limit exceeded" (per-second) stays a retryable 429
QUOTA_RX = re.compile(r"(daily|per[- ]day)[^.\n]{0,40}(limit|quota|budget|allowance)|"
                      r"(quota|budget|credits?|allowance)[^.\n]{0,20}(exceeded|exhausted|reached|used up)", re.I)


class HTTPFail(Exception):
    def __init__(self, status, msg=""):
        super().__init__(f"{status} {msg}")
        self.status = status


def http_get(url, params=None, headers=None, timeout=(15, 60), tries=3, pace=True, stream=False,
             allow_redirects=True, method="GET", json_body=None, ok=(200,), data=None):
    """HTTP with per-host pacing. Retries 5xx/429/timeouts with backoff 1s/5s/30s (429 honours Retry-After);
    any other 4xx raises HTTPFail immediately."""
    host = host_of(url)
    backoff = [1, 5, 30]
    last = None
    for attempt in range(tries):
        if pace:
            PACER.wait(host)
        try:
            r = session().request(method, url, params=params, headers=headers, timeout=timeout, stream=stream,
                                  allow_redirects=allow_redirects, json=json_body, data=data)
        except (requests.Timeout, requests.ConnectionError) as e:
            last = HTTPFail("network", repr(e)[:200])
            if attempt < tries - 1:
                time.sleep(backoff[min(attempt, 2)])
            continue
        if r.status_code in ok:
            return r
        if r.status_code == 429 and not stream and QUOTA_RX.search(r.text[:2000] or ""):
            raise HTTPFail("429-quota", r.text[:200])  # a daily quota is exhausted: retrying cannot help today
        if r.status_code == 429 or r.status_code >= 500:
            last = HTTPFail(r.status_code, r.text[:200] if not stream else "")
            ra = r.headers.get("Retry-After")
            wait = backoff[min(attempt, 2)]
            if r.status_code == 429:
                try:
                    wait = max(wait, min(float(ra), 300)) if ra else max(wait, 20 * (attempt + 1))
                except ValueError:
                    wait = max(wait, 20 * (attempt + 1))
            if attempt < tries - 1:
                time.sleep(wait + random.random())
            continue
        raise HTTPFail(r.status_code, (r.text[:300] if not stream else ""))
    raise last or HTTPFail("unknown")


def get_json(url, params=None, headers=None, tries=4, **kw):
    return http_get(url, params=params, headers=headers, tries=tries, **kw).json()


def patient(fn, *a, label="", max_wait_s=3600, **kw):
    """Retry fn on HTTP 429/5xx/network errors for up to max_wait_s (shared anonymous API pools)."""
    t0 = time.time()
    n = 0
    while True:
        try:
            return fn(*a, **kw)
        except HTTPFail as e:
            st = str(e.status)
            if not (st == "429" or st.startswith("5") or st == "network") or time.time() - t0 > max_wait_s:
                raise
            n += 1
            wait = min(300, 30 * n) + random.uniform(0, 30)
            if n % 3 == 1:
                log(f"{label}: {st} — waiting {wait:.0f}s (attempt {n})")
            time.sleep(wait)


# ------------------------------------------------------------------ topic gate (discovery precision)
DASHES = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-",
                        "\u2212": "-", "\ufe63": "-", "\uff0d": "-", "\u00ad": "", "\u00a0": " "})


def unify_dashes(text):
    """Unicode hyphens / minus signs / soft hyphens -> ASCII, so 'Single‐Atom' and 'single-atom' match the same terms."""
    return (text or "").translate(DASHES)


def _compile_terms(terms):
    out = []
    for t in terms or []:
        t = unify_dashes(str(t))
        if t.startswith("re:"):
            out.append(re.compile(t[3:], re.I))
        else:
            # a space in a term also matches a hyphen, a hyphen also matches a space or nothing ('single atom' =
            # 'single-atom' = 'Single‐Atom' after unify_dashes); re.escape no longer escapes spaces (Python 3.7+)
            parts = [re.escape(x).replace(r"\-", r"[\s\-]?") for x in t.lower().split()]
            out.append(re.compile(r"(?<![a-z0-9])" + r"[\s\-]+".join(parts), re.I))
    return out


class Gate:
    """Anchor-term gate from config['gate']: a record passes when its title/abstract contains any `any` term,
    or at least one term of EVERY group in `all_groups`. Terms are case-insensitive phrases (spaces also match
    hyphens) or regexes prefixed with 're:'. An empty gate passes everything."""

    def __init__(self, spec):
        spec = spec or {}
        self.any = _compile_terms(spec.get("any"))
        self.groups = [_compile_terms(g) for g in spec.get("all_groups") or [] if g]
        self.title_only = _compile_terms(spec.get("title_only"))
        self.empty = not (self.any or self.groups or self.title_only)

    def passes(self, title, abstract):
        if self.empty:
            return True
        title, abstract = unify_dashes(title), unify_dashes(abstract)
        text = f"{title or ''} . {abstract or ''}"
        if any(rx.search(text) for rx in self.any):
            return True
        if self.groups and all(any(rx.search(text) for rx in g) for g in self.groups):
            return True
        # records without a usable abstract: a title-only pattern can rescue them
        if len(abstract or "") < 150 and any(rx.search(title or "") for rx in self.title_only):
            return True
        return False
