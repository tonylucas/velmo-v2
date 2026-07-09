"""Tests d'acceptance — mémoire court terme (chantier 002).

R1 (fil de conversation) est couvert via l'agent + le checkpointer : on assère
sur l'état retenu (`Agent.get_state`), déterministe hors-ligne. R2 / R3 (faits) /
R5 relèvent du Store long terme et sont repris au chantier 003 (skip ci-dessous).
"""

from __future__ import annotations

import pytest

from conftest import build_reference_agent


def test_recall_over_30_messages():
    # R1 : l'info du 1er message est restituée après 30+ messages. Soft window :
    # le checkpointer conserve l'historique complet du thread.
    agent = build_reference_agent()
    user = "acc-recall"
    agent.respond(user, "Ma commande prioritaire est O-2024-0101.")
    for i in range(30):
        agent.respond(user, f"Question de suivi {i} sur un maillot.")

    contents = [m.content for m in agent.get_state(user)]
    assert any("O-2024-0101" in c for c in contents)


@pytest.mark.skip(reason="R2 — mémoire long terme cross-session : chantier 003 (Store)")
def test_cross_session_persistence():
    """Faits durables retrouvés une nouvelle session (Store, pas le checkpointer)."""


@pytest.mark.skip(reason="R3 faits — isolation du Store long terme : chantier 003")
def test_isolation_between_customers():
    """Les faits durables d'un client ne fuitent jamais chez un autre (Store)."""


@pytest.mark.skip(reason="R5 — droit à l'oubli sur le Store long terme : chantier 003")
def test_right_to_be_forgotten():
    """« Oublie mon adresse » supprime effectivement l'information (Store.delete)."""
