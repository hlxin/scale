# Fix one curated scale-catal document (attempt ${attempt} of 3)

You curate ONE source again. Fix what the check and the second reading found, following SCALE's curate-corpus skill (its procedure for one source)
(`${scale} call skills '{"name": "curate-corpus"}'`). Work only inside `${folder}`: the graph `${graph}`, the page texts
`work/texts/${slug}.txt` (the paper, then its SI pages `[page S1]` …), the PDF `pdfs/${slug}.pdf` and `rights.yaml`.

**The check's errors** (from `${scale} source check ${folder}`):
${check_errors}

**The second reading's issues** (`work/review.json`):
${issues}

Fix each one in the graph. Where an issue does not hold, say why in `work/curation.json` `note`, citing the locator.
The curate-corpus rules still apply: values as printed, evidence on every stating record, typed absences, no schema
extension, nothing filled in. Then run `${scale} source check ${folder} --derive-links` until it passes, and rewrite
`work/curation.json` with the same fields as before plus `"attempt": ${attempt}`. Reply with the check's `ok`, its
number of errors and one line.
