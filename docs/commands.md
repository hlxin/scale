# Commands

Every command below runs the same way with `uvx scale-catal …` (no install) or `scale …`
(after `pip install scale-catal`). `scale --help` and `scale <command> --help` list the options.

| operation | command |
|---|---|
| scale-graph: describe, validate, query, search | `scale graph describe [labels] --domain D` (D: the checklist to show, catalysis; its `when` cases are printed with their conditions, and each label names the file that declares it, `defined_in`), `scale graph validate FILES` (a document pinning a version this repository does not hold is refused with the reason, never read under another version: a version newer than the head is named so, and the graph of a kg-bundle, whose `schema_version` is the bundle's own version, as a bundle's graph; query, search, stats, migrate and export refuse it too), `scale graph query G PLAN`, `scale graph index\|search G` (an index records the digest of the document it was built from, and query and search use it only for that document, or one whose quotes it holds exactly; with none saved beside the document, they build it in memory from the document and write nothing; modes hybrid (default), vector, keyword and rrf (reciprocal rank fusion); a search result carries the document's `access`; a query's and a search's embargoes are read on today, the earlier of the local and the UTC date, as `scale graph filter` and the exports read them, or on a plan's earlier `as_of`) |
| scale-graph: labels, properties and units in use and link patterns, what a viewer may see, move a document to the current schema version (or, with `--spec`, to the version of another manifest) | `scale graph stats G`, `scale graph filter G [--as ID\|--public] [--date YYYY-MM-DD] [--out FILE]` (embargoes are read on `--date` or today, whichever is earlier, so a later date never opens one still in force; today is the earlier of the local and the UTC date, on every path that reads an embargo (this filter, a query, a search, the exports), so no path ships a record another still withholds; a kept record's references to hidden records go too; a value that names one is withheld in its place, a property, a list entry or a map entry becoming `not_reported` with `missing_reason: withheld`, which a query reads as `withheld`, not as the source being silent or as not curated; a record_ref path into a kept record moves with a ref-list entry or evidence item removed before it, and one to a part removed or withheld goes; `evidence_ids` naming a removed evidence item go, and a value stated only by removed evidence is withheld. Only `evidence_ids` tie a value to its source: on a record that lost evidence, a value without them may rest on a withheld source alone and is withheld in its place, never left cited to the evidence that remains, nor is a value whose `evidence_ids` name no evidence left, and `filtered_for` counts the kept records that lost evidence. When the viewer may not see the graph's header stewardship and is the public, one project or institutions, the view's header declares that audience, as a kg-bundle's does, each kept record first getting the audience keys it inherited, so its own access is unchanged: a public view of a project graph is public, and its answers too. An embargo stated to the year or month holds to its end, and a stewardship or `embargo_until` that is malformed reads as institution, never as open), `scale graph migrate G DEST [--spec MANIFEST]` |
| scale-graph: the schema and its frozen versions load; frozen files match their SHA256SUMS; every version keeps the spec digest the releases hold; a version's spec document and its digest | `scale graph verify` (prints every version's `spec_sha256`; there is no frozen version and no release yet), `scale graph spec [--domain D\|--spec M] [--version V\|--all] [--out FILE\|DIR] [--expect SHA256]` (the assembled schema as canonical JSON, with the same sha256 whether the version is the head or frozen: the digest a reader binds a schema by, since a version number names a schema only within this repository's numbering; `--expect` says whether the version, the head unless `--version`, is the schema of that digest here and exits 1 when it is not; README.md, "Schema versions") |
| scale-graph: export (Neo4j, kg-bundle) | `scale graph export G --to neo4j\|kg-bundle` (kg-bundle: `--out DIR [--public\|--as ID] [--keep-less-open] [--text ID=FILE:LICENCE] [--version V] [--previous DIR\|--ids-from DIR] [--replaced FILE] [--corpus MANIFEST]`; the bundle names its schema by version and digest, carries `scale_header` in bundle.json, withholds records that part of its audience may not see, the audience being the graph's stewardship, the public with `--public`, or the viewer's own with `--as` (one project, or institutions; a person, several projects or a mix is refused), with every reference a kept record makes to them, unless `--keep-less-open` (which marks each record of another audience with `scale_access` and its project or institutions, and counts those part of the audience may not see in `access_at_export.less_open_kept`), leaves out a `--text` whose source it does not hold and the texts an earlier export left in DIR (only plain file names its manifest gives), and warns when it is not public, naming the audience, or when it holds records part of its audience may not see; embargoes are read on the `--created` day or today (the earlier of the local and the UTC date, as `scale graph filter` reads it), whichever is earlier, so a later `--created` never opens one still in force; a header stewardship that is malformed reads as institution, never as open, and a project or `contributed_by` that is not an id names none; `scale_header` always states an access, institution where the graph states none; `--previous` keeps the previous release's ids, records it with the id changes and carries its changelog forward, and needs a later `--version`; `--ids-from` keeps an earlier build's ids without recording it; `--replaced` maps a retired scale-graph id to its survivor, which lists the retired released id in `replaced_ids`; `--corpus` fills the corpus block from a manifest `scale corpus check` passes; the export report counts what was converted, kept as text, left out (typed absences), inferred (`_statement`) and withheld) |
| readings of scanned pages by two readers: page images and positioned OCR words, the tool's agreement of each reading with OCR in its region, independent second readings ([curation.md](curation.md#reading-scanned-pages-two-readers)) | `scale pages render PDF --source ID --pages DIR [--dpi 200] [--only 1,3]` (page images and the words of the text layer and of OCR, with the OCR engine, in `DIR/<source key>/`; needs pymupdf, OCR the tesseract command; the folder reproduces the source and stays local), `scale pages region --pages DIR --source ID PAGE X0 Y0 X1 Y1 [--transcription TEXT]` (a 400 dpi crop and what OCR reads there), `scale pages agree DOC --pages DIR` (writes `agreement` on every evidence item read from an image and the engines in the document's `ocr_engines`), `scale pages check DOC --pages DIR [--second FILE]` (an agreement that differs is an error with the recorded engines and a warning with others; a reading OCR does not confirm needs a matching independent second reading, a figure point within 5 % or 0.3; every value of a record read from an image is in a transcription or quote; exits 1 on an error), `scale pages pending DOC --pages DIR [--no-crops]` (one item per region with its crop, never the transcription), `scale pages merge-second DOC SECOND` (`{"<record id>#<i>" or "<region id>": reading}`), `scale pages import CACHE --pages DIR [--overwrite] [--written-here]` (words from another pages folder) |
| a frozen corpus manifest | `scale corpus check MANIFEST [--included STATUS …] [--frozen-at DATE] [--description TEXT]` (every candidate source has a status, included or the reason it was left out, a bare `excluded` with a `status_reason`; each is listed once; `counts` add up; prints the bundle corpus block and exits 1 on a problem) |
| scale-graph: a schema change on a branch (the version raised by the rule, the base frozen, the migration step, its checks) | `scale schema diff [--base REF] [--json]` (what the branch changes in the schema against the merge base, its kind and the version that follows), `scale schema bump [--base REF] [--note N]` (freeze the base version, raise the one version in every file that states it, register the migration step), `scale schema check [--base REF] [--comment FILE] [--json]` (what a schema change must carry; exits 1 if not; `--comment` writes the reviewer's summary, which CI puts in the job summary); REF defaults to `origin/main` (below) |
| quoted evidence and publication rights: the copyright cap per source, withheld quotes, every committed document public ([curation.md](curation.md)) | `scale evidence report G [--rights R]` (or `--all`: every committed document that is not a synthetic example, `research_data` or `mixed`; each needs a `rights.yaml` in its folder or above with an entry for every Source it names, and the command exits 1 on a missing file or entry or a quote beyond the cap), `scale evidence cap G [--rights R] [--texts DIR] [-o OUT]`, `scale evidence rehydrate G (--texts DIR \| --source-text ID=FILE …) [-o OUT]`, `scale evidence gap-report REPORT.json (--corpus PATH | --rights R) [-o OUT.md]` (a gap report checked before it leaves a data repository: only corpus, sample and themes with instances of source, locator and quote; every source in the rights file; every quote at most 300 characters and each source within its cap; the Markdown is written only when it passes, and the command exits 1 otherwise), `scale evidence access [FILES]` (every committed scale-graph document, or the given ones, states `access: public` for its graph and leaves every record public; a missing access counts as not public, as the visibility rule reads it) |
| agent tools (JSON in, JSON out) | `scale call [tool] ['<json>']`, `scale mcp`, `scale serve` ([integrate.md](integrate.md)), `scale tools [--format jsonschema\|openapi\|mcp]` (the tool definitions) |
| install the skills into an agent | `scale skills install TARGET [--release R] [--force]` (each skill's whole folder: its SKILL.md and the files it points to, such as `references/`) |
| gaps → GitHub issues | `scale gap list DIR`, `scale gap issue GAP.json [--submit]`, `scale gap from-query RESULT.json --out-dir DIR` (from a `scale graph query` result; each gap carries the result's `access`, and `scale gap issue` warns on, and `--submit` refuses, a gap whose access is not public or not stated, which reads as institution: a gap written by hand states `access.level: public` to be filed) |
| list / build / verify releases | `scale release list\|build\|verify` (none is built yet; a build: `scale release build vX.Y.Z [--date YYYY-MM-DD]`, below) |
| the science kernel and the catalysis domain | `scale domains list [--format json]`, `scale domains check [NAMES] [--json] [--no-examples]`, `scale domains cq [NAMES] [--json]` (the competency questions; below) |
| what a pull request may change, what a schema change must carry, who reviews it | `scale ci spec-changes --base REF [--head REF] [--json]` (below) |
| human checks of curated records (approving is a GitHub review of the pull request; nothing here approves) | `scale review sample G [--fraction F] [--include-flagged]` (a reproducible sample of evidenced records for a person to check against the sources) |
| a knowledge-graph data repository: update every document to a new schema version | `scale kg update [--data DIR] [--domain D] [--to V] [--dry-run] [--no-index] [--out FILE]` (below) |
| every check of CI's `test` jobs, before a pull request | `scale check [--fast]` |
| formats and names, documentation links | `scale fmt [--check]`, `scale lint`, `scale links` |
| community feedback → a weekly digest for the reviewers | `scale triage ingest\|propose\|publish` ([governance/feedback.md](../governance/feedback.md)) |
| readable catalogue of a document, comment links | `scale catalogue G --out FILE`, `scale suggest --record ID \| --text … [--title …]` |
| implementation-status inventory | `scale status [--format markdown] [--out FILE]` |

SCALE reads and writes one data format, scale-graph documents (node-link JSON), each pinning the schema
version it follows.

## The science kernel and the catalysis domain: `scale domains`

SCALE's schema has two layers: the science kernel (`core/`) and the domains; catalysis, the first and for now the
only domain, is the one folder `domain/` beside the core. The catalysis domain is declared by `domain/DOMAIN.yaml`,
whose `domain: catalysis` names it; its graph schema manifest `graph/scale-graph.yaml` lists the catalysis file
`catalysis.yaml` (`domain: catalysis`) under `domains:`; the kernel declares itself in `core/CORE.yaml` (field
reference: [domain/README.md](../domain/README.md)). `--domain` and `follows_domains` name the checklist that
applies (`catalysis`). The schema has one version for the kernel and the catalysis domain together, the manifest's
`version`. `scale domain` is the same command group as `scale domains`.

```bash
scale domains list [--format json]          # name, status, version, team, stewards, listed in scale-release.yaml
scale domains check [NAME] [--json] [--no-examples]
scale domains cq [NAME] [--json]             # run the competency questions and compare with their expectations
scale domain list|check|cq …                 # the same commands
```

`check` runs at the root of a repository checkout (it is a step of `scale check`) and exits 1 on any error.
NAME (`catalysis`) limits the check to the core's rules and the domain's when it is the domain's name. It checks:

- `core/CORE.yaml` and `domain/DOMAIN.yaml`: required keys and types, no unknown keys, semantic versions,
  `domain` a name (lowercase letters, digits and single hyphens), the one shape for people (`maintainers: {team,
  people: [{name, github, orcid?, since, roles: [steward|maintainer]}]}`, `contributors: [{name, github?, orcid?,
  roles}]`; a seat not filled yet has `placeholder: true`), at least one steward; every declared path exists;
  `competency` and `tests` use the names the tools read; the tests directory holds a `test_*.py`,
  the competency directory a question;
- **one version**: `version` in `CORE.yaml` and `DOMAIN.yaml`, `schema_version` in `scale-release.yaml` and the
  kernel-only example manifest's `version` agree with the catalysis manifest's `version`;
- `depends_on` is empty (catalysis is the only domain beside the core); `alternative_to`, when set, names a
  scale-graph file; every scale-graph `imports` resolves to the kernel or the domain's own files;
- the domain's graph schema manifest (`graph.manifest`, the only key of `graph`, required when `graph` is
  declared) uses the core's kernel, lists under `domains:` files inside `domain/`, among them the one named
  after the domain (`domain: <name>`), has no `modules:`, `extensions:` or `profiles:`, and loads; each of the
  domain's files names itself with `domain:`;
- **identifiers**: one index over the kernel and the domain's graph files (file names, labels, edge types,
  properties per label, bridges included); a redeclaration is an error naming both owners. Extending is
  `is_a`, `extends` or `adds_properties` with a new key;
- no copies of core files anywhere in `domain/`, its frozen versions included (no `kernel: scale-graph-kernel`
  file, no file byte-identical to a core file);
- `scale-release.yaml` names `core` and, in `domain_profiles`, `domain/DOMAIN.yaml` unless the domain is
  experimental, and has no `graph` key;
- `.github/CODEOWNERS`: a `/domain/` line naming the domain's code owner (not overridden by a later line); the
  core's declaration owned by the core's code owner (both `@hlxin` today);
- the `example_documents` validate against the domain's manifest at the version they pin (the head or, once a
  schema change has moved it on, `graph/frozen/scale-graph-<version>.yaml`; the core's against
  `core/examples/science-kernel-only.yaml`);
