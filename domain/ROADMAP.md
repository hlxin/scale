# Catalysis roadmap

Open work recorded in this repository, as of schema 0.1.0 (2026-10-08). Nothing here is approved until the
pull request that makes it is. Each item is a suggestion @scale-agents can take up (open an issue for it).

## Schema changes to make

- **Activity in a catalyst state and reaction pathways as records** (catalysis): the activity of a component in a
  catalyst state (which phase or site is active for which reaction, on what evidence), reaction pathways as
  records with their intermediates and rate-determining step, site populations in a state and a test's measured
  product distribution. The draft reporting checklist for authors,
  [docs/reporting/catalyst-state-reporting.md](docs/reporting/catalyst-state-reporting.md), names the fields such a
  change would add; schema 0.1.0 does not have them.
- **Stability maps and the order of phenomena** (kernel): which species or phase is most stable over a region of
  condition space (phase, Pourbaix and regime maps), and the order in time between phenomena. Both are general
  scientific distinctions built from kernel parts, so they belong in the kernel.
- **The schema's wording** (kernel and catalysis): texts
  left as they were, since changing them changes the schema's content ([CHANGELOG](../CHANGELOG.md), "Schema
  texts"; [core/README.md](../core/README.md), "Known follow-ups"):
  - the example in the kernel's `graph.follows_domains` description, `thermocatalysis@0.1.0`, names a frozen
    driving-force profile of the consortium schema repository's earlier numbering, which this repository does not
    hold (a document that follows it gets an unknown-domain error); the example becomes `catalysis` or
    `catalysis@0.1.0`;
  - the checklist's `basis` in `graph/catalysis.yaml` cites "the adopted catalysis schema 0.1.0" three times (the
    thermal, electrochemical and photochemical profiles): the catalysis schema 0.1.0 of that earlier numbering, not
    this repository's scale-graph 0.1.0; the text names where the profiles came from instead (for example "the
    thermal profile of the consortium schema repository's catalysis schema 0.1.0");
  - the kernel's `Operation` text that still speaks of driving-force domains, the descriptions that still speak of
    modules, and the informational `extensions.registry` path.
- **Units**: unit conversion and basis reading in queries are planned with a units change; until then a numeric
  filter compares only values in the unit it states ([docs/querying.md](../docs/querying.md)).
- **Value and statement forms the curation guidance already plans for** (kernel; [docs/curation.md](../docs/curation.md)
  and the curate-source skill say what to record until then):
  - a relative uncertainty (an RSD, "± 5 %" of the value) as a form of the value object's uncertainty, and an
    interquartile range as an uncertainty kind (until then: `as_reported` and `note`);
  - `statement_kind` on links (`conclusion` for interpretive links such as HAS_SITE, INHIBITED_BY, IDENTIFIED_AS
    and an inferred CATALYZES; `assumption` for links taken as given), which the kg-bundle export infers until then;
  - `former_ids` on the surviving record of a merge (until then the merge map is kept beside the document and
    given to the kg-bundle export with `--replaced`);
  - `update_type: reinstatement` for a notice that reverses a retraction or an expression of concern (until then
    it goes in the retracted source's `unmodeled` list).
- **Characterization results as declared properties** (catalysis): specific and external surface area, pore
  volume and diameter and the other keys the recording recipes list
  ([skills/curate-source/references/recipes.md](../skills/curate-source/references/recipes.md),
  "Characterization results"), which go in a Characterization's `results` map until then.

## Open themes of the earlier gap register

The gap register of the consortium schema repository was not carried; the register here
([docs/gaps/register.json](../docs/gaps/register.json)) starts empty and is filled as changes answer themes. The
themes it still held open or partly resolved are tracked here until a curation closes them or a schema change takes them
up (stability maps and the order of phenomena are under "Schema changes to make"):

- **Source lifecycle follow-ups** (kernel and tools):
  - checking sources against registries (Crossref update metadata, Retraction Watch): no tool does it yet, and
    `status_check` records a check a person made. A lookup sends a source's identifiers to the service, which
    then learns what a corpus holds, so a tool must not do it for a corpus that may not be disclosed;
  - the partly resolved provenance themes: the source lifecycle answers them in the schema, but the review gaps that
    raised them were not checked against it again: whether and how a source or dataset was checked for notices;
    notices other than a full retraction (partial retractions, corrections, expressions of concern, withdrawals);
    the text that was read; versions, translations and duplicates of one work; the dates of sources and datasets;
    which statement of a retraction prevails, and what a retraction does to the records. Each closes once a
    curation shows that the schema records it, or leads to a schema change for what remains (such as
    `update_type: reinstatement`, above).
- **Catalyst states and contexts** (catalysis), partly resolved: the catalyst states and contexts of 0.1.0 answer
  these themes in the schema, but the gaps that raised them, recorded in curations that are not in this repository,
  were not checked against them again: surface components and molecular detections; measurement during a treatment
  and states inferred from reactivity; site populations covered by a phase or assigned a pathway effect; computed
  pathway results paired with predicted states; the delay from a trigger to the onset of a transition. They are
  checked when those sources are curated under the current version; site populations and pathway effects overlap
  "Activity in a catalyst state and reaction pathways as records" above.

## Checklist review

The reviewers of the thermo, electrothermo, electro, photo and plasma areas check each case of the catalysis
checklist: its field lists are suggestions for review.

## Stewards

The catalysis domain has one steward. Its stewardship target is two or more; until more stewards join,
`scale domains check` reports the unmet target as a warning. A reviewer seat in
`governance/review-policy.yaml` (placeholders today) must be filled before the owner's changes can be approved; until
then the owner merges under the bootstrap rule ([governance/GOVERNANCE.md](../governance/GOVERNANCE.md)).
