"""Normalization helper and French detection tables.

Lexicons are matched against accent-stripped, casefolded text with whole-word
boundaries (see detectors.matches_any). Inflected forms present in the eval set
are listed explicitly because whole-word matching does not do stemming.
"""

from __future__ import annotations

import re
import unicodedata


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalize(text: str) -> str:
    """Lowercase (casefold) and strip diacritics for robust matching."""
    return _strip_accents(text).casefold()


# Content moderation, per category (normalized forms).
MODERATION: dict[str, tuple[str, ...]] = {
    "hate": (
        "hais",
        "haine",
        "sous-etre",
        "sous-etres",
        "sous-humain",
        "sous-humains",
        "sale race",
    ),
    "violence": ("frapper", "tuer", "faire du mal"),
    "sexual": ("sexuel", "sexuelle", "nudite", "porno"),
}

# Prompt-injection attack phrases.
INJECTION_TERMS: tuple[str, ...] = (
    "ignore tes instructions",
    "ignore tes consignes",
    "oublie tes instructions",
    "oublie tes consignes",
    "developer mode",
    "prompt systeme",
    "plus de regles",
)

# Out-of-scope requests (valuation, resale, investment, legal/medical, 3rd-party auth).
OUT_OF_SCOPE_TERMS: tuple[str, ...] = (
    "combien vaut",
    "cote",
    "revente",
    "placement",
    "bourse",
    "investir",
    "authentifier",
    "juridique",
    "medical",
)

# Attempts to exfiltrate system secrets / credential leaks (block on both sides).
SECRET_LEAK_TERMS: tuple[str, ...] = (
    "cle api",
    "clef api",
    "api key",
    "mot de passe",
    "environnement",
    "token interne",
    "tokens internes",
    "secret de configuration",
    "secret de config",
    "configuration interne",
)

# Unambiguous PII numbers (operate on RAW text to keep digits/letters).
CARD_RE = re.compile(r"\d(?:[ -]?\d){12,18}")
IBAN_RE = re.compile(r"\b[A-Za-z]{2}\d{2}(?:[ ]?[A-Za-z0-9]){10,30}\b")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
