"""Tests for the deterministic (regex) routing fast path."""

from __future__ import annotations

from conftest import seeded_session

from velmo.routing import run_deterministic


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
