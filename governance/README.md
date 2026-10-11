# Governance

How this repository works: who approves, how a change flows from an issue or a corpus to a new schema
version and updated data repositories, how the catalysis domain's maintainers are recorded, how official
releases are made and how people are credited. The model: every change is a pull request with one
approving review from any reviewer other than its author, the owner being a reviewer
([decision record 0001](../docs/decisions/0001-scale-0.1.0.md)). Every path, this directory included, is owned by
every reviewer, so all of them are asked.

| file | what it covers |
|---|---|
| [GOVERNANCE.md](GOVERNANCE.md) | the owner and the reviewers, one approval for every change and no bypass, the flow from an issue or a corpus to review, merge and the data-repository update; schema changes and their version; the catalysis domain; project data |
| [working-groups.md](working-groups.md) | how the catalysis domain's maintainers are recorded and what every change in the catalysis domain needs |
| [release-process.md](release-process.md) | the one process for official releases: freeze, build, review, tag, publish |
| [licensing.md](licensing.md) | the licences (code MIT; vocabulary, records and documentation CC-BY-4.0; third-party material per NOTICE), contributions, the copyright policy for quoted evidence, project data and access levels, contributions to the catalysis domain, how to cite |
| [credit-and-authorship.md](credit-and-authorship.md) | how credit is recorded: contributor lists, stewardship credit, release notes, citation |
| [repository-settings.md](repository-settings.md) | the GitHub settings the owner applies: the repository, collaborators, Actions permissions, secrets, rulesets, the `pypi` environment, sharing the repository |
| [github/ruleset-main.json](github/ruleset-main.json) | branch ruleset for `main` (REST payload) |
| [github/ruleset-tags.json](github/ruleset-tags.json) | tag ruleset for `v*` (REST payload) |
| [review-policy.yaml](review-policy.yaml) | the machine-readable review policy (the reviewers, one approval), enforced by the `main` ruleset |
| [feedback.md](feedback.md) | how comments become changes |
| [`governance/registry/`](./registry/) | extension prefixes and stewardship (institutions, projects) |

Related: [CONTRIBUTING.md](../CONTRIBUTING.md), [the catalysis domain](../domain/README.md),
[decision records](../docs/decisions/), [CODEOWNERS](../.github/CODEOWNERS).

## Human-only actions

Anyone suggests changes or opens pull requests; agents do the work; people decide. These steps are always done by
a person:

- approving and merging a pull request (one reviewer, the person who suggested the change included, never its
  author);
- inviting and adding a reviewer (a real person who agreed; there is no fixed number);
- @scale-agents, which take up every suggestion on their own (or a manual run);
- updating a data repository to a new schema version (`scale kg update`) and merging that change;
- building an official release (`scale release build vX.Y.Z`), tagging it and approving the `pypi`
  deployment;
- inviting collaborators, setting secrets and applying rulesets ([repository-settings.md](repository-settings.md));
- registering the PyPI trusted publisher for `scale-catal`.

Nothing is applied after a merge: what merges is what the reviewer approved.
