"""Tests for the Agent short-term memory (checkpointer-backed)."""

from __future__ import annotations

from conftest import build_reference_agent
from velmo.memory.fact_store import LocalFactStore


def test_agent_retains_conversation_across_turns():
    agent = build_reference_agent()
    user = "C-marc-dubois"
    agent.respond(user, "Retiens ce mot: artichaut.")
    agent.respond(user, "Autre message sans rapport.")
    contents = [m.content for m in agent.get_state(user)]
    assert any("artichaut" in c for c in contents)


def test_agent_isolates_users():
    agent = build_reference_agent()
    agent.respond("C-marc-dubois", "mot secret artichaut")
    agent.respond("C-sophie-martin", "bonjour")
    sophie = [m.content for m in agent.get_state("C-sophie-martin")]
    assert not any("artichaut" in c for c in sophie)


def test_agent_unknown_user_has_empty_state():
    agent = build_reference_agent()
    assert agent.get_state("C-karim-benali") == []


def test_respond_captures_durable_fact_automatically():
    # 003b: a durable fact stated in conversation is extracted and written,
    # with no explicit remember_fact call.
    store = LocalFactStore()
    agent = build_reference_agent(store)
    agent.respond("u-auto", "Tu peux me tutoyer.")
    keys = {f.key for f in agent.inspect_memory("u-auto")}
    assert "tutoiement" in keys


def test_respond_off_topic_writes_nothing():
    store = LocalFactStore()
    agent = build_reference_agent(store)
    agent.respond("u-quiet", "Il fait beau aujourd'hui !")
    assert agent.inspect_memory("u-quiet") == []


class _ExplodingExtractor:
    """Stands in for the production LangMem extractor blowing up.

    Real failure that motivated this: langmem/trustcall raised
    `AttributeError: 'ExtractionState' object has no attribute 'tool_call_id'`
    when the model's structured output failed validation and trustcall entered
    its repair path. A third-party enrichment step must not take the turn down.
    """

    def extract(self, user_id, messages):
        raise AttributeError("'ExtractionState' object has no attribute 'tool_call_id'")


def test_a_failing_extractor_does_not_lose_the_answer():
    from conftest import build_reference_agent

    agent = build_reference_agent()
    agent.extractor = _ExplodingExtractor()

    answer = agent.respond("C-marc-dubois", "Où en est ma commande O-2024-0101 ?")

    # The customer still gets the reply the graph already produced.
    assert "O-2024-0101" in answer
    assert "prepared" in answer


def test_a_failing_extraction_is_recorded_not_swallowed():
    # Degrading silently would be its own bug: an extractor that quietly stops
    # learning looks exactly like a customer who says nothing memorable.
    from conftest import build_reference_agent
    from velmo.turn_log import TurnLog

    agent = build_reference_agent()
    agent.extractor = _ExplodingExtractor()
    turn_log = TurnLog()

    agent.respond("C-marc-dubois", "Je fais du L.", turn_log=turn_log)

    step = next(s for s in turn_log.steps if s.stage == "memory" and s.name == "extract")
    assert step.outcome == "error"
    assert step.detail["count"] == 0
