"""Tests for the deterministic (regex) routing fast path."""

from __future__ import annotations

from conftest import seeded_session

from velmo.memory.fact_store import LocalFactStore
from velmo.routing import run_deterministic
from velmo.tools.memory_tools import remember_fact


def test_order_status_is_recognised():
    session = seeded_session()
    reply = run_deterministic(
        session, "C-marc-dubois", None, "Quel est le statut de ma commande O-2024-0101 ?"
    )
    assert reply is not None
    assert "prepared" in reply


def test_out_of_stock_is_not_fabulated():
    session = seeded_session()
    reply = run_deterministic(
        session, "C-marc-dubois", None, "Le maillot om-1993 en taille M est-il disponible ?"
    )
    assert reply is not None
    assert "indisponible" in reply.lower()


def test_unknown_intent_returns_none():
    session = seeded_session()
    reply = run_deterministic(
        session, "C-marc-dubois", None, "Bonjour, pouvez-vous m'aider aujourd'hui ?"
    )
    assert reply is None


def test_isolation_other_customer_order():
    session = seeded_session()
    reply = run_deterministic(
        session, "C-marc-dubois", None, "Statut de la commande O-2024-0107 ?"
    )
    assert reply is not None
    assert "Je ne trouve pas" in reply


def _store_with_address():
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "adresse", "12 rue des Lilas")
    return store


def test_inspect_intent_routed():
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    reply = run_deterministic(None, "u1", None, "que sais-tu de moi ?", store)
    assert reply is not None
    assert "pointure" in reply


def test_forget_intent_asks_confirmation_first():
    store = _store_with_address()
    reply = run_deterministic(None, "u1", None, "oublie mon adresse", store)
    assert reply is not None
    assert "confirme" in reply.lower()
    # Not deleted yet.
    assert "Lilas" in run_deterministic(None, "u1", None, "que sais-tu de moi ?", store)


def test_forget_intent_deletes_on_confirmation():
    store = _store_with_address()
    reply = run_deterministic(None, "u1", None, "oublie mon adresse, je confirme", store)
    assert "fait" in reply.lower()
    assert "Lilas" not in run_deterministic(None, "u1", None, "que sais-tu de moi ?", store)


def test_forget_all_on_confirmation():
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    remember_fact(store, "u1", "order_info", "order", "O-2024-0101")
    reply = run_deterministic(None, "u1", None, "oublie tout, je confirme", store)
    assert "fait" in reply.lower()
    summary = run_deterministic(None, "u1", None, "que sais-tu de moi ?", store)
    assert "aucune information" in summary.lower()


def test_no_store_means_no_memory_routing():
    assert run_deterministic(None, "u1", None, "que sais-tu de moi ?", None) is None


def test_forget_unknown_target_is_gentle():
    store = LocalFactStore()
    remember_fact(store, "u1", "profile", "pointure", "L")
    reply = run_deterministic(None, "u1", None, "oublie mon numéro de contrat, je confirme", store)
    assert "aucune information" in reply.lower()
