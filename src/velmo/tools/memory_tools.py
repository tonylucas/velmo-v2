"""Long-term memory tools: remember, forget (R5) and inspect (R6).

Each tool is closed over ``store``/``user_id`` by the caller — the model never
picks ``user_id`` (per-customer isolation, same discipline as the order tools).
"""

from __future__ import annotations

from ..memory.facts import Fact, render_facts
from ..memory.fact_store import FactStore


def remember_fact(store: FactStore, user_id: str, fact_type: str, key: str, content: str) -> dict:
    """Store a durable fact about the customer."""
    fact = store.write(Fact.new(user_id, fact_type, key, content))
    return {"action": "remembered", "fact_type": fact.fact_type, "key": fact.key}


def forget_user_data(store: FactStore, user_id: str, target: str | None = None) -> dict:
    """Delete a targeted fact or, when ``target`` is None, every fact of the user."""
    removed = store.delete(user_id, target)
    if removed == 0:
        return {"action": "nothing_to_forget"}
    return {"action": "forgotten", "count": removed}


def inspect_user_memory(store: FactStore, user_id: str) -> str:
    """Return a human-readable French summary of everything retained (R6)."""
    facts = store.all(user_id)
    if not facts:
        return "Je n'ai aucune information mémorisée à votre sujet."
    return f"Voici ce que j'ai retenu à votre sujet :\n{render_facts(facts)}"
