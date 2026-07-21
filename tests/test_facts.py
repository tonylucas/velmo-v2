"""Unit tests for the Fact model and helpers."""

from __future__ import annotations

from velmo.memory.facts import (
    EPISODIC_TYPES,
    FACT_TYPES,
    SEMANTIC_TYPES,
    Fact,
    is_semantic,
    render_facts,
    retrieved_documents,
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


def test_retrieved_documents_are_the_prompt_lines_without_the_bullet() -> None:
    # The judge must score the context the model saw. Deriving from render_facts
    # rather than re-formatting is what guarantees the two cannot drift apart;
    # asserting against a hand-written string would only freeze a typo.
    facts = [
        Fact.new(user_id="u", fact_type="preference", key="taille", content="fait du L"),
        Fact.new(user_id="u", fact_type="preference", key="couleur", content="bleu"),
    ]

    documents = retrieved_documents(facts)

    assert documents == [line.removeprefix("- ") for line in render_facts(facts).splitlines()]
    assert documents == ["taille : fait du L", "couleur : bleu"]


def test_no_facts_retrieves_no_documents() -> None:
    assert retrieved_documents([]) == []


def test_multiline_content_stays_one_document_verbatim() -> None:
    # content is LLM-authored (LangMemExtractor, remember_fact) and can span
    # several lines. It must still be exactly one document, with the content
    # preserved character for character -- not exploded into extra documents
    # by a naive `str.splitlines()` over the rendered text.
    facts = [Fact.new(user_id="u", fact_type="preference", key="adresse", content="l1\nl2")]

    documents = retrieved_documents(facts)

    assert documents == ["adresse : l1\nl2"]
    assert render_facts(facts) == "- adresse : l1\nl2"
