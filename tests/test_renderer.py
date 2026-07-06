"""Tests for the phase-4 renderers: render_audit_report + the PR-body Audit section.

Pure string functions — ANSI is stripped before asserting on content.
"""

import re

from git_to_doc.model import PRDoc
from git_to_doc.auditor import MergedDivergence
from git_to_doc.renderer import render_audit_report, render_pr_body


def _strip(s):
    return re.sub(r"\033\[[0-9;]*m", "", s)


def _md(file, line, confidence, flagged_by, description="something changed"):
    return MergedDivergence(description=description, file=file, line=line,
                            confidence=confidence, flagged_by=flagged_by)


AUDITORS = ["qwen2.5-coder:14b", "deepseek-coder-v2:latest"]


# ── render_audit_report ─────────────────────────────────────────────────────────
def test_audit_report_clean_when_no_high():
    out = _strip(render_audit_report([], "fix: tidy things", AUDITORS, source="abc123f"))
    assert "Verifying commit abc123f" in out
    assert "Auditors: qwen2.5-coder:14b, deepseek-coder-v2:latest (2 independent, cross-family)" in out
    assert "ORIGINAL MESSAGE" in out
    assert "fix: tidy things" in out
    assert "✅ Original message matches the diff" in out
    assert "DIVERGENCES" not in out          # no high section


def test_audit_report_high_divergence():
    merged = [_md("app/auth.py", 13, "high",
                  ["qwen2.5-coder:14b", "deepseek-coder-v2:latest"],
                  "login now returns a token, not a bool")]
    out = _strip(render_audit_report(merged, "fix: tidy login", AUDITORS, source="abc123f"))
    assert "1 DIVERGENCE — all auditors agree" in out
    assert "login now returns a token, not a bool" in out
    assert "app/auth.py:13" in out
    assert "✅" not in out                    # high present → no all-clear line


def test_audit_report_possible_divergence():
    merged = [_md("x.py", 5, "possible", ["qwen2.5-coder:14b"], "adds a side effect")]
    out = _strip(render_audit_report(merged, "msg", AUDITORS))
    assert "✅ Original message matches the diff" in out   # no highs → all-clear line
    assert "1 POSSIBLE divergence — only one auditor flagged" in out
    assert "adds a side effect" in out
    assert "x.py:5" in out
    assert "flagged by qwen2.5-coder:14b, others did not — verify manually" in out


def test_audit_report_benchmark_shows_measured_numbers():
    out = _strip(render_audit_report([], "m", AUDITORS))
    assert "69% precision, 36% recall" in out
    assert "synthetic n=168" in out
    assert "16GB tier" in out
    assert "BENCHMARKS.md" in out


def test_audit_report_benchmark_shows_precision_when_given():
    out = _strip(render_audit_report([], "m", AUDITORS, precision=91))
    assert "Benchmark: 91% precision on git-to-doc eval set (v0.3.0)" in out


# ── render_pr_body Audit section ─────────────────────────────────────────────────
def _pr():
    return PRDoc(title="feat: add thing", summary="Adds a thing.",
                 changes=["add the thing"], test_plan="run it", breaking=False)


def test_pr_body_no_audit_section_when_none():
    body = render_pr_body(_pr(), audit=None)
    assert "## Audit" not in body


def test_pr_body_audit_clean_when_empty_list():
    body = render_pr_body(_pr(), audit=[])
    assert "## Audit" in body
    assert "no high-confidence divergences" in body


def test_pr_body_audit_lists_high_divergences():
    audit = [_md("core.py", 42, "high", ["m1", "m2"], "silently drops errors")]
    body = render_pr_body(_pr(), audit=audit)
    assert "## Audit" in body
    assert "`core.py:42`" in body
    assert "silently drops errors" in body
