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

from typing import Annotated, Literal, TypedDict

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from .agent_tools import build_tools
from .llm import get_chat_model
from .routing import SYSTEM_PROMPT, run_deterministic


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    matched: bool


def build_graph(
    session,
    user_id: str,
    kb,
    chat_model: BaseChatModel,
    context: str = "",
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Compile the two-node agent graph bound to one request."""

    def deterministic_node(state: AgentState) -> dict:
        message = state["messages"][-1].content
        reply = run_deterministic(session, user_id, kb, message)
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
        tools=build_tools(session, user_id, kb),
        system_prompt=system_prompt,
    )

    def llm_node(state: AgentState) -> dict:
        result = react.invoke({"messages": state["messages"]})
        return {"messages": result["messages"]}

    graph = StateGraph(AgentState)
    graph.add_node("deterministic_node", deterministic_node)
    graph.add_node("llm_node", llm_node)
    graph.set_entry_point("deterministic_node")
    graph.add_conditional_edges("deterministic_node", route, {"llm_node": "llm_node", END: END})
    graph.add_edge("llm_node", END)
    return graph.compile(checkpointer=checkpointer)


def answer(
    session,
    user_id: str,
    kb,
    message: str,
    context: str = "",
    chat_model: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    thread_id: str | None = None,
) -> str:
    """Run one turn through the agent graph and return the final reply text."""
    if chat_model is None:
        chat_model = get_chat_model()
    graph = build_graph(session, user_id, kb, chat_model, context, checkpointer)
    config = {"configurable": {"thread_id": thread_id}} if checkpointer is not None else None
    result = graph.invoke(
        {"messages": [HumanMessage(content=message)], "matched": False},
        config,
    )
    return result["messages"][-1].content


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
