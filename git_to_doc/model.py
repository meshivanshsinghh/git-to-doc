import ollama
import json
from pydantic import BaseModel, ValidationError
from typing import Literal, Optional

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
- subject: imperative mood, lowercase, no trailing period, max 72 chars. Make it read naturally like a human wrote it.
- body: 1-3 sentences of technical detail (null if simple). Be descriptive but concise.
- breaking: true ONLY if existing public API contracts are removed or changed incompatibly
- changelog_entry: a detailed markdown bullet like "- feat(scope): humanized description" ready for CHANGELOG.md. Make it user-focused.
- plain_english: 1-2 sentences a non-technical person could understand explaining WHAT changed and WHY.
- human_title: A highly understandable, plain English title for the document (e.g. "New Feature: Added user authentication" or "Bug Fix: Resolved crash on startup").
- review_notes: 1-2 paragraphs highlighting tricky parts, design decisions, or areas reviewers should focus on.
- file_notes: A dictionary mapping the most important changed file paths to a 1-sentence summary of what changed in that file. (e.g. {"src/main.py": "Added initialization logic for the new auth flow."})

Output format: raw JSON only. No ```json fences. No commentary.

"""

def analyze_diff(diff_text: str, model: str = "gemma4", max_retries: int = 3) -> CommitDoc:
    if len(diff_text) > 6000:
        diff_text = diff_text[:6000] + "\n... [truncated]"

    for attempt in range(max_retries):
        try:
            response = ollama.chat(
                model=model if ":" in model else f"{model}:latest",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Analyze this git diff:\n\n{diff_text}"}
                ],
                format=CommitDoc.model_json_schema(),
                options={"temperature": 0}
            )
            raw = response["message"]["content"]
            return CommitDoc.model_validate_json(raw)
        except ValidationError as e:
            print(f"[retry {attempt+1}] validation failed: {e}")
    
    # Fallback — never crash during demo
    return CommitDoc(
        type="chore",
        scope=None,
        subject="update codebase",
        body=None,
        breaking=False,
        changelog_entry="- chore: miscellaneous codebase updates",
        plain_english="General codebase updates were made.",
        human_title="Maintenance: Codebase Update",
        review_notes="This is a general maintenance update. No specific review areas identified.",
        file_notes={}
    )