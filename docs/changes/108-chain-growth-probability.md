# Chain-growth probability alpha (issue #108): evidence record and migration note

Answers #108. Additive change (schema 0.8.1 -> 0.8.2, raised by the systems engineer with `scale schema bump`).
Quotes are the issue's own, short, from CC BY sources; no full text was read by this change.

## Motivating records (as reported in the issue)

| source | locator | quote | what it shows |
|---|---|---|---|
| doi:10.1038/s41467-018-05755-8 (recorded as `ratio`) | as in the issue | "The chain growth probability (α) was evaluated from the slope of straight lines using C14–C21 products" | alpha from a fit, with a stated carbon range |
| doi:10.1021/acscatal.0c05027 (recorded as `fraction`) | as in the issue | "the chain-growth probability determined from the linearized ASF plots" | alpha from a fit of linearized ASF plots |
| doi:10.3390/catal12030288 | curator gap | `missing_concept` gap for alpha | no declared kind |

Curated kinds in 10 of 14 papers (the requester's report, not re-run here): `chain_growth_probability` (undeclared) 4,
`chain_lengthening_probability` (undeclared) 2, `ratio` 2, `fraction` 2. Documents: 10.1038/s41467-018-08019-7,
10.1038/s41586-024-08078-5, 10.1038/s41467-023-37631-5, 10.3390/catal12030288, 10.1038/ncomms13058,
10.1038/s41467-019-11836-z, 10.1038/s41467-018-05755-8, 10.1039/c5cy01942g, 10.1038/s41467-022-33715-w,
10.1021/acscatal.0c05027.

## Existing concepts considered

- `fraction` ("a part of a whole"): alpha is a probability (propagation over propagation plus termination), not a part of a
  whole. Not reused; its description now points alpha to the new kind.
- `ratio` (one component over another in a mixture or recipe): alpha is not a composition ratio. Not reused; its
  description points alpha to the new kind.
- `composition_fraction`, `species_fraction`, `selectivity`, `conversion`, `product_yield`: shares of a sample or of
  converted/fed reactant; alpha is none of them (it summarises a distribution).
- `fraction_basis` context (mass/mole): close, but belongs to composition kinds, has no "not stated" group, and its terms
  do not read W_n/x_n. A dedicated `chain_growth_basis` context was added instead.
- `value.basis` / `definition`: kept as the place the contexts are read from; the carbon range of a fit stays in the
  definition (see limits).
- Qualifier first: a kind per product or per method would be a qualifier; here the missing piece is the kind itself
  (dimensionless probability, with its own comparison rules), so a kind is needed. Theme decision: schema change.
- Undeclared kind spellings (`chain_lengthening_probability`) validate today without warning; not declared as a
  synonym.

## The patch (files)

- `core/graph/kernel.yaml`: kind `chain_growth_probability` (provisional, dimensionless, compare_by
  `chain_growth_method`, `chain_growth_basis`); contexts `chain_growth_method` (distribution_fit,
  lumped_selectivities) and `chain_growth_basis` (weight_fraction, mole_fraction), both read from basis/definition, both
  `unstated: group` (a value that states nothing is compared only with such values); `fraction` and `ratio`
  descriptions point alpha to the new kind. Nothing is converted.
- `domain/graph/catalysis.yaml`: unchanged. It declares no Fischer-Tropsch product-distribution recipe or checklist item
  that names a quantity kind (searched for FTS, Fischer, ASF, chain growth), so there is nothing to repoint.
- `domain/examples/scale-catal/product-measurement-examples/chain-growth-probability.json` (+ `build_chain_growth.py`):
  fixture with three alphas (0.89 weight-basis fit C14-C21; 0.71 mole-basis fit C5-C10; 0.62 from lumped selectivities).
- `domain/tests/fixtures/invalid/chain-growth-probability-in-kelvin.json` (+ `build_fixtures.py`, `expect.yaml`):
  counterexample, rejected because a unit of temperature is not a dimension of the kind.
- `domain/competency/cq-42-chain-growth-probability.yaml`: CQ-42, three groups on the scientific comparison; a variant
  asking for fits leaves the lumped value out as `incompatible_context`.

Checks run: `uv run scale check --fast` passes (CQ 42/42, invalid fixtures rejected for their stated reasons).
Not run by this role: `scale schema bump`, `scale schema check`, CHANGELOG, mappings.

## Limits (stated)

- The contract compares dimensions only, so a dimensionless value outside 0..1 is not rejected; the counterexample
  rejects the wrong unit instead.
- The carbon range of a fit is not a context: an open context can read only `target`, `record` or `producer`
  (tools/quantities.py), so the range stays in the value's definition and two fits over different ranges are told apart
  only by reading it. A range context would need a tooling change (out of scope).
- Contexts are read by listed terms; phrasing outside them is read as not stated (grouped apart, never guessed).
- Per-carbon-number distribution (W_n against n) is out of scope.

## Migration note

Documents pinning 0.8.1 stay valid and keep their kinds. To move to the new kind, set the Variable's `quantity_kind` to
`chain_growth_probability` (and unit `1` or an empty unit as the dimensionless unit is written in the document) wherever it
holds alpha under `fraction`, `ratio`, `chain_growth_probability` (undeclared) or `chain_lengthening_probability`
(undeclared). Put how alpha was obtained and the distribution basis in the value's `basis` or `definition` ("slope of
ln(W_n/n) over C14-C21", "weight fraction W_n"), using the listed terms, so that it is read; keep the carbon range in the
definition. Values already stored as a percent are not rescaled by SCALE: record alpha as reported. Plans that ask for the
kind `chain_growth_probability` then find them all. No automatic rewrite is registered, because the kind alone does not
tell an alpha from another `fraction` or `ratio`; `scale schema bump` registers only the version step.
