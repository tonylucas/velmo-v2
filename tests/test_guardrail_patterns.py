"""Unit tests for guardrail normalization and pattern tables."""

from __future__ import annotations

from velmo.guardrails.patterns import (
    CARD_RE,
    EMAIL_RE,
    IBAN_RE,
    MODERATION,
    normalize,
)


def test_normalize_strips_accents_and_casefolds():
    assert normalize("Étrangers SOUS-ÊTRES") == "etrangers sous-etres"


def test_moderation_table_has_three_categories():
    assert set(MODERATION) == {"hate", "violence", "sexual"}


def test_card_regex_matches_spaced_number():
    assert CARD_RE.search("carte 4111 1111 1111 1111.") is not None


def test_card_regex_ignores_order_id():
    assert CARD_RE.search("commande O-2024-0101") is None


def test_iban_regex_matches():
    assert IBAN_RE.search("IBAN FR76 3000 6000 0112 3456 7890 189") is not None


def test_email_regex_matches():
    assert EMAIL_RE.search("ecris a marc@velmo.fr stp") is not None
