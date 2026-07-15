"""The graph, the deterministic router and the memory lookup record into a Trace."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from conftest import ScriptedToolCallingChatModel, seeded_session
from velmo import agent_graph
from velmo.kb_store import LocalKB
from velmo.memory.fact_store import LocalFactStore
from velmo.memory.facts import Fact
from velmo.routing import run_deterministic
from velmo.trace import Trace


@pytest.fixture
def session():
    return seeded_session()


def _graph_steps(trace: Trace) -> list[tuple[str, str]]:
    return [(s.name, s.outcome) for s in trace.steps if s.stage == "graph"]


def test_deterministic_match_records_the_intent(session) -> None:
    trace = Trace()
    run_deterministic(
        session, "C-marc-dubois", None, "Où en est ma commande O-2024-0101 ?", None, trace=trace
    )

    step = next(s for s in trace.steps if s.name == "deterministic_node")
    assert step.outcome == "match"
    assert step.detail["intent"] == "order_status"


def test_deterministic_records_the_intent_for_a_cancellation(session) -> None:
    trace = Trace()
    run_deterministic(
        session,
        "C-marc-dubois",
        None,
        "Annule ma commande O-2024-0101, je confirme",
        None,
        trace=trace,
    )

    step = next(s for s in trace.steps if s.name == "deterministic_node")
    assert step.detail["intent"] == "cancel_order"


def test_deterministic_node_is_timed(session) -> None:
    # The fast path runs the business tools (real DB queries), so its duration is
    # the interesting number on a deterministic turn — without it the panel
    # reports a turn that took 0 ms.
    trace = Trace()
    run_deterministic(
        session, "C-marc-dubois", None, "Où en est ma commande O-2024-0101 ?", None, trace=trace
    )

    step = next(s for s in trace.steps if s.name == "deterministic_node")
    assert step.duration_ms > 0


def test_no_deterministic_match_is_recorded_as_no_match(session) -> None:
    trace = Trace()
    reply = run_deterministic(
        session, "C-marc-dubois", None, "Raconte-moi une blague", None, trace=trace
    )

    assert reply is None
    assert ("deterministic_node", "no_match") in _graph_steps(trace)


def test_routing_result_is_identical_with_and_without_a_trace(session) -> None:
    message = "Où en est ma commande O-2024-0101 ?"
    without = run_deterministic(session, "C-marc-dubois", None, message, None)
    with_trace = run_deterministic(
        seeded_session(), "C-marc-dubois", None, message, None, trace=Trace()
    )

    assert without == with_trace


def test_answer_records_the_llm_node_and_its_tool_calls(session) -> None:
    # A scripted model that calls a business tool, then answers: the trace must
    # show the LLM node and name the tool the model chose.
    model = ScriptedToolCallingChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "get_order", "args": {"order_id": "O-2024-0101"}, "id": "call_1"}
                ],
            ),
            AIMessage(content="Votre commande est expédiée."),
        ]
    )
    trace = Trace()
    agent_graph.answer(
        session, "C-marc-dubois", LocalKB(), "Raconte-moi un truc", chat_model=model, trace=trace
    )

    assert ("llm_node", "done") in _graph_steps(trace)
    tools_called = [s.name for s in trace.steps if s.stage == "tool"]
    assert "get_order" in tools_called


def test_answer_records_injected_memory_facts(session) -> None:
    store = LocalFactStore()
    store.write(
        Fact.new("C-marc-dubois", "preference", "tutoiement", "Le client préfère le tutoiement")
    )
    trace = Trace()
    agent_graph.answer(
        session,
        "C-marc-dubois",
        LocalKB(),
        "Où en est ma commande O-2024-0101 ?",
        store=store,
        trace=trace,
    )

    step = next(s for s in trace.steps if s.stage == "memory" and s.name == "select_memory")
    assert step.detail["count"] >= 1


def test_answer_without_a_trace_is_unaffected(session) -> None:
    reply = agent_graph.answer(
        session, "C-marc-dubois", LocalKB(), "Où en est ma commande O-2024-0101 ?"
    )

    assert "O-2024-0101" in reply
