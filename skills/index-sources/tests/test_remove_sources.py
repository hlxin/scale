"""Taking sources out of the index (remove_sources.py): records in another language leave, logged in full and with
their files moved (never deleted), and leave index.db too; English ones, a kept topic's and a downloaded source whose
PDF reads as English stay; the gate's english_only turns such records away at the door.

    python -m pytest tests          (from the skill folder; standard library, PyMuPDF and pytest)
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

fitz = pytest.importorskip("fitz")
from test_same_source import make_pdf  # noqa: E402

ES = "Síntesis de catalizadores de níquel para la hidrogenación de CO2"


@pytest.fixture()
def project(tmp_path):
    from _common import Project
    from _ledger import Ledger
    proj = Project(tmp_path / "project")
    led = Ledger(proj)
    sources = {1: ("10.1000/en", "Nickel catalysts for CO2 hydrogenation to methane", "t"),
               2: ("10.1000/es", ES, "t"),
               3: ("10.1000/es-kept", ES + " (corpus)", "kept"),
               4: ("10.1000/es-pdf-en", ES + " (traducción)", "t")}
    for pid, (doi, title, topic) in sources.items():
        led.x("INSERT INTO sources (id, key, doi, title, authors, year, doc_type, access_type) "
              "VALUES (?,?,?,?,'[]',2024,'article','OA')", (pid, doi, doi, title))
        led.set_topic(pid, topic, in_scope=1)
        led.add_dois(pid, [doi])
    for pid, text in ((2, ES + "\nResumen: se estudió la síntesis de los catalizadores para la reacción"),
                      (4, "Nickel catalysts for CO2 hydrogenation: the translated paper in English, with the "
                          "results of the tests and the discussion of the mechanism")):
        rel = f"sources/t/files/OA/{pid}.pdf"
        (proj.root / rel).parent.mkdir(parents=True, exist_ok=True)
        make_pdf(proj.root / rel, text)
        led.set(pid, downloaded=1)
        led.set_topic(pid, "t", path=rel)
    led.export()
    return proj


def run(proj, *args):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "remove_sources.py"), "--project", str(proj.root), *args],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_records_in_another_language_leave_logged_and_their_files_kept_aside(project):
    from _ledger import Ledger
    assert run(project, "--non-english", "--keep-topic", "kept", "--dry-run")["would_remove"] == 1
    out = run(project, "--non-english", "--keep-topic", "kept")
    assert out["removed"] == 1 and out["files_moved"] == 1
    led = Ledger(project)
    assert led.get(2) is None and led.get(1) and led.get(3) and led.get(4)     # 3: kept topic; 4: its PDF is English
    assert not led.q("SELECT 1 FROM dois WHERE doi='10.1000/es'")
    assert (project.scr / "removed" / "non-english" / "2__2.pdf").is_file()
    assert not (project.root / "sources/t/files/OA/2.pdf").exists()
    logged = [json.loads(l) for l in (project.logs / "removed_log.jsonl").read_text().splitlines()]
    assert logged[0]["id"] == 2 and logged[0]["row"]["title"] == ES and logged[0]["reason"].startswith("not English")
    con = sqlite3.connect(str(project.db))                                    # the published database follows
    assert sorted(r[0] for r in con.execute("SELECT id FROM sources")) == [1, 3, 4]
    con.close()


def test_sources_listed_by_id_leave_with_the_reason_given(project, tmp_path):
    from _ledger import Ledger
    ids = tmp_path / "ids.txt"
    ids.write_text("1\n3\n")
    out = run(project, "--ids", str(ids), "--reason", "Out of scope: a review of reviews", "--keep-topic", "kept")
    assert out["removed"] == 1 and out["spared"] == {"kept_topic": 1}
    assert Ledger(project).get(1) is None and Ledger(project).get(3)
    logged = [json.loads(l) for l in (project.logs / "removed_log.jsonl").read_text().splitlines()]
    assert logged[-1]["reason"] == "Out of scope: a review of reviews"


def test_what_counts_as_another_language():
    from _lang import non_english
    english = ["Catalytic Synthesis of С2-С4-Alkenes from Dimethyl Ether",                  # Cyrillic look-alikes
               "Liquid-phase Epoxidation of Propylene with Нуdrogen Peroxide Using Ti-MWW Catalyst",
               "Effect of La and Y promoters on Ni/γ-Al2O3 catalysts for CO2 methanation",   # elements, Greek
               "A novel de novo HDAC8 missense mutation causing Cornelia de Lange syndrome"]  # name particles
    assert not any(non_english(t) for t in english)
    assert non_english("A Pulse Nuclear Magnetic Resonance Study of Hydrogen on a Platinum Catalyst",
                       "La methode de resonance magnetique est utilisee pour mesurer le temps de relaxation de "
                       "l'hydrogene adsorbe sur un catalyseur de platine supporte par du carbone") is None
    for t in ("固定化金属錯体の有機合成への応用", "Кинетика фазовых превращений при селективном растворении",
              "Synthèse et caractérisation des gels à base de dioxyde de titane par voie sol-gel", ES):
        assert non_english(t)
    # elisions, a capitalised first word, an all-capitals title; bilingual titles with the English one first stay
    for t in ("Diagnostic d'un plasma par interferometrie a cavite couplee a l'aide d'un laser a CO2",
              "Le craquage catalytique, unité clé d'une raffinerie",
              "Ossidazione dell'alcol benzilico mediata da catalizzatori metallici supportati",
              "TECHNOLOGIES DE RECOMBUSTION AVANCEE DES OXYDES D'AZOTE : ETUDES EXPERIMENTALE ET CINETIQUE",
              "Ein systemtheoretisches Modell zur Biogenese / A System Theoretic Model of Biogenesis"):
        assert non_english(t)
    for t in ("Agro-industrial residues in biotechnological production of xylitol/ Resíduos agroindustriais",
              "Discovery and Optimization of Catalysts and Solvents for Absorption Using High Throughput "
              "Experimentation Découverte et optimisation de catalyseurs et de solvants pour l'absorption",
              "The structure of the tropism : a study of Les fruits d'or of Nathalie Sarraute",
              "Applications of L'Hôpital's rule to reaction kinetics", "SYNTHESIS OF LA AND CE OXIDES FOR CO OXIDATION"):
        assert non_english(t) is None
    # a translated abstract decides only when the title itself has a foreign word
    fr = ("Nous présentons une nouvelle méthode de synthèse des catalyseurs dans le cadre de la chimie verte. Les "
          "résultats montrent que la sélectivité est élevée et que les catalyseurs sont stables pour la réaction.")
    assert non_english("Cobalt-catalyzed Hydroelementation Reactions", fr) is None
    assert non_english("Pinces moléculaires commutables luminescentes et magnétiques", fr)


def test_the_english_only_gate_turns_other_languages_away():
    from _common import Gate
    terms = ["re:cataly", "re:cat[aá]li[sz]"]                             # the catalysis catalog's own gate
    g = Gate({"any": terms, "english_only": True})
    assert g.passes("Photocatalytic CO2 reduction on TiO2", "") and not g.passes(ES, "")
    assert Gate({"any": terms}).passes(ES, "")                          # without the option nothing changes
