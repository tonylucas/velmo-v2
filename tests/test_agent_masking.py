"""A card number in a user message is masked before it reaches memory/LLM."""

from __future__ import annotations

from conftest import build_reference_agent
from velmo.memory.fact_store import LocalFactStore


def test_card_number_is_masked_before_memory():
    store = LocalFactStore()
    agent = build_reference_agent(store)
    user = "mask-user"
    agent.respond(user, "Ma carte 4111 1111 1111 1111 a ete debitee, ma commande O-2024-0101 ?")

    # Nothing containing the raw PAN is retained in short-term state...
    state_text = " ".join(str(m.content) for m in agent.get_state(user))
    assert "4111 1111 1111 1111" not in state_text
    # ...nor in long-term facts.
    facts_text = " ".join(f.content for f in agent.inspect_memory(user))
    assert "4111" not in facts_text
