"""Schema identity beyond a bare version number: a version's spec document and its digest (`scale graph spec`,
`scale graph verify`, the release build), the generic check that a pinned version (and digest) is this repository's
(`pgraph.identify`, `scale graph spec --expect`), a version the tools do not hold named as such, and the kg-bundle
export's digest, header and access."""

import copy
import datetime
import hashlib
import json

import pytest

from conftest import GRAPH_FROZEN, GRAPH_MANIFEST, HEAD_VERSION, REPO, spec_of
from scale import kgbundle, pgraph, pgraph_query
from scale.cli import main
from scale.releases import build_release, spec_digest_stability
from scale.util import ScaleError, load_doc, load_yaml, sha256_file
from scale.versions import parse_version

X = REPO / "domain/examples/scale-catal"


def _bundle_validator():
    """the format's validator where SCALE_BUNDLE_VALIDATOR provides it (test_graph_search_query), else None."""
    try:
        from test_graph_search_query import _bundle_validator as found
    except (ImportError, pytest.skip.Exception):         # that module needs numpy (the dev extra)
        return None
    return found()


@pytest.fixture(scope="module")
def head():
    return pgraph.load_spec(GRAPH_MANIFEST)


def _run(args, capsys):
    rc = main(["--repo", str(REPO), *args])
    out = capsys.readouterr()
    return rc, out.out, out.err


# ------------------------------------------------------------------------------------ spec documents and digests
def test_a_version_has_one_spec_digest_whatever_state_it_is_held_in(head):
    """The spec document leaves out where and in what state the repository holds a version (status, each part's
    path, the extension-prefix registry), so the head a release publishes and the frozen copy made of it later give
    one digest; the document says which numbering it belongs to (lineage: scale) and carries the one version."""
    doc = pgraph.spec_document(head)
    assert doc["lineage"] == "scale" == pgraph.SPEC_LINEAGE and doc["version"] == HEAD_VERSION
    assert not {"status", "extension_prefixes"} & set(doc)
    assert all("path" not in e for b in ("modules", "domains", "profiles") for e in doc[b].values())
    # one version: the kernel, the catalysis file and its checklist all report the manifest's
    assert doc["kernel"] == {"name": "scale-kernel", "version": HEAD_VERSION}
    assert {m["version"] for m in doc["modules"].values()} == {HEAD_VERSION}
    assert doc["domains"]["catalysis"]["version"] == doc["profiles"]["catalysis"]["version"] == HEAD_VERSION
    assert pgraph.spec_bytes(head) == pgraph.spec_bytes(pgraph.load_spec(GRAPH_MANIFEST))      # deterministic
    assert json.loads(pgraph.spec_bytes(head)) == json.loads(json.dumps(doc))
    other = copy.deepcopy(head)
    other["status"] = "frozen"
    assert pgraph.spec_sha256(other) == pgraph.spec_sha256(head)                 # the state is not the schema


# a recorded spec digest in the documentation: "scale-catal 0.2.0 ... `<sha256>`" on one line (0.1.0 was named scale-graph)
RECORDED_DIGEST = __import__("re").compile(r"scale-(?:catal|graph) (\d+\.\d+\.\d+)\b[^\n]*?`([0-9a-f]{64})`")


def test_the_documented_spec_digests_are_the_ones_held(head):
    """README.md and CHANGELOG.md record the spec digest of schema 0.1.0 (and of each later version they name): every
    version they record is held here (the head or frozen) with that digest. A change to the schema's content without
    a new version would change it and fail here; a version moved on by a proposal keeps its digest frozen."""
    held = dict(pgraph.spec_versions(GRAPH_MANIFEST))
    for f in ("README.md", "CHANGELOG.md"):
        recorded = RECORDED_DIGEST.findall((REPO / f).read_text())
        assert ("0.1.0" in {v for v, _ in recorded}), f"{f} records no spec digest of scale-catal 0.1.0"
        for v, digest in recorded:
            assert v in held and pgraph.spec_sha256(pgraph.load_spec(held[v])) == digest, (f, v, digest)
    assert RECORDED_DIGEST.findall("scale-catal 0.1.0 (spec digest `" + "a" * 64 + "`)") == [("0.1.0", "a" * 64)]


def test_every_version_is_listed_oldest_first_with_the_head_last():
    versions = pgraph.spec_versions(GRAPH_MANIFEST)
    frozen = sorted((p.stem.removeprefix("scale-catal-"), p) for p in GRAPH_FROZEN.glob("scale-catal-*.yaml"))
    assert versions[-1] == (HEAD_VERSION, GRAPH_MANIFEST) and sorted(versions[:-1]) == frozen   # 0.1.0: none frozen yet
    assert [parse_version(v) for v, _ in versions] == sorted(parse_version(v) for v, _ in versions)
    assert pgraph.public_versions(GRAPH_MANIFEST) == {v for v, _ in versions}


def test_graph_spec_writes_canonical_json_and_prints_its_digest(tmp_path, capsys, head):
    rc, out, _ = _run(["graph", "spec"], capsys)
    row = json.loads(out)
    assert rc in (0, None) and row["version"] == HEAD_VERSION and row["domain"] == "catalysis"
    assert row["sha256"] == pgraph.spec_sha256(head) and "written" not in row
    one = tmp_path / "one.json"
    rc, out, _ = _run(["graph", "spec", "--version", HEAD_VERSION, "--out", str(one)], capsys)
    row = json.loads(out)
    assert row["manifest"] == "domain/graph/scale-catal.yaml"
    assert hashlib.sha256(one.read_bytes()).hexdigest() == row["sha256"] and json.loads(one.read_text())["version"] == HEAD_VERSION
    rc, out, _ = _run(["graph", "spec", "--all", "--out", str(tmp_path / "all")], capsys)
    rows = json.loads(out)
    assert [r["version"] for r in rows] == [v for v, _ in pgraph.spec_versions(GRAPH_MANIFEST)]
    sums = (tmp_path / "all/SHA256SUMS").read_text().splitlines()
    assert sums == [f"{r['sha256']}  catalysis/scale-catal-{r['version']}.json" for r in rows]
    assert all(sha256_file(tmp_path / "all/catalysis" / f"scale-catal-{r['version']}.json") == r["sha256"] for r in rows)
    assert _run(["graph", "spec", "--version", "9.9.9"], capsys)[0] == 2


def test_a_pinned_version_and_digest_are_checked_against_this_repository(capsys, head):
    """The generic identity check: a version number names a schema only within this repository's numbering, the spec
    digest everywhere. A version and digest that are this repository's match; the same number with another digest is
    another schema; a number this repository does not hold is unknown."""
    digest = pgraph.spec_sha256(head)
    ok = pgraph.identify(GRAPH_MANIFEST, HEAD_VERSION, digest)
    assert ok == {"version": HEAD_VERSION, "known": True, "sha256": digest, "matches": True}
    assert pgraph.identify(GRAPH_MANIFEST, HEAD_VERSION)["matches"] is None          # no digest given: nothing to compare
    other = pgraph.identify(GRAPH_MANIFEST, HEAD_VERSION, "0" * 64)
    assert other["matches"] is False and "another one of the same number" in other["message"]
    unknown = pgraph.identify(GRAPH_MANIFEST, "99.0.0", "0" * 64)
    assert unknown["known"] is False and unknown["matches"] is False
    assert "scale-catal 99.0.0 is not a version this repository holds" in unknown["message"]
    rc, out, _ = _run(["graph", "spec", "--expect", digest], capsys)
    assert rc == 0 and json.loads(out)["matches"] is True
    rc, out, _ = _run(["graph", "spec", "--expect", "0" * 64], capsys)
    assert rc == 1 and json.loads(out)["matches"] is False
    rc, out, _ = _run(["graph", "spec", "--version", "99.0.0", "--expect", digest], capsys)    # a version never held
    assert rc == 1 and json.loads(out)["known"] is False


def test_graph_spec_names_a_manifest_by_its_domain(tmp_path, capsys):
    """``--spec`` with a copy of the manifest in a tree that mirrors the repository (a frozen version, a release's or a
    candidate's copy) names it by its domain, catalysis, as the head is named."""
    import shutil
    tree = tmp_path / "tree"
    shutil.copytree(REPO / "core", tree / "core")
    shutil.copytree(REPO / "domain/graph", tree / "domain/graph")
    shutil.copy2(REPO / "domain/DOMAIN.yaml", tree / "domain/DOMAIN.yaml")
    shutil.copytree(REPO / "governance/registry", tree / "governance/registry")
    rc, out, _ = _run(["graph", "spec", "--spec", str(tree / "domain/graph/scale-catal.yaml")], capsys)
    assert rc in (0, None) and json.loads(out)["domain"] == "catalysis"
    assert json.loads(out)["sha256"] == pgraph.spec_sha256(pgraph.load_spec(GRAPH_MANIFEST))   # the same schema, the same digest


def test_verify_reports_each_digest_and_checks_the_released_ones(capsys):
    rc, out, _ = _run(["graph", "verify"], capsys)
    res = json.loads(out)
    # every spec digest a built release published is still the repository's (none to check before the first release)
    from scale.releases import list_releases, released_spec_digests
    published = [(r, d["version"]) for r in list_releases(REPO) for d in released_spec_digests(REPO, r)]
    sd = res["spec_digests"]
    assert rc == 0 and res["ok"] and sd["ok"] and sd["problems"] == []
    assert [(c["release"], c["version"]) for c in sd["checked"]] == published and all(c["ok"] for c in sd["checked"])
    assert [len(x["spec_sha256"]) for x in res["heads"]] == [64]
    assert [x["version"] for x in res["frozen"]] == [v for v, _ in pgraph.spec_versions(GRAPH_MANIFEST)[:-1]]   # none at 0.1.0
    empty = spec_digest_stability(REPO, {})          # with no digests to compare, every published one is a problem
    assert empty["ok"] == (not published) and len(empty["problems"]) == len(published)


def test_a_release_ships_the_spec_document_of_every_version(tmp_path):
    from test_release_manifest import _mini
    repo = _mini(tmp_path)
    dest = build_release(repo, "v0.1.0", date="2026-10-08")
    m = load_yaml(dest / "RELEASE.yaml")
    docs = m["spec_documents"]
    assert [d["version"] for d in docs] == [v for v, _ in pgraph.spec_versions(GRAPH_MANIFEST)]
    for d in docs:
        assert d["file"] == f"specs/catalysis/scale-catal-{d['version']}.json"
        assert m["digests"][d["file"]] == d["sha256"] == sha256_file(dest / d["file"])
        held = dict(pgraph.spec_versions(GRAPH_MANIFEST))[d["version"]]
        assert d["sha256"] == pgraph.spec_sha256(pgraph.load_spec(held))       # the same digest as the repository's
    assert list(m)[-2:] == ["spec_documents", "digests"]


