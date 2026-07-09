# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Règles générales

- Tout ce qui est codé (identifiants, noms de fichiers, messages de commit, docstrings, commentaires)
  est **en anglais**, même quand la discussion avec l'utilisateur se déroule en français. Seuls les
  textes destinés à l'utilisateur final de l'agent Velmo (réponses du chatbot, contenu de `kb/docs/`,
  messages de refus) restent en français puisque c'est la langue du produit.
- Applique les bonnes pratiques du langage/framework concerné (voir aussi `pyproject.toml` : ruff,
  mypy strict) sans qu'on ait besoin de le rappeler à chaque fois.
- Ne te contente pas d'implémenter ce qui est demandé littéralement : signale les recommandations
  pertinentes (architecture, sécurité, perf) et pense activement aux edge cases (entrées vides,
  concurrence, isolation entre utilisateurs, limites R1-R6, etc.) plutôt que de les découvrir via les
  tests.

## Projet

Velmo 2.0 — reconstruction complète (from scratch) de l'agent de support d'une boutique en ligne de
maillots de foot collector. L'ancienne version a été jugée irrécupérable par un audit externe
(`docs/reco_expert.md`) : mémoire fragile, garde-fous posés au cas par cas, aucune mesure de qualité
reproductible. Le cahier des charges complet est dans `docs/brief.md`, le découpage en features dans
`docs/roadmap.md`.

Trois exigences non négociables structurent tout le travail :
1. **Mémoire** (court terme + long terme, isolation par utilisateur, droit à l'oubli, traçabilité — R1 à R6 détaillées dans `docs/brief.md`).
2. **Garde-fous** en entrée *et* en sortie (haine/violence/sexuel, PII, hors-périmètre, injection de prompt, fuite de secrets).
3. **Qualité mesurée en continu** (suites d'évaluation, note globale versionnée, seuil bloquant en CI).

État actuel : le routage déterministe et les outils métier (accès Postgres réel) sont fonctionnels.
`memory/`, `guardrails/` et `mlops/` exposent une **surface publique stable, déjà consommée par la
suite d'acceptance**, mais leur logique interne est en stub (no-op ou `NotImplementedError`) — c'est
le travail à construire. Ne change pas ces signatures sans regarder ce que `tests/acceptance/` et
`tests/conftest.py` en attendent : ce sont les contrats à satisfaire.

## Commandes

```bash
uv sync                                   # coeur + base + outils de dev
uv sync --extra vector --extra llm        # + Chroma + Azure AI Inference

make up            # docker compose : app + postgres + chroma
make migrate       # alembic upgrade head
make seed          # peuple Postgres (catalogue, clients, ~14 commandes)
make seed-kb       # ingestion FAQ dans Chroma
make chat          # REPL de conversation (agent.cli --user <id>)

make test          # uv run pytest tests/ -v
make fmt           # ruff format + autofix
make lint          # ruff check
make typecheck     # uv run mypy src   (mypy strict = true)
make eval          # uv run python -m velmo.mlops.score (à construire)
```

Tests ciblés :
```bash
uv run pytest tests/acceptance/test_memory.py -v
uv run pytest tests/acceptance/test_memory.py::test_recall_over_30_messages -v
uv run pytest tests/ -k isolation
```

Le coeur tourne **entièrement hors-ligne** : SQLite en mémoire pour les tests, `LocalKB` (TF-IDF local)
pour la FAQ, `OfflineChatModel` pour le LLM. Les intégrations réelles (Postgres, Chroma, Azure AI Inference) ne
s'activent que si les variables d'env correspondantes sont présentes (`DB_URL`, `CHROMA_URL`,
`AZURE_AI_INFERENCE_ENDPOINT`) — voir `.env.example`. Ça veut dire qu'on peut développer/tester `memory`,
`guardrails`, `mlops` sans docker compose ni credentials.

## Architecture

### Pipeline de l'agent (`src/velmo/agent.py` + `src/velmo/agent_graph.py`)

```
message → guardrails.check_input → graphe LangGraph (mémoire court terme via checkpointer ; routage déterministe → nœud LLM outillé) → guardrails.check_output → réponse
```

`Agent.respond()` orchestre ce pipeline et délègue le raisonnement à `agent_graph.answer(...)`.
L'agent est un `StateGraph` LangGraph à deux nœuds (`src/velmo/agent_graph.py`) :
- `deterministic_node` reprend la logique de `velmo.routing.run_deterministic` — **routage déterministe
  par regex** (numéro de commande `O-\d{4}-\d{4}`, mots-clés d'intention comme « annul », « rembours »,
  « taille », alias produits) — et appelle les outils métier directement, sans LLM.
- si aucune intention n'est reconnue, le graphe route vers `llm_node` : un agent ReAct (`create_agent`
  + `velmo.agent_tools.build_tools`) outillé avec les 10 outils métier fermés sur `session`/`user_id`/`kb`
  (le LLM ne choisit jamais `user_id`, isolation garantie par fermeture).

Les actions qui modifient une commande (annulation, adresse, taille, retour, remboursement) passent
par `_confirm_or_act` (dans `velmo.routing`) : elles exigent une confirmation explicite du client
(« je confirme », etc.) avant d'exécuter l'outil — pour l'instant cette confirmation ne s'applique
qu'au chemin déterministe (limite documentée dans
`docs/superpowers/specs/2026-07-08-agent-langgraph-design.md`).

