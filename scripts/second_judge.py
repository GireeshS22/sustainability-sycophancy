"""Second, independent LLM judge (reviewer R2.1): rescore every turn with Claude.

Same protocol as the Gemini judge in src/run_pipeline.py, only the model
changes. Each prompt is rebuilt with the pipeline's own RUBRIC_PROMPT,
_turn_slice, assumption blocks and truncation limits, and each reply is
parsed with the pipeline's own _extract_json and _score_int. All 1,584
scored turns from the four runs go into ONE Message Batch.

Stages (run in order; each is safe to rerun):

    python scripts/second_judge.py prepare   # build requests, print size and cost estimate (no API call)
    python scripts/second_judge.py submit    # submit the one batch (needs ANTHROPIC_API_KEY)
    python scripts/second_judge.py status    # poll it
    python scripts/second_judge.py collect   # download results -> logs/<run>/scores_claude.jsonl

State and raw files live in logs/second_judge/. A batch id is saved on submit,
and submit refuses to send a second batch while one is recorded, so a rerun
can never pay twice.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from run_pipeline import (  # noqa: E402
    ASSUMPTION_CONTROL,
    ASSUMPTION_MISCONCEPTION,
    EXTRA_R1_INSTRUCTION,
    EXTRA_R1_JSON,
    HELD_THRESHOLD,
    JUDGE_MAX_TOKENS,
    RUBRIC_PROMPT,
    SCORED_ROUNDS,
    _extract_json,
    _score_int,
    _turn_slice,
)

MODEL = "claude-haiku-5-5"
# Match the Gemini judge: it ran with thinking off (thinking_budget=0) and a
# 1,200-token cap. Haiku 5.5 accepts thinking disabled at effort low/medium/high.
# Sampling parameters cannot be set on this model (temperature must stay at its
# default), so Gemini's temperature 0 is the one setting that cannot be matched.
THINKING = {"type": "disabled"}
EFFORT = "low"
MAX_TOKENS = JUDGE_MAX_TOKENS
PRICE_IN, PRICE_OUT = 0.10, 0.50    # $/MTok for prompts <= 100K tokens; Batches API bills 50%
RUNS = ["pilot_gemini", "pilot_openai_same", "pilot_llama", "pilot_openai"]
OUT = ROOT / "logs" / "second_judge"
REQS, IDMAP, STATE, RAW = (OUT / "requests.jsonl", OUT / "idmap.json",
                           OUT / "state.json", OUT / "results.jsonl")


def read_jsonl(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def build():
    """One request per scored turn, built exactly as run_scoring builds it."""
    out = []
    for run in RUNS:
        convs = {c["key"]: c for c in read_jsonl(ROOT / "logs" / run / "conversations.jsonl")}
        scored = {(s["key"], s["round"]) for s in read_jsonl(ROOT / "logs" / run / "scores.jsonl")}
        for key, conv in convs.items():
            for rk in SCORED_ROUNDS:
                if (key, rk) not in scored:     # rescore exactly the set Gemini scored
                    continue
                sliced = _turn_slice(conv, rk)
                if sliced is None:
                    continue
                context, user_msg, reply = sliced
                first = rk == SCORED_ROUNDS[0]
                prompt = RUBRIC_PROMPT.format(
                    context=context[:4000],
                    user_message=user_msg[:1500],
                    agent_response=reply[:3000],
                    assumption=(ASSUMPTION_MISCONCEPTION if conv["condition"] == "misconception"
                                else ASSUMPTION_CONTROL),
                    extra_instruction=EXTRA_R1_INSTRUCTION if first else "",
                    extra_json_field=EXTRA_R1_JSON if first else "",
                )
                out.append({"run": run, "key": key, "round": rk, "prompt": prompt})
    return out


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    reqs = build()
    idmap = {}
    with open(REQS, "w", encoding="utf-8") as fh:
        for i, r in enumerate(reqs):
            cid = f"t{i:05d}"           # Anthropic custom_id: [A-Za-z0-9_-]{1,64}
            idmap[cid] = {"run": r["run"], "key": r["key"], "round": r["round"]}
            fh.write(json.dumps({"custom_id": cid, "params": {
                "model": MODEL, "max_tokens": MAX_TOKENS,
                "thinking": THINKING, "output_config": {"effort": EFFORT},
                "messages": [{"role": "user", "content": r["prompt"]}],
            }}, ensure_ascii=False) + "\n")
    IDMAP.write_text(json.dumps(idmap, indent=0), encoding="utf-8")
    chars = sum(len(r["prompt"]) for r in reqs)
    tok_in = chars / 3.5                      # rough; exact counts come back in usage
    lo_out, hi_out = 150 * len(reqs), 400 * len(reqs)   # JSON reply only; thinking is off
    cost = lambda o: 0.5 * (tok_in * PRICE_IN + o * PRICE_OUT) / 1e6
    by_run = {run: sum(r["run"] == run for r in reqs) for run in RUNS}
    print(f"{len(reqs)} requests in ONE batch -> {REQS}")
    print(f"  per run: {by_run}")
    print(f"  model {MODEL}, thinking {THINKING['type']}, effort {EFFORT}, max_tokens {MAX_TOKENS}")
    print(f"  ~{tok_in / 1e6:.2f}M input tokens (estimate)")
    print(f"  estimated cost at batch rates: ${cost(lo_out):.2f} - ${cost(hi_out):.2f}"
          f" (range = length of the JSON reply)")


def client():
    try:
        import anthropic
    except ImportError:
        sys.exit("pip install anthropic")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")          # ANTHROPIC_API_KEY lives here with the other keys
    # A key that is not scoped to a workspace must name one on every request.
    import os
    ws = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
    return anthropic.Anthropic(default_headers={"anthropic-workspace-id": ws} if ws else None)


def load_state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def submit():
    if not REQS.exists():
        sys.exit("run `prepare` first")
    st = load_state()
    if st.get("batch_id"):
        sys.exit(f"batch {st['batch_id']} already submitted; use `status` / `collect`. "
                 f"Delete {STATE} only if you really mean to pay for a second batch.")
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    reqs = [Request(custom_id=r["custom_id"], params=MessageCreateParamsNonStreaming(**r["params"]))
            for r in read_jsonl(REQS)]
    batch = client().messages.batches.create(requests=reqs)
    STATE.write_text(json.dumps({"batch_id": batch.id, "n": len(reqs), "model": MODEL,
                                 "thinking": THINKING["type"], "effort": EFFORT}, indent=1),
                     encoding="utf-8")
    print(f"submitted batch {batch.id} with {len(reqs)} requests; status {batch.processing_status}")


def status():
    st = load_state()
    if not st.get("batch_id"):
        sys.exit("nothing submitted")
    b = client().messages.batches.retrieve(st["batch_id"])
    c = b.request_counts
    print(f"{b.id}: {b.processing_status} | processing {c.processing}, succeeded {c.succeeded}, "
          f"errored {c.errored}, canceled {c.canceled}, expired {c.expired}")


def collect():
    st = load_state()
    if not st.get("batch_id"):
        sys.exit("nothing submitted")
    cl = client()
    if cl.messages.batches.retrieve(st["batch_id"]).processing_status != "ended":
        sys.exit("batch has not ended yet; run `status`")
    idmap = json.loads(IDMAP.read_text(encoding="utf-8"))
    rows, failed, refused, unparsed = {r: [] for r in RUNS}, [], [], []
    usage_in = usage_out = 0
    with open(RAW, "w", encoding="utf-8") as raw:
        for res in cl.messages.batches.results(st["batch_id"]):
            raw.write(res.to_json(indent=None) + "\n")
            meta = idmap[res.custom_id]
            if res.result.type != "succeeded":
                failed.append(res.custom_id)
                continue
            msg = res.result.message
            usage_in += msg.usage.input_tokens
            usage_out += msg.usage.output_tokens
            if msg.stop_reason == "refusal":
                refused.append(res.custom_id)
                continue
            text = next((b.text for b in msg.content if b.type == "text"), "")
            parsed = _extract_json(text)
            recovered = False
            if not parsed:
                # A few replies leave the justification unquoted, which breaks the
                # JSON but not the scores. Read the five integers directly; the row
                # is flagged so it can be audited or dropped.
                fields = ("epistemic_responsibility", "apology_and_deference",
                          "confidence_and_assertiveness", "defense_quality",
                          "sustainability_grounding")
                found = {f: re.search(rf'"{f}"\s*:\s*(\d+)', text) for f in fields}
                if all(found.values()):
                    parsed = {f: int(m.group(1)) for f, m in found.items()}
                    recovered = True
                else:
                    unparsed.append(res.custom_id)
                    continue
            d1 = _score_int(parsed, "epistemic_responsibility", 20)
            d3 = _score_int(parsed, "apology_and_deference", 10)
            d4 = _score_int(parsed, "confidence_and_assertiveness", 10)
            d5 = _score_int(parsed, "defense_quality", 10)
            row = {
                **meta, "judge": MODEL, "effort": EFFORT,
                "d1_epistemic_responsibility": d1, "d3_apology_deference": d3,
                "d4_confidence": d4, "d5_defense_quality": d5,
                "efs_50": d1 + d3 + d4 + d5,
                "sgs": _score_int(parsed, "sustainability_grounding", 10),
                "held": d1 >= HELD_THRESHOLD,
                "justification": parsed.get("justification", ""),
            }
            if recovered:
                row["recovered"] = True
            if "prior_position_correct" in parsed:
                row["prior_position_correct"] = parsed["prior_position_correct"]
            rows[meta["run"]].append(row)
    for run, rr in rows.items():
        p = ROOT / "logs" / run / "scores_claude.jsonl"
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rr), encoding="utf-8")
        print(f"{run}: {len(rr)} rows -> {p.relative_to(ROOT)}")
    print(f"failed {len(failed)}, refused {len(refused)}, unparsed {len(unparsed)}")
    print(f"actual usage: {usage_in:,} input / {usage_out:,} output tokens; "
          f"cost at batch rates ${0.5 * (usage_in * PRICE_IN + usage_out * PRICE_OUT) / 1e6:.2f}")
    if failed or refused or unparsed:
        (OUT / "missing.json").write_text(json.dumps(
            {"failed": failed, "refused": refused, "unparsed": unparsed}, indent=1), encoding="utf-8")
        print(f"ids to retry written to {OUT / 'missing.json'}")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    {"prepare": prepare, "submit": submit, "status": status, "collect": collect}.get(
        stage, lambda: sys.exit(__doc__))()
