"""Draw the catalysis graph schema: the science kernel (core) and the catalysis domain's file catalysis.yaml, with its
one vocabulary and its one checklist, read from the catalysis manifest (matplotlib). One version for the whole schema:
the manifest's.

    python scale-graph-architecture.py        # writes scale-graph-architecture.png beside this file

Everything shown — the labels of the kernel and the catalysis file, the checklist's items for every record and its cases,
each keyed on the driving forces a catalytic test lists — is read from domain/graph/scale-graph.yaml and
the files it names.
"""

import textwrap as tw
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import yaml  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

def _repo_root(*starts: Path) -> Path:
    """The SCALE checkout (scale-release.yaml and releases/), searched upward from each start in turn."""
    for p in (q for s in starts for q in (s, *s.parents)):
        if (p / "scale-release.yaml").exists() and (p / "releases").is_dir():
            return p
    raise SystemExit("run inside a SCALE repository checkout: no scale-release.yaml and releases/ above "
                     + ", ".join(map(str, starts)))


HERE = Path(__file__).resolve().parent
G = _repo_root(HERE, Path.cwd()) / "domain/graph"   # the manifest's directory: its parts are relative to it
MAN = yaml.safe_load((G / "scale-graph.yaml").read_text())
ROOT = G.parent.parent
KERNEL = yaml.safe_load((ROOT / "core/graph/kernel.yaml").read_text())   # the manifest's kernel (layout.kernel_path)
FILES = {d["domain"]: d for d in (yaml.safe_load((G / p).read_text()) for p in MAN["domains"])}
assert list(FILES) == ["catalysis"] and "modules" not in MAN, "two layers: the kernel and one catalysis file"
V = MAN["version"]                                  # the schema's one version (the kernel and the catalysis file carry none)
CAT = FILES["catalysis"]
CK = CAT["checklist"]
ITEMS = {"must", "should", "edges", "values", "units"}

COL = {"kernel": "#2b5c8a", "domain": "#2e7d45", "every": "#5a5a5a", "single": "#a8323e", "combined": "#7a1f2b"}
W = 24.0


def wrap(words, width, sep=", "):
    lines, cur = [], ""
    for w in words:
        if cur and len(cur) + len(w) + len(sep) > width:
            lines.append(cur + sep.rstrip())
            cur = w
        else:
            cur = f"{cur}{sep}{w}" if cur else w
    return lines + [cur] if cur else lines


def rbox(x, y, w, h, fc, z=3):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.02,rounding_size=0.15", fc=fc, ec="none", zorder=z))


def text(x, y, s, size, bold=False, color="white", va="center", ha="center"):
    ax.text(x, y, s, ha=ha, va=va, fontsize=size, fontweight="bold" if bold else "normal", color=color, zorder=5, linespacing=1.25)


def condition(case):
    """'driving_forces any of thermo, electrothermo' for a case's condition."""
    return "; ".join(f"{k}: {op.replace('_', ' ')} {', '.join(v)}" for k, c in case.items() if k not in ITEMS for op, v in c.items())


def items(block, prefix=""):
    """What a checklist block requires or narrows (must, edges must, values), and how many should items it scores."""
    out = []
    if block.get("must"):
        out.append("must " + ", ".join(prefix + x for x in block["must"]))
    if (block.get("edges") or {}).get("must"):
        out.append("must have " + ", ".join(block["edges"]["must"]))
    out += [f"{prefix}{k} ∈ {{{', '.join(v)}}}" for k, v in (block.get("values") or {}).items()]
    n = len(block.get("should") or []) + len((block.get("edges") or {}).get("should") or [])
    if n:
        out.append(f"should: {n} item{'s' if n != 1 else ''} ({', '.join((block.get('should') or [])[:3])}{', …' if n > 3 else ''})")
    return out


fig, ax = plt.subplots(figsize=(25, 17.5))
ax.set_xlim(0, W)
ax.set_ylim(-2.4, 17.3)
ax.axis("off")
text(0.2, 16.9, f"SCALE schema {V}: science kernel (core) → catalysis domain, with one vocabulary and one checklist",
     22, bold=True, color="#222222", ha="left")
text(0.2, 16.35, "Documents follow the checklist as follows_domains: [catalysis]. What a catalytic test must report depends on the "
     "driving forces it lists (CatalyticTest.driving_forces): each case (red) applies only to the tests whose forces match.",
     12.5, color="#444444", ha="left")

box = {}

# ---- the science kernel
labs = list(KERNEL["nodes"])
op = KERNEL["nodes"]["Operation"]["properties"]
body = wrap(labs, 150) + ["", f"Operation  operation_mode: {' | '.join(op['operation_mode']['values'])}  ·  "
                          + ", ".join(k for k in op if k not in ("operation_mode",)) +
                          "  —  any experiment, under any driving force, can be run statically or dynamically"]
h = 1.0 + 0.32 * len(body)
box["kernel"] = (W / 2, 0.2 + h / 2, W - 0.6, h)
rbox(*box["kernel"], COL["kernel"])
y = box["kernel"][1]
text(W / 2, y + h / 2 - 0.32, f"science kernel  ·  {len(labs)} labels, {len(KERNEL['edges'])} edges  "
     "(the general base layer: the method of science)", 14.5, bold=True)
text(W / 2, y + h / 2 - 0.68, "\n".join(body), 10.5, va="top")
top = y + h / 2

# ---- the catalysis file: its vocabulary
roles = CAT["edges"]["HAS_COMPONENT"]["properties"]["role"]["values"]
forces = CAT["nodes"]["CatalyticTest"]["properties"]["driving_forces"]["items"]["values"]
body = wrap(list(CAT["nodes"]), 165) + ["", "driving_forces: " + " | ".join(forces) + "   ·   roles are on edges, not labels:  "
                                         "HAS_COMPONENT {role: " + ", ".join(r for r in roles if r not in ("not_stated", "other")) + "}"]
