"""Assembles the Velmo agent as a single LangGraph StateGraph.

Two nodes:
- deterministic_node: the regex fast path (velmo.routing). No LLM call.
- llm_node: a ReAct agent (langchain create_agent) with the business tools,
  reached only when the deterministic path matches nothing.

Both paths flow through the same graph, so a future checkpointer and future
guardrail nodes can be inserted here and apply uniformly to both. The graph is
compiled without a checkpointer for this chantier.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
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
    graph.add_conditional_edges(
        "deterministic_node", route, {"llm_node": "llm_node", END: END}
    )
    graph.add_edge("llm_node", END)
    # No checkpointer for chantier 001 — the future memory chantier wires one here.
    return graph.compile()


def answer(
    session,
    user_id: str,
    kb,
    message: str,
    context: str = "",
    chat_model: BaseChatModel | None = None,
) -> str:
    """Run one turn through the agent graph and return the final reply text."""
    if chat_model is None:
        chat_model = get_chat_model()
    graph = build_graph(session, user_id, kb, chat_model, context)
    result = graph.invoke({"messages": [HumanMessage(content=message)], "matched": False})
    return result["messages"][-1].content
