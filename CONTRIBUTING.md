# Contributing to SCALE

**One repository, one review process.** SCALE (Shared Concepts, Attributes, and Links with Evidence) is one
shared framework for evidence-backed scientific knowledge graphs across domains, developed in this
repository, `hlxin/scale`, a personal repository of its owner, Hongliang Xin. Contributions extend the science
kernel or a domain (catalysis is the first) and follow shared compatibility, provenance and release
requirements. Provisional concepts are welcome when their status and scope are explicit. Official SCALE
releases follow the documented review and publication process. This contribution model does not alter rights
granted by the project's licences.

The [code of conduct](CODE_OF_CONDUCT.md) governs participation; [governance/GOVERNANCE.md](governance/GOVERNANCE.md)
holds the rules. New to SCALE? Start with the [README](README.md).

Thank you for helping. Contributions of every size are welcome: an issue describing a scientific
use case in ordinary language is as valuable as a schema change proposal.

## How a change is made

```
an issue or a comment                        or open a pull request yourself
        │                                            (a branch here: <github-handle>/<topic>; a fork once public)
        ▼
a pull request (a person, or an agent: @scale-agent on agent/<run>-<short> when a person starts it)
        │  for a schema change, a proposal checked with `scale proposal check`
        ▼
checks (scale check, package, specification-changes, proposal-check) and review:
        │  ONE approving review from any reviewer other than the author
        │  (the owner is a reviewer; the owner's own pull requests: the bootstrap rule until a second reviewer joins)
        ▼
the approving person merges to main; the branch is deleted
        │  a schema proposal is then applied: the schema's one version moves on
        ▼
data repositories are updated to it (`scale kg update`); later an official release
```

1. **Comment.** Write what you need in plain language on an issue (the forms below) or on a pull request.
2. **Or open a pull request.** Branch `<github-handle>/<topic>`, run `uv run --extra dev scale check`, push,
   open the pull request. For a schema change, add a proposal (below).
