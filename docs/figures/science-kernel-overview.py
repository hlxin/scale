"""Draw the one-slide overview of the science kernel (matplotlib; no Graphviz needed).

    python science-kernel-overview.py        # writes science-kernel-overview.png beside this file

Label and edge names are checked against the kernel (core/graph/kernel.yaml), so the picture cannot drift
from the schema: a name that is not declared there stops the script.
"""

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
REPO = _repo_root(HERE, Path.cwd())
K = yaml.safe_load((REPO / "core/graph/kernel.yaml").read_text())          # the science kernel (core layer)
V = yaml.safe_load((REPO / "domain/graph/scale-catal.yaml").read_text())["version"]   # the schema's one version

METHOD, THINGS, WHO, EXP, STUDIED = "#2b5c8a", "#2e7d45", "#6b3f8f", "#b5651d", "#a8323e"
W, H = 3.3, 1.1

# label: (x, y, colour, key properties)
NODES = {
    "Question":    (7.5, 12.2, METHOD, "statement · scope"),
    "Hypothesis":  (2.5, 9.0, METHOD, "kind · statistical_role\nrefuted_if · status"),
    "Prediction":  (7.5, 9.0, METHOD, "expected value · direction\nproposed_at"),
    "Claim":       (12.5, 9.0, METHOD, "kind · status\ninference_type · scope"),
    "Design":      (2.5, 6.0, METHOD, "design_kind · assignment\nblocking · stopping rule"),
    "Experiment":  (7.5, 6.0, EXP, "physical | computational\ninterventional | observational\nconditions · results"),
    "Procedure":   (12.5, 5.4, METHOD, "method · conditions\nprocedure_status"),
    "Variable":    (2.5, 3.0, METHOD, "scale · quantity_kind\nunit · categories"),
    "Protocol":    (9.2, 3.0, METHOD, "the plan:\nsteps · version"),
    "Operation":   (12.9, 3.0, METHOD, "static | dynamic · varied_quantities\ntime_pattern · period · segments"),
    "Model":       (17.6, 9.0, THINGS, "equations · assumptions\nvalidity_domain"),
    "Source":      (21.6, 11.2, THINGS, "kind · title · doi\nyear · peer_reviewed"),
    "Instrument":  (21.6, 7.0, THINGS, "instrument_kind\nsettings"),
    "Dataset":     (21.6, 9.1, THINGS, "data_kind · uri · sha256\nversion · availability"),
    "ObjectOfStudy": (19.6, 4.3, STUDIED, "thing | system |\nphenomenon | population\nkind or particular"),
    "Software":    (3.0, -0.6, WHO, "software_kind (agent …)\nversion"),
    "Person":      (7.0, -0.6, WHO, "orcid · name_variants"),
    "Institution": (11.0, -0.6, WHO, "institution_kind · ror"),
    "Project":     (15.0, -0.6, WHO, "award_id · dates"),
}

# (edge type, source label, target label, curvature (matplotlib arc3 rad), label position 0..1, dashed)
EDGES = [
    ("ADDRESSES", "Hypothesis", "Question", -0.12, 0.5, False),
    ("ADDRESSES", "Claim", "Question", 0.12, 0.5, False),
    ("DERIVES", "Hypothesis", "Prediction", 0.0, 0.5, False),
    ("TESTS", "Experiment", "Prediction", 0.0, 0.5, False),
    ("TESTS", "Experiment", "Hypothesis", 0.0, 0.5, False),
    ("CONCLUDES", "Experiment", "Claim", 0.0, 0.5, False),
    ("ABOUT", "Claim", "Hypothesis", -0.2, 0.5, False),
    ("DERIVES", "Model", "Prediction", 0.3, 0.5, False),
    ("PART_OF_DESIGN", "Experiment", "Design", 0.0, 0.5, False),
    ("HAS_VARIABLE", "Design", "Variable", 0.0, 0.5, False),
    ("HAS_VARIABLE", "Experiment", "Variable", 0.0, 0.45, False),
    ("FOLLOWS_PROTOCOL", "Experiment", "Protocol", 0.0, 0.45, False),
    ("FOLLOWS_PROTOCOL", "Procedure", "Protocol", 0.0, 0.62, False),
    ("PART_OF", "Procedure", "Experiment", 0.0, 0.5, False),
    ("HAS_OPERATION", "Experiment", "Operation", 0.0, 0.82, False),
    ("HAS_OPERATION", "Procedure", "Operation", 0.0, 0.3, False),
    ("HAS_OUTPUT", "Procedure", "ObjectOfStudy", 0.0, 0.45, False),
    ("EXAMINES", "Experiment", "ObjectOfStudy", 0.3, 0.45, False),
    ("REPRESENTS", "Model", "ObjectOfStudy", 0.0, 0.3, False),
    ("USES_INSTRUMENT", "Experiment", "Instrument", -0.05, 0.4, False),
    ("CALIBRATED_BY", "Instrument", "Experiment", -0.05, 0.62, False),
    ("USES_MODEL", "Experiment", "Model", -0.1, 0.65, False),
    ("PERFORMED_BY", "Experiment", "Person", 0.0, 0.62, False),
    ("PROPOSED_BY", "Experiment", "Software", 0.0, 0.62, False),
    ("MEMBER_OF", "Person", "Institution", 0.0, 0.5, False),
    ("PARTICIPATES_IN", "Institution", "Project", 0.0, 0.5, False),
]
EVIDENCE = [("Claim", "Source"), ("Model", "Source")]     # drawn dashed: embedded evidence points at sources

