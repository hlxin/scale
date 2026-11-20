---
name: first-paper
version: 0.1.0
description: A new contributor's first SCALE experience in one step - give one paper (a DOI or a PDF) and get back a small knowledge graph of it, the paper answering SCALE's three use cases (what was tested under which conditions, has this been done before, which runs failed), a review sheet of every number beside its quote, and, after the person approves, a contribution to catal-commons with credit. Use when someone wants to try SCALE on their own paper, "contribute my first paper", "turn this DOI into a knowledge graph", "show me what SCALE does with my paper", or runs /first-paper with a DOI.
scale_release: ">v0.3.0"
inputs:
  - One paper - a DOI, or a PDF (with its DOI when it has one)
  - Optionally its SI and data files (with their column dictionaries)
  - The person's GitHub login, for credit (asked; never guessed)
allowed-tools:
  - Bash(scale source start:*)
  - Bash(scale source check:*)
  - Bash(scale source digest:*)
  - Bash(scale source finish:*)
  - Bash(scale review values:*)
  - Bash(scale graph describe:*)
  - Bash(scale graph validate:*)
  - Bash(scale pages:*)
  - Bash(scale evidence:*)
  - Bash(scale call skills:*)
  - Bash(scale call describe:*)
  - Bash(scale call template:*)
  # not pre-approved, so a person sees each call: `scale graph contribute --write`, git push, opening a pull request
outputs:
  - The curation folder of the paper (from `scale source start`) with its graph, checked
  - review-values.md - every numeric value beside the text it rests on, flagged values first
  - digest.md - the paper as a knowledge graph - its tests, conditions and results; whether SCALE's graphs report the same catalysts and reactions; its negative results; its claims kept apart; what to check
  - After approval, the public copy and the dry run of the contribution to catal-commons
validation:
  - "`scale source check <folder> --derive-links` reports zero errors"
  - Every flagged value in `scale review values` is fixed or explained in one line
  - "`scale source digest <folder>` runs, and its numbers are the ones shown to the person"
human-review:
  - Always before anything is shared - the person checks review-values.md and the claims, and says "approved"
  - Always before the contribution is written or a pull request opened - the person says so in their own words
---

# Your first paper in SCALE

The goal is a short loop with something worth having at the end of it: the person gives one paper and gets back
their paper **as a knowledge graph that answers questions**, checked, with a clear choice to share it. Keep the
person informed in one line per step; never ask them to do what a tool can do.

## 0. Ask, once, before starting

- the DOI or PDF (and SI or data files, if they have them);
- their GitHub login for credit (or "anonymous" - then the contribution credits no one);
- whether the paper's PDF is open access or they will provide it (`scale source start` finds an open-access copy only
  with `--email`; for a paywalled paper ask for the PDF).

Say what will happen: about an hour of agent work, then about 20 minutes of their checking, and nothing is shared
without their "approved".

## 1. Start the folder

```bash
scale source start --doi <DOI>            # or --pdf <file>; add --email <address> to look for an open-access copy
```

Work only in the folder it prints. Read its `BRIEF.md`.

## 2. Curate - follow the curate-corpus skill for one source

Read `skills/curate-corpus/SKILL.md` (or `scale call skills '{"name": "curate-corpus"}'`) and follow its procedure for
one source, steps 2-11. For a first paper, prioritize what makes the digest useful:

1. every **catalyst** with its components (`HAS_COMPONENT` to species with their formulas), so the paper can be looked
   up against SCALE's graphs; every catalytic **test** linked to its catalyst sample, catalyst and **reaction** (with
   its `equation`);
2. each test's **conditions and results** as printed (value objects with `as_reported`), tables read from the page image
   as well as the text layer (`scale pages render` / `region`);
3. **failed, inactive and null runs** as tests with their conditions - zero as zero, "< 2 %" as an upper bound,
   "not detected" as below detection; never drop them;
4. the authors' **claims** as Claims, any proposal as a Hypothesis, never an interpretation as a property of a material.

Preparations and characterizations follow when there is time; a smaller graph that is right beats a larger one that
is not.

## 3. Check until clean

```bash
scale source check <folder> --derive-links                                    # until 0 errors
scale review values <folder>/<slug>.graph.json --out <folder>/review-values.md
```

For every flagged value: re-read the source; fix the record (most often: cite the sentence that states a condition
the paper gives once, or correct a misread cell), or write one line saying why it is right. Rerun until each flag is
fixed or explained.

## 4. Show the person their paper

```bash
scale source digest <folder> --out <folder>/digest.md
```

In a checkout of the repository the digest looks the paper up in every graph in `graphs/`; elsewhere pass
`--against <clone>/graphs/methanol-synthesis-pre1966` (or another graph) or it uses the public example the package carries.

Present, in this order and briefly:

1. **What the paper became**: the counts, and the digest's three sections in a few lines each, quoting its tables
   rather than paraphrasing numbers. Say plainly that "not found" in section 2 means not in SCALE's graphs, not new.
2. **How to see it**: the [graph explorer](https://hlxin.github.io/scale/) opens `<folder>/<slug>.graph.json`
   (*open a graph file*); every node shows its quote.
3. **Their job**: open `review-values.md`, check the flagged and unverifiable values against the paper, read every
   claim. List what you left `not_reported` or in `unmodeled`, and anything you were unsure of.

Then **stop** and wait. Corrections they give are applied, checked again (step 3) and the digest rerun.

## 5. Only after "approved": prepare the contribution

```bash
scale source finish <folder> --public
```

In a clone of github.com/hlxin/scale, show the dry run:

```bash
scale graph contribute <folder>/<slug>.public.graph.json --to graphs/catal-commons --by <login>
```

It refuses a paper already in the commons and says what it would add. Ask once more before `--write`, a branch, a
push or a pull request. The pull request is opened under the agent's own GitHub identity, never the person's, and a
SCALE reviewer approves it ([governance/review-policy.yaml](../../governance/review-policy.yaml)). If they would
rather not use git, the [contribution form](https://github.com/hlxin/scale/issues/new?template=contribution.yml)
takes the public graph file.

## What must never happen

- Sharing, writing to `graphs/`, pushing or opening a pull request without the person's own "approved" / "yes".
- A number the source does not print, a unit converted, a typical value filled in, a failed run dropped.
- "This has not been done" from a digest that found nothing: it is "not in SCALE's graphs".
- Quoting a paper in copyright beyond the cap: `scale evidence report` must list no violation before step 5.
