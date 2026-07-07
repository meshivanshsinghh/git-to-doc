# git-to-doc

**The audit layer for AI-generated commits.**

[![PyPI](https://img.shields.io/pypi/v/git-to-doc)](https://pypi.org/project/git-to-doc/)
[![Python](https://img.shields.io/pypi/pyversions/git-to-doc)](https://pypi.org/project/git-to-doc/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

## The problem

A lot of commits are written by AI now, and so are their commit messages. The trouble
is that the message often doesn't match what the diff actually did. It skips a side
effect, softens a behavior change, or describes the intent instead of the result.
Reviewers skim the message and trust it. That gap is where bugs slip through.

git-to-doc closes the gap. Point it at a commit and it tells you where the message and
the diff disagree, with every finding pinned to a specific file and line.

## What it looks like

```console
$ git-to-doc verify HEAD

  🔍 Verifying commit a1b2c3d
     Auditors: qwen2.5-coder:14b, deepseek-coder-v2:latest (2 independent, cross-family)

  ORIGINAL MESSAGE
  fix(auth): tidy up the login helper

  ⚠️  1 DIVERGENCE (all auditors agree)
   • login() now issues a session token instead of returning a boolean, and also
     writes an audit-log entry that the message never mentions
     app/auth.py:42

  📊 Benchmark: 69% precision, 36% recall (synthetic n=168, 16GB tier, see BENCHMARKS.md)
```

When the message honestly covers the diff, you get a green "matches" line instead. When
only one of the two models flags something, it shows up as `possible` and asks you to
verify it, rather than being stated as fact.

## How it works

![How git-to-doc verify works](https://raw.githubusercontent.com/meshivanshsinghh/git-to-doc/main/assets/how-it-works.svg)

1. **Two models, different families.** By default `qwen2.5-coder` and
   `deepseek-coder-v2`. Different training gives them different blind spots, which is
   exactly why agreement between them carries weight.
2. **They read the diff blind.** Each model describes what the change does *before* it
   ever sees the author's message, so a misleading message can't steer it.
3. **Then they compare.** Each independent reading is checked against the commit message.
   Anything the message omits or misstates becomes a divergence, and every divergence
   has to cite a file and line or it gets thrown out.
4. **Agreement sets the confidence.** If both models flag the same spot, it is `HIGH`. If
   only one does, it is `possible`. If the models can't produce a valid, cited report at
   all, the tool errors out instead of inventing a reassuring "all clear."

## Install

```bash
pip install git-to-doc

# pull the default two-model panel
ollama pull qwen2.5-coder:14b && ollama pull deepseek-coder-v2:latest
```

git-to-doc runs against a local [ollama](https://ollama.com) daemon by default, or
`ollama.com` if you set `OLLAMA_API_KEY`. Not sure what your machine can run? Run
`git-to-doc doctor` and it reports your RAM, the recommended model pair, and anything
still left to pull.

## Usage

```bash
git-to-doc verify HEAD                    # audit the latest commit
git-to-doc verify a1b2c3d                 # audit a specific commit
git-to-doc verify --url <github-pr-url>   # audit a pull request instead
git-to-doc verify HEAD --json             # machine-readable output
git-to-doc verify HEAD --auditors m1,m2   # pick your own model panel
```

## Benchmarks

Measured on the default 16 GB model pair, not estimated:

- **Synthetic (n=168, known ground truth):** 69% precision, 36% recall.
- **Real-world (n=95 actual AI commits):** 29% of commits carried a high-confidence
  divergence, and the two models agreed on 11% of all findings.

Two things worth saying plainly. Recall is on the low side because `HIGH` only fires when
both models independently agree, which is a strict bar by design. And that 11% agreement
on real commits means most findings are single-model `possible` flags, not certainties.
The full method, per-tool breakdown (Copilot, Claude, Cursor, Devin, Jules), and the
caveats live in [BENCHMARKS.md](BENCHMARKS.md).

## Also useful

git-to-doc started life as a commit-documentation generator, and those commands are still
here:

- `git-to-doc <diff | pr-url | folder>` turns a diff into a Conventional Commit message,
  a changelog entry, and a plain-English summary.
- `git-to-doc pull-request` writes a PR title and body from your branch, then audits that
  AI-written description against the diff before you post it (`--skip-audit` opts out).
- `git-to-doc install-hook` installs a `prepare-commit-msg` hook that drafts the message
  from your staged diff.

## License

[MIT](LICENSE), © 2026 Shivansh Singh
