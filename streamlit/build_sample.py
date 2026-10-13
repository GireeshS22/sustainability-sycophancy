"""Draw the fixed human-validation sample and write data/sample_manifest.json.

Stratified: 4 runs x 2 arms x 2 conditions x 3 scored turns = 48 cells, with
PER_CELL turns drawn from each, giving 96 turns. Within a cell no claim
(source_id) is drawn twice, no conversation contributes more than one turn,
and a turn is only drawn from a conversation that
finished all four turns. Every rater scores this same set, which is what makes
inter-rater agreement computable.

Run once; refuses to overwrite an existing manifest unless --force is given,
because raters' scores are keyed to it.

    python build_sample.py
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone

from common import MANIFEST_FILE, RUNS, SCORED_ROUNDS, complete, conversations, judge_scores

SEED = 20261013
PER_CELL = 2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if MANIFEST_FILE.exists() and not args.force:
        raise SystemExit(f"{MANIFEST_FILE} exists; scores are keyed to it. Use --force to replace.")

    rng = random.Random(SEED)
    samples = []
    for run in RUNS:
        convs = conversations(run)
        scored = judge_scores(run)
        for arm in ("baseline", "ef"):
            for condition in ("misconception", "control"):
                pool = sorted(
                    c["key"] for c in convs.values()
                    if c["arm"] == arm and c["condition"] == condition and complete(c)
                )
                used = set()  # one turn per conversation, so a rater never sees its later turns
                for rk in SCORED_ROUNDS:
                    cell = [k for k in pool if (k, rk) in scored and k not in used]
                    rng.shuffle(cell)
                    picked, seen = [], set()
                    for k in cell:
                        src = convs[k]["source_id"]
                        if src in seen:
                            continue
                        seen.add(src)
                        picked.append(k)
                        used.add(k)
                        if len(picked) == PER_CELL:
                            break
                    samples += [{"run": run, "key": k, "round": rk} for k in picked]

    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.write_text(json.dumps({
        "seed": SEED,
        "per_cell": PER_CELL,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "n": len(samples),
        "samples": samples,
    }, indent=1), encoding="utf-8")
    print(f"wrote {len(samples)} samples to {MANIFEST_FILE}")


if __name__ == "__main__":
    main()
