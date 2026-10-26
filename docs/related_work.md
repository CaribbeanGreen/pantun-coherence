# Related work and model choice

Literature check done on 2026-10-24 to (a) find prior computational work on pantun and
(b) choose embedding models with published evidence for Malay. "Checked" = we read the
paper's results; "abstract/snippet" = only the abstract or a search summary was seen —
verify before citing details.

## 1. Pantun and the pembayang–maksud link

| Source | What it did | Relevance | Checked |
|---|---|---|---|
| [Pantun sebagai Bahan dan Tradisi Logik Melayu Berdasarkan Hubungan Makna Pembayang-Maksud](https://www.researchgate.net/publication/353454581_Pantun_sebagai_Bahan_dan_Tradisi_Logik_Melayu_Berdasarkan_Hubungan_Makna_Pembayang-Maksud) | Humanities study: the pembayang–maksud link as Malay analogical reasoning | Theory for *why* the halves connect (analogy, not literal similarity) | snippet |
| [Poetry Classification Using Support Vector Machines](https://www.academia.edu/51918702/Poetry_Classification_Using_Support_Vector_Machines) (J. Computer Science, 2012) | SVM + TF-IDF to classify 1,500 pantun into 10 themes | Earliest ML on pantun; theme, not coherence | snippet |
| [Siallagan & Alfina (2023), Poetry Generation for Indonesian Pantun: SeqGAN vs GPT-2](https://jiki.cs.ui.ac.id/index.php/jiki/article/view/1113), JIKI 16(1) | Generates pantun; evaluates **structure and rhyme** automatically | Supports evaluating rhyme (a-b-a-b) as a separate dimension | snippet |
| [Sampiran dataset](https://github.com/ir-nlp-csui/sampiran) | 7.8K Indonesian pantun filtered to a-b-a-b rhyme and 8–12 syllables | Rhyme is treated as a defining rule of pantun | snippet |
| [Malay 'Pantun': End Syllable Search System](https://www.researchgate.net/publication/373015723_Malay_'Pantun'_End_Syllable_Search_System_as_An_Alternative_to_Facilitate_the_Search_of_Rhyme) | Rhyme (end-syllable) search tool, 14,465 syllables | End-syllable matching as the unit of pantun rhyme | snippet |

**Gap:** we found no study that measures the *meaning* relation between pembayang and
maksud computationally. This project addresses that gap.

## 2. Embeddings for figurative / poetic text

- Jannidis et al. ([JCLS](https://tuprints.ulb.tu-darmstadt.de/23259/1/jcls-116-ehrmanntraut.pdf)) evaluate
  sentence embeddings on short poetic texts and note that figurative language and archaic words make
  semantic similarity especially hard. (snippet)
- Ties in with our finding: embeddings pick up shared words and surface wording more than the
  analogical link the humanities literature describes.

## 3. Which embedding model for Malay?

**SEA-BED** — Ponwitayarat et al., *SEA-BED: How Do Embedding Models Represent Southeast Asian
Languages?* ([arXiv:2508.12243](https://arxiv.org/abs/2508.12243), AI Singapore et al.). **Checked**
(Table 5, Malay = `zsm`, average over 19 datasets):

| Model | Malay score |
|---|---|
| multilingual-e5-large-instruct (560M) | **84.60** |
| bge-multilingual-gemma2 (9B) | 83.38 |
| LaBSE (471M) | 82.87 |
| bge-m3 (568M) | 82.54 |
| Qwen3-Embedding-8B | 82.39 |
| multilingual-e5-large (560M) | 80.10 |
| multilingual-MiniLM-L12 (118M) | 69.58 |

Key points: no model is best for every language; SEA-specific *generative* LLMs
(SEA-LION, Sailor) are poor embedders; multilingual-e5-large-instruct is best overall and for Malay.

**Mesolitica** — Zolkepli et al. (2024), *Multi-Lingual Malaysian Embedding: Leveraging Large
Language Models for Semantic Representations* ([arXiv:2402.03053](https://arxiv.org/abs/2402.03053)).
Llama2-based embedding models fine-tuned on Malaysian pairs; the 600M model beat OpenAI
text-embedding-ada-002 on Malay semantic-similarity recall@k. (abstract) Not included in SEA-BED.

## 4. Decisions taken (before seeing the new results)

| Model | Why |
|---|---|
| paraphrase-multilingual-MiniLM-L12-v2 | Project brief; small baseline (weakest for Malay in SEA-BED) |
| LaBSE | Project brief; 3rd for Malay in SEA-BED |
| multilingual-e5-base | Project brief |
| **multilingual-e5-large-instruct** | **Added: best for Malay in SEA-BED** |
| **mesolitica/llama2-embedding-600m-8k-contrastive** | **Added: Malaysian-specific; best similarity model in its paper** |
| Rhyme rule (`src/rhyme.py`) | Added: pantun links its halves by sound (a-b-a-b); embeddings cannot see it. Reported separately from meaning |

Not used: Qwen3-Embedding-8B / bge-multilingual-gemma2 (8–9B parameters, too large for CPU);
other Mesolitica models (smaller or less documented).

All models are reported, whatever their result.

## 5. Traditional criteria of a good pantun (used in `src/criteria.py`)

| Criterion | Source | Checked |
|---|---|---|
| Middle and end rhyme a-b-a-b (*rima tengah dan rima akhir ialah a,b,a,b*) | Johari Yahaya (2015), *Pantun Peribahasa Melayu: Analisis daripada Perspektif Teori Pengkaedahan Melayu*, MA thesis, Universiti Sains Malaysia, p. 15 ([PDF](http://eprints.usm.my/30138/1/JOHARI_YAHYA.pdf)) | **Checked** |
| A high-quality pantun needs well-found end rhymes, well-arranged words, suitable symbols (*lambang*) and exact words | Johari Yahaya (2015), p. 12 | **Checked** |
| Pembayang and maksud are linked through symbol, comparison, contrast and allusion (*perlambangan, perbandingan, pertentangan, sindiran*) | Johari Yahaya (2015), p. 11 | **Checked** |
| Pembayang draws on nature and everyday life (land, garden, paddy field, river, sea, forest, trees, fruit, animals, birds, fish, simple everyday things) | F.-R. Daillie (1990), *Alam Pantun Melayu*, p. 6, quoted in Johari (2015) and Juffri Supa'at (2009), [BiblioAsia 5(2)](https://biblioasia.nlb.gov.sg/all-sections/vol-5-issue2-jul-2009-pantun-sumber-masyarakat-melayu/) | **Checked** |
| The link rests on metaphor and sound imagery (*bayangan bunyi*), e.g. *selasih dalam padi* → *kasih dalam hati* | Wilkinson & Winstedt, *Pantun Melayu* (1961), as summarised in [Pantun Melayu (Kalam Melayu)](https://kalammelayu.wordpress.com/2013/01/28/pantun-melayu/) | secondary — verify in the original |
| 8–12 syllables per line, about 4–5 words; rhyme a-b-a-b; matching middle rhyme makes a pantun *lebih baik* | School / literary guides, e.g. [Panitia Kesusasteraan Melayu SMK Jelai](http://sasterasmkj.blogspot.com/2010/07/pantun-dan-ciri-cirinya.html), [Sastera Melayu STPM](http://citrasasteramelayustpm.blogspot.com/2012/05/pantun.html) | school material — cite a textbook (e.g. Harun Mat Piah, 1989, *Puisi Melayu Tradisional*) after checking it |

**Measured on our corpus** (notebook section 10, `results/criteria_summary.csv`): 8–12 syllables 80% of
real pantun; end rhyme 95% (random pairings 1.5%); middle rhyme 49% (traditional anthology 23%,
author collections 54%); nature / daily-life words in 74% of pembayang vs 27% of maksud.

**Not measurable by rule:** the symbolic link (perlambangan, kiasan) that the sources treat as the
heart of a good pantun.
