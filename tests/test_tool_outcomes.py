"""The TurnLog records what business tools returned, not just that they ran.

Escalation rate and tool-error rate are production metrics (chantier 005c); they
are read back from these steps rather than by instrumenting all ten tools.
"""

from __future__ import annotations

from conftest import ScriptedToolCallingChatModel, build_reference_agent, seeded_session
from langchain_core.messages import AIMessage, HumanMessage
from velmo.agent import Agent
from velmo.agent_graph import build_graph
from velmo.guardrails import GuardrailEngine
from velmo.kb_store import LocalKB
from velmo.memory.fact_store import LocalFactStore
from velmo.tools._common import classify_result
from velmo.turn_log import TurnLog


def test_classify_result_normalizes_both_escalation_verbs() -> None:
    # `escalate` (a tool declining to act) and `escalated` (escalate_to_human
    # succeeding) must read as the same outcome to the escalation-rate metric.
    assert classify_result({"action": "escalate"}) == "escalate"
    assert classify_result({"action": "escalated"}) == "escalate"


def test_classify_result_gives_the_isolation_verdict_its_own_word() -> None:
    # not_found_or_forbidden is owned_order declining a lookup on purpose (R3),
    # not a system fault — it must not read as "error" to the tool-error metric.
    assert classify_result({"error": "not_found_or_forbidden"}) == "not_found_or_forbidden"


def test_classify_result_gives_unknown_product_its_own_word() -> None:
    # Same principle for check_stock's business verdict on a bad reference.
    assert classify_result({"error": "unknown_product"}) == "unknown_product"


def test_classify_result_still_reports_error_for_anything_else() -> None:
    # An error string that is not a known business verdict is presumed to be a
    # genuine technical failure, and must still count as "error".
    assert classify_result({"error": "database_unavailable"}) == "error"


def test_classify_result_free_text_containing_error_key_is_not_an_error() -> None:
    # escalate_to_human's `reason` is free text an LLM composes from the
    # conversation; it can legitimately contain "'error':" without the call
    # having failed. Only the actual `error` key should trigger "error".
    result = {
        "action": "escalated",
        "escalation_id": "esc-1",
        "reason": "customer said 'error': timeout",
    }
    assert classify_result(result) == "escalate"


def test_deterministic_escalation_is_recorded_as_a_tool_step() -> None:
    # O-2024-0103 is shipped: MODIFIABLE_STATUSES excludes it, so cancelling
    # escalates instead of failing silently.
    turn_log = TurnLog()
    answer = build_reference_agent().respond(
        "C-marc-dubois", "Je veux annuler ma commande O-2024-0103, je confirme", turn_log=turn_log
    )

    assert "conseiller" in answer
    tools = [s for s in turn_log.steps if s.stage == "tool"]
    assert [s.outcome for s in tools] == ["escalate"]
    assert tools[0].name == "cancel_order"


def test_deterministic_success_is_recorded_with_the_tool_action() -> None:
    # O-2024-0101 is paid, so cancelling actually goes through.
    turn_log = TurnLog()
    build_reference_agent().respond(
        "C-marc-dubois", "Je veux annuler ma commande O-2024-0101, je confirme", turn_log=turn_log
    )

    tools = [s for s in turn_log.steps if s.stage == "tool"]
    assert len(tools) == 1
    assert tools[0].outcome == "cancelled"


def test_unowned_order_is_recorded_as_a_business_verdict_not_an_error() -> None:
    # O-2024-0110 belongs to C-sophie-martin: owned_order returns None and the
    # tool reports {"error": "not_found_or_forbidden"} — a customer mistyping or
    # probing an order id, not a technical fault, so it must not read as "error".
    turn_log = TurnLog()
    build_reference_agent().respond(
        "C-marc-dubois", "Je veux annuler ma commande O-2024-0110, je confirme", turn_log=turn_log
    )

    tools = [s for s in turn_log.steps if s.stage == "tool"]
    assert [s.outcome for s in tools] == ["not_found_or_forbidden"]


