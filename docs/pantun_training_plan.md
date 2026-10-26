# Pre-registration: learning the pembayang–maksud link from pantun

**Written on 2026-10-25, before any training or results.** Nothing below may be changed after
seeing results; any deviation must be reported as a deviation.

## Question
Can a model learn the link between pembayang and maksud (including analogy) from real pantun,
well enough to recognise real pantun in **books it has never seen**, without relying on rhyme,
shared words or book style?

## Data split (by book, so test pantun are truly unseen)
- **Test books (3):** *Kumpulan Pantun Melayu* (Zainal Abidin Bakar, traditional),
  *Setaman Pantun Bertatah Bahasa* (Hilmi Rindu), *Pantun Berkait Mengejar Pelangi* (Ahmad Sarju).
- **Training books:** the other 10.
- **Duplicate control:** a test pantun is removed if its pembayang or its maksud is a near-copy of
  any training pantun's pembayang or maksud (cosine ≥ 0.95 with plain LaBSE, or identical text after
  normalising). Pantun appear in several books in slightly different versions.
- All training and testing happen on this computer only (private corpus).

## Training examples (from training books only)
- Positive: a real pantun (its own pembayang + maksud).
- Negatives: **2 rhyme-matched fakes** per pantun — the pembayang with another training pantun's
  maksud that has the same end sounds (lines 1~3, 2~4), drawn from the **same book** when possible
  (so neither rhyme nor book style can reveal the fake). Seeds 0 and 1.

## Models (settings fixed)
1. **Bi-encoder** — LaBSE fine-tuned with MultipleNegativesRankingLoss on (pembayang, real maksud,
   rhyme-matched maksud) triplets (first negative only). 1 epoch, batch 32, lr 2e-5, warm-up 10%,
   seed 42, max length 64, token-embedding layer frozen.
2. **Cross-encoder** — `FacebookAI/xlm-roberta-base` reading pembayang and maksud together, one
   output, BinaryCrossEntropyLoss on all positives and negatives (1 : 2). 1 epoch, batch 16,
   lr 2e-5, warm-up 10%, seed 42, max length 96, token-embedding layer frozen.
- Reference: **plain LaBSE** (best meaning model in Phase 3), not trained.
- No other settings are tried. Nothing is tuned on the test books.

## Tests (on the test books, after duplicate control)
Each model scores every pair; AUC = chance that a real pantun outscores a fake.
1. Real vs **random** fakes (3 seeds, partners from the test set)
2. Real vs **rhyme-matched** fakes
3. Real vs **same-book** fakes (3 seeds)
4. Real vs random fakes, only pantun with **no shared words** between halves
Results are also reported per test book (traditional vs modern).

## Decision rule
A trained model "learned something beyond shortcuts" only if it beats plain LaBSE on **all four**
tests. Whatever happens, both models are reported in the notebook and the report.

---

## Result (added 2026-10-25, after running; the plan above is unchanged)

Train: 7,849 pantun (10 books). Test: 2,973 pantun (3 unseen books) after removing 85 near-duplicates.
Bi-encoder trained in 13.7 min, cross-encoder in 30.5 min (CPU).

| AUC on unseen books | Plain LaBSE | LaBSE trained on pantun | Cross-encoder (XLM-R) |
|---|---|---|---|
| 1. Real vs random fakes | 0.645 | 0.919 | 0.704 |
| 2. Real vs rhyme-matched fakes | 0.626 | 0.713 | 0.656 |
| 3. Real vs same-book fakes | 0.628 | 0.910 | 0.695 |
| 4. No shared words (vs random) | 0.560 | 0.911 | 0.661 |

**Pre-registered decision rule:** both trained models beat plain LaBSE on all four tests →
"learned something beyond shortcuts".

### Flaw in the plan (reported as a deviation)
Tests 1, 3 and 4 use **random** fakes, which almost never rhyme, so they can be passed by hearing
end rhyme alone. Training also exposed the models to many non-rhyming maksud (other examples in
each batch). The decision rule therefore did not rule out the rhyme shortcut.

### Post-hoc diagnostics (added after seeing the results, NOT pre-registered)
`python -m src.pantun_training diagnose` → `results/pantun_training_diagnostics.json`

| AUC on unseen books | Plain LaBSE | LaBSE trained on pantun | Cross-encoder |
|---|---|---|---|
| Real vs random, **line-end words removed** (2,973 pantun) | 0.633 | 0.612 | 0.621 |
| Real vs fakes matching the **whole final syllable**, same book (258 pairs) | 0.561 | 0.457 | 0.558 |

When rhyme is removed, the gain disappears: the trained models are no better than plain LaBSE.
**Conclusion: training on pantun taught the models to recognise end rhyme, not the
analogical meaning link.** The second diagnostic has only 258 pairs, so it is uncertain on its
own; the first is large and points the same way.