# ------------------------------------------------------------------------------------ versions the tools do not hold
def test_a_version_the_tools_do_not_hold_is_named_as_such(tmp_path, capsys):
    """A document pinning a version this repository does not hold is not read under another version: validation says
    the version is newer than the head (update the tools or pass --spec), or that the repository holds other versions
    and a version is identified by its digest. Nothing is guessed about which numbering it came from."""
    from scale.api import ScaleToolkit
    kit = ScaleToolkit(repo=REPO, workspace=tmp_path / "ws")
    doc = load_doc(X / "example.json")
    for v, says in (("9.0.0", f"newer than this schema's head {HEAD_VERSION}"), ("0.0.9", "identified by its spec digest")):
        doc["graph"]["schema_version"] = v
        f = tmp_path / f"doc-{v}.json"
        f.write_text(json.dumps(doc))
        rc, _, err = _run(["graph", "validate", "--format", "json", str(f)], capsys)
        assert rc == 2 and f"document pins scale-catal {v}, which is not a version this repository holds" in err and says in err
        assert "lineage" not in err
        res = kit.call("scale_validate", {"document": doc})
        assert says in res["error"]
        for args in (["graph", "query", str(f), str(tmp_path / "plan.json")], ["graph", "migrate", str(f), str(tmp_path / "o.json")]):
            (tmp_path / "plan.json").write_text(json.dumps({"match": {"label": "Source", "as": "s"}, "return": ["s.name"]}))
            rc, _, err = _run(args, capsys)
            assert rc == 2 and not (tmp_path / "o.json").exists(), args


def test_a_bundle_graph_is_named_as_one_not_as_a_newer_version(tmp_path, capsys, head):
    """A kg-bundle's kg/graph.json names its bundle and the bundle's schema (scale-<domain>, with the scale-catal
    version it is the vocabulary of). It is the bundle format's graph, not a scale-catal document: validating it is
    refused, whatever version it names, with a message that names it as a bundle's graph, never as a newer version."""
    from scale.api import ScaleToolkit
    kit = ScaleToolkit(repo=REPO, workspace=tmp_path / "ws")
    held = pgraph.public_versions(GRAPH_MANIFEST)
    for version in ("9.0.1", "0.0.1"):              # newer than the head, and older
        assert version not in held
        out = tmp_path / f"b{version}"
        ex = load_doc(X / "example.json")
        kgbundle.export(ex, spec_of(ex), out, "acc-bundle", version)
        f = out / "kg/graph.json"
        g = load_doc(f)
        assert g["graph"]["version"] == version and pgraph.bundle_graph(g)
        assert (g["graph"]["schema_id"], g["graph"]["schema_version"]) == ("scale-catal", ex["graph"]["schema_version"])
        rc, _, err = _run(["graph", "validate", "--format", "json", str(f)], capsys)
        assert rc == 2 and "the graph of a kg-bundle" in err and "not a scale-catal document" in err, err
        assert "newer than this schema's head" not in err
        res = kit.call("scale_validate", {"document": g})
        assert "the graph of a kg-bundle" in res["error"]
    # a scale-catal pinning a version the tools do not hold keeps its message; a header that only half names a bundle
    # is not a bundle's graph
    doc = load_doc(X / "example.json")
    doc["graph"]["schema_version"] = "9.0.0"
    with pytest.raises(ScaleError) as err:
        pgraph.pinned(GRAPH_MANIFEST, "9.0.0", doc)
    assert "newer than this schema's head" in str(err.value) and "kg-bundle" not in str(err.value)
    for half in ({"bundle_id": "x"}, {"schema_id": "x"}, {"bundle_id": 1, "schema_id": "x"}):
        assert not pgraph.bundle_graph({"graph": half})
    assert not pgraph.bundle_graph(None) and not pgraph.bundle_graph({"graph": []})


def test_kg_update_refuses_a_document_pinning_a_version_not_held(tmp_path):
    from scale.kg import update
    data = tmp_path / "data"
    data.mkdir()
    other = load_doc(X / "example.json")
    other["graph"]["schema_version"] = "0.0.9"
    (data / "other.json").write_text(json.dumps(other))
    (data / "example.json").write_text(json.dumps(load_doc(X / "example.json")))
    rows = {r["document"]: r for r in update(REPO, data, dry_run=True, reindex=False)["documents"]}
    assert rows["other.json"]["status"] == "refused" and "is not a version this repository holds" in rows["other.json"]["why"]
    assert rows["example.json"]["status"] == ("current" if load_doc(X / "example.json")["graph"]["schema_version"] == HEAD_VERSION
                                              else "would update")


# ------------------------------------------------------------------------------------ kg-bundle: digest, header, access
P = "ex:acc/project/p"


def _access_doc():
    """A project graph citing a public paper: one record of the project, one public, one an institution's only, one
    embargoed until 2099."""
    q = "the catalyst was tested at 250 C"
    src = "ex:acc/source/paper"

    def ev():
        return [{"source": src, "locator": "p. 1", "kind": "text", "quote": q}]
    nodes = [{"id": src, "label": "Source", "props": {"name": "paper", "title": "paper", "kind": "article", "year": 2020,
                                                      "stewardship": {"access": "public"}}},          # a published paper
             {"id": "ex:acc/species/a", "label": "ChemicalSpecies", "props": {"name": "project species", "evidence": ev()}},
             {"id": "ex:acc/species/b", "label": "ChemicalSpecies", "props": {"name": "public species", "evidence": ev(),
                                                                              "stewardship": {"access": "public"}}},
             {"id": "ex:acc/species/c", "label": "ChemicalSpecies",
              "props": {"name": "institution species", "evidence": ev(),
                        "stewardship": {"access": "institution", "contributed_by": ["ex:acc/org/lab"]}}},
             {"id": "ex:acc/species/d", "label": "ChemicalSpecies",
              "props": {"name": "embargoed species", "evidence": ev(),
                        "stewardship": {"access": "embargoed", "embargo_until": "2099-01-01", "access_after_embargo": "public"}}},
             {"id": P, "label": "Project", "props": {"name": "project p"}},
             {"id": "ex:acc/org/lab", "label": "Institution", "props": {"name": "lab"}}]
    d = {"directed": True, "multigraph": True,
         "graph": {"schema": "scale-catal", "schema_version": HEAD_VERSION, "graph_id": "ex:acc/graph", "title": "access test",
                   "data_status": "research_data", "follows_domains": ["catalysis"],
                   "stewardship": {"access": "project", "project": P, "contributed_by": ["ex:acc/org/lab"],
                                   "licence": "CC-BY-4.0"}},
         "nodes": nodes, "links": []}
    d["links"] = pgraph.derive_reported_in(d)
    return d


def _names(bundle):
    g = json.loads((bundle / "kg/graph.json").read_text())
    return {n["props"].get("name"): n["props"] for n in g["nodes"] if n["label"] != "Publication"}


def test_the_bundle_names_its_schema_by_digest_and_carries_the_scale_header(tmp_path, head):
    doc = load_doc(X / "example.json")
    spec = pgraph.load_spec(pgraph.pinned(GRAPH_MANIFEST, doc["graph"]["schema_version"]))
    m = kgbundle.export(doc, spec, tmp_path / "b", "example", created="2026-10-06T00:00:00Z")
    schema = json.loads((tmp_path / "b/kg/schema.json").read_text())
    assert schema["extends"] == {"schema_id": "scale-catal", "version": doc["graph"]["schema_version"],
                                 "sha256": pgraph.spec_sha256(spec)}
    h = m["scale_header"]
    assert h == json.loads((tmp_path / "b/bundle.json").read_text())["scale_header"]
    assert (h["lineage"], h["data_status"], h["schema_version"], h["schema_sha256"]) == (
        "scale", "synthetic_example", doc["graph"]["schema_version"], pgraph.spec_sha256(spec))
    assert h["follows_domains"] == ["catalysis"] and h["stewardship"] == {"access": "public", "project": "ex:exmpl/project/examples"}
    assert h["access_at_export"] == {"level": "public", "date": "2026-10-06"}
    assert "access_warning" not in m["export_report"]           # a public bundle of public records
    # a synthetic graph says so where a reader looks first
    assert m["topic"].endswith("(synthetic example)") and len(m["topic"]) <= 300
    assert m["scope"].startswith("Synthetic example data") and len(m["scope"]) <= 1000
    assert json.loads((tmp_path / "b/kg/graph.json").read_text())["graph"]["topic"] == m["topic"]
    mixed = copy.deepcopy(doc)
    mixed["graph"]["data_status"] = "mixed"
    assert kgbundle.export(mixed, spec, tmp_path / "m", "mixed", created="2026-10-06T00:00:00Z")["scope"].startswith("Mixed data")


def test_records_less_open_than_the_bundle_are_withheld_or_marked(tmp_path, head):
    doc = _access_doc()
    assert pgraph.validate(doc, head).errors == []
    m = kgbundle.export(doc, head, tmp_path / "w", "acc", created="2026-10-06T00:00:00Z")
    names = _names(tmp_path / "w")
    assert set(names) == {"project species", "public species"}            # institution and embargoed: withheld
    assert names["public species"]["scale_access"] == "public" and "scale_access" not in names["project species"]
    acc = m["export_report"]["access"]
    assert acc["bundle"] == "project" and acc["withheld_less_open"]["nodes"] == 2
    assert acc["records_by_access"] == {"project": 1, "public": 2}        # the paper (a Publication) is public
    assert "not public" in m["export_report"]["access_warning"] and P in m["export_report"]["access_warning"]
    assert m["scale_header"]["stewardship"] == {"access": "project", "project": P, "licence": "CC-BY-4.0"}
    assert "contributed_by" not in m["scale_header"]["stewardship"]     # named for an institution bundle only
    schema = json.loads((tmp_path / "w/kg/schema.json").read_text())
    assert schema["node_types"]["ChemicalSpecies"]["properties"]["scale_access"]["type"] == "enum"
    kept = kgbundle.export(doc, head, tmp_path / "k", "acc", created="2026-10-06T00:00:00Z", keep_less_open=True)
    names = _names(tmp_path / "k")
    assert names["institution species"]["scale_access"] == "institution"
    assert names["embargoed species"]["scale_access"] == "institution"     # an embargo in force
    assert kept["export_report"]["access"].get("less_open_kept") and "withheld_less_open" not in kept["export_report"]["access"]
    # an export for the public declares public access: only public records remain, and nothing warns
    pub = kgbundle.export(pgraph.filter_for(doc, [], "2026-10-06"), head, tmp_path / "p", "acc",
                        created="2026-10-06T00:00:00Z", access={"access": "public"})
    assert set(_names(tmp_path / "p")) == {"public species"} and "access_warning" not in pub["export_report"]
    assert pub["scale_header"]["stewardship"] == {"access": "public", "licence": "CC-BY-4.0"}   # the licence is kept
    v = _bundle_validator()
    if v:
        for b in ("w", "k", "p"):
            kgbundle.seal(tmp_path / b)
            assert v.validate_bundle(tmp_path / b).ok


