# Figure QA — verify, re-crop, and prune the multimodal figures

Extraction crops figures deterministically (`extract_figures.py` / a column-aware cropper): fast, but
imperfect. A crop can grab the wrong region (title/abstract/TOC), be cut off, merge panels, or capture a
figure that is scientifically useless (a review's "scope overview" schematic). Because Claude is a reliable
multimodal reader, **figure QA is a Claude vision pass** and happens in TWO places: the per-paper **reviewer**
(`templates/review_subagent.md`) checks each new crop inline during the build, and this **bulk sweep**
re-verifies every crop across the finished corpus — run after extraction, before a release, or before
answering with figures. Use a vision-capable tier (Sonnet is a good default at this scale).

## Per figure — one of three outcomes
- **GOOD** — a clean, complete, single figure matching its caption. Leave it untouched.
- **BAD → re-crop** — right figure, wrong crop (cut off / wrong region / includes body text). Recover it:
  render the source page(s), locate the real figure, crop a fractional bounding box, view, refine, and
  overwrite **in place** (same filename/path, so `graph.json`'s `Figure.props.path` stays valid). The real
  figure may be on a **different page** than the one recorded — search pages by the caption.
- **DROP** — not worth keeping: a review/overview/scope schematic, a graphical-abstract/TOC, or a montage
  stitching figures from several different studies (typical of review papers). Re-cropping cannot fix bad
  content — remove the `Figure` node (and its `DEPICTS` edges). Prefer figures from **primary** research;
  avoid review-paper figures.

## How to run it (Claude-oriented, parallel)
Dispatch **one subagent per figure** (batches of ~5–10), each given: the figure basename, its current crop
path, the source PDF, the recorded page, and the caption. The subagent views the crop, classifies it, and if
BAD re-crops iteratively; it returns `GOOD | BAD(recropped from page N) | DROP`. One subagent = one figure
(idempotent; a killed agent loses at most one figure).

Tools: `extract_figures.py <pdf> --pages N --out <dir> --prefix <id> --page-render` renders a whole page; the
subagent crops it (it can read the PNG and cut a region with PyMuPDF/Pillow in a one-off command in
`.scripts/<topic>/kg/<name>/figfix/`) and, before overwriting a crop in place, copies the original to
`.scripts/<topic>/kg/<name>/figfix/orig/`. DROP = remove the Figure node from the fragment and re-run the merge;
the PNG moves to `figures_unused/` at release (never deleted).

## Safety
- **Never race a live extraction.** Extraction only writes figures for the paper it is currently processing,
  so QA only figures of **already-finished** papers (ids below the cursor); filenames differ ⇒ no collision.
- **Overwrite in place, back up first.** The graph references figures by relative path — keep the path; the
  backup makes every re-crop reversible.
- **Refresh downstream.** Reports and visualizations base64-embed figures at build time, so after a QA pass
  regenerate any report/subgraph HTML to pick up the corrected crops, and drop DROP-flagged `Figure` nodes
  from any rendered subgraph.

Bias toward scientifically meaningful figures — quantitative result plots (efficiency / yield / rate /
selectivity / polarization curves), mechanism / energy diagrams, characterization that reveals the active
structure — over decorative schematics.
