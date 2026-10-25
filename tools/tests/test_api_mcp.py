"""The agent tools over scale-catal documents: one tool set (TOOLS) behind Python, `scale call`, HTTP and
MCP; zero configuration (a working directory, no lock, no upgrades); errors as data; human actions
never exposed."""

import json
import shutil
import subprocess
import sys

import pytest

from conftest import DRIVING_FORCE_EXAMPLES, HEAD_VERSION, REPO, RUN_SCALE
from scale.api import HUMAN_ONLY, TOOLS, ScaleToolkit
from scale.mcp_server import MCPServer
from scale.util import load_doc, load_yaml, write_canonical

TOOL_NAMES = {"scale_status", "scale_domains", "scale_describe", "scale_template", "scale_validate", "scale_query",
              "scale_search", "scale_migrate", "scale_example", "scale_skills", "scale_source_start", "scale_source_check",
              "scale_source_finish", "scale_trace_ai", "scale_recipe"}
SKILLS = {"index-sources", "fetch-corpus", "curate-corpus", "query-graph", "map-coverage", "scan-conflicts",
          "export-graph", "evolve-schema", "triage-feedback"}                 # the head's skills (scale-release.yaml)


@pytest.fixture()
def tk(tmp_path):
    return ScaleToolkit(workspace=tmp_path / "ws", repo=REPO)


def test_the_tool_set_is_graph_native_and_vendor_neutral(tk):
    names = {t["name"] for t in TOOLS}
    assert names == TOOL_NAMES
    assert {t["name"] for t in tk.schemas()} == names
    assert all(set(t) == {"name", "description", "parameters"} for t in tk.schemas())
    spec = tk.openapi()
    assert spec["openapi"] == "3.1.0" and {f"/tools/{n}" for n in names} <= set(spec["paths"])
    # no human-only actions are exposed to agents
    assert not names & {"scale_approve", "scale_release_build", "scale_apply", "scale_issue_submit", "scale_upgrade_apply"}
    jsonschema = pytest.importorskip("jsonschema")
    for t in TOOLS:
        jsonschema.Draft202012Validator.check_schema(t["input_schema"])


def test_status_is_zero_config_and_writes_nothing(tk):
    st = tk.call("scale_status")
    from scale.releases import list_releases
    rels = list_releases(REPO)                                              # none before the first is built
    assert st["latest_release"] == (rels[-1] if rels else None) and "legacy_archive" not in st
    # one version for the kernel and the catalysis domain together
    assert st["schema_version"] == HEAD_VERSION and st["kernel"] == {"file": "core/graph/kernel.yaml", "schema_version": HEAD_VERSION}
    cat = next(d for d in st["domains"] if d["domain"] == "catalysis")
    from scale import pgraph
    frozen = [v for v, _ in pgraph.spec_versions(REPO / "domain/graph/scale-catal.yaml")[:-1]]          # none at 0.1.0
    assert cat["version"] == cat["schema"]["version"] == HEAD_VERSION and cat["schema"]["frozen_versions"] == frozen
    assert st["documents"] == [] and not tk.workspace.exists()          # nothing written until a tool writes
    assert set(st["skills"]) == SKILLS
    assert "functioning" in st["capabilities"] and st["human_only_actions"] == HUMAN_ONLY
    assert st["updates"]["remote"]["checked"] is False                   # tests never contact the remote


def test_domains_offer_their_competency_plans(tk):
    res = tk.call("scale_domains")
    cat = next(d for d in res["domains"] if d["domain"] == "catalysis")
    assert {"CQ-01", "CQ-02", "CQ-03"} <= set(cat["example_plans"])
    assert "electro" in res["examples"] and "a-designed-series" in res["examples"]
    assert "example" in res["examples"]                                # the worked example is synthetic and public