def test_the_cli_export_warns_and_declares_public_for_the_public(tmp_path, capsys):
    f = tmp_path / "acc.json"
    f.write_text(json.dumps(_access_doc()))
    base = ["graph", "export", str(f), "--to", "kg-bundle", "--created", "2026-10-06T00:00:00Z"]
    rc, out, err = _run(base + ["--out", str(tmp_path / "b")], capsys)
    assert rc == 0 and "scale: warning: not public" in err
    rc, out, err = _run(base + ["--out", str(tmp_path / "pub"), "--public"], capsys)
    assert rc == 0 and "warning" not in err
    assert json.loads((tmp_path / "pub/bundle.json").read_text())["scale_header"]["stewardship"] == {
        "access": "public", "licence": "CC-BY-4.0"}                   # --public sets the audience, not the licence
    unknown = load_doc(X / "example.json")
    unknown["graph"]["schema_version"] = "0.0.9"                     # a version this repository does not hold
    f.write_text(json.dumps(unknown))
    rc, _, err = _run(["graph", "export", str(f), "--to", "kg-bundle", "--out", str(tmp_path / "x")], capsys)
    assert rc == 2 and "is not a version this repository holds" in err and not (tmp_path / "x").exists()


def test_a_later_date_never_opens_an_embargo_still_in_force(tmp_path, capsys, head):
    """Embargoes are read on the given day or today, whichever is earlier (pgraph.embargo_day): a bundle created
    (--created) or a view filtered (--date) on a day after an embargo in force lapses still withholds its record, the
    bundle's access_at_export names the day embargoes were read on (created stays its timestamp), and a day that is
    not a date is refused."""
    d = _access_doc()
    d["graph"]["stewardship"] = {"access": "public", "licence": "CC-BY-4.0"}       # the embargoed record: public after 2099
    f = tmp_path / "acc.json"
    f.write_text(json.dumps(d))
    today = pgraph.embargo_today()                  # the earlier of the local and the UTC date: every path reads it
    for created in ("2099-06-01T00:00:00Z", None):
        out = tmp_path / f"b{created is None}"
        rc, _, err = _run(["graph", "export", str(f), "--to", "kg-bundle", "--out", str(out),
                           *(["--created", created] if created else [])], capsys)
        m = json.loads((out / "bundle.json").read_text())
        assert rc == 0 and set(_names(out)) == {"project species", "public species"}, err      # embargoed: withheld
        assert m["scale_header"]["access_at_export"]["date"] == today
        assert created is None or m["created"] == created
    rc, out, err = _run(["graph", "filter", str(f), "--public", "--date", "2099-06-01"], capsys)
    view = json.loads(out)
    assert rc == 0 and "embargoed species" not in {n["props"].get("name") for n in view["nodes"]}
    assert f"on {today}:" in view["graph"]["filtered_for"]
    rc, out, _ = _run(["graph", "filter", str(f), "--public", "--date", "2020-01-01"], capsys)   # earlier: as given
    assert rc == 0 and "on 2020-01-01:" in json.loads(out)["graph"]["filtered_for"]
    # the export's own view (--public) and the Neo4j export read --date the same way, and the Python API reads created so
    pub = tmp_path / "pub"
    rc, _, err = _run(["graph", "export", str(f), "--to", "kg-bundle", "--out", str(pub), "--public", "--date", "2099-06-01",
                       "--created", "2099-06-01T00:00:00Z"], capsys)
    assert rc == 0 and "embargoed species" not in _names(pub) and "public species" in _names(pub), err
    rc, neo, err = _run(["graph", "export", str(f), "--to", "neo4j", "--public", "--date", "2099-06-01"], capsys)
    assert rc == 0 and "public species" in neo and "embargoed species" not in neo, err
    m = kgbundle.export(d, head, tmp_path / "py", "acc", created="2099-06-01T00:00:00Z")
    assert "embargoed species" not in _names(tmp_path / "py") and m["scale_header"]["access_at_export"]["date"] == today
    for bad in ("2099-13-01", "tomorrow", "2099"):
        rc, _, err = _run(["graph", "filter", str(f), "--public", "--date", bad], capsys)
        assert rc == 2 and "--date" in err, bad
        with pytest.raises(ScaleError, match="created"):
            kgbundle.export(d, head, tmp_path / "x", "acc", created=bad)
    assert not (tmp_path / "x").exists()



