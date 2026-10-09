# Schema evolution, releases and migration

Procedure: [`tools/skills/evolve-schema/SKILL.md`](../tools/skills/evolve-schema/SKILL.md). The schema starts at
0.1.0 with no proposal applied yet ([decision record 0001](decisions/0001-scale-0.1.0.md)); the first proposal will
be `000001`. A synthetic proposal, [`tools/tests/fixtures/proposals/009001/`](../tools/tests/fixtures/proposals/009001), shows the format and is what the tests apply.

## Release ids

SCALE releases are `vX.Y.Z`, starting at `v0.1.0` (`releases/vX.Y.Z/`). None has been built yet. A release's
identity comes from its manifest (`distribution: scale-schema`).

## One version

The schema has one version for the science kernel and the catalysis domain together: the `version` of the
catalysis manifest, `domain/graph/scale-graph.yaml`, which documents pin (`graph.schema_version`). The kernel
file and the catalysis file carry none; `core/CORE.yaml`, `domain/DOMAIN.yaml`, `scale-release.yaml`
(`schema_version`) and the kernel-only example manifest state the same number, and `scale domains check`
requires them to agree. Every applied proposal raises it, whichever file it changes: an additive change raises
the minor version, a breaking one the major version.

## Where a proposal lives

A schema change proposal is a directory named by its six-digit number, which is also its id
(`000001`); the title stays in its `proposal.yaml` (`id: '000001'`, always quoted, so that no YAML
reader takes it for a number). Kernel operations go in `core/proposals/` (owner `core`); a change to
the catalysis file goes in `domain/proposals/` (owner `catalysis`). Numbers are global
across the science kernel and the catalysis domain and are never reused: `scale proposal new <owner>
[--title …]` takes the highest number of any proposal plus one (`000001` first). The tools refuse a number
found in two places, a directory whose name is not six digits and a `proposal.yaml` whose `id` is not its
directory's number. Commands take
a proposal's six-digit id or its directory; a shorter number (`1`, `0001`) is refused as ambiguous.
Every record names a proposal by its number: decision records and the decision log, approvals, the gap
register, the schema manifest's `proposals` and migrated documents (`scale proposal apply` finds its
decision record through the decision log entry for that id and its directory).

Every proposal, wherever it lives, is reviewed like every change: its pull request needs two
approving reviews from reviewers other than its author, and until the reviewer seats are filled the owner
merges under the bootstrap rule ([governance/GOVERNANCE.md](../governance/GOVERNANCE.md)). On every pull
request, `scale ci spec-changes --base <ref>` fails when the kernel's or the catalysis domain's specification
files change without a proposal or decision record, and `scale ci proposal-check` checks every
proposal the pull request changes and posts one comment with the results.

## scale-graph proposals

SCALE's schema has two layers, the science kernel (`core/graph/kernel.yaml`) and the domains; the catalysis
domain's graph schema manifest (`domain/graph/scale-graph.yaml`) assembles the kernel with one
catalysis file, with one vocabulary and one checklist. A change to the kernel or to the catalysis graph
file names the manifest it is assessed against (`base.manifest`) and
its files by repository path, and goes through `scale proposal check <id>` (candidate, mirroring
repository paths; diff, tier, fixtures, migration assessment, competency questions, critic,
`PR_BODY.md`). After its pull request merges, the proposal is applied: a person starts the apply-proposals
workflow, which runs `scale proposal apply-merged <id>` (it records the reviews, writes the decision record
`NNNN-<id>.md` and the gap register, `scale proposal decide`, and applies the proposal, `scale proposal apply
--confirm`, all or nothing, then commits to `main`); under the bootstrap rule the owner decides and applies it
locally in a pull request. Applying freezes the version it replaces and installs the candidate, so documents
that pin the old version keep validating: the catalysis manifest into
`domain/graph/frozen/scale-graph-<version>.yaml` with its parts in `domain/graph/frozen/v<version>/`, the kernel
of that version into `core/graph/frozen/kernel-<version>.yaml`, digests appended to each `SHA256SUMS`; then
every file that states the version is raised to the target. A proposal's `target_version` must raise its base
(`scale proposal check` fails otherwise), and the critic objects when a breaking change does not raise the
major version. `scale graph verify` and the release build check that one version names one content. The two
layers are explained in [core/graph/README.md](../core/graph/README.md).

## From gap to release

```
gap (missing_concept, a     ─► a member (or an agent ─► pull request ─► 2 approvals ─► merge ─► apply (a person ─► data repositories ─► release
comment, or a corpus run)       on request): new ·       proposal-check   (bootstrap:              starts it)        update (one        (a person)
                                build · check            comment          the owner)               decision record,  command)
                                                                                                   freeze, bump
```

1. **Gap.** A curator records a `missing_concept` gap; `scale gap issue gaps/GAP-….json` renders the
   issue body (dry run; `--submit` files it with `gh`, a human action). A comment, or a
   `gap-report` issue (a sample of a new corpus curated against the current schema), starts the same way.
2. **Proposal.** A member, or an agent on their request, runs `scale proposal new <owner> [--title …]`,
   which allocates the next number and scaffolds `proposal.yaml`: the gap themes and
   their resolutions, operations on the schema files (`add`, `extend`, `set`, `remove`, `rename`;
   `add` with `moved_from` for a restructuring; whole files with `add_files` and `remove_files`),
   fixtures and counterexamples, the documents whose migration is assessed with their competency
   plans, `expected_query_changes` and the review areas. There is no silent delete: a removal is a
   tier 3 operation with a reason. The proposal goes in with `status: proposed`.