- the competency questions run (`scale domains cq`); one that does not answer as expected is a warning here and
  an error of `scale domains cq`;
- for `status: stable`, the stewardship targets: two or more stewards, three or more competency questions
  that run and answer as expected (stubs without a plan do not count), example documents, a `decision_record`
  (`docs/decisions/NNNN-*.md`, repository-relative). For catalysis (`founding: true`) they are warnings;
  otherwise errors. A deprecated domain needs `deprecation` and a `decision_record`;
- a **warning** when the review policy lists reviewers by area and nobody lists one of the domain's
  `review_areas` (the policy has one reviewer group for every area, so there is none today).

There is no command that scaffolds a domain. The tests scaffold a synthetic one as `domain/` of a temporary
repository with `new_domain()` from the fixture `tools/tests/fixtures/domain-template/` to exercise these rules on
another domain than catalysis.

## Pull requests: `scale ci spec-changes`

```bash
scale ci spec-changes --base origin/main [--head HEAD] [--json]
```

It compares the branch with its merge base on `--base` and exits 1 when the branch

- modifies, deletes or adds a file inside a release (`releases/<id>/`, a directory holding `RELEASE.yaml`),
  modifies or deletes a frozen file under `core/graph/frozen/` or `domain/graph/frozen/` (each `SHA256SUMS` may
  only gain lines), or modifies any other existing file under `releases/` except the `README` and `CHANGELOG`
  files directly under it; new releases and new frozen versions pass;
