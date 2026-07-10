"""Unit tests for the deterministic offline fact extractor."""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from velmo.memory.extract import DeterministicExtractor


def _facts(text: str):
    return DeterministicExtractor().extract("u1", [HumanMessage(content=text)])


def test_extracts_order_number_as_episodic():
    facts = _facts("Ma commande O-2024-0101 n'est pas arrivée.")
    assert any(f.fact_type == "order_info" and f.content == "O-2024-0101" for f in facts)


def test_extracts_tutoiement_preference():
    facts = _facts("Tu peux me tutoyer, c'est plus simple.")
    prefs = [f for f in facts if f.fact_type == "preference" and f.key == "tutoiement"]
    assert prefs and prefs[0].content == "oui"


def test_extracts_pro_status_as_profile():
    facts = _facts("Je suis client pro / revendeur.")
    profiles = [f for f in facts if f.fact_type == "profile" and f.key == "segment"]
    assert profiles and "pro" in profiles[0].content.lower()


def test_extracts_pointure_as_profile():
    for text in ("Je chausse du L.", "Je fais du XL.", "Ma pointure est M."):
        facts = _facts(text)
        pointures = [f for f in facts if f.fact_type == "profile" and f.key == "pointure"]
        assert pointures, f"no pointure extracted from {text!r}"


def test_off_topic_message_extracts_nothing():
    # Selectivity contract: no durable fact -> empty.
    assert _facts("Il fait beau aujourd'hui, merci !") == []


def test_facts_are_bound_to_the_given_user():
    facts = _facts("Tu peux me tutoyer.")
    assert facts and all(f.user_id == "u1" for f in facts)


def test_source_is_extractor():
    facts = _facts("Ma commande O-2024-0101 est en retard.")
    assert facts and all(f.source == "extractor" for f in facts)
