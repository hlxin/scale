# Supporting Information index

Where each Supporting Information item lives in this repository.

| SI item | location |
|---|---|
| Schema reference (labels, edge types, properties, the checklist) | `scale graph describe [labels] --domain catalysis`; the schema files [`../graph/catalysis.yaml`](../graph/catalysis.yaml) and [`../../core/graph/kernel.yaml`](../../core/graph/kernel.yaml) |
| Implementation-status inventory | [`implementation-status.md`](../../docs/implementation-status.md) / [`implementation-status.yaml`](../../docs/implementation-status.yaml) |
| Synthetic example graphs | [`scale-catal/driving-force-examples/`](../examples/scale-catal/driving-force-examples) (one per driving force and combination); the science kernel's in [`core/examples/`](../../core/examples/README.md) |
| Competency-query examples | [`competency/`](../competency) (graph query plans with their expected answers; `scale domains cq catalysis`) |
| Invalid examples, each rejected for a stated reason | [`domain/tests/fixtures/invalid/`](../tests/fixtures/invalid) (`expect.yaml`) |
| Executable commands | [`docs/commands.md`](../../docs/commands.md), `scale --help` |
| Test descriptions | `tools/tests/`, `core/tests/`, `domain/tests/` (see `pytest`); CI steps in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) |
| Contribution specification | [`CONTRIBUTING.md`](../../CONTRIBUTING.md), issue templates in `.github/ISSUE_TEMPLATE/` |
| Agent skills | [`skills/`](../../skills) (8 × `SKILL.md`); [`agents.md`](../../docs/agents.md) |
| Review | [`GOVERNANCE.md`](../../governance/GOVERNANCE.md) (one approving review per pull request; a schema change raises the version in the same pull request, `scale schema bump`), [decision record 0001](../../docs/decisions/0001-scale-0.1.0.md) |
| Release | [`release-process.md`](../../governance/release-process.md), [`releases/`](../../releases/README.md) |
| Migration | [`evolution.md`](../../docs/evolution.md#migration): documents move along the schema's version steps (`scale graph migrate`) |
| Worked schema changes | none yet; the end-to-end test [`tools/tests/test_version_bump.py`](../../tools/tests/test_version_bump.py) makes one on a copy of the repository |

Environment used for the included tests: Python 3.13 and 3.10 on macOS. The CI matrix covers
Python 3.10–3.13 on Ubuntu.
