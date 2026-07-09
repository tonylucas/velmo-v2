"""Tests for the two-node agent graph (deterministic node + LLM node)."""

from __future__ import annotations

from conftest import ScriptedToolCallingChatModel, seeded_session
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from velmo.agent_graph import answer, build_graph, get_state


def test_deterministic_path_never_calls_llm():
    session = seeded_session()
    # This response would appear only if the LLM node ran; the regex path must win.
    model = ScriptedToolCallingChatModel(responses=[AIMessage(content="LLM_WAS_CALLED")])
    reply = answer(
        session,
        "C-marc-dubois",
        None,
        "Quel est le statut de ma commande O-2024-0101 ?",
        chat_model=model,
    )
    assert "prepared" in reply
    assert "LLM_WAS_CALLED" not in reply


def test_llm_path_returns_final_message():
    session = seeded_session()
    model = ScriptedToolCallingChatModel(
        responses=[AIMessage(content="Bonjour, comment puis-je vous aider ?")]
    )
    reply = answer(session, "C-marc-dubois", None, "Bonjour", chat_model=model)
    assert reply == "Bonjour, comment puis-je vous aider ?"


def test_llm_path_tool_call_respects_isolation():
    session = seeded_session()
    # No order id / keyword => deterministic returns None => LLM node.
    # Scripted model calls get_order on Sophie's order while acting for Marc.
    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "get_order", "args": {"order_id": "O-2024-0107"}, "id": "c1"}],
        ),
        AIMessage(content="Désolé, aucune commande à votre nom."),
    ]
    model = ScriptedToolCallingChatModel(responses=responses)
    graph = build_graph(session, "C-marc-dubois", None, model)
    result = graph.invoke(
        {"messages": [HumanMessage(content="Vérifie une commande pour moi")], "matched": False}
    )
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_messages
    assert "not_found_or_forbidden" in tool_messages[0].content


def test_checkpointer_persists_history_across_turns():
    session = seeded_session()
    ck = InMemorySaver()
    model = ScriptedToolCallingChatModel(
        responses=[AIMessage(content="ok1"), AIMessage(content="ok2")]
    )
    answer(
        session,
        "C-marc-dubois",
        None,
        "Bonjour Velmo",
        chat_model=model,
        checkpointer=ck,
        thread_id="C-marc-dubois",
    )
    answer(
        session,
        "C-marc-dubois",
        None,
        "Une question de plus",
        chat_model=model,
        checkpointer=ck,
        thread_id="C-marc-dubois",
    )
    contents = [m.content for m in get_state(ck, "C-marc-dubois")]
    assert "Bonjour Velmo" in contents
    assert "Une question de plus" in contents


def test_threads_are_isolated_by_user():
    session = seeded_session()
    ck = InMemorySaver()
    model = ScriptedToolCallingChatModel(responses=[AIMessage(content="a"), AIMessage(content="b")])
    answer(
        session,
        "C-marc-dubois",
        None,
        "mot secret artichaut",
        chat_model=model,
        checkpointer=ck,
        thread_id="C-marc-dubois",
    )
    answer(
        session,
        "C-sophie-martin",
        None,
        "coucou",
        chat_model=model,
        checkpointer=ck,
        thread_id="C-sophie-martin",
    )
    sophie = [m.content for m in get_state(ck, "C-sophie-martin")]
    assert not any("artichaut" in c for c in sophie)


def test_get_state_empty_thread_returns_empty():
    assert get_state(InMemorySaver(), "nobody") == []
