"""
Response evaluator for Track 1 (Git-to-Doc).

This script does ONE thing: take a model's generated markdown response (commit
message + changelog) from an .md file and attribute a quality score to it via an
LLM judge using an explicit, weighted rubric. Generation happens elsewhere.

Usage:
    python test.py response.md                      # score one response
    python test.py a.md b.md c.md                   # score & rank several
    python test.py response.md --diff sample.diff   # ground semantic accuracy
    python test.py response.md --judge gemma4:31b   # pick a different judge
"""

import os
import re
import json
import argparse

from dotenv import load_dotenv
from ollama import Client

load_dotenv()  # reads OLLAMA_API_KEY from .env

client = Client(
    host="https://ollama.com",
    headers={"Authorization": "Bearer " + os.environ["OLLAMA_API_KEY"]},
)

# Judge defaults to a strong NON-Gemma model so it isn't grading its own family
# (avoids self-preference bias). Override with --judge.
DEFAULT_JUDGE = "gpt-oss:120b"

# Explicit, weighted rubric. Weights sum to 1.0. Each dimension is scored 1-5 by
# the judge against the anchors; overall = weighted sum, rescaled to /100.
RUBRIC = [
    ("format_compliance", 0.20,
     "The commit header matches Conventional Commits `type(scope): description`, "
     "uses a valid type (feat/fix/docs/style/refactor/perf/test/build/ci/chore/"
     "revert), imperative mood, no trailing period, header <= 72 chars. "
     "5 = perfect spec, 1 = not a conventional commit."),
    ("type_accuracy", 0.15,
     "The chosen type/scope correctly reflect the nature of the change "
     "(a bug fix is `fix`, a new capability is `feat`). 5 = right, 1 = wrong."),
    ("semantic_accuracy", 0.30,
     "The response truthfully describes the change with no hallucinated or "
     "omitted behavior. 5 = fully faithful, 1 = fabricated. (Grounded against "
     "the diff if one is provided; otherwise judged on internal plausibility.)"),
    ("conciseness", 0.15,
     "Terse and free of conversational filler ('Sure, here is...'), preamble, or "
     "stray text. 5 = clean & tight, 1 = bloated/filler."),
    ("changelog_quality", 0.20,
     "The changelog is valid markdown, user-facing, and accurate. "
     "5 = clear and useful, 1 = missing/wrong/internal-jargon."),
]

# Deterministic Conventional Commit header check (objective, zero-variance).
CC_HEADER = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(\([^)]+\))?(!)?: .+"
)


def extract_json(raw):
    """Best-effort parse of a JSON object from a judge reply (fence-tolerant)."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE)
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def cc_header_in(text):
    """Find the first line in the response that is a valid Conventional Commit."""
    for line in text.splitlines():
        stripped = line.strip().strip("`").strip()
        if CC_HEADER.match(stripped):
            return stripped
    return None


def judge_response(response_md, diff, judge_model):
    rubric_txt = "\n".join(
        f"- {name} (weight {w}): {desc}" for name, w, desc in RUBRIC
    )
    fields = ", ".join(f'"{name}": <1-5 int>' for name, _, _ in RUBRIC)
    system = (
        "You are a strict, impartial evaluator of git documentation quality. "
        "Score the response against each rubric dimension from 1 to 5 using the "
        "anchors. Penalize verbosity and filler; do NOT reward length. Respond "
        "with ONLY a JSON object:\n"
        f'{{"scores": {{{fields}}}, "rationale": "<one short sentence>"}}'
    )
    grounding = (
        f"GIT DIFF (ground truth for semantic_accuracy):\n{diff}\n\n"
        if diff else
        "(No diff provided — judge semantic_accuracy on internal plausibility.)\n\n"
    )
    user = (
        f"RUBRIC:\n{rubric_txt}\n\n"
        f"{grounding}"
        f"RESPONSE UNDER EVALUATION (markdown):\n{response_md}"
    )
    resp = client.chat(
        model=judge_model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        format="json",
        stream=False,
        options={"temperature": 0},
    )
    obj = extract_json(resp["message"]["content"]) or {}
    scores = obj.get("scores", {})
    overall = sum(
        w * (scores.get(name) if isinstance(scores.get(name), (int, float)) else 0)
        for name, w, _ in RUBRIC
    )
    return {
        "scores": scores,
        "rationale": obj.get("rationale", "(judge parse failed)"),
        "overall100": round(overall / 5 * 100, 1),
    }


def main():
    ap = argparse.ArgumentParser(description="Score .md responses against a rubric.")
    ap.add_argument("files", nargs="+", help="one or more .md response files")
    ap.add_argument("--diff", help="optional diff to ground semantic accuracy")
    ap.add_argument("--judge", default=DEFAULT_JUDGE, help="judge model id")
    args = ap.parse_args()

    diff = ""
    if args.diff and os.path.exists(args.diff):
        diff = open(args.diff, encoding="utf-8").read().strip()

    grounding = f"grounded against {args.diff}" if diff else "ungrounded (no diff)"
    print(f"# Response evaluation — judge: {args.judge} | {grounding}\n")

    rows = []
    for path in args.files:
        if not os.path.exists(path):
            print(f"  ! skipping {path}: not found")
            continue
        response = open(path, encoding="utf-8").read().strip()
        print(f"→ judging {path} ...", flush=True)
        try:
            verdict = judge_response(response, diff, args.judge)
        except Exception as e:
            print(f"  ! judging failed: {e}")
            continue
        rows.append((path, response, verdict))

    rows.sort(key=lambda r: r[2]["overall100"], reverse=True)

    # Ranked table
    dims = [name for name, _, _ in RUBRIC]
    print("\n## Results (ranked)\n")
    header = ["rank", "file", "score/100", "cc_ok"] + dims
    print("| " + " | ".join(header) + " |")
    print("|" + "|".join("---" for _ in header) + "|")
    for i, (path, response, v) in enumerate(rows, 1):
        cells = [
            str(i), os.path.basename(path), f"{v['overall100']}",
            "✓" if cc_header_in(response) else "✗",
        ] + [str(v["scores"].get(d, "-")) for d in dims]
        print("| " + " | ".join(cells) + " |")

    # Per-file rationale
    print("\n## Rationale\n")
    for path, _, v in rows:
        print(f"- **{os.path.basename(path)}** ({v['overall100']}/100): {v['rationale']}")


if __name__ == "__main__":
    main()
