"""Tests for the two-node agent graph (deterministic node + LLM node)."""

from __future__ import annotations

from contextlib import contextmanager

from conftest import ScriptedToolCallingChatModel, seeded_session
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from velmo import agent_graph
from velmo.agent_graph import answer, build_graph, get_state, select_memory, window_messages
from velmo.llm import OfflineChatModel
from velmo.memory.fact_store import LocalFactStore
from velmo.observability import SYSTEM_PROMPT_FALLBACK, LiteralPrompt
from velmo.tools.memory_tools import remember_fact


def _capturing_model(responses: list) -> tuple:
    """A scripted model plus the SystemMessage content seen on each call —
    what the LLM was actually sent, not what the graph intended to send."""
    seen: list[str] = []

    class Recorder(ScriptedToolCallingChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            system = next(m for m in messages if isinstance(m, SystemMessage))
            seen.append(system.content)
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    return Recorder(responses=responses), seen


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


def test_window_messages_keeps_last_n():
    msgs = [HumanMessage(content=str(i)) for i in range(50)]
    windowed = window_messages(msgs, 30)
    assert len(windowed) == 30
    assert windowed[0].content == "20"
    assert windowed[-1].content == "49"


def test_window_messages_shorter_than_limit_unchanged():
    msgs = [HumanMessage(content=str(i)) for i in range(5)]
    assert window_messages(msgs, 30) == msgs


def test_llm_input_is_windowed_but_state_keeps_all():
    session = seeded_session()
    ck = InMemorySaver()
    seen: list[int] = []

    class Recorder(ScriptedToolCallingChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            seen.append(sum(1 for m in messages if not isinstance(m, SystemMessage)))
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    model = Recorder(responses=[AIMessage(content="ok")])
    user = "C-marc-dubois"
    for i in range(40):
        answer(
            session,
            user,
            None,
            f"Message numero {i} sans intention.",
            chat_model=model,
            checkpointer=ck,
            thread_id=user,
        )
    # The LLM never receives more than the window; the checkpointer keeps everything.
    assert max(seen) <= 30
    assert len(get_state(ck, user)) > 30


def test_answer_runs_with_store_wired():
    # R2 retrieval seam: answer accepts a store and completes a turn.
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    reply = agent_graph.answer(
        None,
        "u1",
        None,
        "Bonjour",
        chat_model=OfflineChatModel(),
        store=store,
    )
    assert isinstance(reply, str) and reply


def test_select_memory_keeps_semantic_facts_despite_episodic_volume():
    # R2: durable semantic traits recorded early must survive a later burst of
    # episodic facts. A single recency-ordered top-k search would evict the
    # older semantic facts; select_memory runs two separate searches so they
    # are always retained.
    store = LocalFactStore()
    user = "u-evict"
    # Semantic traits recorded first (oldest entries).
    remember_fact(store, user, "preference", "tutoiement", "oui")
    remember_fact(store, user, "profile", "pointure", "L")
    # Later burst of more-recent episodic facts.
    for i in range(6):
        remember_fact(store, user, "order_info", "order", f"O-2024-010{i}")

    keys = {f.key for f in select_memory(store, user, "peu importe")}
    assert "tutoiement" in keys
    assert "pointure" in keys


def test_system_prompt_is_compiled_from_the_given_prompt_object():
    session = seeded_session()
    model, seen = _capturing_model([AIMessage(content="ok")])

    answer(
        session,
        "C-marc-dubois",
        None,
        "Bonjour",
        chat_model=model,
        prompt=LiteralPrompt("PROMPT_MARKER_XYZ"),
    )

    assert seen == ["PROMPT_MARKER_XYZ"]


def test_system_prompt_falls_back_to_the_literal_text_when_none_is_given():
    # Every existing call site that predates prompt management (most of this
    # file) calls answer()/build_graph() without `prompt=`; behaviour for them
    # must be unchanged.
    session = seeded_session()
    model, seen = _capturing_model([AIMessage(content="ok")])

    answer(session, "C-marc-dubois", None, "Bonjour", chat_model=model)

    assert seen == [SYSTEM_PROMPT_FALLBACK]


def test_system_prompt_keeps_the_memoire_block_appended_after_it():
    session = seeded_session()
    model, seen = _capturing_model([AIMessage(content="ok")])

    answer(
        session,
        "C-marc-dubois",
        None,
        "Bonjour",
        chat_model=model,
        prompt=LiteralPrompt("BASE"),
        context="- order : O-2024-0101",
    )

    assert seen == ["BASE\n\nMémoire:\n- order : O-2024-0101"]


def test_llm_node_wraps_the_invoke_call_in_the_prompt_link():
    # `prompt.link()` is what attributes the LLM call to a Langfuse prompt
    # version (see velmo.observability._LangfusePrompt). It must wrap the
    # actual `react.invoke()` call, not just run alongside it.
    session = seeded_session()
    calls: list[str] = []

    class SpyPrompt:
        def compile(self) -> str:
            return "BASE"

        def link(self):
            @contextmanager
            def _cm():
                calls.append("enter")
                yield
                calls.append("exit")

            return _cm()

    model = ScriptedToolCallingChatModel(responses=[AIMessage(content="ok")])
    graph = build_graph(session, "C-marc-dubois", None, model, prompt=SpyPrompt())

    graph.invoke({"messages": [HumanMessage(content="Bonjour")], "matched": False})

    assert calls == ["enter", "exit"]
