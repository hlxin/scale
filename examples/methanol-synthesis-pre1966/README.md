# Example — methanol synthesis from CO/CO2 + H2, literature published before 1966

The knowledge graph of the historical methanol-synthesis literature, scoped to **CO and CO2 hydrogenation** (CO + D2
included): 105 sources from 1923 to 1965. It is public research data (`data_status: research_data`, `access:
public`), maintained by SCALE's researchers, and the repository's checks
and tests run on it (`tools/tests/test_example_methanol.py`).

| file | content |
|---|---|
| `sources.json` | The frozen corpus: all 178 candidate sources with their status under the cutoff and the scope (105 `in_scope`, 10 held-out targets, 58 not retrieved, 4 off scope, 1 after the cutoff), and for each in-scope source its PDF and the PDF's sha256. `scale corpus check sources.json` checks it. |
| `pdfs/<slug>.pdf` | The 105 PDFs, **local only** (git-ignored; most are in copyright). |
| `methanol-synthesis.graph.json` | The curated graph, valid under scale-graph 0.1.0: 4,866 nodes, 16,584 links, 684 catalytic tests, 25,230 evidence items. The baseline until the recuration replaces it. |
| `rights.yaml`, `stewardship.yaml` | Each source's rights (the copyright cap), and who curated the graph for which project. |
| `queries/*.yaml` | The manuscript's questions as query plans. |
| `methanol-synthesis-pre1966_v2.0.0.zip` | The graph as a knowledge-graph bundle ([kg-bundle format](../../docs/kg-bundle-format.md) 1.1.0), ready to load into a platform that reads the format, titled "Methanol Synthesis CO/CO2+H2 Pre-1966", its schema scale-catal 0.1.0 (the catalysis vocabulary of scale-graph 0.1.0): 17,563 edges, withheld quotes as digests, 227 typed absences; it follows release 1.1.1. |

A slug is the source's DOI with `/` written as `-` (`10.1021/ie50225a025` → `10.1021-ie50225a025.pdf`); a patent
without a DOI uses its number (`us1625925a`), a thesis or report its corpus id (`hid-20028`). Source records in the
graph are `ex:msyn/source/<slug>`.

## Getting the PDFs

Copy them from a local copy of the corpus (a folder holding each source at its `corpus_pdf` path), checking each
digest:

```bash
CORPUS=/path/to/corpus
cd examples/methanol-synthesis-pre1966 && mkdir -p pdfs
python3 -c "
import json, hashlib, shutil, sys
for s in json.load(open('sources.json'))['sources']:
    if s['status'] == 'in_scope':
        shutil.copyfile(sys.argv[1] + '/' + s['corpus_pdf'], s['pdf'])
        assert hashlib.sha256(open(s['pdf'], 'rb').read()).hexdigest() == s['text']['pdf_sha256'], s['slug']
" "$CORPUS"
```

## The cutoff

A source is in scope when it was published or publicly disclosed **before 1 January 1966** (a patent by the grant
date printed on it, not its priority date). ICI launched low-pressure methanol synthesis over Cu/ZnO/Al2O3 in 1966;
the cutoff holds out that commercialization and what followed (10 held-out targets) and admits everything before it,
ICI's own 1960 patent included. Every record carries its source year, so a plan with `published_before:
1959-01-01` answers for an earlier cutoff. The cutoff does not remove every Cu–Zn–Al composition: `q6` finds five
catalysts in sources of 1928–1965 (Larson's US 2,061,470 among them); a rediscovery evaluation must hold them out
itself (`sources.json`, `cutoff.caution`).

## Queries

```bash
G=examples/methanol-synthesis-pre1966/methanol-synthesis.graph.json
scale graph query $G examples/methanol-synthesis-pre1966/queries/q1-copper-lower-temperature.yaml --format markdown
scale graph search $G "sulphur poisons the copper catalyst" --published-before 1966 --format markdown
```

Text plans and search build the evidence index in memory; `scale graph index $G` saves it (git-ignored) for repeated
searches. Current answers: q1 236 rows, q2 69, q2b 88, q3 47, q4 135, q5 62, q6 5.

## Recurating

Follow the `curate-source` skill (`skills/curate-source/SKILL.md`) one source at a time, from the PDFs:

1. **Page texts** (local; `work/` is git-ignored): `scale.sourcetext.extract_pages(pdf)` gives each page's text from
   the PDF's text layer, or Tesseract OCR where it has none, and `joined(extract_pages(pdf)["pages"])` the text to check quotes against
   (needs `pip install pymupdf` and, for OCR, `tesseract`). For scanned pages whose values OCR loses:
   `scale pages render pdfs/<slug>.pdf --source ex:msyn/source/<slug> --pages work/pages`.
2. **Curate** into a scale-graph document (`scale call template '{"domain": "catalysis"}'`, `scale graph describe
   <Label> --domain catalysis`), every value as printed, every record with its evidence, every unknown with its
   `missing_reason`.
3. **Check:** `scale graph validate <doc> --source-text ex:msyn/source/<slug>=<page text>` (0 errors), then
   `scale evidence report <doc>` against `rights.yaml` (`scale evidence cap` withholds quotes beyond the cap).
4. **Replace** `methanol-synthesis.graph.json` once the recurated graph validates, and compare the query answers
   above.

## Provenance

- **Schema.** Curated under the consortium repository's scale-graph 0.1.0 (a different schema from this
  repository's 0.1.0; the numbering restarted), moved to that repository's 0.5.0 and re-pinned to this repository's
  0.1.0 (decision record 0001). The graph's title and description name the consortium's version and its tools.
- **Release v1.0.0** (2026-10-09; graph sha256 `0dfc8c1c…ed13f`, schema spec `3c2fa720…02006`), its kg-bundle,
  the curation guide, the assembly report (720 gaps, 47 `missing_concept`) and the curation tools are in the git
  history (commit `a169872`, folder `examples/methanol-synthesis-pre1966/`). A kg-bundle is regenerated with
  `scale graph export <graph> --to kg-bundle --corpus sources.json`.
- **Recuration from the PDFs.** 2026-10-09: the 9 runs of `10.1021-ie50302a005` whose pressure was not recorded
  now carry the testing pressure its Experimental Procedure states (178 atmospheres absolute); the other checklist
  gaps were checked against the sources and are theirs (112 violations: values the sources do not state, and a
  blank run and a saturator calibration that use no catalyst, which the checklist cannot exempt yet).
- **Quoted text.** The 55 public-domain sources (US patents, works published before 1931) keep every quote; the 50
  in-copyright sources are capped (300 characters a quote; 4,000 characters and 10 % of the text a source), and
  6,920 evidence items carry withheld text as sha256 and length (`scale evidence rehydrate` restores them from the
  source texts).
