"""Agent Velmo 2.0 : garde-fou d'entrée → mémoire → graphe (routage déterministe
+ nœud LLM outillé) → garde-fou de sortie → écriture mémoire.

`Agent.respond` orchestre le pipeline ; le raisonnement (routage regex + agent
LangGraph) vit dans `velmo.agent_graph`. La mémoire et les garde-fous de contenu
sont encore des stubs (chantiers suivants).
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from . import agent_graph
from .guardrails import GuardrailEngine
from .memory import MemoryManager

DEFAULT_REFUSAL = (
    "Désolé, je ne peux pas traiter cette demande. Je reste à votre disposition "
    "pour vos commandes, livraisons, retours et la FAQ Velmo."
)


class Agent:
    """Assistant de support adossé au graphe (routage déterministe + LLM outillé)."""

    def __init__(
        self,
        chat_model: BaseChatModel | None,
        memory: MemoryManager,
        guardrails: GuardrailEngine,
        session=None,
        kb=None,
    ) -> None:
        self.chat_model = chat_model
        self.memory = memory
        self.guardrails = guardrails
        self.session = session
        self.kb = kb

    def respond(self, user_id: str, message: str) -> str:
        gate_in = self.guardrails.check_input(message)
        if not gate_in.allowed:
            refusal = gate_in.refusal or DEFAULT_REFUSAL
            self.memory.write(user_id, message, refusal)
            return refusal

        context = self.memory.read(user_id, message).render()
        answer = agent_graph.answer(
            self.session, user_id, self.kb, message,
            context=context, chat_model=self.chat_model,
        )

        gate_out = self.guardrails.check_output(answer)
        if not gate_out.allowed:
            answer = gate_out.refusal or DEFAULT_REFUSAL

        self.memory.write(user_id, message, answer)
        return answer


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
        memory=MemoryManager(),
        guardrails=GuardrailEngine(),
        session=session,
        kb=kb,
    )
