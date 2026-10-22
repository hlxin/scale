"""The vector store (publications/vectors.db): the downloaded papers' passages and their vectors. A paper is read once
and a text embedded once — an update reads only new and changed papers and embeds only new text, a paper merged into
another ID keeps its vectors — a paper that leaves takes its passages along, a search finds passages by words and by
meaning and joins them to their records in the index, and every step that changes the downloads keeps the store in
step when the project has one.

    python -m pytest tests          (from the skill folder; needs PyMuPDF and numpy)
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

fitz = pytest.importorskip("fitz")
pytest.importorskip("numpy")

TEXT = {
    1: ["Copper oxide nanocubes reduce CO2 to ethylene with a Faradaic efficiency of 60 percent at -1.0 V vs RHE.\n\n"
        "The copper surface reconstructs under cathodic bias and exposes steps.",
        "Isotope labelling shows that adsorbed CO is the key intermediate on the copper sites."],
    2: ["Nickel phosphide catalyses the hydrogen evolution reaction in alkaline water at 100 mA per square centimetre."],
    3: ["Zinc oxide promotes copper in methanol synthesis from syngas at 250 degrees and 50 bar."],
}


def make_pdf(path, pages):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for t in pages:
        doc.new_page().insert_textbox(fitz.Rect(72, 72, 520, 770), t, fontsize=11)
    doc.save(str(path))
    return hashlib.sha1(path.read_bytes()).hexdigest()


def add_paper(proj, led, pid, title, doi, pages=None, **f):
    led.x("INSERT INTO papers (id, key, doi, title, authors, year, journal, doc_type, access_type) "
          "VALUES (?,?,?,?,?,?,?,?,?)", (pid, doi, doi, title, json.dumps(["A. Author"]), 2024, "J. Test",
                                         f.pop("doc_type", "article"), "OA"))
    led.add_dois(pid, [doi])
    rel = f"publications/t/papers/OA/{pid}.pdf"
    if pages:
        sha = make_pdf(proj.root / rel, pages)
        led.set(pid, downloaded=1, sha1=sha, **f)
        led.set_topic(pid, "t", in_scope=1, relevance=5, path=rel)
    else:
        if f:
            led.set(pid, **f)
        led.set_topic(pid, "t", in_scope=1, relevance=5)


@pytest.fixture()
def project(tmp_path):
    from _common import Project
    from _ledger import Ledger
    proj = Project(tmp_path / "project")
    (proj.scr / "t").mkdir(parents=True, exist_ok=True)
    (proj.scr / "t" / "config.json").write_text(json.dumps({"topic": "Test topic", "slug": "t"}))
    led = Ledger(proj)
    add_paper(proj, led, 1, "Copper nanocubes for CO2 to ethylene", "10.1/one", TEXT[1])
    add_paper(proj, led, 2, "Nickel phosphide for hydrogen evolution (preprint)", "10.26434/chemrxiv-two", TEXT[2],
              is_preprint=1, doc_type="preprint")
    add_paper(proj, led, 3, "Zinc oxide promoted copper for methanol", "10.1/three", TEXT[3])
    add_paper(proj, led, 4, "A paper not downloaded yet", "10.1/four")
    add_paper(proj, led, 5, "Correction to a copper paper", "10.1/five", ["Correction: the copper loading was 2 percent."],
              is_erratum=1)
    led.export()
    return proj


def run(proj, *args):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "vectors.py"), "--project", str(proj.root), *map(str, args)],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def store(proj):
    return sqlite3.connect(str(proj.pub / "vectors.db"))


def test_an_update_reads_each_paper_once_and_embeds_only_new_text(project):
    from _ledger import Ledger
    proj = project
    first = run(proj, "update")
    assert (first["papers_read"], first["papers"]) == (3, 3)                 # not the erratum, not the undownloaded
    n_passages = first["passages"]
    assert first["embedded"]["scale-hash-v1"] == n_passages > 3
    again = run(proj, "update")
    assert (again["papers_read"], again["papers_unchanged"], again["embedded"]["scale-hash-v1"]) == (0, 3, 0)
    led = Ledger(proj)                                   # paper 2 downloaded again, with one more page
    sha = make_pdf(proj.root / "publications/t/papers/OA/2.pdf", TEXT[2] + ["Its Tafel slope is 46 mV per decade."])
    led.set(2, sha1=sha)
    changed = run(proj, "update")
    assert changed["papers_read"] == 1 and changed["passages_already_known"] >= 1
    assert changed["embedded"]["scale-hash-v1"] == 1                          # only the new page's text
    si = proj.root / "publications/t/papers/SI/OA/1_SI1.pdf"                  # SI of paper 1 arrives (fetch_si)
    make_pdf(si, ["Table S1. Ethylene Faradaic efficiency at five potentials."])
    led.set_topic(1, "t", si_paths=[str(si.relative_to(proj.root))])
    with_si = run(proj, "update")
    assert with_si["papers_read"] == 1 and with_si["embedded"]["scale-hash-v1"] == 1
    con = store(proj)
    assert con.execute("SELECT text FROM passages WHERE id = '1/pS1/1'").fetchone()[0].startswith("Table S1.")
    assert con.execute("SELECT COUNT(*) FROM passages WHERE paper_id = 1 AND page IN ('1', '2')").fetchone()[0] >= 2


def test_a_paper_that_leaves_takes_its_passages_and_a_merged_one_keeps_its_vectors(project):
    from _ledger import Ledger
    proj = project
    run(proj, "update")
    led = Ledger(proj)
    led.set(3, downloaded=0)                                                  # no longer downloaded
    out = run(proj, "update")
    assert out["papers_removed"] == 1 and out["vectors_dropped"] >= 1
    con = store(proj)
    assert con.execute("SELECT COUNT(*) FROM passages WHERE paper_id = 3").fetchone()[0] == 0
    con.close()
    # the journal version of paper 2 is indexed: dedup keeps it and moves the downloaded preprint's PDF to its ID
    add_paper(proj, led, 8, "Nickel phosphide for hydrogen evolution", "10.1/eight")
    led.export()
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "dedup.py"), "--project", str(proj.root), "--merge", "2:8"],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-1500:]
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert res["merged"] == [{"kept": 8, "merged": 2}]
    vec = res["vector_store"]                                                 # the merge kept the store in step
    assert vec["papers_removed"] == 1 and vec["papers_read"] == 1 and vec["embedded"]["scale-hash-v1"] == 0
    con = store(proj)
    assert {r[0] for r in con.execute("SELECT DISTINCT paper_id FROM passages")} == {1, 8}


def test_search_finds_passages_and_joins_their_records(project):
    proj = project
    run(proj, "update")
    hit = run(proj, "search", "ethylene from CO2 on copper", "--k", 3)["hits"][0]
    assert hit["paper_id"] == 1 and hit["title"] == "Copper nanocubes for CO2 to ethylene" and hit["doi"] == "10.1/one"
    assert hit["passage"].startswith("1/p1/") and "ethylene" in hit["text"]
    kw = run(proj, "search", "Tafel nickel phosphide", "--mode", "keyword")["hits"]
    assert kw and kw[0]["paper_id"] == 2
    vec = run(proj, "search", "methanol synthesis over zinc oxide and copper", "--mode", "vector")["hits"]
    assert vec[0]["paper_id"] == 3
    only = run(proj, "search", "copper", "--ids", "3")["hits"]
    assert {h["paper_id"] for h in only} == {3}
    st = run(proj, "status")
    assert (st["papers"], st["downloaded_papers"], st["papers_to_read"]) == (3, 3, 0)
    assert st["texts_without_vector"] == {"scale-hash-v1": 0}


def test_every_download_step_keeps_the_store_in_step(project):
    import _vectors as V
    from _ledger import Ledger
    proj = project
    led = Ledger(proj)
    assert V.after_step(proj, led) is None and not V.store_path(proj).exists()   # no store: nothing is made
    run(proj, "init")
    assert V.store_path(proj).exists()
    rel = "publications/t/papers/OA/4.pdf"                    # download_open saves paper 4 ...
    led.set(4, downloaded=1, sha1=make_pdf(proj.root / rel, ["Silver nanowires reduce CO2 to CO in a flow cell."]))
    led.set_topic(4, "t", path=rel)
    led.export()
    res = V.after_step(proj, led)                             # ... and ends with this
    assert res["papers_read"] == 4 and res["papers"] == 4
    hooked = [f for f in ("download_open.py", "download_paywalled.py", "fetch_si.py", "dedup.py", "merge_db.py")
              if "after_step(proj, led)" in (SCRIPTS / f).read_text()]
    assert len(hooked) == 5


def test_a_second_embedder_is_kept_apart_and_can_be_dropped(project, monkeypatch):
    import numpy as np
    import _vectors as V
    from _ledger import Ledger
    proj = project

    class Stub:                                               # stands in for a local neural model
        id, dim = "sentence-transformers:stub", 8

        def encode(self, texts, query=False):
            return np.array([[len(t) % 7 + 1, t.count("o") + 1, *range(6)] for t in texts], dtype=np.float64)

    real = V.get_embedder
    monkeypatch.setattr(V, "get_embedder", lambda name, download=False: Stub() if name == Stub.id else real(name))
    led = Ledger(proj)
    V.update(proj, led)
    both = V.update(proj, led, embedders=[Stub.id])
    assert both["embedded"][Stub.id] == both["passages"] and both["papers_read"] == 0   # vectors, no re-reading
    con = V.open_store(proj)
    assert V.embedders_of(con) == ["scale-hash-v1", Stub.id]
    con.close()
    assert V.search(proj, "copper", embedder=Stub.id, mode="vector")["embedder"] == Stub.id
    assert V.search(proj, "copper")["embedder"] == Stub.id          # a neural embedder with every passage: the default
    again = V.update(proj, led)
    assert again["embedded"] == {"scale-hash-v1": 0, Stub.id: 0}
    out = run(proj, "drop", "--embedder", Stub.id)
    assert out["vectors_removed"] == both["passages"] and out["embedders"] == ["scale-hash-v1"]


@pytest.mark.skipif(not os.environ.get("SCALE_PYTHONPATH"), reason="set SCALE_PYTHONPATH to compare with SCALE's code")
def test_passages_and_hash_vectors_are_scales_own():
    import numpy as np
    import _vectors as V
    sys.path.insert(0, os.environ["SCALE_PYTHONPATH"])
    from scale import passages as S
    texts = ["Cu/ZnO for CO2 hydrogenation at 250 °C.", "Kupfer und Zinkoxyd: Methylalkohol.", "", "word " * 500]
    assert np.array_equal(V.quantize(V.HashEmbedder().encode(texts)), S.quantize(S.HashEmbedder().encode(texts)))
    page = "One paragraph.\n\nAnother " + "sentence here. " * 90 + "\n\nLast."
    assert V.split_page(page) == S.split_page(page)


MODEL = "BAAI/bge-small-en-v1.5"
CACHED = (Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub" /
          f"models--{MODEL.replace('/', '--')}").is_dir()


@pytest.mark.skipif(not CACHED, reason=f"the local model {MODEL} is not on this machine (vectors.py init fetches it)")
def test_a_local_model_embeds_offline_and_finds_by_meaning(project):
    pytest.importorskip("sentence_transformers")
    proj = project
    run(proj, "update")
    name = f"sentence-transformers:{MODEL}"
    out = run(proj, "update", "--embedder", name)                     # offline: from the local cache only
    assert out["papers_read"] == 0 and out["embedded"][name] == out["passages"]
    hit = run(proj, "search", "electrochemical conversion of carbon dioxide into C2 products", "--mode", "vector",
              "--embedder", name)["hits"][0]
    assert hit["paper_id"] == 1 and hit["title"]
    hit = run(proj, "search", "making methanol from synthesis gas", "--mode", "vector", "--embedder", name)["hits"][0]
    assert hit["paper_id"] == 3
    assert run(proj, "status")["texts_without_vector"] == {"scale-hash-v1": 0, name: 0}
    assert run(proj, "update")["embedded"] == {"scale-hash-v1": 0, name: 0}


REFS = ("[1] A. B. Smith, C. D. Jones, J. Am. Chem. Soc. 2019, 141, 1234-1240. [2] E. F. Brown et al., Copper catalysts "
        "for CO2 electroreduction to ethylene, Nat. Catal. 2020, 3, 98-106. [3] G. H. Lee, I. J. Kim, Ethylene from CO2 "
        "on copper, ACS Catal. 2021, 11, 4456-4463. [4] K. L. Wang et al., Angew. Chem. Int. Ed. 2018, 57, 7724-7728.")


def test_reference_lists_are_left_out_of_a_search_unless_asked(project):
    import _vectors as V
    from _ledger import Ledger
    proj = project
    led = Ledger(proj)
    add_paper(proj, led, 9, "A review whose last page cites copper papers", "10.1/nine",
              ["Electrocatalysts are reviewed here in general terms for many reactions.", REFS])
    led.export()
    assert V.is_reference_list(REFS) and not any(V.is_reference_list(t) for pages in TEXT.values() for t in pages)
    run(proj, "update")
    plain = run(proj, "search", "copper catalysts for CO2 electroreduction to ethylene", "--k", 10)
    assert plain["reference_passages_left_out"] >= 1 and "9/p2/1" not in {h["passage"] for h in plain["hits"]}
    full = run(proj, "search", "copper catalysts for CO2 electroreduction to ethylene", "--k", 10, "--with-references")
    assert "9/p2/1" in {h["passage"] for h in full["hits"]} and full["reference_passages_left_out"] is None


def test_a_store_of_the_first_layout_is_reordered_once(project):
    import _vectors as V
    proj = project
    first = run(proj, "update")
    con = sqlite3.connect(str(V.store_path(proj)))                  # the vectors table as the first version kept it
    con.executescript("CREATE TABLE old (text_sha1 TEXT NOT NULL, embedder TEXT NOT NULL, vec BLOB NOT NULL, "
                      "PRIMARY KEY (text_sha1, embedder)) WITHOUT ROWID; INSERT INTO old SELECT * FROM vectors; "
                      "DROP TABLE vectors; ALTER TABLE old RENAME TO vectors;")
    con.close()
    hit = run(proj, "search", "methanol synthesis over zinc oxide and copper", "--mode", "vector")["hits"][0]
    assert hit["paper_id"] == 3
    con = sqlite3.connect(str(V.store_path(proj)))
    assert {r[1]: r[5] for r in con.execute("PRAGMA table_info(vectors)")}["embedder"] == 1
    assert con.execute("SELECT COUNT(*) FROM vectors").fetchone()[0] == first["vectors"]["scale-hash-v1"]
    con.close()
    assert run(proj, "update")["embedded"] == {"scale-hash-v1": 0}


def test_a_paper_is_loaded_by_id_or_doi_and_papers_are_ranked_for_a_question(project, tmp_path):
    proj = project
    run(proj, "update")
    one = run(proj, "get", "10.1/one")                                      # by DOI, through the index
    assert one["paper_id"] == 1 and one["title"] == "Copper nanocubes for CO2 to ethylene" and one["pages"] == 2
    assert [t["page"] for t in one["text"]] == sorted((t["page"] for t in one["text"]), key=int)
    assert "Isotope labelling" in " ".join(t["text"] for t in one["text"])
    assert run(proj, "get", "1")["text"] == one["text"]
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "vectors.py"), "--project", str(proj.root), "get", "1",
                        "--text"], capture_output=True, text=True, timeout=600)
    assert "[page 1]" in r.stdout and "[page 2]" in r.stdout and "10.1/one" in r.stdout
    ids = tmp_path / "ids.txt"
    ranked = run(proj, "search", "copper catalysts", "--by-paper", "--k", 2, "--ids-out", ids)
    got = [p["paper_id"] for p in ranked["papers"]]
    assert got[0] == 1 and len(got) == 2 and ids.read_text().split() == [str(i) for i in got]
    assert all(1 <= len(p["passages"]) <= 3 and p["title"] for p in ranked["papers"])
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "vectors.py"), "--project", str(proj.root), "get", "4"],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode != 0 and "not in the vector store" in r.stderr and "Traceback" not in r.stderr