3. **Check.** `scale proposal check <id>` writes `candidate/`, `evidence_pack.json`, `patch.diff`,
   `validation_report.json`, `migration_assessment.json`, `critic_report.json`, `PR_BODY.md` and
   `review_checklist.md`. It warns while the proposal's migration step (base version to target) is not
   registered in `tools/scale/pgraph_migrate.py`. In the pull request, the proposal-check workflow runs it
   again and posts the summary (tier, diff counts, fixtures, migration effects, competency results) as one
   comment.
4. **Review.** Two approving reviews from reviewers other than the author
   ([`governance/review-policy.yaml`](../governance/review-policy.yaml)). The tier tells reviewers what
   kind of change it is (2 additive or loosening, 3 breaking, which also needs a migration step); new
   concepts enter as `maturity: provisional` whatever the tier. A reviewer who requests changes blocks.
   While the two reviewer seats are placeholders, the owner merges under the bootstrap rule and records why
   in the decision record (`scale proposal decide --bootstrap-bypass`).
5. **Merge, decide and apply.** A person starts the apply-proposals workflow for a merged proposal with
   `status: proposed` (it needs a token configured for this repository; see
   [governance/repository-settings.md](../governance/repository-settings.md)): `scale proposal apply-merged
   <id> --pr <n> --reviews <json>` checks the reviews again (placeholders and the author's own review never
   count; approvals of an older commit neither; only GitHub reviews count, and a pull request that adds files
   to `approvals/` fails its check), records them in `approvals/`, writes the decision record with the
   pull-request link, freezes the old version, installs the new one, sets `status: applied` and runs the full
   `scale check`, the unit tests included. If any step fails, every file is put back and nothing is pushed.
   `scale review status --proposal <id>` shows what the recorded reviews count.
6. **Data repositories.** A knowledge-graph data repository kept apart from this one is moved to the new
   version with `scale kg update --data <dir>`: every scale-graph document of the catalysis domain goes to
   the new version through the registered steps, is validated before and after, written in place and its
   evidence index rebuilt; a document a rule cannot map is refused and left untouched, and a file whose name
   pins a version (`*.scale-graph-0.1.0.graph.json`) is kept. Run `--dry-run` first.
7. **Release.** `scale release build vX.Y.Z --proposal <id> …` (a human action) refuses unless every
   proposal applied since the previous release is named and has a decision record, and unless every
   schema change since then is accounted for by one. A release bundles the schema versions applied since
   the last one; `releases/vX.Y.Z/RELEASE.yaml` records the proposals with their decision records, a
   semantic comparison with the previous release, the versions, the contributors and sha256 digests of
   every file ([governance/release-process.md](../governance/release-process.md)).

## Regression checks

Every proposal check, and `scale check` on every pull request, re-run what a schema change could
break:

- **Fixtures** declared by the proposal must pass, and counterexamples must fail with the stated
  message; the repository's own invalid fixtures (`domain/tests/fixtures/invalid/`) must
  be rejected for the reasons their `expect.yaml` states.
- **Assessed documents** (`assess_documents`) are migrated to the candidate along the version steps
  and validated before and after; a document that becomes invalid fails the check.
- **Competency questions** run against the base and the candidate; a changed answer must be declared
  in `expected_query_changes`. The catalysis competency questions run on public examples on every
  pull request (`scale domains cq`) and must meet their expectations.

## Release comparison

`comparison_to_previous` in `RELEASE.yaml` is a semantic diff of the kernel and of the catalysis
assembled schema against the previous release: labels, edge types, properties, enum values and
checklist items added, removed, changed, narrowed or loosened. It is classified as:

- **breaking**: something removed, changed in type or narrowed (a new requirement, fewer allowed
  values or endpoints);
- **additive**: only additions and loosenings, which still need scientific review as provisional
  meaning;
- **identical**: no change in meaning (titles, descriptions and versions aside).

The same diff gives a proposal its tier (`pgraph_proposal.diff_specs`, `tier`).

## Migration

A document pins its schema version, and every earlier version of the schema stays frozen
beside the catalysis manifest once a proposal has moved it on, so a document is always read under the version it pins. `scale graph migrate`
(or `scale call migrate`) moves it along the version steps a proposal registers
(`tools/scale/pgraph_migrate.py`), keeping every record id. Every proposal that raises the version
registers its step when it is prepared, before its pull request merges: applying a merged proposal (the
apply-proposals workflow a person starts, or `scale proposal apply --confirm` under the bootstrap rule) adds
no code, and without the step no document could move to the new head. An additive step only raises
`schema_version`; a step that changes how records are written has a rule that rewrites the document
and reports every change. A rule that meets a case it cannot map stops with an error instead of inventing a
mapping. At 0.1.0 no step is registered yet.

A version bump must not break the tests. Tests read each document under the version it pins (the
documents stay valid under it; moving them is a separate, optional `scale graph migrate` pull request),
read the head version from the manifest instead of spelling it, and compare what a proposal produced
with that version wherever it lives (the head, or its frozen copy once a later proposal has moved the
head on). `scale proposal apply-merged` runs the full `scale check` after the apply, and
`test_a_version_bump_keeps_the_tests_green` applies a synthetic proposal to a copy of the repository and
runs the tests that read schema versions.

Evidence changes have a separate history. A corrected publication updates the status of affected
claims without rewriting the records an earlier analysis used. That analysis stays traceable to the
document digest recorded in its query results.

## Stability guarantees

- Releases and frozen schema versions are never modified (`scale release verify` and
  `scale graph verify`, run in CI; `scale ci spec-changes` fails a pull request that modifies,
  deletes or adds a file inside an existing release directory, or modifies or deletes an existing
  frozen file).
- Identifiers are never deleted or repurposed.
- A document pins its schema version; moving it to a newer one is explicit.
- Pinning cannot freeze an external model, recover unrecorded evidence or reproduce stochastic
  agent choices. Query results record the document digest and the plan they used.
