# Changelog

## 1.0.0

First release, exported from scale-graph 0.1.0 (ex:msyn/graph/co-co2-hydrogenation).

The graph is the SCALE knowledge-graph release v1.0.0 of examples/methanol-synthesis-pre1966 (hlxin/scale): methanol
synthesis from CO/CO2 + H2, 105 sources published before 1966-01-01, scale-graph 0.1.0 (spec sha256
3c2fa7205a7bae5e0bbfa7d87826ff7ab7803e78536129064101c7d5a2c02006).

### Not carried over

- 3277 links (ABOUT 629, HAS_COMPONENT 353, SUPPORTS 339, FED_WITH 225, PREPARED_FROM 219, OF_REACTION 187, ...) whose every quote is withheld under SCALE's copyright cap (in-copyright sources quote at
  most 4,000 distinct characters and 10 % of their text; the rest is kept as sha256 and length). A GALAXY edge needs
  a verbatim quote, so they are left out here; they stay in the SCALE graph with their source, locator and passage,
  and will be added when GALAXY accepts withheld-quote evidence.
- 229 values the sources do not report (typed absences in SCALE; GALAXY has no field for them).

