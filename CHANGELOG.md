# Changelog

## Unreleased

- **People and agents open pull requests; one person approves and merges** (review policy version 3). An agent may now
  open a pull request ready for review, no longer only a draft; one person other than its author approves it and
  merges it, and agents still never approve, merge or apply. An agent opens its pull request under its own GitHub
  identity (the Claude GitHub App in the scale-agent workflow, or a bot account), never a person's, since GitHub does
  not let an author approve their own pull request (governance/repository-settings.md, "The agent"). The scale-agent
  workflow may run `gh pr create` without `--draft`.
- **The methanol-synthesis example is public** (`examples/methanol-synthesis-pre1966/`), a small benchmark for the
  repository. The ARPA-E CATALYST partners cleared the curated graph of the historical methanol-synthesis literature
  published before 1966 for publication; the example keeps its CO and CO2 hydrogenation scope (105 sources, 4,868
  records, 16,586 links, 684 catalytic tests). It was moved from the consortium schema repository's 0.1.0 to its 0.5.0
  with that repository's tools and re-pinned to 0.1.0 (valid, 0 errors), and its quoted text was capped (`scale
  evidence cap`, which applies to the 50 in-copyright sources only; the 55 public-domain sources, the US patents
  and works published before 1931, keep every quote: 6,920 of 25,230 evidence items, all from in-copyright sources,
  carry withheld text). With it: the corpus (`corpus/sources.json`:
  the 105 sources and each PDF's sha256; the PDFs are local), the rights file, the frozen corpus manifest, the curation
  guide and assembly report, the manuscript's seven query plans and the curation tools. Its first release,
  `releases/v1.0.0/` (2026-10-09), is an immutable snapshot: the graph (sha256 `0dfc8c1c…ed13f`), the corpus list,
  the rights file and the plans, with `RELEASE.yaml` (schema 0.1.0 and its spec digest, counts, each plan's answer)
  and `SHA256SUMS`, built and verified by `tools/release_graph.py`. Its GALAXY bundle,
  `galaxy/methanol-synthesis-pre1966_v1.0.0/`, passes GALAXY's validator (0 errors, 0 warnings): 4,850 nodes, 14,107
  edges; the 3,277 links whose quotes are withheld under the cap are left out until GALAXY accepts withheld-quote
  evidence ([docs/galaxy-platform-changes.md](docs/galaxy-platform-changes.md), the changes requested of GALAXY). The fragments, page
  texts, OCR and the earlier private GALAXY bundles stay in the restricted copy; the evidence index is built locally. New tests,
  `tools/tests/test_example_methanol.py`, run on the public files.
- **One approval for every change (review policy version 2).** A pull request to `main` now merges with one approving
  review from any reviewer other than its author, instead of two; a reviewer who disagrees with a merged change
  corrects it with a pull request of their own. `governance/review-policy.yaml` sets `approvals.required: 1`, and the
  `main` ruleset (`governance/github/ruleset-main.json`) requires one approving review and no longer a code owner's,
  so that any reviewer, not only the owner, can approve; CODEOWNERS still routes review requests. The owner is a reviewer and
  approves other people's pull requests; the bootstrap rule covers only the owner's own pull requests (GitHub does not
  let an author approve) and ends as soon as a second reviewer joins: `scale proposal decide --bootstrap-bypass` is refused
  once another reviewer can approve (`policy.approvable`), not only once every seat is filled. No schema change.

## 0.1.0 — 2026-10-08

The first version of SCALE — Shared Concepts, Attributes, and Links with Evidence — in `github.com/hlxin/scale`:
one shared framework for evidence-backed scientific knowledge graphs across domains, with the science kernel and
catalysis as the first domain ([decision record 0001](docs/decisions/0001-scale-0.1.0.md)). It continues the work
developed in the SCALE Consortium's schema repository (the consortium schema repository, up to commit 79b4fe4),
whose earlier versions, releases, proposals and decision records stay there. No release has been built yet; the
first will be `v0.1.0`.

- **Schema 0.1.0, one version for the whole schema.** The science kernel (`core/graph/kernel.yaml`) and the catalysis
  file (`domain/graph/catalysis.yaml`), assembled by `domain/graph/scale-graph.yaml`, at **scale-graph 0.1.0**.
  The spec digest of scale-graph 0.1.0 (sha256 of its spec document, `scale graph spec`): `3c2fa7205a7bae5e0bbfa7d87826ff7ab7803e78536129064101c7d5a2c02006`.
  The content is that of the
  catalysis graph schema the work had reached (catalysis 0.5.0 on kernel 0.2.0 in the consortium schema
  repository's numbering): the
  method of science, what is studied and done with and who does it, the value object, evidence, record references,
  stewardship and the source lifecycle in the kernel; catalysis as a whole, the terms of every driving force and one
  checklist whose cases follow a test's `driving_forces` in the catalysis file. The kernel and the catalysis file
  carry no version of their own; `core/CORE.yaml`, `domain/DOMAIN.yaml`, `scale-release.yaml` (`schema_version`) and
  the kernel-only example manifest state the one version, `scale domains check` requires them to agree, and every
  applied proposal raises it whichever file it changes, freezing the version it replaces (its kernel as
  `core/graph/frozen/kernel-<version>.yaml`). Concepts carry no `added_in` or proposal id of the earlier numbering;
  every concept is provisional. The kernel, the catalysis manifest and the kernel-only example manifest say
  `status: candidate` (`scale domains check` requires the kernel's and the kernel-only manifest's status to be the
  manifest's); status is not part of the spec document, so the digest above holds.
- **Schema texts.** Apart from the version metadata, no schema text changed: normalized for the version fields,
  `lineage`, the manifest's `proposals` list and the `added_in` and `proposal` stamps, the spec document of
  scale-graph 0.1.0 equals that of the content it was taken from. Two texts therefore still use the consortium
  schema repository's earlier numbering. The example in the kernel's `graph.follows_domains` description names
  `thermocatalysis@0.1.0`, a frozen driving-force profile of that numbering that this repository does not hold (a
  document that follows it gets an unknown-domain error here; follow `catalysis` or `catalysis@0.1.0`). The
  checklist's `basis` in `domain/graph/catalysis.yaml` cites "the adopted catalysis schema 0.1.0", the catalysis
  schema 0.1.0 of that numbering (the profiles the checklist was first built from), not this repository's
  scale-graph 0.1.0. Changing either text changes the schema's content and needs a proposal; both rewordings are
  open work ([domain/ROADMAP.md](domain/ROADMAP.md), "The schema's wording").
- **Identity by digest.** Spec documents say `lineage: scale`. `scale graph spec --expect <sha256>` (and
  `pgraph.identify`) says whether a version and digest are this repository's; a document pinning a version these
  tools do not hold is reported as such, never read under another version of the same number.
- **Examples and fixtures at 0.1.0.** The public synthetic catalysis examples (the worked example, one document per
  driving force and combination, the source-lifecycle example), the invalid fixtures and the synthetic test proposal
  were moved to today's content with `scale graph migrate` and re-pinned to 0.1.0 (the test proposal's fixtures to
  its target, 0.2.0); the source-lifecycle fixtures already pinned today's content and were re-pinned to 0.1.0. The
  five science-kernel cases already pinned 0.1.0 and are unchanged. The public synthetic fixtures of the catalyst
  states and contexts (two passing documents and eight counterexamples, each failing with exactly its stated error)
  were moved the same way and are kept, re-pinned to 0.1.0, in
  [tools/tests/fixtures/catalyst-states/](tools/tests/fixtures/catalyst-states/README.md) and tested
  (`tools/tests/test_catalyst_states.py`), as the source-lifecycle fixtures are.
- **Tools.** The general tools stay: the validator and checklists, curation with evidence and the copyright cap,
  graph queries with typed absences and the unit rule, evidence search, the source lifecycle, schema proposals (check,
  decide, apply, the version bump after a merge), releases, the GALAXY export, competency questions, coverage and
  conflict skills, access rules and viewer filters, the agent tools over the command line, HTTP, MCP and Python, and
  the skills (curate-source, query-graph, evolve-schema, triage-feedback, scan-conflicts, map-coverage,
  curate-dataset, export-graph). `scale proposal check` warns while a proposal's migration step (base version to
  target) is not registered in `tools/scale/pgraph_migrate.py`, and `scale proposal new`, `build`, `decide` and
  `apply` refuse the data bundled in an installed package, so that they never write into it when run outside a
  checkout. With no release built, `scale skills install` installs the head's skills and
  `scale release verify` has nothing to verify. The tools may read inputs that may not be committed from an optional
  restricted copy that only an environment variable names. The skills restart their numbering with this
  repository, as the schema does: every skill is at version 0.1.0 (their earlier versions belong to the consortium
  schema repository), and a later change to a skill's text raises its version.
- **Scanned pages read by two readers: `scale pages`.** The check the consortium schema repository's methanol
  corpus tool applied to scanned sources is now a general command for any curated document and source
  ([tools/scale/pagereading.py](tools/scale/pagereading.py); `render`, `region`, `agree`, `check`, `pending`,
  `merge-second`, `import`): a reading of a page image carries its region and transcription; the tool computes its
  agreement with the OCR words in that region and records the OCR engines; a reading OCR does not confirm needs a
  matching, independent second reading; every value of a record read from an image is in a transcription or quote.
  Its tests on synthetic pages came with it, and its guide is in [docs/curation.md](docs/curation.md#reading-scanned-pages-two-readers).
  The page images and OCR words stay local, since they reproduce the source. CI does not cover the real-PDF path:
  `test_render_and_region_read_a_pdf` needs pymupdf (the `pdf` extra) and tesseract, which CI's `dev` install does
  not have, so it is skipped there; run it locally with `uv run --extra dev --extra pdf pytest
  domain/tests/test_vision_ocr.py` where tesseract is installed.
- **Not carried.** The tools that served only the consortium schema repository's two restricted example corpora
  (the methanol-synthesis corpus's brief, fragment check, assembly, scoping and bundle commands, corpus freezer,
  converters of another group's dataset and bundle into the retired record format, workbook comparison and export,
  value census and one-off revision script; another corpus's curation library and source tools), their query plans and
  READMEs, the tests that needed their data, and two unapplied proposals (stability maps and the order of phenomena;
  activity in a catalyst state and reaction pathways). They served project data that may not be published, which is
  kept in a separate private data repository; the tooling stays in the consortium schema repository at 79b4fe4
  ([decision record 0001](docs/decisions/0001-scale-0.1.0.md), item 4). The two proposals' themes are in
  [domain/ROADMAP.md](domain/ROADMAP.md). The stewardship registry keeps the owner's projects and their funder
  (`scale:project/arpa-e-catalyst`, `scale:org/arpa-e`), so that documents re-curated from that
  work can name their project.
- **A personal repository.** The owner, Hongliang Xin (@hlxin), owns every path in `.github/CODEOWNERS`; two reviewer
  seats are placeholders, two approvals are required once they are filled, and the owner merges under the bootstrap
  rule until then. The `ci` and `proposal-check` workflows run on pull requests without secrets; `apply-proposals` is
  started by hand and needs a token configured for this repository (`APPLY_TOKEN`); `scale-agent` is off unless started
  by hand; `publish` is inert until the PyPI trusted publisher is configured.
