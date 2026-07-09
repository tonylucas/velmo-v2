"""Tests d'acceptance — mémoire court terme (chantier 002).

R1 (fil de conversation) est couvert via l'agent + le checkpointer : on assère
sur l'état retenu (`Agent.get_state`), déterministe hors-ligne. R2 / R3 (faits) /
R5 relèvent du Store long terme et sont repris au chantier 003 (xfail(strict=True)
ci-dessous : ils échouent volontairement tant que le Store n'existe pas, et
échoueront « fort » (unexpectedly passing) le jour où chantier 003 les rendra
verts, forçant le retrait délibéré du marqueur).
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


@pytest.mark.xfail(strict=True, reason="R2 — mémoire long terme cross-session : chantier 003 (Store)")
def test_cross_session_persistence():
    # Critère R2 : pointure, clubs et segment retrouvés une session plus tard.
    session1 = MemoryManager()
    session1.remember_fact("acc-marc", "pointure", "L")
    session1.remember_fact("acc-marc", "clubs", "OM et Brésil")
    session1.remember_fact("acc-marc", "segment", "revendeur")

    session2 = MemoryManager()  # nouvelle session, même client
    rendered = session2.read("acc-marc", "Tu te souviens de moi ?").render()
    assert "L" in rendered
    assert "OM" in rendered
    assert "revendeur" in rendered


@pytest.mark.xfail(strict=True, reason="R3 faits — isolation du Store long terme : chantier 003")
def test_isolation_between_customers():
    # Critère R3 : Marc ne voit jamais les commandes de Sophie.
    mm = MemoryManager()
    mm.remember_fact("acc-marc", "commande", "O-2024-0103")
    mm.remember_fact("acc-sophie", "commande", "O-2024-0107")

    rendered_sophie = mm.read("acc-sophie", "Mes commandes ?").render()
    assert "O-2024-0107" in rendered_sophie
    assert "O-2024-0103" not in rendered_sophie


@pytest.mark.xfail(strict=True, reason="R5 — droit à l'oubli sur le Store long terme : chantier 003")
def test_right_to_be_forgotten():
    # Critère R5 : « oublie mon adresse » supprime effectivement l'information.
    mm = MemoryManager()
    user = "acc-forget"
    mm.write(user, "Mon adresse de livraison est 12 rue des Lilas.", "C'est noté.")

    assert "rue des Lilas" in mm.read(user, "Mon adresse ?").render()

    removed = mm.forget(user, "adresse")
    assert removed >= 1
    assert "rue des Lilas" not in mm.read(user, "Mon adresse ?").render()
