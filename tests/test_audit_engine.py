"""Unit tests for the audit engine (git_to_doc.model.audit_diff + git_to_doc.auditor).

No network, no ollama: the model client is replaced with a scripted fake, so these
tests are deterministic and run anywhere.
"""

import json

import pytest
from pydantic import ValidationError

from git_to_doc.model import audit_diff, AuditReport, Divergence
from git_to_doc import auditor
from git_to_doc.auditor import run_audit, DEFAULT_AUDITORS


SAMPLE_DIFF = """diff --git a/app/auth.py b/app/auth.py
index 1234567..89abcde 100644
--- a/app/auth.py
+++ b/app/auth.py
@@ -10,7 +10,9 @@ def login(user, password):
     if check(user, password):
-        return True
+        log_login(user)
+        return issue_token(user)
     return False
"""

ORIGINAL_MESSAGE = "fix(auth): tidy up the login function"

PHASE_A_TEXT = (
    "In app/auth.py, login() at line 13 now calls log_login(user) and returns "
    "issue_token(user) instead of returning True."
)

# auditor_model here is deliberately WRONG — audit_diff must overwrite it with the
# model it actually called.
VALID_JSON = json.dumps({
    "independent_description":
        "login() now records the attempt and returns an auth token instead of a bool.",
    "divergences": [{
        "description": "login() now returns a token and writes an audit-log entry; "
                       "the message mentions neither",
        "file": "app/auth.py",
        "line": 13,
        "severity": "high",
    }],
    "auditor_model": "some-other-model:99b",
})

# A divergence with no `line` — the exact failure the citation rule must catch.
INVALID_JSON_NO_LINE = json.dumps({
    "independent_description": "login changed",
    "divergences": [{
        "description": "returns a token now",
        "file": "app/auth.py",
        "severity": "high",
    }],
    "auditor_model": "m",
})