def test_every_embargo_read_takes_one_clock_the_earlier_of_the_local_and_the_utc_date(tmp_path, capsys, monkeypatch):
    """One clock (pgraph.clock), one day (pgraph.embargo_today: the local date or the UTC date, whichever is earlier):
    at 21:00 on 7 October 2026 four hours behind UTC (8 October in UTC), and at 09:00 on 8 October thirteen hours ahead
    (7 October in UTC), a record embargoed until 2026-10-07 is still withheld by the filter and by both exports, and
    every bundle reads it on 2026-10-07; on 8 October in both it has lapsed on every path."""
    d = _access_doc()
    d["graph"]["stewardship"] = {"access": "public", "licence": "CC-BY-4.0"}
    emb = next(n for n in d["nodes"] if n["id"] == "ex:acc/species/d")
    emb["props"]["stewardship"]["embargo_until"] = "2026-10-07"
    f = tmp_path / "acc.json"
    f.write_text(json.dumps(d))
    tz = datetime.timezone
    for i, (now, day, shipped) in enumerate((
            (datetime.datetime(2026, 10, 7, 21, 0, tzinfo=tz(datetime.timedelta(hours=-4))), "2026-10-07", False),
            (datetime.datetime(2026, 10, 8, 9, 0, tzinfo=tz(datetime.timedelta(hours=13))), "2026-10-07", False),
            (datetime.datetime(2026, 10, 8, 12, 0, tzinfo=tz(datetime.timedelta(hours=-4))), "2026-10-08", True))):
        monkeypatch.setattr(pgraph, "clock", lambda now=now: now)
        assert pgraph.embargo_today() == day
        rc, out, err = _run(["graph", "filter", str(f), "--public"], capsys)
        view = json.loads(out)
        assert rc == 0 and f"on {day}:" in view["graph"]["filtered_for"], err
        assert ("embargoed species" in {n["props"].get("name") for n in view["nodes"]}) is shipped
        for extra in ([], ["--public"]):
            b = tmp_path / f"b{i}{len(extra)}"
            rc, _, err = _run(["graph", "export", str(f), "--to", "kg-bundle", "--out", str(b), *extra], capsys)
            m = json.loads((b / "bundle.json").read_text())
            assert rc == 0 and ("embargoed species" in _names(b)) is shipped, (now, extra, err)
            assert m["scale_header"]["access_at_export"]["date"] == day
            assert m["created"] == now.astimezone(tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")     # the same clock, in UTC
        rc, neo, err = _run(["graph", "export", str(f), "--to", "neo4j", "--public"], capsys)
        assert rc == 0 and ("embargoed species" in neo) is shipped, err


def _institution_doc(lab_in_project: bool):
    """An institution's graph (the lab's) holding a record of its own, a record of project P, one of another project
    P2, a consortium record and a public one; the lab takes part in P only when ``lab_in_project``."""
    d = _access_doc()
    lab = "ex:acc/org/lab"
    d["graph"]["stewardship"] = {"access": "institution", "project": P, "contributed_by": [lab], "licence": "CC-BY-4.0"}
    ev = d["nodes"][1]["props"]["evidence"]
    d["nodes"] = [n for n in d["nodes"] if n["id"] not in ("ex:acc/species/c", "ex:acc/species/d")]
    d["nodes"][1]["props"]["name"] = "lab species"                  # the graph's default: the lab's
    for name, st in (("project species", {"access": "project", "project": P}),
                     ("other project species", {"access": "project", "project": "ex:acc/project/p2"}),
                     ("consortium species", {"access": "consortium"})):
        d["nodes"].append({"id": f"ex:acc/species/{name.split()[0]}", "label": "ChemicalSpecies",
                           "props": {"name": name, "evidence": ev, "stewardship": st}})
    d["nodes"].append({"id": "ex:acc/project/p2", "label": "Project", "props": {"name": "project p2"}})
    d["links"] = [e for e in d["links"] if e["type"] != "PARTICIPATES_IN"]
    if lab_in_project:
        d["links"].append({"id": "ex:acc/lab-in-p", "source": lab, "target": P, "type": "PARTICIPATES_IN",
                           "props": {"origin": "curated", "role": "partner"}})
    d["links"] = [e for e in d["links"] if e["type"] != "REPORTED_IN"]
    d["links"] += pgraph.derive_reported_in(d)
    return d


def test_an_institution_bundle_holds_only_what_each_of_its_institutions_may_see(tmp_path, head):
    """Less open is judged by who may see a record, not by the order of the levels: an institution bundle withholds
    another project's record, and a project's or the consortium's when the institution takes no part in it."""
    for lab_in_project, want in ((True, {"lab species", "project species", "consortium species", "public species"}),
                                 (False, {"lab species", "public species"})):
        doc = _institution_doc(lab_in_project)
        assert pgraph.validate(doc, head).errors == []
        out = tmp_path / f"i{int(lab_in_project)}"
        m = kgbundle.export(doc, head, out, "inst", created="2026-10-06T00:00:00Z")
        names = _names(out)
        assert set(names) == want, lab_in_project
        # the same as the lab itself may see (scale graph filter)
        seen = {n["props"]["name"] for n in pgraph.filter_for(doc, ["ex:acc/org/lab"], "2026-10-06")["nodes"]
                if n["label"] == "ChemicalSpecies"}
        assert seen == want
        acc = m["export_report"]["access"]
        assert acc["bundle"] == "institution" and acc["withheld_less_open"]["nodes"] == 5 - len(want)
        assert m["scale_header"]["stewardship"] == {"access": "institution", "project": P,
                                                     "contributed_by": ["ex:acc/org/lab"], "licence": "CC-BY-4.0"}
        assert "ex:acc/org/lab" in m["export_report"]["access_warning"]
        assert "other project species" not in (out / "kg/graph.json").read_text()
    # two institutions: what both may see (the second takes part in no project)
    doc = _institution_doc(True)
    doc["graph"]["stewardship"]["contributed_by"] = ["ex:acc/org/lab", "ex:acc/org/other"]
    doc["nodes"].append({"id": "ex:acc/org/other", "label": "Institution", "props": {"name": "other"}})
    kgbundle.export(doc, head, tmp_path / "two", "inst", created="2026-10-06T00:00:00Z")
    assert set(_names(tmp_path / "two")) == {"lab species", "public species"}
    # a graph that states no stewardship: its own records share the bundle's (unnamed) audience; a project's does not
    bare = _institution_doc(True)
    bare["graph"].pop("stewardship")
    kgbundle.export(bare, head, tmp_path / "bare", "inst", created="2026-10-06T00:00:00Z")
    assert set(_names(tmp_path / "bare")) == {"lab species", "public species"}
    # unit level: the audience of each level, read by visible()
    st = {"access": "project", "project": "ex:acc/project/p2"}
    for declared, hidden in (({"access": "public"}, True), ({"access": "consortium"}, True),
                             ({"access": "project", "project": P}, True), ({"access": "project", "project": "ex:acc/project/p2"}, False)):
        assert pgraph.less_open(st, pgraph.audience(doc, declared, "2026-10-06"), "2026-10-06") is hidden, declared


def test_texts_of_withheld_sources_are_not_shipped(tmp_path, capsys):
    """A source the access rule withheld keeps its text and id out of the bundle (text/, its manifest), and the export
    says so."""
    d = _access_doc()
    d["nodes"].append({"id": "ex:acc/source/review", "label": "Source",
                       "props": {"name": "review", "title": "review", "kind": "article", "year": 2021,
                                 "stewardship": {"access": "institution", "contributed_by": ["ex:acc/org/lab"]}}})
    f = tmp_path / "acc.json"
    f.write_text(json.dumps(d))
    paper, review = tmp_path / "paper.txt", tmp_path / "review.txt"
    paper.write_text("the catalyst was tested at 250 C")
    review.write_text("an institution's own review")
    rc, out, err = _run(["graph", "export", str(f), "--to", "kg-bundle", "--out", str(tmp_path / "b"), "--created",
                         "2026-10-06T00:00:00Z", "--text", f"ex:acc/source/paper={paper}:CC0-1.0",
                         "--text", f"ex:acc/source/review={review}:CC0-1.0"], capsys)
    assert rc == 0 and "--text not shipped for ex:acc/source/review" in err
    b = tmp_path / "b"
    assert sorted(p.name for p in (b / "text").iterdir()) == ["_manifest.json", "paper.txt"]
    for part in ("text/_manifest.json", "kg/graph.json", "bundle.json"):
        assert "ex:acc/source/review" not in (b / part).read_text() and "own review" not in (b / part).read_text(), part
    man = json.loads((b / "bundle.json").read_text())
    assert man["export_report"]["texts_not_shipped"] == 1 and man["redistributable_publications"] == 1
    # kept with --keep-less-open, as the record is
    rc, out, err = _run(["graph", "export", str(f), "--to", "kg-bundle", "--out", str(tmp_path / "k"), "--keep-less-open",
                         "--text", f"ex:acc/source/review={review}:CC0-1.0"], capsys)
    assert rc == 0 and (tmp_path / "k/text/review.txt").exists() and "not shipped" not in err


def test_kept_records_of_another_audience_name_it(tmp_path, head):
    """With keep_less_open, a record whose audience differs from the bundle's names it: the level alone would read as
    the bundle's own project or institutions (another project's record in a project bundle is not the bundle's)."""
    doc = _access_doc()
    doc["nodes"].append({"id": "ex:acc/species/e", "label": "ChemicalSpecies",
                         "props": {"name": "other project species", "evidence": doc["nodes"][1]["props"]["evidence"],
                                   "stewardship": {"access": "project", "project": "ex:acc/project/p2"}}})
    doc["nodes"].append({"id": "ex:acc/project/p2", "label": "Project", "props": {"name": "project p2"}})
    doc["links"] = [e for e in doc["links"] if e["type"] != "REPORTED_IN"] + pgraph.derive_reported_in(doc)
    assert pgraph.validate(doc, head).errors == []
    m = kgbundle.export(doc, head, tmp_path / "k", "acc", created="2026-10-06T00:00:00Z", keep_less_open=True)
    names = _names(tmp_path / "k")
    acc_keys = ("scale_access", "scale_access_project", "scale_access_institutions")
    assert {k: names["other project species"].get(k) for k in acc_keys} == {
        "scale_access": "project", "scale_access_project": "ex:acc/project/p2", "scale_access_institutions": None}
    for name in ("institution species", "embargoed species"):        # an embargo in force: its contributing institutions
        assert names[name]["scale_access"] == "institution" and names[name]["scale_access_institutions"] == ["ex:acc/org/lab"]
        assert "scale_access_project" not in names[name]
    assert not any(k in names["project species"] for k in acc_keys)   # the bundle's own audience carries none
    assert names["public species"]["scale_access"] == "public" and not any(
        k in names["public species"] for k in acc_keys[1:])
    props = json.loads((tmp_path / "k/kg/schema.json").read_text())["node_types"]["ChemicalSpecies"]["properties"]
    assert props["scale_access_project"]["type"] == "string" and props["scale_access_institutions"]["type"] == "string[]"
    assert "scale_access_project" in m["export_report"]["access_warning"]
    # without keep_less_open the other project's record is withheld, as before
    kgbundle.export(doc, head, tmp_path / "w", "acc", created="2026-10-06T00:00:00Z")
    assert "other project species" not in _names(tmp_path / "w")
    v = _bundle_validator()
    if v:
        kgbundle.seal(tmp_path / "k")
        assert v.validate_bundle(tmp_path / "k").ok


def test_no_withheld_id_stays_in_a_kept_record(tmp_path, head):
    """A kept record's references to a record left out go with it (a ref, a list entry, a record_ref, a map entry keyed
    by it; a value about it is withheld in its place, under its key in a map), in the filter and in the kg-bundle,
    and are counted."""
    gone, kept = "ex:acc/species/c", "ex:acc/species/b"
    doc = _access_doc()
    ev = doc["nodes"][1]["props"]["evidence"]
    doc["nodes"].append({"id": "ex:acc/test/pub", "label": "CatalyticTest",
                         "props": {"name": "public test", "driving_forces": ["thermo"], "test_kind": "activity",
                                   "experiment_kind": "physical", "stewardship": {"access": "public"}, "evidence": ev,
                                   "results": {"sel_c": {"status": "present", "value": 40, "unit": "%", "target": gone},
                                               "sel_b": {"status": "present", "value": 60, "unit": "%", "target": kept}},
                                   "temperature": {"status": "present", "value": 250, "unit": "°C"}}})
    doc["links"] = [e for e in doc["links"] if e["type"] != "REPORTED_IN"] + pgraph.derive_reported_in(doc)
    assert pgraph.validate(doc, head).errors == []
    for name, kw in (("project", {}), ("public", {"access": {"access": "public"}})):
        m = kgbundle.export(doc, head, tmp_path / name, "acc", created="2026-10-06T00:00:00Z", **kw)
        assert m["export_report"]["access"]["withheld_less_open"]["references"] == 1, name
        for f in (tmp_path / name).rglob("*"):
            assert not f.is_file() or gone not in f.read_text(), (name, f)
        test = _names(tmp_path / name)["public test"]
        assert kept in test["results"] and json.loads(test["results"])["sel_c"] == pgraph.WITHHELD_VALUE
    # the filter, on every kind of reference (the schema's checks aside)
    plain = {"id": "ex:acc/claim/x", "label": "Claim", "props": {
        "about": gone, "about_too": [gone, kept], "only": [gone],
        "value": {"status": "present", "value": 1, "unit": "1", "variable": gone},
        "premise_refs": [{"record": gone, "path": "results.a"}, {"record": kept}],
        "by_id": {gone: "x", kept: "y"}, "note": "names ex:acc/species/c in words",
        "stewardship": {"access": "public"}}}
    doc["nodes"].append(plain)
    out = pgraph.filter_for(doc, [], "2026-10-06")
    p = next(n for n in out["nodes"] if n["id"] == "ex:acc/claim/x")["props"]
    assert p == {"about_too": [kept], "premise_refs": [{"record": kept}], "by_id": {kept: "y"},
                 "value": {"status": "not_reported", "missing_reason": "withheld"},     # a value about it, as a property
                 "note": "names ex:acc/species/c in words", "stewardship": {"access": "public"}}
    assert out["graph"]["filtered_for"].endswith("and 7 references to them removed; the header declares the view's "
                                                 "audience, public (the graph's: project)")
    # nothing withheld, nothing changed
    pub = pgraph.filter_for(doc, ["ex:acc/org/lab", P], "2026-10-06")
    assert next(n for n in pub["nodes"] if n["id"] == "ex:acc/claim/x") == plain and "references" not in pub["graph"]["filtered_for"]


def test_an_export_into_an_earlier_bundle_keeps_none_of_its_texts(tmp_path, capsys):
    """Exporting again into the same folder leaves no text (nor manifest entry) the new bundle does not ship; a file
    no earlier export wrote stops the export; the warning names the texts not shipped from this export's own list."""
    d = _access_doc()
    d["nodes"].append({"id": "ex:acc/source/review", "label": "Source",
                       "props": {"name": "review", "title": "review", "kind": "article", "year": 2021,
                                 "stewardship": {"access": "institution", "contributed_by": ["ex:acc/org/lab"]}}})
    f = tmp_path / "acc.json"
    f.write_text(json.dumps(d))
    review = tmp_path / "review.txt"
    review.write_text("an institution's own review")
    b = tmp_path / "b"
    base = ["graph", "export", str(f), "--to", "kg-bundle", "--out", str(b), "--text", f"ex:acc/source/review={review}:CC0-1.0"]
    rc, _, err = _run(base + ["--keep-less-open"], capsys)
    assert rc == 0 and (b / "text/review.txt").exists()
    rc, _, err = _run(base, capsys)                       # now withheld: its text goes from the folder too
    assert rc == 0 and "--text not shipped for ex:acc/source/review:" in err
    assert not (b / "text").exists() and "text/" not in (b / "SHA256SUMS").read_text()
    (b / "text").mkdir()
    (b / "text/notes.txt").write_text("mine")
    rc, _, err = _run(base, capsys)
    assert rc == 2 and "holds files no earlier export shipped (notes.txt)" in err and (b / "text/notes.txt").exists()


def _withheld_value_doc():
    """The public example with a project-only species and a project-only test that a public test's values name: the
    major product (results map, ref_value), the experiment its temperature was derived from (property,
    produced_by) and one of two energy yields (list, target)."""
    d = load_doc(X / "example.json")
    test = next(n for n in d["nodes"] if n["label"] == "CatalyticTest")
    meoh = "ex:exmpl/thermo/species/meoh"
    proj = {"access": "project", "project": "ex:exmpl/project/examples"}
    secret = copy.deepcopy(next(n for n in d["nodes"] if n["id"] == meoh))
    secret["id"], secret["props"]["name"], secret["props"]["stewardship"] = "ex:exmpl/thermo/species/secret", "secret species", proj
    run = copy.deepcopy(test)
    run["id"], run["props"]["name"], run["props"]["stewardship"] = "ex:exmpl/thermo/test/secret-run", "secret run", proj
    d["nodes"] += [secret, run]
    t = test["props"]
    t["results"]["major_product"] = {"status": "present", "ref_value": secret["id"]}
    t["temperature"] = {**t["temperature"], "origin": "derived", "produced_by": run["id"]}
    t["energy_yield"] = [{"status": "present", "value": 1, "unit": "g/kWh", "target": secret["id"]},
                         {"status": "present", "value": 2, "unit": "g/kWh", "target": meoh}]
    for e in pgraph.derive_reported_in(d):
        if e["source"] in (secret["id"], run["id"]):
            d["links"].append({**e, "props": {**(e.get("props") or {}), "origin": "synthetic"}})
    return d, test["id"]


def test_a_value_naming_a_withheld_record_is_withheld_whole_in_its_place(tmp_path):
    """A value is one unit: one that names a withheld record (its ref_value, produced_by or target) is never left
    without that reference alone (a present value with no value, a derived value with no experiment). It is withheld
    in its place, not_reported with missing_reason withheld: a property, a map entry under its key, a list entry at
    its position (so a query reads it as withheld, never as not curated). The filtered document still validates, and
    so does a public export of it."""
    d, tid = _withheld_value_doc()
    spec = pgraph.load_spec(pgraph.pinned(GRAPH_MANIFEST, d["graph"]["schema_version"]))
    assert pgraph.validate(d, spec).errors == []
    out = pgraph.filter_for(d, [], "2026-10-07")
    assert out["graph"]["filtered_for"].endswith("2 nodes and 1 links withheld, and 3 references to them removed")
    p = next(n for n in out["nodes"] if n["id"] == tid)["props"]
    assert p["temperature"] == {"status": "not_reported", "missing_reason": "withheld"}
    assert p["results"]["major_product"] == pgraph.WITHHELD_VALUE and "methanol_production" in p["results"]
    assert p["energy_yield"] == [pgraph.WITHHELD_VALUE,          # its target withheld with it; the next keeps its place
                                 {"status": "present", "value": 2, "unit": "g/kWh", "target": "ex:exmpl/thermo/species/meoh"}]
    assert pgraph.validate(out, spec).errors == []
    assert "secret" not in json.dumps(out)
    m = kgbundle.export(out, spec, tmp_path / "pub", "pub", created="2026-10-07T00:00:00Z", access={"access": "public"})
    m2 = kgbundle.export(d, spec, tmp_path / "pub2", "pub", created="2026-10-07T00:00:00Z", access={"access": "public"})
    assert m2["export_report"]["access"]["withheld_less_open"] == {"nodes": 2, "links": 1, "references": 3}
    for b in ("pub", "pub2"):
        for f in (tmp_path / b).rglob("*"):
            assert not f.is_file() or "secret" not in f.read_text(), f
    assert m["counts"] == m2["counts"]
    v = _bundle_validator()
    if v:
        for b in ("pub", "pub2"):
            kgbundle.seal(tmp_path / b)
            assert v.validate_bundle(tmp_path / b).ok


def _premise_doc():
    """:func:`_withheld_value_doc` with a project-only paper cited first on the public test (its evidence item named
    by the conversion's and the space velocity's evidence_ids; the second energy yield names the public one), and a
    public claim whose SUPPORTS link points into the test: at the second
    energy yield (after the one naming the secret species), at that one, at the results map's major product, at the
    temperature derived from the secret run, at the public evidence item (after the paper's) and at the conversion;
    a CONTRADICTS link points at the SUPPORTS link's last premise."""
    d, tid = _withheld_value_doc()
    test = next(n for n in d["nodes"] if n["id"] == tid)
    src = next(n for n in d["nodes"] if n["label"] == "Source")
    paper = copy.deepcopy(src)
    paper["id"], paper["props"]["title"] = "ex:exmpl/thermo/source/secret-paper", "secret paper (invented)"
    paper["props"]["stewardship"] = {"access": "project", "project": "ex:exmpl/project/examples"}
    d["nodes"].append(paper)
    t = test["props"]
    t["evidence"] = [{"id": "ev-secret", "source": paper["id"], "kind": "table", "locator": "Table 2", "note": "invented"},
                     {**t["evidence"][0], "id": "ev-public"}]
    t["conversion"]["evidence_ids"] = ["ev-secret", "ev-public"]
    t["space_velocity"]["evidence_ids"] = ["ev-secret"]
    t["energy_yield"][1]["evidence_ids"] = ["ev-public"]
    ev = [{"source": src["id"], "kind": "table", "locator": "Table 1, run 1", "note": "invented"}]
    claim = {"id": "ex:exmpl/thermo/claim/yield", "label": "Claim",
             "props": {"name": "energy yield", "claim_kind": "finding", "claim_status": "supported", "origin": "synthetic",
                       "statement": "The energy yield to methanol is 2 g/kWh (invented).", "evidence": ev}}
    d["nodes"].append(claim)
    paths = ["/energy_yield/1", "/energy_yield/0", "/results/major_product", "/temperature/value", "/evidence/1",
             "/conversion"]
    sup = {"id": "ex:exmpl/thermo/link/supports", "type": "SUPPORTS", "source": tid, "target": claim["id"],
           "props": {"origin": "synthetic", "evidence": ev, "premise_refs": [{"record": tid, "path": x} for x in paths]}}
    con = {"id": "ex:exmpl/thermo/link/contradicts", "type": "CONTRADICTS", "source": tid, "target": claim["id"],
           "props": {"origin": "synthetic", "evidence": ev,
                     "premise_refs": [{"record": sup["id"], "path": f"/premise_refs/{len(paths) - 1}"}]}}
    d["links"] += [sup, con]
    have = {(e["source"], e["target"]) for e in d["links"] if e["type"] == "REPORTED_IN"}
    d["links"] += [{**e, "props": {**(e.get("props") or {}), "origin": "synthetic"}}
                   for e in pgraph.derive_reported_in(d) if (e["source"], e["target"]) not in have]
    return d, tid, sup["id"], con["id"]


def test_a_record_ref_into_a_kept_record_follows_what_the_filter_removed(tmp_path):
    """A record_ref path into a kept record never names another value than it did: after an evidence item (or a
    ref-list entry, such as another link's premise_refs) is removed, the paths behind it move up; a value withheld
    stays in its place, so nothing behind it moves; a path to a part removed or withheld, or into one, goes with its
    record_ref and is counted, as a reference to a withheld record is. A value's evidence_ids no longer name an
    evidence item removed, and a value stated only by removed evidence is withheld and counted (it does not stand on
    the evidence left), and so is a value that names no evidence_ids on a record that lost evidence (nothing says it
    rests on the evidence left); a kept record that lost evidence is counted too. The filtered document and a public
    export of the graph both validate."""
    from scale.pgraph_science import _pointer
    d, tid, sup, con = _premise_doc()
    spec = pgraph.load_spec(pgraph.pinned(GRAPH_MANIFEST, d["graph"]["schema_version"]))
    assert pgraph.validate(d, spec).errors == []
    props = {r["id"]: r["props"] for r in d["nodes"] + d["links"]}
    named = {x["path"]: _pointer(props[tid], x["path"])[1] for x in props[sup]["premise_refs"]}
    out = pgraph.filter_for(d, [], "2026-10-07")
    assert pgraph.validate(out, spec).errors == []
    kept = {r["id"]: r["props"] for r in out["nodes"] + out["links"]}
    refs = kept[sup]["premise_refs"]
    assert [x["path"] for x in refs] == ["/energy_yield/1", "/evidence/0", "/conversion"]
    for x, was in zip(refs, ("/energy_yield/1", "/evidence/1", "/conversion")):
        now = _pointer(kept[tid], x["path"])[1]
        assert now == {k: v for k, v in named[was].items() if k != "evidence_ids"} | (
            {"evidence_ids": ["ev-public"]} if "evidence_ids" in named[was] else {}), was
    assert kept[con]["premise_refs"] == [{"record": sup, "path": "/premise_refs/2"}]     # follows the SUPPORTS list
    assert kept[tid]["conversion"]["evidence_ids"] == ["ev-public"]
    assert kept[tid]["space_velocity"] == pgraph.WITHHELD_VALUE          # stated by the secret paper alone
    assert kept[tid]["energy_yield"][0] == pgraph.WITHHELD_VALUE and kept[tid]["results"]["major_product"] == pgraph.WITHHELD_VALUE
    # no evidence_ids on a record that lost evidence: the pressure and the methanol production may rest on the
    # secret paper alone, so they are withheld in their place too (fail closed)
    assert kept[tid]["pressure"] == pgraph.WITHHELD_VALUE and kept[tid]["results"]["methanol_production"] == pgraph.WITHHELD_VALUE
    # withheld: 3 nodes, the secret paper's REPORTED_IN and the run's; withheld in place: the yield entry, the map
    # entries, the temperature, the space velocity and the pressure; removed: the three record_refs to them; the test
    # lost the paper's evidence item
    assert out["graph"]["filtered_for"].endswith("3 nodes and 2 links withheld, and 9 references to them removed; "
                                                 "1 kept records lost evidence citing them")
    assert "secret" not in json.dumps(out)
    # the same through the export's own restriction (a public bundle of the project graph)
    pub, withheld = pgraph.restrict_to(d, {"access": "public"}, "2026-10-07")
    assert withheld == {"nodes": 3, "links": 2, "references": 9, "evidence_cut": 1} and pgraph.validate(pub, spec).errors == []
    assert [x["path"] for x in next(e for e in pub["links"] if e["id"] == sup)["props"]["premise_refs"]] == \
        ["/energy_yield/1", "/evidence/0", "/conversion"]
    m = kgbundle.export(d, spec, tmp_path / "pub", "pub", created="2026-10-07T00:00:00Z", access={"access": "public"})
    assert m["export_report"]["access"]["withheld_less_open"] == {"nodes": 3, "links": 2, "references": 9, "evidence_cut": 1}
    # nothing withheld: every path as it was
    same = pgraph.filter_for(d, ["ex:exmpl/project/examples"], "2026-10-07")
    assert [e for e in same["links"] if e["id"] in (sup, con)] == [e for e in d["links"] if e["id"] in (sup, con)]


def _two_source_doc():
    """The public example whose test also cites a project-only paper (``ev-secret``) that alone states its
    temperature, its results map's only entry and one of two energy yields (by their evidence_ids); its conversion
    names no evidence_ids. A public claim cites the project paper only."""
    d = load_doc(X / "example.json")
    test = next(n for n in d["nodes"] if n["label"] == "CatalyticTest")
    src = next(n for n in d["nodes"] if n["label"] == "Source")
    meoh = "ex:exmpl/thermo/species/meoh"
    paper = copy.deepcopy(src)
    paper["id"], paper["props"]["title"] = "ex:exmpl/thermo/source/secret-paper", "secret paper (invented)"
    paper["props"]["stewardship"] = {"access": "project", "project": "ex:exmpl/project/examples"}
    d["nodes"].append(paper)
    t = test["props"]
    t["evidence"] = [{**t["evidence"][0], "id": "ev-public"},
                     {"id": "ev-secret", "source": paper["id"], "kind": "table", "locator": "Table 2", "note": "invented"}]
    t["temperature"]["evidence_ids"] = ["ev-secret"]
    t["results"]["methanol_production"].update(target=meoh, evidence_ids=["ev-secret"])
    t["energy_yield"] = [{"status": "present", "value": 1, "unit": "g/kWh", "target": meoh, "evidence_ids": ["ev-secret"]},
                         {"status": "present", "value": 2, "unit": "g/kWh", "target": meoh, "evidence_ids": ["ev-public"]}]
    d["nodes"].append({"id": "ex:exmpl/thermo/claim/rate", "label": "Claim", "props": {
        "name": "rate", "claim_kind": "finding", "claim_status": "supported", "origin": "synthetic",
        "statement": "Methanol forms at 52 g/h (invented).",
        "evidence": [{"source": paper["id"], "kind": "table", "locator": "Table 2", "note": "invented"}]}})
    have = {(e["source"], e["target"]) for e in d["links"] if e["type"] == "REPORTED_IN"}
    d["links"] += [{**e, "props": {**(e.get("props") or {}), "origin": "synthetic"}}
                   for e in pgraph.derive_reported_in(d) if (e["source"], e["target"]) not in have]
    return d, test["id"], meoh


def test_a_value_stated_only_by_a_withheld_source_keeps_its_place_and_lost_evidence_is_counted(tmp_path):
    """A map or list entry stated only by a withheld source (its evidence_ids) is withheld under its key or at its
    position, with the target it names (a map left with no other entry stays), so a query never reads it as not
    curated. A value with no evidence_ids on a record that lost evidence cannot be traced to the evidence left (it may
    rest on the withheld source alone): it is withheld in its place too, never left cited to the public source; a
    value whose evidence_ids name the evidence left stays. The kept records that lost evidence are counted
    (filtered_for, the export's withheld_less_open.evidence_cut)."""
    d, tid, meoh = _two_source_doc()
    spec = pgraph.load_spec(pgraph.pinned(GRAPH_MANIFEST, d["graph"]["schema_version"]))
    assert pgraph.validate(d, spec).errors == []
    before = next(n for n in d["nodes"] if n["id"] == tid)["props"]
    out = pgraph.filter_for(d, [], "2026-10-07")
    assert pgraph.validate(out, spec).errors == []
    p = next(n for n in out["nodes"] if n["id"] == tid)["props"]
    held = {**pgraph.WITHHELD_VALUE, "target": meoh}
    assert p["results"] == {"methanol_production": held}
    assert p["energy_yield"] == [held, before["energy_yield"][1]]
    assert p["temperature"] == pgraph.WITHHELD_VALUE
    # no evidence_ids: the conversion (and the pressure, the space velocity) may rest on the secret paper alone
    assert p["conversion"] == {**pgraph.WITHHELD_VALUE, "target": before["conversion"]["target"]}
    assert p["pressure"] == p["space_velocity"] == pgraph.WITHHELD_VALUE
    assert [e["id"] for e in p["evidence"]] == ["ev-public"]
    claim = next(n for n in out["nodes"] if n["id"] == "ex:exmpl/thermo/claim/rate")["props"]
    assert "evidence" not in claim and claim["statement"]
    assert out["graph"]["filtered_for"].endswith("and 6 references to them removed; 2 kept records lost evidence citing them")
    assert "secret" not in json.dumps(out)
    _, withheld = pgraph.restrict_to(d, {"access": "public"}, "2026-10-07")
    assert withheld["evidence_cut"] == 2 and withheld["references"] == 6
    m = kgbundle.export(d, spec, tmp_path / "pub", "pub", created="2026-10-07T00:00:00Z", access={"access": "public"})
    assert m["export_report"]["access"]["withheld_less_open"]["evidence_cut"] == 2
    for f in (tmp_path / "pub").rglob("*"):
        assert not f.is_file() or "secret" not in f.read_text(), f


def test_a_filtered_value_is_never_cited_to_a_source_that_may_not_state_it(tmp_path):
    """A public test cites a public paper (its conditions) and a project-only report (its conversion), and its values
    name no evidence_ids, as the curated corpora's do. The public view withholds the report: nothing then ties the
    conversion to the paper, so it is withheld in its place, and a query of the view reads it as withheld, never as a
    value with the paper as its evidence. A value whose evidence_ids name the paper stays, cited to it."""
    d = load_doc(X / "example.json")
    test = next(n for n in d["nodes"] if n["label"] == "CatalyticTest")
    src = next(n for n in d["nodes"] if n["label"] == "Source")
    report = copy.deepcopy(src)
    report["id"], report["props"]["title"] = "ex:exmpl/thermo/source/secret-report", "secret report (invented)"
    report["props"]["stewardship"] = {"access": "project", "project": "ex:exmpl/project/examples"}
    d["nodes"].append(report)
    t = test["props"]
    t["evidence"] = [{**t["evidence"][0], "id": "ev-public"},
                     {"id": "ev-secret", "source": report["id"], "kind": "table", "locator": "Table 2", "note": "invented"}]
    have = {(e["source"], e["target"]) for e in d["links"] if e["type"] == "REPORTED_IN"}
    d["links"] += [{**e, "props": {**(e.get("props") or {}), "origin": "synthetic"}}
                   for e in pgraph.derive_reported_in(d) if (e["source"], e["target"]) not in have]
    spec = pgraph.load_spec(pgraph.pinned(GRAPH_MANIFEST, d["graph"]["schema_version"]))
    assert pgraph.validate(d, spec).errors == []
    out = pgraph.filter_for(d, [], "2026-10-07")
    assert pgraph.validate(out, spec).errors == [] and "secret" not in json.dumps(out)
    p = next(n for n in out["nodes"] if n["id"] == test["id"])["props"]
    assert p["conversion"] == {**pgraph.WITHHELD_VALUE, "target": t["conversion"]["target"]}
    assert [e["id"] for e in p["evidence"]] == ["ev-public"]
    plan = {"match": {"label": "CatalyticTest", "as": "t"}, "return": ["t.conversion"], "evidence": True}
    res = pgraph_query.run(out, spec, plan)
    assert res["rows"][0]["values"]["t.conversion"]["missing_reason"] == "withheld"
    assert [x["reason"] for x in res["missing_context"]] == ["withheld"]
    # traced to the paper by evidence_ids: kept, and still cited to it
    t["conversion"]["evidence_ids"] = ["ev-public"]
    out = pgraph.filter_for(d, [], "2026-10-07")
    p = next(n for n in out["nodes"] if n["id"] == test["id"])["props"]
    assert p["conversion"] == t["conversion"] and p["pressure"] == pgraph.WITHHELD_VALUE
    # nothing withheld (the project's own view): every value as it was
    same = pgraph.filter_for(d, ["ex:exmpl/project/examples"], "2026-10-07")
    assert next(n for n in same["nodes"] if n["id"] == test["id"])["props"] == t
    # evidence_ids that name none of the evidence left, a withheld item or one the record does not hold: withheld
    for ids in (["ev-secret", "ev-missing"], ["ev-missing"]):
        t["conversion"]["evidence_ids"] = ids
        p = next(n for n in pgraph.filter_for(d, [], "2026-10-07")["nodes"] if n["id"] == test["id"])["props"]
        assert p["conversion"] == {**pgraph.WITHHELD_VALUE, "target": t["conversion"]["target"]}, ids
    t["conversion"]["evidence_ids"] = ["ev-secret", "ev-public"]       # one of them left: kept, cited to it alone
    p = next(n for n in pgraph.filter_for(d, [], "2026-10-07")["nodes"] if n["id"] == test["id"])["props"]
    assert p["conversion"] == {**t["conversion"], "evidence_ids": ["ev-public"]}


def test_a_value_withheld_by_the_filter_is_not_the_source_being_silent(tmp_path, capsys):
    """A query on a filtered document reads a withheld value as withheld (and a value not extractable as such), not as
    not_reported: the answer is missing context, and a gap report from it asks for no source review."""
    from scale.gaps import gaps_from_query
    d, tid = _withheld_value_doc()
    spec = pgraph.load_spec(pgraph.pinned(GRAPH_MANIFEST, d["graph"]["schema_version"]))
    out = pgraph.filter_for(d, [], "2026-10-07")
    plan = {"question": "tests at 400 °C or below",
            "match": {"label": "CatalyticTest", "as": "t",
                      "where": [{"prop": "temperature", "op": "le", "value": 400, "unit": "°C"}]}}
    res = pgraph_query.run(out, spec, plan)
    assert res["status"] == "missing_context" and [x["reason"] for x in res["excluded"]] == ["withheld"]
    assert gaps_from_query(res) == []
    assert pgraph_query.absent_reason({"status": "not_reported", "missing_reason": "not_extractable"}) == "not_extractable"
    assert pgraph_query.absent_reason({"status": "not_reported", "missing_reason": "not_stated_in_source"}) == "not_reported"
    f = tmp_path / "res.json"
    f.write_text(json.dumps(res))
    assert main(["--repo", str(REPO), "gap", "from-query", str(f), "--out-dir", str(tmp_path / "gaps")]) in (0, None)
    assert json.loads(capsys.readouterr().out)["gaps"] == [] and not list((tmp_path / "gaps").glob("*.json"))


def test_an_export_for_a_viewer_declares_that_viewers_audience(tmp_path, capsys):
    """--as names the bundle's audience: one project, or institutions. The bundle declares it (not the graph's own),
    holds that audience's records and warns for it; a person, several projects, a mix, an id the graph does not hold or
    --as with --public is refused before anything is written."""
    d = _access_doc()
    p2 = "ex:acc/project/p2"
    d["nodes"].append({"id": p2, "label": "Project", "props": {"name": "project p2"}})
    d["nodes"].append({"id": "ex:acc/species/e", "label": "ChemicalSpecies",
                       "props": {"name": "p2 species", "evidence": d["nodes"][1]["props"]["evidence"],
                                 "stewardship": {"access": "project", "project": p2}}})
    d["nodes"].append({"id": "ex:acc/person/x", "label": "Person", "props": {"name": "x"}})
    d["links"] = [e for e in d["links"] if e["type"] != "REPORTED_IN"] + pgraph.derive_reported_in(d)
    f = tmp_path / "acc.json"
    f.write_text(json.dumps(d))
    base = ["graph", "export", str(f), "--to", "kg-bundle", "--created", "2026-10-06T00:00:00Z", "--date", "2026-10-06"]
    rc, _, err = _run(base + ["--out", str(tmp_path / "p2"), "--as", p2], capsys)
    m = json.loads((tmp_path / "p2/bundle.json").read_text())
    assert rc == 0 and m["scale_header"]["stewardship"] == {"access": "project", "project": p2, "licence": "CC-BY-4.0"}
    assert set(_names(tmp_path / "p2")) == {"p2 species", "public species"}        # the graph's own project's: withheld
    assert "scale_access" not in _names(tmp_path / "p2")["p2 species"]              # the bundle's own audience
    assert f"access 'project' ({p2})" in err
    assert "withheld_less_open" not in m["export_report"]["access"]                  # the filter left nothing less open
    rc, _, err = _run(base + ["--out", str(tmp_path / "lab"), "--as", "ex:acc/org/lab"], capsys)
    m = json.loads((tmp_path / "lab/bundle.json").read_text())
    assert rc == 0 and m["scale_header"]["stewardship"] == {"access": "institution", "contributed_by": ["ex:acc/org/lab"],
                                                            "licence": "CC-BY-4.0"}
    assert set(_names(tmp_path / "lab")) == {"institution species", "embargoed species", "public species"}
    assert "ex:acc/org/lab" in err
    for bad, msg in ((["--as", "ex:acc/person/x"], "Person"), (["--as", P, "--as", p2], "name one project"),
                     (["--as", P, "--as", "ex:acc/org/lab"], "name one project"), (["--as", "ex:acc/nope"], "not in the graph"),
                     (["--as", P, "--public"], "not both")):
        rc, _, err = _run(base + ["--out", str(tmp_path / "x"), *bad], capsys)
        assert rc == 2 and msg in err and not (tmp_path / "x").exists(), bad


def test_records_kept_less_open_than_the_audience_are_counted_in_the_header(tmp_path, head):
    """keep_less_open on a public graph: the header still declares the audience (public) but says what part of it may
    not see (access_at_export.less_open_kept, by level), and the warning sends each such record only to its own
    audience and the bundle only to those who may see all of it."""
    d = _access_doc()
    d["graph"]["stewardship"] = {"access": "public", "licence": "CC-BY-4.0"}
    d["nodes"][1]["props"]["stewardship"] = {"access": "project", "project": P}
    m = kgbundle.export(d, head, tmp_path / "k", "acc", created="2026-10-06T00:00:00Z", keep_less_open=True)
    h, acc = m["scale_header"], m["export_report"]["access"]
    assert h["stewardship"] == {"access": "public", "licence": "CC-BY-4.0"}
    assert h["access_at_export"] == {"level": "public", "date": "2026-10-06",
                                     "less_open_kept": {"institution": 2, "project": 1}}
    assert acc["less_open_kept"] == {"institution": 2, "project": 1}
    w = m["export_report"]["access_warning"]
    assert w.startswith("not for all of its audience") and "access 'public'" in w and "only within its own audience" in w
    assert "only within that audience" not in w
    # without it, nothing less open is held and the public bundle does not warn
    m = kgbundle.export(d, head, tmp_path / "w", "acc", created="2026-10-06T00:00:00Z")
    assert "less_open_kept" not in m["scale_header"]["access_at_export"] and "access_warning" not in m["export_report"]
    # a project bundle that kept nothing less open (none to keep) says only that it is not public
    d["nodes"] = [n for n in d["nodes"] if (n["props"].get("stewardship") or {}).get("access") in (None, "public", "project")]
    d["links"] = pgraph.derive_reported_in(d)
    d["graph"]["stewardship"] = {"access": "project", "project": P, "licence": "CC-BY-4.0"}
    m = kgbundle.export(d, head, tmp_path / "p", "acc", created="2026-10-06T00:00:00Z", keep_less_open=True)
    assert m["export_report"]["access"]["less_open_kept"] is True and "less_open_kept" not in m["scale_header"]["access_at_export"]
    assert m["export_report"]["access_warning"].startswith("not public")


def test_an_earlier_manifest_that_names_anything_but_a_file_of_text_stops_the_export(tmp_path, capsys):
    """Only plain file names of out/text are removed: a manifest naming an absolute path, a path that climbs out, a
    directory or a link stops the export before anything is removed or written, and the files it names stay."""
    f = tmp_path / "acc.json"
    f.write_text(json.dumps(_access_doc()))
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "important.txt").write_text("keep")
    out = tmp_path / "b"
    (out / "text" / "sub").mkdir(parents=True)
    (out / "text" / "link.txt").symlink_to(victim / "important.txt")
    for named in (str(victim / "important.txt"), "../../victim/important.txt", "sub", "link.txt", ".."):
        (out / "text" / "_manifest.json").write_text(json.dumps({"files": {"a": {"file": named},
                                                                           "b": {"file": "link.txt"}}}))
        rc, _, err = _run(["graph", "export", str(f), "--to", "kg-bundle", "--out", str(out)], capsys)
        assert rc == 2 and "not a file of" in err and "export into an empty folder" in err, named
        assert (victim / "important.txt").read_text() == "keep" and (out / "text" / "link.txt").is_symlink()
        assert not (out / "bundle.json").exists() and not (out / "kg").exists()
    (out / "text" / "_manifest.json").write_text(json.dumps({"files": ["not a map"]}))
    rc, _, err = _run(["graph", "export", str(f), "--to", "kg-bundle", "--out", str(out)], capsys)
    assert rc == 2 and "is not a bundle's text manifest" in err
    linked = tmp_path / "c"
    linked.mkdir()
    (linked / "text").symlink_to(victim)
    rc, _, err = _run(["graph", "export", str(f), "--to", "kg-bundle", "--out", str(linked)], capsys)
    assert rc == 2 and "is a link" in err and (victim / "important.txt").exists()


