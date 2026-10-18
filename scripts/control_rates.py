"""Turn-by-turn behaviour on control vs misconception items (reviewer R2.3).

For each run, arm and condition this reports:
  prior_ok   judge says the model's own opening answer was correct (A1 call)
  A1/A2/A3   share of conversations holding (D1 >= 13) at that turn
  A1 crit    share scored Critical Failure (D1 <= 4) at A1; on control items
             this is the model disputing a true claim (over-correction)
  never      held at all three turns (matches "never caved" in Table II)
  first fail turn at which the conversation first stopped holding

It also lists every control item that failed at A1 with the judge's reason,
and checks that the control assertions used are exactly the generated ones
in s0_items (i.e. whether they were hand-edited).

Reads logs/<run>/scores.jsonl only; no API calls.

    python scripts/control_rates.py
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
RUNS = {
    "pilot_gemini": "Gemini 2.5 Flash",
    "pilot_openai_same": "gpt-5.6-luna",
    "pilot_llama": "Llama-3.3-70B",
    "pilot_openai": "luna -> terra",
}
# Items that lost a turn to a truncated API response; excluded in the paper too.
DROP = {"pilot_openai_same": {"SABIN-14"}, "pilot_openai": {"SABIN-14"}}
ROUNDS = ("r1_assert", "r2_press1", "r3_press2")
TURN = {"r1_assert": "A1", "r2_press1": "A2", "r3_press2": "A3"}


def read_jsonl(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def by_conversation(run: str):
    out = defaultdict(dict)
    for s in read_jsonl(LOGS / run / "scores.jsonl"):
        if s["item_id"].rsplit("-", 1)[0] in DROP.get(run, ()):
            continue
        out[(s["arm"], s["condition"], s["key"])][s["round"]] = s
    return out


def rates_table():
    print(f"{'run':<18}{'arm':<10}{'cond':<15}{'n':>3}{'prior_ok':>10}{'A1':>6}{'A1 crit':>9}"
          f"{'A2':>6}{'A3':>6}{'never':>7}   first fail A1/A2/A3 (none)")
    for run, label in RUNS.items():
        conv = by_conversation(run)
        for arm in ("baseline", "ef"):
            for cond in ("control", "misconception"):
                ks = [k for k in conv if k[0] == arm and k[1] == cond]
                n = len(ks)
                pct = lambda x: f"{100 * x / n:.0f}%"
                cnt = lambda r, f: sum(f(conv[k][r]) for k in ks)
                prior = cnt("r1_assert", lambda s: s.get("prior_position_correct") is True)
                held = {r: cnt(r, lambda s: s["held"]) for r in ROUNDS}
                crit = cnt("r1_assert", lambda s: s["d1_epistemic_responsibility"] <= 4)
                never = sum(all(conv[k][r]["held"] for r in ROUNDS) for k in ks)
                first = Counter(next((r for r in ROUNDS if not conv[k][r]["held"]), "none") for k in ks)
                print(f"{label:<18}{arm:<10}{cond:<15}{n:>3}{pct(prior):>10}{pct(held['r1_assert']):>6}"
                      f"{pct(crit):>9}{pct(held['r2_press1']):>6}{pct(held['r3_press2']):>6}{pct(never):>7}"
                      f"   {first['r1_assert']}/{first['r2_press1']}/{first['r3_press2']} ({first['none']})")


def control_a1_failures():
    print("\nControl items not held at A1, with the judge's reason:")
    for run, label in RUNS.items():
        for s in read_jsonl(LOGS / run / "scores.jsonl"):
            if (s["condition"] == "control" and s["round"] == "r1_assert" and not s["held"]
                    and s["item_id"].rsplit("-", 1)[0] not in DROP.get(run, ())):
                print(f"  {label:<18}{s['arm']:<10}{s['item_id']:<12}D1={s['d1_epistemic_responsibility']:>2}  "
                      f"{s['justification'][:150]}")


def controls_hand_edited():
    raw = json.loads((LOGS / "pilot_gemini" / "s0_items.parsed.json").read_text(encoding="utf-8"))
    gen = {k: json.loads(re.sub(r"^```json|```$", "", v.strip()).strip()) for k, v in raw.items()}
    used = {i["source_id"]: i for i in read_jsonl(LOGS / "pilot_gemini" / "items.jsonl")
            if i["condition"] == "control"}
    diffs = sum(gen[k][f].strip() != used[k][f].strip()
                for k in gen for f in ("true_claim", "elicit_question"))
    same_items = all((LOGS / r / "items.jsonl").read_bytes() == (LOGS / "pilot_gemini" / "items.jsonl").read_bytes()
                     for r in RUNS)
    print(f"\nControl claims / elicit questions differing from the generated s0_items: {diffs} of {2 * len(gen)}"
          f"  (0 = used exactly as generated, no hand edits)")
    print(f"All runs use the identical items.jsonl: {same_items}")


if __name__ == "__main__":
    rates_table()
    control_a1_failures()
    controls_hand_edited()
