"""
Shared Conventional Commit validation layer.

Deterministic, zero-variance checks used by the self-repair loop (model.py) and
the judge (compare.py --judge). Imports nothing from the rest of the package.
"""

import re

CONVENTIONAL_TYPES = {
    "feat", "fix", "docs", "style", "refactor",
    "perf", "test", "chore", "ci", "build", "revert",
}

CC_HEADER = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|chore|ci|build|revert)"
    r"(\([a-z0-9._/-]+\))?(!)?: .+"
)

MAX_HEADER_LEN = 72


def build_header(doc) -> str:
    scope = f"({doc.scope})" if getattr(doc, "scope", None) else ""
    breaking = "!" if getattr(doc, "breaking", False) else ""
    return f"{doc.type}{scope}{breaking}: {doc.subject}"


def validate_commit(doc) -> list[str]:
    """Return human-readable Conventional Commit violations (empty == valid)."""
    problems = []
    header = build_header(doc)

    if doc.type not in CONVENTIONAL_TYPES:
        problems.append(f"type '{doc.type}' is not a valid Conventional Commit type")
    if not CC_HEADER.match(header):
        problems.append(f"header '{header}' must match 'type(scope): description'")
    if len(header) > MAX_HEADER_LEN:
        problems.append(f"header is {len(header)} chars; keep it <= {MAX_HEADER_LEN}")

    subject = (doc.subject or "").strip()
    if not subject:
        problems.append("subject is empty")
    else:
        if subject[0].isupper():
            problems.append("subject should start lowercase (imperative mood)")
        if subject.endswith("."):
            problems.append("subject must not end with a period")
    return problems


def header_in_text(text: str):
    """First line in arbitrary text that is a valid CC header (or None)."""
    for line in text.splitlines():
        stripped = line.strip().strip("`").strip()
        if CC_HEADER.match(stripped):
            return stripped
    return None


def validate_pr(doc) -> list[str]:
    problems = []
    title = (getattr(doc, "title", "") or "").strip()
    if not title:
        problems.append("PR title is empty")
    elif not CC_HEADER.match(title):
        problems.append(f"PR title '{title}' should be a Conventional Commit header")
    if len(title) > MAX_HEADER_LEN:
        problems.append(f"PR title is {len(title)} chars; keep it <= {MAX_HEADER_LEN}")
    if not getattr(doc, "changes", None):
        problems.append("PR must list at least one change bullet")
    return problems
