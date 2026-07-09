"""Agent Velmo 2.0 : garde-fou d'entrée → graphe (routage déterministe + nœud LLM
outillé, mémoire court terme via checkpointer) → garde-fou de sortie → réponse.

Le fil de conversation est persisté par le checkpointer LangGraph
(`thread_id = user_id`) ; il n'y a plus de gestionnaire de mémoire maison. Les
garde-fous de contenu sont encore des stubs (chantier 004).
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver

from . import agent_graph
from .guardrails import GuardrailEngine
from .memory.checkpointer import get_checkpointer

DEFAULT_REFUSAL = (
    "Désolé, je ne peux pas traiter cette demande. Je reste à votre disposition "
    "pour vos commandes, livraisons, retours et la FAQ Velmo."
)


class Agent:
    """Assistant de support adossé au graphe (routage déterministe + LLM outillé)."""

    def __init__(
        self,
        chat_model: BaseChatModel | None,
        guardrails: GuardrailEngine,
        session=None,
        kb=None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        self.chat_model = chat_model
        self.guardrails = guardrails
        self.session = session
        self.kb = kb
        self.checkpointer: BaseCheckpointSaver = checkpointer or get_checkpointer()

    def respond(self, user_id: str, message: str) -> str:
        gate_in = self.guardrails.check_input(message)
        if not gate_in.allowed:
            return gate_in.refusal or DEFAULT_REFUSAL

        answer = agent_graph.answer(
            self.session,
            user_id,
            self.kb,
            message,
            chat_model=self.chat_model,
            checkpointer=self.checkpointer,
            thread_id=user_id,
        )

        gate_out = self.guardrails.check_output(answer)
        if not gate_out.allowed:
            answer = gate_out.refusal or DEFAULT_REFUSAL
        return answer

    def get_state(self, user_id: str):
        """Return the conversation messages retained for a user (traceability)."""
        return agent_graph.get_state(self.checkpointer, user_id)


def build_default_agent(session=None, kb=None) -> Agent:
    """Assemble un agent avec composants par défaut, base et FAQ."""
    from .db import session_factory
    from .kb_store import get_kb
    from .llm import get_chat_model

    if session is None:
        session = session_factory()()
    if kb is None:
        kb = get_kb()
    return Agent(
        chat_model=get_chat_model(),
        guardrails=GuardrailEngine(),
        session=session,
        kb=kb,
    )
