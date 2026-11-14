# Read one curated scale-catal document a second time

You did not curate this source. Read the document against the source and report what is wrong; never edit the graph,
`rights.yaml` or the curator's report. This is a second reading by another agent, not a review: agents that share a
model are not independent reviewers, and a person reviews the document before it counts as reviewed.
Today's date is ${today}: a date up to it (a retrieval date, say) is not in the future.

1. **Read the procedure:** `${scale} call skills '{"name": "curate-corpus"}'`.
2. **The folder:** `${folder}`. The graph is `${graph}`. The page texts are `work/texts/${slug}.txt` (the source, then its SI
   pages `[page S1]` …). The PDF is `pdfs/${slug}.pdf`, and the curator's report is `work/curation.json`.
3. **Run `${scale} source check ${folder}`** (without `--derive-links`, which would rewrite the graph). It must report
   ok.
4. **The previous reading's issues**, which a fix was asked to resolve. Check each first: one the fix did not
   resolve is reported again, with its severity; then read the rest of the document as below.
${previous}
5. **Check what the tools cannot:**
   - every quote supports the record or value it is cited for (the tool only checks that it is verbatim);
   - values as printed, in the printed unit, with `as_reported` where the text differs; nothing converted in place;
   - conditions and results paired from the same run; a condition stated once is on every run it covers;
   - every driving force of each test is listed; `interpretations` are the source's readings, not the curator's;
   - unknowns typed (`not_reported` with `missing_reason`); no typical value filled in; no unreported product as 0;
   - results the source cites from other works are not recorded as its own runs;
   - values read off a figure carry an uncertainty, with the axis ticks used in the evidence note;
   - `rights.yaml` class and basis follow the copy read; claims are in the curator's words;
   - scope: a document left `no_data`, or one that leaves out a material the source itself makes or characterizes,
     is a `needs_fix` issue when the source reports its own preparation or characterization, whatever the material
     is for (the checklist covers Preparations and Characterizations; `no_data` is for a source with nothing of its
     own, such as a review);
   - coverage: the source's main results (its key tables and figures) are recorded. A main result printed only in a
     figure is digitized by the skill's recipe ("Digitizing a figure"), the points that cannot be read listed in an
     `extraction_error` gap; a main-result figure left undigitized ("not curated", "not digitized") is a `needs_fix`
     issue that names the figure. Supporting information and secondary figures may stay declared not curated.
6. **Give every issue a severity.** `major`: a value, unit, condition or result that is wrong, not supported by its
   quote, paired with the wrong run or filled in; a main result missing or left undigitized; a record that misstates
   the source (a wrong link, a result cited from another work recorded as the source's own, a driving force or scope
   left out). `minor`: the record holds, but its support or wording could be better (a quote that supports it in part
   while the sentence beside it holds the rest, a locator, a note, an optional detail). The verdict is `needs_fix` when
   an issue is major and `pass` when every issue is minor: minor issues stay in the reading for the person who reviews
   the document, they do not send it back. The scripts settle the verdict by this rule, whatever you write.
7. **Write `${folder}/work/review.json`:**
   `{"verdict": "pass" | "needs_fix" | "reject", "issues": [{"record": "<id>", "locator": "<where in the source>",
   "problem": "<what is wrong>", "fix": "<what to do>", "severity": "major" | "minor"}], "coverage": "<one line>",
   "note": "<one line>"}`. Use `reject` only when the folder holds the wrong source or its text cannot be read.
8. **Reply** with the verdict and the number of issues. Nothing else.