def test_llm_path_forbidden_order_gets_the_same_outcome_word_as_the_deterministic_path() -> None:
    # Same isolation verdict as the deterministic-path test above, but reached
    # through the LLM node: O-2024-0107 belongs to C-sophie-martin, so a
    # scripted model calling get_order on it while acting for Marc must record
    # the identical business-verdict word — not "error" — so the two paths
    # cannot drift into disagreeing about what counts as a technical failure.
    session = seeded_session()
    model = ScriptedToolCallingChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "get_order", "args": {"order_id": "O-2024-0107"}, "id": "c1"}],
            ),
            AIMessage(content="Désolé, aucune commande à votre nom."),
        ]
    )
    turn_log = TurnLog()
    graph = build_graph(session, "C-marc-dubois", None, model, turn_log=turn_log)
    graph.invoke(
        {"messages": [HumanMessage(content="Vérifie une commande pour moi")], "matched": False}
    )

    tools = [s for s in turn_log.steps if s.stage == "tool"]
    assert [s.outcome for s in tools] == ["not_found_or_forbidden"]


def test_llm_path_forbidden_order_does_not_inflate_agent_tool_errors() -> None:
    # End-to-end through Agent.respond: the metadata handed to the tracer must
    # report tool_errors=0 for an isolation verdict, since it is not a
    # technical failure — this is the metric the dashboard's "taux d'erreur
    # technique outils" is built from (see docs/superpowers/specs/
    # 2026-07-20-observability-langfuse-design.md §3).
    from velmo.observability import Turn

    class RecordingTurn:
        # Idempotent like the real Turn implementations: Agent.respond's
        # `finally` guard always calls end() a second time, and a well-behaved
        # turn must keep what the first, substantive call recorded.
        def __init__(self) -> None:
            self.callbacks: list = []
            self.metadata: dict = {}
            self._ended = False

        def record_retrieval(self, name: str, query: str, documents: list) -> None:
            return None

        def end(self, *, answer: str, **metadata) -> None:
            if self._ended:
                return
            self._ended = True
            self.metadata = metadata

    class RecordingTracer:
        records = True

        def __init__(self) -> None:
            self.turn = RecordingTurn()

        def start_turn(self, user_id: str, message: str) -> "Turn":
            return self.turn

        def get_prompt(self, name: str, *, fallback: str):
            from velmo.observability import LiteralPrompt

            return LiteralPrompt(fallback)

    model = ScriptedToolCallingChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "get_order", "args": {"order_id": "O-2024-0107"}, "id": "c1"}],
            ),
            AIMessage(content="Désolé, aucune commande à votre nom."),
        ]
    )
    tracer = RecordingTracer()
    agent = Agent(
        chat_model=model,
        guardrails=GuardrailEngine(),
        session=seeded_session(),
        kb=LocalKB(),
        store=LocalFactStore(),
        tracer=tracer,
    )

    agent.respond("C-marc-dubois", "Vérifie une commande pour moi")

    assert tracer.turn.metadata["tool_errors"] == 0


def test_a_read_only_turn_records_no_tool_outcome() -> None:
    # Only the modifying path reports a verdict; reads stay out of scope so the
    # escalation metric is not diluted by lookups.
    turn_log = TurnLog()
    build_reference_agent().respond(
        "C-marc-dubois", "Où en est ma commande O-2024-0101 ?", turn_log=turn_log
    )

    assert [s for s in turn_log.steps if s.stage == "tool"] == []


def test_running_without_a_turn_log_still_answers_the_same() -> None:
    message = "Je veux annuler ma commande O-2024-0103, je confirme"
    without = build_reference_agent().respond("C-marc-dubois", message)
    with_log = build_reference_agent().respond("C-marc-dubois", message, turn_log=TurnLog())

    assert without == with_log
