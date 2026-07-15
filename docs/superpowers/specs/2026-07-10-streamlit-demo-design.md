# Interface de démo Streamlit — conception

> Statut : validé (brainstorming). Objectif : une UI web légère pour démontrer le chat,
> les garde-fous et la mémoire long terme de Velmo 2.0 devant un public d'apprenants,
> sans détailler le code.

## 1. Objectif et périmètre

Outil de **démonstration**, pas un livrable produit. Une page Streamlit qui pilote l'`Agent`
existant (`Agent.respond`) et rend visibles trois choses : la conversation, les décisions des
garde-fous (blocage / masquage), et les faits durables retenus en mémoire long terme.

Hors périmètre : authentification réelle, multi-session concurrente, déploiement. C'est un
harnais de démo local lancé par `make demo`.

## 2. Câblage prod (pas de mode hors-ligne)

La démo pilote la **vraie stack de production** via `build_default_agent()` — c'est l'exigence :
les faits durables affichés doivent être exactement ce qui vit dans Chroma.

- **Données métier** : session PostgreSQL (`session_factory()`), le sélecteur de clients lit les
  **vrais clients** de la base.
- **Mémoire long terme** : `ChromaFactStore` (collection `velmo_memory`) via `get_fact_store()` +
  `CHROMA_URL`. L'onglet « Faits durables » lit `inspect_memory(user)` → contenu réel de la
  collection, filtré par `user_id`.
- **FAQ** : `ChromaKB` (collection `velmo_faq`) via `get_kb()`.
- **Modèle de chat** : Azure Kimi (`get_chat_model()`).
- **Mémoire court terme** : `PostgresSaver` (`get_checkpointer()` + `DB_URL`) — d'où l'ajout de
  l'extra `langgraph-checkpoint-postgres` au groupe `demo`.
- **Garde-fous** : `GuardrailEngine()` (déterministe).

Une seule instance d'`Agent` (cachée par `st.cache_resource`) sert tous les clients ; l'isolation
repose sur `user_id` (checkpointer keyé par `thread_id`, `FactStore`/business filtrés par
`user_id`).

**Pas de bascule hors-ligne** : si un backend est absent/injoignable, un **préflight** dans `main`
attrape l'exception à la construction (Chroma `get_or_create_collection`, `setup()` du checkpointer,
requête clients Postgres) et affiche un message d'aide listant les prérequis (`make up`,
`make migrate`, `make seed`, `make seed-kb`, `.env`, extras) au lieu de retomber silencieusement
sur du local — ce serait contraire à l'objectif (montrer la vraie mémoire Chroma).

**Prérequis** (une fois) : `make up` (Postgres + Chroma), `make migrate`, `make seed`,
`make seed-kb`, et un `.env` avec `DB_URL` / `CHROMA_URL` / `AZURE_AI_INFERENCE_*`. Lancement :
`make demo` (`uv run --extra demo --extra llm --extra vector streamlit run …`).

## 3. Disposition (deux onglets + barre latérale)

**Barre latérale** :
- Sélecteur de **client** (les vrais clients lus depuis Postgres). Changer de client démontre
  l'isolation R3 en un clic.
- Bouton « Réinitialiser la conversation affichée » (vide l'historique d'affichage du client
  courant ; ne touche pas la mémoire long terme).
- Panneau « Backends (prod) » : Postgres (hôte), Chroma (`velmo_memory` / `velmo_faq`), LLM Azure —
  pour confirmer le câblage prod d'un coup d'œil.

**Onglet 1 — Chat** :
- `st.chat_message` / `st.chat_input`, historique d'affichage dans `st.session_state`, keyé par
  client.
- À chaque message, avant `respond`, l'app appelle `guardrails.check_input(message)` pour
  connaître la décision (opération pure et déterministe, donc cohérente avec ce que `respond`
  refait en interne) et l'affiche :
  - **bloqué** → badge rouge « Bloqué — {catégorie} », la bulle assistant montre le refus poli.
  - **masqué** → badge ambre « Secret masqué », affiche le message caviardé réellement transmis.
  - **autorisé** → conversation normale.

