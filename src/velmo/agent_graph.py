"""Assembles the Velmo agent as a single LangGraph StateGraph.

Two nodes:
- deterministic_node: the regex fast path (velmo.routing). No LLM call.
- llm_node: a ReAct agent (langchain create_agent) with the business tools,
  reached only when the deterministic path matches nothing.

Short-term memory is the checkpointer: compiled into the graph and keyed by
thread_id, it holds the conversation history across turns. `answer` invokes the
graph with only the new message; the runtime loads and persists the rest.
"""

from __future__ import annotations

import ast
from contextlib import nullcontext
from typing import Annotated, Any, Literal, TypedDict

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from .agent_tools import build_tools
from .llm import get_chat_model
from .routing import SYSTEM_PROMPT, run_deterministic
from .tools._common import classify_result
from .trace import Trace


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    matched: bool


WINDOW_SIZE = 30


def window_messages(messages: list[BaseMessage], limit: int = WINDOW_SIZE) -> list[BaseMessage]:
    """Return at most the last `limit` messages — the sliding window fed to the LLM.

    The persisted state is never trimmed (soft window): the checkpointer keeps
    the full history; only the model's working context is bounded here.
    """
    return messages[-limit:]


def build_graph(
    session,
    user_id: str,
    kb,
    chat_model: BaseChatModel,
    context: str = "",
    checkpointer: BaseCheckpointSaver | None = None,
    store=None,
    trace: Trace | None = None,
):
    """Compile the two-node agent graph bound to one request."""

    def deterministic_node(state: AgentState) -> dict:
        message = state["messages"][-1].content
        reply = run_deterministic(session, user_id, kb, message, store, trace=trace)
        if reply is None:
            return {"matched": False}
        return {"messages": [AIMessage(content=reply)], "matched": True}

    def route(state: AgentState) -> Literal["llm_node", "__end__"]:
        return END if state.get("matched") else "llm_node"

    system_prompt = SYSTEM_PROMPT
    if context:
        system_prompt = f"{SYSTEM_PROMPT}\n\nMémoire:\n{context}"
    react = create_agent(
        model=chat_model,
        tools=build_tools(session, user_id, kb, store),
        system_prompt=system_prompt,
    )

    def llm_node(state: AgentState) -> dict:
        windowed = window_messages(state["messages"])
        # One invoke on both paths; `timed` keeps the step even if the model
        # raises (Azure timeout), so the panel shows where the turn died.
        measure = trace.timed("graph", "llm_node") if trace is not None else nullcontext(None)
        with measure as step:
            result = react.invoke({"messages": windowed})
            if step is not None:
                step.outcome = "done"
                step.detail["window"] = len(windowed)
        if trace is not None:
            _trace_tool_calls(trace, result["messages"])
        return {"messages": result["messages"]}

    graph = StateGraph(AgentState)
    graph.add_node("deterministic_node", deterministic_node)
    graph.add_node("llm_node", llm_node)
    graph.set_entry_point("deterministic_node")
    graph.add_conditional_edges("deterministic_node", route, {"llm_node": "llm_node", END: END})
    graph.add_edge("llm_node", END)
    return graph.compile(checkpointer=checkpointer)


def _trace_tool_calls(trace: Trace, messages: list[BaseMessage]) -> None:
    """Record the tools the model chose and what they returned.

    The calls are in the AIMessages create_agent returns and the results in the
    matching ToolMessages, so the panel needs no callback handler to see them.
    """
    outcomes = {
        message.tool_call_id: _tool_outcome(message.content)
        for message in messages
        if isinstance(message, ToolMessage)
    }
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            trace.add(
                "tool",
                call["name"],
                outcomes.get(call["id"], "called"),
                args=call.get("args", {}),
            )


def _tool_outcome(content: object) -> str:
    """Classify a tool result read back from a ToolMessage.

    Business tools return dicts; LangChain stringifies them into the message
    content (Python repr), so we parse it back rather than matching substrings.
    Substring matching is unsafe here: some tools carry free text composed by
    the LLM (e.g. escalate_to_human's `reason`), and that text can legitimately
    contain a fragment like `'error':` without the call having failed. Parsing
    the literal and delegating to `classify_result` reads the actual `action`/
    `error` keys instead of guessing from raw text.
    """
    try:
        parsed = ast.literal_eval(str(content))
    except (ValueError, SyntaxError):
        return "ok"
    if not isinstance(parsed, dict):
        return "ok"
    return classify_result(parsed)


def answer(
    session,
    user_id: str,
    kb,
    message: str,
    context: str = "",
    chat_model: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    thread_id: str | None = None,
    store=None,
    trace: Trace | None = None,
    callbacks: list[Any] | None = None,
) -> str:
    """Run one turn through the agent graph and return the final reply text."""
    if chat_model is None:
        chat_model = get_chat_model()
    if store is not None:
        from .memory.facts import render_facts

        facts = select_memory(store, user_id, message)
        if trace is not None:
            trace.add(
                "memory",
                "select_memory",
                "injected" if facts else "empty",
                count=len(facts),
                keys=[f.key for f in facts],
            )
        memory = render_facts(facts)
        if memory:
            context = f"{memory}\n{context}".rstrip() if context else memory
    graph = build_graph(session, user_id, kb, chat_model, context, checkpointer, store, trace)
    # Both keys are optional and independent: a turn can have a checkpointer with
    # no callbacks (offline) or callbacks with no checkpointer (a bare graph).
    config: dict[str, Any] = {}
    if checkpointer is not None:
        config["configurable"] = {"thread_id": thread_id}
    if callbacks:
        config["callbacks"] = callbacks
    result = graph.invoke(
        {"messages": [HumanMessage(content=message)], "matched": False},
        config or None,
    )
    return result["messages"][-1].content


def select_memory(store, user_id: str, message: str, k: int = 5) -> list:
    """Facts to inject this turn: semantic traits (always) + recent episodic."""
    from .memory.facts import EPISODIC_TYPES, SEMANTIC_TYPES

    semantic = store.search(user_id, message, fact_types=list(SEMANTIC_TYPES), k=k)
    episodic = store.search(user_id, message, fact_types=list(EPISODIC_TYPES), k=k)
    return semantic + episodic


def _state_reader_graph(checkpointer: BaseCheckpointSaver):
    """A minimal graph sharing AgentState's channels, used to read persisted state."""
    graph = StateGraph(AgentState)
    graph.add_node("noop", lambda state: {})
    graph.set_entry_point("noop")
    graph.add_edge("noop", END)
    return graph.compile(checkpointer=checkpointer)


def get_state(checkpointer: BaseCheckpointSaver, thread_id: str) -> list[BaseMessage]:
    """Return the conversation messages persisted for a thread (empty if none)."""
    graph = _state_reader_graph(checkpointer)
    snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
    return snapshot.values.get("messages", [])
