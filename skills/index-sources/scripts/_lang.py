"""Is a record in English? Judged from its title and abstract, built for precision: a record counts as non-English
only on clear evidence, never on chemistry's Greek letters (γ-Al2O3, Cuδ+), formulas, names or loanwords.

Evidence: a title a sixth CJK (kana, Hangul, Chinese characters), with a word or a quarter of its letters in another
script (Cyrillic, Arabic, Hebrew, Devanagari, Thai: Cyrillic look-alikes typed for Latin letters do not count), or a
third Greek; an abstract mostly (60%) in a non-Latin script; or, for Latin-script languages, the function
words no title in that language does without ("de la", "und", "für", "dla", "dan yang" ...), counted in lower case
and with two letters or more (element symbols La, Y, W, Os, In, Co and spaced-out letters never count), and only when
they outnumber the English ones. French, Italian and Catalan elisions count as such words ("d'un", "l'aide",
"dell'alcol"; never a name: d'Alembert, L'Hôpital). A title with two unambiguous English words ("of", "the", "and" ...)
is English or bilingual (Oil Gas Sci. Technol. prints each English title with its French translation). A foreign
abstract under a title with English words is not evidence: databases store translated abstracts (a French one for an
English J. Phys. Soc. Jpn. paper).
"""
import re

CJK = re.compile("[ᄀ-ᇿ぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]")
OTHER = re.compile("[Ѐ-ԯ֐-׿؀-ۿݐ-ݿऀ-ॿ฀-๿]")
NON_LATIN = re.compile(CJK.pattern[:-1] + OTHER.pattern[1:])
OTHER_RUN = re.compile(OTHER.pattern + "{3,}")
# Cyrillic letters that look Latin, typed by mistake in English titles ("Нуdrogen", "С2-С4", "МСМ-41", "АТРase")
LOOKALIKE = str.maketrans("АВЕКМНОРСТУХ"
                          "аеорсухіјѕІЈЅ",
                          "ABEKMHOPCTYXaeopcyxijsIJS")
GREEK = re.compile("[Ͱ-Ͽἀ-῿]")
UMLAUT = re.compile("[äöüßÄÖÜ]")

FUNCTION_WORDS = {
    "es": {"el", "los", "las", "del", "y", "para", "con", "una", "sobre", "mediante", "desde", "sus", "entre",
           "como", "por", "que", "de", "la", "en", "un", "su", "lo"},
    "pt": {"os", "da", "das", "do", "dos", "em", "para", "com", "uma", "um", "sobre", "pela", "pelo", "na", "nas",
           "nos", "ao", "aos", "entre", "como", "por", "que", "de", "e", "o"},
    "fr": {"le", "les", "des", "du", "et", "pour", "sur", "dans", "une", "par", "avec", "au", "aux", "entre", "est",
           "sont", "ou", "leur", "cette", "de", "la", "un", "en", "à"},
    "de": {"der", "die", "das", "und", "für", "mit", "von", "zur", "zum", "im", "ein", "eine", "einer", "eines",
           "auf", "bei", "über", "aus", "durch", "dem", "den", "des", "zu", "als", "nach", "unter", "wird",
           "zwischen", "sowie", "beim", "vom"},
    "it": {"il", "gli", "della", "delle", "degli", "dei", "per", "con", "una", "sulla", "nel", "nella", "tra",
           "di", "e", "la", "un", "del", "sul", "da", "dello", "alla", "dal", "dalla", "nei", "nelle", "sui"},
    "nl": {"het", "een", "van", "voor", "met", "bij", "door", "naar", "op", "en", "de"},
    "pl": {"oraz", "dla", "przez", "się", "jest", "na", "w", "z", "do", "od", "po", "ze", "we", "i", "jako"},
    "cs": {"pro", "při", "se", "ve", "na", "z", "ze", "do", "a", "v", "jako"},
    "tr": {"ve", "bir", "ile", "için", "bu", "olarak", "üzerine", "üzerinde"},
    "id": {"dan", "yang", "pada", "dengan", "untuk", "terhadap", "dari", "sebagai", "menggunakan", "pengaruh",
           "dalam", "oleh"},
    "ro": {"și", "în", "pentru", "cu", "din", "pe", "ale", "de", "la"},
    "sv": {"och", "av", "på", "för", "med", "det", "som", "är", "en"},
}
ENGLISH = {"the", "of", "and", "in", "on", "for", "with", "to", "by", "from", "at", "an", "as", "its", "into",
           "over", "under", "between", "through", "toward", "towards", "during", "after", "without", "within",
           "via", "is", "are", "was", "were", "be", "been", "this", "that", "these", "which", "or", "not", "than",
           "their", "using", "based", "new", "study", "effect", "effects", "high", "low", "a", "it", "we", "our",
           "can", "has", "have", "while", "both", "such", "also", "here", "show", "shows", "do", "per", "par", "met"}
