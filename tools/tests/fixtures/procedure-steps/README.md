# Procedure-step fixtures

Synthetic documents (every value invented; `data_status: synthetic_example`, access public, not evidence about the
world) for issue #34: structured steps of a `Preparation` are `ProcedureStep` nodes linked `PART_OF` the preparation,
with `order`. `pass-steps-part-of.json` is valid; `fail-has-procedure-step.json` uses `HAS_PROCEDURE_STEP`, which no
schema file declares, and is rejected with exactly one error, as [expect.yaml](expect.yaml) states.
`tools/tests/test_procedure_steps.py` reads them.
