"""Unit tests for the French refusal templates."""

from __future__ import annotations

from velmo.guardrails.decision import CATEGORIES
from velmo.guardrails.refusals import refusal_for


def test_every_blocking_category_has_a_non_empty_french_refusal():
    for category in CATEGORIES:
        message = refusal_for(category)
        assert message and isinstance(message, str)


def test_unknown_category_falls_back_to_generic():
    assert refusal_for(None)
    assert refusal_for("does-not-exist")
