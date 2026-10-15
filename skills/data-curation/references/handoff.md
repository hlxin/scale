# Hand-off with paper-acquisition

## What data-curation reads
- `publications/papers.db` (preferred) or `publications/<topic>/index/merged.csv`: the topic's papers, their scope
  decision and relevance, document type, access type, license, Topic A/B/C, abstract (present or not) and the PDF/SI
  paths (`publications/<topic>/papers/<access>/<ID>.pdf`, `papers/SI/<access>/`). Paper IDs are shared.
- Only downloaded papers can be extracted. Papers without a PDF are listed by `prepare_run.py`; offer
  paper-acquisition's Download mode (or research-curation-pipeline) for them.

## What data-curation writes back
`.scripts/<topic>/kg/<name>/extraction_status.jsonl`, one line per settled paper (`review_status.py --apply`):

```json
{"paper_id": 41, "topic": "mxene-no3", "kg": "mxene-no3rr", "status": "extracted", "schema_version": "0.1",
 "nodes": 14, "edges": 21, "date": "2026-10-12", "note": "approved: ...", "abstract": "<only when the index had none>"}
```

`status`: `extracted` · `no_data` (nothing for the schema) · `rejected` (outside the schema's scope / unusable) ·
`failed` (invalid twice or still wrong after one corrective pass). paper-acquisition's next export (any step, or
`export.py --topic <topic>`) syncs these lines into its ledger: the index's **Extracted** column shows
`Yes — <name> (<date>)` / `Rejected — ...`, `papers.db` gets an `extractions` row, and an abstract the extractor
copied from the PDF fills a paper that had none (`abstract_source = "pdf (data-curation)"`), after which the paper's
vocabulary topics are recomputed.

## Order of operations
paper-acquisition Index → Download (open + paywalled as chosen) → data-curation (this skill) → `export.py` refresh.
research-curation-pipeline runs the whole chain.
