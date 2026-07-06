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
| 16 GB (default) | `qwen2.5-coder:14b` + `deepseek-coder-v2:latest` | _pending_ | _pending_ | _pending_ |
| 32 GB | `qwen2.5-coder:32b` + `gpt-oss:120b` | _pending_ | _pending_ | _pending_ |

> **Numbers pending.** These rows are placeholders until the full benchmark runs
> complete — a tool whose whole point is trust shouldn't publish precision figures it
> hasn't actually measured. Illustrative targets are ~68% / 82% / 88% precision across
> the tiers; the real figures will be filled in from `benchmarks/*/results/*.json`.

## A note on inter-auditor agreement

Early signal suggests that at the strict "high confidence" bar (both auditors citing the
same file within a few lines), agreement is **rare** — most findings land in the
single-auditor "possible" tier. If that holds on the full run, it's an honest property we
surface rather than hide: high-confidence findings appear when the models genuinely agree,
and possible ones (flagged "verify manually") when they don't. The full synthetic and
real-world runs will quantify exactly how often each tier fires.

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
