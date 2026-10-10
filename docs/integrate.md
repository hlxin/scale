# Using SCALE from an agentic system

SCALE makes no assumption about your model, provider or agent framework. Every system that can
run a command can use it:

```bash
uvx scale-catal call <tool> '<json-arguments>'
```

That is the whole setup. `uvx` (from [uv](https://docs.astral.sh/uv/)) fetches SCALE from PyPI and
runs it in an isolated environment. scale-catal is not on PyPI yet: until its first release is
published, use the checkout or git form below (`uvx --from …`). The command takes JSON arguments and prints a JSON result. It
exits 0 on success and 1 when the result is an error (which is still printed as JSON).

- **Pin a version** so the same command gives the same behaviour every time:
  `uvx scale-catal@0.1.0 call …` (see [Staying current](#staying-current)).
- **MCP** (Claude Code, Claude Desktop and other MCP hosts): `claude mcp add scale -- uvx scale-catal mcp`,
  or register the command `uvx scale-catal mcp` in your host's MCP settings.
- **Install once instead:** `pip install scale-catal`, then call `scale call …` directly.
- **From a checkout or a fork:** `uvx --from /path/to/scale scale-catal call status`,
  or `uvx --from git+https://github.com/hlxin/scale scale-catal call status`.

Register the command as a tool in your system (a shell or command tool, a subprocess call, a CI
step, or a notebook cell). The agent can then discover everything else:

```bash
scale call                                   # lists every tool with its JSON Schema
scale call status                            # versions, the catalysis domain, the working directory, next steps
scale call skills '{"name": "curate-source"}'
scale call describe '{"names": ["CatalyticTest"], "domain": "catalysis"}'
scale call query - < plan.json               # "-" reads arguments from stdin (large inputs)
```

Tool names work with or without the `scale_` prefix. There is no configuration to write and nothing
to upgrade. SCALE reads and writes one data format, **scale-graph documents** (node-link JSON), and
each document pins the schema version it follows (`graph.schema_version`). Documents live in a
working directory, `$SCALE_WORKSPACE` (default `~/.scale/workspace`): a relative `path` argument is
read there, and the two tools that write (`example`, and `migrate` with `save_as`) write only there.

## The same tools through other standard interfaces (optional)

Use one of these only if your system prefers it; all serve the same tools with the same results.

| your system speaks | run | then |
|---|---|---|
| a shell / subprocess (universal) | `scale call <tool> '<json>'` | parse stdout as JSON |
| HTTP or OpenAPI tool import | `scale serve` (binds 127.0.0.1:8765) | `GET /tools`, `POST /tools/<name>` with a JSON body, `GET /openapi.json`; a tool that cannot read a stored document, or whose result is not JSON, answers 503 with a generic error |
| the Model Context Protocol (open standard) | `scale mcp` (stdio) | tools, plus the SCALE skills as MCP prompts |
| Python | `from scale.api import ScaleToolkit` | `ScaleToolkit().call(name, arguments)`; `ScaleToolkit.schemas()` for definitions |

`scale tools --format jsonschema|openapi|mcp` prints the definitions for systems that register
tools from a schema file. JSON Schema is the format most function-calling interfaces accept.

## Skills (procedures) for systems that load instruction files

```bash
uvx scale-catal@0.1.0 skills install <your-agent-skills-folder>
```

This copies the versioned `SKILL.md` procedures that the latest release lists (`--release <id>` for
another one). Each states its inputs, allowed tools, outputs, validation and human-review conditions.
The same texts are available as `scale call skills` and as MCP prompts. `AGENTS.md` summarizes the
rules for any agent.

`skills install` copies each skill as its whole folder: the `SKILL.md` and the files it points to (for
curate-source, its recording recipes in `references/recipes.md`), and `scale call skills` returns a reference
file too (`'{"name": "curate-source", "reference": "references/recipes.md"}'`).

| skill | what it is for |
|---|---|
| `curate-source` | translate a declared source (an article, a patent, a report) into a scale-graph document: values as printed, evidence, typed absences, gaps instead of schema changes; with recording recipes |
| `curate-dataset` | turn a data table or a lab file into a document: the file as a Dataset with its digest and column dictionary, records citing their rows, the access its owners set |
| `query-graph` | answer a question with a graph query plan: rows as reported with evidence, what was left out and why, the coverage, the kind of answer |
| `map-coverage` | a coverage map (materials by properties by conditions) from query plans, each kind of absence kept apart, gaps routed |
| `scan-conflicts` | pair values that seem to disagree and classify each pair as genuine, apparent (with the axis) or not comparable; never rewriting a value |
| `export-graph` | hand a document to another system: validated, capped, filtered for its audience, native or as a kg-bundle with its losses stated, sealed and linked to its previous release |
| `evolve-schema` | turn missing-concept gaps into a schema change in one reviewable pull request |
| `triage-feedback` | sort community feedback into topics and options for the reviewers |

Release v0.1.0 carries all eight skills: curate-source, query-graph, evolve-schema, triage-feedback, scan-conflicts,
map-coverage, curate-dataset and export-graph. On a checkout (`--repo`, or `uvx --from` a
checkout), `scale call skills` serves the head's skills.

## The tools

| tool | what it does | writes |
|---|---|---|
| `status` | tool version, latest release, the science kernel and the catalysis domain with the schema version, the documents in the working directory, skills, capability status, human-only commands | — |
| `domains` | the catalysis domain (`domain/`): status, the schema version and its frozen versions, code owner, example query plans (their competency questions), public examples | — |
| `describe` | labels and edge types with their properties; with `domain` (`catalysis`), the checklist (must and should, and the cases by driving force); with no names, an overview | — |
| `template` | a minimal valid document for the catalysis domain (or the kernel alone, `core`): header and stewardship, a Source, one evidenced record, its REPORTED_IN link | — |
| `validate` | validate a document (inline or a path) under the version it pins: errors, warnings, checklist conformance; `source_texts` checks quotes verbatim | — |
| `query` | run a graph query plan: rows as reported with evidence, records left out and why, a coverage block (candidates, each stage's rows, everything left out by reason, the values compared), and the answer's kind (`answered`, `no_matching_record`, `missing_context`, `schema_gap`); a numeric filter states its unit and compares only values in that unit and on the basis it states, nothing converted ([querying.md](querying.md)) | — |
| `search` | search a document's evidence index (saved by `scale graph index`, or built in memory when none is) by words and meaning | — |
| `migrate` | move a document along the schema's version steps to a newer version (ids kept) | the working directory, with `save_as` |
| `example` | list the public synthetic examples, or copy one into the working directory | the working directory |
| `skills` | list the skills with their reference files, or return one skill's text, or one of its reference files (`reference`; after v0.1.0) | — |

**Human-only by design:** approving and merging pull requests,
building releases and filing issues are not tools. `scale call status` returns the exact command
for each (`human_only_actions`).

## Try it

```bash
scale call example '{"name": "electro-dynamic"}'
scale call validate '{"path": "electro-dynamic.json"}'
python3 -c "import json,yaml;print(json.dumps({'path':'electro-dynamic.json','plan':yaml.safe_load(open(
  'domain/competency/cq-01-faradaic-efficiency.yaml'))['plan']}))" | scale call query -
```

The document is valid and conforms to the catalysis checklist. The query (the catalysis
competency question CQ-01, also returned by `scale call domains`) answers with two catalytic tests:
the pulsed test with its Faradaic efficiency and no single electrode potential (a pulsed test has
none; the record carries the waveform, and the answer lists the potential under `missing_context`
rather than inventing one), and the potentiostatic baseline at −1.4 V vs Ag/AgCl.

## Staying current

| what | pinned by | how it updates |
|---|---|---|
| the **tool** (the `scale` package, with the schemas it bundles) | the version in the command (`scale-catal@0.1.0`) | change the version; without a pin, `uvx --refresh scale-catal …` fetches the newest |
| the **schema version** a document follows | the document itself (`graph.schema_version`) | `scale call migrate` (or `scale graph migrate`) moves it to a newer version when you ask |

A newer tool keeps every earlier schema version (its frozen copies, once a schema change has moved the schema on), so a document is
always read under the version it pins; updating the tool never changes what an existing document
means.

**Being told.** `scale call status` has an `updates` field that says whether a newer tool tag is
published. The lookup uses `git ls-remote`, is cached for a day and needs read access to the
repository; set `SCALE_NO_UPDATE_CHECK=1` to switch it off. An agent relays a notice to its user
rather than acting on it.

## Configuration

| setting | default | purpose |
|---|---|---|
| `SCALE_WORKSPACE` / `--workspace` | `~/.scale/workspace` | the working directory for documents; one per project is good practice |
| `SCALE_REPO` / `--repo` | bundled data | use a SCALE checkout (e.g. a branch with your catalysis changes) instead of the bundled data |
| `SCALE_NO_UPDATE_CHECK` | unset | skip the daily remote lookup of newer tool tags (offline or air-gapped use) |
| `SCALE_REPO_URL` | the SCALE repository | where the remote lookup looks for tags (e.g. a mirror) |
