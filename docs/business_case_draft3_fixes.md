# Business Case Draft 3 — changes to sync the report with the system

Checked on 2026-10-27 against the prototype in this repository. Decision taken: **Option A —
keep all five models and budget a 16 GB server**, so every prototype number in the report stays true.
The 16 GB server price (**RM450/month**) is an assumption, added to Appendix A as A13.
The financial method was checked first: with RM250/month it reproduces every number in Draft 3 exactly.

Measured on the prototype (for the report's own claims):
- RAM with all five models loaded: **9.5 GB** (does not fit 8 GB). LaBSE 2.1, e5-large-instruct 2.6,
  Mesolitica 2.2, e5-base 1.4, MiniLM 1.2 GB.
- Time per pantun after loading: **0.47 s** with five models (target in PO3/SRNF02: ≤ 7 s).

---

## Part 1 — Server size (Option A)

| Where | Old | New |
|---|---|---|
| Executive Summary, "Options and recommendation" | "(RM24,667 at 8%; payback 4.0 years; ROI 24%)" | "(RM13,985 at 8%; payback 4.2 years; ROI 18%)" |
| Executive Summary, "Budget and time" | "RM79,161 including 10% contingency." | "RM80,261 including 10% contingency." |
| Table 10 | "Cloud server for development and testing: 5 months × RM250 — RM1,250" | "Cloud server (16 GB RAM) for development and testing: 5 months × RM450 — RM2,250" |
| Table 10 | "Contingency (10%) RM7,196" | "Contingency (10%) RM7,296" |
| Table 10 | "Total development budget (Year 0) RM79,161" | "Total development budget (Year 0) RM80,261" |
| Table 11 | "Cloud server (8 GB RAM, CPU): RM250 × 12 months — RM3,000" | "Cloud server (16 GB RAM, CPU): RM450 × 12 months — RM5,400" |
| Table 11 | "Fixed running cost per year RM26,504" | "Fixed running cost per year RM28,904" |
| Table 12, Option C limitations | "Highest cost (RM79,161)" | "Highest cost (RM80,261)" |
| Table 14, column C | Development RM79,161 · NPV RM24,667 · ROI 23.7% · Payback 4.0 years | Development **RM80,261** · NPV **RM13,985** · ROI **18.2%** · Payback **4.2 years** (Total income RM348,000 unchanged) |
| Table 17, Technical | "The web version needs a server with 8 GB RAM." | "The prototype runs all five models in 9.5 GB RAM and scores a pantun in 0.5 s, so the web version needs a server with 16 GB RAM." |
| Table 17, Economic | "Budget RM79,161." | "Budget RM80,261." |
| Table 21, Budget | "Development limit of RM79,161 including 10% contingency." | "Development limit of RM80,261 including 10% contingency." |
| R5 (risk register) response | "Use the two best models; cache results" | "16 GB server sized from measured use (9.5 GB); cache results; fall back to the two best models if needed" |
| Appendix B, Option C running cost | "Server RM3,000 + … = RM26,504 per year" | "Server RM5,400 + maintenance 44 days × RM366 = RM16,104 + expert check-up RM2,400 + corpus licence RM2,000 + marketing RM3,000 = RM28,904 per year" |
| Appendix A — add row | — | "A13 · Cloud server, 16 GB RAM · RM450/month · Quotes from two cloud providers in P1" |

### Table 13 — Cash flow for Option C (RM), replace all rows

| Item | Year 0 | Year 1 | Year 2 | Year 3 | Year 4 | Year 5 |
|---|---|---|---|---|---|---|
| Income | RM0 | RM18,000 | RM42,000 | RM72,000 | RM96,000 | RM120,000 |
| Costs | RM80,261 | RM32,504 | RM37,304 | RM43,304 | RM48,104 | RM52,904 |
| Net cash flow | −RM80,261 | −RM14,504 | RM4,696 | RM28,696 | RM47,896 | RM67,096 |
| Cumulative | −RM80,261 | −RM94,765 | −RM90,069 | −RM61,373 | −RM13,477 | RM53,619 |
| Discount factor (8%) | 1.000 | 0.926 | 0.857 | 0.794 | 0.735 | 0.681 |
| Discounted cash flow | −RM80,261 | −RM13,430 | RM4,026 | RM22,780 | RM35,205 | RM45,664 |

NPV = RM13,985. ROI = (348,000 − 294,381) ÷ 294,381 = 18.2%. Payback = 4 + 13,477 ÷ 67,096 = 4.2 years.

### Table 15 — Sensitivity of Option C's NPV, replace all rows

| Scenario | NPV | Payback |
|---|---|---|
| Base case | RM13,985 | 4.2 years |
| Adoption −30% | −RM48,911 | Not within 5 years |
| Adoption +30% | RM76,880 | 3.4 years |
| Price −20% (RM4,800) | −RM38,428 | Not within 5 years |
| Development cost +25% | −RM6,081 | 4.5 years |
| Discount rate 5% | RM26,949 | 4.2 years |
| Discount rate 12% | −RM531 | 4.2 years |

### "What this means" paragraph under Table 15 — replace the first two sentences

Old: "NPV becomes negative if sales are about 12% below plan or if the price falls by 20%. So Option C is
only a small financial gain, …"

New: "NPV becomes negative if sales are about 7% below plan, if the price falls by about 5%, if development
costs rise by 25% or if the discount rate is 12%. So Option C is only a small financial gain, …"
(The rest of the paragraph — client time value RM6,300 — is unchanged.)

### Conclusion
"It has the best weighted score and the only positive NPV. Both margins are small" — still true; no change.

---

## Part 2 — Other mismatches with the system

1. **Section 6, first sentence.** Old: "The working prototype has one screen for everyone." New: "The working
   prototype has two views: a Simple view for everyone (designed so that even children can use it) and an
   Advanced view for researchers."
2. **Section 1.3, "Evidence from our prototype".** Old: "(127 rows were rejected because they were not clean
   four-line pantun)". New: "(127 rows were rejected: 103 duplicates, 14 rows with merged cells and 10
   spreadsheet errors; a further 414 entries from one book were skipped because they were not clean four-line
   pantun)".
