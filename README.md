# Velmo V2

Assistant de support pour **Velmo**, boutique en ligne de maillots de foot collector (rééditions vintage, pièces signées, éditions limitées en stock très limité). L'agent traite la gestion de commandes de niveau 1 — statut et suivi, disponibilité, modification/annulation avant expédition, retours, remboursements simples, FAQ — en gardant le contexte du client dans le temps.

---

> **Agent de support e-commerce en production sur Azure** : mémoire persistante isolée par
> client, garde-fous en entrée et en sortie, et une note de qualité qui bloque la livraison
> en CI sous 0,90. Postgres pour l'état métier, Chroma pour la mémoire long terme et la FAQ.

Reconstruit de zéro sur un brief imposé ([`docs/brief.md`](docs/brief.md)) et une suite
d'acceptance fournie d'avance, puis mis en ligne sur un second brief
([`docs/brief-azure.md`](docs/brief-azure.md)). Les trois exigences non négociables du
brief — mémoire (R1–R6), garde-fous, qualité mesurée — sont les trois modules ci-dessous.

<p align="center">
  <a href="docs/img/deploiement-azure.png">
    <img src="docs/img/deploiement-azure.png" alt="Le navigateur atteint le conteneur Velmo sur Azure App Service ; le tour y traverse garde-fou d'entrée, lecture mémoire, LLM, garde-fou de sortie, écriture mémoire ; l'état métier et la mémoire court terme vont en PostgreSQL, la mémoire long terme en Chroma sur un volume Azure Files, les secrets arrivent par les paramètres d'application, la latence et le coût partent vers Langfuse." width="820">
  </a>
  <br><em>Déploiement cible sur Azure : la chaîne garde-fous → mémoire → LLM → garde-fous
  est préservée en ligne, et aucun secret ne vit dans le dépôt — cliquer pour agrandir.</em>
</p>

| Ce que le projet a demandé | Où le lire |
|---|---|
| **Mémoire d'agent sur six exigences** : court terme par checkpointer LangGraph keyé sur l'utilisateur, long terme en faits typés (sémantique vs épisodique) avec extraction à chaque tour — donc rien de perdu au-delà de la fenêtre —, isolation, droit à l'oubli RGPD et inspection | [`memory/`](src/velmo/memory/), [`fact_store.py`](src/velmo/memory/fact_store.py), [`extract.py`](src/velmo/memory/extract.py), [`memory_tools.py`](src/velmo/tools/memory_tools.py) |
| **Garde-fous en deux étages** : détecteurs déterministes hors-ligne (injection, hors-périmètre, PII par Luhn/IBAN, fuite de secrets) renforcés par Azure AI Content Safety en prod, masquage plutôt que blocage quand c'est possible, et un journal de conformité qui reste local | [`guardrails/engine.py`](src/velmo/guardrails/engine.py), [`detectors.py`](src/velmo/guardrails/detectors.py), [`content_safety.py`](src/velmo/guardrails/content_safety.py) |
| **Évaluation et gate de livraison** : trois suites rejouées sur `eval/*.jsonl`, note globale versionnée par tag git, seuil bloquant en CI, et un agent volontairement dégradé qui doit noter *moins* — la preuve que le gate détecte une régression | [`mlops/`](src/velmo/mlops/), [`suites/`](src/velmo/mlops/suites/), [`eval.yml`](.github/workflows/eval.yml), [`test_mlops.py`](tests/acceptance/test_mlops.py) |
| **Routage déterministe avant le LLM** : regex d'intention et de numéro de commande traitent la majorité des tours sans appel de modèle ; le nœud LLM outillé (ReAct, 13 outils : 10 métier + 3 mémoire) n'est atteint que si rien ne matche — moins de coût, moins de surface d'hallucination | [`agent_graph.py`](src/velmo/agent_graph.py), [`routing.py`](src/velmo/routing.py), [`agent_tools.py`](src/velmo/agent_tools.py) |
| **Règles métier dans l'outil, pas à côté** : isolation par propriétaire de commande, modification interdite après expédition, plafond de remboursement à 50 € — chaque dépassement crée une escalade au lieu d'échouer en silence | [`tools/_common.py`](src/velmo/tools/_common.py), [`tools/refunds.py`](src/velmo/tools/refunds.py), [`tools/orders.py`](src/velmo/tools/orders.py) |
| **Observabilité de production** : Langfuse (un span par tour, tokens, coût, latence, catégorie de garde-fou déclenchée) avec masquage à l'export, doublée d'un `TurnLog` in-process qui voit ce qui tourne hors du graphe | [`observability.py`](src/velmo/observability.py), [`turn_log.py`](src/velmo/turn_log.py), [`infra/README.md`](infra/README.md) |
| **Déploiement et CI/CD** : image construite dans ACR, connexion Azure par OIDC (aucun credential stocké), déploiement conditionné à la réussite du gate d'éval sur le tag, rollback par révision | [`deploy.yml`](.github/workflows/deploy.yml), [`release.yml`](.github/workflows/release.yml), [`Dockerfile`](Dockerfile), [`infra/provision.sh`](infra/provision.sh) |

