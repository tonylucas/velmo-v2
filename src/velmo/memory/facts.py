"""The durable-fact model and its pure helpers.

A ``fact_type`` splits semantic traits (one mutable value per attribute — FR-009
replace) from episodic events (accumulated, never overwritten). The ``key`` field
is the attribute name (``pointure``, ``tutoiement``, ``order``…): FR-009 replaces
on the ``(fact_type, key)`` pair, since a user holds several distinct semantic
facts at once. No backend knowledge lives here.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

SEMANTIC_TYPES = {"preference", "profile"}
EPISODIC_TYPES = {"order_info", "dispute"}
FACT_TYPES = SEMANTIC_TYPES | EPISODIC_TYPES


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_semantic(fact_type: str) -> bool:
    return fact_type in SEMANTIC_TYPES


class Fact(BaseModel):
    user_id: str
    fact_type: str
    key: str
    content: str
    created_at: str
    updated_at: str
    source: str = "tool"

    @classmethod
    def new(
        cls, user_id: str, fact_type: str, key: str, content: str, source: str = "tool"
    ) -> "Fact":
        now = _now()
        return cls(
            user_id=user_id,
            fact_type=fact_type,
            key=key,
            content=content,
            created_at=now,
            updated_at=now,
            source=source,
        )


def render_facts(facts: list[Fact]) -> str:
    """Render facts as a compact bullet list for injection into the LLM prompt."""
    return "\n".join(f"- {f.key} : {f.content}" for f in facts)
