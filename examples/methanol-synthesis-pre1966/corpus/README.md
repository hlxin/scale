# Corpus — methanol synthesis from CO/CO2 + H2, before 1966

The benchmark corpus of this example: the publications and patents on methanol synthesis from carbon monoxide
and/or carbon dioxide with hydrogen (CO + D2 included), published or publicly disclosed before 1 January 1966.

| file | content |
|---|---|
| `sources.json` | The 105 sources: slug, kind, publication date, title, the PDF and its sha256, and the path the PDF has in the project corpus. Also the 3 in-scope sources left out, and why the list is what it is. |
| `manifest.json` | The frozen corpus the curation started from: every source, its date and date basis, its status under the cutoff (in scope, held-out target, after the cutoff, not retrieved, off scope). |
| `pdfs/<slug>.pdf` | The PDFs, **local only** (git-ignored: 105 files, about 300 MB, most of them in copyright). |

**Scope.** `sources.json` keeps the in-scope sources of `manifest.json` that the CO and CO2 hydrogenation scope
keeps (`tools/curation.py scope`): a source stays when a test of CO or CO2 hydrogenation, or a claim, rests on it.
105 of the 108 in-scope sources: 54 articles, 39 patents, 12 theses and reports. Left out: methanol decomposition
over aluminium and zinc oxides (1928) and two 1951 papers on poisoning a zinc catalyst whose tests are not
hydrogenation tests.

**Getting the PDFs.** Copy them from the project corpus (`<corpus>/<corpus_pdf>` for each source in
`sources.json`) to `pdfs/<slug>.pdf`; each one's sha256 must equal `pdf_sha256` (the digest the curation was
checked against).
