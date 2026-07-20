"""Agent Velmo 2.0 : garde-fou d'entrée → graphe (routage déterministe + nœud LLM
outillé, mémoire court terme via checkpointer) → garde-fou de sortie → réponse.

Le fil de conversation est persisté par le checkpointer LangGraph
(`thread_id = user_id`) ; il n'y a plus de gestionnaire de mémoire maison. Les
garde-fous de contenu sont encore des stubs (chantier 004).
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

from . import agent_graph
from .guardrails import GuardrailEngine, Identity
from .memory.checkpointer import get_checkpointer
from .memory.extract import Extractor, get_extractor
from .memory.fact_store import get_fact_store
from .observability import Tracer, get_tracer
from .trace import Trace

DEFAULT_REFUSAL = (
    "Désolé, je ne peux pas traiter cette demande. Je reste à votre disposition "
    "pour vos commandes, livraisons, retours et la FAQ Velmo."
)


def _tool_signals(trace: Trace | None) -> tuple[bool, int]:
    """(escalated, tool_errors) read back from a turn's tool steps.

    Reading the Trace keeps the ten business tools free of instrumentation.
    """
    if trace is None:
        return False, 0
    steps = [step for step in trace.steps if step.stage == "tool"]
    return (
        any(step.outcome == "escalate" for step in steps),
        sum(1 for step in steps if step.outcome == "error"),
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
        store=None,
        extractor: Extractor | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self.chat_model = chat_model
        self.guardrails = guardrails
        self.session = session
        self.kb = kb
        self.checkpointer: BaseCheckpointSaver = checkpointer or get_checkpointer()
        self.store = store if store is not None else get_fact_store()
        self.extractor: Extractor = extractor if extractor is not None else get_extractor()
        self.tracer: Tracer = tracer if tracer is not None else get_tracer()

    def respond(self, user_id: str, message: str, *, trace: Trace | None = None) -> str:
        """Answer one turn. Pass a `trace` to record what ran (demo panel only);
        without one the pipeline behaves exactly as before and costs nothing."""
        gate_in = self.guardrails.check_input(message, trace=trace)
        if not gate_in.allowed:
            # Counted so the blocking rate stays measurable, but the offending
            # message never leaves the process: only its verdict does.
            blocked = self.tracer.start_turn(user_id, "[blocked input]")
            blocked.end(
                answer="[refused]",
                guardrail_in=gate_in.action,
                guardrail_in_category=gate_in.category,
            )
            return gate_in.refusal or DEFAULT_REFUSAL

        # Masking keeps the pipeline going on a sanitized message: the secret never
        # reaches the LLM, the memory, the checkpoint or the logs.
        safe_message = (
            gate_in.sanitized
            if gate_in.action == "mask" and gate_in.sanitized is not None
            else message
        )

        # An internal Trace is the source of the escalation and tool-error
        # metrics. Built only when the tracer would use it, so the offline path
        # keeps costing nothing.
        if trace is None and self.tracer.records:
            trace = Trace()
        turn = self.tracer.start_turn(user_id, safe_message)
        try:
            answer = agent_graph.answer(
                self.session,
                user_id,
                self.kb,
                safe_message,
                chat_model=self.chat_model,
                checkpointer=self.checkpointer,
                thread_id=user_id,
                store=self.store,
                trace=trace,
                callbacks=turn.callbacks,
            )

            facts = list(self.extractor.extract(user_id, [HumanMessage(content=safe_message)]))
            for fact in facts:
                self.store.write(fact)
            if trace is not None:
                trace.add(
                    "memory",
                    "extract",
                    "written" if facts else "nothing",
                    count=len(facts),
                    keys=[f.key for f in facts],
                )

            gate_out = self.guardrails.check_output(
                answer, identity=self._identity(user_id), trace=trace
            )
            if not gate_out.allowed:
                answer = gate_out.refusal or DEFAULT_REFUSAL

            escalated, tool_errors = _tool_signals(trace)
            turn.end(
                answer=answer,
                guardrail_in=gate_in.action,
                guardrail_in_category=gate_in.category,
                guardrail_out=gate_out.action,
                guardrail_out_category=gate_out.category,
                escalated=escalated,
                tool_errors=tool_errors,
                facts_written=len(facts),
            )
            return answer
        finally:
            # A raise between start_turn and end would otherwise leave the span
            # open and its context vars leaking into the next turn. end() is
            # idempotent, so the normal path above is unaffected by this second
            # call.
            turn.end(answer="[unhandled error]", error=True)

    def _identity(self, user_id: str) -> Identity:
        """Build the session customer's identity allow-list (email) for the output
        leak check. Returns an empty identity when unavailable (offline/tests)."""
        if self.session is None:
            return Identity()
        try:
            from .db import Customer

            customer = self.session.get(Customer, user_id)
        except Exception:
            return Identity()
        return Identity(email=customer.email if customer is not None else None)

    def get_state(self, user_id: str):
        """Return the conversation messages retained for a user (traceability)."""
        return agent_graph.get_state(self.checkpointer, user_id)

    def inspect_memory(self, user_id: str):
        """Return the durable facts retained for a user (R6 traceability)."""
        return self.store.all(user_id)


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
