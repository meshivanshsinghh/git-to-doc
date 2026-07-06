"""analyze_diff must fail loudly, never return a silent stub, when repairs are
exhausted. A fake all-clear commit is a trust hole; the same principle the audit
engine already enforces.
"""

import json

import pytest

from git_to_doc.model import analyze_diff, CommitDoc, GenerationError


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
