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
