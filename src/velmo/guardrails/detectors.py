"""Deterministic, offline guardrail detectors.

Text-category detectors match whole words on normalized (accent-stripped,
casefolded) text. PII-number detectors run on raw text to keep digits/letters.
"""

from __future__ import annotations

import re

from .decision import Identity
from .patterns import (
    CARD_RE,
    EMAIL_RE,
    IBAN_RE,
    INJECTION_TERMS,
    MODERATION,
    OUT_OF_SCOPE_TERMS,
    SECRET_LEAK_TERMS,
    SUPPORT_EMAILS,
    normalize,
)


def luhn_valid(digits: str) -> bool:
    """Standard Luhn checksum over a digit string."""
    if not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def matches_any(text_norm: str, terms: tuple[str, ...]) -> str | None:
    """Return the first term found as a whole word/phrase, else None."""
    for term in terms:
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text_norm):
            return term
    return None


def detect_moderation(text: str) -> str | None:
    norm = normalize(text)
    for category, terms in MODERATION.items():
        if matches_any(norm, terms):
            return category
    return None


def detect_injection(text: str) -> str | None:
    return "prompt_injection" if matches_any(normalize(text), INJECTION_TERMS) else None


def detect_out_of_scope(text: str) -> str | None:
    return "out_of_scope" if matches_any(normalize(text), OUT_OF_SCOPE_TERMS) else None


def detect_secret_leak(text: str) -> str | None:
    return "secret_leak" if matches_any(normalize(text), SECRET_LEAK_TERMS) else None


def scan_secrets(text: str) -> tuple[str, bool]:
    """Mask card numbers (Luhn-checked) and IBANs. Return (masked_text, found)."""
    found = False

    def repl_iban(_: re.Match[str]) -> str:
        nonlocal found
        found = True
        return "[REDACTED_IBAN]"

    def repl_card(match: re.Match[str]) -> str:
        nonlocal found
        digits = re.sub(r"\D", "", match.group())
        if 13 <= len(digits) <= 19 and luhn_valid(digits):
            found = True
            return "[REDACTED_CARD]"
        return match.group()

    # IBAN first so its digit run is not partially consumed by the card scan.
    masked = IBAN_RE.sub(repl_iban, text)
    masked = CARD_RE.sub(repl_card, masked)
    return masked, found


def foreign_email(text: str, identity: Identity) -> str | None:
    """Return an email in `text` that is not the session customer's, else None.

    Velmo's own support/contact addresses (SUPPORT_EMAILS) are never flagged:
    the agent legitimately surfaces those in FAQ/contact answers.
    """
    if not identity.email:
        return None
    own = identity.email.casefold()
    for email in EMAIL_RE.findall(text):
        email_norm = email.casefold()
        if email_norm != own and email_norm not in SUPPORT_EMAILS:
            return email
    return None
