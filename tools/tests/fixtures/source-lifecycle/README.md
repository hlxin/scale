# Source-lifecycle fixtures

Synthetic documents (every value invented; `data_status: synthetic_example`, access public) of the source
lifecycle in the kernel: notices that retract, correct or update a source (`RETRACTS`, `UPDATES`), a partial
retraction scoped to a part of a source, an expression of concern, a preprint of a published work
(`SAME_WORK_AS`) and a recorded status check (`status_check`). The `pass-*` documents are valid and
conformant; each `fail-*` document is rejected for the one reason its name gives. They pin schema 0.1.0.
`tools/tests/test_source_lifecycle.py` reads them.
