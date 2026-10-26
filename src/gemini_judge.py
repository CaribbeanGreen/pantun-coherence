"""AI-judge experiment: can Gemini see the pembayang-maksud link (including kiasan)?

The plan (sample, prompt, analysis, decision rule) was fixed BEFORE any API call:
see docs/gemini_judge_plan.md.

Steps (run from the project root):
    python -m src.gemini_judge sample          # build the 600-item sample -> results/gemini_sample.csv
    python -m src.gemini_judge run             # ask Gemini (resumable)    -> results/gemini_raw.jsonl
    python -m src.gemini_judge evaluate        # analysis                  -> results/gemini_judge.json
    python -m src.gemini_judge run_local       # ask Gemma 4 in LM Studio  -> results/gemma_raw.jsonl
    python -m src.gemini_judge evaluate_local  # analysis                  -> results/gemma_judge.json
(Amendment 2 in the plan: Gemma 4 12B runs locally on all 600 items with the same prompt.)

The API key is read from the file .env (GEMINI_API_KEY=...), which is never shared.
"""

import json
import re
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
from scipy import stats

from src.data_loader import PROJECT_ROOT, join_couplet, load_pantun
from src.rhyme import last_word, sound_score

RESULTS = PROJECT_ROOT / "results"
SAMPLE_CSV = RESULTS / "gemini_sample.csv"
RAW_JSONL = RESULTS / "gemini_raw.jsonl"
OUT_JSON = RESULTS / "gemini_judge.json"
SEED, PER_GROUP, BATCH = 42, 150, 25
LINK_TYPES = ["word_echo", "sound_echo", "kiasan", "same_topic", "none"]

PROMPT = """You are an expert in Malay literature and traditional Malay pantun.

A pantun empat kerat has two parts. The PEMBAYANG (lines 1-2) usually draws an image from nature or
daily life. The MAKSUD (lines 3-4) carries the real message. In a good pantun the pembayang prepares
or hints at the maksud, for example through a repeated word, an echo of sound, a shared topic, or an
analogy / symbol (kiasan). Rhyme at the line ends (a-b-a-b) is expected in every pantun, so do NOT
judge the line-end rhyme; judge only how the pembayang connects to the maksud.

For each pantun below, give:
- "score": an integer 1-10 for how strongly the pembayang hints at or prepares the maksud
  (1 = no connection at all, 10 = a very clear and fitting connection)
- "link_type": the main kind of connection, one of: word_echo, sound_echo, kiasan, same_topic, none
- "hint": one short sentence (max 25 words) explaining the connection, or saying there is none

Answer with a JSON list, one object per pantun, with the fields "id", "score", "link_type", "hint".

Pantun:
"""


# ---------------------------------------------------------------------------
# Sample
# ---------------------------------------------------------------------------

def final_syllable(word):
    m = re.search(r"[^aeiou]*[aeiou]+[^aeiou]*$", word)
    return m.group(0) if m else word


def build_sample():
    pantun, _ = load_pantun()
    lines = [p.lines for p in pantun]
    maksud = [p.maksud for p in pantun]
    book = [p.info["collection"] for p in pantun]
    group = ["traditional" if p.info["collection_type"] == "traditional_anthology" else "author"
             for p in pantun]
    key = lambda a, b: (final_syllable(last_word(a)), final_syllable(last_word(b)))
    by_end = defaultdict(list)
    for j, l in enumerate(lines):
        by_end[key(l[2], l[3])].append(j)
    # A borrowed maksud that is a near-copy of the pembayang's own maksud (another version of the
    # same pantun from a different book) would make the "fake" secretly real. Exclude those.
    emb = np.load(RESULTS / "embeddings" / "labse.npz")["maksud"]

    def partners(i):
        pool = [j for j in by_end[key(lines[i][0], lines[i][1])]
                if maksud[j] != maksud[i] and float(emb[i] @ emb[j]) < 0.8]
        same = [j for j in pool if book[j] == book[i]]
        return same or pool

    rng = np.random.default_rng(SEED)
    used, rows = set(), []
    for g in ["traditional", "author"]:
        pool = [i for i in range(len(pantun)) if group[i] == g and partners(i)]
        rng.shuffle(pool)
        fakes = reals = 0
        for i in pool:
            if i in used:
                continue
            if fakes < PER_GROUP:                       # fake: pembayang i + maksud of partner j
                options = [j for j in partners(i) if j not in used]
                if not options:
                    continue
                j = int(rng.choice(options))
                used |= {i, j}
                rows.append({"pembayang_from": pantun[i].id, "maksud_from": pantun[j].id, "group": g,
                             "real": 0, "lines": lines[i][:2] + lines[j][2:]})
                fakes += 1
            elif reals < PER_GROUP:                     # real pantun
                used.add(i)
                rows.append({"pembayang_from": pantun[i].id, "maksud_from": pantun[i].id, "group": g,
                             "real": 1, "lines": lines[i]})
                reals += 1
            if fakes == reals == PER_GROUP:
                break
    df = pd.DataFrame(rows).sample(frac=1, random_state=SEED).reset_index(drop=True)
    df.insert(0, "item", [f"Q{k:03d}" for k in range(len(df))])
    for k in range(4):
        df[f"line{k + 1}"] = df["lines"].str[k]
    df = df.drop(columns="lines")
    SAMPLE_CSV.parent.mkdir(exist_ok=True)
    df.to_csv(SAMPLE_CSV, index=False, encoding="utf-8")
    print(df.groupby(["group", "real"]).size())
    print(f"Wrote {SAMPLE_CSV.relative_to(PROJECT_ROOT)}")


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def api_key():
    env = PROJECT_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("No GEMINI_API_KEY in .env - create the file first (see README).")


def pick_model(client):
    """Newest stable Gemini Flash model (no preview / lite / experimental versions)."""
    names = [m.name.split("/")[-1] for m in client.models.list()]
    flash = [n for n in names if re.fullmatch(r"gemini-\d+(\.\d+)?-flash", n)]
    if not flash:
        sys.exit(f"No stable Gemini Flash model found. Available: {names}")
    return max(flash, key=lambda n: float(re.search(r"\d+(\.\d+)?", n).group(0)))


def run():
    from google import genai
    from google.genai import errors, types

    df = pd.read_csv(SAMPLE_CSV, keep_default_na=False)
    done = set()
    if RAW_JSONL.exists():
        for line in RAW_JSONL.read_text(encoding="utf-8").splitlines():
            done |= set(json.loads(line)["items"])
    client = genai.Client(api_key=api_key())
    model = pick_model(client)
    print(f"Model: {model}; already done: {len(done)} of {len(df)} items")
    schema = {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "score": {"type": "integer"},
        "link_type": {"type": "string", "enum": LINK_TYPES}, "hint": {"type": "string"}},
        "required": ["id", "score", "link_type", "hint"]}}
    config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                         response_json_schema=schema)
    todo = df[~df["item"].isin(done)]
    for start in range(0, len(todo), BATCH):
        batch = todo.iloc[start:start + BATCH]
        text = PROMPT + "\n".join(f'{r.item}:\n{r.line1}\n{r.line2}\n{r.line3}\n{r.line4}\n'
                                  for r in batch.itertuples())
        for attempt in range(6):
            try:
                resp = client.models.generate_content(model=model, contents=text, config=config)
                answers = json.loads(resp.text)
                break
            except errors.ClientError as e:
                if e.code == 429 and attempt < 5:      # rate limit: wait and retry
                    print("  rate limit reached, waiting 65 s ...")
                    time.sleep(65)
                    continue
                print(f"Stopped: {e}. Progress is saved; run again later to continue.")
                return
            except (json.JSONDecodeError, errors.ServerError) as e:
                print(f"  problem ({type(e).__name__}), retrying ...")
                time.sleep(10)
        else:
            print("Stopped after repeated problems. Progress is saved; run again later.")
            return
        with open(RAW_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps({"model": model, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "items": list(batch["item"]), "answers": answers}, ensure_ascii=False) + "\n")
        print(f"  batch {start // BATCH + 1}: {len(answers)} answers")
        time.sleep(7)                                   # stay under the per-minute limit
    print("All items done.")


LOCAL_URL = "http://localhost:1234/v1/chat/completions"
LOCAL_MODEL = "gemma4-judge"   # identifier given when loading google/gemma-4-12b-qat in LM Studio
GEMMA_RAW = RESULTS / "gemma_raw.jsonl"
MAX_TOKENS = 12000                                  # Amendment 3: cap on thinking + answer per request


def run_local():
    """Same prompt and batches, sent to Gemma 4 running in LM Studio on this computer."""
    import urllib.request

    df = pd.read_csv(SAMPLE_CSV, keep_default_na=False)
    done = set()
    if GEMMA_RAW.exists():
        for line in GEMMA_RAW.read_text(encoding="utf-8").splitlines():
            done |= set(json.loads(line)["items"])
    item_schema = {"type": "object", "properties": {
        "id": {"type": "string"}, "score": {"type": "integer"},
        "link_type": {"type": "string", "enum": LINK_TYPES}, "hint": {"type": "string"}},
        "required": ["id", "score", "link_type", "hint"]}
    schema = {"type": "object", "properties": {"answers": {"type": "array", "items": item_schema}},
              "required": ["answers"]}
    def ask(batch):
        """Send one batch; return (answers, info). answers is None if the model gave no valid answer."""
        text = PROMPT + "\n".join(f'{r.item}:\n{r.line1}\n{r.line2}\n{r.line3}\n{r.line4}\n'
                                  for r in batch.itertuples())
        body = {"model": LOCAL_MODEL, "temperature": 0, "seed": SEED,
                "max_tokens": MAX_TOKENS,           # Amendment 3: stops endless "thinking" loops
                "messages": [{"role": "user", "content": text}],
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": "pantun_judgements", "strict": True, "schema": schema}}}
        req = urllib.request.Request(LOCAL_URL, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=1800) as resp:
                reply = json.loads(resp.read().decode("utf-8"))
        except TimeoutError:
            return None, "timeout"
        choice = reply["choices"][0]
        try:
            return json.loads(choice["message"].get("content") or "")["answers"], "ok"
        except (json.JSONDecodeError, KeyError):
            return None, f"finish_reason={choice.get('finish_reason')}"

    def save(batch, answers, size):
        with open(GEMMA_RAW, "a", encoding="utf-8") as f:
            f.write(json.dumps({"model": LOCAL_MODEL, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "batch_size": size, "items": list(batch["item"]), "answers": answers},
                               ensure_ascii=False) + "\n")

    todo = df[~df["item"].isin(done)]
    print(f"Model: {LOCAL_MODEL}; already done: {len(done)} of {len(df)} items")
    for start in range(0, len(todo), BATCH):
        batch = todo.iloc[start:start + BATCH]
        t0 = time.time()
        answers, info = ask(batch)
        if answers is not None:
            save(batch, answers, BATCH)
            print(f"  batch {start // BATCH + 1}: {len(answers)} answers in {time.time() - t0:.0f} s", flush=True)
            continue
        # Amendment 3: a failed batch of 25 is retried as smaller batches (5, then 1 item).
        print(f"  batch {start // BATCH + 1}: failed ({info}); retrying in smaller batches", flush=True)
        pending = [batch.iloc[k:k + 5] for k in range(0, len(batch), 5)]
        for small in pending:
            answers, info = ask(small)
            if answers is not None:
                save(small, answers, len(small))
                print(f"    {len(small)} items ok", flush=True)
                continue
            for k in range(len(small)):
                one = small.iloc[k:k + 1]
                answers, info = ask(one)
                if answers is not None:
                    save(one, answers, 1)
                    print(f"    1 item ok ({one['item'].iloc[0]})", flush=True)
                else:
                    save(one, [], 1)          # recorded as failed: counted as missing in the analysis
                    print(f"    1 item FAILED ({one['item'].iloc[0]}, {info})", flush=True)
    print("All items done.", flush=True)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def auc(real, fake):
    u, _ = stats.mannwhitneyu(real, fake)
    return float(u / (len(real) * len(fake)))


def bootstrap_ci(scores, labels, n=1000, seed=SEED):
    rng = np.random.default_rng(seed)
    real, fake = scores[labels == 1], scores[labels == 0]
    vals = [auc(rng.choice(real, len(real)), rng.choice(fake, len(fake))) for _ in range(n)]
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def evaluate(raw_path=RAW_JSONL, out_path=OUT_JSON, items_csv=RESULTS / "gemini_scored_items.csv"):
    df = pd.read_csv(SAMPLE_CSV, keep_default_na=False)
    answers, models = {}, set()
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        models.add(rec["model"])
        for a in rec["answers"]:
            answers[a["id"]] = a
    df["gemini_score"] = df["item"].map(lambda k: answers.get(k, {}).get("score", np.nan))
    df["link_type"] = df["item"].map(lambda k: answers.get(k, {}).get("link_type", ""))
    df["hint"] = df["item"].map(lambda k: answers.get(k, {}).get("hint", ""))
    missing = int(df["gemini_score"].isna().sum())
    df = df.dropna(subset=["gemini_score"])

    # Comparison methods on the same items (cached embeddings from Phase 2 + rhyme rule).
    pantun, _ = load_pantun()
    pos = {p.id: k for k, p in enumerate(pantun)}
    for name in ["labse", "e5_large_instruct"]:
        e = np.load(RESULTS / "embeddings" / f"{name}.npz")
        df[name] = [float(e["pembayang"][pos[a]] @ e["maksud"][pos[b]])
                    for a, b in zip(df["pembayang_from"], df["maksud_from"])]
    df["sound"] = [sound_score([r.line1, r.line2, r.line3, r.line4]) for r in df.itertuples()]
    df.to_csv(items_csv, index=False, encoding="utf-8")

    y = df["real"].to_numpy()
    out = {"plan": "docs/gemini_judge_plan.md", "model": sorted(models), "items_scored": int(len(df)),
           "items_missing": missing, "auc": {}, "auc_ci95": {}, "auc_by_group": {}}
    for m in ["gemini_score", "labse", "e5_large_instruct", "sound"]:
        s = df[m].to_numpy(dtype=float)
        out["auc"][m] = auc(s[y == 1], s[y == 0])
        out["auc_ci95"][m] = bootstrap_ci(s, y)
        out["auc_by_group"][m] = {g: auc(df.loc[(df.group == g) & (df.real == 1), m].to_numpy(float),
                                         df.loc[(df.group == g) & (df.real == 0), m].to_numpy(float))
                                  for g in ["traditional", "author"]}
    out["mean_score"] = {"real": float(df.loc[y == 1, "gemini_score"].mean()),
                         "fake": float(df.loc[y == 0, "gemini_score"].mean())}
    out["link_type_counts"] = {lab: dict(Counter(df.loc[y == v, "link_type"]))
                               for lab, v in [("real", 1), ("fake", 0)]}
    best_embedding = max(out["auc"]["labse"], out["auc"]["e5_large_instruct"])
    out["sees_link_beyond_rhyme"] = bool(out["auc"]["gemini_score"] > best_embedding
                                         and out["auc_ci95"]["gemini_score"][0] > 0.5)
    out_path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


def evaluate_local():
    evaluate(GEMMA_RAW, RESULTS / "gemma_judge.json", RESULTS / "gemma_scored_items.csv")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    {"sample": build_sample, "run": run, "evaluate": evaluate,
     "run_local": run_local, "evaluate_local": evaluate_local}[sys.argv[1]]()
