# Contributing to SCALE

SCALE (Shared Concepts, Attributes, and Links with Evidence) is one shared framework for evidence-backed
scientific knowledge graphs across domains. It is developed here, in `hlxin/scale`, the personal repository of its
owner, Hongliang Xin. You can extend the science kernel or the catalysis domain, or add sources, examples,
questions, tools or documentation. Provisional concepts are welcome if their status and scope are clear. This
contribution model does not change the rights the licences grant.

The [code of conduct](CODE_OF_CONDUCT.md) applies to everyone; the rules are in
[governance/GOVERNANCE.md](governance/GOVERNANCE.md). New to SCALE? Start with the [README](README.md).

## How a change is made

Every change is one pull request. Anyone, a person or an agent, can suggest a change or open a pull request.
Agents do most of the work. One person approves and merges.

```
a suggestion in an issue or a comment                 or a pull request opened directly
        │  @scale-agents pick it up on their own
        ▼
the agents make the change on a branch, check it and open a pull request
        │
        ▼
CI runs the checks (and, for a schema change, writes a summary for the reviewer)
        │
        ▼
ONE reviewer approves and merges (the person who suggested it may be that reviewer)
```

- **Suggest.** Open an issue (see [Suggesting without Git](#suggesting-without-git)) or comment on one, in plain
  language. You do not need to know the schema, the code or Git.
- **The agents do it.** `@scale-agents` pick up every new issue, comment and review (an approval with no text excepted) on their own; nobody needs to
  tag anything. Five roles share the work, from framing the request to verifying the evidence
  ([`.github/scale-agents/`](.github/scale-agents/instructions.md)). Each pull request they open carries the patch,
  its evidence, its tests and a migration assessment. Comment on it or review it to ask for fixes.
- **Or open a pull request yourself.** Use a branch `<github-handle>/<topic>`, make the change, run
  `uv run --extra dev scale check --fast`, push and fill in the pull request template.
- **Approve and merge.** Every pull request needs one approving review from a reviewer listed in
  [governance/review-policy.yaml](governance/review-policy.yaml). GitHub does not let a pull request's author
  approve it, so a pull request you opened needs another reviewer. Every reviewer is asked; the first who approves
  also merges. Agents never
  approve or merge.

### Schema changes

A schema change edits `core/graph/kernel.yaml` or `domain/graph/catalysis.yaml` directly. In the same pull request,
`scale schema bump --base origin/main` freezes the base version, raises the version and registers the migration
step: a breaking change raises the second number (0.1.0 to 0.2.0), an additive one the third (0.1.0 to 0.1.1).
CI checks this with `scale schema check`.

## Getting started as a collaborator

1. **Accept the invitation** to `hlxin/scale` (Write access). Once you agree, the owner adds you as a reviewer in
   [governance/review-policy.yaml](governance/review-policy.yaml) and [.github/CODEOWNERS](.github/CODEOWNERS), by
   a pull request, with your name and GitHub handle.
2. **Set up:** `git clone https://github.com/hlxin/scale && cd scale && uv run --extra dev scale check`. This
   creates the environment and runs every check CI runs. Without [uv](https://docs.astral.sh/uv/), use
   `pip install -e ".[dev]" && scale check`. Reading PDFs also needs `--extra pdf` and the `tesseract` command.
3. **Keep data in its place.** Commit only public documents. Source PDFs, page texts and anything not cleared for
   publication stay local or in a private data repository; each example's `.gitignore` says what stays local.

## Branches

Use `<github-handle>/<topic>` for your own work, one topic per pull request. The branch is deleted when it merges.

## Suggesting without Git

- Open a **[comment or suggestion](https://github.com/hlxin/scale/issues/new?template=comment.yml)**, or use a
  form for a [missing concept](https://github.com/hlxin/scale/issues/new?template=missing-concept.yml), an
  [extraction error](https://github.com/hlxin/scale/issues/new?template=extraction-error.yml), missing or ambiguous
  [source information](https://github.com/hlxin/scale/issues/new?template=source-information.yml), a
  [new source](https://github.com/hlxin/scale/issues/new?template=new-source.yml), a
  [competency question](https://github.com/hlxin/scale/issues/new?template=competency-question.yml) or a
  [science-kernel change](https://github.com/hlxin/scale/issues/new?template=core-change.yml).
  `scale gap issue GAP.json` writes such an issue from a gap report.
- Send content (a curation, data, a correction, a competency question) with the
  **[contribution form](https://github.com/hlxin/scale/issues/new?template=contribution.yml)** and say how you
  want to be credited. The pull request that carries it names you as co-author with a `Co-authored-by:` line.
- Comment on any pull request or line. Each week, feedback is grouped by topic into a feedback digest issue
  ([governance/feedback.md](governance/feedback.md)).

## What a change carries

These rules hold for every pull request; the agents know them from [AGENTS.md](AGENTS.md).

- **Curation** follows `skills/curate-source/SKILL.md`. Documents validate with no errors, every statement
  cites evidence, quotes stay within the copyright cap in the folder's `rights.yaml`
  ([docs/curation.md](docs/curation.md)), and committed documents state `access: public`.
- **A schema change** follows `skills/evolve-schema/SKILL.md`: additions rather than deletions, new concepts
  marked provisional, a passing and a failing test example, and a CHANGELOG line. Catalysis terms stay out of the
  kernel.
- **A competency question** is a file `domain/competency/cq-NN-*.yaml`: the question, the public documents it runs
  on, a query plan and the expected answer ([docs/querying.md](docs/querying.md)).
- **Code** lives in `tools/` ([tools/README.md](tools/README.md)). It is deterministic (anything that calls
  a model sits behind a skill) and has tests in `tools/tests/`, `core/tests/` or `domain/tests/`. Update
  `docs/implementation-status.yaml` when a capability changes.
- **Never edit a release** (`releases/<id>/`) or an existing frozen schema version (`core/graph/frozen/`,
  `domain/graph/frozen/`). CI fails a pull request that does.

## Licensing of contributions

Inbound = outbound: a contribution takes the licence that [`REUSE.toml`](REUSE.toml) gives its path. That is MIT
for code (every Python file, and `tools/` apart from the skills' texts) and CC-BY-4.0 for the vocabulary, curated
records, examples and documentation. By opening a pull request or using the contribution form, you agree to this
and confirm you have the right to contribute the content. You keep the copyright in your work.

- **Sign-off is recommended, not required.** `git commit -s` adds a `Signed-off-by:` line certifying the
  [Developer Certificate of Origin](https://developercertificate.org/); no check enforces it.
- **Quotes** from sources are short excerpts within the cap in the folder's `rights.yaml`, never whole texts
  ([governance/licensing.md](governance/licensing.md), section 3).
- **Third-party material** under another licence (an adopted vocabulary, a dataset, a figure) needs a
  `REUSE.toml` entry, its licence text in `LICENSES/` and a line in [`NOTICE`](NOTICE). People decide this in a
  pull request. `scale check` runs `reuse lint`, which fails if a file has no licence.

## Credit

In the same pull request, add yourself to `contributors` in `domain/DOMAIN.yaml` (or `core/CORE.yaml`) for the
part you worked on, with your name, GitHub handle or ORCID, and roles. Releases take their credits from these
files. Nobody is credited without consent ([governance/credit-and-authorship.md](governance/credit-and-authorship.md)).
