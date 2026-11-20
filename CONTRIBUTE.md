# Contribute your first paper

Share **one paper** (yours, or one you know well) as a SCALE record: its catalysts, preparations, test conditions,
results and claims, each linked to the page, table or figure that states it. It takes an agent about an hour of work
and you about 20 minutes of checking. Your paper then answers questions like *"which catalysts work under these
conditions?"*, *"has this been done?"* and *"why didn't this work?"* for every agent that queries SCALE, with a citation
back to you.

## What to share

| share | why it matters |
|---|---|
| the paper (DOI or PDF) | required: every record cites a page, table or figure in it |
| the SI | most conditions and negative results live here |
| data files (CSV, instrument exports) with a column dictionary | values come straight from data, not from a reading of a plot |
| **negative and null results**, even if not in the paper | the hardest knowledge to find anywhere else |

Copyright is handled for you: for a paper in copyright the shared record keeps no quoted text beyond short excerpts
(`rights.yaml`, [docs/curation.md](docs/curation.md)). Unpublished data stays local unless you choose to share it.

## The fastest way: one command

In Claude Code, in a clone of this repository:

```bash
git clone --depth 1 https://github.com/hlxin/scale && cd scale && claude
```

then type

```text
/first-paper 10.xxxx/your-doi
```

The [first-paper skill](skills/first-paper/SKILL.md) asks for your GitHub login (for credit) and the PDF if the paper
is not open access, then curates the paper and checks it. You get back:

1. **your paper as a knowledge graph**, to open in the [graph explorer](https://hlxin.github.io/scale/);
2. **`digest.md`**: your paper answering SCALE's three questions: what was tested under which conditions, whether
   SCALE's graphs already report the same catalysts and reactions (and since when), and which runs failed or were
   inactive. Its claims are kept apart from the measurements;
3. **`review-values.md`**: every number beside the text it came from, the ones a tool could not confirm first. This is
   your 20 minutes.

Nothing is shared until you say "approved", and nothing is written to the commons or pushed until you say so again.

## Other paths

| path | needs | best for |
|---|---|---|
| **A. Web page**: curate and *Contribute to the commons* in the browser | a GitHub account; the SCALE web service ([service/](service/README.md)) running for your group | trying it once, no install |
| **B. Copy-paste prompt** (below) into Codex, Cursor or another coding agent | [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh \| sh`); Tesseract only for scanned PDFs | agents other than Claude Code |
| **C. By hand** | uv | full control: [graphs/catal-commons/README.md](graphs/catal-commons/README.md) |

A chatbot without a shell (no tool use) cannot run the checks, so use the command, path A or path B.

## Path B: the prompt

Open your coding agent in an empty folder, paste this, and fill in the first lines. (The prompt runs SCALE from the
repository's head, which has `review values` and `source digest`; once a release includes it, `uvx scale-catal@<version>` works too.)

```text
Contribute one paper to the SCALE catalysis knowledge base (github.com/hlxin/scale).
Paper: <DOI, or path to the PDF>
Also read (optional): <paths to the SI, data files and their column dictionaries>
My GitHub login, for credit: <login>

Work in this order and stop where I say stop.

1. Setup. Below, SCALE means the command
   `uvx --from "scale-catal[pdf,search] @ git+https://github.com/hlxin/scale" scale-catal`.
   Run `SCALE call status`. Then read the curation procedure, `SCALE call skills '{"name": "curate-corpus"}'`,
   and follow it exactly for everything below.
2. Start. `SCALE source start --doi <DOI>` (or `--pdf <file>`). Work only in the folder it creates.
3. Curate. Fill the graph from the paper (and SI/data). Rules that matter most:
   - every value as printed, with its unit and `as_reported` text; never convert units or fill a typical value;
   - every node and link cites a short verbatim quote with its page/table/figure locator;
   - measurements, the authors' interpretations (Claim) and any proposal (Hypothesis) are separate records;
   - record failed and inactive runs as tests with their conditions - do not drop them;
   - unknown values get `not_reported` with a `missing_reason`; "below detection limit", "0" and "not reported"
     stay different;
   - for every table, render the page (`SCALE pages render`) and read the image as well as the text layer.
4. Check. Run `SCALE source check <folder> --derive-links` until it reports zero errors.
   Then run `SCALE review values <folder>/<slug>.graph.json --out <folder>/review-values.md`.
   For every FLAGGED value, re-read the source and either fix the record or explain in one line why it is right.
   Then run `SCALE source digest <folder> --out <folder>/digest.md`.
5. STOP. Show me digest.md (what was tested and under which conditions, whether SCALE already reports the same
   catalysts and reactions - "not found" means not in SCALE's graphs, not new - and the negative results), the
   review sheet path, every Claim and Hypothesis with its quote, and anything you left `not_reported` or in
   `unmodeled`. Wait for me to check the review sheet against the paper.
6. Only after I say "approved": run `SCALE source finish <folder> --public`, then show me the
   dry run of `SCALE graph contribute <folder>/<slug>.graph.json --to graphs/catal-commons` in a clone of the
   repository. Do not use --write, push, or open a pull request until I say so.
```

## What you check (step 5, about 20 minutes)

Open `review-values.md`. It lists every number the agent recorded beside the text it rests on, with the ones a tool
could not confirm first:

1. **Flagged** rows: the recorded number does not match its own printed text, or the quotes the record cites do not
   print it. Typical causes: a misread table cell, a shifted column, an OCR digit, a condition stated elsewhere in
   the paper (cite that sentence). Tick each when fixed or confirmed.
2. **Unverifiable** rows: values read off a figure, written in words, or whose quotes are withheld. Check them
   against the paper.
3. Read every **Claim**: is it what the authors say, not what the agent concluded?

Then tell the agent "approved". Your contribution becomes a pull request that a SCALE reviewer approves
([governance/review-policy.yaml](governance/review-policy.yaml)), and you are credited
([governance/credit-and-authorship.md](governance/credit-and-authorship.md)).