def test_only_public_synthetic_documents_are_served_as_examples(tmp_path):
    """Project data and research data are never served as an example, even when they lie among the examples."""
    from conftest import as_project_data
    repo = tmp_path / "repo"
    (repo / "releases").mkdir(parents=True)
    shutil.copy2(REPO / "scale-release.yaml", repo / "scale-release.yaml")
    ex = repo / "domain/examples/scale-catal"
    ex.mkdir(parents=True)
    doc = load_doc(DRIVING_FORCE_EXAMPLES / "photo.json")
    write_canonical(ex / "public.json", doc)
    write_canonical(ex / "project-synthetic.json", {**doc, "graph": {**doc["graph"], "stewardship": {"access": "project"}}})
    write_canonical(ex / "research.json", as_project_data(doc))
    unstated = {**doc, "graph": {k: v for k, v in doc["graph"].items() if k != "stewardship"}}
    write_canonical(ex / "unstated.json", unstated)                     # no access: institution, as pgraph.visible reads it
    assert set(ScaleToolkit(workspace=tmp_path / "ws", repo=repo)._examples()) == {"public"}


def test_describe_overview_label_and_checklist(tk):
    over = tk.call("scale_describe")
    assert over["schema_version"] == HEAD_VERSION and "CatalyticTest" in over["labels"] and "REPORTED_IN" in over["edges"]
    one = tk.call("scale_describe", {"names": ["CatalyticTest"], "domain": "catalysis"})
    assert "faradaic_efficiency" in one["labels"]["CatalyticTest"]["properties"]
    assert one["checklist"]["labels"]["CatalyticTest"]["when"]                  # the driving-force cases
    same = tk.call("scale_describe", {"names": ["CatalyticTest"], "schema_version": HEAD_VERSION})
    assert same["schema_version"] == HEAD_VERSION
    assert "is not a version this repository holds" in tk.call("scale_describe", {"schema_version": "0.0.1"})["error"]
    assert "error" in tk.call("scale_describe", {"names": ["NoSuchLabel"]})
    kernel = tk.call("scale_describe", {"domain": "core"})
    assert "Claim" in kernel["labels"] and "CatalyticTest" not in kernel["labels"]


def test_the_template_is_a_valid_document(tk):
    t = tk.call("scale_template", {"domain": "catalysis"})
    assert t["valid"] and t["schema_version"] == HEAD_VERSION and t["notes"]
    doc = t["document"]
    # a document meant for the repository is public (scale check requires explicit access: public); the note says
    # where project data that is not cleared goes instead
    assert doc["graph"]["follows_domains"] == ["catalysis"] and doc["graph"]["stewardship"]["access"] == "public"
    assert any("access project" in n and "stays outside the repository" in n for n in t["notes"])
    labels = [n["label"] for n in doc["nodes"]]
    assert "Source" in labels and [link["type"] for link in doc["links"]] == ["REPORTED_IN"]
    assert any((n["props"].get("evidence") or [{}])[0].get("quote") for n in doc["nodes"])
    rep = tk.call("scale_validate", {"document": doc})
    assert rep["valid"] and rep["errors"] == []
    assert tk.call("scale_template", {"domain": "core"})["valid"]


def test_new_user_flow_example_validate_query(tk):
    listing = tk.call("scale_example")["examples"]
    assert {e["name"] for e in listing} >= {"electro", "photo", "a-designed-series"}
    out = tk.call("scale_example", {"name": "electro"})
    assert out["written"] == str(tk.workspace / "electro.json")
    assert tk.call("scale_status")["documents"] == ["electro.json"]
    rep = tk.call("scale_validate", {"path": "electro.json"})
    pinned = load_doc(DRIVING_FORCE_EXAMPLES / "electro.json")["graph"]["schema_version"]   # checked under its own pin
    assert rep["valid"] and rep["schema_version"] == pinned and rep["conformance"]["profiles"]["catalysis"]["conformant"]
    cq = load_yaml(REPO / "domain/competency/cq-01-faradaic-efficiency.yaml")
    res = tk.call("scale_query", {"path": "electro.json", "plan": cq["plan"], "format": "markdown"})
    assert res["status"] == "answered" and res["row_count"] == 1 and res["markdown"].startswith("# ")
    gap = tk.call("scale_query", {"path": "electro.json", "plan": {"match": {"label": "Catalyst", "as": "c"},
                                                                   "return": ["c.turnover_magic"]}})
    assert gap["status"] == "schema_gap" and gap["schema_gaps"]                 # an absence is an answer
    assert tk.call("scale_example", {"name": "example"})["written"]               # the worked example (synthetic, public)