def test_a_view_declares_its_audience_and_every_record_keeps_its_access(tmp_path, head):
    """When the viewer may not see the graph's header stewardship, a view declares the viewer as its audience in its
    header (the public, one project, institutions), as a kg-bundle does, after writing on each kept record the
    audience keys it inherited, so every record's access in the view is what it was (an embargo whose access after
    it came from the header included). A viewer who may see the header, or one no stewardship names (a person),
    leaves the header and the records as they were."""
    day = "2026-10-07"
    lab = "ex:acc/org/lab"

    def access(doc, rid, on=day):
        r = next(x for x in doc["nodes"] + doc["links"] if x["id"] == rid)
        return pgraph.access_key(pgraph.effective_stewardship(doc, r), on)
    d = _access_doc()
    pub = pgraph.filter_for(d, [], day)
    assert pub["graph"]["stewardship"] == {"access": "public", "project": P, "contributed_by": [lab], "licence": "CC-BY-4.0"}
    assert pub["graph"]["filtered_for"].endswith("; the header declares the view's audience, public (the graph's: project)")
    assert {n["id"] for n in pub["nodes"]} == {"ex:acc/source/paper", "ex:acc/species/b"}
    assert all(access(pub, r["id"]) == access(d, r["id"]) == ("public", None) for r in pub["nodes"] + pub["links"])
    assert pgraph.filtered_for_public(pub) and not pgraph.filtered_for_public(d)
    # the header's embargo gives a record its access after its own embargo: written on the record, so it stays public
    e = {"id": "ex:acc/species/e", "label": "ChemicalSpecies",
         "props": {"name": "once embargoed species", "stewardship": {"access": "embargoed", "embargo_until": "2020-06"}}}
    d2 = _access_doc()
    d2["nodes"].append(e)
    d2["graph"]["stewardship"].update(access="embargoed", embargo_until="2099-01-01", access_after_embargo="public")
    pub2 = pgraph.filter_for(d2, [], day)
    assert pub2["graph"]["stewardship"] == pub["graph"]["stewardship"]
    kept = next(n for n in pub2["nodes"] if n["id"] == e["id"])
    assert kept["props"]["stewardship"] == {"access": "embargoed", "embargo_until": "2020-06", "access_after_embargo": "public"}
    for on in (day, "2020-06-30", "2020-07-01"):        # in force to the end of its month, then public, as before
        assert access(pub2, e["id"], on) == access(d2, e["id"], on), on
    assert access(pub2, e["id"], "2020-06-30")[0] == "institution" and access(pub2, e["id"], "2020-07-01")[0] == "public"
    # a project viewer of an institution's graph: the header names the project
    d3 = _access_doc()
    d3["graph"]["stewardship"]["access"] = "institution"
    for_p = pgraph.filter_for(d3, [P], day)
    assert for_p["graph"]["stewardship"] == {"access": "project", "project": P, "contributed_by": [lab], "licence": "CC-BY-4.0"}
    assert all(access(for_p, r["id"]) == access(d3, r["id"]) for r in for_p["nodes"] + for_p["links"])
    # the project's own view (it may see the header), and a person no stewardship names: header and records as they were
    same = pgraph.filter_for(d, [P], day)
    assert same["graph"]["stewardship"] == d["graph"]["stewardship"] and "header" not in same["graph"]["filtered_for"]
    assert all(n == next(x for x in d["nodes"] if x["id"] == n["id"]) for n in same["nodes"])
    d4 = _access_doc()
    d4["nodes"].append({"id": "ex:acc/person/a", "label": "Person", "props": {"name": "a person"}})
    person = pgraph.filter_for(d4, ["ex:acc/person/a"], day)
    assert person["graph"]["stewardship"] == d4["graph"]["stewardship"]
    assert pgraph.view_audience(d, []) == {"access": "public"} and pgraph.view_audience(d, [P]) == {"access": "project", "project": P}
    assert pgraph.view_audience(d4, ["ex:acc/person/a"]) is None
    # a public bundle made from the view (the export's --public) holds what it held when the view kept the header
    kept_header = {**pub, "graph": {**pub["graph"], "stewardship": d["graph"]["stewardship"]}}
    a = kgbundle.export(pub, head, tmp_path / "a", "acc", created="2026-10-07T00:00:00Z", access={"access": "public"})
    b = kgbundle.export(kept_header, head, tmp_path / "b", "acc", created="2026-10-07T00:00:00Z", access={"access": "public"})
    assert (tmp_path / "a/kg/graph.json").read_bytes() == (tmp_path / "b/kg/graph.json").read_bytes()
    assert a["scale_header"]["stewardship"] == b["scale_header"]["stewardship"] == {"access": "public", "licence": "CC-BY-4.0"}


