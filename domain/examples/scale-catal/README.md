# scale-catal examples (synthetic)

Worked examples of the catalysis scale-catal schema
(`domain/graph/scale-catal.yaml`: the science kernel plus the catalysis file, with its one
checklist; schema 0.1.0). Every document follows the checklist (`follows_domains: ["catalysis"]`); what
each catalytic test must report follows from the driving forces it lists. Every value is invented; each document
says so (`data_status: synthetic_example`, `origin: synthetic`).

| file | what it shows |
|---|---|
| `example.json` | A thermocatalytic test (ZnO, CO + 2 H2) with its catalyst sample, feed, reaction, conditions and results as value objects, evidence with locators, REPORTED_IN links and the stewardship of a graph (an invented laboratory and project, public access). |
| `driving-force-examples/*.json` | One document per other driving force or combination: electrocatalysis (static and pulsed), photocatalysis, plasma catalysis, electrothermal, photothermal (static and dynamic), photoelectro- and electrophotocatalysis, each with its controls. Built by `build_examples.py`. |
| `comparison-examples/current-density-comparison.json` | Eight CO2-electroreduction tests on one Ag electrode whose current densities differ only in what a scientific comparison keeps apart: the same potentials vs RHE and vs SHE, geometric and ECSA normalization (the ECSA one naming its denominator with `normalized_by`), a potential converted from Ag/AgCl to RHE with evidence, a basis that contradicts its record, and a normalization or a reference scale not reported. Competency question CQ-06 ranks them in groups (`comparison: scientific`). Built by `build_examples.py`. |
| `source-lifecycle/retracted-source.json` | Two thermocatalytic runs from two invented papers and a retraction notice that retracts the second (a Source of kind `retraction_notice`, a `RETRACTS` link with reason, date and evidence). The validator flags the records that rest on the retracted paper; competency question CQ-05 shows that a query leaves its run out by default and brings it back, labelled, with `include_retracted: true`. |

```bash
scale graph validate domain/examples/scale-catal/example.json
scale graph validate domain/examples/scale-catal/driving-force-examples/*.json
python domain/examples/scale-catal/driving-force-examples/build_examples.py   # rebuilds them (tests check they are unchanged)
python domain/examples/scale-catal/comparison-examples/build_examples.py
```
