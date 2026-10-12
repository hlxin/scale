# Changelog

## Unreleased

- **The full methanol example leaves the repository; the public one stays.** `examples/methanol-synthesis-pre1966/`
  (105 sources, most in copyright: the graph with capped quotes, its corpus list, rights and the bundle zip) is removed
  and kept outside the repository, until a legal way to curate community graphs is settled. The public-domain example,
  `examples/methanol-synthesis-public/` (55 sources with their PDFs and page texts), stays and now carries the
  manuscript's seven query plans (`queries/`), and its tests check their answers. The test that it is exactly the
  public-domain part of the full graph runs where a restricted copy holds that graph (docs/commands.md); the
  parts round-trip test uses the public example. The earlier versions remain in the git history.
- **The package carries the public example.** `examples/` is bundled into the wheel (`scale/_data/examples/`): the
  public-domain methanol example's parts, page texts and query plans, without its PDFs (22 MB; they stay in the
  repository and the source archive). The wheel grows from about 0.8 MB to 2 MB; an installed package validates and
  queries the example on its own.
- **Only a collaborator's event starts @scale-agents**, now that the repository is public: a run spends the owner's
  Claude usage. Anyone's issue or comment is welcome; a collaborator's comment on it starts the team, which reads the
  whole thread as data.
- **scale-catal is on PyPI** from v0.2.0 (`uvx scale-catal …`); the documents no longer say it is not.
- **An approval with no text no longer starts @scale-agents.** It asked nothing, and the run failed for want of an
  `OUTCOME:` line (reported by a reviewer on #23). The instructions say a run that does nothing still ends with
  `OUTCOME: nothing`.
- **@scale-agents loads its instructions on every event.** On an event about a pull request the action restores
  `.claude/` from `main` (the head is untrusted), which removed the copied `.claude/CLAUDE.md` and roles: the agents
  ran without their rules and ended without an `OUTCOME:` line (#24). The workflow installs the instructions and
  roles, as on `main`, in `~/.claude/` (user memory and subagents), and the prompt says how to read the event
  (`scale thread`) and how to end.
## v0.2.0 — 2026-10-11

Schema 0.2.0, renamed `scale-catal` (breaking: the name only; documents at 0.1.0 migrate with `scale graph migrate`),
the `scale-catal` tools 0.2.0 and the skills; graphs kept as one part per source, and a fully open methanol example
with its public-domain sources, PDFs and page texts.

- **A graph kept as one part per source; a fully open methanol example.** `scale graph split` writes a graph as
  `parts/` (the header, the shared records, one file per source) and `scale graph build` builds it back, sorted by id;
  every command reads such a folder as one graph. The methanol graph splits and builds back to the identical file.
  `examples/methanol-synthesis-public/` holds its 55 public-domain sources (16 articles of 1923-1930, 39 patents)
  as parts, with their PDFs and page texts (`LicenseRef-PublicDomain-US`, NOTICE) and every quote in full; a test
  finds every quote in its source's page texts. The publication and copyright checks read a parts folder as one
  graph.
- **No bypass of the `main` ruleset.** The repository admin's bypass is removed: every change to `main`, the owner's
  included, is a pull request approved by a reviewer other than its author.
- **What testing @scale-agents on GitHub showed, fixed.** `scale thread N` gives the agents the whole thread of an
  issue or pull request, the line comments of reviews included (`gh pr view` leaves them out). A manual run names its
  issue and waits its turn with the other runs on it. The evidence verifier reads every line a rename changed, and a
  test keeps history under the names things had. The agents may change `governance/` and `.github/` (not workflows)
  when a change needs it, listed under Governance changes in the pull request. A run fails when the agents end
  blocked or do not say how they ended. `scale schema check` lists the committed bundles a schema change leaves at an
  older version, as a follow-up for a separate issue. The package and the schema keep their own versions: a release
  always raises the package version; the schema version moves only when the schema changes.
- **Two reviewers join; every reviewer is asked, one approval is enough.** Tianyou Mou (`@mutianyou2013`) and Raul
  Diaz (`@diazr04`) join as reviewers; the list stays open, with no fixed number, and more are added as they join. CODEOWNERS names every reviewer on every line, so GitHub asks all of them, and `scale domains check`
  fails when one is missing. A new `reviewers` workflow withdraws the open review requests when one reviewer approves
  (and comments who approved and merges) and, after a push, asks again every reviewer whose approval the push
  dismissed or who asked for changes. A request for changes still blocks the merge until its reviewer approves. The
  documents no longer speak of reviewer seats or of a bootstrap rule pending a second reviewer.
- **Package 0.2.0, with the schema renamed.** The package version is raised to 0.2.0 for the next release, v0.2.0
  (the package and the schema keep their own versions; here both move). The methanol example's bundle is re-exported at schema scale-catal 0.2.0 (`methanol-synthesis-pre1966_v3.0.0.zip`,
  following 2.0.0; 17,563 edges, unchanged), and the governance documents name the schema `scale-catal`.
- **Breaking: the schema `scale-graph` is renamed `scale-catal` (0.1.0 -> 0.2.0, issue #16).** The kernel
  `scale-graph-kernel` is `scale-kernel`; the manifest is `domain/graph/scale-catal.yaml`, the examples are in
  `domain/examples/scale-catal/`, and documents pin `"schema": "scale-catal"`. No label, edge type or property changes.
  Version 0.1.0 is frozen as it was (`domain/graph/frozen/scale-catal-0.1.0.yaml` and `core/graph/frozen/`, which still
  say `scale-graph`; digest unchanged), so a document pinning `scale-graph` 0.1.0 still validates against it. Migration
  step 0.1.0 -> 0.2.0 rewrites the pin (`scale graph migrate`, `scale kg update`); a document at 0.2.0 that still
  names `scale-graph` is rejected with a message pointing to it. `scale schema diff` reads a renamed schema or kernel
  as a breaking change. The kg-bundle schema and its `extends` entry are both `scale-catal` (`extends` names the graph
  schema's own name, `scale-graph` at 0.1.0); the version and the spec digest identify them, and the descriptions say
  which is which. The methanol graph is migrated to 0.2.0 (only the pin changed); its bundle is still the sealed
  release exported from 0.1.0. Spec digest of scale-catal 0.2.0: `166bfc5539df7f44de075a4fb504c54170af32d6b3a01a916d6171bfcecec714`.
  The v0.1.0 release and the 0.1.0 entries below keep the old name as history.
- **Fixes from a second code review.** Profile files are retired by design: a manifest listing `profiles:` is refused,
  and conformance reads `follows_domains` only. Bundle export: a released Publication keeps its id in later releases;
  two records never share a bundle id; every destination is checked before the first write (no link, nothing inside
  `--previous`), so a refused export changes nothing; a text may not be named like the manifest in any case. Evidence
  index: vectors not saved with their items, and a `.terms` file whose words changed, are rebuilt. Queries: a plan's
  text search ranks only the evidence of the rows it keeps (the methanol evidence-search plans now find q2 86, q3 92
  and q5 108 rows); a description shares no object with the kept schema. Schema change: a nested change that can
  invalidate documents is breaking. Validation: NaN and infinity are not values; a long chain is checked for cycles
  without recursion. REPORTED_IN ids of sources ending alike are distinct. Page reading compares every record of a
  PDF with its digest. The MCP server answers a line it cannot parse.
- **Fixes from a code review.** Bundle export: a parallel link with other values is listed, never merged under
  another's values (six in the methanol graph); distinct sources never share a Publication id; an export is never
  written over the release it follows; a shipped text is a plain file in `text/`, and one named by its source id is
  that publication's (quoted, never withheld); a typed absence goes where its unit and basis put it. Queries and the
  agent toolkit: a result shares no object with the document; a kept schema, document or index is read again when its
  files change (identity and change time included). Evidence search: an index is used only when it holds the
  document's quotes, whatever digest it names; a `.terms` file whose arrays changed is rebuilt; `k` is at least 1; `rrf`
  with a filter ranks only the items it keeps. The MCP server answers a malformed message and keeps serving. Stale
  counts and statements in the docs and the methanol example are corrected.
- **Simpler layout:** the skills are in `skills/` at the root, and the package's modules sit directly in
  `tools/` (the folder is the package `scale`; there is no `tools/scale/`).

## v0.1.0 — 2026-10-10

The first official release: schema 0.1.0 (the science kernel and the catalysis domain), the `scale-catal` tools
and the skills, with the methanol-synthesis example.

- **The Python package is `scale-catal`** (was `scale-schema`): SCALE is more than a schema. The commands are
  `scale` and `scale-catal`; the README installs it with one line.
- **One pull request for every change; proposals retired.** Anyone, a person or an agent, suggests a change (an
  issue, a comment) or opens a pull request; agents do the work; one person approves and merges, any reviewer, the
  person who suggested the change included. A schema change is a pull request like any other: it edits
  `core/graph/kernel.yaml` or `domain/graph/catalysis.yaml` directly and raises the one version in the same pull
  request, a breaking change the second number (0.1.0 -> 0.2.0), an additive change the third (0.1.0 -> 0.1.1).
  New commands: `scale schema diff | bump | check` (`tools/scale/schema_change.py`); `bump` freezes the base version,
  raises the version everywhere it is stated and registers the migration step, and `check`, run by CI's
  `specification-changes` job, asks for the version, the frozen base, the step (and rule, if breaking), a test for
  what is added and a CHANGELOG line, and writes a summary for the reviewer. Removed: the proposal folders
  (`core/proposals/`, `domain/proposals/`), `scale proposal …`, `scale review status`, `scale ci proposal-check |
  proposals`, `scale release build --proposal`, the apply-proposals and proposal-check workflows, the `APPLY_TOKEN`
  secret and decision records per change (`docs/decisions/` keeps decisions about the project). `@scale-agent`
  becomes `@scale-agents` (`.github/workflows/scale-agents.yml`), a team that starts on its own on every new issue,
  comment and pull-request review, with no tag or label: a discovery strategist frames the use case and coordinates; a
  data scientist proposes the corrections to records or changes to schema definitions; a protocol compiler writes
  the tests with their expected outcomes; an evidence verifier assesses the support, the counterexamples and the
  effects on existing records and queries; a systems engineer packages the change set (patch, evidence record,
  test cases, migration assessment) as the pull request (`.github/scale-agents/`). The
  `main` ruleset no longer requires `proposal-check` (re-apply `governance/github/ruleset-main.json`). Review policy
  version 4.
- **A knowledge-graph bundle's schema is the vocabulary: scale-catal 0.1.0.** `kg/schema.json` is no longer the
  subset of types a graph uses, named after the bundle and versioned with it: it is the catalysis vocabulary of the
  scale-graph version the graph pins, every label and edge type with every property a bundle can carry, the same in
  every bundle of that version, named `scale-catal` (catalysis) with the scale-graph version (`scale-kernel` for a
  kernel-only graph). Its `extends` names scale-graph 0.1.0 by its spec digest, which identifies it. A value not of its
  property's declared type is kept as text in `<property>_as_reported` (no type is changed for a graph), property
  names are snake_case (`pH` is `ph`), and every exported record is checked against the schema before anything is
  written. `scale graph validate` refuses a bundle's `kg/graph.json`, whatever version it names. The methanol bundle is
  released as 2.0.0 (`methanol-synthesis-pre1966_v2.0.0.zip`, following 1.1.1), titled "Methanol Synthesis CO/CO2+H2
  Pre-1966"; every type and property of 1.1.1's schema is in it; the format's validator reports 0 errors and one
  warning, that the schema's version is lower than 1.1.1's (the schema is another one, so its numbering restarts).
- **A knowledge-graph bundle has a short title by default.** A platform names an imported graph after the bundle's
  title (`topic`, and the schema's `title`). `scale graph export --to kg-bundle` takes `--title`; by default the title
  is the graph's own when it has at most 40 characters, and otherwise its leading words, cut at a word boundary and
  ending in "…", with the full title kept in the bundle's scope (the export says so). The curate-source skill asks for a
  short graph title with the scope's details in `description`. The methanol graph's title is now "Methanol Synthesis
  CO/CO2+H2 Pre1966" (its former title opens its description), and its bundle is released as 1.1.1 (`methanol-synthesis-pre1966_v1.1.1.zip`, following 1.1.0; only the title changed; the format's validator: 0
  errors, 0 warnings).
- **Maintained by researchers, independent of any institution or project.** The stewardship registry names one
  steward, "SCALE researchers" (`scale:org/scale-researchers`), and one project, `scale:project/methanol-synthesis-pre1966`
  (the methanol benchmark); the institutions, the funder and the funded project it named before
  are removed, as is the `vt` extension prefix (`exmpl` is now owned by the steward). The methanol example's
  stewardship, its graph's header and its stewardship records name that steward and project.
- **Knowledge-graph bundles in format 1.1.0: withheld quotes and typed absences.** The kg-bundle format 1.1.0 carries a quote
  withheld under the copyright cap (`quote_withheld`: its sha256 and length under `scale-match-text-1`, SCALE's
  verbatim normalization) and a value the source does not report (`_value_status`). `scale graph export --to kg-bundle`
  now writes both instead of dropping them: a link whose quotes are all withheld is an edge, and a typed absence says
  why the record has no value. The methanol graph exports as 17,563 edges instead of 14,107 (3,274 substantive edges
  resting only on withheld quotes) with 227 typed absences, and passes the format's validator with 0 errors and 0
  warnings. A withheld quote longer than the format's 600 characters is left out and counted (`withheld_too_long`: one
  in the methanol graph). The bundle is in the example folder (`methanol-synthesis-pre1966_v1.1.0.zip`), and
  [docs/kg-bundle-format.md](docs/kg-bundle-format.md) notes the format SCALE writes. The exporter is
  `tools/scale/kgbundle.py`, and its target `scale graph export --to kg-bundle`.
- **The methanol example, simplified and ready to recurate.** `examples/methanol-synthesis-pre1966/` keeps only what
  a reader and a recuration need: `sources.json` (the frozen corpus, all 178 candidates with their status, each of the
  105 in-scope sources with its PDF `pdfs/<slug>.pdf` and the PDF's sha256; it replaces `corpus/manifest.json`,
  `corpus/manifest-co-co2-hydrogenation.json` and `corpus/sources.json`), the graph, `rights.yaml`,
  `stewardship.yaml` and `queries/*.yaml`. The PDFs are local and git-ignored, named by slug: the DOI with `/` as `-`
  (a patent or report without a DOI: its number or corpus id). Removed and kept in the git history (commit `a169872`):
  release `v1.0.0` (a second copy of the graph), its kg-bundle (regenerated with `scale graph export --to
  kg-bundle`), the curation guide and assembly report, and the conversion tools of the earlier pipeline; recuration
  follows the `curate-source` skill. The query answers are unchanged.
- **Methanol example: 9 runs get the pressure their source states.** Read against its PDF, Molstad and Dodge (1935,
  `10.1021-ie50302a005`) state one testing pressure for their tests in their Experimental Procedure (178
  atmospheres absolute). The six runs of the high-temperature resistance test and the three Zn50Cr50 catalysts
  (dry-process, Groger) had it as not stated; they now carry it, citing that passage (a quote already withheld
  under the cap, so no quoted text is added), as another run of the paper did. Checklist violations: 121 → 112; the
  graph stays valid (0 errors) and every query answers as before. The other gaps were checked and are the sources'
  own: no temperature for the maxima of Frolich et al. (1928), no pressure for the Fig. 7 and 8 runs of
  `10.1246-bcsj.31.45`, and patent examples that only say "similar conditions".
- **Queries reuse what does not depend on the plan.** Every query used to hash the whole document, read its access and
  the publication status of its sources, and gather its evidence quotes, about 100 ms on the methanol graph whatever
  the plan. `pgraph_query.Graph` now computes each once, when first needed, and `run(..., graph=)` reuses it: the
  agent tools keep a document loaded by path with its graph and evidence index until the file changes, and the
  competency questions and proposal checks build one per document. A repeat query on the methanol graph takes 2-15
  ms; the answers are identical.
- **Text queries and search build the evidence index when none is saved.** `scale graph query` (a plan with `text`),
  `scale graph search`, the agent tools `scale_query` and `scale_search`, the competency questions and `scale proposal
  check` used to fail when no index lay beside the document (three of the methanol example's seven plans stopped with
  a missing-file error). The index is derived from the document alone, so they now build it in memory, deterministically
  and writing nothing, as `scale graph index` would save it; a saved index is still used only for its own document.
  The index stays uncommitted: about 30 MB for the methanol graph, and stale after any edit of a quote.
- **Evidence search for large graphs.** The search scored every quote in Python loops; at 930,000 quotes a query took
  2.6-3.5 s and 3.8 GB. It now reads an inverted index (only the postings of the query's words; saved beside the
  index as `<graph>.evidence.terms`, checked against the items it was saved with), computes the int8 cosine in exact
  float32 blocks over norms computed once (the float32 vectors kept in memory after a first query when they fit 2 GB)
  and sorts only the best candidates: about 20 ms (keyword) to 70 ms (hybrid) a query at 930,000 quotes once loaded.
  Results are unchanged: the same hits, scores and order as before in hybrid, vector and keyword mode (checked on the
  methanol graph; ties go by item id as before), so plans and their `min_score` keep their answers. Building the
  index hashes each feature once. A new mode, `rrf` (reciprocal rank fusion of the keyword and vector rankings, scores
  up to 2/61), is opt-in; `hybrid` stays the default.
- **People and agents open pull requests; one person approves and merges** (review policy version 3). An agent may now
  open a pull request ready for review, no longer only a draft; one person other than its author approves it and
  merges it, and agents still never approve, merge or apply. An agent opens its pull request under its own GitHub
  identity (the Claude GitHub App in the scale-agent workflow, or a bot account), never a person's, since GitHub does
  not let an author approve their own pull request (governance/repository-settings.md, "The agent"). The scale-agent
  workflow may run `gh pr create` without `--draft`.
- **The methanol-synthesis example is public** (`examples/methanol-synthesis-pre1966/`), a small benchmark for the
  repository. The curated graph of the historical methanol-synthesis literature published before 1966 was cleared
  for publication; the example keeps its CO and CO2 hydrogenation scope (105 sources, 4,868
  records, 16,586 links, 684 catalytic tests). It was moved from the consortium schema repository's 0.1.0 to its 0.5.0
  with that repository's tools and re-pinned to 0.1.0 (valid, 0 errors), and its quoted text was capped (`scale
  evidence cap`, which applies to the 50 in-copyright sources only; the 55 public-domain sources, the US patents
  and works published before 1931, keep every quote: 6,920 of 25,230 evidence items, all from in-copyright sources,
  carry withheld text). With it: the corpus (`corpus/sources.json`:
  the 105 sources and each PDF's sha256; the PDFs are local), the rights file, the frozen corpus manifest, the curation
  guide and assembly report, the manuscript's seven query plans and the curation tools. Its first release,
  `releases/v1.0.0/` (2026-10-09), is an immutable snapshot: the graph (sha256 `0dfc8c1c…ed13f`), the corpus list,
  the rights file and the plans, with `RELEASE.yaml` (schema 0.1.0 and its spec digest, counts, each plan's answer)
  and `SHA256SUMS`, built and verified by `tools/release_graph.py`. Its kg-bundle,
  `methanol-synthesis-pre1966_v1.0.0`, passes the format's validator (0 errors, 0 warnings): 4,850 nodes, 14,107
  edges; the 3,277 links whose quotes are withheld under the cap are left out, since format 1.0.0 has no place for
  withheld-quote evidence. The fragments, page
  texts, OCR and the earlier private kg-bundles stay in the restricted copy; the evidence index is built locally. New tests,
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
  decide, apply, the version bump after a merge), releases, the kg-bundle export, competency questions, coverage and
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
  ([tools/pagereading.py](tools/pagereading.py); `render`, `region`, `agree`, `check`, `pending`,
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
  [domain/ROADMAP.md](domain/ROADMAP.md).
- **A personal repository.** The owner, Hongliang Xin (@hlxin), owns every path in `.github/CODEOWNERS`; two reviewer
  seats are placeholders, two approvals are required once they are filled, and the owner merges under the bootstrap
  rule until then. The `ci` and `proposal-check` workflows run on pull requests without secrets; `apply-proposals` is
  started by hand and needs a token configured for this repository (`APPLY_TOKEN`); `scale-agent` is off unless started
  by hand; `publish` is inert until the PyPI trusted publisher is configured.
