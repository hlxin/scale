# Reporting-applicability fixtures

Synthetic documents (every value invented; `data_status: synthetic_example`, access public, not evidence about the
world) for the catalysis checklist's applicability and connected evidence (scale-catal 0.5.0 on).

- `pass-applicability-known.json` and `fail-applicability-unknown.json`: tests that list their driving forces, list
  none or list an empty list, beside an equilibrium estimate. A test that lists no driving force has unknown
  applicability, and its checklist is never complete; an equilibrium estimate is exempt.
- `pass-evidence-found.json` and `fail-evidence-missing.json`: one test per reading (`interpretations`) with the
  evidence the checklist looks for in the records connected to it, or without it.

Every document is valid. [expect.yaml](expect.yaml) states each one's checklist outcome, and
`tools/tests/test_reporting_applicability.py` checks it. `build_fixtures.py` rebuilds them from the helpers of the
evidence examples' builder (`domain/examples/scale-catal/evidence-examples/`).
