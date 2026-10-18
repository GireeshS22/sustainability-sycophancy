# Review Response — To-Do

Both reviewers recommend **Accept with Minor Revision**. Reviewer 1 gives two short
points: figures and the abstract. Reviewer 2 gives eight specific weaknesses. This
document lists every point, what we already have, and what still needs to be done.

**Hard constraint:** the manuscript is already at the IEEE 6-page limit
(`manuscript/main.log`: 6 pages). Every addition to the text needs a matching
cut somewhere else, or it has to go to supplementary material or the public repo.
Check the venue's camera-ready rules on extra pages and supplementary files
before starting T4.

## Summary

| ID | Reviewer | Point | Kind of work | Effort | Status |
|----|----------|-------|--------------|--------|--------|
| T1 | R2 | Single LLM judge, no human validation | New experiment + text | High | ☐ |
| T2 | R2 | Justify the 13/20 "held" threshold | Free re-analysis + text | Low | ☑ done (scripts/threshold_sensitivity.py) |
| T3 | R2 | Control condition is confusing | Text | Low | ☑ done (scripts/control_rates.py) |
| T4 | R2 | Publish exact prompts and router keywords | Supplementary / repo | Medium | ☑ repo line (xxx); repo still to create |
| T5 | R2 | Why grounding is kept outside the 50-point total | Text | Low | ☑ done |
| T6 | R2 | Small claim pool (33 claims, one report) | Text (reframe) | Low | ☑ text done |
| T7 | R2 | Only one cross-model arbiter configuration | Text (optional run) | Low–Medium | ☑ text done, no new runs |
| T8 | R2 | Confirm the name "gpt-5.6-luna" | Verify + footnote | Low | ☑ done ("OpenAI's" at first mention, no footnote) |
| T9 | R1 | Abstract should be more concise | Rewrite | Low | ☐ |
| T10 | R1 | Figure quality needs improvement | Figure polish | Medium | ☐ |
| T11 | — | Write the response letter | Writing | Medium | ☐ |

Suggested order: T8 → T2 → T1 (start the run early, it is the only one that
waits on an API) → T3, T5, T6, T7 → T4 → T10 → T9 last (the abstract should
reflect any new numbers from T1/T2) → T11.

---

## T1. Second judge and/or human agreement (R2, the main weakness)

**Comment.** All scoring uses one judge, `gemini-2.5-flash`, and in some runs it
shares a model family with the system under test. Add a human agreement study or
at least a second independent judge.

**Where we stand.** The judge is fixed at `gemini-2.5-flash` for all four runs
(`src/run_pipeline.py:91`). In the Gemini run the judge is not just the same
family but the *same model* as the system under test — the Limitations paragraph
(`main.tex:514`) says "shares a model family", which undersells it. A human
reliability gate was planned (ICC ≥ 0.7 on the epistemic score, weighted κ ≥ 0.6
on D1, ~100 hand-scored turns; `docs/results.md:684`) but never run.

**Actions.**
- [ ] Re-judge all 1,584 scored turns with a second judge from a family that is
      not under test in any run. A Claude model is the cleanest choice, since no
      run generates with it. Same rubric, same JSON schema, temperature 0.
      The pipeline already takes `--judge-model` / `--judge-provider`.
- [ ] Report judge–judge agreement: ICC on the epistemic score, weighted κ on D1,
      and agreement on the held/not-held call at 13.
- [ ] Re-run the headline comparisons (arbiter − baseline, 31%/69% split) under
      the second judge. If the conclusions hold, one sentence plus a small table
      row or footnote is enough. If they move, that is a bigger rewrite — flag it
      before writing.
- [ ] Specifically check whether the Gemini run's gains shrink under the
      independent judge (self-preference check).
- [x] Human-eval app built: `streamlit/` (EF protocol, fixed stratified sample
      of 96 turns in `streamlit/data/sample_manifest.json`, gate checked in the
      Analysis tab and by `streamlit/analyze_agreement.py`).
- [ ] Hand-score the 96 turns (at least one rater; a second rater on the same
      set gives inter-rater agreement). Scores land in
      `streamlit/data/human_scores.jsonl`.
- [ ] Fix the Limitations wording: "same model" for the Gemini run, and replace
      "no human agreement study" with what we now have.

## T2. Justify the 13/20 holding threshold (R2)

**Comment.** Justify the threshold for "held".

**Where we stand.** The reason exists only in a code comment
(`src/run_pipeline.py:977`): 13 is the lower edge of the rubric's own
"right action, minor flaws" band (13–16); 5–12 is the "caves" band. The scope doc
planned a ≥10 / ≥17 sensitivity check (`docs/scope.md:736`) that was never run.

**Actions.**
- [ ] Run the survival analysis at thresholds 10 and 17 (no API calls — just
      `scripts/analysis.py` on existing scores).
- [ ] In Methods (`main.tex:275`), add one sentence: the threshold is the rubric's
      own band boundary, not a tuned value, and it is used only for
      time-to-failure.
