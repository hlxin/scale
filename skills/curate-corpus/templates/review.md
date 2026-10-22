# Read one curated scale-catal document a second time

You did not curate this source. Read the document against the source and report what is wrong; never edit the graph,
`rights.yaml` or the curator's report. This is a second reading by another agent, not a review: agents that share a
model are not independent reviewers, and a person reviews the document before it counts as reviewed.

1. **Read the procedure:** `${scale} call skills '{"name": "curate-corpus"}'`.
2. **The folder:** `${folder}`. The graph is `${graph}`. The page texts are `work/texts/${slug}.txt` (the paper, then its SI
   pages `[page S1]` …). The PDF is `pdfs/${slug}.pdf`, and the curator's report is `work/curation.json`.
3. **Run `${scale} source check ${folder}`** (without `--derive-links`, which would rewrite the graph). It must report
   ok.
4. **Check what the tools cannot:**
   - every quote supports the record or value it is cited for (the tool only checks that it is verbatim);
   - values as printed, in the printed unit, with `as_reported` where the text differs; nothing converted in place;
   - conditions and results paired from the same run; a condition stated once is on every run it covers;
   - every driving force of each test is listed; `interpretations` are the source's readings, not the curator's;
   - unknowns typed (`not_reported` with `missing_reason`); no typical value filled in; no unreported product as 0;
   - results the source cites from other works are not recorded as its own runs;
   - values read off a figure carry an uncertainty, with the axis ticks used in the evidence note;
   - `rights.yaml` class and basis follow the copy read; claims are in the curator's words;
   - coverage: the source's main results (its key tables and figures) are recorded, or declared not curated.
5. **Write `${folder}/work/review.json`:**
   `{"verdict": "pass" | "needs_fix" | "reject", "issues": [{"record": "<id>", "locator": "<where in the source>",
   "problem": "<what is wrong>", "fix": "<what to do>"}], "coverage": "<one line>", "note": "<one line>"}`.
   Use `reject` only when the folder holds the wrong paper or its text cannot be read.
6. **Reply** with the verdict and the number of issues. Nothing else.