class FakeClient:
    """Scripted stand-in for ollama.Client — pops canned responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def chat(self, model, messages, format=None, options=None):
        # Snapshot messages at call time — audit_diff mutates the same list across
        # passes, and a real client serializes it per call, so we must too.
        self.calls.append({"model": model,
                           "messages": [dict(m) for m in messages],
                           "format": format})
        if not self._responses:
            raise AssertionError("FakeClient exhausted — audit_diff made an extra call")
        return {"message": {"content": self._responses.pop(0)}}


# ── Schema: citations are mandatory ─────────────────────────────────────────────
def test_divergence_rejects_missing_file():
    with pytest.raises(ValidationError):
        Divergence(description="x", line=5, severity="low")


def test_divergence_rejects_missing_line():
    with pytest.raises(ValidationError):
        Divergence(description="x", file="app/auth.py", severity="low")


def test_divergence_rejects_empty_file():
    with pytest.raises(ValidationError):
        Divergence(description="x", file="", line=5, severity="low")


def test_divergence_rejects_nonpositive_line():
    with pytest.raises(ValidationError):
        Divergence(description="x", file="app/auth.py", line=0, severity="low")


def test_auditreport_rejects_uncited_divergence():
    payload = {
        "independent_description": "does X",
        "divergences": [{"description": "y", "file": "app/auth.py", "severity": "low"}],
        "auditor_model": "m",
    }
    with pytest.raises(ValidationError):
        AuditReport.model_validate(payload)


def test_auditreport_accepts_empty_divergences():
    report = AuditReport(independent_description="d", divergences=[], auditor_model="m")
    assert report.divergences == []


# ── audit_diff: two-pass, blind-first, self-repairing ───────────────────────────
def test_audit_diff_returns_valid_report(monkeypatch):
    fake = FakeClient([PHASE_A_TEXT, VALID_JSON])
    monkeypatch.setattr("git_to_doc.model._client", fake)

    report = audit_diff(SAMPLE_DIFF, "qwen2.5-coder:14b", ORIGINAL_MESSAGE)

    assert isinstance(report, AuditReport)
    # auditor_model is recorded by us, not trusted from the model's own output
    assert report.auditor_model == "qwen2.5-coder:14b"
    assert len(report.divergences) == 1
    d = report.divergences[0]
    assert d.file == "app/auth.py"
    assert d.line == 13
    assert d.severity == "high"

    # exactly two model calls: pass 1 free-form, pass 2 schema-constrained
    assert len(fake.calls) == 2
    assert fake.calls[0]["format"] is None
    assert fake.calls[1]["format"] is not None


def test_audit_diff_pass1_does_not_see_original_message(monkeypatch):
    fake = FakeClient([PHASE_A_TEXT, VALID_JSON])
    monkeypatch.setattr("git_to_doc.model._client", fake)

    audit_diff(SAMPLE_DIFF, "qwen2.5-coder:14b", "SECRET-SENTINEL-MESSAGE")

    pass1 = "\n".join(m["content"] for m in fake.calls[0]["messages"])
    assert "SECRET-SENTINEL-MESSAGE" not in pass1   # blind first
    pass2 = "\n".join(m["content"] for m in fake.calls[1]["messages"])
    assert "SECRET-SENTINEL-MESSAGE" in pass2        # revealed only in the compare pass


def test_audit_diff_self_repairs_missing_citation(monkeypatch):
    fake = FakeClient([PHASE_A_TEXT, INVALID_JSON_NO_LINE, VALID_JSON])
    monkeypatch.setattr("git_to_doc.model._client", fake)

    report = audit_diff(SAMPLE_DIFF, "qwen2.5-coder:14b", ORIGINAL_MESSAGE)

    assert isinstance(report, AuditReport)
    assert report.divergences[0].line == 13
    # pass 1 + rejected pass 2 + repaired pass 2
    assert len(fake.calls) == 3


def test_audit_diff_raises_rather_than_false_all_clear(monkeypatch):
    fake = FakeClient([PHASE_A_TEXT, INVALID_JSON_NO_LINE, INVALID_JSON_NO_LINE,
                       INVALID_JSON_NO_LINE])
    monkeypatch.setattr("git_to_doc.model._client", fake)

    with pytest.raises(ValueError):
        audit_diff(SAMPLE_DIFF, "qwen2.5-coder:14b", ORIGINAL_MESSAGE)


# ── run_audit: one report per auditor ───────────────────────────────────────────
def test_run_audit_one_report_per_default_auditor(monkeypatch):
    seen = []

    def fake_audit(diff_text, model, original_message):
        seen.append(model)
        return AuditReport(independent_description="d", divergences=[], auditor_model=model)

    monkeypatch.setattr(auditor, "audit_diff", fake_audit)

    reports = run_audit(SAMPLE_DIFF, ORIGINAL_MESSAGE)

    assert len(reports) == len(DEFAULT_AUDITORS)
    assert [r.auditor_model for r in reports] == DEFAULT_AUDITORS
    assert seen == DEFAULT_AUDITORS


def test_run_audit_honors_custom_auditors(monkeypatch):
    monkeypatch.setattr(
        auditor, "audit_diff",
        lambda d, m, o: AuditReport(independent_description="d",
                                    divergences=[], auditor_model=m))
    reports = run_audit(SAMPLE_DIFF, ORIGINAL_MESSAGE, auditors=["solo-model:7b"])
    assert len(reports) == 1
    assert reports[0].auditor_model == "solo-model:7b"


# ── Extra coverage: enum, parser robustness, input handling ─────────────────────
def test_divergence_rejects_invalid_severity():
    with pytest.raises(ValidationError):
        Divergence(description="x", file="app/auth.py", line=1, severity="critical")


def test_audit_diff_tolerates_json_fences(monkeypatch):
    # Some models wrap JSON in ```json fences despite the schema; _parse must cope.
    fenced = "```json\n" + VALID_JSON + "\n```"
    fake = FakeClient([PHASE_A_TEXT, fenced])
    monkeypatch.setattr("git_to_doc.model._client", fake)

    report = audit_diff(SAMPLE_DIFF, "qwen2.5-coder:14b", ORIGINAL_MESSAGE)

    assert isinstance(report, AuditReport)
    assert report.divergences[0].line == 13


def test_audit_diff_truncates_oversized_diff(monkeypatch):
    huge = "diff --git a/big.py b/big.py\n" + ("+x\n" * 8000)  # ~24k chars, over the cap
    fake = FakeClient([PHASE_A_TEXT, VALID_JSON])
    monkeypatch.setattr("git_to_doc.model._client", fake)

    audit_diff(huge, "qwen2.5-coder:14b", ORIGINAL_MESSAGE)

    pass1 = "\n".join(m["content"] for m in fake.calls[0]["messages"])
    assert "[truncated]" in pass1
    assert len(pass1) < len(huge)   # the full body was not sent
