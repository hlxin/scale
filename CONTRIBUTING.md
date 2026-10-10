# Contributing to SCALE

SCALE (Shared Concepts, Attributes, and Links with Evidence) is one shared framework for evidence-backed
scientific knowledge graphs across domains, developed in this repository, `hlxin/scale`, a personal repository of
its owner, Hongliang Xin. Contributions extend the science kernel or a domain (catalysis is the first), add
curated sources, examples, questions, tools or documentation. Provisional concepts are welcome when their status
and scope are explicit. This contribution model does not alter rights granted by the project's licences.

The [code of conduct](CODE_OF_CONDUCT.md) governs participation; [governance/GOVERNANCE.md](governance/GOVERNANCE.md)
holds the rules. New to SCALE? Start with the [README](README.md).

## How a change is made

Anyone can suggest a change or open a pull request. Agents do most of the work. One person approves and merges.

```
a suggestion (an issue or a comment), by a person or an agent         or a pull request opened directly
        │  @scale-agents take it up on their own (no tag, no label)
        ▼
the agents decide, implement it on a branch, verify it and open a pull request
        │  (any change: a schema change, a curation, a question, a tool, documentation)
        ▼
CI runs the checks; for a schema change it also writes a summary for the reviewer
        │
        ▼
ONE person approves and merges (any reviewer, the person who suggested it included)
```

- **Suggest.** Open an issue (the forms below) or comment on one, in plain language. You do not need to know the
  schema, the code or Git.
- **The agents do it.** `@scale-agents` take up every new issue and comment on their own: a discovery strategist decides
  whether it needs an answer, a question back or a change; for a change a data scientist proposes the patch with its
  evidence, a protocol compiler writes the tests, an evidence verifier assesses the support and the effects on
  existing records and queries, and a systems engineer opens the pull request, under the team's own GitHub
  identity, with the whole change set ([AGENTS.md](AGENTS.md), the skills in `tools/skills/`). Ask for fixes by commenting or
  reviewing on that pull request; the agents push them. Your own AI agent may do the same on your machine.
- **Or open a pull request yourself.** Branch `<github-handle>/<topic>`, make the change, run
  `uv run --extra dev scale check --fast`, push and open the pull request with the template filled in.
