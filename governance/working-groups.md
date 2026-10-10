# Domain maintainers

What this repository records and checks for the people who look after the catalysis domain (`domain/`),
every area of catalysis included. A domain's maintainers may form a working group of their own once there
are several; until then, the owner and the reviewers look after the kernel and the catalysis domain together.

## Composition

| part | where it is recorded |
|---|---|
| **code owner** | `maintainers.team` in `domain/DOMAIN.yaml`, and the `/domain/` line in [CODEOWNERS](../.github/CODEOWNERS); today `@hlxin` (a team `@org/team` is accepted too, should the repository move to an organization) |
| **stewards** | `maintainers.people` with `roles: [steward]` |
| **maintainers** | `maintainers.people` with `roles: [maintainer]`; a seat not filled yet is `placeholder: true` and is nobody |
| **contributors** | `contributors` in `DOMAIN.yaml` ([credit-and-authorship.md](credit-and-authorship.md)) |
| **review areas** | `review_areas` in `DOMAIN.yaml` |

People in `maintainers.people` are also on the `/domain/` line of CODEOWNERS once they have Write access. The
owner keeps the two in step (a human action; see [repository-settings.md](repository-settings.md)).

## The schema version

The schema has one version for the kernel and the catalysis domain together. The `version` in `DOMAIN.yaml`
states it and must equal the catalysis manifest's (`scale domains check`); every applied proposal raises it
(minor for additive changes, major for breaking ones), whichever file it changes.

## What every change needs

Every pull request, to the catalysis domain or to the science kernel, needs one approving review from
a reviewer other than its author (the owner's own pull requests: the bootstrap rule until another reviewer joins). Nobody may redeclare an
identifier that the kernel or the catalysis domain declares (extend with `is_a`, `extends` or
`adds_properties` with a new key). A schema change is a proposal, applied after the merge; official
releases follow [release-process.md](release-process.md).

## Shared compatibility requirements

`scale domains check` enforces these for the catalysis domain:

- `DOMAIN.yaml` is complete, `domain` names the domain, and declared paths exist;
- its `version` is the schema's one version (the catalysis manifest's), as are `core/CORE.yaml`'s and
  `scale-release.yaml`'s `schema_version`;
- every graph `imports` resolves to the kernel or the catalysis domain's own files;
- no label, edge type or property key is declared twice across the kernel and the catalysis files; a
  collision names both owners;
- no copy of a kernel file inside the catalysis domain;
- example documents validate, tests exist, competency questions exist;
- `.github/CODEOWNERS` has a `/domain/` line naming the domain's code owner.

Run it with `scale domains check` (or `scale check`, which includes it).

## Branches

Work happens on short-lived branches in this repository (collaborators) or in forks (once it is public),
named for the work (see [CONTRIBUTING.md](../CONTRIBUTING.md)), merged by pull request and then deleted
automatically. There are no permanent lab or working-group branches.

## Joining and stepping down

- **Joining.** A pull request edits `DOMAIN.yaml` and CODEOWNERS (one approval, or the bootstrap rule); the
  owner invites the person as a collaborator. Only people who agreed are added.
- **Stepping down.** In `DOMAIN.yaml` the person moves from `maintainers.people` to `contributors`, so their
  credit stays.

## Catalysis

Catalysis has one steward (`DOMAIN.yaml`), so the stewardship target of two is reported as a warning
rather than an error.
