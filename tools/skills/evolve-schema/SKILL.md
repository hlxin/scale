---
name: evolve-schema
version: 0.1.0
description: Turn missing-concept gaps into a reviewable scale-graph schema change proposal — gap themes, operations on the schema files, fixtures and counterexamples, the migration of assessed documents and the competency questions to re-run — for human scientific review.
scale_release: ">=v0.1.0"
inputs:
  - Gap reports of kind missing_concept (curation fragments, `scale gap from-query`, a GitHub issue using the missing-concept template, a `gap-report` issue from a corpus run, or a person's request to the agent)
  - The documents containing the motivating records
  - The schema manifest the change starts from (domain/graph/scale-graph.yaml)
allowed-tools:
  - "scale proposal new | build | check <id>"
  - "scale graph describe | validate | query | search | migrate"
  - "scale domains cq"                                 # the competency questions
  - "scale ci proposal-check --base origin/main"        # what the pull request's proposal-check comment will say
  - "scale review status --proposal <id>"              # what the recorded reviews count (read-only)
  - write access to the proposal directory only; never to releases/ or frozen schema versions
outputs:
  - "<NNNNNN>/: proposal.yaml, candidate/, evidence_pack.json, patch.diff, validation_report.json, migration_assessment.json, critic_report.json, review_checklist.md, PR_BODY.md"
validation:
  - "`scale proposal check <id>` reports ok (fixtures behave, assessed documents stay valid, no blocking critic objection)"
  - Fixtures include at least one counterexample that fails for a stated reason
  - Every competency question whose answer changes is declared in expected_query_changes
human-review:
  - Always. The pull request that carries the proposal needs one approving review from a reviewer other than its author (governance/review-policy.yaml); new concepts enter as provisional whatever the tier. After the merge the apply-proposals workflow applies it (decision record, freeze, version bump); never apply it yourself
  - Any breaking change, any override of a blocking objection, and any change to what a value means
---

# Evolve the SCALE schema

A detected gap becomes a change request with an example, source evidence, an explanation of its
scientific consequence and the existing concepts considered. Only a genuinely missing concept calls
for schema extension; extraction errors and absent source information do not.

## Procedure

1. **Collect the gaps.** Read the `missing_concept` gaps curators recorded (fragments' `gaps`, the
   assembly report). Group them into themes by the distinction they need, not by source.
2. **Decide each theme.** `addressed` (schema operations), `guide` (an existing concept or a
   curation convention answers it; say which), `deferred` or `rejected` — the last three with a
   reason a reviewer can accept. A measure used by one source is usually `guide` until it recurs. A
   quantity named after a species, product, stream, method or run is a qualifier, not a concept
   (below, **Qualifier first**).
3. **Write `proposal.yaml`** in `<dir>/<NNNNNN>/`, where `<dir>` is `core/proposals/`
   (owner `core`) for kernel operations, and `domain/proposals/` (owner `catalysis`) for the
   catalysis files. `scale proposal new <owner> --title "…"` takes the next six-digit number (global
   across the science kernel and the catalysis domain: the highest of any proposal plus one, `000001`
   for the first) and scaffolds the file; the folder is the number and the title stays in `proposal.yaml`
   (`id: '000001'`, quoted); never reuse a number. SCALE's schema has two layers, the science kernel and
   the domains (catalysis the first), one version for both, and no repository-wide composition: `base.manifest` names the schema manifest
   the change is assessed against (`domain/graph/scale-graph.yaml`; a kernel proposal names it
   too). `kind: scale-graph`: `base` (`manifest` and
   `version`), target version, `proposer` (for an agent: `agent: true` and `requested_by`), `areas`,
   `gap_sources`, `gap_themes`, `operations` (`add | extend | set | remove | rename` on a schema file named by
   its repository path, e.g. `core/graph/kernel.yaml` or `domain/graph/catalysis.yaml`, and a
   dotted path, each `resolves` its themes), `fixtures` (pass, and fail with the expected message
   and reason), `assess_documents` with their `competency` plans, `expected_query_changes`,
   `mappings_considered`, and a `decision_record` for tier 3.
4. **Prefer additions;** new concepts enter provisional (the check refuses otherwise). Loosen a
   checklist with `unless` exemptions rather than removing requirements; items that hold only for some
   records go in a `when` case (a condition such as `driving_forces: {any_of: [electro]}` and its must,
   should, edges and values). A restructuring moves a concept verbatim with `{op: add, …, moved_from:
   <file>}`, renames a key where it stands with `{op: rename, path: <key>, to: <new key>}` and drops
   whole files with `remove_files` (their manifest entries go too). Register the
   version step in `tools/scale/pgraph_migrate.py` for every version raise (an additive one without a
   rule; a change in how records are written with its rule; `scale proposal check` warns while it is
   missing, and the comment `scale proposal new` writes names the line), so the check migrates the assessed
   documents and, once the merged proposal is applied (a person starts the apply-proposals workflow; under
   the bootstrap rule the owner runs `scale proposal apply --confirm` in a pull request), every document can
   move to the new head. Keep the reasons of a tier 3 decision inside the proposal (`motivation`, the themes'
   reasons): after the merge, the apply-proposals workflow writes the decision record
   `docs/decisions/NNNN-<id>.md` from them, with the pull-request link and the reviewers. The
   schema has **one version** for the kernel and the catalysis domain together, the manifest's: the
   part files (`core/graph/kernel.yaml`, `domain/graph/catalysis.yaml`) carry no `version`, so never
   add or set one (the schema then fails to load). State the new version as `target_version` only;
   it must raise the base version (`scale proposal new` proposes the next minor one). `apply` raises
   it in the manifest and in every other file that states it (`CORE.yaml`, `DOMAIN.yaml`,
   `scale-release.yaml`, the kernel-only example manifest) and freezes the version it replaces: the
   manifest and the parts in `domain/graph/frozen/`, the kernel as
   `core/graph/frozen/kernel-<base version>.yaml`.
5. **Run `scale proposal check <id>`** until `ok`: every gap assigned to one
   theme, every addressed theme resolved by an operation, fixtures behaving, documents still
   valid, competency answers unchanged or declared, no blocking critic objection.
6. **Hand over for review.** Set `status: proposed` and open a pull request (an agent opens it under its
   own GitHub identity, never a person's) whose body is `PR_BODY.md`; it carries the proposal and its reports, never edits to the
   schema files. `review_checklist.md` is for the reviewers. Only people approve, by reviewing the pull
   request; one reviewer other than its author must approve (the owner is a reviewer; the owner's own
   pull requests are merged under the bootstrap rule until another reviewer joins). After the merge, the proposal is applied (`scale proposal
   apply-merged`, run by the apply-proposals workflow a person starts, or `decide --bootstrap-bypass` and
   `apply --confirm` under the bootstrap rule): it records the reviews, writes the decision record, freezes
   the version it replaces (the catalysis manifest and file into `domain/graph/frozen/`, the kernel into
   `core/graph/frozen/`), installs the candidate and raises the schema's one version. If another proposal was applied first on the same base
   version, rebuild yours on the new head (`scale proposal check`) in a new pull request.

## Writing a proposal

- New labels, edge types and properties enter with **`maturity: provisional`**. Promote them later
  in a separate proposal, once they have been used in real records; it needs the same approval.
- Prefer **additive** operations. Express a change of meaning as a deprecation with what supersedes
  it; never delete or reuse an identifier.
- Put the concept where it is **most generally true**: the kernel only for general scientific
  distinctions that are not about catalysis (a `core` proposal); everything about catalysis in the
  catalysis file (`catalysis.yaml`). Keep
  reaction detail out of the schema (species and reactions are records, not labels).
- **Qualifier first.** A property per species, product, stream position, method or run ("methanol
  selectivity", "exit-gas CO", "methanol by titration") is not a new concept: it is the existing
  property, or an Experiment `results` key such as `selectivity`, qualified by the value's `target`,
  `basis`, `variable` or `definition`. Decide such a theme `guide` and say which field carries the
  qualifier. When the value object lacks the qualifier the theme needs (a stream position, a phase, a
  method, a replicate), propose it once as a kernel change to the value fields, never as a property
  per species.
- List `mappings_considered`: existing labels, properties and external vocabularies, and why each
  was or was not reused. Do not invent external identifiers.
- Supply fixtures that pass and counterexamples that fail, each with the message it must fail with
  and why.
- Declare `expected_query_changes`: competency questions whose answers should change.

Agents that share a model or a corpus are not independent reviewers; agent agreement is not
approval. A release names the proposals applied since the previous release (`scale release build
--proposal …`, a human action).
