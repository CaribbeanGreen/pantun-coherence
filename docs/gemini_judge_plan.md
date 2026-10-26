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

## Decision rule
Gemini "sees the link beyond rhyme" only if its overall AUC is **higher than every embedding model**
on the same items **and** the lower end of its 95% interval is above 0.5. Reported whatever happens.
