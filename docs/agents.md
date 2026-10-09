# Agents and people: who does what

SCALE's tools are deterministic. The judgment work (reading a source, choosing what to record,
writing a query plan, drafting a schema change) is done by a person or by an agent that follows a
versioned skill ([`tools/skills/`](../tools/skills)). Agents propose; people decide.

| work | done by | with | what the tools check |
|---|---|---|---|
| curate a source into a scale-graph document | a person or an agent | [curate-source](../tools/skills/curate-source/SKILL.md); `scale_template`, `scale_describe`, `scale_validate` | validity, checklist conformance, verbatim quotes (`--source-text`), REPORTED_IN backed by evidence |
| answer a question | a person or an agent | [query-graph](../tools/skills/query-graph/SKILL.md); `scale_query`, `scale_search` | the plan's labels and properties exist (else `schema_gap`); values are returned as reported; absences are typed |
| draft a schema change proposal | a person or an agent | [evolve-schema](../tools/skills/evolve-schema/SKILL.md); `scale proposal new \| build \| check` | the semantic diff and its tier, fixtures and counterexamples, the migration of assessed documents, competency questions before and after, a critic report and the PR body |
| triage community feedback | an agent (rules or any external system) | [triage-feedback](../tools/skills/triage-feedback/SKILL.md); `scale triage` | proposals are validated; none may contain a decision |
| draft a change on GitHub from a person's request or a corpus | `@scale-agent` (Claude on GitHub; off unless a person with write access starts its workflow by hand) | [.github/agent/instructions.md](../.github/agent/instructions.md), the skills above; a draft pull request | the pull request's checks (proposal-check posts the proposal's summary) |
| approve and merge pull requests, release, file issues | people only | GitHub reviews (two reviewers other than the author), `scale release build`, `scale gap issue --submit` | the review policy ([governance/review-policy.yaml](../governance/review-policy.yaml)) and the `main` ruleset |
| decide and apply a merged proposal | the apply-proposals workflow, started by a person, from the merged pull request's reviews (or the owner under the bootstrap rule) | `scale proposal apply-merged` (`scale proposal decide --bootstrap-bypass`, `apply --confirm`) | the review policy again, then the full `scale check`; all or nothing |

The agent tools (`scale call`, MCP, HTTP, Python; [integrate.md](integrate.md)) cover curating,
validating, querying, searching and migrating documents. No agent tool approves, applies a
proposal, builds a release or files an issue (the apply-proposals workflow applies only what people merged); `scale_status` lists those human actions with the
commands a person runs.

## What is real and what is left to the host

**Real (executed and tested).** Document validation and checklist conformance; verbatim quote
checks; graph queries with typed absences; evidence search; document migration along the schema's
version steps; proposal build and check (candidate schema, semantic diff, tier, fixtures, migration
assessment, competency re-runs, critic objections, PR body); approval records from GitHub reviews and the
policy evaluation; decision records; applying a merged proposal (freezing the base version), all or nothing;
updating a data repository to a new schema version (`scale kg update`); release builds that
name the applied proposals; competency questions with expected answers (`scale domains cq`).

**Left to the host.** Language-model extraction of documents, natural-language-to-plan translation
and the text of a proposal happen in whatever host follows the skills. No model is bundled.

## Independence

Agents that share a model or a source corpus are not independent reviewers. The proposal critic
records this as an advisory objection. Deterministic tests, distinct evidence checks and human
judgment complement agent proposals; they do not turn agent agreement into community consensus.

## Running with a model host

Any host that can read `SKILL.md` files and run shell commands can drive SCALE: the skill names
the allowed `scale` commands, the expected outputs, the validation to run and when to stop for
human review. Nothing in the repository depends on a particular provider.
