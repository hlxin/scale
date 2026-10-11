# __TITLE__

An **experimental** SCALE domain, scaffolded as `domain/` of a test repository by the tests' `new_domain()`
from the test fixture `tools/tests/fixtures/domain-template/`. SCALE has two layers: the science kernel
(`core/`) and the domain in `domain/`, self-contained in its folder. This domain builds on the kernel
through its own schema manifest, `graph/scale-catal.yaml`. It is checked like the catalysis domain, but it
is not part of any official release until it is promoted to stable.

| | |
|---|---|
| status | `experimental` |
| maintainers | `__TEAM__` |
| stewards | __STEWARD_NAME__ (`__STEWARD_GITHUB__`), since __SINCE__ |
| declaration | [DOMAIN.yaml](DOMAIN.yaml) |
| open work | [ROADMAP.md](ROADMAP.md) |

## Scope

TODO: what the domain covers and what it leaves to the core or to other domains.

## Contents

| path | what |
|---|---|
| `graph/scale-catal.yaml` | the domain's graph schema manifest: the science kernel plus the domain file; its `version` is the schema's one version (kernel and domain together), which documents pin |
| `graph/__DOMAIN__.yaml` | the domain file (`domain: __DOMAIN__`): the vocabulary added to the kernel and, optionally, the domain's checklist, with `when` cases |
| `competency/` | competency questions: graph query plans with expected answers (`scale domains cq`); the first runs on the example, two are stubs to fill in |
| `examples/` | example documents |
| `tests/` | the domain's tests (collected by pytest) |

## Checks

```bash
scale domains check __DOMAIN__
uv run --extra dev scale check
```