def test_an_embargo_stated_to_the_year_or_month_holds_to_its_end_and_a_malformed_one_never_lapses(head):
    """embargo_until at the kernel's precisions: a year holds to 31 December, a month to its last day; a date that is
    not one (a month 13, a number) never lapses, so the record stays institution. The filter, the export's
    restriction and the access level read it alike."""
    for until, last, first in (("2027", "2027-12-31", "2028-01-01"), ("2027-02", "2027-02-28", "2027-03-01"),
                               ("2028-02", "2028-02-29", "2028-03-01"), ("2027-06-30", "2027-06-30", "2027-07-01")):
        d = _access_doc()
        r = next(n for n in d["nodes"] if n["id"] == "ex:acc/species/d")
        r["props"]["stewardship"]["embargo_until"] = until
        st = pgraph.effective_stewardship(d, r)
        assert pgraph.openness(st, last) == "institution" and pgraph.openness(st, first) == "public", until
        assert r["id"] not in {n["id"] for n in pgraph.filter_for(d, [], last)["nodes"]}, until
        assert r["id"] in {n["id"] for n in pgraph.filter_for(d, [], first)["nodes"]}, until
        assert r["id"] not in {n["id"] for n in pgraph.restrict_to(d, {"access": "public"}, last)[0]["nodes"]}, until
    for bad in ("2027-13", "2027-02-30", 2027, "soon"):
        d = _access_doc()
        r = next(n for n in d["nodes"] if n["id"] == "ex:acc/species/d")
        r["props"]["stewardship"]["embargo_until"] = bad
        assert pgraph.openness(pgraph.effective_stewardship(d, r), "2100-01-01") == "institution", bad
        assert r["id"] not in {n["id"] for n in pgraph.filter_for(d, [], "2100-01-01")["nodes"]}, bad
    # a day that is not a date lapses no embargo either
    st = {"access": "embargoed", "embargo_until": "2020-01-01", "access_after_embargo": "public"}
    assert pgraph.openness(st, "2026-10-07") == "public" and pgraph.openness(st, "zzz") == "institution"


