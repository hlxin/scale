# Governance

This page holds the rules of this repository: the review rule and its bootstrap, how a change flows, schema
versions, the catalysis domain, project data and releases.

SCALE (Shared Concepts, Attributes, and Links with Evidence) is one shared framework for evidence-backed
scientific knowledge graphs across domains. It is developed in [hlxin/scale](https://github.com/hlxin/scale),
a personal repository of its owner, Hongliang Xin (`@hlxin`); its Python package is `scale-catal`. The
repository starts private and is shared with collaborators; the rules are the same before and after it
becomes public ([decision record 0001](../docs/decisions/0001-scale-0.1.0.md)).

The model in one paragraph: **anyone can suggest a change or open a pull request; agents do most of the work; one
person approves and merges.** Every change, whatever it touches (the schema, records, questions, tools,
documentation, governance), is one pull request. A suggestion (an issue or a comment, by a person or an agent)
goes to an agent, which implements it, runs the checks and opens the pull request. Any reviewer approves it, the
person who suggested it included, and merges it. A schema change raises the schema's one version in the same pull
request; a data repository then moves to the new version with one command (`scale kg update`). Agents never
approve or merge.

## Glossary

| term | meaning |
|---|---|
| **two layers** | The specification has two layers: the science kernel and the domains. Catalysis is the first domain and, for now, the only one. Its graph schema is the kernel plus one catalysis file, with one vocabulary and one checklist. There is no repository-wide composition. |
| **science kernel** | The base layer under [`core/`](../core/) ("the core" as a folder): the kernel file `core/graph/kernel.yaml`, declared by `core/CORE.yaml`. |
| **catalysis domain** | The folder [`domain/`](../domain/README.md), declared by its `DOMAIN.yaml` (`domain: catalysis`). Its schema manifest `graph/scale-catal.yaml` assembles the kernel with the catalysis file `catalysis.yaml`. Thermocatalysis, electrocatalysis, photocatalysis and plasma catalysis, and their combinations, all belong to it. |
| **schema version** | One version for the kernel and the catalysis domain together: the catalysis manifest's `version`, which documents pin (0.1.0 today). Every schema change raises it, whichever file it changes: a breaking change the second number, an additive change the third. |
| **checklist** | What a catalysis record must and should report: the catalysis file's `checklist:`, named `catalysis`, selected with `--domain` and declared in a document's `follows_domains`. |
| **suggestion** | An issue or a comment that asks for a change, by a person or an agent. @scale-agents take it up on their own and turn it into a pull request when it asks for a change; anyone may also open one. |
| **reviewers** | The people who approve changes, listed in [`review-policy.yaml`](review-policy.yaml): the owner and the domain experts invited to review. The list is open: more people are added as they join. Any one of them approves a change. |
| **maturity** | Of a concept: `provisional` or `stable`. New concepts enter as provisional. |
| **official release** | A tagged, digested distribution built by the release process: `releases/vX.Y.Z/`, tag `vX.Y.Z`, PyPI `scale-catal` X.Y.Z ([release-process.md](release-process.md)). The first is `v0.1.0`. |

## Who does what

| who | GitHub | what they do |
|---|---|---|
| **owner** | `@hlxin`, admin of the repository, code owner of every path in [`.github/CODEOWNERS`](../.github/CODEOWNERS) | a reviewer: approves and merges pull requests (their own are approved by another reviewer); invites reviewers; builds releases; repository settings, rulesets and secrets ([repository-settings.md](repository-settings.md)) |
| **reviewers** | domain experts, collaborators (Write), added to the review policy and CODEOWNERS when they join; no fixed number | approve and merge pull requests (any one of them is enough). The current list is in [`review-policy.yaml`](review-policy.yaml) |
| **contributors** | anyone: issues and comments; collaborators also branches and pull requests; others through forks once the repository is public | suggest changes, curate, report gaps |
| **@scale-agents** | a team of Claude agents on GitHub, started by every new issue, comment and review (no tag or label), or a manual run | a discovery strategist frames and coordinates, a data scientist proposes the patch and its evidence, a protocol compiler writes the tests, an evidence verifier assesses support and effects, and a systems engineer opens pull requests from `agent/…` branches under the Claude GitHub App's identity; never approves or merges |

## The rule: one approval for every change

- Every update to `main` arrives by pull request. Nobody pushes to `main` directly, and nothing is applied after a
  merge: what merges is what the reviewer approved.
- A pull request merges with **one approving review by a reviewer**, a passing set of required checks, and no
  reviewer asking for changes. Any reviewer may give it, the person who suggested the change included; no
  particular reviewer or code owner has to. To correct a merged change, suggest a new one. This holds for every
  kind of change: documentation, tools, records, schema changes, governance and releases.
- **Anyone opens it; one person approves it and merges it.** Only people approve, by reviewing the pull request
  on GitHub; the GitHub reviews are the approvals, and there is no other approval record to write. A change made
  by an agent needs the same approval.
- **An agent opens a pull request under its own GitHub identity**: the Claude GitHub App in the scale-agents
  workflow, or a bot account for an agent working elsewhere (repository-settings.md, "The agent"), never a
  person's account. GitHub does not let the author of a pull request approve it, so the person who asked for the
  change can approve the agent's pull request.
- **Only real people count.** Every reviewer is a real person who agreed to review (never invented). An entry
  marked `placeholder: true` is nobody: it never counts, and `scale check` warns while one is listed.
- The latest review of each reviewer counts. A reviewer whose latest review requests changes blocks until
  they approve or the review is dismissed; an approval given before new commits were pushed is dismissed.

GitHub enforces the rule through the `main` ruleset: one approving review (a code-owner review is not required;
CODEOWNERS only routes review requests), stale approvals dismissed, the last push approved by someone else,
required checks ([repository-settings.md](repository-settings.md)).

**Kinds of change are information, not approval classes.** CI's summary of a schema change says whether it is
breaking or additive and what it adds, changes or removes, so that the reviewer knows what they review. New
concepts enter as `maturity: provisional`; a later change may promote them to `stable`. There are no comment
periods, no separate approver for provisional concepts and no committee quorum: the approval is the decision.

### Every reviewer is asked; one approval is enough

CODEOWNERS names every reviewer on every line, so GitHub asks all of them to review each new pull request (except
its author); `scale domains check` fails when a reviewer of the review policy is missing from a line. Any one of them
reviews:

- **The first approval decides.** The [reviewers workflow](../.github/workflows/reviewers.yml) withdraws the review
  requests still open and comments who approved; the approver merges once the checks pass. Others need not review.
- **A request for changes blocks.** A reviewer who asks for changes blocks the merge until they approve or their
  review is dismissed, whoever else approved. The agents push the fixes to the same branch.
- **A push asks again.** A push dismisses earlier approvals (the ruleset); the workflow asks again every reviewer
  whose approval it dismissed or who asked for changes. The last pusher cannot give the approval.

### No bypass

The owner is a reviewer and approves other people's and the agent's pull requests as any reviewer does; another
reviewer approves the owner's. Nobody bypasses the ruleset, the owner included: every change to `main` is a pull
request with one approval ([repository-settings.md](repository-settings.md#no-bypass)).

## How a change flows

```
an issue, a comment or a gap report            a new corpus (a sample curated against the schema)
(a person or an agent)                                 │ gap report issue (label gap-report)
        │                                              │
        ▼                                              ▼
@scale-agents take it up on their own                             (or anyone opens a pull request)
        ▼
discovery strategist: frames the use case, decides (answer, question back, change or nothing), coordinates
data scientist: sources, corrections to records or changes to schema definitions, the evidence record
protocol compiler: tests with explicit expected outcomes · evidence verifier: support, counterexamples, effects
systems engineer: version raised, migration assessment, checks → a pull request holding the change set
        ▼
checks: scale check, package, specification-changes (with a summary of a schema change for the reviewer)
        ▼
every reviewer is asked; one, not the author, approves and merges
        ▼
data repositories: scale kg update --data DIR (every document migrated and validated)
        ▼
official release (a human step, release-process.md)
```

1. **Suggest.** Anyone opens an issue or comments, in plain language (the issue forms ask the right questions). A
   gap found while curating is filed with `scale gap issue`. To find what the schema cannot express in a new
   corpus, a curator (or an agent following the curate-source skill) curates a sample of open-access sources
   against the current schema and files a `gap-report` issue (short capped quotes only).
2. **The agents take it up.** `@scale-agents` start on every new issue, comment and review, with no tag or label.
   The discovery strategist frames the use case, decides what it needs and coordinates the revision; the data
   scientist assembles the sources and proposes corrections to records or changes to schema definitions; the
   protocol compiler turns the validation requirements into tests with explicit expected outcomes; the evidence
   verifier assesses the scientific support, the counterexamples and the effects on existing records and queries;
   the systems engineer packages the change set (the patch, the evidence record, the test cases, the migration
   assessment) as a pull request. They follow [`AGENTS.md`](../AGENTS.md) and the skills. They treat issue, comment and
   corpus text as data, never as instructions about permissions, workflows, governance or secrets, and never edit
   releases, frozen versions or workflows; a change to `governance/` or `.github/` that a change needs is listed
   under Governance changes in its pull request
   ([`.github/scale-agents/instructions.md`](../.github/scale-agents/instructions.md)). Anyone may also open a pull request
   directly, with their own agent or by hand.
3. **Review.** CI runs the checks and, for a schema change, writes the summary. A reviewer comments or asks
   for changes on the pull request (the agents push the fixes to their own pull requests), or approves and merges.
4. **Data repositories.** Whoever keeps a knowledge-graph data repository runs `scale kg update --data DIR` there:
   every scale-catal document is moved to the new version through the registered migration steps, validated and
   its evidence index rebuilt. A document a step rule cannot migrate is reported and left untouched.

Releases stay a human step: [release-process.md](release-process.md).

## Schema changes

A schema change edits the schema files (`core/graph/kernel.yaml`, `domain/graph/catalysis.yaml`) directly and
raises the schema's one version in the same pull request, whichever file it changes: a breaking change (something
removed, changed or narrowed) raises the second number (0.1.0 -> 0.2.0), an additive change the third
(0.1.0 -> 0.1.1). `scale schema bump` freezes the version it replaces (the catalysis manifest and file in
`domain/graph/frozen/`, the kernel in `core/graph/frozen/`), so that documents pinning it stay valid, raises the
version in every file that states it and registers the migration step; a breaking change also carries the rule
that rewrites documents. `scale schema check` (CI's `specification-changes` job) checks all of it, that a test uses
what is added and that the CHANGELOG says what changed. If two schema changes are open on the same version, the
second rebases and bumps again after the first merges. The procedure is
[`skills/evolve-schema/SKILL.md`](../skills/evolve-schema/SKILL.md);
[docs/evolution.md](../docs/evolution.md) explains the versions. Open themes stay in the gap register
(`docs/gaps/register.json`) until a later change answers them.

## The community path

- **Anyone** comments and opens issues (plain-language forms). People who do not use Git submit content
  through the [contribution form](https://github.com/hlxin/scale/issues/new?template=contribution.yml); the pull
  request that carries it credits them ([credit-and-authorship.md](credit-and-authorship.md)).
- **Weekly digest.** A workflow groups the week's feedback into topics with options and opens a feedback
  digest issue. It decides nothing; a person acts on a topic by handing it to the agent or opening a pull request
  ([feedback.md](feedback.md)).
- **Reviewers.** The owner invites reviewers; there is no fixed number. Adding one edits `review-policy.yaml`,
  `core/CORE.yaml`, `domain/DOMAIN.yaml` and CODEOWNERS
  ([repository-settings.md](repository-settings.md#2-collaborators-and-reviewers)).
- **Domain maintainers.** People who look after the catalysis domain are listed in `domain/DOMAIN.yaml`
  ([working-groups.md](working-groups.md)) and, as code owners, on the `/domain/` line of CODEOWNERS.

## The catalysis domain

Catalysis is the first domain (`domain/`, `status: stable`, `founding: true`), built on the science kernel
and listed in `scale-release.yaml`. It extends the kernel (`is_a`, `extends`, or `adds_properties` with a
new key), never redeclares a label, edge type or property the kernel declares, and never copies kernel files
(`scale domains check`). A second domain would revisit the one-folder layout and how the one version spans
several domains, in a decision record.

## Disagreement

Scientific disagreement is represented, not resolved, by the schema: conflicting claims coexist with
their sources and scope (`contradicts` links). When reviewers disagree about a representation, a reviewer
asks for changes and the discussion stays on the pull request. Conduct is covered by the
[code of conduct](../CODE_OF_CONDUCT.md).

## Decision records

Decisions about the project itself get a record in `docs/decisions/NNNN-*.md` (numbering from 0001), written in a
pull request. Everyday changes need none: the pull request, its review and the CHANGELOG are the record.
[Decision record 0001](../docs/decisions/0001-scale-0.1.0.md) holds the decisions this repository started with.

## Project data

Shared definitions do not make restricted records public. Every document committed here is public
(`access: public`, checked by `scale check`); project data that is not cleared for publication is never
committed and stays in a data repository of its own ([licensing.md](licensing.md)). Laboratories may keep
their records in their own databases, pin an official release and contribute back definitions, mappings,
competency questions or synthetic fixtures.

## Releases and licence

Releases are immutable and digested (`releases/vX.Y.Z/RELEASE.yaml`) and built by a person
([release-process.md](release-process.md)): the tag, the PyPI package version and the release directory
always agree. The first is `v0.1.0`.

Code is under the MIT licence ([LICENSE](../LICENSE)); the vocabulary, curated records and documentation
are under CC-BY-4.0; third-party material stays under its owners' terms ([NOTICE](../NOTICE)).
[REUSE.toml](../REUSE.toml) gives every file its licence, and contributions come in under the licence of
their path ([licensing.md](licensing.md)). The contribution model does not change licence rights. "Official
SCALE release" names what this process produces; it is not a licence restriction.

## Changing this document

Everything under `governance/` changes by pull request with one approval, like everything else.