3. **Figure 3 caption.** Old: "\Measured on 5,445 held-out pantun. Source: … results/calibration.json.*"
   New: "AUC per method measured on all 10,907 pantun; combined-model figures ("can't tell", 78% correct)
   measured on 5,445 held-out pantun. Source: project files results/methods_comparison.csv and
   results/calibration.json." (Delete the stray "\" and "*".)
4. **References.** Remove *Dewan Bahasa dan Pustaka (2013), Kurik kundi merah saga* — this book was **not**
   in the corpus (its PDF was never extracted). If you want it, say "planned for a future corpus extension".
   Consider listing the 13 books actually used (they are the data sources; see `docs/related_work.md` and
   `data/pantun.csv` → `source` column).
5. **SRNF05** ("update or replace the transformer model through settings"): in the prototype the model list
   is in the code (`src/score.py`). Fine as a requirement for the web system; it is not marked [P].

---

## Part 3 — Report vs assignment instructions (not system issues)

1. Executive Summary: instructions ask for **2 paragraphs**; Draft 3 has six labelled short paragraphs.
2. Section numbering: instructions number **2. Introduction** (2.1 Background, 2.2 Problem, 2.3 MOV),
   3. Requirements … 7. Exhibits. Draft 3 starts at 1.
3. Team members: instructions require **photos**, designations and job descriptions — check Figure 2.
4. Page header: "Page 5 **of 4**" → correct total (30); "Final Report" → "Business Case".
5. References: delete the note "Before submission: complete the full author lists…" after completing them.
6. The assignment asks for the **Health & Wellness** industry (pantun given as the example). Optional: one
   sentence on how pantun learning supports wellbeing (cultural identity, language confidence).
