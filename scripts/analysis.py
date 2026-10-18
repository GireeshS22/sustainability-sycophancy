"""Regenerate every number in docs/results.md from the committed run artifacts.

Naming: the 50-point measure is the "epistemic score", its 0-10 companion the
"grounding score", and the two arms are "baseline" and "base+arb" (the baseline
plus an arbiter stage). The raw artifacts still use the field names efs_50, sgs
and the arm id "ef".

Reads only logs/<run>/{scores,conversations,items}.jsonl. Makes no API calls.

    python scripts/analysis.py                       # full dump to stdout
    python scripts/analysis.py --json _metrics.json  # machine-readable
    python scripts/analysis.py --section headline    # one section only
"""
import argparse
import glob
import json
import os
import pathlib
import sys

import numpy as np
from scipy import stats

ROOT = pathlib.Path(__file__).resolve().parent.parent
EF_ROOT = ROOT.parent / "epistemic_fortitude"

ROUNDS = ["r1_assert", "r2_press1", "r3_press2"]
LAB = {"r1_assert": "A1", "r2_press1": "A2", "r3_press2": "A3"}
DIMS = [
    ("d1_epistemic_responsibility", "D1 epistemic responsibility", 20),
    ("d3_apology_deference", "D3 apology & deference", 10),
    ("d4_confidence", "D4 confidence", 10),
    ("d5_defense_quality", "D5 defense quality", 10),
]
BOOT_SEED = 20260808
BOOT_N = 10000

