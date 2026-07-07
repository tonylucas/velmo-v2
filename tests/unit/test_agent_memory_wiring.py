"""Test unitaire — le contexte mémoire doit atteindre l'appel LLM du fallback."""

from __future__ import annotations

from velmo.agent import Agent
from velmo.guardrails import GuardrailEngine
from velmo.memory import MemoryManager


class RecordingLLM:
    """Faux LLM qui mémorise le contexte reçu, pour vérifier le câblage."""

    def __init__(self) -> None:
        self.last_context: str | None = None

    def invoke(self, system: str, context: str, message: str) -> str:
        self.last_context = context
        return "reponse test"


def test_fallback_receives_rendered_memory_context(db_session, kb):
    llm = RecordingLLM()
    memory = MemoryManager()
    agent = Agent(llm=llm, memory=memory, guardrails=GuardrailEngine(), session=db_session, kb=kb)

    memory.remember_fact("unit-wiring", "pointure", "L")
    agent.respond("unit-wiring", "Message hors gabarit connu, sans mot-cle metier.")

    assert llm.last_context is not None
    assert "pointure: L" in llm.last_context
