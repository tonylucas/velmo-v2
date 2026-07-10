"""Fact extraction from conversation.

The ``Extractor`` protocol has two implementations behind it: this deterministic
one (regex/keyword entity pinning, offline, testable) and — in production — a
LangMem-backed one (see ``get_extractor``). Both honour the same eligibility
contract: only durable facts about the customer, across the four fact types;
off-topic or ephemeral content yields nothing.
"""

from __future__ import annotations

import os
import re
from typing import Protocol

from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel

from .facts import FACT_TYPES, Fact

_ORDER_RE = re.compile(r"O-\d{4}-\d{4}")
_SIZE_RE = re.compile(
    # First-person statements of one's own size, with the size token immediately
    # adjacent to the cue — avoids matching unrelated clauses like "je fais appel
    # à l'équipe" or stock questions like "la taille L est-elle dispo ?".
    r"\b(?:je\s+chausse|je\s+fais|je\s+taille|ma\s+pointure)\s+"
    r"(?:du\s+|un\s+|une\s+|taille\s+|le\s+|est\s+)?(XXL|XL|XS|S|M|L)\b",
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


ELIGIBILITY_INSTRUCTIONS = (
    "Extract only durable facts about the customer that fit one of these types: "
    "preference (e.g. wants to be addressed informally / 'tutoiement'), "
    "profile (e.g. shoe/jersey size 'pointure', pro-customer segment), "
    "order_info (an order number the customer refers to), "
    "dispute (an ongoing dispute the customer raises). "
    "Use a short 'key' (the attribute name, e.g. 'tutoiement', 'pointure', 'segment', 'order') "
    "and a concise 'content' value. Ignore small talk, ephemeral remarks and anything off-topic. "
    "If there is no durable fact, extract nothing."
)


class MemoryFact(BaseModel):
    """Schema LangMem extracts into (mapped to velmo Fact by LangMemExtractor)."""

    fact_type: str
    key: str
    content: str


class LangMemExtractor:
    """Production extractor: LangMem's stateless memory manager over the project
    LLM. Storage-agnostic — the manager only extracts; persistence and FR-009
    consolidation stay in FactStore.write. Not exercised offline (langmem absent);
    this is the prod seam, like ChromaFactStore."""

    def __init__(self, model) -> None:
        from langmem import create_memory_manager

        self._manager = create_memory_manager(
            model,
            schemas=[MemoryFact],
            instructions=ELIGIBILITY_INSTRUCTIONS,
            enable_inserts=True,
            enable_updates=True,
            enable_deletes=False,
        )

    def extract(self, user_id: str, messages: list[BaseMessage]) -> list[Fact]:
        extracted = self._manager.invoke({"messages": messages})
        facts: list[Fact] = []
        for item in extracted:
            memory = item.content
            if memory.fact_type in FACT_TYPES:
                facts.append(
                    Fact.new(
                        user_id, memory.fact_type, memory.key, memory.content, source="extractor"
                    )
                )
        return facts


def get_extractor() -> Extractor:
    """Return the LangMem extractor if the LLM and langmem are available, else the
    deterministic one. Mirrors get_chat_model() / get_fact_store()."""
    if os.getenv("AZURE_AI_INFERENCE_ENDPOINT"):
        try:
            import langmem  # noqa: F401
        except ImportError:
            return DeterministicExtractor()
        from ..llm import get_chat_model

        return LangMemExtractor(get_chat_model())
    return DeterministicExtractor()