def test_validate_reports_errors_and_writes_nothing(tk):
    doc = load_doc(DRIVING_FORCE_EXAMPLES / "photo.json")
    doc["nodes"][0]["props"]["invented_attribute"] = "x"
    rep = tk.call("scale_validate", {"document": doc})
    assert not rep["valid"] and any("not declared" in e["message"] for e in rep["errors"])
    assert not tk.workspace.exists()


def test_migrate_moves_a_document_along_registered_steps(tk, monkeypatch):
    """A document at the head is already current; one pinning a version this repository does not hold has no step
    (none is registered at 0.1.0). A step `scale schema bump` registers moves a document."""
    from scale import pgraph, pgraph_migrate
    head = load_doc(DRIVING_FORCE_EXAMPLES / "electro.json")
    if head["graph"]["schema_version"] != HEAD_VERSION:        # an example stays at the version it pins until migrated
        head = pgraph_migrate.raise_version(head, HEAD_VERSION, pgraph.load_spec(REPO / "domain/graph/scale-catal.yaml"))[0]
    assert "already at" in tk.call("scale_migrate", {"document": head})["error"]
    older = {**head, "graph": {**head["graph"], "schema_version": "0.0.9"}}
    assert "migrations run along the steps" in tk.call("scale_migrate", {"document": older})["error"]
    assert "is not a version this repository holds" in tk.call("scale_validate", {"document": older})["error"]
    # a synthetic step, as `scale schema bump` registers it
    monkeypatch.setitem(pgraph_migrate.STEPS, "0.0.9", (HEAD_VERSION, "additive change"))
    res = tk.call("scale_migrate", {"document": older, "save_as": "migrated"})
    assert res["from_version"] == "0.0.9" and res["to_version"] == HEAD_VERSION
    assert [s["note"] for s in res["steps"]] == ["additive change"] and res["validation"] == {"error": 0, "warning": 0}
    assert res["document"] == head and res["written"] == str(tk.workspace / "migrated.json")
    assert "error" in tk.call("scale_migrate", {"document": older, "save_as": "../escape"})


def test_search_and_a_text_query_build_the_evidence_index_when_none_is_saved(tk):
    """With no index beside the document (or a document given inline), scale_search and a text scale_query build it in
    memory from the document and write nothing."""
    from scale.passages import evidence_items

    tk.call("scale_example", {"name": "c-inconsistent-reference"})
    doc = load_doc(tk.workspace / "c-inconsistent-reference.json")
    words = " ".join(evidence_items(doc)[0]["text"].split()[:4])
    res = tk.call("scale_search", {"path": "c-inconsistent-reference.json", "query": words})
    assert res["hits"] and not (tk.workspace / "c-inconsistent-reference.evidence.jsonl").exists()
    plan = {"match": {"label": "CatalyticTest", "as": "t"}, "text": {"query": words, "mode": "keyword"},
            "return": ["t.name"]}
    assert "error" not in tk.call("scale_query", {"document": doc, "plan": plan})