**Onglet 2 — Faits durables (Chroma)** :
- Backend affiché (`ChromaFactStore` — collection `velmo_memory`).
- Table des `Fact` du client courant, lue via `agent.inspect_memory(user_id)` : colonnes
  `fact_type`, `key`, `content`, `created_at`, `source`. C'est **littéralement** le contenu de la
  collection `velmo_memory` filtré par `user_id` (isolation R3 visible : changer de client change
  la table, aucun fait d'un autre client n'apparaît).
- Message clair si la mémoire est vide pour ce client (elle se remplit à mesure que les faits sont
  extraits et écrits dans Chroma).

## 4. Ce que ça touche côté code

- **Créé** : `src/velmo/demo_app.py` (UI + préflight + assemblage via `build_default_agent()`).
- **Modifié** : `pyproject.toml` — extra `demo = ["streamlit…", "langgraph-checkpoint-postgres…"]`
  (hors dépendances cœur). `Makefile` — cible `demo:` lançant
  `uv run --extra demo --extra llm --extra vector streamlit run src/velmo/demo_app.py`.
- **Aucun changement** dans `guardrails/`, `agent.py`, `memory/`, `db.py` : l'app consomme la
  surface publique existante (`build_default_agent`, `respond`, `inspect_memory`,
  `guardrails.check_input`, `Customer`).

## 5. Différé / hors périmètre

- Badges de blocage **en sortie** : `respond` ne renvoie que le texte final (déjà neutralisé) ;
  le détail du blocage de sortie (identité-aware) n'est pas exposé. On montre uniquement les
  décisions d'**entrée** (bloc / masquage), les plus démonstratives.
- Visualisation du journal des garde-fous (`events`) : dépend de la persistance en DB, brainstorming
  reporté.
- Édition/suppression manuelle de faits depuis l'UI : le droit à l'oubli (R5) se démontre déjà
  dans le chat (« oublie mon adresse »).

## 5b. Problème connu — watcher Streamlit × PyTorch (résolu)

Les embeddings Chroma (`sentence-transformers`) chargent **PyTorch**. Le watcher de fichiers de
Streamlit inspecte les modules importés à chaque rerun ; en parcourant `torch.classes`, il
provoque un **segfault natif** (exit 139, « leaked semaphore », aucune traceback Python). Reproduit
de façon déterministe (watcher actif + modification d'un source pendant que torch est chargé →
crash) et corrigé en **désactivant le watcher** : `--server.fileWatcherType none` passé en **flag
CLI** dans la cible `make demo` (mécanisme fiable qui prime sur `.streamlit/config.toml`, dont la
prise en compte s'est révélée non garantie selon la version/découverte de config). La démo n'a pas
besoin du hot-reload. Vérifié : sous la même procédure, `none` ne crashe jamais, `auto` crashe.

## 5c. Second crash (tour de chat) — thread worker dédié (résolu)

Le watcher désactivé, un **second** segfault survient au premier message. Streamlit exécute chaque
rerun sur un thread ScriptRunner **changeant** ; or les ressources natives de l'agent (modèle
PyTorch, client Azure/**gRPC**, session SQLAlchemy, connexion checkpointer) créées sur un thread
puis réutilisées sur un autre segfaultent sur macOS. Correctif : **épingler tout le travail de
l'agent sur un unique thread worker** (`ThreadPoolExecutor(max_workers=1)`, helper
`run_on_agent(...)`) — build, `respond`, `inspect_memory` et la lecture des clients passent tous par
ce thread ; seul `guardrails.check_input` (pur, sans état natif) reste sur le thread Streamlit. Le
chemin offline (build + plusieurs tours + écriture Chroma, tout sur le worker) est vérifié ; le
chemin Azure n'a pas pu être exercé localement faute de credentials, mais l'isolation sur un thread
unique est la parade standard aux crashs natifs cross-thread sous Streamlit.

## 6. Stratégie de test

Outil de démo : pas de suite d'acceptance dédiée. Vérifications faites : `import velmo.demo_app`
ne plante pas (le corps de l'UI est sous `if __name__ == "__main__"`), `ruff check`/`format`
propres, et démarrage headless — y compris **sans backends** pour confirmer que le préflight rend
le message d'aide (`st.error` + `st.stop`) au lieu de crasher. La logique métier sous-jacente
(agent, garde-fous, mémoire) est déjà couverte par les suites des chantiers 001-004. Le chemin
prod complet (Postgres + Chroma + Azure joignables) se valide en lançant `make demo` avec les
services up.
