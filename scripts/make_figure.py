"""Generate the manuscript's trajectory figure.

A 2xN grid of small multiples, N being the number of runs (currently 4). Columns
are models in the RUNS order -- same-model runs first, the heterogeneous-arbiter
ablation last; the top row is the epistemic score (0-50), the bottom row the
grounding score (0-10). Each panel shows both arms across the three scored turns
with +/-1 SE bars.

The two measures get their own row rather than a second y-axis: they are
different constructs on different scales, and a dual-axis chart would invite the
reader to compare their slopes as if they were commensurable.

The point of the figure is the *timing* of collapse. The arms start together at
A1 in every panel, and the three model families then break at different turns.
That is the one thing the A3 results table cannot show. The bottom row carries
the companion finding: grounding is equal at A1 everywhere, so the arbiter
changes whether a position is held, not how well it is argued from the start --
and Llama's bottom-row collapse to ~0 is the strongest single piece of evidence
for that reading.

Numbers come from scripts/analysis.py, so the figure and the tables can never
drift apart.

    python scripts/make_figure.py

Writes manuscript/figures/trajectory.pdf (for LaTeX) and .png (for eyeballing).
"""
import pathlib
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from analysis import ROOT, ROUNDS, RUNS, load_run, paired, summarise  # noqa: E402

OUT_DIR = ROOT / "manuscript" / "figures"

# Validated categorical slots 1 and 2 (see dataviz reference palette).
# All-pairs CVD dE 24.7, normal-vision dE 33.6 on a white surface.
C_EF = "#2a78d6"        # blue
C_BASE = "#eb6834"      # orange
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

# The baseline arm answers every turn with the primary prompt. The other arm is
# identical except that a keyword router hands contradiction turns to the
# arbiter prompt -- normally on the same model, and on a different model only in
# the ablation. So the contrast is "plus an arbiter", not "a different system".
LABEL_EF = "Baseline + arbiter"
LABEL_BASE = "Baseline"

# Line style and marker shape duplicate the colour encoding, so the figure still
# reads when the proceedings are printed in greyscale.
STYLE = {
    "ef": dict(color=C_EF, linestyle="-", marker="o", markerfacecolor=C_EF,
               label=LABEL_EF),
    "baseline": dict(color=C_BASE, linestyle="--", marker="s", markerfacecolor="white",
                     label=LABEL_BASE),
}

# (field, axis label, upper limit, tick step)
MEASURES = [
    ("efs_50", "Epistemic score\n(0–50)", 50, 10),
    ("sgs", "Grounding score\n(0–10)", 10, 2),
]

# Headroom above the last tick, so the per-turn effect sizes never collide with
# a data point. Ticks still stop at the measure's real maximum.
ANN_Y = 1.03      # annotation baseline, as a fraction of the measure maximum
PAD_Y = 1.09      # axis top, same units

XTICKS = ["A1\nassert", "A2\n+doubt", "A3\n+authority"]

# Panel geometry. Four columns across IEEE's 7.16in text width leaves ~1.7in per
# panel, so type that was comfortable at three columns now has to be sized
# deliberately rather than left at the rcParam default.
FIG_W = 7.16
FIG_H = 3.5     # unchanged from the 3-column version: the 4th column costs no page depth
FS_TITLE = 7.5
FS_TICK = 7
FS_ANN = 6.2

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Nimbus Roman No9 L", "DejaVu Serif"],
    "font.size": 8,
    "axes.linewidth": 0.6,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "pdf.fonttype": 42,      # embed TrueType, not Type 3 (IEEE PDF-eXpress)
    "ps.fonttype": 42,
})


def series(idx, drop, arm_index, field):
    """Mean and standard error at each scored turn, misconception condition."""
    means, ses = [], []
    for rk in ROUNDS:
        vals = paired(idx, "misconception", rk, field, drop)[arm_index]
        means.append(vals.mean())
        ses.append(vals.std(ddof=1) / np.sqrt(len(vals)))
    return np.array(means), np.array(ses)


def stars(p):
    return "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"


def effects(idx, drop, field):
    """Cohen's d and a significance marker for each scored turn."""
    out = []
    for rk in ROUNDS:
        s = summarise(*paired(idx, "misconception", rk, field, drop))
        out.append("%.2f%s" % (s["d"], stars(s["p"])))
    return out