def test_search_reads_only_the_documents_own_index_and_says_its_access(tk):
    """scale_search and a text scale_query use the index beside a document only when it was built from it; the
    search result carries the document's access, as a query result does."""
    from scale.passages import Index, evidence_items, graph_sha256

    tk.call("scale_example", {"name": "c-inconsistent-reference"})                 # an example that quotes its sources
    doc = load_doc(tk.workspace / "c-inconsistent-reference.json")
    stem = tk.workspace / "c-inconsistent-reference.evidence"
    Index.build(evidence_items(doc), graph_sha256=graph_sha256(doc)).save(stem)
    words = " ".join(evidence_items(doc)[0]["text"].split()[:4])
    res = tk.call("scale_search", {"path": "c-inconsistent-reference.json", "query": words})
    assert res["hits"] and res["access"]["level"] == "public"
    other = json.loads(json.dumps(doc))
    other["nodes"][0]["props"]["note"] = "another document"
    Index.build([{**evidence_items(doc)[0], "text": "a quote this document does not hold"}],
                graph_sha256=graph_sha256(other)).save(stem)
    res = tk.call("scale_search", {"path": "c-inconsistent-reference.json", "query": "quote"})
    assert "error" in res and "was built from another document" in res["error"]
    plan = {"match": {"label": "CatalyticTest", "as": "t"}, "text": {"query": "quote"}, "return": ["t.name"]}
    res = tk.call("scale_query", {"path": "c-inconsistent-reference.json", "plan": plan})
    assert "was built from another document" in res["error"]


def test_a_kept_schema_is_read_again_when_its_files_change(tk, tmp_path):
    """The toolkit keeps a schema while none of the files it is read from changes; a new version in the manifest,
    or a label added to the domain file, is read on the next call."""
    import os
    import shutil
    for d in ("core/graph", "domain/graph", "governance/registry"):
        shutil.copytree(REPO / d, tmp_path / d)
    man = tmp_path / "domain/graph/scale-catal.yaml"
    first = tk._spec(man)
    assert tk._spec(man) is first                                            # kept while nothing changes
    text = man.read_text()
    man.write_text(text.replace(f"version: {first['version']}\n", "version: 9.9.9\n", 1))
    os.utime(man, ns=(os.stat(man).st_mtime_ns + 10**9,) * 2)
    assert tk._spec(man)["version"] == "9.9.9"
    cat = tmp_path / "domain/graph/catalysis.yaml"
    cat.write_text(cat.read_text().replace("\nnodes:\n", "\nnodes:\n  ZzProbe:\n    description: a probe label\n", 1))
    os.utime(cat, ns=(os.stat(cat).st_mtime_ns + 10**9,) * 2)
    assert "ZzProbe" in tk._spec(man)["nodes"]


def test_a_same_size_replacement_keeping_its_timestamp_is_read_again(tk):
    """A document replaced by one of the same size whose modification time is set back to the old one is still a new
    version: its change time differs, and the toolkit reads it again."""
    import os
    import time
    tk.call("scale_example", {"name": "electro"})
    f = tk.workspace / "electro.json"
    plan = {"match": {"label": "CatalyticTest", "as": "t"}, "return": ["t.name"]}
    first = tk.call("scale_query", {"path": "electro.json", "plan": plan})["rows"][0]["values"]["t.name"]
    st = os.stat(f)
    time.sleep(0.01)
    text = f.read_text()
    renamed = "X" + first[1:]
    f.write_text(text.replace(json.dumps(first), json.dumps(renamed), 1))
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert os.stat(f).st_size == st.st_size and os.stat(f).st_mtime_ns == st.st_mtime_ns
    assert tk.call("scale_query", {"path": "electro.json", "plan": plan})["rows"][0]["values"]["t.name"] == renamed


def test_changing_a_description_never_changes_the_kept_schema(tk):
    """scale_describe returns parts of no kept schema: appending to a returned required list, or to the overview's
    ancestry, leaves the next validation and description as they were."""
    tk.call("scale_example", {"name": "electro"})
    before = tk.call("scale_validate", {"path": "electro.json"})
    d = tk.call("scale_describe", {"names": ["CatalyticTest"], "domain": "catalysis"})

    def grow(x):
        if isinstance(x, dict):
            for v in x.values():
                grow(v)
        elif isinstance(x, list):
            for v in x:
                grow(v)
            x.append("description")

    grow(d)
    overview = tk.call("scale_describe", {"domain": "catalysis"})
    grow(overview)
    assert tk.call("scale_validate", {"path": "electro.json"}) == before
    assert tk.call("scale_describe", {"names": ["CatalyticTest"], "domain": "catalysis"}) != d
    assert "description" not in tk.call("scale_describe", {"domain": "catalysis"})["labels"]["CatalyticTest"]["is_a"]


