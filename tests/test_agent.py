"""Tests for the Agent short-term memory (checkpointer-backed)."""

from __future__ import annotations

from conftest import build_reference_agent


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
