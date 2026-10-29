# Selectivity basis (issue #82): evidence record

Answers #82. Quotes are the issue's own, short, from CC BY sources; nothing here is a reading of a full text.

## Motivating records

| source | locator | quote (as in the issue) | what it shows |
|---|---|---|---|
| Lyu et al., Nat. Commun. 11 (2020), doi:10.1038/s41467-020-20068-5 | Table 1, row "ε-Fe2C@graphene" | "582.8 \| 20.3 \| 2.6 \| 10.3 \| 23.9 \| 65.8" | CO2 20.3 % beside CH4 + C2-C4 + C5+ = 100: two wholes in one row. The hydrocarbon whole is read from the columns, not stated. |
| same | Methods | "The product selectivity was calculated based on the carbon balance." | counts carbon atoms; names no whole |
| Xie et al., Nat. Commun. 2019, doi:10.1038/s41467-018-08019-7 | 1 bar tests | "calculated as equivalent of carbon atoms in a product with respect to the total carbon atoms present in the hydrocarbons produced" | hydrocarbon whole, carbon atoms |
| same | 1 bar tests | "CO2 was not measured" | |
| same | Table 1 (10 bar) | "Co3Mn1-Na2O \| 20 \| 0.09 \| 9 \| 14 \| 7 \| 42 \| 28" | CO2 in the denominator where measured (columns sum to 100) |
| Catalysts 2022, 12, 288, doi:10.3390/catal12030288 | Methods | "SCn [C%] = FCn/(FCO, in - FCO, out) x 100%" ; "SC5+ [C%] = 100% - Sum SC1-C4" | share of converted CO; C5+ by difference, so CO2 carbon sits inside C5+ |
| Nat. Commun. 2022, doi:10.1038/s41467-022-33715-w | | "74.5% of C5+= slate in the olefins distribution" | share within a pool |
| Nat. Commun. 2016, doi:10.1038/ncomms13058 | | "The highest fractional selectivity SRCHO/RO of ~97 wt% is obtained for Co4Mn1K0.1." | share within the oxygenates, by mass |

The issue's 14-paper curation (294 values, 34 basis strings, 7 for C5+; 35 values lost to `other_basis`) was not seen by
this change; it is the requester's report.

## Existing concepts considered

- `value.basis` / `definition` (free text): kept; they remain the source's words and are now also read as a context.
  They cannot hold a reference to a pool record.
- `species` context (the target): the numerator only; unchanged.
- `fraction_basis` (mass/mole/atom/volume, `relative_to_component` refined by `relative_to`): closest pattern, reused for
  the `refine` mechanism; not reused as a context, because it has no carbon-atom value, no "share of converted
  reactant" and belongs to composition kinds (`composition_fraction`, `loading`, `ratio`).
- `balance_basis` (carbon/charge/...): a balance's quantity; a selectivity is not a balance.
- `target` as a `ProductLump` (#39): names the numerator, so not reused for the denominator.
- `origin` (assumed/derived), evidence `kind: curation_note`, `note`: say how a value arose, not what its denominator is.
- Ontologies: the only mapping of `selectivity` is `quantitykind:DimensionlessRatio` (broad). No term for a selectivity's
  denominator or counting basis was found among those the mapping sets use, so no mapping is added or invented.

## Decisions

| part of the request | decision | why |
|---|---|---|
| (a) what is counted | add context `selectivity_count` (carbon_atoms, mole, mass), read from unit, basis, definition; `wt%` and `mass%` state `mass` | three counts give three quantities; read as text because the value has no sibling in result_values |
| (b) what it is a share of | add context `selectivity_whole` (converted_reactant_incl_co2, products_excl_co2, within_lump refined by `relative_to`), and the value field `relative_to` (provisional) | the pool must be a record reference; a value has no field for one. `target` stays the numerator |
| both in selectivity `compare_by`, unstated kept apart | yes, `unstated: group`: a value that states none is compared only with such values (shown as `not stated`) | no whole assumed |
| `mol%` as a mole count | not read: neither as a term of `mole` nor as a unit that states it | the unit `wt%` says mass unambiguously, but `mol%` on a selectivity is often C-mol% (carbon atoms) and sometimes moles of product; reading it would pick one silently. The value stays `not stated` unless its basis or definition says `mole basis`, `molar basis` or `C-mol`. The cost is that a genuine mole selectivity written only `mol%` is compared apart, never wrongly with another |
| (c) mark an inferred basis | not added | `note` plus an evidence item of `kind: curation_note` already say it was inferred (Lyu Table 1). A comparison cannot group by it without a further tool change; wait until real records need it |
| catalysis.yaml | no change | nothing about the contexts is catalysis-specific beyond the CO2 wording; `relative_to` is kernel-wide (the domain's `context_targets` could narrow it later) |

Open points for the reviewer: the term lists read no negation: bare `including CO2`, `CO2 included`, `CO2-inclusive`, bare `carbon`, `carbon-based` and `converted carbon basis` (a count, not a whole) are not terms, since "not including CO2" or "carbon monoxide" would be read as their opposite or as a carbon count; tests probe those phrases. `mol%` is deliberately unread (decision above). `value.relative_to` has `targets: ANY` (the kernel cannot name catalysis labels); that the pool is a ProductLump or species is a convention, not enforced, and the domain's `context_targets` could narrow it later. The query layer's `exclude()` in `tools/pgraph_query.py` counts one exclusion per (record, reason), so several values of one record left out for one reason count once; this is a separate follow-up, not fixed here. `products_excl_co2` does not say whether oxygenates are inside the whole ("hydrocarbons only"
and "all organic products" share one value; record the source's words in `basis`); lump ids are minted per document, so
two documents' "olefins" pools never match by id (same limit as CQ-13); the term lists are deliberately narrow, a phrase
outside them is not read (the value is then `not stated`, never guessed).

## Consequences

- Schema diff says **breaking** (needs 0.8.0): `selectivity` is narrowed (compared by two more contexts). Added:
  `value.relative_to`, two contexts. Changed: `wt%`, `mass%` unit entries gain `selectivity_count: mass`.
- A document is still valid; only what a scientific comparison puts in one group changes: selectivities of one product
  now split by count and whole, those that state neither form one `not stated` group (the old single group).
- As-reported filters (no `comparison: scientific`) are unchanged: they still compare `basis` as text, and still return
  `other_basis` for a mismatch.
- Existing records: no committed graph in `graphs/` or `examples/` holds a selectivity value object; 15 values in
  `domain/examples` (basis `carbon` or none) all land in one group each as before (a bare `carbon` is no longer read as carbon atoms, so these are `not stated`; the group is the same). All 41 competency questions (CQ-07,
  CQ-13 included) answer as before.
- Tool support needed beyond YAML (made on this branch, for the engineer to check): `tools/quantities.py` (new
  `relative_to` read source; the `within_lump` refinement reads the value's own `relative_to`), `tools/results.py`
  (`relative_to` tells two results apart and is a reference field a query step can follow).
- Still to do by others: `scale schema bump`, the migration rule for a breaking change, CHANGELOG line, fixture and
  counterexample (a `within_lump` value without `relative_to` is `missing_context`; contradictory unit/basis such as
  `wt%` with "carbon basis" is reported), competency question for the new contexts, `docs/implementation-status`.
