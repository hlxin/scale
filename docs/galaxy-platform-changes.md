# GALAXY: changes requested by SCALE

For the Alchemic platform team (`alchemic-platform`, `docs/galaxy/kg-bundle-format.md`, `src/alchemic/galaxy/`).
Status: requested 2026-10-09; nothing here is implemented yet.

SCALE exports its knowledge graphs as GALAXY bundles (`scale graph export <graph> --to galaxy`). The bundles are
valid today: the first public one, `examples/methanol-synthesis-pre1966/galaxy/methanol-synthesis-pre1966_v1.0.0/`,
passes `bundle_validate.py` with 0 errors and 0 warnings. But the format cannot carry three things SCALE's rules
require, so the bundle is smaller than the graph it comes from:

| what SCALE keeps | what the bundle loses today | change |
|---|---|---|
| evidence whose quote is withheld under the copyright cap, which applies to in-copyright sources only (source, locator, passage, sha256 and length of the quote) | **3,277 links**, all from in-copyright sources: 14,107 edges instead of 17,563 (8,477 substantive instead of 11,751, 28 % fewer) | 1 (required) |
| the schema a graph follows, named by version **and** spec digest | nothing is lost, but GALAXY cannot tell that two bundles share a schema | 2 |
| typed absences: a value the source does not report, did not measure, or gives below a detection limit | 229 absences | 3 |

One bundle serves everyone: it follows SCALE's rules (public, quotes within the cap). With change 1, the next
release of the methanol bundle carries every link (17,563 edges, 11,751 substantive) instead of 14,107.

## 1. Withheld-quote evidence (required)

**Why.** SCALE publishes research graphs built from in-copyright papers. Its copyright cap (governance, in
`hlxin/scale`) lets each such source be quoted for at most 300 characters a quote and 4,000 distinct characters
and 10 % of its text in all; the rest of the quoted text is withheld, kept as the sha256 and length of the quote.
The record keeps its source and page, so a reader with the paper can find and check the passage. GALAXY's
principle 1 ("every substantive edge carries at least one verbatim quote") cannot accept such evidence, so SCALE
leaves those edges out. A located, digested quote is still a claim with a source; the change lets GALAXY carry it
and say plainly that the text is withheld.

**Format (bundle format 1.1.0, additive).** An evidence object carries either `quote` or `quote_withheld`, never
both:

```json
"_evidence": [{
  "source_id": "10.1002/jctb.5000501602",
  "locator": {"page": 1},
  "quote_withheld": {"sha256": "9ab6627a3e2430ce0ea66cd91c58533f5329e417a7fe83a2874a5f0d610dc1bc", "chars": 198,
                     "normalization": "scale-match-text-1", "reason": "copyright"}
}]
```

- `sha256`: 64 lowercase hex digits, the sha256 of the UTF-8 bytes of the quote **after normalization**;
  `chars`: the number of code points of the normalized quote (1–600).
- `normalization: "scale-match-text-1"` is SCALE's verbatim-match normalization (`match_text` in
  `tools/scale/util.py`), applied in this order: remove U+00AD (soft hyphen); Unicode NFKC; map the dashes
  U+2010 U+2011 U+2012 U+2013 U+2014 U+2015 U+2212 U+FE63 U+FF0D to `-`; remove all whitespace (`\s+`);
  lowercase; remove every `-`. A quote is found in a text when its normalized form is a substring of the
  normalized text.
- `reason`: `copyright` (the only value for now).

**Validator rules.**

- Exactly one of `quote`, `quote_withheld` per evidence object (**error** otherwise); `sha256` and `chars` well
  formed (**error**); `normalization` a known value (**error**).
- `quote_withheld` only on a source that does not ship its text under `text/` and whose `Publication.license` is
  not an open or public-domain licence (**error** if the text ships: then quote it).
- An edge whose evidence is all withheld is a valid substantive edge; count such edges in `validation.json`
  (`stats.withheld_quote_edges`) and report one **info** finding per bundle, not a warning per edge.
- The source-node form only: a withheld quote cites a `Publication` (an inline-form bundle has no other provenance
  than its quotes, so it may not withhold them).

**Platform.**

- Importer: store `quote_withheld` as it comes; never synthesize text for it.
- Inspector: show such evidence as *"Quote withheld (copyright) · p. 1 · 198 characters · <Publication title>"*, with
  the digest under a details toggle. Optional: a **Check against my copy** action: the reader pastes the passage,
  the client normalizes it as above and compares the digest (match or no match; nothing is sent).
- `kg_query` and agent tools: return `quote_withheld` evidence as such (`"quote": null, "quote_withheld": {…}`), and
  tell agents in the tool description never to reconstruct or paraphrase a withheld quote; cite source and page.
- Search over quotes simply has no text for these items.

**Acceptance.** A bundle whose edges carry only `quote_withheld` evidence validates with 0 errors, imports, and
shows the edges with their source and page; a bundle mixing `quote` and `quote_withheld` on one object fails; a
withheld quote on a source shipped under `text/` fails; bundles of format 1.0.0 still validate unchanged.

**SCALE side, once it lands.** The exporter writes `quote_withheld` instead of dropping the edge (under
`format_version: 1.1.0`), and the methanol bundle is released as 1.1.0 with every link.

## 2. Resolve `extends` against published schemas

**Why.** Every SCALE bundle's `kg/schema.json` declares the types it uses and names the schema they come from:

```json
"extends": {"schema_id": "scale-graph", "version": "0.1.0",
            "sha256": "3c2fa7205a7bae5e0bbfa7d87826ff7ab7803e78536129064101c7d5a2c02006"}
```

A version number names a schema only within one numbering (SCALE's numbering restarted once); the digest names
it everywhere. Today `extends` is informational (format §1.1), so GALAXY cannot join two SCALE bundles by schema or
show which schema a graph follows.

**Change.**

- A schema registry keyed by `(schema_id, sha256)`, with the version as a label. Seed it with SCALE's spec
  documents: each SCALE release publishes the spec document of every schema version with its digest
  (`scale graph spec --version <v>` writes it; its sha256 is the digest), starting with scale-graph 0.1.0 above.
- Validator: `extends` may carry `sha256` (accepted today, keep it); **warning** when the `(schema_id, sha256)`
  pair is unknown; **error** when the registry holds the same `schema_id` and `version` with a different digest
  (another schema of the same number).
- Graph details: *Schema* shows the bundle schema and, under it, *Extends: scale-graph 0.1.0 (3c2fa720…)*; graphs
  extending the same digest can be joined on their shared types.

**Acceptance.** The methanol bundle shows *Extends: scale-graph 0.1.0 (3c2fa720…)*; a bundle naming scale-graph
0.1.0 with another digest is refused with a message that names both digests.

## 3. Typed absences

**Why.** SCALE never fills a gap with a guess: a value the source does not give is recorded as such
(`not_reported` with a reason, `not_measured`, `not_applicable`, `below_detection_limit` with the limit). These are
answers in their own right ("the source does not report the pressure"), and the exporter drops them today.

**Change.** A reserved property `_value_status` on any node or edge: a map from a declared property to its
status.

```json
"_value_status": {"pressure": {"status": "not_reported", "missing_reason": "not_stated_in_source"},
                  "conversion": {"status": "below_detection_limit", "limit": {"value": 0.1, "unit": "%"}}}
```

- `status`: `not_reported`, `not_measured`, `not_applicable`, `below_detection_limit`,
  `below_quantification_limit`; `missing_reason` (only with `not_reported`): `not_stated_in_source`,
  `not_curated`, `ambiguous_in_source`, `withheld`, `not_extractable`; `limit` a quantity (only with the two
  limit statuses).
- Validator: the key is a property declared for that type; the property itself is absent on the record
  (**error** if both are present); enums as above (**error**).
- Inspector: list them under the record's properties as *"pressure: not reported (not stated in source)"*.

**Acceptance.** The methanol bundle's 229 absences import and show; a `_value_status` on an undeclared property
fails.

## What does not need to change

Ranges (format §3.2, `uncertainty.kind: range`), as-reported text, units, Publications and `REPORTED_IN`, the
statement kinds and versioning all fit as they are; SCALE's extra manifest block `scale_header` and its declared
`scale_*` properties validate today.