3. **Review.** Every pull request needs **one approving review from a reviewer other than its author**
   ([governance/review-policy.yaml](governance/review-policy.yaml), where the reviewers are listed); any
   reviewer may give it. A reviewer who asks for changes blocks until they approve. A reviewer who disagrees
   with a merged change corrects it with a pull request of their own. The owner is a reviewer and approves
   other people's pull requests; GitHub does not let an author approve their own, so until a second reviewer
   joins, the owner merges their own pull requests under the bootstrap rule ([governance/GOVERNANCE.md](governance/GOVERNANCE.md#bootstrap-until-the-reviewers-join)).
4. **After the merge.** A schema proposal (`status: proposed`) is applied on `main`: a person starts the
   apply-proposals workflow, which records the reviews, writes the decision record, freezes the old version
   and installs the new one (under the bootstrap rule the owner applies it in a pull request). You do not
   apply it yourself, and the pull request does not change the schema files.
5. **Data.** Whoever keeps a knowledge-graph data repository moves it to the new schema version with
   `scale kg update`.

`@scale-agent` (Claude on GitHub) is off: a person with write access may start its workflow by hand with a
request; it then opens a pull request under the Claude GitHub App's identity, following [AGENTS.md](AGENTS.md)
and the skills, and never approves, merges or applies. Any agent may open a pull request the same way, under its
own GitHub identity (a bot account), never under a person's: a person approves it and merges it.

## Access levels

The repository is private for now and shared with collaborators.

| GitHub role | who | what it allows |
|---|---|---|
| — | everyone, once the repository is public | read, open issues, comment, fork and open pull requests from a fork |
| Write | collaborators the owner invites, the reviewers among them | push branches, open and update pull requests, start the manual workflows |
| reviewer | the reviewers of the review policy, code owners in `.github/CODEOWNERS` | the approvals every pull request needs (two, not the author's own) |
| Admin | the owner, `@hlxin` | repository settings, rulesets, collaborators and secrets |

- **CODEOWNERS routes review; it does not restrict writes.** What protects `main` is the branch ruleset:
  a pull request, one approval from any reviewer (not necessarily a code owner), passing required checks, no force pushes and no
  deletion ([governance/repository-settings.md](governance/repository-settings.md)).
- **Write access is a trust grant.** It lets a collaborator start workflows and run them from a branch, and
  such a run can read the repository's secrets.

## Branches

- **Names:** `<github-handle>/<topic>` for your own work (`hlxin/fix-rhe-note`), or `catalysis/<topic>`
  for work shared on the catalysis domain (`catalysis/one-checklist`). Lowercase, words joined by `-`.
- **Reserved prefixes:** `agent/` is the agent's (`agent/<run>-<short>`), `release/` is for release
  pull requests (`release/vX.Y.Z`, [governance/release-process.md](governance/release-process.md)). Do not
  use them for other work.
- **Temporary:** one topic, one pull request; the branch is deleted when it merges. There are no permanent
  lab or working-group branches.
- Keep a branch current by merging or rebasing `main`. A push after approval needs fresh approvals.

## If you do not use Git

You do not need to know the schema, the code or Git.

- Open a **[comment or suggestion](https://github.com/hlxin/scale/issues/new?template=comment.yml)**.
- Click 💬 next to any record in a record catalogue (`scale catalogue <document>` renders one).
- Send content (a curation, data, a correction, a competency question) with the
  **[contribution form](https://github.com/hlxin/scale/issues/new?template=contribution.yml)**,
  and say how you want to be credited.
- Comment on any pull request or line.

For a submission, a collaborator prepares the pull request and adds you as co-author with a
`Co-authored-by:` trailer (the `<id>+<user>@users.noreply.github.com` form unless you give another
address). With your consent, you are also added to `contributors` in `domain/DOMAIN.yaml` (or
`core/CORE.yaml`), from which release manifests take their credits. Nobody is credited without consent
([governance/credit-and-authorship.md](governance/credit-and-authorship.md)).

Every comment is read. Each week, feedback is grouped into topics with options in a feedback digest
issue; you get a link to it on your thread ([governance/feedback.md](governance/feedback.md)).

## Setup

```bash
git clone https://github.com/hlxin/scale && cd scale && uv run --extra dev scale check
```

[uv](https://docs.astral.sh/uv/) creates the environment on first use. `scale check` runs every
check of CI's `test` jobs: tests, release digests, the scale-graph schema and its frozen versions, the
catalysis and kernel declarations and their one version (`scale domains check`), the competency questions
(`scale domains cq`), publication rights, licences (`reuse lint`), style, documentation links and the invalid
fixtures. Run it before every pull request; `--fast` skips the tests. The other required checks are
`package` (builds the wheel and smoke-tests it from outside the checkout), `specification-changes`
(run it locally with `scale ci spec-changes --base origin/main`) and `proposal-check` (checks every
proposal the pull request changes and posts one comment with the results; locally
`scale ci proposal-check --base origin/main`). `scale check` also warns while reviewer seats in the review
policy are placeholders. Without uv: `pip install -e ".[dev]" && scale check`.

`scale ci spec-changes --base origin/main` shows what CI will say about your branch: which
specification files changed, whether a proposal or decision record covers them, and which
owners must review.

## Ways to contribute

### 1. Report a representational problem
Open an issue with the matching template:

- **Missing concept**: the representation cannot express a distinction a source makes.
- **Extraction error**: a curated value or locator does not match its source.
- **Source information**: the source lacks, or is ambiguous about, information that is needed.

`scale gap issue gaps/GAP-….json` renders a pre-filled issue from a gap report.

### 2. Curate a source
Follow `tools/skills/curate-source/SKILL.md`. Put the curation in the catalysis examples
(`domain/examples/<example>/`). Documents must pass
`scale graph validate … --source-text …` with zero errors. Respect the source licence: short
excerpts only, never the article text, within the copyright cap recorded in the folder's `rights.yaml`
(`scale evidence report`; [docs/curation.md](docs/curation.md)). Commit only public documents (each states
`access: public`): project data not cleared for publication stays out of the repository
([governance/licensing.md](governance/licensing.md)).

### 3. Propose a schema change
Follow `tools/skills/evolve-schema/SKILL.md`: start with `scale proposal new <owner> --title "…"` (below), set
`status: proposed`, run `scale proposal check <id>` until it reports ok, and open a pull request whose body is
`PR_BODY.md`. The pull request carries the proposal and its reports, not changes to the schema files: after
the merge the proposal is applied and the schema's one version is raised.

A proposal is named by a six-digit number, global across the science kernel and the catalysis domain:
proposal `000001` lives in `domain/proposals/000001/`, and its title stays in `proposal.yaml`.
The folder's location says who owns it (`catalysis`, or `core` for the kernel); a number is never used
twice anywhere. `scale proposal new catalysis --title "Pathway records"` takes the next number
(`000001` for the first) and scaffolds `domain/proposals/000001/proposal.yaml`. Commands take the
six-digit id or the directory (`scale proposal check 000001`).

| the change touches | proposal directory |
|---|---|
| the catalysis domain (`domain/graph/`) | `domain/proposals/<NNNNNN>/` |
| the science kernel (`core/graph/`) | `core/proposals/<NNNNNN>/` |

Every proposal raises the schema's one version (kernel and catalysis together), whichever file it changes,
and needs the same approval. Two proposals built on the same schema version cannot both apply: the
second is rebuilt on the new version (`scale proposal check`) after the first is applied.

Every proposal needs:

- `maturity: provisional` for new concepts;
- structured operations (additive; deprecate instead of delete);
- evidence for the motivating records;
- fixtures that pass **and** counterexamples that fail for a stated reason;
- its version step in `tools/scale/pgraph_migrate.py` (every version raise), and for a change in how
  records are written its rule, so that the assessed documents move and every document can reach the new
  head after the apply;
- `expected_query_changes` listing every competency question whose answer should change;
- `mappings_considered`, listing existing labels, properties and external vocabularies and why each
  was or was not reused. Never invent an external identifier.

SCALE's schema has two layers: the science kernel (`core/`), the general base layer, and the domains, each
built on it; catalysis (`domain/`) is the first. The catalysis graph schema manifest
(`domain/graph/scale-graph.yaml`) assembles the kernel with one catalysis file
(`catalysis.yaml`), with one vocabulary and one checklist; applying a proposal freezes the earlier version
into `graph/frozen/` beside it, and the kernel of that version into `core/graph/frozen/`. The catalysis domain
extends the kernel; it never copies or redeclares it. Extending means `is_a`, `extends`, or `adds_properties`
with a new key. A label, edge type or property name that the kernel already declares is an error in
`scale domains check`.

### 4. Add a competency question
Add `domain/competency/cq-NN-*.yaml`: the question, the public example documents it runs
on, a scale-graph query plan and the expected answer (`expect`); `scale domains cq catalysis` runs it
([docs/querying.md](docs/querying.md)). Competency questions are how researchers state what
the representation must recover.

See [domain/README.md](domain/README.md) for the `DOMAIN.yaml` fields. Keep catalysis terms out of
the kernel.

## Changes to the science kernel

`core/` is the base layer every domain builds on, so a change there reaches the catalysis schema too. Say in
the pull request how the catalysis domain is affected; `scale ci spec-changes` lists who must review. It is
reviewed like every change (one approval). Open a
[science-kernel issue](https://github.com/hlxin/scale/issues/new?template=core-change.yml)
first for anything larger than a fix. See [core/README.md](core/README.md).

The kernel changes only by a kernel proposal: everything about catalysis, electrochemical and
photochemical terms included, stays in the catalysis domain.

## Formats, names and review

- Records, bundles and other machine-written documents are **canonical JSON**. Specifications,
  proposals and configuration are **block-style YAML**. Run `scale fmt`, then `scale check`, before
  opening a pull request ([docs/style.md](docs/style.md)).
- Review: the owner owns every path today (`.github/CODEOWNERS`), and every pull request needs two
  approving reviews from reviewers other than its author ([governance/GOVERNANCE.md](governance/GOVERNANCE.md),
  [governance/review-policy.yaml](governance/review-policy.yaml)). A proposal's tier (0 to 3) is shown in
  its reports for the reviewers; it does not change the approvals needed.
  `scale review status <id>` shows what an applied or merged proposal's recorded reviews count.
- New concepts enter as `maturity: provisional`.

## Rules for code

- The Python package is `tools/scale/`; skills are in `tools/skills/`
  ([tools/README.md](tools/README.md)). Python ≥ 3.10; the runtime dependencies are PyYAML and
  jsonschema.
- Tools must be deterministic. Anything that calls a model sits behind a skill (or, for triage,
  `SCALE_TRIAGE_COMMAND`).
- Tests for every behaviour: tool tests in `tools/tests/`, kernel tests in `core/tests/`, catalysis
  tests in `domain/tests/`. Update `docs/implementation-status.yaml` when you
  add, mock or finish a capability; CI checks that functioning entries cite existing tests.
- Never edit a release. CI verifies the digests, and `scale ci spec-changes` fails a pull request
  that modifies, deletes or adds a file inside an existing release directory (`releases/<id>/`), or
  modifies or deletes an existing frozen schema file under `core/graph/frozen/` or `domain/graph/frozen/`,
  whose `SHA256SUMS` may only gain lines. Adding a new release or a new frozen version is allowed, and so is
  editing the `README.md` and `CHANGELOG.md` files directly under `releases/`.

## Licensing of contributions

Inbound = outbound: a contribution is licensed under the licence that [`REUSE.toml`](REUSE.toml) gives its
path, MIT for code (every Python file, `tools/` apart from the skills' texts) and CC-BY-4.0 for the
vocabulary, curated records, examples and documentation. By opening a pull request, or submitting content
through the contribution form, you agree to that and confirm you have the right to contribute the content.
You keep the copyright in your work.

- **Sign-off is recommended, not enforced.** `git commit -s` adds a `Signed-off-by:` line certifying the
  [Developer Certificate of Origin](https://developercertificate.org/); no check requires it.
- **Quotes** of sources follow the copyright policy: short excerpts within the cap of the folder's
  `rights.yaml`, never whole texts ([governance/licensing.md](governance/licensing.md), section 3).
- **Third-party material** under another licence (an adopted vocabulary, a dataset, a figure) needs a
  `REUSE.toml` entry, its licence text in `LICENSES/` and a line in [`NOTICE`](NOTICE), which people decide
  in a pull request. `scale check` runs `reuse lint`, which fails when a file has no licence.

## Credit

Add yourself to `contributors` in `domain/DOMAIN.yaml` (or `core/CORE.yaml`) for the part
you worked on, in the same pull request, with your name, GitHub handle or ORCID, and roles. Release manifests
take their credits from these files. Co-authors are credited with `Co-authored-by:` trailers. See
[governance/credit-and-authorship.md](governance/credit-and-authorship.md).

## Forks

While the repository is private, collaborators work on branches here. Once it is public, forks are permitted
as the licences allow, and a pull request from a fork is reviewed like any other. A fork's own builds are not
official SCALE releases; that designation belongs to releases made through this repository's process.

## Conduct

Participation is governed by the [code of conduct](CODE_OF_CONDUCT.md).
