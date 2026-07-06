"""
auditor.py — orchestrates a multi-model audit of a diff against its commit message.

Each auditor is a model from a different family, so their blind spots don't overlap;
we run the same diff through all of them and collect one AuditReport apiece.
"""

from git_to_doc.model import audit_diff, AuditReport

# Default panel: two strong code models from independent families.
DEFAULT_AUDITORS = ["qwen2.5-coder:14b", "deepseek-coder-v2:16b"]


def run_audit(diff_text, original_message, auditors=None) -> list[AuditReport]:
    """Run the diff through N auditors from different families.
    Returns one AuditReport per auditor."""
    auditors = auditors or DEFAULT_AUDITORS
    return [audit_diff(diff_text, m, original_message) for m in auditors]
