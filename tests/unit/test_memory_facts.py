"""Tests unitaires — faits durables (src/velmo/memory/facts.py)."""

from __future__ import annotations

from velmo.memory import facts


def test_remember_and_search():
    collection = facts.get_collection()
    facts.remember(collection, "unit-facts-1", "pointure", "L")
    hits = facts.search(collection, "unit-facts-1", "Quelle est ma pointure ?")
    assert any("pointure: L" in hit for hit in hits)


def test_remember_replaces_previous_value_for_same_key():
    collection = facts.get_collection()
    facts.remember(collection, "unit-facts-2", "pointure", "M")
    facts.remember(collection, "unit-facts-2", "pointure", "XL")
    stored = facts.all_facts(collection, "unit-facts-2")
    pointure_values = [f["content"] for f in stored if f.get("key") == "pointure"]
    assert pointure_values == ["pointure: XL"]


def test_search_isolated_by_user():
    collection = facts.get_collection()
    facts.remember(collection, "unit-facts-a", "commande", "O-2024-0001")
    facts.remember(collection, "unit-facts-b", "commande", "O-2024-0002")
    hits_a = facts.search(collection, "unit-facts-a", "commande")
    assert any("O-2024-0001" in h for h in hits_a)
    assert not any("O-2024-0002" in h for h in hits_a)


def test_delete_matching_removes_and_counts():
    collection = facts.get_collection()
    facts.remember(collection, "unit-facts-forget", "adresse", "12 rue des Lilas")
    removed = facts.delete_matching(collection, "unit-facts-forget", "adresse")
    assert removed == 1
    assert facts.all_facts(collection, "unit-facts-forget") == []


def test_store_excerpt_is_searchable():
    collection = facts.get_collection()
    facts.store_excerpt(collection, "unit-facts-excerpt", "human: Ma commande prioritaire est O-2024-0101.")
    hits = facts.search(collection, "unit-facts-excerpt", "Quelle etait ma commande prioritaire ?")
    assert any("O-2024-0101" in h for h in hits)