- changes `core/graph/` or the catalysis domain's `domain/graph/` files (schema manifest included; not while the
  domain is experimental at both the merge base and the head) without what `scale schema check` asks (below).

It prints whose review the change requests according to `.github/CODEOWNERS` at the merge base (the owner sets;
the fewest owners who own every changed path; a code owner's approval is not required), the rule that every pull
request needs one approving review by a person, any listed reviewer (the owner's own pull requests are merged under
the bootstrap rule until another reviewer joins), and, when `core/` changes, the catalysis domain it affects.

## Schema changes: `scale schema`

```bash
scale schema diff --base origin/main        # what the branch changes in the schema, its kind, the version that follows
scale schema bump --base origin/main        # freeze the base, raise the version, register the migration step (once)
scale schema check --base origin/main       # what the pull request must carry (CI runs it); exit 1 if not
```

A schema change is a pull request that edits `core/graph/kernel.yaml` or `domain/graph/catalysis.yaml` directly
([evolution.md](evolution.md)). All three commands compare the working tree with the merge base of `--base`
(default `origin/main`), rebuilding the base's schema from git. `diff` prints the semantic diff (added, loosened,
changed, narrowed, removed) and the version the change needs: a breaking change (something removed, changed or
narrowed) raises the second number (0.1.0 -> 0.2.0), any other change the third (0.1.0 -> 0.1.1).

