# SCALE catalysis knowledge base — instructions for your agent

<!-- Copy this file into your own project as CLAUDE.md or AGENTS.md (or append it to the one you have), and register the
SCALE tools with the MCP setup in agents/README.md. It tells an agent WHEN to query SCALE and HOW to answer from it. -->

You can query **SCALE**: knowledge graphs of the catalysis literature in which every reported value, condition and
claim is linked to its source, page and a verbatim quote. The tools are the `scale_*` MCP tools (or
`uvx scale-catal call <tool> '<json>'` in a shell). Start a session with `scale_status`.

## When to query SCALE (and when not to)

Query SCALE **before** answering from memory or the web when the question is one of these:

| the user asks… | use case | worked plan to copy and adapt |
|---|---|---|
| "Which catalysts work for X **under** these conditions?", "What was tested at ≤ T and ≤ P?", "Recommend a catalyst for…" | **catalyst search, accounting for conditions** | `use-cases/uc1-catalyst-search-by-conditions.yaml` |
| "Has anyone done X?", "Is this new?", "Who first reported…?", related-work for a paper or proposal | **novelty / related work** | `use-cases/uc2-has-this-been-done.yaml`, `uc2b-cu-zn-co2-undecidable.yaml` |
| "Why didn't this work?", "Which catalysts were inactive?", "What poisons / deactivates…?" | **negative results** | `use-cases/uc3-negative-results.yaml`, `uc3b-why-it-failed.yaml` |
| "What evidence supports this mechanism / active site?", "Do sources disagree on…?" | claims and their evidence | `domain/competency/cq-16-activity-assignments.yaml` |

The worked plans are in `examples/methanol-synthesis-public/use-cases/` in the repository and in the installed
package (`scale_domains` lists more example plans, the competency questions).

Do **not** query SCALE for general chemistry or textbook knowledge, for topics outside the curated graphs (check
`scale_status` and the graph's `title` and `description`), or to look up a single paper you already have open.

## How to answer from SCALE

1. **Write a query plan; don't guess field names.** Use `scale_describe` to see the labels, edges and properties,
   then run `scale_query` (structured) and/or `scale_search` (words and meaning over the evidence quotes).
2. **Cite every factual sentence** with the returned evidence: source, locator (page, table, figure) and quote.
3. **Keep three layers apart**, and label each in your answer:
   - *reported* — measured or computed values as the source printed them (`as_reported`, unit, basis);
   - *authors' interpretation* — `Claim` records (`claim_kind`, `claim_status`);
   - *your own* inference, extrapolation or hypothesis — in a separate, clearly labelled paragraph.
4. **Respect conditions and bases.** Don't compare or rank values in different units, bases (e.g. per cent of CO
   converted vs. of carbon fed), temperatures or pressures. The query reports what it left out and why
   (`excluded`, `coverage`, `limitations`); pass those caveats on to the user.
5. **An absence is a result, not a "no".**
   - `no_matching_record`: nothing in *this graph* matches. Say "not found in the curated sources", never "has not
     been done".
   - `missing_context`: the graph cannot decide (e.g. catalyst components not curated). Say so and name what is
     missing.
   - `schema_gap`: the schema cannot express the question. Report it; it can become a change request.
6. **Bounds and zeros stay distinct.** "Less than 2 %", "below detection limit", "0.0" and "not reported" are four
   different answers; never collapse them.
7. Synthetic examples (`data_status: synthetic_example`) are not evidence about the world.

## Contributing back

If the user wants to add their own paper, use the `first-paper` skill (`/first-paper <DOI>` in a clone of the SCALE
repository) or the copy-paste prompt in its `CONTRIBUTE.md`: curation → checks → a digest and review sheet → a pull
request. Never open a pull request or submit a gap without the user's
explicit approval.