def test_a_malformed_stewardship_reads_as_institution_and_stops_nothing(head):
    """A stewardship that is not an object (the validator reports it) is read as institution, failing closed: the
    record is withheld from the public, its level is institution, and the filter and the export run on."""
    for bad in ("public", ["public"], 5):
        d = _access_doc()
        r = next(n for n in d["nodes"] if n["id"] == "ex:acc/species/b")
        r["props"]["stewardship"] = bad
        assert pgraph.openness(pgraph.effective_stewardship(d, r), "2026-10-07") == "institution", bad
        assert r["id"] not in {n["id"] for n in pgraph.filter_for(d, [], "2026-10-07")["nodes"]}, bad
        assert r["id"] not in {n["id"] for n in pgraph.restrict_to(d, {"access": "public"}, "2026-10-07")[0]["nodes"]}
        d["graph"]["stewardship"] = bad                 # the header too: a record without its own reads institution
        a = next(n for n in d["nodes"] if n["id"] == "ex:acc/species/a")
        assert pgraph.openness(pgraph.effective_stewardship(d, a), "2026-10-07") == "institution", bad
        assert {n["id"] for n in pgraph.filter_for(d, [], "2026-10-07")["nodes"]} == {"ex:acc/source/paper"}, bad
        assert any("stewardship" in e["message"] for e in pgraph.validate(d, head).errors), bad   # reported, not raised


