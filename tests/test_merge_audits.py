"""Unit tests for auditor.merge_audits — fuzzy dedup + confidence assignment.

Pure logic, no ollama: builds AuditReports directly and checks the merge output.
"""

from git_to_doc.model import AuditReport, Divergence
from git_to_doc.auditor import merge_audits, MergedDivergence


def _div(file, line, severity="medium", description="x"):
    return Divergence(description=description, file=file, line=line, severity=severity)


def _report(model, *divs):
    return AuditReport(independent_description="d", divergences=list(divs), auditor_model=model)


def test_empty_reports_merge_to_nothing():
    assert merge_audits([]) == []


def test_no_divergences_merge_to_nothing():
    assert merge_audits([_report("m1"), _report("m2")]) == []


def test_both_auditors_same_location_is_high_confidence():
    reports = [
        _report("m1", _div("app/auth.py", 13, "medium", "returns a token")),
        _report("m2", _div("app/auth.py", 15, "high", "now returns an auth token, not a bool")),
    ]
    merged = merge_audits(reports)
    assert len(merged) == 1
    m = merged[0]
    assert isinstance(m, MergedDivergence)
    assert m.confidence == "high"
    assert m.flagged_by == ["m1", "m2"]
    assert m.line == 13                                       # earlier line wins
    assert m.description == "now returns an auth token, not a bool"  # higher severity wins


def test_single_auditor_is_possible():
    reports = [
        _report("m1", _div("app/auth.py", 13, "high")),
        _report("m2"),   # m2 flagged nothing
    ]
    merged = merge_audits(reports)
    assert len(merged) == 1
    assert merged[0].confidence == "possible"
    assert merged[0].flagged_by == ["m1"]


def test_same_file_far_apart_do_not_merge():
    reports = [
        _report("m1", _div("app/auth.py", 13, "high")),
        _report("m2", _div("app/auth.py", 40, "low")),   # >3 lines away
    ]
    merged = merge_audits(reports)
    assert len(merged) == 2
    assert all(m.confidence == "possible" for m in merged)


def test_within_three_lines_merges():
    reports = [
        _report("m1", _div("a.py", 10, "medium")),
        _report("m2", _div("a.py", 13, "medium")),   # exactly 3 apart → still merges
    ]
    merged = merge_audits(reports)
    assert len(merged) == 1
    assert merged[0].confidence == "high"
    assert merged[0].line == 10


def test_different_files_do_not_merge():
    reports = [
        _report("m1", _div("a.py", 5, "high")),
        _report("m2", _div("b.py", 5, "high")),
    ]
    merged = merge_audits(reports)
    assert len(merged) == 2
    assert {m.file for m in merged} == {"a.py", "b.py"}
    assert all(m.confidence == "possible" for m in merged)


def test_high_confidence_sorts_before_possible():
    reports = [
        _report("m1", _div("a.py", 100, "low"), _div("z.py", 5, "high")),
        _report("m2", _div("z.py", 6, "high")),   # z.py flagged by both → high
    ]
    merged = merge_audits(reports)
    assert merged[0].file == "z.py" and merged[0].confidence == "high"
    assert merged[1].file == "a.py" and merged[1].confidence == "possible"


def test_three_auditors_partial_agreement_is_possible():
    # Only 2 of 3 auditors flag the spot → not ALL → possible.
    reports = [
        _report("m1", _div("a.py", 10, "high")),
        _report("m2", _div("a.py", 11, "high")),
        _report("m3"),
    ]
    merged = merge_audits(reports)
    assert len(merged) == 1
    assert merged[0].confidence == "possible"
    assert merged[0].flagged_by == ["m1", "m2"]


def test_three_auditors_full_agreement_is_high():
    reports = [
        _report("m1", _div("a.py", 10, "high")),
        _report("m2", _div("a.py", 11, "medium")),
        _report("m3", _div("a.py", 12, "low")),
    ]
    merged = merge_audits(reports)
    assert len(merged) == 1
    assert merged[0].confidence == "high"
    assert merged[0].flagged_by == ["m1", "m2", "m3"]
    assert merged[0].line == 10
