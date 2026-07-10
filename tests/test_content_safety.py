"""The Content Safety seam is inert offline (no endpoint configured)."""

from __future__ import annotations

from velmo.guardrails.content_safety import get_moderator


def test_get_moderator_is_none_without_endpoint(monkeypatch):
    monkeypatch.delenv("AZURE_CONTENT_SAFETY_ENDPOINT", raising=False)
    assert get_moderator() is None
