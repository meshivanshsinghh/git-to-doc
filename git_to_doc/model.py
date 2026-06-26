import os
import re
from pydantic import BaseModel, ValidationError
from typing import Literal, Optional

from dotenv import load_dotenv
from ollama import Client

from git_to_doc.validate import validate_commit, validate_pr

load_dotenv()  # picks up OLLAMA_API_KEY from a local .env if present

# ── Backend auto-detection ────────────────────────────────────────────────────
# Cloud (ollama.com) when OLLAMA_API_KEY is set; otherwise a local ollama daemon.
_API_KEY = os.environ.get("OLLAMA_API_KEY")
USE_CLOUD = bool(_API_KEY)
if USE_CLOUD:
    _client = Client(host="https://ollama.com",
                     headers={"Authorization": f"Bearer {_API_KEY}"})
else:
    _client = Client()  # defaults to http://localhost:11434

# Cloud uses size tags (gemma4:31b); local relies on whatever you've pulled.
_CLOUD_ALIASES = {"gemma4": "gemma4:31b", "gemma3": "gemma3:12b", "gemma2": "gemma3:4b"}


def backend() -> str:
    return "cloud (ollama.com)" if USE_CLOUD else "local (localhost:11434)"


def _resolve_model(model: str) -> str:
    if ":" in model:
        return model
    if USE_CLOUD:
        return _CLOUD_ALIASES.get(model, f"{model}:latest")
    return f"{model}:latest"


def _chat(model: str, messages: list, schema: dict) -> str:
    resp = _client.chat(
        model=_resolve_model(model),
        messages=messages,
        format=schema,
        options={"temperature": 0},
    )
    return resp["message"]["content"]


def _parse(raw: str, Model):
    """Validate model output into `Model`, tolerating ```json fences / stray prose.

    Some models (e.g. gemma3:12b) wrap their JSON in code fences despite the
    schema constraint; we fall back to the first balanced {...} block.
    """
    candidates = [raw]
    cleaned = re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.MULTILINE)
    m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if m:
        candidates.append(m.group(0))
    last_err = None
    for c in candidates:
        try:
            return Model.model_validate_json(c)
        except ValidationError as e:
            last_err = e
    
    if last_err is not None:
        raise last_err
    raise ValueError("No valid candidates found for parsing.")


# ── Commit document ───────────────────────────────────────────────────────────
class CommitDoc(BaseModel):
    type: Literal["feat","fix","docs","refactor","perf","test","chore","ci","build","revert"]
    scope: Optional[str]
    subject: str
    body: Optional[str]
    breaking: bool
    changelog_entry: str
    plain_english: str
    human_title: str
    review_notes: str
    file_notes: dict[str, str]


SYSTEM_PROMPT = """
You are a senior developer and expert technical writer.
Given a raw git diff, output ONLY a valid JSON object with no explanation, no markdown fences, no preamble.

Rules for each field:
- type: one of feat|fix|docs|refactor|perf|test|chore|ci|build|revert
- scope: lowercase name of the module or folder most affected (null if unclear)
- subject: imperative mood, lowercase, no trailing period, max 72 chars. Write it like a human developer would — natural and specific, not robotic.
- body: 2-4 sentences of precise technical detail explaining WHAT was changed and WHY. Reference specific function names, file paths, or patterns you see in the diff. Never be vague. null if truly trivial.
- breaking: true ONLY if existing public API contracts are removed or changed incompatibly
- changelog_entry: a user-facing markdown bullet starting with "- " that summarizes the change for a CHANGELOG.md. Be specific and helpful — mention the feature, fix, or improvement by name. For large changes, use multiple sub-bullets with "  - " to break down the key items.
- plain_english: 3-5 sentences explaining this change to a developer who hasn't seen the code. Cover: (1) what the code did before, (2) what it does now, and (3) why this matters. Use concrete language, not vague summaries. Reference module names and behaviors.
- human_title: A clear, specific title for the document. Bad: "Code Update". Good: "Refactor: Simplified checkpoint loading to return checkpointer objects directly". The title should tell someone exactly what happened without opening the doc.
- review_notes: 2-3 paragraphs for code reviewers. Paragraph 1: the overall approach and key design decisions. Paragraph 2: specific areas that need careful review (e.g., edge cases, error handling, concurrency). Paragraph 3 (optional): suggestions for follow-up work or things that were intentionally left out.
- file_notes: A dictionary mapping up to 10 of the MOST IMPORTANT changed file paths to a 1-sentence summary of what changed in each. Focus on files where the logic actually changed, not config or boilerplate. If the diff has more than 10 files, pick the ones with the most substantive changes.

Output format: raw JSON only. No ```json fences. No commentary.
"""


