# Licensing, copyright and project data

How the contents of this repository are licensed, how much of a source a curated record may quote, which
data may be committed, how contributions to the catalysis domain are licensed, and how to cite. The decisions are
recorded in [decision record 0001](../docs/decisions/0001-scale-0.1.0.md) (items 6 to 8). This file,
[`REUSE.toml`](../REUSE.toml), [`NOTICE`](../NOTICE), [`LICENSE`](../LICENSE) and [`LICENSES/`](../LICENSES/)
are owned, like every path, by the owner, `@hlxin`.

## 1. The licence model

| what | licence | where |
|---|---|---|
| code: the `scale` package and everything under `tools/` except the skills' texts and the texts of the domain-template test fixture, every Python file anywhere (catalysis tests, example tools, builders), packaging and CI files | MIT | [`LICENSE`](../LICENSE), [`LICENSES/MIT.txt`](../LICENSES/MIT.txt) |
| vocabulary (the science kernel `core/`, the catalysis domain `domain/`), curated records, examples and fixtures, documentation (`docs/`, the root documents), governance, the skills' texts (`tools/skills/`), the texts of the domain-template test fixture (`tools/tests/fixtures/domain-template/`, its Python files excepted), `CITATION.cff`, `scale-release.yaml` and the releases `releases/v*/` | CC-BY-4.0 | [`LICENSES/CC-BY-4.0.txt`](../LICENSES/CC-BY-4.0.txt) |
| third-party material | its owners' terms | [`NOTICE`](../NOTICE) |

