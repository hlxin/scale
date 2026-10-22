# Curate one source into a scale-catal document

You curate ONE source. Follow SCALE's curate-corpus skill (its procedure for one source) exactly; this note only says where things are and what to
report. Work only inside the folder below.

1. **Read the procedure first:** `${scale} call skills '{"name": "curate-corpus"}'` (and, when a situation needs one,
   its recipes: `${scale} call skills '{"name": "curate-corpus", "reference": "references/recipes.md"}'`). Read the
   schema with `${scale} graph describe <Label> --domain catalysis`, never from memory.
2. **The working folder** (made by `scale source start`): `${folder}`
   - `BRIEF.md`: what to curate and how; read it next.
   - `${graph}`: the graph to fill. Its header, Source, steward and project are already there.
   - `work/texts/${slug}.txt`: the page texts the verbatim check reads: the paper's pages (`[page 1]` …), then its
     supporting information (`[page S1]` …; supporting information belongs to the paper's Source). SI appended:
${si_read}
     SI files not appended (read them yourself if they matter; their values cannot be quoted verbatim):
${si_left}
   - `pdfs/${slug}.pdf`: the PDF. For a figure or a page whose text layer loses values, use `${scale} pages render`
     and `${scale} pages region`, as the skill says.
   - `rights.yaml`: the source's rights. Set `class`, `licence` and `basis` from the copy you read (its first page),
     as the skill says. The paper index's verdict, to check against the copy: licence ${licence}; copy: ${text_version}.
3. **What the paper index knows** (the copy wins where they differ): ${title} (${year}), DOI ${doi}. Set the Source's
   `text_version` to the version of the copy you read.
   ${start_note}
4. **Curate what the source itself reports**, by the skill's procedure: records, value objects in the printed unit
   (the printed text in `as_reported` where it differs), evidence with a short verbatim quote, a locator and the
   source on every record and link that states something, typed absences (`not_reported` with `missing_reason`),
   `unmodeled` for what the schema cannot express, every driving force of each test, and the source's own
   interpretations. Claims in your own words. Never extend the schema, never fill a missing value, never record a
   result the source cites from another work as its own run.
5. **Check until it passes:** `${scale} source check ${folder} --derive-links` (exit 0: zero errors, every quote found,
   the cap respected).
   Gap reports you write by hand (the procedure, step 12) go in `${folder}/work/gaps/`, one `GAP-*.json` each in
   SCALE's gap format, with their `access`.
6. **Write `${folder}/work/curation.json`:**
   `{"result": "curated" | "no_data", "records": {"nodes": <nodes you added>, "links": <links you added>}, "gaps": <n>,
   "not_curated": "<what you did not look at, e.g. SI tables S4-S6, Source Data>", "note": "<one line>"}`.
   `no_data` only when the source reports nothing the catalysis checklist covers (say why in `note`); the graph then
   keeps its header and Source.
7. **Reply** with the last check's `ok`, its number of errors and warnings, and your one-line note. Nothing else.
