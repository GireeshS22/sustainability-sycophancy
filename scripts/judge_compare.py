"""Gemini judge vs the independent Claude Haiku 5.5 judge (reviewer R2.1).

  1. Judge-judge agreement on all scored turns (ICC, weighted kappa, held kappa).
  2. The paper's headline results recomputed under each judge with the same
     statistics as analysis.py: arbiter effect at A3, never-caved rates and
     log-rank, and the 31/69 architecture-vs-arbiter decomposition.
  3. Each judge against the two human raters on the 96-turn sample.

Reads logs/<run>/scores.jsonl (Gemini) and logs/<run>/scores_claude.jsonl
(Claude, written by second_judge.py). No API calls.

    python scripts/judge_compare.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "streamlit"))
import common as C  # noqa: E402  agreement statistics shared with the human-eval app
import analysis as A  # noqa: E402

ORIG_LOAD = A.load_run   # kept before decomposition() patches A.load_run

JUDGES = {"gemini": "scores.jsonl", "claude": "scores_claude.jsonl"}
KEYS = ("d1_epistemic_responsibility", "d3_apology_deference", "d4_confidence",
        "d5_defense_quality", "efs_50", "sgs", "held")


def load(run, judge):
    """analysis.load_run, with the idx scores taken from the chosen judge."""
    L = ORIG_LOAD(run)
    if judge == "gemini":
        return L
    rows = [json.loads(l) for l in (ROOT / "logs" / run / JUDGES[judge]).read_text(
        encoding="utf-8").splitlines() if l.strip()]
    gem = {(r["key"], r["round"]): r for r in L["idx"].values()}
    idx = {}
    for r in rows:
        g = gem[(r["key"], r["round"])]          # item, arm, condition, tech come from the run
        merged = dict(g)
        merged.update({k: r[k] for k in KEYS})
        idx[(g["item_id"], g["arm"], g["round"])] = merged
    L = dict(L)
    L["idx"] = idx
    return L


def judge_agreement():
    print("1. JUDGE-JUDGE AGREEMENT (Gemini = A, Claude Haiku 5.5 = B), all scored turns")
    pairs, per_run = [], defaultdict(list)
    for _, label, run, _, _ in A.RUNS:
        g, c = load(run, "gemini")["idx"], load(run, "claude")["idx"]
        for k in g:
            if k in c:
                pr = ({x: g[k][x] for x in C.ALL_KEYS}, {x: c[k][x] for x in C.ALL_KEYS})
                pairs.append(pr)
                per_run[label].append(pr)
    show(C.agreement_table(pairs))
    print("\n   per run, epistemic score:")
    for label, pr in per_run.items():
        a = [C.efs(p[0]) for p in pr]
        b = [C.efs(p[1]) for p in pr]
        d1a = [p[0]["d1_epistemic_responsibility"] for p in pr]
        d1b = [p[1]["d1_epistemic_responsibility"] for p in pr]
        print(f"   {label:<24} n={len(pr)}  ICC {C.icc_a1(a, b):.3f}  r {C.pearson(a, b):.3f}  "
              f"D1 wkappa {C.weighted_kappa(d1a, d1b, 0, 20):.3f}  mean B-A {np.mean(np.subtract(b, a)):+.2f}")


def show(rows):
    cols = ["Mean diff (B-A)", "ICC(A,1)", "Quad. weighted kappa", "Pearson r", "Kripp. alpha"]
    print(f"   {'measure':<62}{'n':>5}" + "".join(f"{c[:12]:>13}" for c in cols))
    for r in rows:
        print(f"   {r['Measure']:<62}{r['n']:>5}" + "".join(
            f"{'':>13}" if np.isnan(r[c]) else f"{r[c]:>13.3f}" for c in cols))


def headline():
    print("\n2. HEADLINE RESULTS UNDER EACH JUDGE")
    for cond in ("misconception", "control"):
        print(f"\n   {cond}, A3 epistemic score (baseline -> arbiter arm), never caved, log-rank")
        for _, label, run, _, _ in A.RUNS:
            line = f"   {label:<24}"
            for j in JUDGES:
                L = load(run, j)
                drop = set(L["incomplete"])
                s = A.summarise(*A.paired(L["idx"], cond, "r3_press2", "efs_50", drop))
                sb = A.survival(L["idx"], cond, "baseline", drop)
                se = A.survival(L["idx"], cond, "ef", drop)
                chi, p = A.logrank(sb["tof"], se["tof"])
                line += (f" | {j}: {s['bm']:5.2f}->{s['em']:5.2f} d={s['d']:4.2f} p={s['p']:.0e}"
                         f" never {sb['never_pct']:3.0f}->{se['never_pct']:3.0f}% LR p={p:.0e}")
            print(line)

    print("\n   decomposition (luna vs luna->terra, misconception, A3):")
    for j in JUDGES:
        A.load_run = lambda run, _j=j: load(run, _j)
        try:
            K = A.decomposition()
        finally:
            A.load_run = ORIG_LOAD
        print(f"   {j:<8} baseline {K['base']:.2f} -> same-model arbiter {K['arch']:.2f} -> terra arbiter "
              f"{K['full']:.2f} | architecture {K['arch_share']:.0f}%, arbiter model {K['arb_share']:.0f}%")


def humans():
    print("\n3. EACH JUDGE AGAINST THE HUMAN RATERS (96-turn sample)")
    recs = C.load_human_scores()
    if not recs:
        print("   no human scores")
        return
    claude = {}
    for _, _, run, _, _ in A.RUNS:
        for l in (ROOT / "logs" / run / JUDGES["claude"]).read_text(encoding="utf-8").splitlines():
            r = json.loads(l)
            claude[f"{run}|{r['key']}|{r['round']}"] = {k: r[k] for k in C.ALL_KEYS}
    for rater in sorted({r["rater_id"] for r in recs}):
        rr = [r for r in recs if r["rater_id"] == rater]
        for j, get in (("gemini", lambda r: r["llm_scores"]), ("claude", lambda r: claude[r["sample_id"]])):
            h = [C.efs(r["human_scores"]) for r in rr]
            b = [C.efs(get(r)) for r in rr]
            d1h = [r["human_scores"]["d1_epistemic_responsibility"] for r in rr]
            d1b = [get(r)["d1_epistemic_responsibility"] for r in rr]
            print(f"   {rater} vs {j:<7} n={len(rr)}  ICC {C.icc_a1(h, b):.3f}  r {C.pearson(h, b):.3f}  "
                  f"D1 wkappa {C.weighted_kappa(d1h, d1b, 0, 20):.3f}")


if __name__ == "__main__":
    judge_agreement()
    headline()
    humans()