def test_changing_an_answer_never_changes_the_loaded_document(tk):
    """A query's result shares no object with the document the toolkit keeps loaded: scrambling every value of one
    answer leaves the next answer, and the document's digest, as they were."""
    import copy

    def scramble(x):
        if isinstance(x, dict):
            for k, v in list(x.items()):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    x[k] = 999999
                else:
                    scramble(v)
            x["scrambled"] = True
        elif isinstance(x, list):
            for v in x:
                scramble(v)
            x.append("scrambled")

    tk.call("scale_example", {"name": "electro"})
    plan = load_yaml(REPO / "domain/competency/cq-01-faradaic-efficiency.yaml")["plan"]
    first = tk.call("scale_query", {"path": "electro.json", "plan": plan})
    kept = copy.deepcopy(first)
    scramble(first)
    assert tk.call("scale_query", {"path": "electro.json", "plan": plan}) == kept


def test_a_loaded_document_is_reused_until_its_file_changes(tk):
    """scale_query and scale_search keep a document loaded by path, with its query graph and evidence index, and load it
    again when the file changes."""
    import os
    tk.call("scale_example", {"name": "electro"})
    plan = load_yaml(REPO / "domain/competency/cq-01-faradaic-efficiency.yaml")["plan"]
    assert tk.call("scale_query", {"path": "electro.json", "plan": plan})["row_count"] == 1
    first = tk._loaded[str((tk.workspace / "electro.json").resolve())]
    assert tk.call("scale_query", {"path": "electro.json", "plan": plan})["row_count"] == 1
    assert tk._loaded[str((tk.workspace / "electro.json").resolve())] is first
    doc = load_doc(tk.workspace / "electro.json")
    doc["nodes"] = [n for n in doc["nodes"] if n["label"] != "CatalyticTest"]
    (tk.workspace / "electro.json").write_text(json.dumps(doc))
    os.utime(tk.workspace / "electro.json", ns=(first["key"][0] + 10**9, first["key"][0] + 10**9))
    assert tk.call("scale_query", {"path": "electro.json", "plan": plan})["row_count"] == 0


def test_skills_are_listed_and_served(tk):
    skills = {s["name"]: s for s in tk.call("scale_skills")["skills"]}
    assert set(skills) == SKILLS
    text = tk.call("scale_skills", {"name": "query-graph"})["text"]
    assert "name: query-graph" in text and "scale graph query" in text
    assert "error" in tk.call("scale_skills", {"name": "assess-upgrade"})
    # a skill is its folder: the references its text points to are listed and served, and nothing else is
    refs = skills["curate-corpus"]["references"]
    assert {"references/recipes.md", "references/runs.md", "references/batches.md", "scripts/curate_run.py"} <= set(refs)
    assert skills["query-graph"]["references"] == []
    cs = tk.call("scale_skills", {"name": "curate-corpus"})
    assert "references/recipes.md" in cs["text"] and "references/runs.md" in cs["text"] and cs["references"] == refs
    ref = tk.call("scale_skills", {"name": "curate-corpus", "reference": "references/recipes.md"})
    assert ref["reference"] == "references/recipes.md" and ref["text"].startswith("# Recording recipes")
    for bad in ("SKILL.md", "../query-graph/SKILL.md", "references/none.md"):
        assert "error" in tk.call("scale_skills", {"name": "curate-corpus", "reference": bad}), bad


def test_the_names_of_merged_skills_still_find_the_skill_they_went_into(tk):
    """curate-source and curate-dataset were merged into curate-corpus: their names find it, and say so."""
    for old in ("curate-source", "curate-dataset"):
        got = tk.call("scale_skills", {"name": old})
        assert got["name"] == "curate-corpus" and got["renamed_from"] == old and "name: curate-corpus" in got["text"]
    ref = tk.call("scale_skills", {"name": "curate-source", "reference": "references/recipes.md"})
    assert ref["name"] == "curate-corpus" and ref["text"].startswith("# Recording recipes")
    assert "renamed_from" not in tk.call("scale_skills", {"name": "curate-corpus"})
    listed = {s["name"] for s in tk.call("scale_skills")["skills"]}
    assert "curate-source" not in listed and "curate-dataset" not in listed


