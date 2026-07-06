# git-to-doc benchmarks

How well does the auditor catch divergences between a commit message and what its diff
actually did? Two benchmarks answer that. Full methodology and reproduce steps live in
[`benchmarks/README.md`](benchmarks/README.md).

- **Synthetic** — well-documented commits with a deliberately corrupted message (a
  code-file sentence deleted, or the body dropped). Ground truth is known, so we measure
  **precision / recall / FPR** directly.
- **Real-world** — actual AI-authored commits (Copilot, Claude, Cursor, Devin, Jules). No
  ground truth, so we report **divergence rate** and **inter-auditor agreement** (how
  often the two models independently agree — the credibility signal).

## Results by memory tier

`git-to-doc` sizes its auditor pair to your RAM — run `git-to-doc doctor` to see your
tier and what to pull.

| Tier | Auditors | Synthetic precision | Recall | FPR |
|---|---|---|---|---|
| 8 GB | `gemma2:2b` + `qwen2.5-coder:7b` | _pending_ | _pending_ | _pending_ |
| 16 GB (default) | `qwen2.5-coder:14b` + `deepseek-coder-v2:latest` | **69%** | 36% | 32% |
| 32 GB | `qwen2.5-coder:32b` + `gpt-oss:120b` | _pending_ | _pending_ | _pending_ |

> **16 GB measured** (n=168, high-confidence, 2026-07-06); 8 GB and 32 GB still pending
> (this hardware can't run them). These are what we actually measured, not the
> illustrative ~68/82/88% targets — a trust tool shouldn't publish figures it hasn't run.
> Recall is the fraction of planted omissions caught (by type: OMISSION 25%, TRUNCATION
> 46% — a dropped body is easier to catch than a single missing sentence). FPR is the
> fraction of *unmodified* commits flagged; it's inflated because real "original" messages
> are themselves often incomplete, so some of those flags are genuine omissions the author
> never wrote. Source: `benchmarks/synthetic/results/2026-07-06T05-58-31_*.json`.

## Does "high confidence" fire?

**Yes.** On the full synthetic run (n=168) the two auditors agreed at the strict
high-confidence bar **58 times** (40 true positives + 18 false positives) — the early n=3
smoke test that suggested "high never fires" did **not** hold at scale. So the two-tier
design works: high confidence is a real, populated bucket, not a marketing fiction. It's
also *conservative* — high-confidence recall is 36%, because the tier only asserts when
both models independently agree; the single-auditor "possible" tier (flagged "verify
manually") catches more but with less certainty. The real-world run will report how often
high confidence fires on actual AI-authored commits.

## Reproduce

```bash
git-to-doc doctor                       # confirm your tier + pull the models

# synthetic (ground-truth precision/recall)
python benchmarks/synthetic/build_dataset.py --commits 200
python benchmarks/synthetic/run_eval.py

# real-world (population behavior; needs GITHUB_TOKEN)
export GITHUB_TOKEN=ghp_…
python benchmarks/real_world/harvest.py --total 200
python benchmarks/real_world/run_eval.py
```