for lab in NODES:
    assert lab in K["nodes"], f"{lab} is not a kernel label"
for t, s, d, *_ in EDGES:
    assert t in K["edges"], f"{t} is not a kernel edge"
    ed = K["edges"][t]
    for side, lab in (("from", s), ("to", d)):
        allowed = ed[side]
        assert allowed == "ANY" or isinstance(allowed, dict) or lab in allowed, f"{t}.{side} does not allow {lab}"

fig, ax = plt.subplots(figsize=(25, 18.5))
ax.set_xlim(-0.4, 25.2)
ax.set_ylim(-5.1, 14.2)
ax.axis("off")
ax.text(0, 13.85, f"SCALE science kernel (schema {V}): the method of science, what it is done with, who does it",
        fontsize=23, fontweight="bold", color="#222222")
ax.text(0, 13.3, "Domains specialize: CatalyticTest, Characterization, Computation, Analysis is_a Experiment; Preparation, Treatment "
        f"is_a Procedure; Material, Catalyst, Reaction is_a ObjectOfStudy.   {len(K['nodes'])} labels, {len(K['edges'])} edge types (main ones drawn).",
        fontsize=13, color="#444444")

for (x0, y0, x1, y1, title, col) in [(0.5, 2.0, 14.6, 12.95, "The method of science", METHOD),
                                     (15.5, 6.2, 23.7, 12.4, "What science is done with", THINGS),
                                     (16.6, 2.9, 22.6, 5.85, "What is studied", STUDIED),
                                     (1.0, -1.6, 17.0, 0.75, "Who does it", WHO)]:
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0.02,rounding_size=0.25",
                                fc=col, alpha=0.06, ec=col, lw=1.2, zorder=0))
    ax.text(x0 + 0.2, y1 - 0.4, title, fontsize=14, fontweight="bold", color=col, zorder=1)


def size(lab):
    if lab == "Experiment":
        return W + 0.5, H + 0.95
    if lab == "ObjectOfStudy":
        return W + 0.5, H + 0.75
    return W, H


def anchor(a, b, lab):
    """Point on the border of the box of `lab` centred at a, towards b."""
    w, h = size(lab)
    (xa, ya), (xb, yb) = a, b
    dx, dy = xb - xa, yb - ya
    sx = (w / 2) / abs(dx) if dx else float("inf")
    sy = (h / 2) / abs(dy) if dy else float("inf")
    k = min(sx, sy)
    return xa + dx * k, ya + dy * k


def on_curve(p0, p2, rad, t):
    """Point at t on matplotlib's arc3 quadratic Bezier from p0 to p2."""
    (x1, y1), (x2, y2) = p0, p2
    cx, cy = (x1 + x2) / 2 + rad * (y2 - y1), (y1 + y2) / 2 - rad * (x2 - x1)
    return ((1 - t) ** 2 * x1 + 2 * t * (1 - t) * cx + t * t * x2,
            (1 - t) ** 2 * y1 + 2 * t * (1 - t) * cy + t * t * y2)


def draw(s, d, rad, label=None, pos=0.5, dashed=False):
    a, b = NODES[s][:2], NODES[d][:2]
    p0, p1 = anchor(a, b, s), anchor(b, a, d)
    ax.add_patch(FancyArrowPatch(p0, p1, connectionstyle=f"arc3,rad={rad}", arrowstyle="-|>", mutation_scale=16,
                                 color="#888888" if dashed else "#555555", lw=1.3, zorder=2, shrinkA=3, shrinkB=3,
                                 linestyle=(0, (4, 3)) if dashed else "-"))
    if label:
        x, y = on_curve(p0, p1, rad, pos)
        ax.text(x, y, label, ha="center", va="center", fontsize=10, color="#333333", zorder=5,
                bbox=dict(fc="white", ec="none", pad=1.0, alpha=0.92))


