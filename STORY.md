# git-to-doc — Hackathon Slideshow Story Brief

> **For:** Claude (design/slideshow generation)
> **Goal:** Produce a ~12-slide deck that tells the story of `git-to-doc`, a CLI that turns a raw git diff into a spec-valid commit, changelog, and pull request — powered by a **Gemma** model whose reasoning is fenced by a deterministic self-repair loop.
> **Tone:** confident, minimal, developer-native. Dark terminal aesthetic, monospace accents, one idea per slide. Let Gemma be the protagonist.
> **Through-line:** *"LLMs guess. git-to-doc proves."* Every slide should reinforce that Gemma does the reasoning and a validation layer makes it trustworthy.

---

## The narrative arc

A developer ships great code and writes a one-line commit: `"fixed stuff"`. The history rots, the changelog dies, the PR has no test plan. The reasoning that went into the change — *why* this is a `fix` and not a `feat`, *what* breaks, *how* to verify — lives only in their head for about ten minutes, then it's gone.

`git-to-doc` recovers that reasoning. You feed it a diff; **Gemma reads the change like a senior engineer**, decides the commit type, the scope, what's breaking, and writes the human story of the change. Then — and this is the twist — its output is held to the Conventional Commits spec by a deterministic validator. If Gemma is wrong, it's told *exactly* how, and it tries again until it's right. The model reasons; the loop guarantees. That pairing is the whole pitch.

---

## Slide-by-slide

### Slide 1 — Title
- **Headline:** `git-to-doc`
- **Sub:** Your diff already knows what it did. Let Gemma say it.
- **Visual:** A terminal cursor blinking after `$ git-to-doc`. Minimal, dark.
- **Footer chip:** `pip install git-to-doc`

### Slide 2 — The problem (make them wince)
- **Headline:** Every team's git history is a crime scene.
- Three real commit messages, stacked, monospace: `fixed stuff` · `wip` · `asdf final FINAL`
- **Line:** Commit messages are bad. Changelogs get skipped. PRs ship with no test plan. The *reasoning* behind a change evaporates the moment it's merged.
- **Sub:** The information was there — at the diff. We just never captured it.

### Slide 3 — The idea
- **Headline:** A diff is a fully-formed argument. Someone just has to read it.
- **Line:** `git-to-doc` feeds your diff to a **Gemma** model and gets back three things, every time:
  - ✅ a spec-valid **Conventional Commit**
  - 📝 a ready-to-paste **changelog** entry
  - 🗣️ a **plain-English** summary for non-engineers
- **Sub:** One command. Local or cloud. No copy-paste into a chat window.

### Slide 4 — Meet Gemma, the reasoner (THE HERO SLIDE)
- **Headline:** Gemma reads the change like a senior reviewer.
- Show the actual reasoning chain as a vertical flow over a real diff (`parser.py` gains validation + a `safe_parse` wrapper):
  - *"This adds guards against `None` and missing keys."* → it prevents a crash, not adds a feature → **type: `fix`**
  - *"The change lives in one module."* → **scope: `parser`**
  - *"Existing call signatures are untouched."* → **breaking: `false`**
  - *"Here's why a human cares."* → **plain-English summary**
- **Punchline:** This isn't templating. It's judgment — the same calls a reviewer makes, in milliseconds.

### Slide 5 — The output (proof, not promise)
- **Headline:** From diff to documentation, in one shot.
- Render the real generated commit:
  ```
  fix(parser): add input validation to parse and introduce safe_parse

  Implemented explicit checks for None and missing 'value' keys
  in parse() to prevent unhandled exceptions. Added a safe_parse
  wrapper that catches these errors and returns None while logging.
  ```
- Beside it, the changelog bullet + the one-sentence plain-English line.
- **Sub:** Imperative mood. ≤72-char subject. Correct type. Every time.

### Slide 6 — The twist: reasoning isn't enough (TENSION)
- **Headline:** But an LLM that's *usually* right is a liability in your git history.
- **Line:** Models hallucinate. They invent commit types, blow the 72-char limit, wrap JSON in stray fences. "Probably valid" is not valid.
- **Sub, large:** So we don't trust the model. We *check* it.

