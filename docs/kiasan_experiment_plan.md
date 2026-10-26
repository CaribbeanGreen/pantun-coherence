# Pre-registration: teaching a model figurative language (kiasan) with peribahasa

**Written on 2026-10-25, before any training or results.** Nothing below may be changed after
seeing results; any deviation must be reported as a deviation.

## Question
Does fine-tuning a sentence-embedding model on Malay peribahasa (figurative phrase ↔ plain
meaning) make it better at detecting the pembayang–maksud link in pantun?

## Training data
- `mesolitica/peribahasa-instructions` (Hugging Face): 8,321 training pairs (`train.json`),
  257 held-out pairs (`test.json`). No licence stated: used locally for research only, cited,
  not redistributed.
- **No pantun are used for training.** The private pantun library is only used for testing.

## Model and settings (fixed)
- Base model: `sentence-transformers/LaBSE` (best meaning model in Phase 3).
- Loss: MultipleNegativesRankingLoss (each phrase must be closest to its own meaning among the batch).
- 1 epoch, batch size 32, learning rate 2e-5, 10% warm-up, seed 42, max sequence length 64.
- Token-embedding layer frozen (LaBSE's 501k-word vocabulary is most of its size; with 8k pairs
  only the transformer layers are trained). CPU only.
- No other settings are tried. No tuning on pantun.

## Checks
1. **Did it learn peribahasa?** On the 257 held-out pairs: for each phrase, is its own meaning
   the most similar of the 257 meanings? Report top-1 accuracy, before vs after.
2. **Does it help with pantun?** Compare plain LaBSE vs fine-tuned LaBSE on the same pantun:
   - AUC, real vs random pairing (10 seeds, as in Phase 3)
   - AUC, real vs **rhyme-matched** fake (pembayang + another pantun's maksud with the same
     end sounds, so rhyme cannot give the answer away)
   - AUC on pantun with **no shared words** between halves (real vs random)
3. **Leakage control.** Pantun whose maksud contains a training peribahasa (≥ 3 words, exact
   match after lower-casing and removing punctuation) are excluded from all pantun tests, since the
   model would have seen that exact phrase. Results are reported for the remaining pantun.

## Decision rule
The fine-tuned model "helps" only if its AUC is higher than plain LaBSE's on **both** the random
and the rhyme-matched test. Whatever happens, the result is reported in the notebook and the report.

---

## Result (added 2026-10-25, after running; the plan above is unchanged)

| | Plain LaBSE | LaBSE + peribahasa |
|---|---|---|
| Peribahasa held-out top-1 (257 pairs) | 0.296 | 0.354 |
| Pantun AUC, real vs random | 0.607 | 0.599 |
| Pantun AUC, real vs rhyme-matched | 0.588 | 0.581 |
| Pantun AUC, no shared words | 0.565 | 0.558 |

9,582 pantun tested (1,325 excluded by the leakage control). Training: 261 steps, 11.9 min on CPU,
final training loss 1.48. **Decision rule: does not help.** No deviations from the plan.
Full numbers: `results/kiasan_experiment.json`; notebook section 11.
