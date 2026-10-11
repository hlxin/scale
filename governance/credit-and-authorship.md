# Credit and authorship

This page says how credit is recorded in this repository (`hlxin/scale`): consent, agents, citation and
publications.

## Where credit is recorded

| record | who is in it | where |
|---|---|---|
| core maintainers and contributors | people who review, maintain or contributed to the core and the tools (a placeholder entry is nobody and is never credited) | `core/CORE.yaml`: `maintainers.people`, `contributors` |
| catalysis stewards, maintainers and contributors | people who maintain or contributed to the catalysis domain | `domain/DOMAIN.yaml`: `maintainers.people`, `contributors` |
| release contributors | everyone in `CORE.yaml` and the released `DOMAIN.yaml`, deduplicated by GitHub handle (or ORCID, or name, when there is no handle), with their roles | `releases/vX.Y.Z/RELEASE.yaml`: `contributors` |
| commits | authors and co-authors | git history (`Co-authored-by` trailers) |
| release notes | people whose work is in the release, by name | the GitHub release and `CHANGELOG.md` |
| institutions and projects | partner institutions, funders, projects | [`governance/registry/stewardship.yaml`](./registry/stewardship.yaml) |

`CORE.yaml` and `DOMAIN.yaml` use the same shape:

```yaml
maintainers:
  team: '@hlxin'
  people:
    - name: Hongliang Xin
      github: hlxin
      since: '2026-09-26'
      roles:
        - steward
contributors:
  - name: Hongliang Xin
    github: hlxin
    roles:
      - steward
```

- `maintainers.people` entries have `name`, `github`, `since`, `roles` (`steward` or
  `maintainer`) and optionally `orcid`.
- `contributors` entries have `name` and `roles`, and `github` or `orcid` where the person has
  one. A person without a GitHub account is credited by name and, if they wish, ORCID.
- `roles` are short words describing the work, such as `steward`, `maintainer`, `curation`,
  `review`, `questions`, `examples`, `tooling`, `documentation`.
- Add a person, handle or ORCID only with that person's agreement, and never guess an identifier.
  An entry marked `placeholder: true`: it is nobody and is never credited.

**Stewardship credit.** Maintaining the catalysis domain is scientific work. Stewards are listed in
`maintainers.people` with `since`, and in every release that contains their work. When they step
down they move to `contributors`; their name stays in every earlier release manifest.

## How to be credited

- **Pull request authors** add themselves to `contributors` in `domain/DOMAIN.yaml` (or
  `core/CORE.yaml`) for the part they worked on, in the same pull request. The pull-request template asks for it.
- **Co-authors** of a commit are credited with a trailer in the GitHub no-reply form:

  ```
  Co-authored-by: Full Name <ID+username@users.noreply.github.com>
  ```

  `gh api users/<username> --jq .id` gives the numeric `ID`. The no-reply form links the commit to
  the account without publishing an e-mail address.
- **Submissions through an issue.** People who do not use Git can submit content with the
  [contribution form](https://github.com/hlxin/scale/issues/new?template=contribution.yml),
  which asks how they want to be credited. The maintainer who turns the submission into a pull request:
  1. adds a `Co-authored-by` trailer for the submitter (no-reply form) if they have a GitHub
     account and agreed;
  2. adds them to `contributors` in the relevant manifest, with the name and identifiers they gave
     and agreed to publish;
  3. links the issue from the pull request.

  If the submitter does not answer about credit, nothing about them is added beyond the link to
  their issue.

## Credit and licence

Credit and licence are separate. Being credited does not transfer copyright: contributors keep the
copyright in their work and license it under the licence of its path (code MIT; vocabulary, records and
documentation CC-BY-4.0; [licensing.md](licensing.md)). CC-BY-4.0 asks everyone who reuses the material to
attribute it; the attribution SCALE asks for is "SCALE contributors", the release and a link to the
repository, and the people in the release's `contributors` are those contributors. The authors of the
sources a record quotes are credited by citing their publications in the record's evidence; their text
stays under their terms.

## Release notes

The notes of every official release name, for the catalysis domain and for the science kernel, the
people whose work is in the release (from the release manifest's `contributors` and the merged pull
requests), and the pull requests and their approvers.

## Citing the software

[`CITATION.cff`](../CITATION.cff) describes how to cite SCALE (the Python package scale-catal). Today its author is the
collective "SCALE contributors". A rule for naming its authors (for example, the people in the latest release's
`contributors`) is left for a later decision record.

## Publications

Authorship of publications about SCALE follows the usual scientific criteria (a substantial contribution, and
agreement to the text); there is no separate policy yet. The accompanying article is in preparation
([CITATION.cff](../CITATION.cff)).

## Agents

Agents are not listed as contributors; work an agent did at a person's request is credited to that
person, and the agent is named where the work is described (for example in a `Co-Authored-By` trailer).