def test_errors_are_data_not_exceptions(tk):
    assert "error" in tk.call("scale_nope")
    assert "error" in tk.call("scale_validate", {})
    assert "error" in tk.call("scale_validate", {"path": "missing.json"})
    assert "error" in tk.call("scale_query", {"plan": {}, "document": {"graph": {}, "nodes": [], "links": []}})
    assert "error" in tk.call("scale_describe", {"bogus": 1})
    assert "error" in tk.call("scale_describe", {"domain": "astronomy"})


def test_mcp_in_process(tk):
    srv = MCPServer(tk)
    init = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["protocolVersion"] == "2025-06-18" and "scale-catal" in init["result"]["instructions"]
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    lst = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert {t["name"] for t in lst} == TOOL_NAMES and all("inputSchema" in t for t in lst)
    doc = load_doc(DRIVING_FORCE_EXAMPLES / "photo.json")
    call = srv.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "scale_validate", "arguments": {"document": doc}}})
    assert call["result"]["isError"] is False and json.loads(call["result"]["content"][0]["text"])["valid"]
    assert srv.handle({"jsonrpc": "2.0", "id": 4, "method": "nope"})["error"]["code"] == -32601
    prompts = srv.handle({"jsonrpc": "2.0", "id": 5, "method": "prompts/list"})["result"]["prompts"]
    assert {p["name"] for p in prompts} == SKILLS
    prompt = srv.handle({"jsonrpc": "2.0", "id": 6, "method": "prompts/get", "params": {"name": "curate-corpus"}})
    assert "name: curate-corpus" in prompt["result"]["messages"][0]["content"]["text"]
    old = srv.handle({"jsonrpc": "2.0", "id": 7, "method": "prompts/get", "params": {"name": "curate-source"}})
    assert "name: curate-corpus" in old["result"]["messages"][0]["content"]["text"]   # the merged skill's old name


def test_a_malformed_message_is_answered_and_the_server_keeps_serving(tk):
    """JSON that is not a request object (a number, a string, an empty batch, an entry of a batch), params that are
    not an object, an integer too long to read or nesting too deep is answered with a JSON-RPC error, and the next
    request is still served."""
    import io
    srv = MCPServer(tk)
    lines = ["1", '"text"', "[]", "[2]", '{"jsonrpc": "2.0", "id": 7, "method": "ping", "params": [1]}',
             "9" * 5000, "[" * 100000 + "]" * 100000, '{"jsonrpc": "2.0", "id": 8, "method": "ping"}']
    out = io.StringIO()
    srv.serve(io.StringIO("\n".join(lines) + "\n"), out)
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert [r.get("error", {}).get("code") for r in replies] == [-32600, -32600, -32600, -32600, -32602, -32700, -32700, None]
    assert replies[-1] == {"jsonrpc": "2.0", "id": 8, "result": {}}


def test_mcp_stdio_subprocess(tmp_path):
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "scale_validate", "arguments": {
                "path": str(DRIVING_FORCE_EXAMPLES / "plasma.json")}}}]
    proc = subprocess.run([sys.executable, "-c", RUN_SCALE, str(REPO / "tools"), "--repo", str(REPO), "mcp", "--workspace",
                           str(tmp_path / "ws")],
                          input="\n".join(json.dumps(m) for m in msgs) + "\n", capture_output=True, text=True, timeout=60,
                          env={"PATH": "/usr/bin:/bin", "SCALE_NO_UPDATE_CHECK": "1"})
    lines = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [line["id"] for line in lines] == [1, 2, 3]
    assert len(lines[1]["result"]["tools"]) == len(TOOL_NAMES)
    assert lines[2]["result"]["isError"] is False and lines[2]["result"]["structuredContent"]["valid"]


