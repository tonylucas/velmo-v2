"""Unit tests for the deterministic offline fact extractor."""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from velmo.memory.extract import DeterministicExtractor


def _facts(text: str):
    return DeterministicExtractor("u1").extract([HumanMessage(content=text)])


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


def test_no_facts_returns_empty():
    assert _facts("Bonjour, merci beaucoup !") == []


def test_source_is_extractor():
    facts = _facts("Ma commande O-2024-0101 est en retard.")
    assert facts and all(f.source == "extractor" for f in facts)