- **Approve and merge.** Every pull request needs one approving review from a person listed in
  [governance/review-policy.yaml](governance/review-policy.yaml); the person who suggested the change may give it.
  GitHub does not let the author of a pull request approve it, so a pull request you opened yourself needs another
  reviewer (the owner's own: the bootstrap rule until another reviewer joins). The approving person merges
  (squash) and the branch is deleted. Ask for changes rather than approve with reservations; to correct a merged
  change, suggest a new one. Agents never approve or merge.

A schema change is a pull request like any other: it edits the schema files directly and raises the schema's one
version in the same pull request (breaking: the second number, 0.1.0 -> 0.2.0; additive: the third,
0.1.0 -> 0.1.1). The agent does this with `scale schema bump`; CI checks it with `scale schema check`. Whoever keeps
a knowledge-graph data repository moves it to the new version with `scale kg update`.

## Getting started as a collaborator

1. **Accept the invitation** to `hlxin/scale` (Write access). The owner adds you to the reviewers in
   [governance/review-policy.yaml](governance/review-policy.yaml) and [.github/CODEOWNERS](.github/CODEOWNERS) by a
   pull request, with your name and GitHub handle, once you agree.
2. **Set up:** `git clone https://github.com/hlxin/scale && cd scale && uv run --extra dev scale check` (one line:
   the environment and every check CI runs; [uv](https://docs.astral.sh/uv/) creates the environment on first use;
   without uv, `pip install -e ".[dev]" && scale check`). Reading PDFs needs `--extra pdf` and the `tesseract`
   command.
3. **Keep data in its place.** Commit only public documents; source PDFs, page texts and anything not cleared for
   publication stay local or in a private data repository (each example's `.gitignore` says what stays local).

## Access levels

The repository is private for now and shared with collaborators.

| GitHub role | who | what it allows |
|---|---|---|
| — | everyone, once the repository is public | read, open issues, comment, fork and open pull requests from a fork |
| Write | collaborators the owner invites, the reviewers among them | push branches, open pull requests, run the agents by hand |
| reviewer | the reviewers of the review policy, code owners in `.github/CODEOWNERS` | the one approval every pull request needs |
| Admin | the owner, `@hlxin` | repository settings, rulesets, collaborators and secrets |

What protects `main` is the branch ruleset: a pull request, one approval, passing required checks, no force pushes
and no deletion ([governance/repository-settings.md](governance/repository-settings.md)). CODEOWNERS routes review
requests; it does not restrict writes. Write access is a trust grant: it lets a collaborator start the agent.

## Branches

- `<github-handle>/<topic>` for your own work, `agent/…` for the agent's, `release/vX.Y.Z` for release pull
  requests ([governance/release-process.md](governance/release-process.md)). Lowercase, words joined by `-`.
- One topic, one pull request; the branch is deleted when it merges. A push after approval needs a fresh approval.

## Suggesting without Git

- Open a **[comment or suggestion](https://github.com/hlxin/scale/issues/new?template=comment.yml)**, or an issue
  with a matching template: **missing concept** (the representation cannot express a distinction a source makes),
  **extraction error** (a curated value or locator does not match its source), **source information** (the source
  lacks, or is ambiguous about, information that is needed). `scale gap issue gaps/GAP-….json` renders one from a
  gap report.
- Send content (a curation, data, a correction, a competency question) with the
  **[contribution form](https://github.com/hlxin/scale/issues/new?template=contribution.yml)**, and say how you
  want to be credited. The pull request that carries it adds you as co-author with a `Co-authored-by:` trailer.
- Comment on any pull request or line. Each week, feedback is grouped into topics with options in a feedback
  digest issue ([governance/feedback.md](governance/feedback.md)).

## What a change carries

The agent knows these rules ([AGENTS.md](AGENTS.md)); they hold for every pull request:

- **Curation** follows `tools/skills/curate-source/SKILL.md`: documents validate with zero errors, every
  statement cites evidence, quotes stay within the copyright cap of the folder's `rights.yaml`
  ([docs/curation.md](docs/curation.md)), and committed documents state `access: public`.
- **A schema change** follows `tools/skills/evolve-schema/SKILL.md`: additive operations, deprecation instead of
  deletion, `maturity: provisional` for new concepts, a fixture and a counterexample, the version raised with
  `scale schema bump`, a migration rule for a breaking change, the competency questions that change updated, a
  CHANGELOG line. The catalysis domain extends the kernel and never redeclares a kernel identifier; catalysis
  terms stay out of the kernel. A kernel change says how the catalysis domain is affected.
- **A competency question** is `domain/competency/cq-NN-*.yaml`: the question, the public documents it runs on, a
  query plan and the expected answer ([docs/querying.md](docs/querying.md)).
- **Code** lives in `tools/scale/` ([tools/README.md](tools/README.md)), is deterministic (anything that calls a
  model sits behind a skill), and has tests (`tools/tests/`, `core/tests/`, `domain/tests/`). Update
  `docs/implementation-status.yaml` when a capability changes.
- **Formats:** machine-written documents are canonical JSON, specifications and configuration block-style YAML
  (`scale fmt`; [docs/style.md](docs/style.md)).
- **Never edit a release** (`releases/<id>/`) or an existing frozen schema version (`core/graph/frozen/`,
  `domain/graph/frozen/`); CI fails a pull request that does.

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

Add yourself to `contributors` in `domain/DOMAIN.yaml` (or `core/CORE.yaml`) for the part you worked on, in the
same pull request, with your name, GitHub handle or ORCID, and roles. Release manifests take their credits from
these files. Nobody is credited without consent
([governance/credit-and-authorship.md](governance/credit-and-authorship.md)).

## Forks

While the repository is private, collaborators work on branches here. Once it is public, forks are permitted
as the licences allow, and a pull request from a fork is reviewed like any other. A fork's own builds are not
official SCALE releases; that designation belongs to releases made through this repository's process.
