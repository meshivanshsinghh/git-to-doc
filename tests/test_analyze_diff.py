"""analyze_diff must fail loudly, never return a silent stub, when repairs are
exhausted. A fake all-clear commit is a trust hole; the same principle the audit
engine already enforces.
"""

import json

import pytest

from git_to_doc.model import analyze_diff, analyze_pr, CommitDoc, PRDoc, GenerationError, _fit_header
from git_to_doc.validate import build_header


class FakeClient:
    """Scripted stand-in for ollama.Client — pops canned responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def chat(self, model, messages, format=None, options=None):
        self.calls += 1
        if not self._responses:
            raise AssertionError("FakeClient exhausted — analyze_diff made an extra call")
        return {"message": {"content": self._responses.pop(0)}}


VALID_COMMIT_JSON = json.dumps({
    "type": "feat", "scope": "auth", "subject": "add oauth login",
    "body": None, "breaking": False,
    "changelog_entry": "- add oauth login",
    "plain_english": "Adds OAuth login to the auth module.",
    "human_title": "Add OAuth login",
    "review_notes": "Check token handling and refresh flow.",
    "file_notes": {},
})


def test_generation_error_is_a_valueerror():
    # Subclassing ValueError keeps `except ValueError` / older callers working.
    assert issubclass(GenerationError, ValueError)


def test_analyze_diff_raises_on_exhaustion_no_stub(monkeypatch):
    # Every attempt returns unparseable output → all retries fail → must raise,
    # NOT return a fabricated "chore: update codebase" stub.
    fake = FakeClient(["not valid json at all"] * 3)
    monkeypatch.setattr("git_to_doc.model._client", fake)

    with pytest.raises(GenerationError):
        analyze_diff("some diff", model="whatever", max_retries=3)

    assert fake.calls == 3   # it genuinely retried the full budget


def test_analyze_diff_returns_on_valid_output(monkeypatch):
    # Happy path still works — the fail-loud change didn't break generation.
    fake = FakeClient([VALID_COMMIT_JSON])
    monkeypatch.setattr("git_to_doc.model._client", fake)

    doc = analyze_diff("some diff", model="whatever")

    assert isinstance(doc, CommitDoc)
    assert doc.type == "feat"
    assert doc.subject == "add oauth login"
    assert fake.calls == 1   # no wasted retries on valid output


# ── analyze_pr: same fail-loud contract (no stub PR on exhaustion) ──────────────
VALID_PR_JSON = json.dumps({
    "title": "feat(auth): add oauth login", "summary": "Adds OAuth login.",
    "changes": ["add oauth login flow"], "test_plan": "run the suite", "breaking": False,
})


def test_analyze_pr_raises_on_exhaustion_no_stub(monkeypatch):
    fake = FakeClient(["not valid json at all"] * 3)
    monkeypatch.setattr("git_to_doc.model._client", fake)
    with pytest.raises(GenerationError):
        analyze_pr("some diff", model="whatever", max_retries=3)
    assert fake.calls == 3


def test_analyze_pr_returns_on_valid_output(monkeypatch):
    fake = FakeClient([VALID_PR_JSON])
    monkeypatch.setattr("git_to_doc.model._client", fake)
    pr = analyze_pr("some diff", model="whatever")
    assert isinstance(pr, PRDoc)
    assert pr.title == "feat(auth): add oauth login"
    assert fake.calls == 1


# ── _fit_header: normalize over-long headers instead of failing (not a stub) ─────
def test_fit_header_trims_overlong_subject():
    doc = CommitDoc(
        type="refactor", scope="peft",
        subject="rework the lora adapter to support configurable rank and alpha scaling",
        body=None, breaking=False, changelog_entry="- rework lora",
        plain_english="x", human_title="x", review_notes="x", file_notes={})
    assert len(build_header(doc)) > 72          # starts too long
    _fit_header(doc)
    assert len(build_header(doc)) <= 72         # now fits the spec
    assert doc.subject and not doc.subject.endswith(" ")


def test_analyze_diff_trims_long_header_instead_of_failing(monkeypatch):
    # Otherwise-valid commit whose header exceeds 72 chars: accepted with a trimmed
    # subject on the first pass, NOT raised as a GenerationError.
    payload = json.dumps({
        "type": "refactor", "scope": "peft",
        "subject": "rework the lora adapter to support configurable rank and alpha scaling now",
        "body": None, "breaking": False, "changelog_entry": "- rework lora adapter",
        "plain_english": "Reworks the LoRA adapter.", "human_title": "Rework LoRA adapter",
        "review_notes": "Check rank/alpha handling.", "file_notes": {}})
    fake = FakeClient([payload])
    monkeypatch.setattr("git_to_doc.model._client", fake)
    doc = analyze_diff("some diff", model="whatever")
    assert isinstance(doc, CommitDoc)
    assert len(build_header(doc)) <= 72
    assert fake.calls == 1        # trimmed and accepted, no wasted retries
