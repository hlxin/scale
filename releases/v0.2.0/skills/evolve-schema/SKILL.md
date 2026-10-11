---
name: evolve-schema
version: 0.2.0
description: Turn missing-concept gaps or a person's request into a scale-catal schema change in one pull request — the edit to the schema files, fixtures and counterexamples, the version raised by the rule, the migration step and the competency questions to re-run — for one person's approval.
scale_release: ">=v0.1.0"
inputs:
  - Gap reports of kind missing_concept (curation fragments, `scale gap from-query`, a GitHub issue, a `gap-report` issue from a corpus run, or a person's request)
  - The documents containing the motivating records
  - The schema files (core/graph/kernel.yaml, domain/graph/catalysis.yaml; the manifest domain/graph/scale-catal.yaml)
allowed-tools:
  - "scale schema diff | bump | check --base origin/main"
  - "scale graph describe | validate | query | search | migrate"
  - "scale domains cq"                                 # the competency questions
  - "scale check --fast"
  - write access to the schema files, fixtures, examples, tests and CHANGELOG; never to releases/ or by hand to frozen schema versions
outputs:
  - "one pull request: the schema edit, a fixture that uses what is added (and a counterexample), the frozen base version, the raised version, the migration step (and rule, if breaking), a CHANGELOG line"
validation:
  - "`scale schema check --base origin/main` and `scale check --fast` pass"
  - Fixtures include at least one counterexample that fails for a stated reason
  - Every competency question whose answer changes is updated in the same pull request and said so
human-review:
  - Always. One person approves and merges the pull request (governance/review-policy.yaml); new concepts enter as provisional whatever the kind of change
  - Say plainly in the pull request when the change is breaking or changes what a value means
---

# Evolve the SCALE schema

A detected gap becomes a change with an example, source evidence, an explanation of its scientific
consequence and the existing concepts considered. Only a genuinely missing concept calls for schema
extension; extraction errors and absent source information do not. A schema change is a pull request like any
other: it edits the schema files directly, and CI checks that it carries what it must.

## Procedure

1. **Collect the gaps.** Read the `missing_concept` gaps curators recorded (fragments' `gaps`, the
   assembly report) or the request. Group them into themes by the distinction they need, not by source.
2. **Decide each theme.** Change the schema, or `guide` (an existing concept or a curation convention answers
   it; say which), or wait (say why). A measure used by one source is usually `guide` until it recurs. A quantity
   named after a species, product, stream, method or run is a qualifier, not a concept (below, **Qualifier
   first**). Write the decisions in the pull request description.
3. **Edit the schema files** on a branch: the science kernel `core/graph/kernel.yaml` for general scientific
   distinctions, the catalysis file `domain/graph/catalysis.yaml` for everything about catalysis. The schema has
   **one version** for both, the manifest's (`domain/graph/scale-catal.yaml`); the part files carry no `version`,
   so never add one. Prefer additions; new labels, edge types and properties enter with
   **`maturity: provisional`**. Loosen a checklist with `unless` exemptions rather than removing requirements;
   items that hold only for some records go in a `when` case (a condition such as
   `driving_forces: {any_of: [electro]}` and its must, should, edges and values). Express a change of meaning as a
   deprecation with what supersedes it; never delete or reuse an identifier.
4. **Add tests.** A fixture (a valid document under `domain/tests/fixtures/`, `domain/examples/` or
   `tools/tests/fixtures/`) that uses every label and edge type you add, and a counterexample in
   `domain/tests/fixtures/invalid/` (listed in its `expect.yaml` with the error and the reason). Update the
   competency questions whose answers change (`scale domains cq`).
5. **Raise the version.** `scale schema diff --base origin/main` shows the kind of change and the version it
   needs: a breaking change (something removed, changed or narrowed) raises the second number (0.1.0 -> 0.2.0),
   an additive change the third (0.1.0 -> 0.1.1). `scale schema bump --base origin/main [--note "…"]` freezes the
   base version (the manifest and the catalysis file into `domain/graph/frozen/`, the kernel into
   `core/graph/frozen/`), raises the version in every file that states it and registers the migration step in
   `tools/pgraph_migrate.py`. Run it once, after the edit. A breaking change also needs its rewrite rule
   (`STEP_RULES[<base version>]`), so that `scale kg update` can move documents.
6. **Check.** Add a line under `## Unreleased` in `CHANGELOG.md`, then run `scale schema check --base origin/main`
   and `scale check --fast` until both pass.
7. **Open the pull request** (an agent opens it under its own GitHub identity, never a person's). Its description
   names the gaps or request it answers, the themes and their decisions, the existing concepts considered, the
   summary `scale schema check` prints, and what it did not do. One person approves and merges it. If another
   schema change merges first, rebase, and run `scale schema bump` again on the new base.

## Writing a change

- Put the concept where it is **most generally true**: the kernel only for general scientific distinctions that
  are not about catalysis; everything about catalysis in `catalysis.yaml`. Keep reaction detail out of the schema
  (species and reactions are records, not labels).
- **Qualifier first.** A property per species, product, stream position, method or run ("methanol
  selectivity", "exit-gas CO", "methanol by titration") is not a new concept: it is the existing
  property, or an Experiment `results` key such as `selectivity`, qualified by the value's `target`,
  `basis`, `variable` or `definition`. Decide such a theme `guide` and say which field carries the
  qualifier. When the value object lacks the qualifier the theme needs (a stream position, a phase, a
  method, a replicate), change the kernel's value fields once, never add a property per species.
- Consider existing labels, properties and external vocabularies, and say in the pull request why each was or
  was not reused. Do not invent external identifiers.
- Promote a provisional concept later, in its own pull request, once it has been used in real records.

Agents that share a model or a corpus are not independent reviewers; agent agreement is not approval.