`build_default_agent()` est le point d'assemblage prod (session Postgres réelle + `get_kb()` +
`get_chat_model()`). `tests/conftest.py` fournit l'équivalent test (`build_reference_agent`,
`build_degraded_agent` avec des SQLite seedées et `OfflineChatModel`/`LocalKB`).

La **mémoire court terme** est le checkpointer LangGraph (`velmo.memory.checkpointer.get_checkpointer` :
`InMemorySaver` hors-ligne, `PostgresSaver` si `DB_URL`), compilé dans le graphe et keyé par
`thread_id = user_id`. `Agent.respond` n'invoque qu'avec le nouveau message ; le runtime charge et
persiste l'historique. Une **soft window** (`agent_graph.window_messages`, 30 messages) borne le prompt
LLM sans élaguer le state (`Agent.get_state(user_id)` restitue l'historique complet). Il n'y a plus de
`MemoryManager` maison.

### Trois modules à construire, avec surface publique déjà figée

- **Mémoire long terme (chantier 003, fait pour R2/R3/R5/R6)** : `FactStore` sur le
  patron `kb_store` (`velmo.memory.fact_store.get_fact_store` : `LocalFactStore`
  hors-ligne, `ChromaFactStore` / collection `velmo_memory` en prod). Faits typés
  (`velmo.memory.facts.Fact`, sémantique vs épisodique, FR-009), trois outils
  (`velmo.tools.memory_tools` : `remember_fact`/`forget_user_data`/`inspect_user_memory`),
  recherche par tour injectée dans le `context` du graphe. Intentions d'oubli/inspection
  routées en déterministe (FR-010). **Différé** : extraction auto LangMem/LLM, ingestion
  « sans perte » de l'excédent (R4), async.
- **`guardrails/`** (`GuardrailEngine`) : `check_input(message) -> Decision`,
  `check_output(text) -> Decision`, journalisation via `self.events`. Catégories dans `CATEGORIES`
  (hate, violence, sexual, pii, out_of_scope, prompt_injection, secret_leak). Les tests
  (`tests/acceptance/test_guardrails.py`) attendent un blocage strict des catégories interdites, une
  résistance à l'injection de prompt, et un **taux de faux positifs sous seuil** sur `eval/guardrail_cases.jsonl`
  — l'équilibre sécurité/utilité est jugé, pas juste le blocage brut.
- **`mlops/`** : `run_eval(agent) -> Scores` (note mémoire/garde-fous/qualité + note globale),
  `enforce_threshold(scores, min_score)` (lève `DeliveryBlocked` sous le seuil),
  `write_report(scores, path)` (doit contenir note mémoire, taux de blocage, faux positifs, latence,
  coût — voir `test_report_contains_signals`), `current_version()`. Le pattern clé pour prouver la
  non-régression : `tests/conftest.py` fournit un `degraded_agent` (garde-fous neutralisés via
  `AllowAllGuardrails`) dont la note doit être strictement inférieure à celle du `reference_agent`
  (`test_regression_blocks_delivery`). `.github/workflows/quality.yml` a une étape "Quality gate"
  commentée à activer une fois `velmo.mlops.score` disponible.

### Outils métier (`src/velmo/tools/`)

Chaque outil encapsule ses propres règles métier — pas de couche de validation séparée :
- **Isolation client** : `_common.owned_order(session, order_id, user_id)` renvoie `None` (→
  `{"error": "not_found_or_forbidden"}`) si la commande n'appartient pas à l'appelant. Tous les outils
  d'action/lecture sur commande passent par là.
- **Modifiabilité** : `MODIFIABLE_STATUSES = {paid, prepared}`. Toute tentative de modification/annulation
  sur une commande `shipped`+ crée une `Escalation` et renvoie `{"action": "escalate"}` au lieu
  d'échouer silencieusement.
- **Plafond de remboursement** : `REFUND_CAP = 50.0` (`tools/_common.py`). Au-delà, `trigger_refund`
  crée un `Refund(status=escalated)` + une `Escalation`, jamais d'auto-remboursement.
- Convention de retour : dict avec soit `{"error": ...}`, soit `{"action": "escalate"|"updated"|...}`,
  jamais d'exception pour un cas métier attendu.

### Données (`src/velmo/db.py`)

SQLAlchemy 2 déclaratif, IDs lisibles en chaîne (`O-2024-0103`, `C-marc-dubois`, `mu-1999-treble`) —
volontairement pas des UUID, pour rester déboguable à l'œil. Le schéma est portable Postgres/SQLite :
`make_engine()`/`session_factory()` lisent `DB_URL` (Postgres par défaut) ; `fresh_sqlite_session()`
crée une base SQLite en mémoire avec le même schéma pour les tests. `alembic/` gère les migrations
Postgres seulement (SQLite de test est recréée à chaque fixture via `Base.metadata.create_all`).

### FAQ / KB (`src/velmo/kb_store.py`)

`get_kb()` retourne `ChromaKB` si `CHROMA_URL` est défini et que `chromadb` est importable, sinon
`LocalKB` (scoring TF-IDF léger sur `kb/docs/*.md`, sans dépendance externe). Les deux backends exposent
la même interface `search(query, k) -> list[dict]` avec `source`/`snippet`.

### LLM (`src/velmo/llm.py`)

`get_chat_model()` retourne un `AzureAIOpenAIApiChatModel` (Kimi-K2.6 via `langchain-azure-ai`, import
différé) si `AZURE_AI_INFERENCE_ENDPOINT` est défini, sinon `OfflineChatModel` (accusé de réception
déterministe, sans tool-calling). L'agent est un `StateGraph` (`velmo.agent_graph`) : le nœud
déterministe (`velmo.routing`) route la majorité des intentions sans LLM, et ne bascule sur le nœud LLM
outillé (`create_agent` + `build_tools`) que lorsqu'aucune règle ne matche.

### Tests (`tests/`)

- `tests/acceptance/` = traduction directe des critères d'acceptance du brief (`test_business.py`,
  `test_guardrails.py`, `test_memory.py`, `test_mlops.py`) — ce sont les tests que l'implémentation
  finale doit faire passer, pas des tests à modifier légèrement pour qu'ils passent.
- `tests/conftest.py` centralise les fixtures : sessions SQLite seedées (`db_session`), FAQ locale
  (`kb`), agents pré-assemblés (`reference_agent`, `degraded_agent`).
- `eval/*.jsonl` (`memory_cases.jsonl`, `guardrail_cases.jsonl`, `quality_cases.jsonl`) sont les jeux de
  cas rejoués par les suites d'évaluation MLOps ET par certains tests d'acceptance
  (`test_legitimate_messages_not_blocked` charge `guardrail_cases.jsonl` pour mesurer les faux positifs).
- `pyproject.toml` fixe `pythonpath = ["src", "tests"]`, donc les tests importent `velmo` directement et
  peuvent faire `from conftest import ...` sans passer par un package.