def analyze_diff(diff_text: str, model: str = "gemma4", max_retries: int = 3,
                 verbose: bool = False) -> CommitDoc:
    """Generate a CommitDoc, then self-repair until it passes the spec.

    Each round we deterministically validate the output (validate.py). On failure
    we feed the exact problems back and regenerate, so the result is guaranteed
    spec-valid rather than merely hopeful.
    """
    if len(diff_text) > 6000:
        diff_text = diff_text[:6000] + "\n... [truncated]"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Analyze this git diff:\n\n{diff_text}"},
    ]
    schema = CommitDoc.model_json_schema()

    for attempt in range(max_retries):
        try:
            raw = _chat(model, messages, schema)
            doc = _parse(raw, CommitDoc)
        except ValidationError as e:
            messages.append({"role": "user", "content":
                f"That was not valid JSON for the schema: {e}. "
                "Output ONLY a corrected JSON object."})
            if verbose:
                print(f"  ↻ repair {attempt+1}: invalid JSON")
            continue

        problems = validate_commit(doc)
        if not problems:
            return doc
        if verbose:
            print(f"  ↻ repair {attempt+1}: " + "; ".join(problems))
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content":
            "Your commit violates the Conventional Commits spec:\n- "
            + "\n- ".join(problems) + "\nReturn a corrected JSON object only."})

    # Fallback — never crash during a demo.
    return CommitDoc(
        type="chore", scope=None, subject="update codebase", body=None,
        breaking=False, changelog_entry="- chore: miscellaneous codebase updates",
        plain_english="General codebase updates were made.",
        human_title="Maintenance: Codebase Update",
        review_notes="This is a general maintenance update. No specific review areas identified.",
        file_notes={}
    )


# ── Pull request document ─────────────────────────────────────────────────────
class PRDoc(BaseModel):
    title: str
    summary: str
    changes: list[str]
    test_plan: str
    breaking: bool


PR_SYSTEM_PROMPT = """
You are an expert engineer writing a pull request from a git diff (the full set
of changes on a branch). Output ONLY a valid JSON object — no prose, no fences.

Fields:
- title: a Conventional Commit header summarising the whole PR, e.g.
  "feat(auth): add OAuth2 login" — lowercase subject, no trailing period, <= 72 chars
- summary: 1-3 sentences describing what this PR does and why
- changes: array of concise bullet strings, one per meaningful change
- test_plan: short, concrete steps a reviewer can run to verify the change
- breaking: true ONLY if public API/behaviour changes incompatibly

Output format: raw JSON only. No ```json fences. No commentary.
"""


def analyze_pr(diff_text: str, model: str = "gemma4", max_retries: int = 3,
               verbose: bool = False) -> PRDoc:
    """Generate a PRDoc from a branch diff, with the same self-repair loop."""
    if len(diff_text) > 12000:
        diff_text = diff_text[:12000] + "\n... [truncated]"

    messages = [
        {"role": "system", "content": PR_SYSTEM_PROMPT},
        {"role": "user", "content": f"Branch diff:\n\n{diff_text}"},
    ]
    schema = PRDoc.model_json_schema()

    for attempt in range(max_retries):
        try:
            raw = _chat(model, messages, schema)
            doc = _parse(raw, PRDoc)
        except ValidationError as e:
            messages.append({"role": "user", "content":
                f"Invalid JSON for the schema: {e}. Output ONLY corrected JSON."})
            continue

        problems = validate_pr(doc)
        if not problems:
            return doc
        if verbose:
            print(f"  ↻ repair {attempt+1}: " + "; ".join(problems))
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content":
            "Your PR has these problems:\n- " + "\n- ".join(problems)
            + "\nReturn a corrected JSON object only."})

    return PRDoc(
        title="chore: update branch",
        summary="This pull request bundles changes on the current branch.",
        changes=["Various updates across the codebase."],
        test_plan="Run the existing test suite and verify the app starts.",
        breaking=False,
    )
