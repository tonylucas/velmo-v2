"""Unit tests for the offline fact store (LocalFactStore) and the factory."""

from __future__ import annotations

from velmo.memory.facts import Fact
from velmo.memory.fact_store import (
    LocalFactStore,
    episodic_storage_key,
    get_fact_store,
    semantic_storage_key,
)


def _write(store, user_id, fact_type, key, content):
    return store.write(Fact.new(user_id, fact_type, key, content))


def test_semantic_fact_replaced_on_conflict():
    # FR-009 semantic: same (fact_type, key) keeps only the most recent value.
    store = LocalFactStore()
    _write(store, "u1", "profile", "pointure", "L")
    _write(store, "u1", "profile", "pointure", "XL")
    pointures = [f for f in store.all("u1") if f.key == "pointure"]
    assert len(pointures) == 1
    assert pointures[0].content == "XL"


def test_semantic_update_preserves_created_at():
    store = LocalFactStore()
    first = _write(store, "u1", "profile", "pointure", "L")
    updated = _write(store, "u1", "profile", "pointure", "XL")
    assert updated.created_at == first.created_at


def test_distinct_semantic_keys_coexist():
    store = LocalFactStore()
    _write(store, "u1", "preference", "tutoiement", "oui")
    _write(store, "u1", "preference", "equipe", "OM")
    assert {f.key for f in store.all("u1")} == {"tutoiement", "equipe"}


def test_episodic_facts_accumulate():
    # FR-009 episodic: each entry is kept as a distinct record.
    store = LocalFactStore()
    _write(store, "u1", "order_info", "order", "O-2024-0101")
    _write(store, "u1", "order_info", "order", "O-2024-0102")
    orders = [f for f in store.all("u1") if f.fact_type == "order_info"]
    assert {f.content for f in orders} == {"O-2024-0101", "O-2024-0102"}


def test_isolation_between_users():
    # R3: a user's read never leaks another user's facts (separate dicts).
    store = LocalFactStore()
    _write(store, "u1", "order_info", "order", "O-2024-0101")
    _write(store, "u2", "order_info", "order", "O-2024-0101")  # same content
    u2 = store.all("u2")
    assert len(u2) == 1
    assert all(f.user_id == "u2" for f in u2)


def test_search_filters_by_fact_type():
    store = LocalFactStore()
    _write(store, "u1", "profile", "pointure", "L")
    _write(store, "u1", "order_info", "order", "O-2024-0101")
    got = store.search("u1", "peu importe", fact_types=["profile"])
    assert [f.key for f in got] == ["pointure"]


def test_search_respects_k():
    store = LocalFactStore()
    for i in range(7):
        _write(store, "u1", "order_info", "order", f"O-2024-000{i}")
    assert len(store.search("u1", "commande", k=3)) == 3


def test_delete_target_removes_matching_fact():
    store = LocalFactStore()
    _write(store, "u1", "profile", "adresse", "12 rue des Lilas")
    _write(store, "u1", "profile", "pointure", "L")
    removed = store.delete("u1", target="adresse")
    assert removed == 1
    assert {f.key for f in store.all("u1")} == {"pointure"}


def test_delete_all_when_target_none():
    store = LocalFactStore()
    _write(store, "u1", "profile", "adresse", "12 rue des Lilas")
    _write(store, "u1", "order_info", "order", "O-2024-0101")
    assert store.delete("u1", target=None) == 2
    assert store.all("u1") == []


def test_delete_unknown_target_removes_nothing():
    store = LocalFactStore()
    _write(store, "u1", "profile", "pointure", "L")
    assert store.delete("u1", target="adresse") == 0
    assert len(store.all("u1")) == 1


def test_get_fact_store_offline_returns_local(monkeypatch):
    monkeypatch.delenv("CHROMA_URL", raising=False)
    assert isinstance(get_fact_store(), LocalFactStore)


def test_semantic_storage_key_is_namespaced_by_user():
    # R3/Fix A: two users' identical (fact_type, key) must never collide on the
    # Chroma document id, since ChromaFactStore keys a single shared collection.
    key_a = semantic_storage_key(Fact.new("A", "profile", "pointure", "L"))
    key_b = semantic_storage_key(Fact.new("B", "profile", "pointure", "L"))
    assert key_a.startswith("A:")
    assert key_b.startswith("B:")
    assert key_a != key_b


def test_episodic_storage_key_is_content_derived():
    f1 = Fact.new("u1", "order_info", "order", "O-2024-0101")
    f2 = Fact.new("u1", "order_info", "order", "O-2024-0101")
    f3 = Fact.new("u1", "order_info", "order", "O-2024-0102")
    assert episodic_storage_key(f1) == episodic_storage_key(f2)
    assert episodic_storage_key(f1) != episodic_storage_key(f3)


def test_episodic_write_is_idempotent_on_same_content():
    store = LocalFactStore()
    store.write(Fact.new("u1", "order_info", "order", "O-2024-0101"))
    store.write(Fact.new("u1", "order_info", "order", "O-2024-0101"))
    orders = [f for f in store.all("u1") if f.fact_type == "order_info"]
    assert len(orders) == 1
