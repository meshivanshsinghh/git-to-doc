# git-to-doc

**The audit layer for AI-generated commits.**

[![PyPI](https://img.shields.io/pypi/v/git-to-doc)](https://pypi.org/project/git-to-doc/)
[![Python](https://img.shields.io/pypi/pyversions/git-to-doc)](https://pypi.org/project/git-to-doc/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Your AI wrote the commit. Did the message actually describe the diff? `git-to-doc verify`
runs the change through two independent code models from different families and reports
where the message and the diff disagree — with every claim cited to a file and line.

```console
$ git-to-doc verify HEAD

  🔍 Verifying commit a1b2c3d
     Auditors: qwen2.5-coder:14b, deepseek-coder-v2:latest (2 independent, cross-family)

  ORIGINAL MESSAGE
  fix(auth): tidy up the login helper

  ⚠️  1 DIVERGENCE — all auditors agree
   • login() now issues a session token instead of returning a boolean, and writes
     an audit-log entry — the message mentions neither
     app/auth.py:42

  📊 Benchmark: 69% precision, 36% recall (synthetic n=168, 16GB tier — see BENCHMARKS.md)
```

When the two models don't independently agree on a finding, it drops to a `possible` tier
marked "verify manually" rather than being asserted. The high bar is deliberate: on real
AI-authored commits the models agree only ~11% of the time, so a high-confidence flag
means something.

## Install

```bash
pip install git-to-doc

# pull the default auditor pair (two models, different families)
ollama pull qwen2.5-coder:14b && ollama pull deepseek-coder-v2:latest
```

git-to-doc talks to a local [ollama](https://ollama.com) daemon by default, or to
`ollama.com` when `OLLAMA_API_KEY` is set. Run **`git-to-doc doctor`** to check your RAM
and see which models to pull for your hardware.

## Usage

```bash
git-to-doc verify HEAD                    # audit the latest commit
git-to-doc verify a1b2c3d                 # audit a specific commit
git-to-doc verify --url <github-pr-url>   # audit a pull request instead
git-to-doc verify HEAD --json             # machine-readable output
git-to-doc verify HEAD --auditors m1,m2   # choose your own model panel
```

## How it works

- **Blind, then compared.** Each auditor reads the diff and describes what it does *before*
  it ever sees the author's message — so a misleading message can't anchor it.
- **Cross-family by default.** The two models come from different families
  (`qwen2.5-coder`, `deepseek-coder-v2`). A divergence they *both* flag is high-confidence;
  one only a single model raises is `possible`.
- **Every claim is cited.** A divergence must name a file and a line from the diff, or the
  schema rejects it — no vague "this looks off." And if the models can't produce a valid,
  cited report, the tool errors out rather than inventing a reassuring "all clear."

## Benchmarks

Measured on the default 16 GB tier — not hand-waved:

| Metric | Synthetic (n=168) | Real-world AI commits (n=95) |
|---|---|---|
| Precision | 69% | — |
| Recall | 36% | — |
| Divergence rate | — | 29% |
| Inter-auditor agreement | — | 11% |

High-confidence recall is intentionally conservative — the tier only fires when both models
independently agree. Full methodology, per-tool breakdowns (Copilot / Claude / Cursor /
Devin / Jules), and the honest caveats are in **[BENCHMARKS.md](BENCHMARKS.md)**.

## Also useful

git-to-doc grew out of a commit-documentation generator, and those commands remain:

- **`git-to-doc <diff | pr-url | folder>`** — a Conventional Commit message, changelog
  entry, and plain-English summary from a diff.
- **`git-to-doc pull-request`** — generate a PR title and body from your branch, then audit
  that AI-written description against the diff before you post it (`--skip-audit` to opt out).
- **`git-to-doc install-hook`** — a `prepare-commit-msg` hook that drafts the message from
  your staged diff.

## License

[MIT](LICENSE) © Shivansh Singh