### Slide 7 — The self-repair loop (THE INNOVATION)
- **Headline:** Reason → Validate → Repair → Guarantee.
- A loop diagram:
  1. **Gemma** generates structured JSON (Pydantic-typed)
  2. **`validate.py`** checks it against the Conventional Commits spec — deterministic, zero-dependency, zero variance
  3. ❌ Invalid? The **exact violations** are fed back to Gemma: *"subject exceeds 72 chars; regenerate."*
  4. ✅ Valid? Ship it. (Loop caps at 3 tries.)
- **Punchline:** The model does the thinking. The loop does the guaranteeing. Output is **spec-valid by construction — not by luck.**

### Slide 8 — Why Gemma specifically
- **Headline:** The reasoning runs where your code lives.
- Three pillars:
  - **Local-first / private** — no key → runs against your own `ollama` daemon. Your diffs never leave the machine.
  - **Cloud when you want it** — set `OLLAMA_API_KEY` → same code, hosted Gemma. Auto-detected, zero config change.
  - **Right-sized reasoning** — `gemma3:4b` → `gemma3:12b` → `gemma4:31b`. Trade speed for depth per task.
- **Sub:** Generation is Gemma-only by design. Other model families are allowed *only* to grade it — never to write your history.

### Slide 9 — It writes your PRs too
- **Headline:** `git-to-doc pr` — one command, a complete pull request.
- Gemma reads the full branch diff (`base...HEAD`) and reasons out: **title · summary · itemized changes · test plan · breaking flag.**
- Flow: detect base branch → analyze → `--create` pushes and opens via `gh`.
- **Sub:** It doesn't just describe the PR. It tells a reviewer how to *verify* it.

### Slide 10 — Lives inside your workflow
- **Headline:** No new habits. It hooks into the ones you have.
- `git-to-doc install-hook` → a `prepare-commit-msg` hook auto-fills your message on every `git commit`. Accept or edit.
- Also: GitHub PR URLs, stdin pipes, batch a whole folder of diffs.
- **Sub:** The best tool is the one you never have to remember to use.

### Slide 11 — Measured, not vibes (CREDIBILITY)
- **Headline:** We don't claim quality. We benchmark it.
- `git-to-doc-compare` scores models two ways:
  - **CC pass-rate** — deterministic Conventional Commits compliance (the same validator from the loop)
  - **LLM-as-judge** — a weighted rubric (format, type accuracy, semantics, conciseness, changelog quality), run by a *different* model family so Gemma never grades its own homework.
- Show a clean benchmark table: `MODEL · TIME · CC ✓ · SCORE · SUBJECT`.
- **Sub:** Every quality claim in this deck is reproducible from the CLI.

### Slide 12 — Close
- **Headline:** Stop writing `fixed stuff`.
- **Line:** Gemma captures the reasoning. The self-repair loop guarantees it's correct. Your git history finally tells the truth.
- **Three chips:** `~700 lines, no heavy frameworks` · `local or cloud` · `spec-valid by construction`
- **CTA:** `pip install git-to-doc` → `git-to-doc pr --create`

---

## Design notes for the deck
- **Palette:** near-black background, off-white text, one accent (terminal green or a cool electric blue). Use it sparingly — only on the words "Gemma," "valid," and the CTA.
- **Type:** a clean grotesque sans for headlines; a real monospace (JetBrains Mono / IBM Plex Mono) for every code, commit, and diff block. Never fake code with a sans font.
- **Rhythm:** one idea per slide; headlines ≤ 8 words. Let whitespace carry the minimalism the project itself values.
- **Recurring motif:** a small `reason → validate → repair → ✅` glyph in a corner from slide 6 onward, so the loop becomes the deck's signature.
- **The two emotional beats to land:** Slide 4 (*Gemma actually reasons*) and Slide 7 (*and we prove it's right*). Everything else supports those two.

## One-sentence elevator version (for the opener or a backup slide)
> `git-to-doc` turns a git diff into a spec-valid commit, changelog, and PR by letting a local **Gemma** model reason about the change like a senior reviewer — then holding that reasoning to the Conventional Commits spec with a deterministic self-repair loop, so the output is correct by construction, not by luck.
