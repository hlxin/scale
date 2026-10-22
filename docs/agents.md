# Agents and people: who does what

SCALE's tools are deterministic. The judgment work (reading a source, choosing what to record,
writing a query plan, drafting a schema change) is done by a person or by an agent that follows a
versioned skill ([`skills/`](../skills)). Agents do the work; people decide.

| work | done by | with | what the tools check |
|---|---|---|---|
| find and index the sources of a topic, and freeze a corpus | a person or an agent | [index-sources](../skills/index-sources/SKILL.md) (its scripts) | `scale corpus check` on the frozen corpus |
| curate a source, a data file or a corpus into scale-catal documents | a person or an agent | [curate-corpus](../skills/curate-corpus/SKILL.md); `scale_template`, `scale_describe`, `scale_validate` | validity, checklist conformance, verbatim quotes (`--source-text`), REPORTED_IN backed by evidence |
| answer a question | a person or an agent | [query-graph](../skills/query-graph/SKILL.md); `scale_query`, `scale_search` | the plan's labels and properties exist (else `schema_gap`); values are returned as reported; absences are typed |
| make a schema change | an agent (or a person) | [evolve-schema](../skills/evolve-schema/SKILL.md); `scale schema diff \| bump \| check` | the semantic diff and its kind (breaking or additive), the version raised by the rule, the base version frozen, the migration step (and rule, if breaking), a test for what is added, a CHANGELOG line; the competency questions (`scale check`) |
| triage community feedback | an agent (rules or any external system) | [triage-feedback](../skills/triage-feedback/SKILL.md); `scale triage` | proposals are validated; none may contain a decision |
| implement a suggested change and open a pull request, from an issue, a comment or a corpus | `@scale-agents` (a team of Claude agents on GitHub, started by every new issue, comment and review by a collaborator, and anyone else's once a collaborator comments on it: a discovery strategist, a data scientist, a protocol compiler, an evidence verifier and a systems engineer) | [.github/scale-agents/instructions.md](../.github/scale-agents/instructions.md), [.github/scale-agents/roles/](../.github/scale-agents/roles/), the skills above; a pull request under the agent's own GitHub identity (the Claude GitHub App, or a bot account) | the pull request's checks (specification-changes writes the summary of a schema change) |
| approve and merge pull requests, release, file issues | people only | GitHub reviews (one reviewer, who then merges), `scale release build`, `scale gap issue --submit` | the review policy ([governance/review-policy.yaml](../governance/review-policy.yaml)) and the `main` ruleset |

The agent tools (`scale call`, MCP, HTTP, Python; [integrate.md](integrate.md)) cover curating,
validating, querying, searching and migrating documents. No agent tool approves or merges a
pull request, builds a release or files an issue; `scale_status` lists those human actions with the
commands a person runs.

## What is real and what is left to the host

**Real (executed and tested).** Document validation and checklist conformance; verbatim quote
checks; graph queries with typed absences; evidence search; document migration along the schema's
version steps; schema changes on a branch (`scale schema diff | bump | check`: semantic diff, kind, the version
raised by the rule, the base frozen, the migration step, tests and CHANGELOG checked); the pull-request checks
(`scale ci spec-changes`); updating a data repository to a new schema version (`scale kg update`); release builds
with a semantic comparison to the previous release; competency questions with expected answers
(`scale domains cq`).

**Left to the host.** Language-model extraction of documents, natural-language-to-plan translation
and the text of a schema change happen in whatever host follows the skills. No model is bundled.

## Independence

Agents that share a model or a source corpus are not independent reviewers. Deterministic tests,
distinct evidence checks and human judgment complement agent work; they do not turn agent agreement into community consensus.

## Running with a model host

Any host that can read `SKILL.md` files and run shell commands can drive SCALE: the skill names
the allowed `scale` commands, the expected outputs, the validation to run and when to stop for
human review. Nothing in the repository depends on a particular provider.
