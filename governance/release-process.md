# Official releases

There is one process for official SCALE releases. It is run by the owner (and the reviewers, once they
join), and every step that publishes something is done by a person. The first release is `v0.1.0`,
with schema 0.1.0.

Releases are not the version bump. The schema's one version moves on with every schema change, in the
pull request that makes it; documents pin those versions directly. A release is a human step taken now and
then: it **bundles the schema versions merged since the last release** (the head version, with the frozen versions), the tools and the skills, under one id.

## What an official release is

An official release `vX.Y.Z` is:

| part | where |
|---|---|
| the science kernel | `core/` (`CORE.yaml`, the kernel and its frozen versions), copied and digested into `releases/vX.Y.Z/` |
| the catalysis domain | `domain/DOMAIN.yaml`, the one entry of `domain_profiles` in `scale-release.yaml`, with its schema manifest (`graph/scale-graph.yaml`), every part it lists and its frozen versions, copied and digested. The two layers stay separate: there is no repository-wide composition |
| the spec documents | every version of the released schema as a spec document (`specs/<domain>/scale-graph-<version>.json`) with its sha256, the digest a reader binds a schema by |
| validators and tools | the Python package `scale-catal` X.Y.Z on PyPI, built from the tagged commit, with the bundled skills |
| documentation | the documentation in the tagged commit `vX.Y.Z` |
| the release manifest | `releases/vX.Y.Z/RELEASE.yaml` |

Three names always agree: the git tag `vX.Y.Z`, the package version `X.Y.Z` in `pyproject.toml`,
and the directory `releases/vX.Y.Z/`. The publish workflow refuses to publish otherwise. A release
that changes only the tools still gets a new release directory; its schema is then classified
as identical to the previous release.

Only stable domains are part of an official release: the build refuses a manifest that lists
`domain/DOMAIN.yaml` while the domain is marked `status: experimental`, and `RELEASE.yaml` names the domain
when it leaves it out (`excluded_domains`; none today).

## The release manifest

`scale release build` writes `releases/vX.Y.Z/RELEASE.yaml`. Besides the release id, status, date,
previous release, skills and digests of every copied file, it records:

- `component_versions`: the schema's one version; the core, the kernel and the catalysis domain at that
  version (with the domain's status and `scale_graph`: its schema manifest); the tool package and version;
  each skill with its version;
- `contributors`: the people in `CORE.yaml` and the released `DOMAIN.yaml` (maintainers and
  contributors), deduplicated by GitHub handle (or ORCID, or name, when there is no handle), with
  their roles and `scopes` (whether the credit comes from the kernel or the catalysis domain); placeholders
  are never credited;
- `excluded_domains`: experimental folders left out (none today);
- `spec_documents`: the spec documents shipped with the release and their sha256;
- `comparison_to_previous`: a semantic diff of the kernel and of the catalysis assembled schema
  against the previous release (labels, edge types, properties and checklist items added, removed,
  changed, narrowed or loosened), classified `identical`, `additive` or `breaking`, and the files
  added, changed or removed (none for the first release);
- `source`: `repository: https://github.com/hlxin/scale`, the repository the release was built from, and
  `tag: vX.Y.Z`, the tag that will mark its commit.

The manifest cannot hold the commit it is part of. The tag `vX.Y.Z` identifies the commit, and with it the
documentation of the release: the docs of a release are those of its tagged commit.

A release is always built from the repository head. The first release, `v0.1.0`, has no previous release: it
records no comparison.

## Steps

| step | who | command or action |
|---|---|---|
| 1. Open a release issue | the owner or a reviewer | lists the changes since the last release (the CHANGELOG), and the target version |
| 2. Freeze | the owner | announce on the issue; until step 7, merge only release preparation and fixes to it |
| 3. Prepare a branch | the owner or a reviewer | branch `release/vX.Y.Z`; set `version` in `pyproject.toml` and `release` in `scale-release.yaml`; update `CHANGELOG.md`, `CITATION.cff` (version, date) and release notes |
| 4. Check | the same | `uv run --extra dev scale check` |
| 5. Build | **human** | `scale release build vX.Y.Z --date YYYY-MM-DD`, then `scale release verify` |
| 6. Review | one reviewer (the owner's own pull request: the bootstrap rule until another reviewer joins) | pull request from `release/vX.Y.Z`; the required checks pass |
| 7. Merge | the owner or a reviewer | merge into `main` |
| 8. Tag and release | **human** (the owner; `v*` tags are restricted to the repository admin) | `gh release create vX.Y.Z --target <merge commit> --title vX.Y.Z --notes-file <notes>` |
| 9. Publish | **human** approves the `pypi` deployment (where the plan allows required reviewers) | the `publish` workflow checks tag = package version = `releases/vX.Y.Z/` and that the release verifies, then publishes `scale-catal` to PyPI by trusted publishing |
| 10. Confirm | the owner or a reviewer | `uvx scale-catal@X.Y.Z call status` from a clean machine; close the release issue |

Agents may prepare steps 1–4 and draft release notes. They never build an official release on
their own initiative, tag, publish or approve.

The build refuses when:

- schema content changed since the previous release while the schema version did not;
- an experimental folder is listed, or the schema manifests name several versions;
- the requested version differs from `release` in `scale-release.yaml`;
- `releases/vX.Y.Z/` already exists (releases are immutable).

If a published release is wrong, it is not edited. A new release fixes it, and the release notes
say what was wrong.

## Version numbers

- **Distribution** `vX.Y.Z`: the official release, versioned semantically. `comparison_to_previous`
  in `RELEASE.yaml` classifies the schema change (`identical`, `additive` or `breaking`).
- **The schema** has one version for the science kernel and the catalysis domain together: the catalysis
  manifest's `version` (0.1.0 today), stated also by `CORE.yaml`, `DOMAIN.yaml` and `scale-release.yaml`
  (`schema_version`). Documents pin it (`graph.schema_version`); earlier versions are frozen in
  `domain/graph/frozen/` and `core/graph/frozen/` once a schema change has moved it on. A version number names a
  schema only within this repository's numbering; its spec digest identifies it.
- A schema change raises the second number when it is breaking (0.1.0 -> 0.2.0) and the third when it is additive
  (0.1.0 -> 0.1.1). Decision records (NNNN, numbered globally from 0001) are never reused.

## One-time setup (human actions)

- Register `hlxin/scale`, workflow `publish.yml`, environment `pypi` as a trusted publisher of the PyPI
  project `scale-catal` (the repository is named `scale`, the package `scale-catal`).
- Create the `pypi` environment and the tag ruleset ([repository-settings.md](repository-settings.md)).
