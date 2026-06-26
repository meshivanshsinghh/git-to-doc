# git-to-doc ⚡

> Turn any git diff into a Conventional Commit message, changelog, and plain-English PR summary — powered by Gemma running locally via Ollama.

## Install

```bash
pip install git-to-doc
```

**Requires:** [Ollama](https://ollama.com) running locally with a Gemma model pulled:
```bash
ollama pull gemma4
```

## Usage

```bash
# From a GitHub PR URL
git-to-doc https://github.com/pallets/flask/pull/5000

# From a local .diff file
git-to-doc sample.diff

# Save output as markdown
git-to-doc https://github.com/pallets/flask/pull/5000 --output md

# Save both markdown and JSON
git-to-doc sample.diff --output both

# Use a different model
git-to-doc sample.diff --model gemma2:2b

# Benchmark multiple diffs
git-to-doc-compare sample.diff https://github.com/pallets/flask/pull/5000
```

## Output

For each diff, `git-to-doc` produces:

1. **Conventional Commit message** — ready to paste into `git commit`
2. **Changelog entry** — ready to paste into `CHANGELOG.md`
3. **Plain-English summary** — for non-technical stakeholders

```
──────────────────────────────────────────────────────────
  ✨  CONVENTIONAL COMMIT MESSAGE
──────────────────────────────────────────────────────────

  feat(parser): add null safety and safe_parse wrapper

──────────────────────────────────────────────────────────
  📋  CHANGELOG ENTRY
──────────────────────────────────────────────────────────

## [Unreleased] — 2026-06-26
### Added
- feat(parser): add null safety checks and safe_parse fallback

──────────────────────────────────────────────────────────
  🗣️  PLAIN ENGLISH SUMMARY
──────────────────────────────────────────────────────────

  The parser now safely handles missing or null input instead of crashing.
```

📄 **See a real rendered example →** [examples/PR-474.md](examples/PR-474.md) *(GitHub renders the callouts, collapsible sections, and code blocks natively)*

## Supported Inputs

| Input | Example |
|---|---|
| GitHub PR URL | `git-to-doc https://github.com/org/repo/pull/123` |
| Raw diff URL | `git-to-doc https://patch-diff.githubusercontent.com/raw/org/repo/pull/123.diff` |
| Local `.diff` file | `git-to-doc my_changes.diff` |
| Folder of diffs | `git-to-doc ./diffs/` |

## Flags

| Flag | Description |
|---|---|
| `--output md` | Save markdown file (auto-named `PR-123-changelog-DATE.md`) |
| `--output json` | Save JSON file |
| `--output both` | Save both |
| `--model NAME` | Ollama model to use (default: `gemma4`) |

## Built With

- [Ollama](https://ollama.com) — local LLM runtime
- [Gemma](https://ai.google.dev/gemma) — Google's open model
- [Pydantic](https://docs.pydantic.dev) — structured output validation

---

Built at AI-First Developer Efficiencies Hackathon · Track 1: The Automagic Documenter
