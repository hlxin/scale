# Topic A/B/C and Related topics

## Contents
- What the columns mean
- The vocabulary
- How topics are assigned (Claude / API / deterministic)
- Extending the vocabulary
- Correcting topics by hand

## What the columns mean

- **Topic A, B, C** — the paper's three main topics, most central first. Usually: what is catalyzed (CO2RR, OER,
  NO3RR ...), the catalyst class (Copper catalysts, Single-atom catalysts, MOFs ...) and how it is studied (DFT,
  Operando characterization, Machine learning ...). A paper may have fewer than three.
- **Related topics** — up to six more: other vocabulary topics the paper clearly touches, then the vocabulary
  neighbours of A/B/C (CO2RR ~ CORR, OER ~ ORR, HER ~ HOR, NRR ~ NO3RR ~ NORR, CO2RR ~ C-N coupling ...). They make
  filtering forgiving: a search for CORR also finds the CO2RR papers that discuss CO.

Topics belong to the paper, not to the index topic: a paper in two indexes has one set of topics.

## The vocabulary

The vocabulary belongs to the domain, not to this skill. The first of these is used: a path given to the script,
`$INDEX_SOURCES_VOCAB`, the project's `.scripts/vocab.json`, or, when the skill runs from a checkout of hlxin/scale,
SCALE's catalysis vocabulary, `graphs/catal-commons/literature/vocabulary.json` (copy it to `.scripts/vocab.json` in a
project that installed the skill elsewhere).

The catalysis vocabulary (125 terms in 4 facets: reaction 72, material 26, method 17, system 10) — electro-, photo-,
thermo-, bio- and plasma catalysis, catalytic organic synthesis, esterification/biodiesel, coal conversion; catalyst
classes incl. enzymes, nanozymes, solid acids and ionic liquids; characterization, crystallography, kinetics,
computation, techno-economics; devices and reactors. (On the all-of-catalysis index this left 22% of papers without a
Topic A, down from 44% with the earlier 116-term version: mostly biomedical papers that only mention catalysis.) Each term: `id`, `label` (what the CSV shows), `name`, `facet`, `synonyms`, `related`, `weight` (< 1 for
broad terms such as Metal oxides, Catalyst synthesis, Hydrogen production, so they rank below specific ones).
`topics.py vocab` lists it; papers.db holds it in `subjects`.

## How topics are assigned

- **Claude / API screening** — the screening prompt lists the vocabulary labels; for every paper the model returns
  `topics` (up to 3, most central first) and optional `related`. Labels outside the vocabulary are kept as proposed
  terms (`topics.py proposed`). Related topics are completed with the vocabulary neighbours.
- **Deterministic** (keywords / none screening, and right after `build_list.py` for every new paper) — synonyms are
  matched on the words of the title (x3), keywords (x2) and abstract (x1); a longer synonym consumes its words
  ("electrochemical ammonia synthesis" counts for NRR, not for thermal ammonia synthesis). Acronyms and formulas
  match case-sensitively (HER is not "her"; CdS is not "CDs"), plurals are allowed. Score >= 1 needed; reaction terms
  win near-ties. About 0.7 ms per paper, so 60,000 papers take under a minute.
- A better method is never overwritten by a lesser one: manual > Claude > API > vocabulary. When abstracts arrive
  later (classify_access.py, fill_abstracts.py, a curation result), vocabulary topics are recomputed.

## Extending the vocabulary

For a topic outside catalysis, write the domain's own vocabulary (same shape) to `.scripts/vocab.json`. When
`topics.py proposed` shows a recurring label, add terms to `.scripts/vocab_custom.json` (project-specific; overrides
the vocabulary's terms with the same `id`), show the user the
additions, then `topics.py assign --topic <slug>`:

```json
{"terms": [
  {"id": "pec-tandem", "label": "PEC tandem cells", "name": "Photoelectrochemical tandem devices", "facet": "system",
   "synonyms": ["tandem photoelectrochemical", "PEC tandem", "unassisted solar water splitting"],
   "related": ["pec", "photo-h2"], "weight": 1.0}
]}
```

Synonym rules: phrases are case-insensitive (spaces and hyphens interchangeable); tokens with an inner capital or a
digit (CO2, MOF, Ti3C2) and short capitalized tokens (Cu, Co) are case-sensitive; `re:` starts a regular
expression. Avoid words that are common outside the topic ("benchmark", "in situ", "stack").

## Correcting topics by hand

`topics.py set --ids 12,57 --main "CO2RR,Copper catalysts,Operando characterization" [--related CORR]` — stored as
method `manual`, never overwritten by later runs. With `--add`, the terms go in front of each paper's own Topic A/B/C
(three in all; the ones pushed out become related topics): `topics.py set --ids <a list's papers> --main
"Methanol synthesis" --add` marks what an imported list is about without losing what each paper was given.
