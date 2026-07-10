"""Unit tests for the deterministic offline fact extractor."""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from velmo.memory.extract import DeterministicExtractor, get_extractor


def _facts(text: str):
    return DeterministicExtractor().extract("u1", [HumanMessage(content=text)])


def test_size_regex_does_not_match_unrelated_je_fais_clauses():
    for text in (
        "Je fais appel à l'équipe pour ma commande.",
        "Je fais suivre au service M. Dupont.",
        "Je fais du sport, la taille L est-elle dispo ?",
    ):
        facts = _facts(text)
        sizes = [f for f in facts if f.fact_type == "profile" and f.key in ("taille", "pointure")]
        assert sizes == [], f"spurious size extracted from {text!r}: {sizes}"


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


def test_extracts_taille_as_profile():
    # Clothing/jersey size: a letter or a number (e.g. "32" for trousers).
    for text, expected in (
        ("Je fais du XL.", "XL"),
        ("Ma taille est M.", "M"),
        ("Je fais du 32.", "32"),
    ):
        facts = _facts(text)
        tailles = [f for f in facts if f.fact_type == "profile" and f.key == "taille"]
        assert tailles and tailles[0].content == expected, f"no taille extracted from {text!r}"


def test_extracts_pointure_as_profile():
    # Shoe size ("pointure"): always a number in French sizing, never a letter.
    for text, expected in (
        ("Je chausse du 44.", "44"),
        ("Ma pointure est 42.", "42"),
    ):
        facts = _facts(text)
        pointures = [f for f in facts if f.fact_type == "profile" and f.key == "pointure"]
        assert pointures and pointures[0].content == expected, (
            f"no pointure extracted from {text!r}"
        )


def test_pointure_does_not_match_letter_sizes():
    # "Je chausse du L" is not valid French (shoe sizes are numeric) — no match.
    facts = _facts("Je chausse du L.")
    pointures = [f for f in facts if f.fact_type == "profile" and f.key == "pointure"]
    assert pointures == []


def test_off_topic_message_extracts_nothing():
    # Selectivity contract: no durable fact -> empty.
    assert _facts("Il fait beau aujourd'hui, merci !") == []


def test_facts_are_bound_to_the_given_user():
    facts = _facts("Tu peux me tutoyer.")
    assert facts and all(f.user_id == "u1" for f in facts)


def test_source_is_extractor():
    facts = _facts("Ma commande O-2024-0101 est en retard.")
    assert facts and all(f.source == "extractor" for f in facts)


def test_get_extractor_offline_is_deterministic(monkeypatch):
    monkeypatch.delenv("AZURE_AI_INFERENCE_ENDPOINT", raising=False)
    assert isinstance(get_extractor(), DeterministicExtractor)
