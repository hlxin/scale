# Tools

The `scale` Python package and command (this folder is the package), and its tests. The skills agents follow are
in [`../skills/`](../skills/).

```
tools/
├── layout.py   # every repository-relative path the tools use, in one place
├── cli.py      # the `scale` command
├── …           # agent interfaces, scale-graph validation and queries, schema changes, releases
└── tests/      # tests of the tools, with their fixtures
```

The modules are mapped in [docs/architecture.md](../docs/architecture.md#code-map).

## The package

- The distribution is `scale-catal`; the import package is `scale` (the folder `tools/`, mapped in `pyproject.toml`); the commands are `scale`
  and `scale-catal` (so that `uvx scale-catal …` works). Python ≥ 3.10; the runtime
  dependencies are PyYAML and jsonschema.
- The wheel bundles what the tools read at run time (`scale-release.yaml`,
  `core/`, `domain/`, `skills/`, the review policy and registries, `releases/`,
  `docs/implementation-status.yaml`, `AGENTS.md`) under `scale/_data`, mirroring the repository
  layout, so the same repository-relative paths work in a checkout and in an installed wheel.
- Paths are never hard-coded in modules: they come from `tools/layout.py`, which also finds the
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
needs would live in `tools/`, reviewed like every change.

Files that enforce governance: the review policy implementation (`tools/policy.py`), what a schema
change must carry (`tools/schema_change.py`: `scale schema diff | bump | check`), the pull-request checks
(`tools/ci.py`: `scale ci spec-changes`), the catalysis and kernel declaration checks
(`tools/domains.py`) and the CODEOWNERS evaluator (`tools/codeowners.py`). Changing what they
enforce is a pull request like any other; say so plainly in it. `tools/kg.py` (`scale kg update`) moves a knowledge-graph data
repository to a new schema version.

## Skills

[`skills/`](../skills/), at the repository root, holds the procedures agents follow: `curate-source`, `query-graph`, `evolve-schema`,
`triage-feedback`, `scan-conflicts`, `map-coverage`, `curate-dataset` and `export-graph`. Each `SKILL.md`
carries a version. Releases list the skills in
their manifest (`skills:`, `skills/…`); `scale skills install` installs a release's skills (the
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
