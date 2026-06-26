"""
LLM-as-judge evaluator with an explicit weighted rubric.

Used by `git-to-doc-compare --judge` to score generated docs for quality,
alongside the deterministic Conventional Commit check in validate.py.
"""

import re
import json

from git_to_doc.model import _client, _resolve_model

# Judge defaults to a strong NON-Gemma model so it isn't grading its own family.
DEFAULT_JUDGE = "gpt-oss:120b"

RUBRIC = [
    ("format_compliance", 0.20,
     "Commit header matches Conventional Commits, valid type, imperative, "
     "no trailing period, <= 72 chars. 5 = perfect, 1 = not conventional."),
    ("type_accuracy", 0.15,
     "type/scope correctly reflect the change. 5 = right, 1 = wrong."),
    ("semantic_accuracy", 0.30,
     "Truthfully describes the diff, no hallucination/omission. 5 = faithful, 1 = fabricated."),
    ("conciseness", 0.15,
     "Terse, free of filler/preamble. 5 = clean, 1 = bloated."),
    ("changelog_quality", 0.20,
     "Valid markdown, user-facing, accurate. 5 = useful, 1 = missing/wrong."),
]


def _extract_json(raw):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE)
    m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def judge_response(response_md: str, diff: str, judge_model: str = DEFAULT_JUDGE) -> dict:
    rubric_txt = "\n".join(f"- {n} (weight {w}): {d}" for n, w, d in RUBRIC)
    fields = ", ".join(f'"{n}": <1-5 int>' for n, _, _ in RUBRIC)
    system = (
        "You are a strict, impartial evaluator of git documentation quality. "
        "Score the response against each rubric dimension from 1 to 5. Penalize "
        "verbosity and filler; do NOT reward length. Respond with ONLY a JSON "
        f'object:\n{{"scores": {{{fields}}}, "rationale": "<one short sentence>"}}'
    )
    grounding = (f"GIT DIFF (ground truth):\n{diff}\n\n" if diff
                 else "(No diff — judge on internal plausibility.)\n\n")
    user = f"RUBRIC:\n{rubric_txt}\n\n{grounding}RESPONSE (markdown):\n{response_md}"

    resp = _client.chat(
        model=_resolve_model(judge_model),
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        format="json",
        options={"temperature": 0},
    )
    obj = _extract_json(resp["message"]["content"]) or {}
    scores = obj.get("scores", {})
    overall = sum(w * (scores.get(n) if isinstance(scores.get(n), (int, float)) else 0)
                  for n, w, _ in RUBRIC)
    return {
        "scores": scores,
        "rationale": obj.get("rationale", "(judge parse failed)"),
        "overall100": round(overall / 5 * 100, 1),
    }