[`REUSE.toml`](../REUSE.toml) is the record: it gives every file its licence by path (the
[REUSE specification 3.3](https://reuse.software/spec-3.3/); later entries override earlier ones), and
`scale check` runs `reuse lint` ("licence annotations are complete"), which fails when a file has no licence
or a licence named there has no text in `LICENSES/`. `LICENSE` at the root holds the same MIT text so that
GitHub and package indexes detect it. The copyright holder is "SCALE contributors": contributors keep the
copyright in their contributions and license them as below.

The Python package (`scale-schema` on PyPI) declares `License-Expression: MIT AND CC-BY-4.0`, since its wheel
holds code and the bundled vocabulary, records and documentation; it ships `LICENSE`, `LICENSES/MIT.txt`,
`LICENSES/CC-BY-4.0.txt` and `NOTICE`. No file of the repository is under a third-party licence. `CITATION.cff` says `license: MIT`: it describes the software, and its format has no way to state that
two licences apply together.

**Official releases are not a licence restriction.** "Official SCALE release" names what this repository's
release process produces ([release-process.md](release-process.md)). The licences
grant everyone the right to use, fork, modify and redistribute the contents under their terms; the
contribution model and the review process do not narrow that right.

## 2. Contributions: inbound = outbound

A contribution is licensed under the licence that `REUSE.toml` gives its path: code under MIT, vocabulary,
records and documentation under CC-BY-4.0. Opening a pull request (or submitting content through the
[contribution form](../.github/ISSUE_TEMPLATE/contribution.yml)) means agreeing to that and confirming that
you have the right to contribute the content.

- **Sign-off is recommended, not enforced.** Signing commits with `git commit -s` adds a
  `Signed-off-by:` line certifying the [Developer Certificate of Origin](https://developercertificate.org/).
  No check requires it.
- **New licences need a decision.** Material under another licence (an adopted vocabulary, a dataset, a
  figure) enters only with an entry in `REUSE.toml`, its licence text in `LICENSES/` (obtained with
  `reuse download <SPDX id>`, never paraphrased) and a line in `NOTICE`, decided by people in a pull
  request (the owner owns those files). Material whose licence does not allow redistribution stays out.
- **Credit** is recorded in `CORE.yaml` and `DOMAIN.yaml` and in commit trailers
  ([credit-and-authorship.md](credit-and-authorship.md)); it is separate from the licence.

## 3. Quoted evidence: short quotes, capped

Curated records cite their sources with short verbatim excerpts. The policy, as `scale check` implements it
(`tools/scale/rights.py`; [docs/curation.md](../docs/curation.md)):

- **Rights per source.** Each folder with research-data documents has a `rights.yaml`:
  `sources: {<source id>: {class: public_domain | open | restricted | in_copyright | synthetic,
  licence: <SPDX id or text>, basis: <why>, text_chars: <int, optional>}}`. A source without an entry counts
  as `in_copyright`.
- **The cap.** For `restricted` and `in_copyright` sources each quoted text (`quote`, `transcription`,
  `second_reading`) is at most 300 characters, and the distinct quoted characters of one source are at most
  4,000 and at most 10 % of `text_chars` when it is known. Public-domain, open and synthetic sources have
  no cap; their quotes are still only text found verbatim.
- **Free text.** Claim statements, names and notes are the curator's own words and do not copy an
  in-copyright source beyond a short phrase (a curation rule, not machine-checked without the text).
- **Withheld text.** Text beyond the cap is withheld: the evidence item keeps its source, locator and
  kind (and passage, region); the text is removed and `note` records `<field> withheld: sha256:<hex>
  chars:<n>`, the digest and length of the text under the verbatim checker's normalization.
  `scale evidence rehydrate` restores it from one's own copy of the source; `scale evidence cap` withholds
  deterministically (evidence of quantitative values first, then shorter texts, then by record id).
- **Checked.** `scale check` runs `scale evidence report --all`: every committed document that is not a
  synthetic example (`research_data` or `mixed`) needs a rights file, every Source a rights entry, and every
  capped source must be within its cap.

The quoted excerpts stay under their sources' terms; the CC-BY-4.0 licence of a record covers the
contributors' own work in it (structure, values as curated, notes), not the excerpts.

## 4. Project data and access levels

Every record carries stewardship: who contributed it (`contributed_by`), which project it belongs to
(`project`) and who may see it (`access`): `public` (anyone), `consortium` (any institution in a project
of the graph), `project` (the record's project), `institution` (the contributing institutions) or
`embargoed` (the contributing institutions until `embargo_until`, then `access_after_embargo`). The graph
header gives the default and a record may override it field by field (`scale graph filter` shows a viewer
what they may see).

- **Everything committed is public, explicitly.** Every scale-graph document in the repository states
  `access: public` for its graph and leaves every record public (`scale evidence access`, a step of
  `scale check`). A missing access is not public: the visibility rule reads it as `institution`. The
  synthetic examples kept in an applied proposal's record stay as they were written and are exempt.
- **Project data stays out until cleared.** Data that its project partners have not cleared for
  publication is never committed. It stays in a data repository of its own, under the projects' own terms;
  neither licence of this repository applies to it. The tools may read inputs that may not be committed
  from an optional restricted copy outside the repository (named by an environment variable only, with no
  default location); a proposal that reads such inputs writes its full reports there and keeps public
  summaries in the repository.
- **Publishing it** needs the partners' clearance, then: access set to `public`, the copyright cap applied
  (`scale evidence cap`), the claim statements reviewed, and a pull request that `scale check` passes and
  two reviewers approve.
- **Synthetic look-alikes.** Where an example or fixture needs the structure of project data, it uses an
  invented source and invented values (`data_status: synthetic_example`, `ex:exmpl/` ids).
- Laboratories that keep restricted records in their own databases pin an official release and
  contribute back definitions, mappings, questions or synthetic fixtures
  ([GOVERNANCE.md](GOVERNANCE.md#project-data)).

## 5. Contributions to the catalysis domain

The catalysis domain is licensed like the rest of the repository: its vocabulary, competency questions,
examples, records and documentation under CC-BY-4.0, its Python code under MIT (the `domain/**` entries
of `REUSE.toml`). The catalysis domain's maintainers cannot choose another licence for its folder on their own: a
different licence, or adopting an external vocabulary or dataset with its own terms, needs a decision
record and the `REUSE.toml` and `NOTICE` entries above, approved like every change. Curated catalysis
data follows sections 3 and 4.

## 6. How to cite

- **The software and its vocabulary**: cite the release you used, as [`CITATION.cff`](../CITATION.cff) says
  (GitHub's "Cite this repository" renders it); tagged releases will be archived with a DOI.
- **Attribution under CC-BY-4.0**: "SCALE contributors", the title of the material, a link to
  `https://github.com/hlxin/scale` (or the release), the licence, and whether you changed
  it. For a schema, name its version and spec digest (`scale-graph 0.1.0`, catalysis); for a record, its id and release.
- **The sources behind a record**: cite the publications its evidence names, not only SCALE.
- Who is credited in releases, and authorship of publications: [credit-and-authorship.md](credit-and-authorship.md).
