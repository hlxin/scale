"""A one-source graph contributed to catal-commons (scale graph contribute; tools/commons.py): refused when its source
is there already, its ids moved into the commons namespace, its quotes capped under the commons rights, and the parts
it writes build into a graph that validates."""

import json
import shutil

import pytest

from conftest import REPO
from scale import commons, curate, graphparts, pgraph, rights
from scale.cli import main
from scale.util import ScaleError, load_doc, load_yaml, write_canonical

TEXT = "[page 1]\nThe copper catalyst gave methanol at 250 °C.\n\n[page 2]\nWe conclude that copper is the active phase.\n"
LICENSED = {"message": {"title": ["Copper catalysts for methanol synthesis"], "issued": {"date-parts": [[2026]]},
                        "type": "journal-article", "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}]}}


def one_source(tmp_path, name, doi=None, licensed=False, title=None):
    (tmp_path / f"{name}.txt").write_text(TEXT, encoding="utf-8")
    meta = json.loads(json.dumps(LICENSED))
    if title:
        meta["message"]["title"] = [title]
    if not licensed:
        meta["message"]["license"] = []
    get = lambda url, h: json.dumps(meta).encode()
    version = load_doc(REPO / "graphs" / "catal-commons" / "parts" / "header.json")["graph"]["schema_version"]
    res = curate.start(tmp_path / name, text=tmp_path / f"{name}.txt", doi=doi, repo=REPO, get=get, version=version)
    w = tmp_path / name
    g = w / res["graph"]
    doc = load_doc(g)
    sid = res["source_id"]
    prefix = sid.replace("/source/", "/")
    ev = lambda q: [{"source": sid, "locator": "p. 2", "kind": "text", "quote": q}]
    doc["nodes"] += [
        {"id": f"{prefix}/claim/1", "label": "Claim",
         "props": {"name": "copper active", "statement": "Copper is the active phase.", "claim_kind": "finding",
                   "claim_status": "proposed", "origin": "reported", "evidence": ev("copper is the active phase")}},
        {"id": "ex:pub/species/copper", "label": "ChemicalSpecies",
         "props": {"name": "copper", "formula": "Cu", "origin": "reported", "evidence": ev("copper is the active phase")}},
    ]
    write_canonical(g, doc)
    assert curate.check(w, REPO, derive_links=True)["ok"]
    return w, g, sid


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "catal-commons"
    shutil.copytree(REPO / "graphs" / "catal-commons", d)
    return d


def test_a_source_joins_the_commons_in_its_namespace_with_no_quote_of_a_source_in_copyright(tmp_path, folder):
    w, g, sid = one_source(tmp_path, "a", doi="10.9999/a.1")
    entry = rights.load_rights(w / "rights.yaml")[sid]
    res = commons.contribute(load_doc(g), folder, entry, REPO)
    slug = "10.9999-a.1"
    assert res["source"] == f"scale:commons/source/{slug}" and res["class"] == "in_copyright"
    assert set(res["files"]) == {f"parts/sources/{slug}.json", "parts/shared.json", "rights.yaml"}
    assert res["shared_added"] == ["scale:commons/species/copper"] and res["quotes"]["kept"] == 0
    commons.write(res, folder)
    built = graphparts.build_folder(folder)
    ids = {n["id"] for n in built["nodes"]}
    assert f"scale:commons/{slug}/claim/1" in ids and not any(i.startswith("ex:pub") for i in ids)
    assert "ex:pub/project/" + slug not in json.dumps(built)                # the one-source steward and project stay out
    quotes = [ev for _, _, _, ev in rights.items(built)]
    assert quotes and all("quote" not in ev and rights.withheld(ev) for ev in quotes)    # sha256 and length kept
    spec = pgraph.load_spec(pgraph.spec_for(REPO, built["graph"]["schema_version"], None, built))
    assert not pgraph.validate(built, spec).errors
    text = (folder / "rights.yaml").read_text(encoding="utf-8")
    assert text.startswith("# Rights of the sources of catal-commons") and "quote_chars: 0" in text
    assert load_yaml(folder / "rights.yaml")["sources"][res["source"]]["class"] == "in_copyright"
    assert rights.report(built, rights.load_rights(folder / "rights.yaml"))["ok"]


def test_a_source_already_in_the_commons_is_found_by_doi_or_by_title_and_year(tmp_path, folder):
    w, g, sid = one_source(tmp_path, "a", doi="10.9999/a.1", licensed=True)
    commons.write(commons.contribute(load_doc(g), folder, rights.load_rights(w / "rights.yaml")[sid], REPO), folder)
    again = commons.contribute(load_doc(g), folder, {}, REPO)
    assert again["files"] == {} and again["already"][0]["by"] == ["doi", "title_year"]
    w2, g2, sid2 = one_source(tmp_path, "b")                                  # the same paper as a PDF, no DOI
    doc2 = load_doc(g2)
    src = next(n for n in doc2["nodes"] if n["id"] == sid2)
    src["props"].update(title="Copper Catalysts for Methanol Synthesis.", year=2026)
    assert commons.find(doc2, graphparts.read_parts(folder))[0]["by"] == ["title_year"]


def test_an_open_source_keeps_its_quotes_and_a_shared_record_gains_the_new_evidence(tmp_path, folder):
    w, g, sid = one_source(tmp_path, "a", doi="10.9999/a.1", licensed=True)
    res = commons.contribute(load_doc(g), folder, rights.load_rights(w / "rights.yaml")[sid], REPO)
    assert res["class"] == "open" and res["quotes"]["withheld"] == 0
    commons.write(res, folder)
    w2, g2, sid2 = one_source(tmp_path, "b", doi="10.9999/b.2", licensed=True, title="Another copper paper on methanol")
    res2 = commons.contribute(load_doc(g2), folder, rights.load_rights(w2 / "rights.yaml")[sid2], REPO)
    assert res2["shared_added"] == [] and res2["shared_with_new_evidence"] == ["scale:commons/species/copper"]
    commons.write(res2, folder)
    cu = next(n for n in graphparts.read_parts(folder)["shared"]["nodes"] if n["id"] == "scale:commons/species/copper")
    assert sorted(e["source"] for e in cu["props"]["evidence"]) == ["scale:commons/source/10.9999-a.1",
                                                                     "scale:commons/source/10.9999-b.2"]


def test_a_graph_of_several_sources_or_without_rights_is_refused(tmp_path, folder):
    w, g, sid = one_source(tmp_path, "a", doi="10.9999/a.1")
    with pytest.raises(ScaleError, match="rights entry"):
        commons.contribute(load_doc(g), folder, {}, REPO)
    with pytest.raises(ScaleError, match="one Source record"):
        commons.contribute(load_doc(REPO / "examples" / "methanol-synthesis-public"), folder, {}, REPO)


def test_a_graph_pinning_a_newer_schema_than_the_commons_is_refused(tmp_path, folder):
    w, g, sid = one_source(tmp_path, "a", doi="10.9999/a.1")
    doc = load_doc(g)
    doc["graph"]["schema_version"] = "99.0.0"
    with pytest.raises(ScaleError, match="the folder moves to 99.0.0 first"):
        commons.contribute(doc, folder, rights.load_rights(w / "rights.yaml")[sid], REPO)


def test_the_command_reports_writes_and_refuses_a_second_time(tmp_path, folder, capsys):
    w, g, sid = one_source(tmp_path, "a", doi="10.9999/a.1")
    assert main(["graph", "contribute", str(g), "--to", str(folder)]) == 0
    assert "dry run" in capsys.readouterr().out and not (folder / "parts/sources/10.9999-a.1.json").exists()
    assert main(["graph", "contribute", str(g), "--to", str(folder), "--write"]) == 0
    assert (folder / "parts/sources/10.9999-a.1.json").is_file()
    capsys.readouterr()
    assert main(["graph", "contribute", str(g), "--to", str(folder)]) == 1
    assert "already in" in capsys.readouterr().out
