# Pre-registration: can an AI judge (Gemini) see the pembayang–maksud link?

**Written on 2026-10-26, before any API call.** Nothing below may be changed after seeing results;
any deviation must be reported as a deviation.

## Question
Can a large language model rate how strongly a pembayang hints at its maksud (including kiasan)
well enough to tell real pantun from fakes that **rhyme perfectly**?

## Permission
The user confirmed on 2026-10-26 that sending pantun to the Gemini API is allowed. On the free
tier Google may use inputs to improve its products.

## Sample (seed 42, fixed)
- Only pantun that have a **strictly rhyme-matched partner**: another pantun whose maksud ends in
  the same whole final syllable on lines 1~3 and 2~4 (e.g. *-yar/-yar*, *-ti/-ti*), with a different maksud.
- **300 fakes:** the pembayang of one pantun + the strictly rhyme-matched maksud of another, from the
  same book when possible. 150 from the traditional anthology, 150 from author collections.
- **300 real pantun:** different pantun from the same pool, 150 traditional + 150 author collections.
- No pembayang or maksud appears twice in the sample.
- Items are shuffled and sent in batches of 25. Gemini is **not told** that some are fakes.

## Model and prompt
- The newest stable **Gemini Flash** model available on the free tier at run time (exact name recorded
  in the results), temperature 0, JSON output. One run only.
- For each pantun Gemini returns: `score` 1–10 (how strongly the pembayang hints at / prepares the
  maksud), `link_type` (`word_echo`, `sound_echo`, `kiasan`, `same_topic`, `none`) and a one-sentence `hint`.
- Prompt text is saved in `src/gemini_judge.py`; all raw responses are saved.

## Analysis
1. AUC of Gemini's score, real vs fake, with a 95% bootstrap interval (1,000 resamples).
2. Same AUC per group (traditional vs author collections). A much higher AUC on traditional pantun
   would suggest **memorisation** of famous pantun rather than judgement.
3. On the same 600 items: AUC of plain LaBSE, multilingual-e5-large-instruct and the rhyme sound
   score, for comparison.
4. `link_type` counts for real vs fake.

## Amendment before any API call (2026-10-26)
A check of the first sample found 11 fakes whose borrowed maksud was a near-copy of the
pembayang's own maksud (another version of the same pantun, e.g. *Susah/Sukar jua pada yang tidak*),
which would make them secretly real. Partners whose maksud has LaBSE similarity ≥ 0.8 with the
pembayang's own maksud are now excluded, and the sample was rebuilt. No API call had been made.

## Amendment 2 (2026-10-26): free-tier limit and a local second judge
The free tier allows only 20 Gemini requests per day; the run stopped after 16 of 24 batches
(400 of 600 items). An interim analysis of those 400 items was computed automatically and seen.
- **Gemini** stays as planned: the remaining 200 items may be completed after the quota resets, with
  the same model and prompt. The interim result must be labelled as interim.
- **Second judge, added now:** Google's open **Gemma 4 12B** (`google/gemma-4-12B-it-qat-q4_0-gguf`,
  Q4_0, Apache-2.0) running locally in LM Studio (Vulkan, AMD RX 6700 XT), on **all 600 items**, with the
  **same prompt**, same batches of 25, temperature 0. Because LM Studio's structured output needs a JSON
  object at the top level, the answer list is wrapped as `{"answers": [...]}`; the fields are unchanged.
  Raw answers: `results/gemma_raw.jsonl`; analysis: `results/gemma_judge.json`.
- The same analysis and decision rule apply to each judge separately.

## Amendment 3 (2026-10-26): Gemma reasoning loop
Gemma 4 failed twice on the same batch (17 of 24): first its hidden reasoning filled the 16,384-token
context (empty answer), then with a 32,768-token context it was still generating after 30 minutes —
a reasoning loop, which can happen at temperature 0. Changes, for Gemma only and from batch 17 on:
- context 32,768 tokens; at most 12,000 generated tokens per request;
- a batch of 25 that fails is retried as batches of 5, and a failed batch of 5 as single items;
  items that still fail are recorded and counted as missing. Each saved record notes its batch size.
Update: with a 32,768-token context the model no longer fit in the GPU's 12 GB and ran far slower
(a batch of 25 timed out again; it then succeeded as 5 items). From item 406 on, the context is back
to 16,384 tokens with the 12,000-token output cap (prompt ≈ 3,000 + output ≤ 12,000 fits).
Batches 1–16 (400 items) were already complete under the original settings. An interim analysis of
those 400 items had been seen. The prompt and model are unchanged.

## Decision rule
Gemini "sees the link beyond rhyme" only if its overall AUC is **higher than every embedding model**
on the same items **and** the lower end of its 95% interval is above 0.5. Reported whatever happens.

---

## Result (added 2026-10-26, after running)

| AUC, real vs perfectly rhyming fakes | Items | AUC | 95% interval | Mean score real / fake | "kiasan" real / fake |
|---|---|---|---|---|---|
| **Gemma 4 12B** (local) | 600 | 0.500 | 0.45–0.54 | 3.96 / 3.97 | 96 / 107 |
| **Gemini 3.8 Flash** (interim) | 400 | 0.525 | 0.47–0.58 | 5.61 / 5.41 | 46 / 64 |
| LaBSE, same 600 items | 600 | 0.556 | 0.51–0.60 | | |
| e5-large-instruct, same 600 items | 600 | 0.537 | 0.49–0.58 | | |

By group (Gemma): traditional 0.546, author collections 0.454 (Gemini interim: 0.553 / 0.498) — no
clear memorisation effect. **Decision rule: neither judge "sees the link beyond rhyme".** Gemma: no
failed items. Gemini: 200 items not yet scored (free-tier limit). Notebook section 13, finding 12.
