# Methanol synthesis from CO/CO2 + H2, literature published before 1966

The knowledge graph of the historical methanol-synthesis literature, scoped to **CO and CO2 hydrogenation** (CO + D2
included): 105 sources from 1923 to 1965, 4,866 nodes and 16,584 links, kept as one part per source. It is public
research data (`access: public`) maintained by SCALE's researchers, valid under scale-catal 0.8.2 (curated under
0.2.0 and upgraded mechanically: see *Schema version* below).

**Each source is quoted only as far as its rights allow** (`rights.yaml`): the 55 public-domain sources (US patents,
works published before 1931) keep every quote; the 50 sources in copyright keep none. Their quotes are withheld
(`limits: {quote_chars: 0, source_chars: 0}`): each evidence item keeps its source and locator, and its note keeps
the quote's sha256 and length, so anyone holding the source restores it (`scale evidence rehydrate`). No PDF is
committed; the public-domain sources' PDFs and page texts are in
[`examples/methanol-synthesis-public/`](../../examples/methanol-synthesis-public/README.md), which is exactly this
graph's public-domain part (a test checks it).

| file | content |
|---|---|
| `parts/` | the graph: `header.json`, `shared.json` (261 shared records) and `sources/<slug>.json` (105 sources) |
| `sources.json` | the frozen corpus: all 178 candidate sources with their status under the cutoff and the scope (105 `in_scope`, 10 held-out targets, 58 not retrieved, 4 off scope, 1 after the cutoff), and for each in-scope source its PDF's sha256. `scale corpus check sources.json` checks it. |
| `rights.yaml`, `stewardship.yaml` | each source's rights, and who curated the graph for which project |

A slug is the source's DOI with `/` written as `-` (`10.1021/ie50225a025` → `10.1021-ie50225a025`); a patent without
a DOI uses its number (`us1625925a`), a thesis or report its corpus id (`hid-20028`). Source records are
`ex:msyn/source/<slug>`.

```bash
G=graphs/methanol-synthesis-pre1966
scale graph validate $G                                     # 0 errors
scale graph query $G examples/methanol-synthesis-public/queries/q1-copper-lower-temperature.yaml --format markdown
```

## The cutoff

A source is in scope when it was published or publicly disclosed **before 1 January 1966** (a patent by the grant
date printed on it, not its priority date). ICI launched low-pressure methanol synthesis over Cu/ZnO/Al2O3 in 1966;
the cutoff holds out that commercialization and what followed (10 held-out targets) and admits everything before it,
ICI's own 1960 patent included. Every record carries its source year, so a plan with `published_before:
1959-01-01` answers for an earlier cutoff. The cutoff does not remove every Cu–Zn–Al composition (Larson's US
2,061,470 of 1936 among them); a rediscovery evaluation must hold them out itself (`sources.json`, `cutoff.caution`).

## Provenance

Curated by agents under the `curate-source` skill from the page texts of the PDFs (text layer, or Tesseract OCR),
every quote checked verbatim against them; schema history in the CHANGELOG. It was kept in
`examples/methanol-synthesis-pre1966/` until v0.2.0 with quotes capped at 300 characters (4,000 a source), left the
repository in #28, and is back here with no quoted text of a source in copyright. Its earlier bundles
(`methanol-synthesis-pre1966_v1.0.0` to `v3.0.0`) are in the git history.

## Schema version

Curated under scale-catal 0.2.0; upgraded to 0.8.2 with `scale graph upgrade`, together with its public part
([`examples/methanol-synthesis-public/`](../../examples/methanol-synthesis-public/README.md)). The upgrade is
mechanical: every record id is kept, the 0.2.1 → 0.3.0 migration rule moved 47 `HAS_COMPONENT.fraction` values given
in a mass or amount unit to `amount` (39 of them in the public part), every other step only raised the version, and the graph validates with 0 errors.
Every query plan of the example answers as before.

### Re-reading for 0.8.2 (2026-11-20)

The 55 public-domain sources, whose page texts are in the example, were re-read where 0.8.2 asks for more than the
0.2.0 curation recorded. Only the cited passages and the sentences that could settle each gap were read, and nothing
was filled from convention:

- **Citations.** 268 values whose records did not cite the sentence that states them now cite it (152 records; for
  example a paper's "a pressure of 150 atmospheres was consistently employed"). Two `as_reported` texts that held a
  table's row label now hold the printed value; two reduction times read on the page image (3½ h, 1¾ h) were
  confirmed.
- **Filled from the source (216 values).** The species of 173 conversions and yields (carbon monoxide converted,
  methanol formed; for two papers from their own definition of the measure, cited); the flow reference of 21 flows
  and space velocities ("standard conditions (0° C. and 760 mm.)", "N.T.P."); the basis of 11 space velocities
  ("cubic feet of gas per cubic foot of catalyst per hour") and of 11 compositions whose own sentence says by weight,
  by volume or atomic.
- **Recorded as not stated (1,081 values).** No pressure in these sources says gauge or absolute (393); most gas
  flows and space velocities do not say what conditions their volumes are counted at (249) or define the space
  velocity (204); most compositions do not say their basis in the sentence that prints them (234; for 143 of them
  the note names the one basis the source states elsewhere, e.g. "parts by weight" in a patent's first example, for
  a reviewer to decide on). Each value's `note` says so, so a query that keeps it apart can say why. One product
  stays unidentified as the source names it ("alkohol"). Three flows "measured under ordinary conditions" have no
  flow reference in the schema to say it with: a schema gap.

**Not re-read:** the 50 sources in copyright, whose text is not committed: 1,020 values (256 pressures, 243 compositions, 188
flow references, 187 space-velocity bases, 146 species) still lack a context, with no note. Re-reading them needs their PDFs (`scale evidence
rehydrate`, then the upgrade-curation skill on the worklist). The full report, step by step and with the re-reading
worklist by source, is [UPGRADE-0.2.0-to-0.8.2.md](UPGRADE-0.2.0-to-0.8.2.md); it describes the graph before this
re-reading.