`bump` freezes the base version (its kernel as `core/graph/frozen/kernel-<v>.yaml`, the catalysis manifest as
`domain/graph/frozen/scale-graph-<v>.yaml` with its parts in `v<v>/`, digests appended to each `SHA256SUMS`),
raises the version in the manifest, `CORE.yaml`, `DOMAIN.yaml`, `scale-release.yaml`, the kernel-only example
manifest and the sentences of the documentation that name it, and registers `STEPS[<base>] = (<new>, <note>)` in
`tools/scale/pgraph_migrate.py`. It refuses an unchanged schema, a version raised already and a version frozen
before, and writes into a repository checkout only.

`check` asks for: the version raised by the rule; the base frozen, its copy's spec digest equal to the base's;
every file stating the new version; the migration step, and for a breaking change its rule (`STEP_RULES[<base>]`);
every label and edge type the change adds used in a valid fixture or example document; and a changed
`CHANGELOG.md`. It reads the steps from the repository's own `pgraph_migrate.py`. `--comment FILE` writes the
reviewer's summary (Markdown); `--json` prints the whole result. `scale ci spec-changes` runs it when the
specification changes.

## Knowledge-graph data repositories: `scale kg update`

```bash
scale --repo ../scale kg update --data . --dry-run       # in a data repository: report only
scale --repo ../scale kg update --data .                 # write in place
```

