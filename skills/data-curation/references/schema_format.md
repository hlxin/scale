# The schema (given by the user, never generated)

## Contents
- Rule: the schema is the user's
- schema.json format
- Properties: hint strings or objects
- Optional sections (scope, record_view, never_merge, faithfulness_rules)
- Converting a user's document into schema.json
- Changing the schema mid-run

## Rule: the schema is the user's

Extraction follows exactly the node types, properties and edge types the user gives. You never add a type, a
property or an allowed value, never "improve" the schema, and never induce one from papers. When the pilot shows the
schema cannot hold what the papers report (a recurring concept with no type, enum values that never match), you tell
the user what is missing with examples and they decide. Unknown enum terms are flagged in fragments as
`_pending_vocab_addition` so the evidence for a schema change is collected, not invented.

## schema.json format

```json
{
  "name": "co2rr-catalysts",
  "version": "1.0",
  "topic": "Electrochemical CO2 reduction catalysts and their measured performance",
  "scope": "Primary studies reporting CO2RR performance values; reviews contribute no values.",
  "node_types": {
    "Catalyst": {"description": "...", "properties": {"name": "string (required)", "loading_mg_cm2": "number (0-100)"}},
    "PerformanceMetric": {"description": "...", "properties": {
        "metric": {"type": "string", "required": true, "enum": ["faradaic_efficiency", "partial_current_density"]},
        "value": "number (required)", "unit": "string (required)"}}
  },
  "edge_types": {
    "ACHIEVES": {"from": "Catalyst", "to": "PerformanceMetric", "description": "The catalyst attains this value."}
  }
}
```

- `name` — the graph's folder name (`publications/<topic>/kg/<name>/`); `version` — recorded in the index's Extracted
  column. Both optional (file name / "1").
- Node types: PascalCase (`Catalyst`, `ActiveSite`). Edge types: UPPER_SNAKE_CASE, `from`/`to` = a node type or a list
  of node types. Never declare the builtins (`Publication`, `Figure`, `REPORTED_IN`, `DEPICTS`, `MENTIONS`, `CITES`).
- Property names: snake_case; a unit suffix keeps its case (`binding_energy_eV`); `pH` is fine.
- Full example: `examples/schema.catalysis.example.json`. Check any schema with `check_schema.py <file>`.

## Properties: hint strings or objects

| Form | Meaning |
|---|---|
| `"string"`, `"number"`, `"integer"`, `"boolean"`, `"array"`, `"object"` | type only |
| `"string (required)"` | must be present (a node without it is left out) |
| `"number (0-100)"` | numeric bounds |
| `"string (one of: H-cell, flow cell, MEA)"` | allowed values |
| `{"type": "number", "required": true, "min": 0, "max": 100, "unit": "%", "enum": [...], "description": "..."}` | object form, same meaning |

Every numeric or controlled value an extractor fills carries `_evidence` + `_citation`; you never declare those.

## Optional sections

- `scope` — which papers belong in the graph. The reviewer rejects papers outside it (they get `Rejected` in the
  index's Extracted column), so out-of-scope papers that slipped through screening cost one review, not a corrupt graph.
- `record_view` — `{"label": "PerformanceMetric", "join": [{"edge": "ACHIEVES", "direction": "in", "prefix":
  "catalyst_"}, ...]}`: `tables/records.csv` gets one row per record node with its neighbours' properties (the flat
  dataset many analyses want).
- `never_merge` — sentences the alias pass must respect ("Cu(100) and Cu(111) facets are distinct").
- `faithfulness_rules` — extra domain rules for extractors and reviewers (additive; they cannot relax the defaults in
  [faithfulness.md](faithfulness.md)).

## Converting a user's document into schema.json

Users often give a table, a list of fields, a spreadsheet header or an older protocol. Convert it faithfully:
1. Every entity the user lists → a node type; every field → a property of that type, with the type and units they
   state; every relation they state → an edge type. A flat field list (one row per measurement) becomes one record
   node type plus the entities its fields describe only when the user's own document groups them that way; otherwise
   keep one node type with all fields and say so.
2. Add nothing. Where the document is ambiguous (unit missing, allowed values unclear), ask — do not guess.
3. Write it to `.scripts/<topic>/kg/schema_draft.json`, run `check_schema.py` on it, show the readable summary to the
   user and get an explicit approval before `prepare_run.py` freezes it. Keep the user's original document beside it.

## Changing the schema mid-run

A changed schema makes earlier fragments inconsistent. Options: a new `--name` (a second graph, nothing lost), or
`prepare_run.py --replace-schema` (the old schema is kept as `schema.replaced.<hash>.json`) followed by
`next_batch.py --role extract --all` (old fragments move to `fragments/superseded/`).
