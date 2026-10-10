<!-- Every pull request to main needs one approving review by a reviewer (governance/review-policy.yaml), the
person who suggested the change included; until another reviewer joins, the owner merges their own under the
bootstrap rule. For a schema change, CI's specification-changes job writes a summary for the reviewer. See
CONTRIBUTING.md and governance/GOVERNANCE.md. -->

## Summary

<!-- What changes, and why. Link the issue or comment it answers (e.g. "Closes #12"). If an agent drafted
it (@scale-agents), say which request it answers; the agents fill in the change set below. If merged under the bootstrap rule, write "Bootstrap bypass:
reviewers not yet added". -->

## Change set

<!-- What a reviewer needs to accept, request revision or reject: -->

- **Proposed patch:** <!-- what changed, file by file -->
- **Evidence record:** <!-- the sources, quotes and locators that justify it; the existing concepts considered -->
- **Test cases and expected outcomes:** <!-- fixtures that pass, counterexamples that fail and why, competency questions and their answers -->
- **Migration assessment:** <!-- breaking or additive, the version raised, the effect on existing records and queries (scale schema check, scale kg update --dry-run) -->
- **Verification:** <!-- the evidence verifier's report, or how you checked it -->

## Type

- [ ] **Schema change**: `core/graph/kernel.yaml` (the science kernel) or `domain/graph/catalysis.yaml` (the catalysis domain), with the version raised
- [ ] **Catalysis domain**: competency questions, examples or docs inside `domain/` (no schema change)
- [ ] **Records**: curated records or curation bundles
- [ ] **Governance**: `governance/`, `.github/`, this template, the review policy
- [ ] **Release**: a new `releases/v<version>/` or a change to `scale-release.yaml`
- [ ] **Tooling**: `tools/`, `docs/`, packaging

Part affected (the catalysis domain or the science kernel):

## Checks

- [ ] `uv run --extra dev scale check` passes (or `scale check` in your environment)
- [ ] `scale ci spec-changes --base origin/main` passes
- [ ] A schema change raises the version with `scale schema bump --base origin/main` (breaking: the second number; additive: the third) and passes `scale schema check --base origin/main`
- [ ] Schema changes: `maturity: provisional` for new concepts, a fixture and a counterexample, a migration rule if breaking, the competency questions that change updated, the existing concepts considered, a CHANGELOG line
- [ ] New behaviour has tests; `docs/implementation-status.yaml` is updated
- [ ] Curated evidence uses short excerpts only, within the copyright cap of the folder's `rights.yaml`; every committed document states `access: public` (project data not cleared for publication is never committed)
- [ ] No file inside an existing release directory (`releases/<id>/`) is modified, deleted or added, and no existing frozen file under `core/graph/frozen/` or `domain/graph/frozen/` is modified or deleted (`scale schema bump` only adds them)

## Licence and credit

- [ ] My contribution is licensed under the licence `REUSE.toml` gives its path (code MIT; vocabulary, records and documentation CC-BY-4.0), and I have the right to contribute it (sign-off with `git commit -s` is recommended, not required)
- [ ] Third-party material under other terms has a `REUSE.toml` entry, its text in `LICENSES/` and a line in `NOTICE`, or there is none

- [ ] Every person who contributed is credited with a commit trailer, one per person:
      `Co-authored-by: Name <ID+username@users.noreply.github.com>`
- [ ] Contributions sent through an issue: link the issue. If the submitter consented, they are added to
      `contributors` in `domain/DOMAIN.yaml` (or `core/CORE.yaml`)

Submitted through issue:
