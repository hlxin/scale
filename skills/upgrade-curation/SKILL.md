---
name: upgrade-curation
version: 0.1.0
description: Upgrade a curated graph to a newer schema version when its maintainers decide it is worth it - never on every schema change. First a report (scale graph upgrade) of what each schema step between the two versions means for this graph, step by step, with what needs attention, what is optional and what is nothing to do; then, on approval, the mechanical upgrade (ids kept); then, only if asked, a targeted re-reading of the passages the worklist names, filling what the newer version asks (a context comparisons now need, a checklist item, a new property the maintainers chose) instead of curating the papers again. Use when asked to upgrade, migrate or bring a curated graph up to a newer schema, to see what a schema change means for existing curations, or to re-read old curations for what a new schema version can express.
scale_release: ">v0.3.0"
inputs:
  - A curated graph (a graph file, or a folder of parts such as graphs/methanol-synthesis-pre1966)
  - The version to upgrade to (default the current schema)
  - Which part of the worklist to re-read, if any - all of it, some sources, some kinds of gap, or none; and any new properties to enrich for
  - The sources' page texts (the curation folders' work/texts, or the example's texts/) for the passages to re-read
allowed-tools:
  - Bash(scale graph upgrade:*)
  - Bash(scale graph validate:*)
  - Bash(scale graph describe:*)
  - Bash(scale graph query:*)
  - Bash(scale review values:*)
  - Bash(scale evidence:*)
  - Bash(scale pages:*)
  # not pre-approved, so a person sees each call: `scale graph upgrade --write`, git commits, pushes, pull requests
outputs:
  - upgrade-<graph>-<from>-to-<to>.md - the report a person decides from
  - upgrade-<graph>-<from>-to-<to>.json - the same, with the re-reading worklist (each record, its sources, locators and what it lacks)
  - After approval, the upgraded graph; after a re-reading, the records patched and a short account of what was filled and what the sources do not say
validation:
  - "`scale graph upgrade` reports 0 validation errors after the upgrade before anything is written"
  - "`scale graph validate <graph> --source-text …` reports 0 errors after a re-reading; every quote added is verbatim"
  - "`scale review values <graph>` flags nothing the re-reading added"
  - Every record id is unchanged; no value outside the worklist's fields changed
human-review:
  - Always before --write - the person reads the report and chooses stay, upgrade, or upgrade and re-read
  - Always before re-reading - which sources and which gaps (the report's tables), since it costs model time
  - Always before the patched graph is committed or contributed - as for any curation (review-values.md)
---

# Upgrade a curation to a newer schema, on demand

A graph pins the schema version it was curated under and stays valid under it: every version is kept frozen, so a
schema change never forces anything. This skill runs when the maintainers decide a newer version is worth it, and
it re-reads only what the newer version asks, never whole papers.

## 1. Report

```bash
scale graph upgrade <graph> --to <version> --report-dir <dir>
```

Read `upgrade-…md` and tell the person, in a few lines:

- how many steps **need attention**, are **optional**, **checked automatically** or **nothing to do**, and for the
  steps that need attention, what they change (rewrites, checklist items, comparisons by a new context);
- the validation result after the mechanical upgrade (it must be 0 errors; if a step **stops**, say where and why:
  a person decides how those records are written, which may be a change to the migration rule, not to the graph);
- the size of the re-reading worklist (records, sources, passages), its top sources, and which gaps it holds
  (e.g. "393 pressures do not say gauge or absolute");
- the new optional properties, in case some are worth enriching for (`--enrich Label.property`).

Then ask which option: **stay**, **upgrade mechanically**, or **upgrade and re-read** (all, the top N sources, or only
some kinds of gap). Stop until they answer.

## 2. Upgrade mechanically (on approval)

```bash
scale graph upgrade <graph> --to <version> --write
```

A folder of parts is rewritten in place, so this belongs on a branch. Check `scale graph validate <graph>`.

## 3. Re-read the worklist (only if asked)

Read the JSON report's `worklist.items` for the sources the person chose. For each source, open its page texts and,
for each item, read **only the cited locators** (and the sentences around them):

- `asks` naming a context (`state its pressure_convention`, `species`, `flow_reference`, `fraction_basis`, …): write
  it where the schema reads it from (`scale graph describe <Label>`: the property's contract; for most contexts the
  value's `basis` or `definition` text, or its `unit`), using the source's words. If the passage does not say, record
  that in the value's `note` ("the source does not state gauge or absolute") and leave the context unstated: a
  query then keeps it apart, now for a stated reason. Never infer it from what was usual at the time.
- `asks` naming a checklist item: fill it from the passage with a verbatim quote, or declare it `not_reported` with
  `missing_reason: not_stated_in_source`.
- `could_add` (a property the person chose to enrich for): fill it only where the passage states it.

Follow the curate-corpus rules for every value: as printed, with `as_reported`, the unit the source printed, a
verbatim quote and locator for anything new. Change nothing outside the item's fields; keep every id.

## 4. Check and hand over

```bash
scale graph validate <graph> --source-text <id>=<texts>     # 0 errors
scale review values <graph> --out review-values.md          # nothing flagged that the re-reading added
scale graph upgrade <graph-before> --to <version> --report-dir <dir>   # optional: the worklist again, to show what is left
```

Report what was filled, by kind of gap, and what the sources do not say. The person reviews it as a curation
(review-values.md and the changed records) before it is committed or contributed.

## What must never happen

- `--write`, a re-reading, a commit or a pull request without the person's own go-ahead.
- Re-curating a whole paper, or changing a value the worklist did not name.
- Filling a context or a checklist item from convention or memory rather than the passage.
- Upgrading a graph because a new schema version exists: staying at the pinned version is always valid.