# Same-model runs first, ablation last. Every table and the figure follow this
# order, so a reader meets the architecture result before the arbiter-swap.
RUNS = [
    ("gemini", "Gemini 2.5 Flash", "pilot_gemini", "gemini-2.5-flash", "gemini-2.5-flash"),
    ("luna", "gpt-5.6-luna", "pilot_openai_same", "gpt-5.6-luna", "gpt-5.6-luna"),
    ("llama", "Llama-3.3-70B", "pilot_llama",
     "meta-llama/Llama-3.3-70B-Instruct-Turbo", "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
    ("lunaterra", "gpt-5.6-luna -> terra", "pilot_openai", "gpt-5.6-luna", "gpt-5.6-terra"),
]

# EF paper runs, for the cross-paper rebase onto EFS-50.
EF_PAIRS = [
    ("Gemini 2.5 Flash", "swebench_langgraph_baseline", "swebench_langgraph_arbiter"),
    ("GPT-5.1", "swebench_langgraph_gpt-5-1_baseline", "swebench_langgraph_gpt-5-1_arbiter"),
    ("Claude Sonnet 4.5",
     "swebench_langgraph_claude-sonnet-4-5-20250929_baseline",
     "swebench_langgraph_claude-sonnet-4-5-20250929_arbiter"),
    ("Llama-3.3-70B",
     "swebench_langgraph_meta-llama-Llama-3-3-70B-Instruct-Turbo_baseline",
     "swebench_langgraph_meta-llama-Llama-3-3-70B-Instruct-Turbo_arbiter"),
]


# --------------------------------------------------------------------------- io

def load_run(run):
    base = ROOT / "logs" / run
    if not base.is_dir():
        return None
    rows = [json.loads(l) for l in
            base.joinpath("scores.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    convs = [json.loads(l) for l in
             base.joinpath("conversations.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    items = {j["item_id"]: j for j in
             (json.loads(l) for l in
              base.joinpath("items.jsonl").read_text(encoding="utf-8").splitlines() if l.strip())}
    routing = {}
    for c in convs:
        for t in c["turns"]:
            if t.get("role") == "assistant":
                k = (c["arm"], t.get("agent", "primary"))
                routing[k] = routing.get(k, 0) + 1
    return dict(
        idx={(r["item_id"], r["arm"], r["round"]): r for r in rows},
        incomplete=sorted({c["item_id"] for c in convs if len(c["turns"]) != 8}),
        items=items, nconv=len(convs), nscore=len(rows), routing=routing,
    )


# ------------------------------------------------------------------- statistics

def paired(idx, cond, rk, field="efs_50", drop=(), only=None):
    ids = sorted({k[0] for k in idx if idx[k]["condition"] == cond and k[0] not in drop})
    if only is not None:
        ids = [i for i in ids if i in only]
    pairs = [(idx[(i, "baseline", rk)][field], idx[(i, "ef", rk)][field])
             for i in ids
             if (i, "baseline", rk) in idx and (i, "ef", rk) in idx]
    return (np.array([p[0] for p in pairs], float),
            np.array([p[1] for p in pairs], float))


def summarise(b, e):
    """Paired comparison of baseline b against EF arm e."""
    if len(b) == 0:
        return None
    diff = e - b
    sd_d = diff.std(ddof=1)
    pooled = np.sqrt((b.std(ddof=1) ** 2 + e.std(ddof=1) ** 2) / 2)
    rng = np.random.default_rng(BOOT_SEED)
    boot = rng.choice(diff, (BOOT_N, len(diff)), replace=True).mean(axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    try:
        p = float(stats.wilcoxon(e, b).pvalue) if np.any(e != b) else 1.0
    except ValueError:
        p = 1.0
    return dict(
        n=len(b), bm=b.mean(), bs=b.std(ddof=1), em=e.mean(), es=e.std(ddof=1),
        delta=diff.mean(),
        pct=100 * diff.mean() / b.mean() if b.mean() else float("nan"),
        d=diff.mean() / pooled if pooled else 0.0,
        dz=diff.mean() / sd_d if sd_d else 0.0,
        ci_lo=lo, ci_hi=hi, p=p,
        win=int((diff > 0).sum()), loss=int((diff < 0).sum()), tie=int((diff == 0).sum()),
    )


def survival(idx, cond, arm, drop=()):
    """held% per turn, never-caved%, and turns-of-failure (4 == censored)."""
    ids = sorted({k[0] for k in idx if idx[k]["condition"] == cond and k[0] not in drop})
    held = dict.fromkeys(ROUNDS, 0)
    never, tof = 0, []
    for i in ids:
        seq = [idx[(i, arm, rk)]["held"] if (i, arm, rk) in idx else None for rk in ROUNDS]
        for rk, h in zip(ROUNDS, seq):
            if h:
                held[rk] += 1
        if all(seq):
            never += 1
            tof.append((4, 0))
        else:
            tof.append((next(k + 1 for k, h in enumerate(seq) if not h), 1))
    n = max(len(ids), 1)
    return dict(n=len(ids), held_pct={LAB[rk]: 100 * held[rk] / n for rk in ROUNDS},
                never_pct=100 * never / n, tof=tof)


def logrank(a, b):
    """Mantel-Cox log-rank on (time, event) pairs; event 0 == censored."""
    times = sorted({t for t, e in list(a) + list(b) if e == 1})
    obs = exp = var = 0.0
    for t in times:
        n1 = sum(1 for x, _ in a if x >= t)
        n2 = sum(1 for x, _ in b if x >= t)
        d1 = sum(1 for x, e in a if x == t and e == 1)
        d2 = sum(1 for x, e in b if x == t and e == 1)
        n, d = n1 + n2, d1 + d2
        if n < 2:
            continue
        obs += d1
        exp += d * n1 / n
        var += d * (n1 / n) * (1 - n1 / n) * (n - d) / (n - 1)
    chi = (obs - exp) ** 2 / var if var > 0 else 0.0
    return chi, float(1 - stats.chi2.cdf(chi, 1))


def median_tof(tof):
    s = sorted(t for t, _ in tof)
    return s[len(s) // 2]


# ------------------------------------------------------------------- collection

def collect():
    out = {}
    for key, label, run, primary, arbiter in RUNS:
        L = load_run(run)
        if L is None:
            print("skipping %s (no logs/%s)" % (label, run), file=sys.stderr)
            continue
        idx, drop = L["idx"], set(L["incomplete"])
        R = dict(label=label, run=run, primary=primary, arbiter=arbiter,
                 nconv=L["nconv"], nscore=L["nscore"], excluded=sorted(drop),
                 routing={"%s/%s" % k: v for k, v in sorted(L["routing"].items())})
        for cond in ("misconception", "control"):
            C = {}
            for rk in ROUNDS:
                c = summarise(*paired(idx, cond, rk, "efs_50", drop))
                c["sgs"] = summarise(*paired(idx, cond, rk, "sgs", drop))
                c["dims"] = {}
                for field, _, _ in DIMS:
                    s = summarise(*paired(idx, cond, rk, field, drop))
                    c["dims"][field] = {k: s[k] for k in ("bm", "em", "delta", "d")}
                C[LAB[rk]] = c
            C["survival"] = {arm: survival(idx, cond, arm, drop) for arm in ("baseline", "ef")}
            chi, p = logrank(C["survival"]["baseline"]["tof"], C["survival"]["ef"]["tof"])
            C["logrank"] = dict(chi2=chi, p=p,
                                med_base=median_tof(C["survival"]["baseline"]["tof"]),
                                med_ef=median_tof(C["survival"]["ef"]["tof"]))
            R[cond] = C
        R["tech_A3"] = {}
        for t in ("solar", "wind", "ev"):
            only = {i for i in L["items"] if L["items"][i]["tech"] == t}
            c = summarise(*paired(idx, "misconception", "r3_press2",
                                  "efs_50", drop, only=only))
            # never-caved, restricted to this technology
            ids = sorted({k[0] for k in idx if idx[k]["condition"] == "misconception"
                          and k[0] not in drop and k[0] in only})
            for arm in ("baseline", "ef"):
                ok = [i for i in ids if all(idx[(i, arm, rk)]["held"] for rk in ROUNDS)]
                c["never_" + arm] = 100 * len(ok) / len(ids) if ids else 0.0
            R["tech_A3"][t] = c
        out[key] = R
    return out


def decomposition():
    """luna vs luna->terra on the items present in both runs. Isolates the arbiter."""
    A, B = load_run("pilot_openai_same"), load_run("pilot_openai")
    if A is None or B is None:
        return None
    drop = set(A["incomplete"]) | set(B["incomplete"])
    ids = sorted({k[0] for k in A["idx"]
                  if A["idx"][k]["condition"] == "misconception" and k[0] not in drop})
    rows = {}
    for rk in ROUNDS:
        for arm in ("baseline", "ef"):
            a = np.array([A["idx"][(i, arm, rk)]["efs_50"] for i in ids], float)
            b = np.array([B["idx"][(i, arm, rk)]["efs_50"] for i in ids], float)
            pooled = np.sqrt((a.std(ddof=1) ** 2 + b.std(ddof=1) ** 2) / 2)
            try:
                p = float(stats.wilcoxon(b, a).pvalue) if np.any(a != b) else 1.0
            except ValueError:
                p = 1.0
            rows["%s/%s" % (LAB[rk], arm)] = dict(
                n=len(ids), luna=a.mean(), terra=b.mean(), delta=b.mean() - a.mean(),
                d=(b.mean() - a.mean()) / pooled if pooled else 0.0, p=p)
    base = rows["A3/baseline"]["luna"]
    arch = rows["A3/ef"]["luna"]
    full = rows["A3/ef"]["terra"]
    total = full - base
    return dict(rows=rows, n=len(ids), base=base, arch=arch, full=full,
                arch_gain=arch - base, arb_gain=full - arch, total=total,
                arch_share=100 * (arch - base) / total if total else 0.0,
                arb_share=100 * (full - arch) / total if total else 0.0)


def tech_pooled(rk="r3_press2", cond="misconception", same_model_only=True):
    """Per-technology, pooled over runs rather than split by model.

    Pairs are (run, item): each of the 33 claims contributes one observation per
    run, so the rows are NOT independent and the table is descriptive. Pooling
    exists to buy back the power that splitting 33 claims three ways destroys --
    it is what makes the EV subset testable at all. The ablation is excluded by
    default, since blending a different-model arbiter into a technology summary
    would mix the architecture effect with the arbiter-model effect.
    """
    runs = [r for r in RUNS if not same_model_only or r[3] == r[4]]
    out = {}
    for tech in ("solar", "wind", "ev"):
        b, e, hb, he = [], [], [], []
        for key, _lab, run, _p, _a in runs:
            L = load_run(run)
            if L is None:
                continue
            idx, items, drop = L["idx"], L["items"], set(L["incomplete"])
            ids = sorted({k[0] for k in idx if idx[k]["condition"] == cond
                          and k[0] not in drop and items[k[0]]["tech"] == tech})
            for i in ids:
                if (i, "baseline", rk) not in idx or (i, "ef", rk) not in idx:
                    continue
                b.append(idx[(i, "baseline", rk)]["efs_50"])
                e.append(idx[(i, "ef", rk)]["efs_50"])
                hb.append(all(idx[(i, "baseline", r)]["held"] for r in ROUNDS))
                he.append(all(idx[(i, "ef", r)]["held"] for r in ROUNDS))
        s = summarise(np.array(b, float), np.array(e, float))
        s["never_baseline"] = 100 * float(np.mean(hb))
        s["never_ef"] = 100 * float(np.mean(he))
        s["n_runs"] = len(runs)
        out[tech] = s
    return out


def ef_paper_rebase():
    """Rebase the accepted EF paper's stored per-dimension scores onto EFS-50."""
    if not EF_ROOT.is_dir():
        return None

    def load(d):
        out = {}
        for f in glob.glob(str(EF_ROOT / "logs/experiments" / d / "epistemic_scores/*.json")):
            j = json.load(open(f, encoding="utf-8"))
            s = j["scores"]
            out[j["example_id"]] = (s["epistemic_responsibility"] + s["apology_and_deference"]
                                    + s["confidence_and_assertiveness"] + s["defense_quality"],
                                    s["total_epistemic_fortitude"])
        return out

    res = {}
    for label, bd, ad in EF_PAIRS:
        B, A = load(bd), load(ad)
        ids = sorted(set(B) & set(A))
        if not ids:
            continue
        b = np.array([B[i][0] for i in ids], float)
        e = np.array([A[i][0] for i in ids], float)
        s = summarise(b, e)
        s["b60"] = float(np.mean([B[i][1] for i in ids]))
        s["e60"] = float(np.mean([A[i][1] for i in ids]))
        res[label] = s
    return res


# ---------------------------------------------------------------------- reports

def hr(t):
    print("\n" + "=" * 96)
    print(t)
    print("=" * 96)


def sec_integrity(D):
    hr("1-2. RUNS AND DATA INTEGRITY")
    print("%-24s%-20s%-18s%7s%8s  %s" %
          ("model", "primary", "arbiter", "conv", "scores", "excluded"))
    for R in D.values():
        print("%-24s%-20s%-18s%7d%8d  %s" %
              (R["label"], R["primary"], R["arbiter"], R["nconv"], R["nscore"],
               ", ".join(R["excluded"]) or "none"))
    print("\nrouting (assistant turns by arm/agent)")
    for R in D.values():
        print("  %-24s %s" % (R["label"], R["routing"]))


def sec_headline(D):
    hr("3. HEADLINE -- epistemic score at A3, misconception")
    print("%-24s%5s%17s%17s%9s%8s%7s%7s%18s%10s%10s" %
          ("model", "n", "baseline M(SD)", "base+arb M(SD)", "delta", "%impr", "d", "dz",
           "95% CI", "p", "w/l/t"))
    for R in D.values():
        c = R["misconception"]["A3"]
        print("%-24s%5d%10.2f (%5.2f)%10.2f (%5.2f)%+9.2f%+7.1f%%%7.2f%7.2f  [%+6.2f,%+6.2f]%10.1e%10s" %
              (R["label"], c["n"], c["bm"], c["bs"], c["em"], c["es"], c["delta"],
               c["pct"], c["d"], c["dz"], c["ci_lo"], c["ci_hi"], c["p"],
               "%d/%d/%d" % (c["win"], c["loss"], c["tie"])))


def sec_trajectory(D):
    hr("4. TRAJECTORY -- epistemic score by turn, misconception")
    for R in D.values():
        print("\n  %s" % R["label"])
        print("  %-4s%5s%17s%17s%9s%8s%11s" %
              ("turn", "n", "baseline M(SD)", "base+arb M(SD)", "delta", "d", "p"))
        for t in ("A1", "A2", "A3"):
            c = R["misconception"][t]
            print("  %-4s%5d%10.2f (%5.2f)%10.2f (%5.2f)%+9.2f%8.2f%11.1e" %
                  (t, c["n"], c["bm"], c["bs"], c["em"], c["es"], c["delta"], c["d"], c["p"]))


def sec_decomp(K):
    hr("5. DECOMPOSITION -- arbiter stage vs arbiter model (same primary, same items)")
    if K is None:
        print("  needs both pilot_openai_same and pilot_openai")
        return
    print("%-14s%5s%12s%12s%9s%8s%11s" %
          ("turn/arm", "n", "luna arb", "terra arb", "delta", "d", "p"))
    for k, v in K["rows"].items():
        print("%-14s%5d%12.2f%12.2f%+9.2f%8.2f%11.1e" %
              (k, v["n"], v["luna"], v["terra"], v["delta"], v["d"], v["p"]))
    print("\n  A3 misconception, n=%d" % K["n"])
    print("  arbiter stage (same model)        %6.2f -> %6.2f  %+7.2f  (%.0f%%)" %
          (K["base"], K["arch"], K["arch_gain"], K["arch_share"]))
    print("  arbiter swap (luna -> terra)      %6.2f -> %6.2f  %+7.2f  (%.0f%%)" %
          (K["arch"], K["full"], K["arb_gain"], K["arb_share"]))
    print("  total                             %6.2f -> %6.2f  %+7.2f" %
          (K["base"], K["full"], K["total"]))


def sec_control(D):
    hr("6. CONTROL (true claims) -- over-correction check, A3")
    print("%-24s%5s%17s%17s%9s%8s%11s" %
          ("model", "n", "baseline M(SD)", "base+arb M(SD)", "delta", "d", "p"))
    for R in D.values():
        c = R["control"]["A3"]
        print("%-24s%5d%10.2f (%5.2f)%10.2f (%5.2f)%+9.2f%8.2f%11.1e" %
              (R["label"], c["n"], c["bm"], c["bs"], c["em"], c["es"],
               c["delta"], c["d"], c["p"]))
    print("\n  cells where base+arb is significantly WORSE than baseline (p<0.05, delta<0):")
    any_bad = False
    for R in D.values():
        for cond in ("misconception", "control"):
            for t in ("A1", "A2", "A3"):
                c = R[cond][t]
                if c["delta"] < 0 and c["p"] < 0.05:
                    any_bad = True
                    print("    %-24s %-14s %s  base %.2f  +arb %.2f  d=%+.2f  p=%.3f" %
                          (R["label"], cond, t, c["bm"], c["em"], c["d"], c["p"]))
    if not any_bad:
        print("    none")


def sec_survival(D):
    hr("7. SURVIVAL -- held% per turn and never-caved")
    for cond in ("misconception", "control"):
        print("\n  %s" % cond)
        print("  %-24s%-10s%7s%7s%7s%13s" % ("model", "arm", "A1", "A2", "A3", "never caved"))
        for R in D.values():
            for arm in ("baseline", "ef"):
                s = R[cond]["survival"][arm]
                print("  %-24s%-10s%6.0f%%%6.0f%%%6.0f%%%12.0f%%" %
                      (R["label"], "base+arb" if arm == "ef" else arm, s["held_pct"]["A1"], s["held_pct"]["A2"],
                       s["held_pct"]["A3"], s["never_pct"]))
    print("\n  log-rank on turns-of-failure (4 == censored / never failed)")
    print("  %-24s%-16s%12s%12s%10s%11s" %
          ("model", "condition", "med base", "med EF", "chi2(1)", "p"))
    for R in D.values():
        for cond in ("misconception", "control"):
            g = R[cond]["logrank"]
            print("  %-24s%-16s%12s%12s%10.2f%11.1e" %
                  (R["label"], cond,
                   "cens" if g["med_base"] == 4 else g["med_base"],
                   "cens" if g["med_ef"] == 4 else g["med_ef"], g["chi2"], g["p"]))


def sec_dims(D):
    hr("8. PER-DIMENSION -- A3, misconception")
    for R in D.values():
        print("\n  %s" % R["label"])
        for field, name, hi in DIMS:
            v = R["misconception"]["A3"]["dims"][field]
            print("    %-32s (0-%2d)  base %6.2f  +arb %6.2f  delta %+6.2f  d=%+.2f" %
                  (name, hi, v["bm"], v["em"], v["delta"], v["d"]))


def sec_sgs(D):
    hr("9. GROUNDING SCORE (0-10), reported outside the total")
    print("%-24s%-16s%22s%22s%22s" %
          ("model", "condition", "A1 base->+arb (d)", "A2 base->+arb (d)", "A3 base->+arb (d)"))
    for R in D.values():
        for cond in ("misconception", "control"):
            cells = []
            for t in ("A1", "A2", "A3"):
                s = R[cond][t]["sgs"]
                cells.append("%5.2f -> %5.2f (%+.2f)" % (s["bm"], s["em"], s["d"]))
            print("%-24s%-16s%22s%22s%22s" % (R["label"], cond, *cells))


def sec_tech(D):
    hr("10. PER-TECHNOLOGY -- A3, misconception  (EV is n=4: descriptive only)")
    print("%-24s%-7s%4s%17s%17s%9s%8s%10s%14s" %
          ("model", "tech", "n", "baseline M(SD)", "base+arb M(SD)", "delta", "d", "p",
           "never b/+arb"))
    for R in D.values():
        for t, v in R["tech_A3"].items():
            if v is None:
                continue
            print("%-24s%-7s%4d%10.2f (%5.2f)%10.2f (%5.2f)%+9.2f%8.2f%10.1e%7.0f%%/%4.0f%%" %
                  (R["label"], t, v["n"], v["bm"], v["bs"], v["em"], v["es"],
                   v["delta"], v["d"], v["p"], v["never_baseline"], v["never_ef"]))
        print()
    print("  cells that do NOT reach p<0.05 (splitting n=33 costs power):")
    for R in D.values():
        for t, v in R["tech_A3"].items():
            if v is not None and v["p"] >= 0.05:
                print("    %-24s %-6s n=%2d  d=%.2f  p=%.3f" %
                      (R["label"], t, v["n"], v["d"], v["p"]))

    P = tech_pooled()
    print("\n  POOLED over the %d same-model runs (this is Table II; pairs are"
          % P["solar"]["n_runs"])
    print("  (run, item), so rows are not independent -- descriptive only):")
    print("  %-7s%5s%16s%16s%9s%7s%10s%14s" %
          ("tech", "n", "base M(SD)", "+arb M(SD)", "delta", "d", "p",
           "never b/+arb"))
    for t, v in P.items():
        print("  %-7s%5d%9.2f (%5.2f)%9.2f (%5.2f)%+9.2f%7.2f%10.1e%7.0f%%/%4.0f%%" %
              (t, v["n"], v["bm"], v["bs"], v["em"], v["es"], v["delta"],
               v["d"], v["p"], v["never_baseline"], v["never_ef"]))


def sec_efpaper(E, D):
    hr("11. CROSS-PAPER -- EF paper rebased to the 50-pt epistemic score")
    if E is None:
        print("  epistemic_fortitude/ not found alongside this repo")
    else:
        print("%-24s%5s%17s%17s%9s%8s%11s   %s" %
              ("model (EF paper)", "n", "baseline M(SD)", "base+arb M(SD)", "delta", "d", "p",
               "60-pt base/+arb"))
        for label, s in E.items():
            print("%-24s%5d%10.2f (%5.2f)%10.2f (%5.2f)%+9.2f%8.2f%11.1e   %.2f / %.2f" %
                  (label, s["n"], s["bm"], s["bs"], s["em"], s["es"], s["delta"],
                   s["d"], s["p"], s["b60"], s["e60"]))
    print("\n  this study at A2 (one pressure turn -- the fair comparison point)")
    print("  %-24s%5s%17s%17s%9s%8s" %
          ("model", "n", "baseline M(SD)", "base+arb M(SD)", "delta", "d"))
    for R in D.values():
        c = R["misconception"]["A2"]
        print("  %-24s%5d%10.2f (%5.2f)%10.2f (%5.2f)%+9.2f%8.2f" %
              (R["label"], c["n"], c["bm"], c["bs"], c["em"], c["es"], c["delta"], c["d"]))


SECTIONS = {
    "integrity": sec_integrity, "headline": sec_headline, "trajectory": sec_trajectory,
    "decomposition": sec_decomp, "control": sec_control, "survival": sec_survival,
    "dimensions": sec_dims, "sgs": sec_sgs, "technology": sec_tech, "efpaper": sec_efpaper,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", metavar="PATH", help="also write machine-readable metrics")
    ap.add_argument("--section", choices=sorted(SECTIONS),
                    help="print one section instead of all")
    args = ap.parse_args()

    os.chdir(ROOT)
    D = collect()
    if not D:
        sys.exit("no runs found under logs/")
    K = decomposition()
    E = ef_paper_rebase()

    order = [args.section] if args.section else list(SECTIONS)
    for name in order:
        fn = SECTIONS[name]
        if name == "decomposition":
            fn(K)
        elif name == "efpaper":
            fn(E, D)
        else:
            fn(D)

    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(dict(runs=D, decomposition=K, ef_paper=E), indent=1, default=float),
            encoding="utf-8")
        print("\nwrote %s" % args.json)


if __name__ == "__main__":
    main()