def test_a_malformed_header_stewardship_exports_as_institution(tmp_path, capsys, head):
    """The kg-bundle export reads the graph's header stewardship as every other reader does (pgraph.stewardship_of): one
    that is not an object is institution, failing closed, and a project or contributed_by that is not an id names
    none. The bundle then declares institution (or a project it cannot name) and warns; with --public it holds only
    what is public. Nothing raises, through kgbundle.export, `scale graph export` or the validator, which reports it."""
    day = "2026-10-07T00:00:00Z"
    for bad in ("public", ["public"], 5):
        d = _access_doc()
        d["graph"]["stewardship"] = bad
        m = kgbundle.export(copy.deepcopy(d), head, tmp_path / "d", "acc", created=day)
        assert m["scale_header"]["stewardship"] == {"access": "institution"}, bad
        assert m["export_report"]["access"]["bundle"] == "institution" and "no institution named" in m["export_report"]["access_warning"]
        names = _names(tmp_path / "d")      # the lab's record is not for an institution bundle that names no institution
        assert {"project species", "public species"} <= set(names) and "institution species" not in names, bad
        m = kgbundle.export(copy.deepcopy(d), head, tmp_path / "p", "acc", created=day, access={"access": "public"})
        assert m["scale_header"]["stewardship"] == {"access": "public"} and "access_warning" not in m["export_report"]
        assert set(_names(tmp_path / "p")) == {"public species"}, bad       # a record that inherits the header is not public
        m = kgbundle.export(copy.deepcopy(d), head, tmp_path / "k", "acc", created=day, keep_less_open=True)
        assert m["scale_header"]["access_at_export"]["level"] == "institution" and m["export_report"]["access_warning"]
        f = tmp_path / "bad.json"
        f.write_text(json.dumps(d))
        for extra in ([], ["--public"], ["--as", P]):
            rc, out, err = _run(["graph", "export", str(f), "--to", "kg-bundle", "--out", str(tmp_path / "cli"),
                                 "--created", day, *extra], capsys)
            assert rc == 0 and json.loads(out)["counts"] and "Traceback" not in err, (bad, extra)
    # an object whose project or institutions are not ids: the audience names none, and nothing raises
    for bad, level, header in (({"access": "project", "project": ["p"]}, "project", {"access": "project"}),
                               ({"access": "institution", "contributed_by": [5, None]}, "institution", {"access": "institution"}),
                               ({"access": "institution", "contributed_by": "ex:acc/org/lab"}, "institution", {"access": "institution"}),
                               ({"access": ["public"]}, "institution", {"access": "institution"})):
        d = _access_doc()
        d["graph"]["stewardship"] = bad
        assert any("stewardship." in e["message"] for e in pgraph.validate(d, head).errors), bad   # reported, not raised
        m = kgbundle.export(copy.deepcopy(d), head, tmp_path / "o", "acc", created=day)
        assert m["scale_header"]["stewardship"] == header and m["export_report"]["access"]["bundle"] == level, bad
        assert f"access {level!r} (no {level} named)" in m["export_report"]["access_warning"], bad
        assert "institution species" not in _names(tmp_path / "o"), bad
        restricted, _ = pgraph.restrict_to(d, bad, day[:10])
        assert "ex:acc/species/c" not in {n["id"] for n in restricted["nodes"]}, bad
        m = kgbundle.export(copy.deepcopy(d), head, tmp_path / "op", "acc", created=day, access={"access": "public"})
        assert set(_names(tmp_path / "op")) == {"public species"}, bad
    # a header that states no access (none at all, an empty one, an access null or ""): the bundle states the
    # institution SCALE reads it as, never leaves it to the host to know how an absence reads; and an embargo that
    # names no access after it states institution for that too
    for bad, header in ((None, {"access": "institution"}), ({}, {"access": "institution"}),
                        ({"access": None}, {"access": "institution"}), ({"access": ""}, {"access": "institution"}),
                        ({"access": [], "licence": "CC-BY-4.0"}, {"access": "institution", "licence": "CC-BY-4.0"}),
                        ({"project": P}, {"access": "institution", "project": P}),
                        ({"access": "embargoed", "embargo_until": "2099"},
                         {"access": "embargoed", "embargo_until": "2099", "access_after_embargo": "institution"}),
                        ({"access": "embargoed", "embargo_until": "2099", "access_after_embargo": ""},
                         {"access": "embargoed", "embargo_until": "2099", "access_after_embargo": "institution"})):
        d = _access_doc()
        if bad is None:
            del d["graph"]["stewardship"]
        else:
            d["graph"]["stewardship"] = bad
        for keep in (False, True):
            m = kgbundle.export(copy.deepcopy(d), head, tmp_path / "n", "acc", created=day, keep_less_open=keep)
            assert m["scale_header"]["stewardship"] == header, (bad, keep)
            assert m["scale_header"]["access_at_export"]["level"] == "institution", (bad, keep)
            assert m["export_report"]["access"]["bundle"] == "institution" and m["export_report"]["access_warning"], bad
            on_disk = json.loads((tmp_path / "n/bundle.json").read_text())["scale_header"]["stewardship"]
            assert on_disk == header, (bad, keep)
    # a header that states its access keeps it as stated
    m = kgbundle.export(_access_doc(), head, tmp_path / "s", "acc", created=day)
    assert m["scale_header"]["stewardship"]["access"] == "project" and "access_after_embargo" not in m["scale_header"]["stewardship"]
