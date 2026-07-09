"""Checkpointer factory: the LangGraph short-term memory backend.

`InMemorySaver` offline (tests, eval); `PostgresSaver` when `DB_URL` is set and
the Postgres checkpointer package is installed. Symmetrical to `get_kb()` /
`get_chat_model()`.

The Postgres branch is the prod seam: it is not exercised by the offline suite
(no `DB_URL`) and is finalised when a real Postgres is connected.
"""

from __future__ import annotations

import os

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver


def get_checkpointer() -> BaseCheckpointSaver:
    """Return the Postgres checkpointer if configured, else the in-memory one."""
    db_url = os.getenv("DB_URL")
    if not db_url:
        return InMemorySaver()
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
    except ImportError:
        return InMemorySaver()
    from psycopg import Connection

    conninfo = db_url.replace("postgresql+psycopg://", "postgresql://")
    conn = Connection.connect(conninfo, autocommit=True, prepare_threshold=0)
    saver = PostgresSaver(conn)
    saver.setup()
    return saver
