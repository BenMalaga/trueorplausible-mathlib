"""Generate the TrueOrPlausible overview figure (design schematic, no model outputs).

Two panels:
  (left)  one real benchmark pair, a TRUE Mathlib4 statement next to its subtly-FALSE
          near-miss mutant, with the single edit highlighted.
  (right) the mutation taxonomy: Family A (false-by-construction, tiers F/M) and
          Family B (truth-uncertain near-misses, tier N), with one example operator each.

INPUT / DESIGN DATA ONLY. This draws the benchmark's *input* design (a true/false pair and
the operator taxonomy). It contains NO model judgments, scores, or pre-registered outcome
metrics. The headline pair is a real item from the built benchmark (data/benchmark/
trueorplausible_v1.0.jsonl); the per-operator examples are short faithful illustrations.

Run:
    .venv/bin/python -m src.figures.make_overview_figure
Output:
    docs/figures/overview.png  (~150 dpi, colorblind-friendly)
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

# --- Palette (colorblind-friendly: Okabe-Ito) ------------------------------------------------
INK = "#22292f"
MUTED = "#5b6770"
TRUE_C = "#0072B2"   # blue: TRUE / library-proved
FALSE_C = "#D55E00"  # vermilion: FALSE / mutant
FAM_A = "#009E73"    # green: Family A (false by construction)
FAM_B = "#AA4499"    # purple: Family B (truth-uncertain)
PANEL = "#f6f8f9"
EDGE = "#d6dadd"
HILITE = "#FFE2C9"   # edit highlight (pale vermilion)

MONO = {"family": "monospace"}

# --- The headline pair: a REAL A3 (Tier M) item from the built benchmark ----------------------
# data/benchmark/trueorplausible_v1.0.jsonl ,  source decl `empty : μ ⊥ = 0`
# A3 swaps the conclusion's head relation `=` -> `≠`: a single surface-subtle character,
# yet logically the negation of the theorem.
PAIR = {
    "name": "theorem empty :",
    "head": "μ ⊥ ",
    "true_rel": "=",
    "false_rel": "≠",
    "tail": " 0",
    "operator": "A3",
    "family": "A",
    "tier": "M",
    "edit": "=   →   ≠     (complementary-relation swap)",
}

# --- Taxonomy: one short faithful example per operator ----------------------------------------
TAXONOMY = [
    ("A", "F", "A1", "negate the conclusion", "P", "¬ (P)"),
    ("A", "F", "A2", "quantifier negation", "∀ x, P x", "∃ x, ¬ P x"),
    ("A", "M", "A3", "complementary relation", "a = b", "a ≠ b"),
    ("B", "N", "B1", "drop a hypothesis", "(h : 0<n) … P", "… P"),
    ("B", "N", "B2", "strict ↔ non-strict", "a < b", "a ≤ b"),
    ("B", "N", "B3", "off-by-one literal", "n", "n+1"),
]


def draw_box(ax, x, y, w, h, fc, ec, lw=1.2, radius=0.018, z=1):
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            linewidth=lw, edgecolor=ec, facecolor=fc, zorder=z,
        )
    )


def main(out_path="docs/figures/overview.png"):
    fig = plt.figure(figsize=(12.8, 6.3), dpi=150)
    fig.patch.set_facecolor("white")
    gs = fig.add_gridspec(1, 2, width_ratios=[1.05, 1.0], wspace=0.08,
                          left=0.03, right=0.985, top=0.99, bottom=0.04)

    # ============================ LEFT PANEL: the one pair ===================================
    axL = fig.add_subplot(gs[0, 0])
    axL.set_xlim(0, 1)
    axL.set_ylim(0, 1)
    axL.axis("off")

    axL.text(0.0, 0.975, "One statement, one edit, opposite truth value",
             fontsize=15, fontweight="bold", color=INK, va="top")
    axL.text(0.0, 0.915,
             "A real benchmark pair: a Mathlib4 theorem vs. its near-miss mutant.\n"
             "The model sees ONE statement and answers True or False, with no proof and no context.",
             fontsize=9.6, color=MUTED, va="top", linespacing=1.5)

    # TRUE card
    draw_box(axL, 0.02, 0.605, 0.96, 0.210, PANEL, TRUE_C, lw=1.8)
    axL.text(0.05, 0.778, "TRUE", fontsize=12, fontweight="bold", color=TRUE_C, va="center")
    axL.text(0.165, 0.778, "library-proved in Mathlib4", fontsize=8.8, color=MUTED, va="center")
    # statement: name line, then the proposition line; relation rendered in blue, inline
    axL.text(0.05, 0.715, PAIR["name"], fontsize=12.5, color=INK, va="center", **MONO)
    axL.text(0.05, 0.660, PAIR["head"], fontsize=14, color=INK, va="center", **MONO)
    axL.text(0.155, 0.660, PAIR["true_rel"], fontsize=15, fontweight="bold",
             color=TRUE_C, va="center", **MONO)
    axL.text(0.185, 0.660, PAIR["tail"], fontsize=14, color=INK, va="center", **MONO)

    # arrow + operator label between cards
    axL.annotate("", xy=(0.5, 0.475), xytext=(0.5, 0.595),
                 arrowprops=dict(arrowstyle="-|>", color=FAM_A, lw=2.3))
    axL.text(0.535, 0.535,
             f"apply  {PAIR['operator']}",
             fontsize=11, color=FAM_A, fontweight="bold", va="center")
    axL.text(0.535, 0.498,
             f"Family {PAIR['family']} · Tier {PAIR['tier']}",
             fontsize=9, color=MUTED, va="center")

    # FALSE card
    draw_box(axL, 0.02, 0.250, 0.96, 0.210, PANEL, FALSE_C, lw=1.8)
    axL.text(0.05, 0.423, "FALSE", fontsize=12, fontweight="bold", color=FALSE_C, va="center")
    axL.text(0.175, 0.423, "mutant: one operator application", fontsize=8.8,
             color=MUTED, va="center")
    axL.text(0.05, 0.360, PAIR["name"], fontsize=12.5, color=INK, va="center", **MONO)
    axL.text(0.05, 0.305, PAIR["head"], fontsize=14, color=INK, va="center", **MONO)
    # highlight box behind the edited relation
    draw_box(axL, 0.149, 0.278, 0.034, 0.054, HILITE, FALSE_C, lw=1.5, radius=0.009, z=2)
    axL.text(0.155, 0.305, PAIR["false_rel"], fontsize=15, fontweight="bold",
             color=FALSE_C, va="center", zorder=3, **MONO)
    axL.text(0.185, 0.305, PAIR["tail"], fontsize=14, color=INK, va="center", **MONO)

    # edit caption box
    axL.text(0.5, 0.180, "the single edit", fontsize=9.5, color=MUTED, va="center",
             ha="center", style="italic")
    draw_box(axL, 0.13, 0.060, 0.74, 0.080, "white", FALSE_C, lw=1.5, radius=0.012)
    axL.text(0.5, 0.100, PAIR["edit"], fontsize=11, color=FALSE_C, fontweight="bold",
             va="center", ha="center", **MONO)

    # ============================ RIGHT PANEL: taxonomy tree =================================
    axR = fig.add_subplot(gs[0, 1])
    axR.set_xlim(0, 1)
    axR.set_ylim(0, 1)
    axR.axis("off")

    axR.text(0.0, 0.975, "Mutation taxonomy", fontsize=15, fontweight="bold",
             color=INK, va="top")
    axR.text(0.0, 0.915,
             "Six operators, two families, three tiers, ordered from\n"
             "textually obvious to surface-subtle.",
             fontsize=9.6, color=MUTED, va="top", linespacing=1.5)

    # root
    rx, ry = 0.5, 0.815
    draw_box(axR, rx - 0.21, ry - 0.030, 0.42, 0.060, "white", INK, lw=1.6)
    axR.text(rx, ry, "true Mathlib4 statement", fontsize=10.5, fontweight="bold",
             color=INK, va="center", ha="center")

    # two family headers
    famA_x, famB_x = 0.265, 0.735
    fam_top = 0.700      # top edge of family header box
    fam_h = 0.066
    # connectors root -> families
    for fx, fc in [(famA_x, FAM_A), (famB_x, FAM_B)]:
        axR.plot([rx, fx], [ry - 0.030, fam_top], color=fc, lw=1.5, zorder=0)

    draw_box(axR, famA_x - 0.225, fam_top - fam_h, 0.45, fam_h, "white", FAM_A, lw=1.6)
    axR.text(famA_x, fam_top - 0.024, "Family A", fontsize=9.8, fontweight="bold",
             color=FAM_A, va="center", ha="center")
    axR.text(famA_x, fam_top - 0.048, "false by construction", fontsize=8.0,
             color=MUTED, va="center", ha="center")

    draw_box(axR, famB_x - 0.225, fam_top - fam_h, 0.45, fam_h, "white", FAM_B, lw=1.6)
    axR.text(famB_x, fam_top - 0.024, "Family B", fontsize=9.8, fontweight="bold",
             color=FAM_B, va="center", ha="center")
    axR.text(famB_x, fam_top - 0.048, "truth-uncertain · Lean-verified", fontsize=8.0,
             color=MUTED, va="center", ha="center")

    # operator rows under each family
    tier_label = {"F": "Tier F: far (textually obvious)",
                  "M": "Tier M: mid (no negation symbol)",
                  "N": "Tier N: near (minimal near-miss)"}
    A_ops = [t for t in TAXONOMY if t[0] == "A"]
    B_ops = [t for t in TAXONOMY if t[0] == "B"]

    def draw_op_column(ops, cx, fc):
        row_h = 0.088
        gap = 0.020
        tier_gap = 0.022   # extra space above a new tier's first row for its label
        y = fam_top - fam_h - 0.050
        last_tier = None
        for fam, tier, op, desc, before, after in ops:
            if tier != last_tier:
                y -= tier_gap
                axR.text(cx, y + 0.006, tier_label[tier], fontsize=7.8, color=fc,
                         fontweight="bold", va="bottom", ha="center")
                last_tier = tier
            top = y
            draw_box(axR, cx - 0.225, top - row_h, 0.45, row_h, PANEL, EDGE, lw=1.0)
            draw_box(axR, cx - 0.225, top - row_h, 0.012, row_h, fc, fc, lw=0, radius=0.003)
            axR.text(cx - 0.195, top - 0.020, op, fontsize=9.5, fontweight="bold",
                     color=fc, va="top", ha="left")
            axR.text(cx - 0.140, top - 0.020, desc, fontsize=8.6, color=INK,
                     va="top", ha="left")
            axR.text(cx - 0.195, top - row_h + 0.016,
                     f"{before}  →  {after}", fontsize=8.2, color=MUTED,
                     va="bottom", ha="left", **MONO)
            y -= row_h + gap
        return y

    draw_op_column(A_ops, famA_x, FAM_A)
    draw_op_column(B_ops, famB_x, FAM_B)

    # footer note (design provenance)
    axR.text(0.5, 0.012,
             "Ground truth is machine-checkable. Pairs are length-controlled; "
             "each operator applies once.",
             fontsize=7.8, color=MUTED, va="bottom", ha="center", style="italic")

    fig.savefig(out_path, dpi=150, facecolor="white", bbox_inches="tight", pad_inches=0.12)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