For every scale-graph document of the catalysis domain (`--domain`, default catalysis) under `--data`, outside
sealed packages (`.scale-verbatim`) and `work/` folders: move it to the head schema version
(or `--to`) through the registered steps (`scale graph migrate`'s; none yet at 0.1.0), validate it before and
after (errors, warnings, checklist violations), write it in canonical JSON and rebuild its evidence index
(`<name>.evidence.jsonl`, with the embedder recorded in the old index) unless `--no-index`. A document a step rule
cannot map is refused and untouched; one whose migrated form has more validation errors is not written; one
pinning a version this repository does not hold is refused; a file whose name pins a version
(`*.scale-graph-0.1.0.graph.json`) is kept. It exits 1 when a document was refused.

## Competency questions: `scale domains cq`

```bash
scale domains cq [NAME ...] [--json]
```

The catalysis competency questions (`domain/competency/*.yaml`) say what its schema must let people
ask. Each names its `id` and `question`, the public example `documents` it runs on (among the catalysis
`example_documents.graph`, with stewardship access public), a scale-graph query `plan` and what the answer
must be (`expect`: `status`, optionally `min_rows`, `max_rows`, `values` that rows must return, `schema_gaps`).
`cq` runs each plan on each document under the schema version the document pins and compares the combined
answer with the expectation; it exits 1 when a question does not answer as expected (a step of `scale check`).
A question without a plan is a stub: listed, not counted. Format reference: `tools/scale/competency.py`.

## Release builds: `scale release build`

```bash
scale release build vX.Y.Z [--date YYYY-MM-DD]        # a human action
```

The first release is `v0.1.0`, with schema 0.1.0. A release is always built from the
repository head, under the version `scale-release.yaml` names (`--override-version` renumbers on purpose). It
copies and digests the core declaration, the science kernel and its frozen versions, the catalysis domain (each
folder in `domain_profiles`) with its `DOMAIN.yaml`, its schema manifest, every part it lists and its frozen
versions, and the skills. `RELEASE.yaml` records `component_versions` (the schema's one version; the core, the
kernel and the catalysis domain at that version, with the domain's status and scale-graph manifest; the tool; the
skills), `contributors` (from the kernel's and the catalysis domain's maintainers and contributors, deduplicated by
GitHub handle, with roles and scopes; placeholders are never credited), `excluded_domains` (experimental folders;
none today), `source` (repository and tag), `spec_documents` (every version of the released schema as a spec
document, `specs/<domain>/scale-graph-<version>.json`, with its sha256; `scale graph verify` fails when the
repository's copy of a version no longer has that digest), and, against the previous release,
`comparison_to_previous`: a semantic diff of the kernel and of the catalysis assembled schema (labels, edge types,
properties and checklist items added, removed, changed, narrowed or loosened, classified `identical`, `additive` or
`breaking`) and the files added, changed and removed.

The gate: schema content changed since the previous release under the version of the previous release is refused
(each schema change raises the version in its own pull request). The build also refuses an experimental folder in
`domain_profiles` and schema manifests that name several versions. The first release has no previous release and
records no comparison.

## Repository layout

```
scale-release.yaml  the head release manifest (distribution, release, schema_version, core, domain_profiles, skills)
core/               the science kernel: CORE.yaml (its declaration), graph/kernel.yaml, graph/frozen/ (the kernel
                    of each earlier schema version, once the schema has changed), examples/, tests/
domain/             the catalysis domain: DOMAIN.yaml (its declaration), graph/ (scale-graph.yaml, the catalysis
                    file catalysis.yaml with its one checklist, frozen/ versions once the schema has changed),
                    competency/ (graph query plans with expected answers), examples/ (synthetic scale-graph
                    examples), docs/, tests/ (unit tests, invalid fixtures)
tools/              scale/ (Python package and `scale` CLI), skills/ (versioned SKILL.md procedures), tests/
governance/         GOVERNANCE.md, review-policy.yaml, feedback.md, and the extension-prefix and stewardship registries
releases/           immutable releases with sha256 digests (the first is v0.1.0)
docs/               architecture, workflows, decision records, gap register, status inventory
```
