# git-to-doc ⚡

> **The audit layer for AI-generated commits.**

AI writes your commits now — but does the message actually describe what the diff did? `git-to-doc verify` runs a commit through independent, cross-family code models and reports where the message and the diff disagree, with every claim cited to a file and line.

## Install

```bash
pip install git-to-doc

# pull the default auditor panel (two models from different families)
ollama pull qwen2.5-coder:14b && ollama pull deepseek-coder-v2:latest
```

git-to-doc talks to a local [ollama](https://ollama.com) daemon by default, or to `ollama.com` when `OLLAMA_API_KEY` is set.

## Quick start

```bash
# audit the latest commit against its message
git-to-doc verify HEAD

# audit a specific commit
git-to-doc verify a1b2c3d

# audit a GitHub pull request instead of a local commit
git-to-doc verify --url https://github.com/owner/repo/pull/123
```

The report separates divergences the auditors **agree** on (`high` confidence) from the ones only a **single** auditor raised (`possible` — verify manually). Add `--json` for machine-readable output, or `--auditors m1,m2,m3` to choose your own panel.

## How it works

- **Independent audit** — each auditor reads the diff *blind* and describes what it does on its own terms, *before* it ever sees the author's message. It can't be anchored by a misleading one.
- **Cross-family** — the default panel is two models from different families (`qwen2.5-coder`, `deepseek-coder-v2`), so their blind spots don't overlap. A divergence they both flag is `high` confidence; one only a single model flags is `possible`.
- **Cited claims** — every divergence must cite a specific file and line from the diff. A finding with no citation is rejected by the schema, never shown to you.

## Also useful

git-to-doc grew out of a commit-documentation generator, and those commands are still here:

- **`git-to-doc <diff>`** — turn a diff, a GitHub PR URL, or a folder of `.diff` files into a Conventional Commit message, a changelog snippet, and a plain-English summary.
- **`git-to-doc pull-request`** — generate a PR title and body from your current branch, then audit that AI-generated description against the diff and append the findings *before* you post it (`--skip-audit` to opt out).
- **`git-to-doc install-hook`** — install a `prepare-commit-msg` hook so a bare `git commit` auto-fills a Conventional Commit message from the staged diff.

## Benchmarks

Auditor precision/recall on the git-to-doc eval set — see [BENCHMARKS.md](BENCHMARKS.md) *(coming in a future release)*.

## Learn more

Landing page → https://git-to-doc.dev *(placeholder)*

---

### Library use

```python
from git_to_doc import run_audit, merge_audits

reports = run_audit(diff_text, original_message)   # one AuditReport per auditor
divergences = merge_audits(reports)                # merged high/possible findings
```
