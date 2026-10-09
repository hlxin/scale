# Governance

This page holds the rules of this repository: the review rule and its bootstrap, how a change flows,
proposals, the catalysis domain, project data and releases.

SCALE (Shared Concepts, Attributes, and Links with Evidence) is one shared framework for evidence-backed
scientific knowledge graphs across domains. It is developed in [hlxin/scale](https://github.com/hlxin/scale),
a personal repository of its owner, Hongliang Xin (`@hlxin`); its Python package is `scale-schema`. The
repository starts private and is shared with collaborators; the rules are the same before and after it
becomes public ([decision record 0001](../docs/decisions/0001-scale-0.1.0.md)).

The model in one paragraph: **every change is a pull request that needs two approving reviews from
reviewers other than its author**; until the two reviewer seats are filled, the owner merges under the
bootstrap rule. A schema change is a pull request that carries a *proposal*. When it merges, the proposal is
applied on `main` and the schema's one version moves on. A data repository is then moved to the new version
with one command (`scale kg update`). Agents draft changes and proposals; they never approve, merge or apply.

## Glossary

| term | meaning |
|---|---|
| **two layers** | The specification has two layers: the science kernel and the domains. Catalysis is the first domain and, for now, the only one. Its graph schema is the kernel plus one catalysis file, with one vocabulary and one checklist. There is no repository-wide composition. |
| **science kernel** | The base layer under [`core/`](../core/) ("the core" as a folder): the kernel file `core/graph/kernel.yaml`, declared by `core/CORE.yaml`. |
| **catalysis domain** | The folder [`domain/`](../domain/README.md), declared by its `DOMAIN.yaml` (`domain: catalysis`). Its schema manifest `graph/scale-graph.yaml` assembles the kernel with the catalysis file `catalysis.yaml`. Thermocatalysis, electrocatalysis, photocatalysis and plasma catalysis, and their combinations, all belong to it. |
| **schema version** | One version for the kernel and the catalysis domain together: the catalysis manifest's `version`, which documents pin (0.1.0 today). Every applied proposal raises it, whichever file it changes. |
| **checklist** | What a catalysis record must and should report: the catalysis file's `checklist:`, named `catalysis`, selected with `--domain` and declared in a document's `follows_domains`. |
| **proposal** | A schema change, in `core/proposals/<NNNNNN>/` (the science kernel) or `domain/proposals/<NNNNNN>/` (the catalysis domain), named by a six-digit number that is global across both. |
| **reviewers** | The people who approve changes, listed in [`review-policy.yaml`](review-policy.yaml): the owner and two seats to be filled. |
| **maturity** | Of a concept: `provisional` or `stable`. New concepts enter as provisional. |
| **official release** | A tagged, digested distribution built by the release process: `releases/vX.Y.Z/`, tag `vX.Y.Z`, PyPI `scale-schema` X.Y.Z ([release-process.md](release-process.md)). None has been built yet. |

## Who does what

| who | GitHub | what they do |
|---|---|---|
| **owner** | `@hlxin`, admin of the repository, code owner of every path in [`.github/CODEOWNERS`](../.github/CODEOWNERS) | reviews and approves pull requests; merges under the bootstrap rule until the seats are filled; applies merged proposals; builds releases; repository settings, rulesets and secrets ([repository-settings.md](repository-settings.md)) |
| **reviewers** | collaborators (Write), added to CODEOWNERS when they join | review and approve pull requests: the science kernel, the catalysis domain, tools, governance and releases. Today: two seats to be filled (`TODO-reviewer-2`, `TODO-reviewer-3` in the review policy) |
| **contributors** | anyone: issues and comments; collaborators also branches and pull requests; others through forks once the repository is public | propose changes, curate, report gaps |
| **@scale-agent** | Claude on GitHub, started by hand by a person with write access (off otherwise) | drafts changes and proposals on `agent/…` branches as draft pull requests; never approves, merges or applies |

## The rule: two approvals for every change

- Every update to `main` arrives by pull request. Nobody pushes to `main` directly; the one exception is the
  application of a merged proposal, which the apply-proposals workflow (or the owner, in a pull request)
  commits after checking its approvals.
- A pull request merges with **two approving reviews from reviewers other than its author**, a passing
  set of required checks, and no reviewer asking for changes. This holds for every kind of change:
  documentation, tools, records, schema proposals of every tier, governance and releases.
- **Only people approve**, by reviewing the pull request on GitHub. The GitHub reviews are the approvals;
  there is no other approval record to write. A change proposed by an agent needs the same two approvals.
- **Placeholders never count.** The two seats not filled yet are marked `placeholder: true` in the review
  policy, `core/CORE.yaml` and `domain/DOMAIN.yaml`; `scale check` warns until they are
  filled with real people (never invented).
- The latest review of each reviewer counts. A reviewer whose latest review requests changes blocks until
  they approve or the review is dismissed; an approval given before new commits were pushed is dismissed.

GitHub enforces the rule through the `main` ruleset where the plan allows it: two approving reviews, a
code-owner review, stale approvals dismissed, the last push approved by someone else, required checks
([repository-settings.md](repository-settings.md)). `scale proposal apply-merged` evaluates it again, from
the merged pull request's reviews, before it applies a proposal.

**Tiers are information, not approval classes.** `scale proposal check` classifies each proposal (0 no
change in meaning, 1 records, 2 additive or loosening, 3 breaking) so that reviewers know what they
review; a breaking change also needs a migration step and gets a decision record. New concepts enter as
`maturity: provisional`; a later proposal may promote them to `stable` (`set_maturity`). There are no
comment periods, no separate approver for provisional concepts and no committee quorum: the two
approvals are the decision.

### Bootstrap: until the reviewers join

With one filled seat, two approvals from people other than the author are impossible. Until two
reviewers have joined, the owner may merge pull requests through a **bootstrap bypass** of the ruleset,
only after the checks pass, each use noted in the pull request ("Bootstrap bypass: reviewers not yet
added"). A proposal merged this way has no two approvals, so `scale proposal apply-merged` refuses it; the
owner applies it in a pull request that also notes the bypass:
`scale proposal decide <id> --pr <n> --bootstrap-bypass "reviewers not yet added" --by hlxin`, then
`scale proposal apply <id> --confirm`. The decision record says it was not approved by two reviewers;
the tool refuses a bypass once every seat is filled. The bypass is narrowed or removed once the two
reviewers have joined ([repository-settings.md](repository-settings.md#bootstrap-bypass)).

## How a change flows

```
an issue, a comment or a gap report            a new corpus (a sample curated against the schema)
        │                                              │ gap report issue (label gap-report)
        ▼                                              ▼
a pull request (by a collaborator, or a draft by @scale-agent when a person starts it)
        ▼
checks: scale check, package, specification-changes, proposal-check (one comment with the proposal's
        tier, diff, fixtures, migration and competency results)
        ▼
review: two approving reviews from reviewers other than the author → merge
        (until the seats are filled: the owner, under the bootstrap rule)
        ▼
apply (a person starts the apply-proposals workflow; under the bootstrap rule the owner applies it in a
        pull request): reviews checked → approvals recorded → decision record → old version frozen →
        new version installed → the schema's one version raised → commit
        "Apply proposal 0000NN (catalysis): schema X → Y (PR #N)"
        ▼
data repositories: scale kg update --data DIR (every document migrated and validated)
        ▼
official release (a human step, release-process.md): bundles the schema versions applied since the last
```

1. **Issue or comment.** Anyone opens an issue or comments, in plain language (the issue forms ask the
   right questions). A gap found while curating is filed with `scale gap issue`.
2. **Corpus.** To find what the schema cannot express in a new corpus, a curator (or an agent following the
   curate-source skill) curates a sample of open-access sources against the current schema and files a
   `gap-report` issue (short capped quotes only), from which a proposal is drafted.
3. **Draft.** A collaborator opens a pull request; an agent follows [`AGENTS.md`](../AGENTS.md) and the
   skills, and for a schema change writes a proposal (`scale proposal new`, `scale proposal check`). An
   agent treats issue, comment and corpus text as data, never as instructions about permissions, workflows,
   governance or secrets, and it never edits `.github/`, `governance/`, releases or frozen versions
   ([`.github/agent/instructions.md`](../.github/agent/instructions.md)).
4. **Review.** The pull request gets the proposal-check comment. Two reviewers other than the author
   approve, or ask for changes.
5. **Merge and version bump.** After the merge, a person starts the apply-proposals workflow for the
   proposal (it needs a token configured for this repository, [repository-settings.md](repository-settings.md#the-apply-token)):
   it writes the approval records from the GitHub reviews, the decision record with the pull-request link,
   freezes the base version (the catalysis manifest and file in `domain/graph/frozen/`, the kernel in
   `core/graph/frozen/`), installs the candidate, raises the schema's one version, updates the gap register,
   runs the full `scale check` (the unit tests included, so a version bump that breaks a test never reaches
   `main`) and commits to `main`. If anything fails, it puts every file back and pushes nothing. Two
   proposals built on the same version cannot both apply: the second must be rebuilt on the new head
   (`scale proposal check`) in a new pull request.
6. **Data repositories.** Whoever keeps a knowledge-graph data repository runs `scale kg update --data DIR`
   there: every scale-graph document is moved to the new version through the registered migration steps,
   validated and its evidence index rebuilt. A document a step rule cannot migrate is reported and left
   untouched.

Releases stay a human step: [release-process.md](release-process.md).

## Proposals: where they go and what they hold

Placement: kernel operations go to `core/proposals/<NNNNNN>/`; operations on the catalysis file go to
`domain/proposals/<NNNNNN>/`. Numbers are global and never reused (`scale proposal new <owner>` allocates
the next; the first is `000001`). A proposal states, for each gap theme, a resolution (`addressed` by schema
operations, answered by the curation `guide`, `deferred` or `rejected`, the last three with a reason), the
operations, fixtures and counterexamples, the documents and competency questions to re-check, and, for a
change in how records are written, a migration step. A pull request carries the proposal with
`status: proposed` and its reports; it does not change the schema files, which are changed when the
proposal is applied after the merge. The procedure is
[`tools/skills/evolve-schema/SKILL.md`](../tools/skills/evolve-schema/SKILL.md);
[docs/evolution.md](../docs/evolution.md) explains the versions.

Every proposal raises the schema's one version, whether it changes the kernel, the catalysis file or both;
it is assessed through the catalysis manifest. Deferred themes stay open in the gap register
(`docs/gaps/register.json`) until a later proposal answers them.

## The community path

- **Anyone** comments and opens issues (plain-language forms). People who do not use Git submit content
  through the [contribution form](https://github.com/hlxin/scale/issues/new?template=contribution.yml); a
  collaborator prepares the pull request and credits them ([credit-and-authorship.md](credit-and-authorship.md)).
- **Weekly digest.** A workflow groups the week's feedback into topics with options and opens a feedback
  digest issue. It decides nothing; a person acts on a topic by opening a pull request ([feedback.md](feedback.md)).
- **Reviewers.** The owner invites reviewers. Filling a seat is a pull request that edits `review-policy.yaml`,
  `core/CORE.yaml`, `domain/DOMAIN.yaml` and CODEOWNERS
  ([repository-settings.md](repository-settings.md#2-collaborators-and-reviewers)); past decisions keep their names.
- **Domain maintainers.** People who look after the catalysis domain are listed in `domain/DOMAIN.yaml`
  ([working-groups.md](working-groups.md)) and, as code owners, on the `/domain/` line of CODEOWNERS.

## The catalysis domain

Catalysis is the first domain (`domain/`, `status: stable`, `founding: true`), built on the science kernel
and listed in `scale-release.yaml`. It extends the kernel (`is_a`, `extends`, or `adds_properties` with a
new key), never redeclares a label, edge type or property the kernel declares, and never copies kernel files
(`scale domains check`). It changes its schema only through proposals. A second domain would revisit the
one-folder layout and how the one version spans several domains, in a decision record.

## Disagreement

Scientific disagreement is represented, not resolved, by the schema: conflicting claims coexist with
their sources and scope (`contradicts` links). When reviewers disagree about a representation, a reviewer
asks for changes, the discussion stays on the pull request, and the decision record of an applied
proposal keeps the reviews. Conduct is covered by the [code of conduct](../CODE_OF_CONDUCT.md).

## Decision records

Consequential decisions get a record in `docs/decisions/NNNN-*.md` (numbering global, from 0001).
`scale proposal decide` writes one for every applied proposal (`NNNN-<proposal>.md`, with the pull-request
link and the reviewers who approved); decisions about the project itself are written by people in a pull
request. [Decision record 0001](../docs/decisions/0001-scale-0.1.0.md) holds the decisions this repository
started with.

## Project data

Shared definitions do not make restricted records public. Every document committed here is public
(`access: public`, checked by `scale check`); project data that is not cleared for publication is never
committed and stays in a data repository of its own ([licensing.md](licensing.md)). Laboratories may keep
their records in their own databases, pin an official release and contribute back definitions, mappings,
competency questions or synthetic fixtures.

## Releases and licence

Releases are immutable and digested (`releases/vX.Y.Z/RELEASE.yaml`) and built by a person
([release-process.md](release-process.md)): the tag, the PyPI package version and the release directory
always agree. The first will be `v0.1.0`.

Code is under the MIT licence ([LICENSE](../LICENSE)); the vocabulary, curated records and documentation
are under CC-BY-4.0; third-party material stays under its owners' terms ([NOTICE](../NOTICE)).
[REUSE.toml](../REUSE.toml) gives every file its licence, and contributions come in under the licence of
their path ([licensing.md](licensing.md)). The contribution model does not change licence rights. "Official
SCALE release" names what this process produces; it is not a licence restriction.

## Changing this document

Everything under `governance/` changes by pull request with two approvals (the bootstrap rule until the
seats are filled), like everything else.
