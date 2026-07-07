"""Fenêtre courte de conversation : checkpointer LangGraph, isolation par `thread_id=user_id`.

Postgres (`DB_URL`) en prod ; repli mémoire partagé au niveau module hors-ligne
(tests/CI, pas de service externe) — même pattern que `llm.py`/`db.py`.

Le graphe est un unique nœud passthrough : son seul rôle est d'accumuler les
messages dans le state (réducteur `add_messages` de `MessagesState`), persistés
par le checkpointer choisi. Lire/écrire l'historique passe toujours par
`graph.invoke()`/`graph.get_state()` — jamais de `Checkpoint` construit à la main.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph

History = CompiledStateGraph[MessagesState, Any, MessagesState, MessagesState]

_offline_lock = threading.Lock()
_offline_saver: InMemorySaver | None = None


def _shared_offline_saver() -> InMemorySaver:
    """Checkpointer en mémoire partagé par tout le process (hors-ligne/tests).

    Une seule instance pour tout le process : deux `MemoryManager()` construits
    séparément doivent voir le même historique tant qu'aucun `DB_URL` n'est
    configuré.
    """
    global _offline_saver
    with _offline_lock:
        if _offline_saver is None:
            _offline_saver = InMemorySaver()
        return _offline_saver


def build_checkpointer(db_url: str | None = None) -> BaseCheckpointSaver[str]:
    """Postgres si `db_url`/`DB_URL` configuré, sinon repli mémoire partagé."""
    url = db_url or os.getenv("DB_URL")
    if not url:
        return _shared_offline_saver()

    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg import Connection
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool: ConnectionPool[Connection[dict[str, Any]]] = ConnectionPool(
        url,
        min_size=1,
        max_size=5,
        open=True,
        connection_class=Connection[dict[str, Any]],
        kwargs={"autocommit": True, "row_factory": dict_row},
    )
    saver = PostgresSaver(pool)
    saver.setup()
    return saver


def _passthrough(state: MessagesState) -> dict[str, Any]:
    return {}


def build_history_graph(checkpointer: BaseCheckpointSaver[str]) -> History:
    """Graphe à un seul nœud : accumule les messages, persistés par `checkpointer`."""
    graph = StateGraph(MessagesState)
    graph.add_node("passthrough", _passthrough)
    graph.add_edge(START, "passthrough")
    graph.add_edge("passthrough", END)
    return graph.compile(checkpointer=checkpointer)


def _config(user_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": user_id}}


def append_turn(graph: History, user_id: str, user_message: str, assistant_message: str) -> None:
    """Ajoute un tour (message utilisateur + réponse) à l'historique persistant."""
    graph.invoke(
        {"messages": [HumanMessage(content=user_message), AIMessage(content=assistant_message)]},
        config=_config(user_id),
    )


def get_history(graph: History, user_id: str) -> list[BaseMessage]:
    """Historique complet actuel (fenêtre courte), le plus ancien en premier."""
    state = graph.get_state(_config(user_id))
    if not state.values:
        return []
    return list(state.values.get("messages", []))


def remove_messages(graph: History, user_id: str, message_ids: list[str]) -> None:
    """Supprime des messages précis de l'historique (par id) — R4 (troncature) et R5 (oubli)."""
    if not message_ids:
        return
    graph.update_state(
        _config(user_id), {"messages": [RemoveMessage(id=mid) for mid in message_ids]}
    )
