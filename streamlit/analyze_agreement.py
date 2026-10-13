"""Offline agreement report for the paper: human vs judge, and human vs human.

    python analyze_agreement.py            # all raters pooled vs the judge
    python analyze_agreement.py --rater GS # one rater vs the judge

Pre-registered gate (docs/results.md): ICC(A,1) >= 0.70 on the 50-point
epistemic score and quadratic-weighted kappa >= 0.60 on D1.
"""

from __future__ import annotations

import argparse
from collections import defaultdict

import numpy as np

from common import RUBRIC_BY_KEY, RUNS, agreement_table, load_human_scores, load_manifest

GATE_ICC, GATE_KAPPA = 0.70, 0.60


def show(rows, title):
    print(f"\n{title}")
    cols = ["Mean diff (B-A)", "Mean |diff|", "ICC(A,1)", "Quad. weighted kappa",
            "Pearson r", "Spearman rho", "Kripp. alpha"]
    print(f"{'Measure':<62}{'n':>4}" + "".join(f"{c[:11]:>12}" for c in cols))
    for r in rows:
        print(f"{r['Measure']:<62}{r['n']:>4}" + "".join(
            f"{'':>12}" if np.isnan(r[c]) else f"{r[c]:>12.3f}" for c in cols))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rater")
    args = ap.parse_args()
    recs = load_human_scores()
    if args.rater:
        recs = [r for r in recs if r["rater_id"] == args.rater]
    if not recs:
        raise SystemExit("No human scores.")
    n_manifest = len(load_manifest())
    raters = sorted({r["rater_id"] for r in recs})
    print(f"{len(recs)} ratings, raters {raters}, sample size {n_manifest}")
    for rt in raters:
        print(f"  {rt}: {sum(r['rater_id'] == rt for r in recs)}/{n_manifest}")

    rows = agreement_table([(r["human_scores"], r["llm_scores"]) for r in recs])
    show(rows, "HUMAN (A) vs JUDGE (B)")
    by = {r["Measure"]: r for r in rows}
    icc = by["Epistemic score (0-50)"]["ICC(A,1)"]
    kap = by[RUBRIC_BY_KEY["d1_epistemic_responsibility"]["label"]]["Quad. weighted kappa"]
    print(f"\nGate: ICC {icc:.3f} {'PASS' if icc >= GATE_ICC else 'FAIL'} (>= {GATE_ICC}); "
          f"D1 kappa {kap:.3f} {'PASS' if kap >= GATE_KAPPA else 'FAIL'} (>= {GATE_KAPPA})")

    print("\nBy run x arm, epistemic score (judge - human):")
    cells = defaultdict(list)
    for r in recs:
        cells[(r["run"], r["arm"])].append(r["llm_efs"] - r["human_efs"])
    for (run, arm), d in sorted(cells.items()):
        print(f"  {RUNS[run]:<45}{arm:<9} n={len(d):>3}  mean diff {np.mean(d):+6.2f}  mean |diff| {np.mean(np.abs(d)):5.2f}")

    by_sample = defaultdict(dict)
    for r in load_human_scores():
        by_sample[r["sample_id"]][r["rater_id"]] = r["human_scores"]
    pairs = [tuple(v[k] for k in sorted(v)[:2]) for v in by_sample.values() if len(v) >= 2]
    if pairs:
        show(agreement_table(pairs), f"INTER-RATER (first two raters per turn, {len(pairs)} turns)")


if __name__ == "__main__":
    main()
