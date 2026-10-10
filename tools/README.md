# Tools

The shared tooling: the `scale` Python package and command, the skills agents follow, and the
tests for both. Reviewed, like every path, by its code owner (`@hlxin` today) and the reviewers.

| directory | what it holds |
|---|---|
| [`scale/`](scale/) | The Python package and the `scale` command (distribution `scale-catal`). [`scale/layout.py`](scale/layout.py) is the one place that names repository paths. |
| [`skills/`](skills/) | Versioned `SKILL.md` procedures for people and agents (curate-source, query-graph, evolve-schema, triage-feedback, scan-conflicts, map-coverage, curate-dataset, export-graph). Releases ship the skills their manifest lists. |
| [`tests/`](tests/) | Tests of the tools. The kernel's tests are in `core/tests/`, the catalysis tests in `domain/tests/`; the one shared `conftest.py` is at the repository root. |

```
tools/
├── scale/          # the Python package `scale` (distribution `scale-catal`)
│   ├── layout.py   # every repository-relative path the tools use, in one place
│   └── …           # CLI, agent interfaces, scale-graph validation and queries, schema changes, releases
├── skills/         # versioned SKILL.md procedures
└── tests/          # tests of the tools, with their fixtures
```

The modules are mapped in [docs/architecture.md](../docs/architecture.md#code-map).

## The package

- The distribution is `scale-catal`; the import package is `scale`; the commands are `scale`
  and `scale-catal` (so that `uvx scale-catal …` works). Python ≥ 3.10; the runtime
  dependencies are PyYAML and jsonschema.
- The wheel bundles what the tools read at run time (`scale-release.yaml`,
  `core/`, `domain/`, `tools/skills/`, the review policy and registries, `releases/`,
  `docs/implementation-status.yaml`, `AGENTS.md`) under `scale/_data`, mirroring the repository
  layout, so the same repository-relative paths work in a checkout and in an installed wheel.
- Paths are never hard-coded in modules: they come from `scale/layout.py`, which also finds the
  catalysis domain (`domain/`, its name read from `domain/DOMAIN.yaml`), the competency questions and the optional
  restricted copy (named by an environment variable only).
- Tools are deterministic. Anything that calls a model sits behind a skill (or, for feedback
  triage, an external command named with `--agent-command`).
- They read and write one data format, scale-graph documents, each pinning the schema version it follows
  (one version for the kernel and the catalysis domain together).

Commands are listed in [docs/commands.md](../docs/commands.md); agent interfaces (`scale call`,
MCP, HTTP, Python) in [docs/integrate.md](../docs/integrate.md).

## Catalysis code

The tools hold no catalysis-specific code today: the catalysis domain is data (its schema files,
examples, competency questions) that the tools read in `domain/`. Code that only the catalysis domain
needs would live in `tools/scale/`, reviewed like every change.

Files that enforce governance: the review policy implementation (`tools/scale/policy.py`), what a schema
change must carry (`tools/scale/schema_change.py`: `scale schema diff | bump | check`), the pull-request checks
(`tools/scale/ci.py`: `scale ci spec-changes`), the catalysis and kernel declaration checks
(`tools/scale/domains.py`) and the CODEOWNERS evaluator (`tools/scale/codeowners.py`). Changing what they
enforce is a pull request like any other; say so plainly in it. `tools/scale/kg.py` (`scale kg update`) moves a knowledge-graph data
repository to a new schema version.

## Skills

`tools/skills/` holds the procedures agents follow: `curate-source`, `query-graph`, `evolve-schema`,
`triage-feedback`, `scan-conflicts`, `map-coverage`, `curate-dataset` and `export-graph`. Each `SKILL.md`
carries a version. Releases list the skills in
their manifest (`skills:`, `tools/skills/…`); `scale skills install` installs a release's skills (the
head's while no release is built) into an agent, and `scale call skills` (or MCP prompts) serves them.

## Tests

| tests of | in |
|---|---|
| the tools | `tools/tests/` |
| the kernel | `core/tests/` |
| the catalysis domain | `domain/tests/` |

pytest collects all three (`testpaths` in `pyproject.toml`; the domain template test fixture,
`tools/tests/fixtures/domain-template/`, whose starter tests are templates, is not collected); the one shared `conftest.py` is at
the repository root. Test file names are unique across the repository. Update
`docs/implementation-status.yaml` when you add, mock or finish a capability; CI checks that
functioning entries cite existing tests.

```bash
uv run --extra dev scale check          # every check of CI's test jobs, from the repository root
uv run --extra dev scale check --fast   # without the tests
```
