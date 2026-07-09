"""Unit tests for the Fact model and helpers."""

from __future__ import annotations

from velmo.memory.facts import (
    EPISODIC_TYPES,
    FACT_TYPES,
    SEMANTIC_TYPES,
    Fact,
    is_semantic,
    render_facts,
)


def test_fact_new_sets_timestamps_and_default_source():
    fact = Fact.new("u1", "profile", "pointure", "L")
    assert fact.created_at == fact.updated_at
    assert fact.source == "tool"
    assert fact.user_id == "u1"


def test_is_semantic_classification():
    assert is_semantic("preference") is True
    assert is_semantic("profile") is True
    assert is_semantic("order_info") is False
    assert is_semantic("dispute") is False


def test_fact_type_sets_are_disjoint_and_complete():
    assert SEMANTIC_TYPES.isdisjoint(EPISODIC_TYPES)
    assert FACT_TYPES == SEMANTIC_TYPES | EPISODIC_TYPES


def test_render_facts_lists_key_and_content():
    facts = [Fact.new("u1", "profile", "pointure", "L")]
    rendered = render_facts(facts)
    assert "pointure" in rendered
    assert "L" in rendered


def test_render_facts_empty_is_empty_string():
    assert render_facts([]) == ""
