<!-- Every pull request to main needs two approving reviews from reviewers other than its author
(governance/review-policy.yaml; until the reviewer seats are filled, the owner merges under the bootstrap
rule). For a schema change, the proposal-check workflow posts the proposal's summary as a comment; after the
merge, the proposal is applied and the schema's one version moves on. See CONTRIBUTING.md and
governance/GOVERNANCE.md. -->

## Summary

<!-- What changes, and why. Link the issue or comment it answers (e.g. "Closes #12"). If an agent drafted
it (@scale-agent), say which request it answers. If merged under the bootstrap rule, write "Bootstrap bypass:
reviewers not yet added". -->

## Type

- [ ] **Schema proposal**: a new or revised proposal in `core/proposals/<NNNNNN>/` (the science kernel) or `domain/proposals/<NNNNNN>/` (the catalysis domain)
- [ ] **Catalysis domain**: competency questions, examples or docs inside `domain/` (no schema change)
- [ ] **Records**: curated records or curation bundles
- [ ] **Governance**: `governance/`, `.github/`, this template, the review policy
- [ ] **Release**: a new `releases/v<version>/` or a change to `scale-release.yaml`
- [ ] **Tooling**: `tools/`, `docs/`, packaging

Part affected (the catalysis domain or the science kernel):

## Checks

- [ ] `uv run --extra dev scale check` passes (or `scale check` in your environment)
- [ ] `scale ci spec-changes --base origin/main` passes
- [ ] A schema change is a proposal (`scale proposal new <owner> --title "…"` allocates the next six-digit number) with `status: proposed`, checked with `scale proposal check <id>`; the schema files themselves are changed when the proposal is applied after the merge, not in this pull request
- [ ] Schema changes: `maturity: provisional` for new concepts, fixtures and counterexamples, migration outcomes, `expected_query_changes`, `mappings_considered`
- [ ] New behaviour has tests; `docs/implementation-status.yaml` is updated
- [ ] Curated evidence uses short excerpts only, within the copyright cap of the folder's `rights.yaml`; every committed document states `access: public` (project data not cleared for publication is never committed)
- [ ] No file inside an existing release directory (`releases/<id>/`) is modified, deleted or added, and no existing frozen file under `core/graph/frozen/` or `domain/graph/frozen/` is modified or deleted

## Licence and credit

- [ ] My contribution is licensed under the licence `REUSE.toml` gives its path (code MIT; vocabulary, records and documentation CC-BY-4.0), and I have the right to contribute it (sign-off with `git commit -s` is recommended, not required)
- [ ] Third-party material under other terms has a `REUSE.toml` entry, its text in `LICENSES/` and a line in `NOTICE`, or there is none

- [ ] Every person who contributed is credited with a commit trailer, one per person:
      `Co-authored-by: Name <ID+username@users.noreply.github.com>`
- [ ] Contributions sent through an issue: link the issue. If the submitter consented, they are added to
      `contributors` in `domain/DOMAIN.yaml` (or `core/CORE.yaml`)

Submitted through issue:
