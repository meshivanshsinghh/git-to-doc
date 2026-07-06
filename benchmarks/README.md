# git-to-doc benchmarks

Two complementary benchmarks measure how well the auditor catches divergences between a
commit message and what its diff actually did.

## Why two benchmarks?

- **Synthetic (`synthetic/`)** — take well-documented real commits and *deliberately
  corrupt* the message (delete a file-describing sentence, or drop the body). Because we
  know exactly what we removed, we have **ground truth** and can measure precision,
  recall, and false-positive rate directly and cheaply. Weakness: the corruptions are
  artificial and may not resemble how real messages actually go wrong.
- **Real-world (`real_world/`, phase 6)** — sample the *actual population* of commits and
  have humans (or a strong judge model) label whether each flag is real. This reflects
  true performance but has no free ground truth, so labeling is expensive and slower.

You need both: synthetic gives cheap, exact, repeatable numbers; real-world tells you
whether those numbers hold on the messages people actually write.

## Synthetic corruption benchmark

Each source commit yields three variants:

| Variant | Message | Expectation |
|---|---|---|
| `CONTROL` | original, intact | auditor should flag **nothing** |
| `OMISSION` | one file-describing sentence deleted | auditor should flag **that file** |
| `TRUNCATION` | body dropped, subject line only | auditor should flag **that file** |

For `OMISSION`/`TRUNCATION` we record the `{file, line, description}` the removed content
referred to (single-label ground truth). Metrics:

- **Recall** — of corrupted commits, how many had the planted file flagged.
- **FPR** — of `CONTROL` commits, how many were flagged anyway.
- **Precision** — `TP / (TP + FP)`, where TP = planted omissions caught and FP = flags on
  `CONTROL` commits. Extra unlabeled flags on corrupted commits are neither credited nor
  penalized — a known limitation of single-label synthetic data. `--confidence high`
  (default) scores only "all auditors agree" flags; `--confidence any` includes
  single-auditor "possible" flags.

### Reproduce

```bash
# 1. build the dataset (200 commits × 3 variants). Set GITHUB_TOKEN to raise the API limit.
python benchmarks/synthetic/build_dataset.py --commits 200

# 2. audit each entry and score → results/{timestamp}_{model_pair}.json + a printed summary
python benchmarks/synthetic/run_eval.py

# smoke test (fast): a few commits, evaluate a handful of entries
python benchmarks/synthetic/build_dataset.py --commits 10
python benchmarks/synthetic/run_eval.py --limit 3
```

The full run audits ~600 (message, diff) pairs with two local models — **it takes hours.**

## Current results

| Date | Auditors | Precision | Recall | FPR | Results |
|---|---|---|---|---|---|
| _pending full run_ | qwen2.5-coder:14b + deepseek-coder-v2:latest | — | — | — | `synthetic/results/*.json` |

Result JSON files land in `synthetic/results/`. After a full run, commit the JSON you
want to publish and fill in the row above with a link to it.
