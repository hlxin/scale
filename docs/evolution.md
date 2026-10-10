# Schema evolution, releases and migration

Procedure: [`tools/skills/evolve-schema/SKILL.md`](../tools/skills/evolve-schema/SKILL.md). The schema starts at
0.1.0 with no change merged yet ([decision record 0001](decisions/0001-scale-0.1.0.md)).
`tools/tests/test_version_bump.py` makes a synthetic schema change on a copy of the repository and runs the tests on
it.

## Release ids

SCALE releases are `vX.Y.Z`, starting at `v0.1.0` (`releases/vX.Y.Z/`), the first, built on 2026-10-10. A release's
identity comes from its manifest (`distribution: scale-catal`).

## One version

The schema has one version for the science kernel and the catalysis domain together: the `version` of the
catalysis manifest, `domain/graph/scale-graph.yaml`, which documents pin (`graph.schema_version`). The kernel
file and the catalysis file carry none; `core/CORE.yaml`, `domain/DOMAIN.yaml`, `scale-release.yaml`
(`schema_version`) and the kernel-only example manifest state the same number, and `scale domains check`
requires them to agree. Every schema change raises it, whichever file it changes: a breaking change (something
removed, changed in type or narrowed) raises the second number (0.1.0 -> 0.2.0), any other change the third
(0.1.0 -> 0.1.1).

## A schema change is a pull request

SCALE's schema has two layers, the science kernel (`core/graph/kernel.yaml`) and the domains; the catalysis
domain's graph schema manifest (`domain/graph/scale-graph.yaml`) assembles the kernel with one catalysis file,
with one vocabulary and one checklist. A schema change edits those files directly, on a branch, in one pull
request that also carries everything the change needs. Nothing is applied after the merge: what merges is what
the reviewer approved ([governance/GOVERNANCE.md](../governance/GOVERNANCE.md)).

```
gap or request (an issue, ─► @scale-agents (on     ─► pull request: edit · tests ·  ─► 1 approval ─► merge ─► data repositories ─► release
a comment, a corpus run)     their own) or anyone   scale schema bump · check       (any reviewer)            update (one        (a person)
                                                          (CI writes the summary)                                  command)
```

1. **Gap or request.** A curator records a `missing_concept` gap; `scale gap issue gaps/GAP-….json` renders the
   issue body (dry run; `--submit` files it with `gh`, a human action). A comment, or a `gap-report` issue (a
   sample of a new corpus curated against the current schema), starts the same way. @scale-agents take it up on
   their own, or anyone opens the pull request.
2. **Edit and test.** The kernel or the catalysis file is edited directly: additive operations, deprecation
   instead of deletion, `maturity: provisional` for new concepts. A fixture uses every label and edge type the
   change adds, and a counterexample in `domain/tests/fixtures/invalid/` fails for its stated reason. The
   competency questions whose answers change are updated.
3. **Bump.** `scale schema diff --base origin/main` compares the branch's schema with the merge base (rebuilt
   from git) and names the kind of change and the version it needs. `scale schema bump --base origin/main
   [--note …]` then freezes the base version, so documents that pin it keep validating (the catalysis manifest
   into `domain/graph/frozen/scale-graph-<version>.yaml` with its parts in `domain/graph/frozen/v<version>/`, the
   kernel of that version into `core/graph/frozen/kernel-<version>.yaml`, digests appended to each `SHA256SUMS`),
   raises the version in every file and sentence that states it, and registers the migration step in
   `tools/scale/pgraph_migrate.py`. A breaking change also adds its rewrite rule (`STEP_RULES[<base version>]`).
4. **Check.** `scale schema check --base origin/main` asks for all of it: the version raised by the rule, the
   frozen copy equal to the base (by spec digest), every file stating the new version, the migration step (and
   rule, if breaking), a valid fixture or example that uses what is added, and a CHANGELOG line. CI's
   `specification-changes` job runs it on every pull request that changes the schema (`scale ci spec-changes`)
   and writes its summary (the kind of change and what it adds, loosens, changes, narrows or removes) as the job
   summary for the reviewer.
5. **Review and merge.** One approving review by any reviewer, the person who asked for the change included
   ([`governance/review-policy.yaml`](../governance/review-policy.yaml)). The kind of change tells the reviewer
   what they review; a reviewer who requests changes blocks. Until another reviewer joins, the owner merges their
   own pull requests under the bootstrap rule. If another schema change merged first on the same version, the
   pull request rebases and runs `scale schema bump` again.
6. **Data repositories.** A knowledge-graph data repository kept apart from this one is moved to the new
   version with `scale kg update --data <dir>`: every scale-graph document of the catalysis domain goes to
   the new version through the registered steps, is validated before and after, written in place and its
   evidence index rebuilt; a document a rule cannot map is refused and left untouched, and a file whose name
   pins a version (`*.scale-graph-0.1.0.graph.json`) is kept. Run `--dry-run` first.
7. **Release.** `scale release build vX.Y.Z` (a human action) bundles the schema versions merged since the last
   release; it refuses schema content changed since then under the same version. `releases/vX.Y.Z/RELEASE.yaml`
   records a semantic comparison with the previous release, the versions, the contributors and sha256 digests
   of every file ([governance/release-process.md](../governance/release-process.md)).

`scale graph verify` and the release build check that one version names one content, and that every version a
migration step leads away from is frozen. The two layers are explained in
[core/graph/README.md](../core/graph/README.md).

## Regression checks

`scale check`, on every pull request, re-runs what a schema change could break:

- **Fixtures and examples** validate under the version they pin, and the repository's invalid fixtures
  (`domain/tests/fixtures/invalid/`) must be rejected for the reasons their `expect.yaml` states.
- **Competency questions** (`scale domains cq`) run on public examples and must meet their expectations; a
  change that changes an answer updates the question in the same pull request.
- **The tests** read each document under the version it pins and the head version from the manifest, so a
  version bump does not break them; `test_a_version_bump_keeps_the_tests_green` bumps a copy of the repository
  and runs the whole suite on it.

## Release comparison

`comparison_to_previous` in `RELEASE.yaml` is a semantic diff of the kernel and of the catalysis
assembled schema against the previous release: labels, edge types, properties, enum values and
checklist items added, removed, changed, narrowed or loosened. It is classified as:

- **breaking**: something removed, changed in type or narrowed (a new requirement, fewer allowed
  values or endpoints);
- **additive**: only additions and loosenings, which still need scientific review as provisional
  meaning;
- **identical**: no change in meaning (titles, descriptions and versions aside).

The same diff gives a schema change its kind and the version it needs (`schema_change.diff_specs`, `tier`,
`next_version`).

## Migration

A document pins its schema version, and every earlier version of the schema stays frozen beside the catalysis
manifest once a change has moved it on, so a document is always read under the version it pins. `scale graph
migrate` (or `scale call migrate`) moves it along the version steps (`tools/scale/pgraph_migrate.py`), keeping
every record id. `scale schema bump` registers the step in the pull request that raises the version. An additive
step only raises `schema_version`; a step that changes how records are written has a rule that rewrites the
document and reports every change. A rule that meets a case it cannot map stops with an error instead of
inventing a mapping. At 0.1.0 no step is registered yet.

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
