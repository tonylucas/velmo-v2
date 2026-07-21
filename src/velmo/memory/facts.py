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


def _fact_lines(facts: list[Fact]) -> list[str]:
    """One line per fact, `key : content`, with `content` untouched.

    The shared builder behind both `render_facts` and `retrieved_documents`, so
    the two can never drift apart. Splitting on `content`'s own newlines (as
    `str.splitlines()` over the joined text used to) would silently turn one
    fact into several documents and drop whichever separator triggered the
    split — wrong for a judge that is supposed to see exactly what the model
    saw, character for character.
    """
    return [f"{f.key} : {f.content}" for f in facts]


def render_facts(facts: list[Fact]) -> str:
    """Render facts as a compact bullet list for injection into the LLM prompt."""
    return "\n".join(f"- {line}" for line in _fact_lines(facts))


def retrieved_documents(facts: list[Fact]) -> list[str]:
    """The injected memory lines, one per fact, without the markdown bullet.

    Built from the same line-per-fact list as `render_facts` (one document per
    fact, always — a multi-line `content` stays a single document), so the
    context a judge scores can never drift from the context the model was
    given. The bullet is prompt presentation, not content: keeping it would put
    an artefact in every document that an evaluator has to learn to ignore.
    """
    return _fact_lines(facts)
