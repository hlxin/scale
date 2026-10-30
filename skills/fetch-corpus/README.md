# fetch-corpus — README

A Claude Code skill that fetches the files of a corpus: each included source's PDF and supplementary information
(SI). The corpus comes from [index-sources](../index-sources/README.md), which indexes a topic and freezes a corpus by
a rule (`freeze_corpus.py` → `sources/<topic>/corpora/<name>/sources.json`); curate-corpus then curates what was
fetched. Ask Claude in plain words ("fetch the open-access sources of the co2rr-ethylene corpus", "get the PDFs of
this corpus, paywalled ones too", "resume the fetch").

## What it does

1. **Asks first**: the corpus's sources by access type, what is already on disk, and how long the rest takes; you
   choose the access types (OA, OA+ND, Free-to-read, Paywalled).
2. **Open routes**: every known open copy, most open first (repositories, PubMed Central, arXiv, publisher CDNs, and
   Elsevier's article API for its open articles once a developer key is in keys.txt); each
   PDF is checked against the source's title (or its own DOI printed in it) and filed by the licence printed in it. A
   PDF the check rejects is kept for review, and filed once someone has confirmed it (`accept_pdf.py`). PDFs another
   project already downloaded can be copied in first, with no network (`import_pdfs.py`).
3. **Paywalled sources**: only through your library's EZproxy from the campus network or VPN, by one rate-limited
   process per computer (≤ 120 sources per publisher per day, ≤ 600 per day overall, long pauses, automatic stops on
   any block or login page; a network or proxy outage costs no source a try and pauses the visits). It never logs
   in, never types credentials, never solves CAPTCHAs.
   Details: `references/paywalled.md`.
4. **SI**: the files index-sources listed first, then the source's own page.
5. **Settles the corpus**: the manifest records, for each included source, its files — or `not_retrieved` and why
   (queued for EZproxy, no copy found, access type not fetched). Settle again after a later fetch.

## Where the files go

```
sources/<topic>/files/<access>/<ID>.pdf        the fetched PDFs (access: OA, OA+ND, Free-to-read, Paywalled)
sources/<topic>/files/SI/<access>/<ID>_SI…     their SI
sources/<topic>/corpora/<name>/sources.json    the corpus, settled: each source's pdf and si paths, or why not
```

The machine-wide EZproxy settings and limiter state are in `~/.scale/sources/ezproxy/`.

## Requirements

Python 3.10+ with `requests`, `pymupdf` and `pypdf`, and the index-sources skill beside this one: it works in the
same project and uses index-sources' scripts as its library. Optional: poppler's `pdftotext`, a second reader for PDFs
whose fonts PyMuPDF decodes badly.
