"""Fact extraction from conversation.

The ``Extractor`` protocol has two implementations behind it: this deterministic
one (regex/keyword entity pinning, offline, testable) and — in a later increment
— a LangMem/LLM one for production. Wiring the extractor into automatic ingestion
(R4 overflow) is deferred; this module only defines and tests the extraction.
"""

from __future__ import annotations

import re
from typing import Protocol

from langchain_core.messages import BaseMessage, HumanMessage

from .facts import Fact

_ORDER_RE = re.compile(r"O-\d{4}-\d{4}")
_TUTOIEMENT_HINTS = ("tutoie", "tutoyer")
_PRO_HINTS = ("client pro", "revendeur", "professionnel", "compte pro")


class Extractor(Protocol):
    def extract(self, messages: list[BaseMessage]) -> list[Fact]: ...


class DeterministicExtractor:
    """Offline entity-pinning extractor bound to one user."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def extract(self, messages: list[BaseMessage]) -> list[Fact]:
        text = " ".join(str(m.content) for m in messages if isinstance(m, HumanMessage))
        low = text.lower()
        facts: list[Fact] = []

        for order_id in dict.fromkeys(_ORDER_RE.findall(text)):
            facts.append(
                Fact.new(self._user_id, "order_info", "order", order_id, source="extractor")
            )
        if any(h in low for h in _TUTOIEMENT_HINTS):
            facts.append(
                Fact.new(self._user_id, "preference", "tutoiement", "oui", source="extractor")
            )
        if any(h in low for h in _PRO_HINTS):
            facts.append(
                Fact.new(self._user_id, "profile", "segment", "client pro", source="extractor")
            )
        return facts
