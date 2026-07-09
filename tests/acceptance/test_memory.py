"""Tests d'acceptance — mémoire long terme (chantier 003).

R1 (fil court terme) reste couvert via le checkpointer. R2/R3/R5/R6 s'appuient
sur le FactStore : on pilote le vrai agent et on assère sur le stocké
(`Agent.inspect_memory`) ou sur la réponse déterministe (oubli/inspection), jamais
sur l'écho du modèle offline. Tout tourne sur `LocalFactStore`, sans Docker.
"""

from __future__ import annotations

from conftest import build_reference_agent
from velmo.memory.fact_store import LocalFactStore
from velmo.tools.memory_tools import remember_fact


def test_recall_over_30_messages():
    # R1 : l'info du 1er message est restituée après 30+ messages (checkpointer).
    agent = build_reference_agent()
    user = "acc-recall"
    agent.respond(user, "Ma commande prioritaire est O-2024-0101.")
    for i in range(30):
        agent.respond(user, f"Question de suivi {i} sur un maillot.")

    contents = [m.content for m in agent.get_state(user)]
    assert any("O-2024-0101" in c for c in contents)


def test_cross_session_persistence():
    # R2 : pointure, clubs et segment retrouvés une session plus tard (même Store).
    store = LocalFactStore()
    build_reference_agent(store)  # session 1
    remember_fact(store, "acc-marc", "profile", "pointure", "L")
    remember_fact(store, "acc-marc", "profile", "clubs", "OM et Brésil")
    remember_fact(store, "acc-marc", "profile", "segment", "revendeur")

    session2 = build_reference_agent(store)  # nouvelle session, même client, même Store
    contents = " ".join(f.content for f in session2.inspect_memory("acc-marc"))
    assert "L" in contents
    assert "OM" in contents
    assert "revendeur" in contents


def test_isolation_between_customers():
    # R3 : Marc ne voit jamais les commandes de Sophie.
    store = LocalFactStore()
    agent = build_reference_agent(store)
    remember_fact(store, "acc-marc", "order_info", "order", "O-2024-0103")
    remember_fact(store, "acc-sophie", "order_info", "order", "O-2024-0107")

    sophie = " ".join(f.content for f in agent.inspect_memory("acc-sophie"))
    assert "O-2024-0107" in sophie
    assert "O-2024-0103" not in sophie


def test_right_to_be_forgotten():
    # R5 : « oublie mon adresse » supprime effectivement l'information via l'agent.
    store = LocalFactStore()
    agent = build_reference_agent(store)
    user = "acc-forget"
    remember_fact(store, user, "profile", "adresse", "12 rue des Lilas")
    assert any("Lilas" in f.content for f in agent.inspect_memory(user))

    ask = agent.respond(user, "oublie mon adresse")
    assert "confirme" in ask.lower()  # confirmation demandée, rien supprimé encore
    assert any("Lilas" in f.content for f in agent.inspect_memory(user))

    agent.respond(user, "oublie mon adresse, je confirme")
    assert not any("Lilas" in f.content for f in agent.inspect_memory(user))


def test_inspect_user_memory():
    # R6 : l'inspection restitue tous les faits actifs.
    store = LocalFactStore()
    agent = build_reference_agent(store)
    user = "acc-inspect"
    remember_fact(store, user, "profile", "pointure", "L")
    remember_fact(store, user, "preference", "tutoiement", "oui")
    remember_fact(store, user, "order_info", "order", "O-2024-0101")

    summary = agent.respond(user, "que sais-tu de moi ?")
    assert "L" in summary
    assert "tutoiement" in summary
    assert "O-2024-0101" in summary


def test_semantic_conflict_keeps_latest():
    # FR-009 sémantique : une seule pointure subsiste (la plus récente).
    store = LocalFactStore()
    agent = build_reference_agent(store)
    user = "acc-conflict"
    remember_fact(store, user, "profile", "pointure", "L")
    remember_fact(store, user, "profile", "pointure", "XL")
    pointures = [f for f in agent.inspect_memory(user) if f.key == "pointure"]
    assert len(pointures) == 1
    assert pointures[0].content == "XL"


def test_episodic_facts_accumulate():
    # FR-009 épisodique : deux commandes distinctes coexistent.
    store = LocalFactStore()
    agent = build_reference_agent(store)
    user = "acc-orders"
    remember_fact(store, user, "order_info", "order", "O-2024-0101")
    remember_fact(store, user, "order_info", "order", "O-2024-0102")
    orders = [f for f in agent.inspect_memory(user) if f.fact_type == "order_info"]
    assert {f.content for f in orders} == {"O-2024-0101", "O-2024-0102"}


def test_forget_confirmation_is_deterministic_template():
    # FR-010 : la confirmation est un gabarit littéral et stable, pas du LLM.
    store = LocalFactStore()
    agent = build_reference_agent(store)
    user = "acc-fr010"
    remember_fact(store, user, "profile", "adresse", "12 rue des Lilas")
    reply = agent.respond(user, "oublie mon adresse")
    assert "irréversible" in reply.lower()
    assert "je confirme" in reply.lower()
