# git-to-doc benchmarks

Two complementary benchmarks measure how well the auditor catches divergences between a
commit message and what its diff actually did.

## Why two benchmarks?

- **Synthetic (`synthetic/`)** — take well-documented real commits and *deliberately
  corrupt* the message (delete a file-describing sentence, or drop the body). Because we
  know exactly what we removed, we have **ground truth** and can measure precision,
  recall, and false-positive rate directly and cheaply. Weakness: the corruptions are
  artificial and may not resemble how real messages actually go wrong.
- **Real-world (`real_world/`)** — harvest the *actual population* of AI-authored commits
  (Copilot, Claude, Cursor, Devin, Jules) and measure how the auditor behaves on them.
  There's no free ground truth, so instead of precision/recall we report population
  statistics — divergence rate and, crucially, **inter-auditor agreement** (how often the
  two models independently flag the same thing). Labeled precision on this set (human or
  judge-model) is a further step.

You need both: synthetic gives cheap, exact, repeatable numbers; real-world tells you
whether the tool's behavior holds on the messages people actually write.

> Tip: run `git-to-doc doctor` to see your RAM, installed models, and the recommended
> auditor pair for your hardware before running a benchmark.

## Synthetic corruption benchmark

Each source commit yields three variants:

| Variant | Message | Expectation |
|---|---|---|
| `CONTROL` | original, intact | auditor should flag **nothing** |
| `OMISSION` | one code-file-describing sentence deleted | auditor should flag **that file** |
| `TRUNCATION` | body dropped, subject line only | auditor should flag **that file** |

Omissions are planted only on **code files** (the auditor is designed to ignore
docs/config, so a docs omission would penalize correct behavior). For
`OMISSION`/`TRUNCATION` we record the `{file, line, description}` the removed content
referred to (single-label ground truth). Metrics:

- **Recall** — of corrupted commits, how many had the planted file flagged.
- **FPR** — of `CONTROL` commits, how many were flagged anyway.
- **Precision** — `TP / (TP + FP)`, where TP = planted omissions caught and FP = flags on
  `CONTROL` commits. Extra unlabeled flags on corrupted commits are neither credited nor
  penalized — a limitation of single-label synthetic data. `--confidence high` (default)
  scores only "all auditors agree" flags; `--confidence any` includes single-auditor
  "possible" flags.

```bash
# full run (200 commits × 3). Set GITHUB_TOKEN to raise the API limit / reach 200.
python benchmarks/synthetic/build_dataset.py --commits 200
python benchmarks/synthetic/run_eval.py

# smoke test (fast)
python benchmarks/synthetic/build_dataset.py --commits 10
python benchmarks/synthetic/run_eval.py --limit 3
```

## Real-world benchmark

Harvest AI-authored commits and audit them (needs `GITHUB_TOKEN`):

```bash
export GITHUB_TOKEN=ghp_…
python benchmarks/real_world/harvest.py --total 200      # → data/real_world.jsonl
python benchmarks/real_world/run_eval.py                 # → results/…json + summary
```

`harvest.py` searches the REST commit-search API for each AI tool's co-author trailer
(GitHub's GraphQL API can't search commit messages) and keeps commits from repos with
>50 stars, diffs of 20–500 lines, and messages >100 chars. `run_eval.py` reports, per
tool: **divergence rate** (% of commits with ≥1 high-confidence divergence),
**inter-auditor agreement** (% of all flags that are high-confidence), and the
divergences-per-commit distribution.

Both full runs audit hundreds of (message, diff) pairs with two local models — **they
take hours.**

## Results by memory tier

`git-to-doc` picks an auditor pair sized to your RAM (`recommend_auditors()` /
`git-to-doc doctor`):

| Tier | Auditors | Synthetic precision |
|---|---|---|
| 8 GB | `gemma2:2b` + `qwen2.5-coder:7b` | _pending_ |
| 16 GB (default) | `qwen2.5-coder:14b` + `deepseek-coder-v2:latest` | **69%** (recall 36%, FPR 32%) |
| 32 GB | `qwen2.5-coder:32b` + `gpt-oss:120b` | _pending_ |

16 GB measured on n=168 (high-confidence, 2026-07-06); high confidence **fired** (40 TP +
18 FP). 8 GB / 32 GB still pending (needs that hardware). The illustrative ~68/82/88%
targets were **not** used — these are measured. See [../BENCHMARKS.md](../BENCHMARKS.md)
and `synthetic/results/*.json`.

Generated datasets and result JSON are git-ignored; commit the curated results you want
to publish.
