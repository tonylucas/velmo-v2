"""Fact extraction from conversation.

The ``Extractor`` protocol has two implementations behind it: this deterministic
one (regex/keyword entity pinning, offline, testable) and — in production — a
LangMem-backed one (see ``get_extractor``). Both honour the same eligibility
contract: only durable facts about the customer, across the four fact types;
off-topic or ephemeral content yields nothing.
"""

from __future__ import annotations

import re
from typing import Protocol

from langchain_core.messages import BaseMessage, HumanMessage

from .facts import Fact

_ORDER_RE = re.compile(r"O-\d{4}-\d{4}")
_SIZE_RE = re.compile(
    # First-person statements of one's own size — avoids matching stock questions
    # like "la taille L est-elle dispo ?" (no "je"/"ma" cue).
    r"\b(?:je\s+chausse|je\s+fais|je\s+taille|ma\s+pointure)\b[^.\n]*?\b(XXL|XL|XS|S|M|L)\b",
    re.IGNORECASE,
)
_TUTOIEMENT_HINTS = ("tutoie", "tutoyer")
_PRO_HINTS = ("client pro", "revendeur", "professionnel", "compte pro")


class Extractor(Protocol):
    def extract(self, user_id: str, messages: list[BaseMessage]) -> list[Fact]: ...


class DeterministicExtractor:
    """Offline entity-pinning extractor. Selective by construction: it only pins
    known patterns, so it cannot emit off-topic facts."""

    def extract(self, user_id: str, messages: list[BaseMessage]) -> list[Fact]:
        text = " ".join(str(m.content) for m in messages if isinstance(m, HumanMessage))
        low = text.lower()
        facts: list[Fact] = []

        for order_id in dict.fromkeys(_ORDER_RE.findall(text)):
            facts.append(Fact.new(user_id, "order_info", "order", order_id, source="extractor"))
        if any(h in low for h in _TUTOIEMENT_HINTS):
            facts.append(Fact.new(user_id, "preference", "tutoiement", "oui", source="extractor"))
        if any(h in low for h in _PRO_HINTS):
            facts.append(Fact.new(user_id, "profile", "segment", "client pro", source="extractor"))
        size = _SIZE_RE.search(text)
        if size:
            facts.append(
                Fact.new(user_id, "profile", "pointure", size.group(1).upper(), source="extractor")
            )
        return facts