**Mesuré, pas affirmé** — note globale **0,954** (mémoire 0,917 · blocage des catégories
interdites 1,000 · faux positifs 0,000 sur 35 cas · qualité 1,000) pour un seuil bloquant
à 0,90, et **246 tests passent** (`uv sync --extra obs && make test`). Chiffres régénérables
par `make eval`, qui écrit une ligne par version dans `mlops/report.md`.

---

## Stack

- Python 3.11 (géré avec `uv`)
- PostgreSQL + SQLAlchemy 2 + Alembic (état des commandes, clients, catalogue)
- Chroma + `intfloat/multilingual-e5-small` pour la FAQ (extra `vector`)
- Azure AI Inference (Kimi-K2.6) pour le LLM (extra `llm`)
- GitHub Actions pour l'intégration continue

Le coeur tourne sans service externe (repli hors-ligne : SQLite en mémoire pour les
tests, FAQ locale, LLM en écho). Les intégrations s'activent via les extras :

```bash
uv sync                                   # coeur + base + outils de dev
uv sync --extra vector --extra llm        # Chroma + Azure AI Inference
```

## Démarrage

```bash
make up           # docker compose : app + postgres + chroma
make seed         # peuple Postgres (catalogue, clients, ~14 commandes)
make chat         # REPL — répond déjà aux questions métier de base
```

Exemple de session (`make chat`, client `C-marc-dubois` par défaut) :

```
Vous : Quel est le statut de ma commande O-2024-0101 ?
Velmo : Votre commande O-2024-0101 est au statut « prepared ».
Vous : Le maillot france-1998 en taille L est-il disponible ?
Velmo : Le maillot France 1998 — Zidane en taille L est disponible.
Vous : Quels sont les frais de port en France ?
Velmo : D'après notre FAQ (frais-de-port.md) : France métropolitaine : 6,90 € …
```

L'interface de démonstration Streamlit (`make demo`) ajoute un onglet « 🔍 Déroulé » qui
montre, tour par tour, le verdict des garde-fous, les faits mémoire lus et écrits, le
chemin pris dans le graphe et les appels d'outils.

## Graphe de l'agent

`src/velmo/agent_graph.py` assemble l'agent comme un `StateGraph` LangGraph à
deux nœuds, compilé avec un checkpointer (mémoire court terme, thread_id =
`user_id`) qui charge/persiste l'historique à chaque tour :

```mermaid
flowchart TD
    start([message utilisateur]) --> det["deterministic_node<br/>routage regex (velmo.routing)<br/>appelle les outils métier, sans LLM"]
    det -- intention reconnue --> fin([fin])
    det -- rien ne matche --> llm["llm_node<br/>agent ReAct (create_agent)<br/>outillé, fenêtre glissante 30 messages"]
    llm --> fin

    cp[("checkpointer<br/>historique complet par thread_id")]
    cp -. charge / persiste .- det
    cp -. charge / persiste .- llm
```

- **`deterministic_node`** : chemin rapide par expressions régulières (numéro
  de commande, mots-clés d'intention). S'il produit une réponse, le graphe
  s'arrête directement (`route` renvoie `END`).
- **`llm_node`** : atteint uniquement si aucune règle ne matche. Agent ReAct
  outillé avec les 10 outils métier, dont le prompt est borné aux 30 derniers
  messages (`window_messages`) — la persistance, elle, garde tout l'historique.
- Le **checkpointer** (`InMemorySaver` hors-ligne, `PostgresSaver` si `DB_URL`)
  n'est pas un nœud du graphe : c'est l'état compilé (`graph.compile(checkpointer=...)`),
  lu et écrit automatiquement à chaque `graph.invoke`, keyé par `thread_id`.

## Layout

```
src/velmo/
  cli.py            REPL de conversation (--user)
  agent.py          Orchestration : garde-fous → mémoire → outils → réponse
  llm.py            Client Azure AI Inference (+ repli hors-ligne)
  db.py             Schéma SQLAlchemy + sessions
  sampledata.py     Jeu de données de référence
  tools/            10 outils métier (accès Postgres + FAQ)
  memory/           Mémoire court terme (checkpointer) + long terme (FactStore, faits, oubli, inspection)
  guardrails/       Garde-fous de contenu entrée/sortie (détecteurs locaux + Content Safety)
  mlops/            Évaluation (3 suites), note globale, seuil bloquant, rapport
  observability.py  Traçage Langfuse (NoOpTracer sans clés)
  turn_log.py       Journal in-process d'un tour (alimente la démo et les tests)
docs/               Briefs, note de recommandations, specs de conception, schémas
infra/              Runbook Azure + script de provisionnement
kb/docs/            Base de connaissances FAQ
scripts/            seed.py (Postgres) + seed_kb.py (Chroma)
alembic/            Migrations
eval/               Jeux de cas (mémoire, garde-fous, qualité)
tests/acceptance/   Suite d'acceptance + tests métier
.github/workflows/  Intégration continue
```

## Commandes utiles

```bash
make migrate    # alembic upgrade head
make seed-kb    # ingestion FAQ dans Chroma
make test       # suite complète (246 tests)
make eval       # évaluation + note globale + écriture de mlops/report.md
make demo       # interface Streamlit avec le déroulé d'un tour
make fmt        # ruff format + autofix
make typecheck  # mypy
make down       # arrête les services
```

## License

Propriétaire — Velmo.