- [ ] Add one sentence with the sensitivity result (e.g. "log-rank conclusions
      are unchanged at 10 and 17").

## T3. Control condition clarity (R2)

**Comment.** Unclear what "held a correct position" means on control items, where
the user asserts the true claim and then expresses doubt with the fixed pressure
wording.

**Where we stand.** Methods (`main.tex:222–241`) says the pressure wording is
identical across conditions but never spells out what that looks like on a
control item. The confusing phrase recurs at `main.tex:378` and `main.tex:465`.

**Actions.**
- [ ] Read two or three control conversations in `logs/` to confirm what actually
      happens (does the model agree at A1, and does the pressure push it away from
      the true claim?).
- [ ] Add two sentences to the Protocol paragraph walking through a control item:
      the user states the true claim, the model agrees, then the user doubts and
      appeals to authority. "Held" means the model keeps the true position;
      "caved" means it drops a correct answer it had just endorsed.
- [ ] Make the wording at `main.tex:378` and `main.tex:465` match.

## T4. Prompt transparency (R2)

**Comment.** Give the exact prompts for baseline, arbiter, router and judge
rubric; list the router keywords.

**Where we stand.** All prompts are in `src/run_pipeline.py` (judge rubric around
lines 990–1160). The router is 16 strong + 21 soft keywords
(`src/run_pipeline.py:210–224`). None of this is in the paper, and there is no
repo/data link in the manuscript.

**Actions.**
- [ ] Decide where it goes: supplementary PDF (if the venue allows) or a public
      repo/Zenodo link. Six pages will not hold full prompts.
- [ ] Prepare a clean supplementary file: baseline prompt, arbiter prompt, judge
      rubric verbatim, router keyword lists and tier logic, the two pressure turns.
- [ ] In the paper, add the keyword lists compactly (a footnote or a few lines)
      if space allows — the reviewer asked for them directly — and one sentence
      pointing to the full prompts.
- [ ] Note in Methods that the router never fell through to tier 3 (report the
      miss count from the run logs) so the keyword list is the whole router.

## T5. Grounding score kept out of the total (R2)

**Comment.** Explain why grounding is reported separately and never added to the
50-point total.

**Where we stand.** `main.tex:271–275` gives one reason (comparability with the
published 50-point scale). The rubric itself (`src/run_pipeline.py:1154`) states
the second reason: grounding measures a different thing — a response can be well
grounded and still capitulate, or hold firm with no evidence.

**Actions.**
- [ ] Add that second reason in one sentence: the epistemic score measures
      whether the model kept its position; grounding measures what evidence it
      used, and the two can come apart. Adding them would hide that.

## T6. Small claim pool (R2)

**Comment.** 33 claims from one Columbia Law report are not representative of
public discourse. Acknowledge, or present as a case study.

**Where we stand.** Limitations (`main.tex:516–520`) already acknowledges this.

**Actions.**
- [x] "Case study" framing in abstract, introduction and Limitations (revision1, in 
ev{}).
- [x] Stated that every misconception turn is the report's verbatim public quote (checked 33/33).
- [x] Future-work line on broader claim sets via the CARDS taxonomy (Coan et al. 2021, verified).
- [ ] Optional, deferred: FrugalAI coverage check (what share of public claims the 33 cover).

## T7. Arbiter model ablation has one configuration (R2)

**Comment.** Only one different arbiter model was tested, so heterogeneity cannot
be separated from general robustness. Recommend more configurations as future
work.

**Where we stand.** Already acknowledged (`main.tex:505–508`). The reviewer is
asking for a future-work line, not a new run.

**Actions.**
- [ ] Add a future-work sentence naming the grid: each primary paired with each
      other arbiter model.
- [ ] *Optional:* one extra configuration (e.g. Gemini primary with a luna or
      Claude arbiter) would cost little and make the 31/69 split less dependent on
      a single pairing. Only do this if T1 finishes with time to spare.

## T8. Model name "gpt-5.6-luna" (R2)

**Comment.** Verify that "gpt-5.6-luna" is the correct model name/version.

**Where we stand.** Verified from the raw API responses in `logs/*/*.output.jsonl`:
931 responses report `"model": "gpt-5.6-luna"` and 134 report `"gpt-5.6-terra"`
(the ablation arbiter), all created 2026-08-08. The names are correct. (An
earlier count of 2,126 / 268 double-counted request files; do not use it.)

**Actions.**
- [ ] Add a footnote at first mention giving the provider, the API model
      identifier as returned, and the access dates, so the reader can tell it is
      the exact identifier and not a typo.
- [x] Access date from the API `created` timestamps: 2026-08-08 (UTC).

## T9. Concise abstract (R1)

**Comment.** The abstract should be written concisely.

**Where we stand.** About 270 words (`main.tex:66–91`), with many numbers.

**Actions.**
- [ ] Cut to about 150–180 words. Keep: problem, setup in one sentence, the three
      headline findings (baseline caving, arbiter gain, 31/69 split), one line on
      control items. Move per-model numbers to the results.
- [ ] Do this after T1/T2 so the numbers are final.

## T10. Figure quality (R1)

**Comment.** "Ok, need improvement." No specifics.

**Where we stand.** Three figures: `method.pdf` and `example.pdf` (draw.io),
`trajectory.pdf` (matplotlib, `scripts/make_figure.py`).

**Actions.**
- [ ] Check every figure at print size: smallest font ≥ 8 pt, lines readable,
      no overlap.
- [ ] Make sure all three are vector PDFs (not the PNG) and readable in grayscale.
- [ ] `trajectory`: larger tick and legend fonts, consistent colours for
      baseline/arbiter across all panels.
- [ ] `example`: verbatim text is likely small at column width — check
      legibility, abridge further if needed.
- [ ] `method`: align fonts and colours with the other two figures.

## T11. Response letter

- [ ] Write a point-by-point response: thank the reviewers, quote each comment,
      say what changed and where (section and page).
- [ ] Be honest where we did not fully do what was asked (e.g. if no human study).
- [ ] Rebuild `main.pdf`, confirm it is still ≤ 6 pages, and produce a
      changes-marked version if the venue asks for one.
