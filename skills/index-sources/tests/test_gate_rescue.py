"""Gate rescue rules: a source of the topic that never writes the anchor word ("cataly") gets in by a title term (a
catalytic reaction) or a journal term (a catalysis journal), vetoed journals stay out, and keyword screening keeps such
a source in scope with the rescue as its note.

    python -m pytest tests          (from the skill folder; standard library and pytest)
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

SPEC = {"any": ["re:cataly"], "english_only": True,
        "title_any": [r"re:\b(?:heck|sonogashira)\b|hydroformylation",
                      r"re:^(?!.*(?:\bhydrides?\b|storage|alloy)).*hydrogenation"],
        "journal_any": [r"re:catalysis|\bcatalysts\b"], "journal_not": [r"re:focus on catalysts|kinetics and catalysis"]}


def test_title_and_journal_rescue_with_vetoes():
    from _common import Gate
    g = Gate(SPEC)
    assert g.passes("Synthesis of fluorescent rhodamine dyes using an extension of the Heck reaction", "")
    assert g.passes("Selective hydrogenation of maleic anhydride to gamma-butyrolactone", "")
    assert not g.passes("Dehydrogenation kinetics of nickel-doped magnesium hydride for hydrogen storage", "")
    assert g.passes("Propane oxidation over platinum supported on zirconia", "", "Journal of Catalysis")
    assert not g.passes("Sasol opens a research centre", "", "Focus on Catalysts")
    assert not g.passes("NEWDBRIEF", "", "Applied Catalysis A: General")                # a news brief, not an article
    assert not g.passes("Interpretation paradoxes in unimolecular heterolysis kinetics", "", "Kinetics and Catalysis")
    assert not g.passes("Total phenolic content by the Folin-Ciocalteu assay", "", "Food Chemistry")
    assert not g.passes("Síntesis de catalizadores para la reacción de Heck en agua", "")     # English only first
    assert g.rescue("Hydroformylation of oct-1-ene in ionic liquid crystals") == "title: Hydroformylation"
    assert Gate({"any": ["re:cataly"]}).passes("Heck reaction in water", "") is False    # no rescue rule, no rescue


def test_keyword_screening_keeps_rescued_sources_in_scope():
    from _common import Gate
    from screen import KeywordScorer
    kw = {"include_groups": [["re:cataly"]], "exclude": ["catalyst for change"]}
    sc = KeywordScorer(kw, Gate(SPEC))
    s, note = sc.score("Heck arylations of Baylis-Hillman adducts", "")
    assert s == 4 and note.startswith("rescued by the topic gate (title: Heck")
    s, note = sc.score("Coking, aging and regeneration of zeolites", "", "Applied Catalysis A: General")
    assert s == 4 and "journal: Applied Catalysis A: General" in note
    assert sc.score("Zeolite catalysts for cracking", "")[0] == 5                   # the include word still rules
    assert sc.score("Folin-Ciocalteu assay of wine phenolics", "")[0] == 0
    assert KeywordScorer(kw).score("Heck arylations of Baylis-Hillman adducts", "")[0] == 0     # without the gate
