# Real-world benchmark

Harvest actual AI-authored commits and measure how the auditor behaves on them — the
real population, not synthetic corruptions.

- `harvest.py` — pull AI-authored commits (Copilot / Claude / Cursor / Devin / Jules)
  via the REST commit-search API, filtered for quality (repo >50 stars, 20–500 line
  diffs, >100-char messages). Requires `GITHUB_TOKEN`. → `data/real_world.jsonl`
- `run_eval.py` — audit each with the default panel and report divergence rate,
  inter-auditor agreement, and the divergences-per-commit distribution, broken down by
  AI tool. → `results/{timestamp}_{model_pair}.json`

```bash
export GITHUB_TOKEN=ghp_…
python benchmarks/real_world/harvest.py --total 200
python benchmarks/real_world/run_eval.py
```

See [../README.md](../README.md) for why both benchmarks are needed and
[../../BENCHMARKS.md](../../BENCHMARKS.md) for results.
