"""A one-source graph contributed to catal-commons (scale graph contribute; tools/commons.py): refused when its source
is there already, its ids moved into the commons namespace, its quotes capped under the commons rights, and the parts
it writes build into a graph that validates."""

import json
import shutil

import pytest

from conftest import REPO
from scale import commons, curate, graphparts, pgraph, rights
from scale.cli import main
from scale.util import ScaleError, dump_yaml, load_doc, load_yaml, write_canonical

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
    def get(url, h):
        return json.dumps(meta).encode()
    version = load_doc(REPO / "graphs" / "catal-commons" / "parts" / "header.json")["graph"]["schema_version"]
    res = curate.start(tmp_path / name, text=tmp_path / f"{name}.txt", doi=doi, repo=REPO, get=get, version=version)
    w = tmp_path / name
    g = w / res["graph"]
    doc = load_doc(g)
    sid = res["source_id"]
    prefix = sid.replace("/source/", "/")
    def ev(q):
        return [{"source": sid, "locator": "p. 2", "kind": "text", "quote": q}]
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


def test_a_credited_contribution_joins_the_ledger_and_the_leaderboard_ranks_it(tmp_path, folder):
    """Credit is a file the pull request changes: contributors.yaml gains who, which source, the day and the counts;
    the leaderboard ranks by triples (the knowledge added), then papers, then who was first."""
    assert commons.contributions(folder) == [] and commons.leaderboard(folder) == []
    for name, doi, who, day in (("a", "10.9999/a.1", "Ada", "2026-10-20"), ("b", "10.9999/b.2", "bob", "2026-10-21"),
                                ("c", "10.9999/c.3", "ada", "2026-10-25")):
        w, g, sid = one_source(tmp_path, name, doi=doi, title=f"Copper catalysts for methanol synthesis, part {name}")
        res = commons.contribute(load_doc(g), folder, rights.load_rights(w / "rights.yaml")[sid], REPO,
                                 contributor=who, on=day)
        assert "contributors.yaml" in res["files"]
        commons.write(res, folder)
    rows = commons.contributions(folder)
    assert [(r["github"], r["source"], r["added"]) for r in rows] == [
        ("Ada", "10.9999-a.1", "2026-10-20"), ("bob", "10.9999-b.2", "2026-10-21"), ("ada", "10.9999-c.3", "2026-10-25")]
    assert all(r["records"] > 0 and r["links"] >= 0 and r["triples"] > r["links"] for r in rows)
    board = commons.leaderboard(folder)
    assert [(b["rank"], b["github"], b["sources"], b["first"], b["last"]) for b in board] == [
        (1, "Ada", 2, "2026-10-20", "2026-10-25"), (2, "bob", 1, "2026-10-21", "2026-10-21")]
    assert board[0]["triples"] == rows[0]["triples"] + rows[2]["triples"]
    ledger = folder / "contributors.yaml"                       # one rich paper outranks two thin ones
    data = load_yaml(ledger)
    data["contributions"][1]["triples"] = 100000
    ledger.write_text(dump_yaml(data))
    assert [b["github"] for b in commons.leaderboard(folder)] == ["bob", "Ada"]
    w, g, sid = one_source(tmp_path, "d", doi="10.9999/d.4", title="Copper catalysts for methanol synthesis, part d")
    entry = rights.load_rights(w / "rights.yaml")[sid]
    with pytest.raises(ScaleError, match="not a GitHub login"):
        commons.contribute(load_doc(g), folder, entry, REPO, contributor="ada; rm -rf", on="2026-10-25")
    with pytest.raises(ScaleError, match="give the day"):
        commons.contribute(load_doc(g), folder, entry, REPO, contributor="ada")
    assert "contributors.yaml" not in commons.contribute(load_doc(g), folder, entry, REPO)["files"]   # uncredited


def test_triples_count_evidence_backed_statements_not_bookkeeping():
    """A triple is a link between two records (not REPORTED_IN) or a value stated on a record or a link, counted only
    when that link or record cites evidence; evidence, provenance, notes, a value not reported and a Source's
    bibliography are not counted."""
    ev = [{"quote": "q"}]
    nodes = [{"id": "s", "label": "Source", "props": {"title": "A paper", "year": 2020, "evidence": ev}},
             {"id": "t", "label": "CatalyticTest", "props": {
                 "temperature": {"status": "reported", "value": 523, "unit": "K"},
                 "pressure": {"status": "not_reported", "missing_reason": "not_stated_in_source"},
                 "test_kind": "activity", "evidence": ev, "origin": "reported", "note": "n"}},
             {"id": "c", "label": "Catalyst", "props": {"name": "Cu/ZnO", "description": ""}}]        # no evidence
    links = [{"type": "REPORTED_IN", "source": "t", "target": "s", "props": {"status": "asserted", "evidence": ev}},
             {"type": "USES_CATALYST", "source": "t", "target": "c", "props": {"role": "main", "evidence": ev}},
             {"type": "FED_WITH", "source": "t", "target": "c", "props": {}}]                            # no evidence
    assert commons.triples(nodes, links) == 2 + 2      # temperature, test_kind; USES_CATALYST and its role