def test_call_cli_is_json_in_json_out(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "SCALE_WORKSPACE": str(tmp_path / "ws"),
           "SCALE_NO_UPDATE_CHECK": "1"}
    run = lambda *a, stdin=None: subprocess.run([sys.executable, "-c", RUN_SCALE, str(REPO / "tools"), "--repo", str(REPO), "call", *a],   # noqa: E731
                                                input=stdin, capture_output=True, text=True, timeout=60, env=env)
    listing = json.loads(run().stdout)
    assert {t["name"] for t in listing["tools"]} == TOOL_NAMES
    assert run("example", '{"name": "electro-dynamic"}').returncode == 0
    plan = load_yaml(REPO / "domain/competency/cq-01-faradaic-efficiency.yaml")["plan"]
    out = run("query", "-", stdin=json.dumps({"plan": plan, "path": "electro-dynamic.json"}))
    assert out.returncode == 0 and json.loads(out.stdout)["status"] == "answered"
    bad = run("status", "not json")
    assert bad.returncode == 1 and "error" in json.loads(bad.stdout)


def test_http_interface(tk):
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer
    from scale.http_server import UNAVAILABLE, make_handler
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tk, "http://127.0.0.1"))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{port}"
        tools = json.load(urllib.request.urlopen(f"{base}/tools"))
        assert {t["name"] for t in tools} == TOOL_NAMES
        assert json.load(urllib.request.urlopen(f"{base}/openapi.json"))["openapi"] == "3.1.0"
        req = urllib.request.Request(f"{base}/tools/describe", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        assert json.load(urllib.request.urlopen(req))["schema_version"] == HEAD_VERSION
        # a stored document the tools cannot read (a record whose props is not an object) answers 503 with a
        # generic error, never a dropped connection, the document's text or a traceback
        tk.call("example", {"name": "electro-dynamic"})
        d = json.loads(next(tk.workspace.rglob("electro-dynamic.json")).read_text())
        for n in d["nodes"]:
            n["props"] = "SECRET-PROPS-TEXT"
        (tk.workspace / "bad.json").write_text(json.dumps(d))
        plan = load_yaml(REPO / "domain/competency/cq-01-faradaic-efficiency.yaml")["plan"]
        for tool, args in (("query", {"plan": plan, "path": "bad.json"}), ("validate", {"path": "bad.json"})):
            req = urllib.request.Request(f"{base}/tools/{tool}", data=json.dumps(args).encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
            with pytest.raises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(req)
            assert err.value.code == 503, tool
            body = err.value.read().decode()
            assert json.loads(body) == {"error": UNAVAILABLE} and "SECRET" not in body and "Traceback" not in body
        # a stored document whose answer is not JSON (a returned value holding NaN) answers 503 too, never a body that
        # is not JSON; so does any result that cannot be written as JSON (a key that is not text)
        nan = json.loads(next(tk.workspace.rglob("electro-dynamic.json")).read_text())
        for n in nan["nodes"]:
            for v in n["props"].get("faradaic_efficiency") or []:      # a returned value (cq-01 returns it)
                v["value"] = float("nan")
        (tk.workspace / "nan.json").write_text(json.dumps(nan))         # Python writes NaN, which JSON does not have
        assert "NaN" in (tk.workspace / "nan.json").read_text()
        real_call = tk.call
        for bad, args in ((None, {"plan": plan, "path": "nan.json"}), ({("a", "tuple"): 1}, {}), ({"x": float("inf")}, {})):
            if bad is not None:
                tk.call = lambda name, arguments=None, bad=bad: bad          # noqa: E731 (a result that is not JSON)
            req = urllib.request.Request(f"{base}/tools/query", data=json.dumps(args).encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
            with pytest.raises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(req)
            tk.call = real_call
            assert err.value.code == 503 and json.loads(err.value.read()) == {"error": UNAVAILABLE}, bad
        # a Content-Length that is not a length (ASCII digits only) answers 400 at once, never a dropped connection
        # and never a wait for a body that does not come ("1_0" and "+10" are numbers to int(), not lengths)
        import socket

        def post(length: bytes) -> bytes:
            with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
                s.sendall(b"POST /tools/describe HTTP/1.1\r\nHost: x\r\nContent-Length: " + length + b"\r\n\r\n{}")
                reply = b""
                while chunk := s.recv(4096):
                    reply += chunk
            return reply
        for bad in (b"abc", b"-5", b"1_0", b"+10", b"0x2", b"2.0", b"1 0"):
            reply = post(bad)
            assert reply.startswith(b"HTTP/1.0 400") and b"Content-Length is not a length" in reply, bad
        assert post(b" 2 ").startswith(b"HTTP/1.0 200")                 # a length, its surrounding space aside
        assert post(b"9" * 4301).startswith(b"HTTP/1.0 413")           # longer than int() reads: too large, never a drop
        assert post(b"0" * 5000 + b"2").startswith(b"HTTP/1.0 200")     # leading zeros: still the length 2
    finally:
        httpd.shutdown()


def test_skills_install(tmp_path, capsys):
    from scale.cli import main
    from scale.releases import list_releases, release_root, skill_files
    assert main(["--repo", str(REPO), "skills", "install", str(tmp_path / "skills")]) == 0
    # the latest release's skills; while no release is built, the head's
    rels = list_releases(REPO)
    src = release_root(REPO, rels[-1]) if rels else REPO
    skills = {p.parent.name: p.parent for p in skill_files(src)}      # where the release's manifest puts them
    shipped = set(skills)
    assert shipped and (rels or shipped == SKILLS)
    assert sorted(p.parent.name for p in (tmp_path / "skills").glob("*/SKILL.md")) == sorted(f"scale-{s}" for s in shipped)
    # the whole folder of each skill, not its SKILL.md alone: triage-feedback carries its schema
    out = json.loads(capsys.readouterr().out)
    assert out["release"] == (rels[-1] if rels else "head (no release built yet)")
    assert out["files"]["scale-triage-feedback"] == ["SKILL.md", "proposal.schema.json"]
    assert (tmp_path / "skills/scale-triage-feedback/proposal.schema.json").read_bytes() == (
        skills["triage-feedback"] / "proposal.schema.json").read_bytes()


def test_human_only_actions_cover_the_review_gates():
    """People approve and merge; nothing is applied after a merge; there is no approval command
    (governance/review-policy.yaml)."""
    for action in ("merge an approved pull request",
                   "add a reviewer (a real person who agreed; no fixed number)", "move a data repository's documents to the latest schema",
                   "build a release", "publish a release to PyPI (once the trusted publisher is configured)",
                   "register the PyPI trusted publisher for scale-catal",
                   "apply the repository settings (ruleset, environments, secrets)", "file a GitHub issue"):
        assert action in HUMAN_ONLY, action
    assert any(a.startswith("approve a pull request") for a in HUMAN_ONLY)
    from test_retired_terms import R3                 # no organization or data repository of another repository
    assert not any(R3.search(a + c) for a, c in HUMAN_ONLY.items())
    assert not any("upgrade" in a or "rollback" in a for a in HUMAN_ONLY)
    assert not any("review approve" in c or "domains-consulted" in c for c in HUMAN_ONLY.values())


def test_a_shipped_text_names_its_licence(tmp_path, capsys):
    """`scale graph export --to kg-bundle --text ID=FILE` redistributes the text: its licence is required, never
    assumed (it used to default to 'public domain')."""
    from scale.cli import main
    txt = tmp_path / "source.txt"
    txt.write_text("a source text")
    args = ["--repo", str(REPO), "graph", "export", str(DRIVING_FORCE_EXAMPLES / "photo.json"), "--to", "kg-bundle",
            "--out", str(tmp_path / "bundle"), "--created", "2026-10-04T00:00:00Z"]
    assert main(args + ["--text", f"ex:df-photo/source/paper={txt}"]) == 2
    assert "name the text's licence" in capsys.readouterr().err
    assert not (tmp_path / "bundle").exists()