h = 1.0 + 0.32 * len(body)
box["catalysis"] = (W / 2, top + 1.0 + h / 2, W - 0.6, h)
rbox(*box["catalysis"], COL["domain"])
y = box["catalysis"][1]
text(W / 2, y + h / 2 - 0.32, f"catalysis domain (catalysis.yaml)  ·  {len(CAT['nodes'])} labels, "
     f"{len(CAT['edges'])} edges  (catalysis as a whole and the terms of every driving force)", 14.5, bold=True)
text(W / 2, y + h / 2 - 0.68, "\n".join(body), 10.0, va="top")
top = y + h / 2

# ---- its checklist: what every record must report, then the cases
ct = CK["labels"]["CatalyticTest"]
unless = "; ".join(f"{k} ∈ {{{', '.join(v)}}}" for k, v in (ct.get("unless") or {}).items())
every = ["every CatalyticTest: " + "; ".join(items(ct)) + (f"   ·   exempt when {unless}" if unless else "")]
for lab, blk in CK["labels"].items():
    if lab != "CatalyticTest" and items(blk, f"{lab}."):
        every += tw.wrap(f"{lab}: " + "; ".join(items(blk)), 170)
for e, blk in (CK.get("edges") or {}).items():
    if items(blk):
        every.append(f"{e} (edge): " + "; ".join(items(blk)))
h = 0.9 + 0.3 * len(every)
box["every"] = (W / 2, top + 0.45 + h / 2, W - 0.6, h)
rbox(*box["every"], COL["every"])
y = box["every"][1]
text(W / 2, y + h / 2 - 0.3, "checklist  catalysis  ·  for every record", 13.5, bold=True)
text(W / 2, y + h / 2 - 0.62, "\n".join(every), 9.8, va="top")
top = y + h / 2

edge_cases = [(e, c) for e, blk in (CK.get("edges") or {}).items() for c in blk.get("when") or []]
cases = ct["when"]
single = [c for c in cases if len(next(iter(c["driving_forces"].values()))) == 1 or "any_of" in c["driving_forces"]]
combined = [c for c in cases if c not in single]


def case_lines(c, w):
    """The lines of a case's tile: its items, and the edge items that apply under the same condition."""
    cw, lines = int(w * 6.4), []
    for s in items(c):
        lines += tw.wrap(s, cw)
    for e, ec in edge_cases:
        if condition(ec) == condition(c):
            lines += tw.wrap(f"{e}: " + "; ".join(items(ec)), cw)
    return lines


def case_row(row, y0, colour):
    """One row of case tiles of equal height, from y0 upwards; returns the row's top."""
    if not row:
        return y0
    w = (W - 0.6 - 0.25 * (len(row) - 1)) / len(row)
    lines = [case_lines(c, w) for c in row]
    h = 0.75 + 0.27 * max(len(x) for x in lines)
    for i, (c, ls) in enumerate(zip(row, lines)):
        x, yc = 0.3 + w / 2 + i * (w + 0.25), y0 + h / 2
        rbox(x, yc, w, h, colour)
        text(x, yc + h / 2 - 0.27, condition(c).replace("driving_forces: ", ""), 11.5, bold=True)
        text(x, yc + h / 2 - 0.55, "\n".join(ls), 9.0, va="top")
    return y0 + h


top = case_row(single, top + 0.35, COL["single"])
top = case_row(combined, top + 0.3, COL["combined"])
ax.set_ylim(-2.4, max(17.3, top + 1.6))
for t_ in ax.texts[:2]:                                   # keep the title above everything
    t_.set_y(max(17.3, top + 1.6) - 0.4 - (0.55 if t_ is ax.texts[1] else 0))


def arrow(a, b):
    xa, ya, wa, ha = box[a]
    xb, yb, wb, hb = box[b]
    ax.add_patch(FancyArrowPatch((xa - wa / 2 + 0.6, ya - ha / 2), (xb - wb / 2 + 0.6, yb + hb / 2), arrowstyle="-|>",
                                 mutation_scale=14, color="#777777", lw=1.4, zorder=6))


arrow("catalysis", "kernel")
arrow("every", "catalysis")

legend = [("kernel", "science kernel"), ("domain", "catalysis domain (catalysis.yaml): one vocabulary"),
          ("every", "checklist: items for every record"), ("single", "checklist case: one driving force (or a group of them)"),
          ("combined", "checklist case: where forces act together (all of them listed)")]
for i, (k, t) in enumerate(legend):
    x, y = 0.4 + (i % 3) * 7.9, -0.45 - (i // 3) * 0.45
    ax.add_patch(FancyBboxPatch((x, y - 0.14), 0.45, 0.28, boxstyle="round,pad=0.01", fc=COL[k], ec="none"))
    text(x + 0.6, y, t, 11, color="#333333", ha="left")
text(0.4, -1.75, "Dynamic is not a driving force: a dynamic run is a kernel Operation (operation_mode dynamic) under the same checklist case. "
     "Extension keys _<prefix>_<name> hold what the schema has not yet; a new driving force enters the catalysis file (its terms and a case) "
     "by proposal.\nOne version number for the whole schema, kernel and catalysis together: every applied proposal raises it.",
     10.5, color="#333333", ha="left", bold=False)
ax.texts[-1].set_bbox(dict(fc="#f4f4f4", ec="#999999", boxstyle="round,pad=0.4"))
fig.savefig(HERE / "scale-graph-architecture.png", dpi=100, bbox_inches="tight", facecolor="white")
print("wrote", HERE / "scale-graph-architecture.png")
