"""Raw search hits (.scripts/<topic>/raw/<label>/<database>.jsonl): kept compressed (.jsonl.gz) they build exactly the
same; a run of its own (search.py --label, build_list.py --run <label>) is read alone; the topic gate's english_only
keeps other languages out of the build; a large raw file is cut into byte ranges for --batches; and a secondary
OpenAlex query stops early only after a long run of pages with nothing new.

    python -m pytest tests          (from the skill folder; standard library and pytest only)
"""
import gzip
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

HITS = [{"doi": "10.1000/raw.1", "title": "Copper catalysts for the electroreduction of CO2 to ethylene", "year": 2024,
         "source": "openalex", "doc_type": "article"},
        {"doi": "10.1000/raw.2", "title": "Catalizadores de cobre para la electrorreducción de CO2 a etileno en medio",
         "year": 2024, "source": "openalex", "doc_type": "article"}]


@pytest.fixture()
def project(tmp_path):
    from _common import Project
    proj = Project(tmp_path / "project")
    (proj.scr / "t").mkdir(parents=True, exist_ok=True)
    (proj.scr / "t" / "config.json").write_text(json.dumps(
        {"topic": "Test topic", "slug": "t", "gate": {"any": ["re:cataly", "re:cat[aá]li[sz]"], "english_only": True},
         "screening": {"method": "none", "threshold": 3}}))
    raw = proj.scr / "t" / "raw"
    (raw / "full").mkdir(parents=True)
    with gzip.open(raw / "full" / "openalex.jsonl.gz", "wt", encoding="utf-8") as fh:     # an older run, compressed
        fh.write(json.dumps(HITS[0]) + "\n")
    (raw / "again").mkdir()
    (raw / "again" / "openalex.jsonl").write_text(json.dumps(HITS[1]) + "\n")             # a run of its own
    return proj


def build(proj, *args):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "build_list.py"), "--project", str(proj.root), "--topic",
                        "t", *args], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_compressed_hits_build_and_a_labelled_run_is_read_alone(project):
    from _ledger import Ledger
    b = build(project, "--run", "full")
    assert b["raw_records"] == 1 and b["new_in_ledger"] == 1                 # read from openalex.jsonl.gz
    b = build(project, "--run", "again")
    assert b["raw_records"] == 1 and b["new_in_ledger"] == 0                 # only that run; Spanish: gated out
    assert b["off_topic_dropped_by_gate"] == 1
    led = Ledger(project)
    assert led.find_id(doi="10.1000/raw.1") and not led.find_id(doi="10.1000/raw.2")


def test_one_large_raw_file_is_cut_into_byte_ranges_that_cover_every_record_once(tmp_path):
    import json as _json
    from build_list import iter_part, split_files
    big, small = tmp_path / "openalex.jsonl", tmp_path / "crossref.jsonl"
    big.write_text("".join(_json.dumps({"i": i, "t": "x" * (i % 97)}) + "\n" for i in range(3000)))
    small.write_text("".join(_json.dumps({"i": 10000 + i}) + "\n" for i in range(200)))
    for n in (1, 3, 8):
        groups = split_files([small, big], n)
        got = sorted(r["i"] for g in groups for part in g for r in iter_part(part))
        assert got == list(range(3000)) + list(range(10000, 10200))
    assert sum(isinstance(p, tuple) for g in split_files([small, big], 8) for p in g) >= 6     # the big file was cut


def fake_openalex(pages=60, new_every=None):
    """A stand-in for the OpenAlex fetcher (no network): `pages` pages of 5 records each. The query "first" brings
    new DOIs; any other query repeats them, except one new DOI every `new_every` pages."""
    calls = []

    def fetch(query, cursor, since, ctx):
        n = int(cursor or 0)
        calls.append((query, n))
        if query == "first":
            recs = [{"doi": f"10.1000/p{n}.{i}", "title": f"Catalyst {n}.{i}"} for i in range(5)]
        else:
            recs = [{"doi": f"10.1000/p{n % 7}.{i}", "title": "Catalyst again"} for i in range(5)]
            if new_every and n % new_every == 0:
                recs[0] = {"doi": f"10.1000/{query}.{n}", "title": "A new catalyst"}
        return recs, (str(n + 1) if n + 1 < pages else None), pages * 5
    return fetch, calls


def test_a_secondary_openalex_query_stops_only_after_a_long_run_of_pages_with_nothing_new(tmp_path, monkeypatch):
    import search
    from _common import Project, load_state
    proj = Project(tmp_path / "project")
    fetch, calls = fake_openalex()
    monkeypatch.setitem(search.FETCHERS, "openalex", fetch)
    runner = search.Runner(proj, "t", {"slug": "t", "gate": {}}, "full", None)
    runner.run_query("openalex", "q1", "first", primary=True)
    runner.run_query("openalex", "q2", "again", primary=False)
    state = load_state(proj, "t")["search"]["full"]["openalex"]
    assert state["q1"]["pages"] == 60 and state["q1"]["done"]
    # one page of duplicates used to end q2 at its first page; now it takes DUP_PAGES of them in a row
    assert state["q2"]["pages"] == search.DUP_PAGES and state["q2"]["dup_streak"] == search.DUP_PAGES
    assert "pages in a row" in state["q2"]["stopped_because"]
    fetch, calls = fake_openalex(new_every=10)              # something new now and then: paged to the end
    monkeypatch.setitem(search.FETCHERS, "openalex", fetch)
    runner.run_query("openalex", "q3", "sometimes", primary=False)
    state = load_state(proj, "t")["search"]["full"]["openalex"]
    assert state["q3"]["pages"] == 60 and not state["q3"]["stopped_because"]


def test_a_run_of_its_own_with_its_own_queries_file(tmp_path, monkeypatch):
    import search
    from _common import Project, load_state
    proj = Project(tmp_path / "project")
    (proj.scr / "t").mkdir(parents=True, exist_ok=True)
    (proj.scr / "t" / "config.json").write_text(json.dumps({"topic": "Test topic", "slug": "t",
                                                            "databases": ["openalex"], "gate": {}}))
    (proj.scr / "t" / "queries.json").write_text(json.dumps({"openalex": {"q1": "topic queries"}}))
    extra = tmp_path / "gap_queries.json"
    extra.write_text(json.dumps({"openalex": {"g1": "first"}}))
    fetch, calls = fake_openalex(pages=2)
    monkeypatch.setitem(search.FETCHERS, "openalex", fetch)
    monkeypatch.setattr(sys, "argv", ["search.py", "--project", str(proj.root), "--topic", "t",
                                      "--queries", str(extra), "--label", "gaps"])
    search.main()
    assert {q for q, _ in calls} == {"first"}                                      # the file given, not queries.json
    assert (proj.scr / "t" / "raw" / "gaps" / "openalex.jsonl").is_file()
    assert load_state(proj, "t")["search_runs"]["gaps"]["finished_at"]
