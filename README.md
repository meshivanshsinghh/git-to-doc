# git-to-doc

Turn a git diff into developer documentation with a local or cloud **Gemma** model — Conventional Commit messages, markdown changelogs, and pull requests — straight from the terminal.

```bash
pip install git-to-doc
```

## Why

Developers write terrible commit messages and skip doc updates. `git-to-doc` is the plumbing that fixes that: feed it a diff, get back a spec-valid commit, a changelog snippet, and a plain-English summary. It can also write your PRs and auto-fill commit messages via a git hook.

## Backend (auto-detected)

- **Cloud:** set `OLLAMA_API_KEY` (in a `.env` or your environment) → uses `ollama.com`.
- **Local:** no key → uses a local `ollama` daemon (`localhost:11434`).

## Commands

```bash
# diff → commit message + changelog + plain-English summary
git-to-doc sample.diff
git-to-doc https://github.com/pallets/flask/pull/5000 --output both
git-to-doc ./diffs/ --output md           # batch a folder
cat x.diff | git-to-doc --commit-msg -    # print ONLY the commit message

# generate (and open) a pull request from the current branch
git-to-doc pr                              # preview
git-to-doc pr --create                     # push + open via gh
git-to-doc pr --draft --base develop

# install a git hook so `git commit` (no -m) auto-fills the message
git-to-doc install-hook

# benchmark models (timing; add --judge for rubric quality + CC pass-rate)
git-to-doc-compare sample.diff --models gemma3:4b gemma3:12b --judge gpt-oss:120b
```

## How it's built for trust

- **Self-repair loop** — every generated commit is checked against the Conventional Commits spec (`validate.py`); on failure the exact violations are fed back and the model regenerates. Output is guaranteed spec-valid, not hopeful.
- **Structured output** — Pydantic schemas force valid JSON from the model.
- **Measured, not guessed** — `git-to-doc-compare --judge` scores models with an LLM-as-judge rubric *and* a deterministic Conventional Commit pass-rate.

## Library use

```python
from git_to_doc import analyze_diff, render_full_output
doc = analyze_diff(open("sample.diff").read(), model="gemma4")
print(render_full_output(doc))
```
