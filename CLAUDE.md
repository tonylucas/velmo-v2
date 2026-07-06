# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Contexte du projet

Velmo 2.0 est un agent de support client pour une boutique de maillots de foot collector (rééditions vintage, pièces signées, éditions limitées). L'agent traite en autonomie les demandes de niveau 1 (suivi de commande, disponibilité, changement de taille/adresse, annulation, retour, remboursement) et escalade au-delà de certains seuils (remboursement > 50 €, commande déjà expédiée, litige d'authenticité).

Projet de formation en IA agentique — reconstruction complète à partir de zéro sur trois piliers : **Mémoire**, **Garde-fous**, **Évaluation & MLOps**. Voir `brief.md` (énoncé pédagogique) et `docs/reco_expert.md` (note de cadrage technique de l'expert externe, qui impose la stack ci-dessous).

La phrase de `docs/reco_expert.md` sur un agent « rapiécé une fois de trop » désigne le code actuel de ce dépôt (`src/velmo/agent.py` et son routage regex, `MemoryManager`/`GuardrailEngine` stubbés) tel qu'il existe avant les chantiers de reconstruction — pas un projet distinct. Ce dépôt (`velmo-v2`) a été forké aujourd'hui depuis le projet où le code et les specs `specs/00X-*` avaient déjà été élaborés séparément (specs écrites via un exercice **spec-kit** antérieur) ; son historique git court ne reflète que la date du fork, pas l'ancienneté du code. Voir `ROADMAP.md` pour l'état exact (spec/plan/tasks/implémentation) de chaque chantier.

## Stack imposée (`docs/reco_expert.md`)

- **LLM** : Azure AI Inference (Kimi-K2.6) via `langchain-azure-ai` — cf. `src/velmo/llm.py`. Pas de modèle local en prod (repli `EchoLLM` hors-ligne pour dev/tests).
- **Mémoire long terme (faits durables & épisodique)** : ChromaDB (recherche par similarité), embeddings `intfloat/multilingual-e5-small` (extra `vector`).
- **CI** : GitHub Actions, blocage de livraison sous seuil de qualité.

PostgreSQL (`src/velmo/db.py`) reste utilisé pour les données métier (catalogue, commandes, clients) et pour l'état conversationnel via le checkpointer LangGraph (`AsyncPostgresSaver`) — pas pour les faits durables, qui vivent entièrement dans Chroma (cf. `specs/002-long-term-memory/spec.md`).

**Important** : les artefacts de planification (`plan.md`/`tasks.md`/`data-model.md`) des prototypes spec-kit pour 001/002 n'ont volontairement pas été migrés — à régénérer via `/speckit-plan`. Décision d'architecture actée (voir `docs/superpowers/specs/2026-07-06-agent-runtime-langgraph-design.md`) : l'agent runtime est un **agent LangGraph** (StateGraph + `AsyncPostgresSaver` + LangMem comme extracteur de faits seul), qui remplace le routage par regex de `Agent._handle()`. Les `spec.md` de 001/002 restent inchangées — elles anticipaient déjà cette forme (composants `Checkpointer`/`LangMemExtractor` dans leurs schémas de séquence) sans l'imposer dans leurs exigences.

## Architecture cible

```
entrée → garde-fou d'entrée → mémoire (lecture) → agent LangGraph (tool-calling) → garde-fou de sortie → mémoire (écriture) → réponse
```

`Agent.respond()` (`src/velmo/agent.py`) devient asynchrone et orchestre un `StateGraph` LangGraph
compilé avec `AsyncPostgresSaver` (`thread_id = user_id`) : nœuds `garde-fou-in → mémoire-read →
agent (create_react_agent + outils métier) → garde-fou-out → mémoire-write`. Le nœud agent
utilise le LLM Azure déjà intégré avec `bind_tools`, remplaçant le routage regex. `db.py` et
`tools/*.py` restent synchrones ; les nœuds async y accèdent via `asyncio.to_thread(...)`.

Le checkpoint LangGraph ne contient que la fenêtre courte glissante (R1/R4) ; les faits durables
(R2/R5/R6, sémantiques et épisodiques) vivent entièrement dans Chroma, jamais dans l'état
checkpointé — suppression et inspection via filtres de métadonnées exacts (`user_id`,
`fact_type`), pas de recherche par similarité, pour que le droit à l'oubli reste vérifiable.
Détail complet : `docs/superpowers/specs/2026-07-06-agent-runtime-langgraph-design.md`.

### Outils de l'agent

**Lecture :** `getorder`, `trackshipment`, `checkstock`, `searchkb`

**Action (confirmation requise) :** `updateorderitem`, `cancelorder`, `createreturn`, `triggerrefund`, `escalateto_human`

### Structure du repo

```
src/velmo/
  cli.py            REPL de conversation (--user)
  agent.py          Orchestration : garde-fous → mémoire → outils → réponse
  llm.py            Client Azure AI Inference (+ repli hors-ligne)
  db.py             Schéma SQLAlchemy + sessions
  sampledata.py     Jeu de données de référence
  tools/            Outils métier (accès Postgres + FAQ)
  memory/           Mémoire court + long terme, isolation par utilisateur, droit à l'oubli (à construire)
  guardrails/       Garde-fou d'entrée + garde-fou de sortie (à construire)
  mlops/            Suites d'évaluation, CI, versionnage, report.md (à construire)
docs/               reco_expert.md (note de cadrage) + schémas de conception
kb/docs/            Base de connaissances FAQ
scripts/            seed.py (Postgres) + seed_kb.py (Chroma)
alembic/            Migrations
eval/               Jeux de cas figés (memory_cases.jsonl, guardrail_cases.jsonl, quality_cases.jsonl)
tests/acceptance/   Suite d'acceptance + tests métier
specs/              Specs spec-kit par chantier (001-006) — cf. ROADMAP.md pour l'état
```

## Mémoire — exigences non négociables (R1–R6)

| Réf | Exigence                                                                   |
| --- | -------------------------------------------------------------------------- |
| R1  | Tenir le fil sur 30+ messages sans perte                                   |
| R2  | Mémoire long terme persistante entre sessions (faits/préférences durables) |
| R3  | Isolation stricte par utilisateur                                          |
| R4  | Sélection et résumé au-delà de 30 messages                                 |
| R5  | Droit à l'oubli RGPD avec suppression effective et vérifiable              |
| R6  | Traçabilité : inspection de la mémoire d'un utilisateur                    |

La mémoire long terme **n'est pas un outil** — c'est le magasin persistant des faits durables (pointure, équipes suivies, litiges en cours).

## Garde-fous — catégories à bloquer (entrée ET sortie)

- Contenus haineux, discriminatoires, harcèlement
- Violence, menaces, incitation à se faire du mal
- Contenus sexuels / NSFW
- PII sensibles en sortie (n° de carte, mots de passe, données d'autres clients)
- Sorties hors périmètre (conseil juridique/médical, engagement de Velmo au-delà du support)
- Injections de prompt / tentatives de contournement
- Fuite de secrets ou configuration interne

Toute violation déclenche : refus poli à l'utilisateur + journalisation + escalade humaine pour les cas graves.

## Évaluation & MLOps

Trois suites d'évaluation à implémenter, rejouées **headless** via `Agent.respond` (pas via l'API HTTP) :

- **Mémoire** : rejouer `eval/memory_cases.jsonl`
- **Garde-fous** : taux de blocage sur `eval/guardrail_cases.jsonl` + taux de faux positifs
- **Qualité générale** : note globale comparable d'une version à l'autre (`eval/quality_cases.jsonl`)

La CI (`quality.yml`) bloque la livraison si la note chute sous le seuil. Chaque version (prompt + config mémoire + config garde-fous) est versionnée avec sa note dans `mlops/report.md`.

## Commandes

```bash
make up           # docker compose : app + postgres + chroma
make migrate       # alembic upgrade head
make seed          # peuple Postgres (catalogue, clients, ~14 commandes)
make seed-kb        # ingestion FAQ dans Chroma
make chat          # REPL — répond déjà aux questions métier de base
make test          # suite d'acceptance + tests métier
make fmt           # ruff format + autofix
make typecheck      # mypy
make down          # arrête les services
```