for t, s, d, rad, pos, dashed in EDGES:
    draw(s, d, rad, t, pos, dashed)
for s, d in EVIDENCE:
    draw(s, d, -0.32 if s == "Claim" else -0.1, "evidence (embedded)" if s == "Claim" else None, 0.5, True)

# self-loops
for lab, t, dy, off in (("Hypothesis", "COMPETES_WITH", H / 2, -1.5), ("ObjectOfStudy", "HAS_PART", (H + 0.75) / 2, 0.6)):
    x, y = NODES[lab][:2]
    ax.add_patch(FancyArrowPatch((x + off, y + dy), (x + off + 0.8, y + dy), connectionstyle="arc3,rad=-1.4",
                                 arrowstyle="-|>", mutation_scale=14, color="#555555", lw=1.2, zorder=2))
    ax.text(x + off + 0.4, y + dy + 0.72, t, ha="center", fontsize=10, color="#333333", zorder=5,
            bbox=dict(fc="white", ec="none", pad=1.0, alpha=0.92))

for lab, (x, y, col, props) in NODES.items():
    w, h = size(lab)
    big = lab in ("Experiment", "ObjectOfStudy")
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.02,rounding_size=0.15",
                                fc=col, ec="none", zorder=3))
    ax.text(x, y + h / 2 - 0.3, lab, ha="center", va="center", fontsize=17 if big else 14.5, fontweight="bold",
            color="white", zorder=4)
    ax.text(x, y - (0.22 if big else 0.14), props, ha="center", va="center", fontsize=10, color="white",
            zorder=4, linespacing=1.3)

note = ("Experiment → Experiment:  CONTROL_FOR {control_kind, differs_in}   ·   REPLICATES {repeat | replicate | reproduce, changed}\n"
        "SUPPORTS / CONTRADICTS {warrant, premise_refs}:  Experiment, Claim, Dataset, Source → Claim, Hypothesis\n"
        "EVALUATES {verification | validation, criterion, outcome}:  Experiment → Model, Software, Prediction\n"
        "HAS_INPUT / HAS_OUTPUT {role, input_version}:  Experiment, Procedure → ObjectOfStudy, Dataset, Model, …\n"
        "AUTHORED_BY:  Source, Dataset → Person, Institution   ·   REPORTED_IN:  any record → Source, Dataset\n"
        "Variable.of → ObjectOfStudy (whose property it is)   ·   physical specimens are domain labels (CatalystSample)\n"
        "TESTS {outcome: supports | disputes | refutes | inconclusive, statistical_decision, result_refs}")
ax.text(20.4, 1.25, note, ha="center", va="center", fontsize=9.6, color="#333333", zorder=5, linespacing=1.55,
        bbox=dict(fc="white", ec="#aaaaaa", boxstyle="round,pad=0.5"))

# shared structures band
panel = [
    ("value object", "status · value | lower–upper | text_value\n| boolean_value | ref_value · unit · qualifier\n"
                     "bound · as_reported · missing_reason\nuncertainty: kind, GUM evaluation, interval,\n"
                     "coverage k, confidence, replicates\nvariable · target · origin · produced_by"),
    ("evidence item", "source → Source | Dataset\nlocator · kind · quote (verbatim)\nid · ECO evidence_type"),
    ("record_ref", "record · path (JSON pointer)\nrecord_version\nlets TESTS and SUPPORTS cite one result"),
    ("stewardship", "contributed_by · curated_by\nproject · access · embargo\nlicence"),
    ("every node", "name · origin · evidence\nidentifiers · recorded_at\nrecord_version · unmodeled"),
]
ax.text(0.5, -2.2, "Shared structures", fontsize=14, fontweight="bold", color="#444444")
x = 0.5
widths = [6.2, 4.4, 4.4, 4.0, 4.0]
for (title, body), w in zip(panel, widths):
    ax.add_patch(FancyBboxPatch((x, -4.95), w - 0.3, 2.4, boxstyle="round,pad=0.02,rounding_size=0.12",
                                fc="#f4f4f4", ec="#999999", lw=1, zorder=3))
    ax.text(x + 0.2, -2.85, title, fontsize=12.5, fontweight="bold", color="#333333", va="center", zorder=4)
    ax.text(x + 0.2, -3.15, body, fontsize=10, color="#333333", va="top", zorder=4, linespacing=1.35)
    x += w

fig.savefig(HERE / "science-kernel-overview.png", dpi=100, bbox_inches="tight", facecolor="white")
print("wrote", HERE / "science-kernel-overview.png")