def test_the_score_weights_triples_by_use_and_the_boards_show_levels_and_the_last_90_days(tmp_path):
    """Score = triples x (1 + log2(1 + reach)); the ranking is by score, so a paper others use outranks a larger one
    nobody has used; completeness is shown, weighted by triples, never mixed in; levels and the recent board follow."""
    (tmp_path / "contributors.yaml").write_text(dump_yaml({"contributions": [
        {"github": "ada", "source": "big", "added": "2026-01-02", "records": 50, "links": 60, "triples": 900,
         "completeness": 0.5},
        {"github": "bob", "source": "used", "added": "2026-10-01", "records": 20, "links": 20, "triples": 400,
         "completeness": 0.9},
        {"github": "bob", "source": "old", "added": "2025-01-01", "records": 2, "links": 1, "triples": 100}]}))
    assert commons.use_weight(0) == 1 and commons.use_weight(1) == 2 and commons.use_weight(7) == 4
    board = commons.boards(tmp_path, {"used": 3}, today="2026-10-25")
    top = board["contributors"]
    assert [(b["github"], b["score"], b["triples"], b["reach"]) for b in top] == [("bob", 1300, 500, 3),
                                                                                  ("ada", 900, 900, 0)]
    assert top[0]["completeness"] == 0.9 and top[0]["contributions"][0] == {
        "source": "used", "added": "2026-10-01", "triples": 400, "reach": 3, "score": 1200, "completeness": 0.9}
    assert top[0]["level"] == {"name": "Curator", "next": "Senior curator", "to_next": 8700}
    assert [b["github"] for b in board["recent"]] == ["bob"] and board["recent"][0]["sources"] == 1
    assert board["scoring"] is commons.SCORING and board["levels"][0] == {"at": 0, "name": "Contributor"}
    assert [b["github"] for b in commons.leaderboard(tmp_path)] == ["ada", "bob"]     # no use counted: by triples


def test_repeats_of_what_the_commons_holds_are_discarded_on_merge_and_never_counted(tmp_path, folder):
    """A shared record the commons holds under another id (the same name, no other formula) is not added again: the
    contribution points to the held record, which gains its evidence; a value equal to the held one is a repeat, and a
    link stated twice is merged into one. Repeats are reported and add no triple."""
    w, g, sid = one_source(tmp_path, "a", doi="10.9999/a.1", title="Copper catalysts for methanol synthesis, part a")
    first = commons.contribute(load_doc(g), folder, rights.load_rights(w / "rights.yaml")[sid], REPO)
    commons.write(first, folder)
    w, g, sid = one_source(tmp_path, "b", doi="10.9999/b.2", title="Copper catalysts for methanol synthesis, part b")
    doc = json.loads(json.dumps(load_doc(g)).replace("ex:pub/species/copper", "ex:pub/species/cu-metal"))   # another id
    claim = next(n["id"] for n in doc["nodes"] if n["label"] == "Claim")
    ev = [{"source": sid, "locator": "p. 2", "kind": "text", "quote": "copper is the active phase"}]
    doc["links"] += [{"id": f"{claim}/about/{i}", "type": "ABOUT", "source": claim, "target": "ex:pub/species/cu-metal",
                      "props": {"evidence": ev}} for i in (1, 2)]             # one link, stated twice
    res = commons.contribute(doc, folder, rights.load_rights(w / "rights.yaml")[sid], REPO)
    assert res["repeats"]["records"] == [{"given": "scale:commons/species/cu-metal", "held": "scale:commons/species/copper"}]
    assert res["repeats"]["links"] == 1 and res["repeats"]["values"] == 2 and res["conflicts"] == []
    assert res["shared_added"] == [] and "scale:commons/species/copper" in res["shared_with_new_evidence"]
    part = json.loads(res["files"][f"parts/sources/{res['slug']}.json"])
    about = [lk for lk in part["links"] if lk["type"] == "ABOUT"]
    assert [lk["target"] for lk in about] == ["scale:commons/species/copper"]
    shared = json.loads(res["files"]["parts/shared.json"])
    ends = {x for lk in part["links"] + shared["links"] for x in (lk["source"], lk["target"])}
    assert not any("cu-metal" in x for x in ends | {n["id"] for n in part["nodes"] + shared["nodes"]})
    assert res["records"]["triples"] == first["records"]["triples"] - 2 + 1   # not the species again; the link once
