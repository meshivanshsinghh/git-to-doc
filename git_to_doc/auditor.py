"""
auditor.py — orchestrates a multi-model audit of a diff against its commit message.

Each auditor is a model from a different family, so their blind spots don't overlap;
we run the same diff through all of them and collect one AuditReport apiece.
"""

from typing import Literal

from pydantic import BaseModel

from git_to_doc.model import audit_diff, AuditReport

# Auditor panels by host RAM — each a pair of strong code models from *different*
# families so their blind spots don't overlap. The 16GB tier is the default.
# (deepseek-coder-v2:latest is the 16b model, same weights as the :16b tag; we use
#  :latest to match what ollama pulls by default and the earlier default choice.)
AUDITOR_TIERS = {
    "8gb":  ["gemma2:2b", "qwen2.5-coder:7b"],
    "16gb": ["qwen2.5-coder:14b", "deepseek-coder-v2:latest"],
    "32gb": ["qwen2.5-coder:32b", "gpt-oss:120b"],
}

DEFAULT_AUDITORS = AUDITOR_TIERS["16gb"]

# How close two line citations must be to count as the same finding.
LINE_TOLERANCE = 3
_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


def recommend_auditors() -> list[str]:
    """Detect available RAM via psutil and recommend an appropriate auditor tier."""
    try:
        import psutil
        gb = psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        return AUDITOR_TIERS["16gb"]   # safe default when RAM can't be detected
    if gb < 12:
        return AUDITOR_TIERS["8gb"]
    if gb < 24:
        return AUDITOR_TIERS["16gb"]
    return AUDITOR_TIERS["32gb"]


def run_audit(diff_text, original_message, auditors=None) -> list[AuditReport]:
    """Run the diff through N auditors from different families.
    Returns one AuditReport per auditor."""
    auditors = auditors or DEFAULT_AUDITORS
    return [audit_diff(diff_text, m, original_message) for m in auditors]


class MergedDivergence(BaseModel):
    description: str
    file: str
    line: int
    confidence: Literal["high", "possible"]
    # high = all auditors flagged; possible = only one
    flagged_by: list[str]  # which auditor models raised this


def merge_audits(reports: list[AuditReport]) -> list[MergedDivergence]:
    """Merge N audit reports. A divergence is 'high' confidence if ALL auditors
    flagged the same file+line (within 3 lines tolerance). Otherwise 'possible'.

    Fuzzy matching: two divergences match if they're on the same file AND their
    line numbers are within 3 lines of each other. The merged output keeps the
    earlier line number and the description from the higher-severity divergence.
    """
    all_models = {r.auditor_model for r in reports}

    # Flatten every divergence, tagged with the model that raised it.
    tagged = [(d, r.auditor_model) for r in reports for d in r.divergences]

    # Single-linkage clustering by file + line proximity. Members of a cluster
    # always share a file, so we can test the file against any member.
    clusters: list[list] = []
    for div, model in tagged:
        for cluster in clusters:
            if cluster[0][0].file == div.file and any(
                    abs(other.line - div.line) <= LINE_TOLERANCE for other, _ in cluster):
                cluster.append((div, model))
                break
        else:
            clusters.append([(div, model)])

    merged = []
    for cluster in clusters:
        flagged_by = sorted({model for _, model in cluster})
        representative = max((d for d, _ in cluster),
                             key=lambda d: _SEVERITY_RANK.get(d.severity, 0))
        merged.append(MergedDivergence(
            description=representative.description,
            file=cluster[0][0].file,
            line=min(d.line for d, _ in cluster),
            confidence="high" if all_models and set(flagged_by) == all_models else "possible",
            flagged_by=flagged_by,
        ))

    # Surface high-confidence findings first, then order by location.
    merged.sort(key=lambda m: (m.confidence != "high", m.file, m.line))
    return merged