# English words no French, Italian, Spanish or Portuguese title uses ("a", "in", "per", "do", "as" ... are theirs too)
STRONG_ENGLISH = ENGLISH - {"a", "in", "per", "par", "met", "do", "as", "an", "be", "on", "via", "it", "new"}
# an elided article or preposition before a lower-case word: French, Italian, Catalan (d'un, l'aide, dell'alcol)
ELISION = re.compile(r"^(?:[dlDL]|qu|j|n|s|c|dell|nell|sull|dall|all|degl|un)['’][a-zà-ÿœ]")
LATIN_PHRASE = {"novo", "facto", "jure", "situ", "vivo", "vitro", "silico", "operando"}
NAME_PARTICLES = {"de", "da", "do", "dos", "das", "du", "van", "von", "der", "den", "la", "le", "di", "del", "della",
                  "des", "el", "lo", "ter", "ten"}
_TOKEN = re.compile(r"^[^\w]+|[^\w]+$")


def _tokens(text):
    """Whitespace words with their outer punctuation removed; hyphenated words (de-NOx) stay whole."""
    return [w for w in (_TOKEN.sub("", t) for t in (text or "").split()) if w]


def _latin_votes(text):
    """(best foreign language, its function-word hits, English hits): foreign words count in lower case and with two
    letters or more (no element symbol, no spaced-out letters), English ones in any case (Title Case included)."""
    words = _tokens(text)
    en = sum(1 for w in words if w.lower() in ENGLISH)
    if words and words[0][:1].isupper() and words[0][1:].islower():
        words[0] = words[0].lower()                         # a title's first word: "Le craquage", "Il ruolo"
    # a name particle before a name or a Latin phrase is English too (Cornelia de Lange, van der Waals, de novo); other
    # words count before capitals: German writes every noun with one ("des CO2-Austausches zwischen ... und Plasma")
    low = [w for i, w in enumerate(words) if w.islower() and len(w) >= 2 and w not in ENGLISH
           and not (w in NAME_PARTICLES and i + 1 < len(words) and words[i + 1][:1].isupper())
           and not (i + 1 < len(words) and words[i + 1] in LATIN_PHRASE)]
    elided = sum(1 for w in words if ELISION.match(w))
    best, hits = None, 0
    for lang, fw in FUNCTION_WORDS.items():
        n = sum(1 for w in low if w in fw) + (elided if lang in ("fr", "it") else 0)
        if n > hits:
            best, hits = lang, n
    return best, hits, en


def non_english(title, abstract=None):
    """None when the record reads as English (or there is too little to tell), else a short reason."""
    title, abstract = (title or "").translate(LOOKALIKE), (abstract or "").translate(LOOKALIKE)
    letters = [c for c in title if c.isalpha()]
    # CJK is dense: a sixth of the letters is a title in that language (one term in an English title is not); other
    # scripts: a word of three letters or a quarter of the title
    other = sum(1 for c in letters if OTHER.match(c)) / len(letters) if letters else 0
    if letters and (sum(1 for c in letters if CJK.match(c)) / len(letters) >= 0.15 or other >= 0.25
                    or (other >= 0.1 and OTHER_RUN.search(title))):   # not one foreign name in an English title
        return "non-Latin script"
    if letters and sum(1 for c in letters if GREEK.match(c)) / len(letters) >= 0.3:
        return "Greek"
    letters = [c for c in abstract if c.isalpha()]
    if len(letters) >= 100 and sum(1 for c in letters if NON_LATIN.match(c)) / len(letters) >= 0.6:
        return "non-Latin script (abstract)"
    caps = [c for c in title if c.isalpha()]
    allcaps = len(caps) >= 12 and sum(1 for c in caps if c.isupper()) / len(caps) >= 0.8
    if allcaps:                                 # an all-capitals title ("ETUDE DE LA ...") votes in lower case, and one
        title = title.lower()                   # plain English word keeps it (patents: "CATALYST FOR ... KATALYSATOR")
    lang, hits, en = _latin_votes(title)
    # words English shares with the Romance languages ("a", "in", "per") count half; two plain English words: bilingual
    strong = sum(1 for w in _tokens(title) if w.lower() in STRONG_ENGLISH)
    english_too = strong >= (1 if allcaps else 2) or _english_first(title)
    if len(_tokens(title)) >= 4 and hits >= 2 and hits > strong + (en - strong) / 2 and not english_too:
        return f"title in {lang}"
    words = _tokens(title)      # German nouns carry umlauts; one Mössbauer or Hückel in an English title is not that
    if en == 0 and sum(1 for w in words if UMLAUT.search(w)) >= 2 and any(w in FUNCTION_WORDS["de"] for w in words):
        return "title in de"
    # a title without one English word but with a foreign one: its abstract decides (an English title with no function
    # word, "Cobalt-catalyzed Hydroelementation Reactions", may carry a translated abstract)
    if en == 0 and hits >= 1 and len(abstract) >= 150:
        lang, hits, en_abs = _latin_votes(abstract)
        if hits >= 8 and hits > 3 * en_abs:
            return f"abstract in {lang}"
    return None


def _english_first(title):
    """An English title followed by its translation ("... of xylitol / Resíduos agroindustriais ...", "... efficiency.
    (Méthodes d'optimisation ...)"): the part before the first " / ", " = ", " [" or " (" reads English."""
    head = re.split(r"\s*/\s+|\s+=\s+|\s+\[|\s+\(", title, maxsplit=1)
    if len(head) < 2:
        return False
    _, hits, en = _latin_votes(head[0])     # "do", "a" count as English: two of them only in a title without accents
    return hits == 0 and (any(w.lower() in STRONG_ENGLISH for w in _tokens(head[0])) or en >= 2 and head[0].isascii())