def main():
    panels = []
    for _key, label, run, primary, arbiter in RUNS:
        L = load_run(run)
        if L is None:
            print("skipping %s (no logs/%s)" % (label, run), file=sys.stderr)
            continue
        drop = set(L["incomplete"])
        P = dict(
            label=label.replace("->", "→"),
            ablation=primary != arbiter,      # heterogeneous arbiter
            n=len(paired(L["idx"], "misconception", "r3_press2", "efs_50", drop)[0]),
        )
        for field, _, _, _ in MEASURES:
            P[field] = {arm: series(L["idx"], drop, i, field)
                        for i, arm in enumerate(("baseline", "ef"))}
            P[field + "_d"] = effects(L["idx"], drop, field)
        panels.append(P)
    if not panels:
        sys.exit("no runs found under logs/")

    fig, axes = plt.subplots(len(MEASURES), len(panels), figsize=(FIG_W, FIG_H),
                             sharex="col", sharey="row")
    axes = np.atleast_2d(axes)
    x = np.arange(len(ROUNDS))

    for row, (field, ylabel, ymax, step) in enumerate(MEASURES):
        for col, P in enumerate(panels):
            ax = axes[row, col]
            ax.set_axisbelow(True)
            ax.yaxis.grid(True, color=GRID, linewidth=0.5)
            ax.xaxis.grid(False)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
            for side in ("left", "bottom"):
                ax.spines[side].set_color(AXIS)

            for arm in ("baseline", "ef"):
                m, se = P[field][arm]
                ax.errorbar(x, m, yerr=se, linewidth=1.4, markersize=4.5,
                            markeredgewidth=1.0, markeredgecolor=STYLE[arm]["color"],
                            capsize=2, elinewidth=0.8, clip_on=False, zorder=3,
                            **STYLE[arm])

            # Cohen's d and significance for each turn, on a reserved strip
            # above the last tick. This is what lets the prose stop reciting
            # numbers: the reader gets the effect size where the data is.
            for i, txt in enumerate(P[field + "_d"]):
                ax.text(i, ymax * ANN_Y, txt, ha="center", va="bottom",
                        fontsize=FS_ANN, color=INK_2)

            # A touch of extra left margin so a negative d at A1 clears the axis.
            ax.set_xlim(-0.38, len(ROUNDS) - 0.68)
            ax.set_ylim(0, ymax * PAD_Y)
            ax.set_yticks(range(0, ymax + 1, step))
            ax.tick_params(colors=MUTED, length=3, labelsize=FS_TICK)
            for lb in ax.get_xticklabels() + ax.get_yticklabels():
                lb.set_color(INK_2)

            if row == 0:
                # Model name alone on the title line -- at four columns there is
                # not room for the name and the n together without risking an
                # overlap into the neighbouring panel. n and the ablation flag go
                # on a muted second line; the caption spells out what "ablation"
                # means, which is cheaper in prose than in 1.7in of panel.
                ax.set_title(P["label"], fontsize=FS_TITLE, color=INK, pad=14)
                note = "$n=%d$" % P["n"]
                if P["ablation"]:
                    note += "  ·  ablation"
                ax.text(0.5, 1.03, note, transform=ax.transAxes,
                        ha="center", va="bottom", fontsize=FS_ANN, color=MUTED)
            if row == len(MEASURES) - 1:
                ax.set_xticks(x)
                ax.set_xticklabels(XTICKS)
            if col == 0:
                ax.set_ylabel(ylabel, color=INK, fontsize=8)

    handles, labels = axes[0, 0].get_legend_handles_labels()
    order = [labels.index(LABEL_EF), labels.index(LABEL_BASE)]
    fig.legend([handles[i] for i in order], [labels[i] for i in order],
               loc="lower center", ncol=2, frameon=False, fontsize=8,
               bbox_to_anchor=(0.5, -0.02), handlelength=2.6, columnspacing=2.5)

    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.subplots_adjust(hspace=0.28)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        path = OUT_DIR / ("trajectory.%s" % ext)
        fig.savefig(path, dpi=400, bbox_inches="tight", facecolor="white")
        print("wrote %s" % path.relative_to(ROOT))


if __name__ == "__main__":
    main()
