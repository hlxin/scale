# Catalyst-state and context fixtures

Synthetic documents (every value invented; `data_status: synthetic_example`, access public) of the catalyst states
and contexts in the catalysis domain: a catalyst's states (`CatalystState`, its phases with their location and
dominance, how it was observed) and the transitions between them (`StateTransition`, its kind, what triggers and
drives it), a state's effect on a pathway (`AFFECTS_PATHWAY`), what a computation predicts (`PREDICTS`), the
components of a state and what they are bound to, a molecular detection (`DETECTS`), coverages, site-scoped effects
and the delay from a trigger to the onset of a transition.

They are the passing documents and counterexamples written with these concepts in the consortium schema
repository (up to commit 79b4fe4), moved to today's content with `scale graph migrate` of that time (which changed
only their version) and re-pinned to 0.1.0, with `access: public` and titles that name no change request. The `pass-*`
documents are valid; each `fail-*` document is rejected with exactly one error, the one
[expect.yaml](expect.yaml) states, for the reason it gives. `tools/tests/test_catalyst_states.py` reads them.
