# Example — methanol synthesis, public-domain sources

The public-domain part of the methanol-synthesis graph (the full curation, 105 sources, most in copyright, is kept
outside this repository):
55 sources on CO and CO2 hydrogenation to methanol, **with their PDFs and page texts** and every quote in full. Anyone can
reproduce the curation from this folder alone, and every quote is checked against its source's text
(`tools/tests/test_example_methanol_public.py`).

| sources | count | why public domain (in the United States) |
|---|---:|---|
| articles, 1923–1930 | 16 | first published before 1931; two also say "Not subject to copyright" (US Bureau of Mines) |
| US patents, 1925–1960 | 38 | US patent texts are not under copyright |
| Polish patent, 1928 | 1 | an official document, excluded from copyright (and published before 1931) |

Outside the United States some articles may still be in copyright (the author's life plus 70 years); each source's
basis is in `rights.yaml`.

## The graph is kept as parts

| file | content |
|---|---|
| `parts/header.json` | the graph's own object: title, description, schema version, stewardship |
| `parts/sources/<slug>.json` | one source: its Source record, every record it alone states, and their links |
| `parts/shared.json` | the records several sources refer to: species, reactions, people, institutions |
| `pdfs/<slug>.pdf` | the source (its sha256 is `text.pdf_sha256` in `sources.json`) |
| `texts/<slug>.json` | its page texts, the ones it was curated from: the PDF's text layer, or Tesseract OCR with the settings in `ocr_engine` |
| `sources.json`, `rights.yaml`, `stewardship.yaml` | the corpus, each source's rights, the default stewardship |
| `queries/*.yaml` | the manuscript's questions as query plans; on these 55 sources: q1 117 rows, q2 71, q2b 60, q3 70, q4 55, q5 102, q6 3 |

Tools read the folder as one graph: they build it from its parts
([docs/graph-parts.md](../../docs/graph-parts.md)). `scale graph build examples/methanol-synthesis-public` writes the
built copy (`methanol-synthesis-public.graph.json`, git-ignored).

```bash
G=examples/methanol-synthesis-public
scale graph validate $G                                    # 2,851 nodes, 9,335 links, 0 errors
scale graph query $G $G/queries/q1-copper-lower-temperature.yaml --format markdown
scale graph search $G "sulphur poisons the copper catalyst" --format markdown
```

A source's records are those of the full graph, unchanged; shared records keep only the evidence of these 55
sources. `scale graph split <the full graph> --out . --sources @LIST` makes the parts again, and a test checks that
this folder is exactly that where a restricted copy holds the full graph ([docs/commands.md](../../docs/commands.md)).

## Checking a quote against its source

```python
import json
from scale.sourcetext import joined
from scale.util import match_text
text = match_text(joined(json.load(open("texts/us1625925a.json"))["pages"]))
match_text("a quote from the graph") in text
```

`scale graph validate $G --source-text ex:msyn/source/<slug>=<file>` does the same for one source from a plain text
file.
