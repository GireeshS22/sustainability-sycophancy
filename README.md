# Sustainability Sycophancy — Run Guide

This is a runbook. Follow the steps in order. Everything runs from **one
command**, and that command is safe to run over and over — it always picks up
where it stopped.

You do not need to understand the research to run this. If something looks
wrong, there is a list at the bottom of things to report. Don't try to fix the
experiment design — just report and stop.

---

## Step 1 — Install

You need Python 3.10 or newer.

```bash
cd sustainability-sycophancy
pip install -r requirements.txt
```

## Step 2 — Add your API key

```bash
cp .env.example .env
```

Open `.env` in a text editor and paste your Gemini key after `GEMINI_API_KEY=`.
Get a free key at <https://aistudio.google.com/apikey>.

```
GEMINI_API_KEY=AIza...
```

Leave `TOGETHER_API_KEY` blank. You won't need it.

The same file also holds the provider, the model names and the polling interval.
**Leave all of those exactly as they are** unless Gireesh tells you otherwise —
they are already set correctly for this run.

## Step 3 — Download the data

```bash
python scripts/fetch_data.py
```

Downloads the Sabin Center report and extracts the 33 claims. Safe to re-run —
anything already on disk is skipped.

It must end with `claims extracted : 33/33`. If it doesn't, stop and report it.

## Step 4 — Small test run (do this first)

This uses only 3 claims, so you can confirm everything works before running the
full thing.

```bash
python src/run_pipeline.py --limit 3 --run-name test3
```

Wait for it to finish and print a table. If it does, go to Step 5.

## Step 5 — Full run

```bash
python src/run_pipeline.py
```

That's it. Leave it running.

---

## What to expect while it runs

Every LLM call goes through the **Gemini Batch API**. The script submits a job,
then waits and prints the job's state **every 2 minutes**:

```
provider=gemini  model=gemini-2.5-flash  judge=gemini-2.5-flash  poll=120s
[s0_items] 33 requests
  [s0_items] uploading 33 requests
  [s0_items] job=batches/xyz123
  [s0_items] state=JOB_STATE_PENDING
  [s0_items] state=JOB_STATE_RUNNING
  [s0_items] state=JOB_STATE_SUCCEEDED
[s0_items] done, 33/33 ok
[items] built 66 items (0 claims skipped)

66 items x 2 arms = 132 conversations

[r0_elicit] 132 requests
  ...
```

**Batch jobs are not instant.** Each of the six stages can take anywhere from a
few minutes to a few hours — that's normal for a batch API, not a bug. The whole
run may take several hours. Just let it sit.

If the terminal looks frozen on `state=JOB_STATE_RUNNING`, it is working. Leave
it.

## What the final table means

```
======================================================================================
arm       condition         n  score@assert  score@final   lost  evidence  never caved
--------------------------------------------------------------------------------------
baseline  misconception    33          31.4         19.8   11.6       5.2          31%
baseline  control          33          38.1         34.0    4.1       5.8          78%
ef        misconception    33          41.7         40.2    1.5       6.9          79%
ef        control          33          40.9         39.4    1.5       7.1          80%
======================================================================================
```

*(Those numbers are made up, just to show the shape.)*

- **score@assert** — the main score, out of 50. How well the model held its
  ground when the user first made the claim
- **score@final** — the same score after being pushed twice
- **lost** — points dropped between the two. Bigger = caved harder
- **evidence** — sustainability grounding, out of 10, scored separately. Whether
  the answer used real engineering figures. **Never added into the main score**
- **never caved** — held the right position on all three turns

The rows that matter: `ef / misconception` should lose far fewer points than
`baseline / misconception`. The two `control` rows are a safety check — they
should *not* get worse when the fix is switched on.

Send Gireesh this table when the run finishes.

---

## If it stops or crashes

**Run the exact same command again.**

```bash
python src/run_pipeline.py
```

Nothing gets redone and nothing gets billed twice. Finished stages are skipped
instantly. A batch job that was already submitted gets picked back up, not
resubmitted.

To see how far it got without spending anything:

```bash
python src/run_pipeline.py --status
```

### Common problems

| What you see | What to do |
| --- | --- |
| `GEMINI_API_KEY not set` | Step 2 didn't work — check `.env` has your key |
| `PROVIDER is '...', must be one of` | You edited the `PROVIDER` line in `.env`. Set it back to `gemini` |
| `sabin_claims.json not found` | Run step 3 — `python scripts/fetch_data.py` |
| Terminal stuck on `JOB_STATE_RUNNING` | Nothing is wrong. It only prints every 2 minutes, so long silences are expected. Wait. |
| Crashed, closed laptop, lost connection | Run the same command again |
| `batch ended JOB_STATE_FAILED` | Run the same command again once. If it fails a second time, stop and report |
| `item set changed (abc -> def)` | You reused a run name with a different `--limit`. Use `--run-name something_new` |

**Never delete `logs/<run-name>/state.json` while a run is in progress.** That is
the file that remembers what's already done.

If you truly need to start over from scratch, delete the whole folder:

```bash
rm -rf logs/pilot_gemini
```

---

## Where the results go

Everything is written to `logs/pilot_gemini/`:

| File | What it is |
| --- | --- |
| `items.jsonl` | The 66 test items |
| `conversations.jsonl` | Every conversation, all turns |
| `scores.jsonl` | The rubric scores behind the summary table — 3 rows per conversation, one per scored turn |
| `state.json` | Resume bookkeeping — don't touch |
| `*.input.jsonl` / `*.output.jsonl` | Raw batch files, keep them |

Zip the whole `logs/pilot_gemini/` folder and send it over when the run is done.

---

## Stop and report if you see any of these

Don't try to fix these yourself.

1. The `never caved` column is all 0% or all 100%
2. Every score is nearly identical across all four rows, or every `evidence` is 9–10
3. More than about 5 items failed after retries (look for `WARNING: N unrecoverable`)
4. A stage says `done, 40/396 ok` — a lot of missing responses
5. `[score] wrote N rows` where N is well under 3× the conversation count
6. Any line saying `WARNING: N/132 replies end mid-sentence`
7. `tier3_misses` is a large number in the `[r2_press1]` / `[r3_press2]` lines
8. A batch job fails twice in a row
9. Anything in `items.jsonl` reads as nonsense or obviously false

---

## Notes for whoever picks this up next

Not needed for the run above.

```bash
# Progress check, costs nothing
python src/run_pipeline.py --status

# Scaled runs use Together's Batch API instead
python src/run_pipeline.py --provider together

# Separate run folders never interfere
python src/run_pipeline.py --run-name experiment_2
```

Project layout:

```
sustainability-sycophancy/
├── src/run_pipeline.py            # the whole pipeline
├── data/interim/sabin_claims.json # the 33 source claims
├── logs/<run-name>/               # all outputs
├── docs/scope.md                  # research plan
├── requirements.txt
└── .env.example
```

Analysis (metrics, significance tests, figures) is deliberately not in this
pipeline. It gets built on top of `scores.jsonl` after the first real run.
