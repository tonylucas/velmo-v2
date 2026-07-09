# Chantier 002 — Mémoire court terme : dossier de conception

> Statut : design validé en brainstorming, prêt pour le plan d'implémentation.
> Périmètre : **court terme uniquement** (R1 + fenêtre glissante). Le long terme
> (R2/R3-faits/R5/R6, faits durables, **résumé/sélection épisodique Chroma =
> R4 « sans perte »**, droit à l'oubli) est le **chantier 003**.

## 1. Intention

Donner à l'agent une vraie mémoire de conversation : tenir le fil d'un échange
(R1) et **borner la fenêtre de contexte** envoyée au modèle (fenêtre glissante),
sans jamais perdre de données côté stockage.

Décision structurante : **on n'écrit pas de gestionnaire de mémoire maison.** La
version précédente tenait « avec de la ficelle » (audit `docs/reco_expert.md`) ;
on repart sur les primitives natives de LangGraph. La mémoire court terme, c'est
le **checkpointer** — écrit par le runtime du graphe, jamais poké à la main.

Conséquence directe : la classe stub `MemoryManager` (dans `src/velmo/memory/`)
est **supprimée**. Elle n'était consommée que par la suite d'acceptance et
l'agent ; les deux sont réoutillés pour parler au checkpointer. **Le package
`memory/` reste** : c'est le foyer du pilier mémoire — le checkpointer court
terme y vit (`memory/checkpointer.py`) et le long terme l'y rejoindra en 003.

## 2. Modèle mémoire (LangGraph canonique)

Un agent LangGraph idiomatique répartit la mémoire sur deux primitives :

| Primitive | Rôle | Backend hors-ligne / prod | Exigences | Chantier |
|---|---|---|---|---|
| **Checkpointer** (`InMemorySaver` / `PostgresSaver`) | mémoire **court terme**, thread-scoped : l'historique des messages, persisté par le runtime à chaque tour, keyé par `thread_id` | `InMemorySaver` / `PostgresSaver` | **R1**, fenêtre glissante | **002** |
| **Store** (`BaseStore` : `InMemoryStore` / `PostgresStore`) + **Chroma** (épisodique) | mémoire **long terme** : faits typés cross-thread + souvenirs épisodiques récupérés sémantiquement | (déféré) | R2, R3-faits, **R4 (résumer/sélectionner sans perte)**, R5, R6 | 003 |

Ce chantier ne construit que la **colonne de gauche**. On ne touche pas au Store
ni à Chroma.

### 2.1 Où vit R4 ? (point clarifié en brainstorming)

R4 — « Au-delà des 30 messages, **résumer / sélectionner** sans perdre
l'information critique » — recouvre **deux** préoccupations qu'il faut séparer :

1. **Borner la fenêtre active** (mémoire de travail) : empêcher le contexte
   envoyé au LLM de grossir sans fin. → **court terme, 002** (« fenêtre
   glissante »).
2. **Ne pas perdre / re-sélectionner l'excédent** : stocker les vieux tours et
   pouvoir les récupérer plus tard, y compris une autre session. Le verbe
   « **sélectionner** » = récupération sémantique = embeddings + **ChromaDB**. →
   **long terme, 003** (épisodique).

Donc le **« sans perte » de R4 relève du 003**. 002 se contente de borner la
fenêtre. C'est aligné avec la roadmap : 002 = « fenêtre glissante, **overflow →
long terme** » ; 003 = « épisodiques (ChromaDB) ».

### 2.2 Identité de thread

`thread_id = user_id`. En 002, un client = un thread de conversation. Suffisant
pour R1, et l'isolation court terme R3 est garantie par construction : deux
`user_id` distincts ⇒ deux threads qui ne se croisent jamais dans le
checkpointer. Un `session_id` distinct (plusieurs conversations pour un même
client) pourra s'ajouter plus tard sans casser cette surface.

## 3. Architecture du pipeline

```
message
  → guardrails.check_input           (stub, chantier 004)
  → graphe LangGraph (avec checkpointer, config thread_id=user_id)
        deterministic_node → (route) → llm_node | END
        (llm_node applique la fenêtre glissante : 30 derniers messages au LLM)
  → guardrails.check_output          (stub, chantier 004)
  → réponse
```

Changements par rapport au chantier 001 :

- Le graphe est compilé **avec** un checkpointer : `graph.compile(checkpointer=...)`.
- `Agent.respond(user_id, message)` invoque le graphe avec **seulement le
  nouveau message** et `config={"configurable": {"thread_id": user_id}}`. Le
  checkpointer charge l'historique du thread, `add_messages` fusionne le nouveau
  message. Plus d'appels `memory.read(...).render()` ni `memory.write(...)`.
- Le nœud LLM applique une **fenêtre glissante à la lecture** : il ne passe que
  les 30 derniers messages au modèle, sans jamais toucher au state persisté.

`Agent` perd son paramètre `memory`. `build_default_agent` et les fixtures
`tests/conftest.py` (`build_reference_agent`, `build_degraded_agent`) sont mis à
jour. Les garde-fous restent appelés autour du graphe (stubs inchangés).

### 3.1 Le checkpointer : `get_checkpointer()`

Factory symétrique à `get_kb()` / `get_chat_model()` :

- `PostgresSaver` si `DB_URL` est défini **et** `langgraph-checkpoint-postgres`
  importable ;
- sinon `InMemorySaver` (hors-ligne, tests, éval).

Le cœur tourne donc hors-ligne sans docker ni credentials, conformément au
principe du projet.

### 3.2 Fenêtre glissante « soft » (lecture) — la fenêtre du court terme

**Choix : soft window.** Le checkpointer **conserve l'historique complet** ; on
ne borne que les messages **passés au LLM**. Aucune donnée n'est jamais perdue
en 002 — l'élagage réel et la récupération de l'excédent arrivent en 003 (Chroma).

- **Fenêtre : 30 messages** (messages, pas tours — un échange = 2 messages).
- Mécanisme : avant l'appel au modèle dans `llm_node`, on tronque la liste aux
  30 derniers messages (via `langchain_core.messages.trim_messages`, idéalement
  branché comme `pre_model_hook` de `create_agent`). Le state externe (source de
  vérité) n'est **pas** modifié : pas de `RemoveMessage`, pas de résumé, pas
  d'extraction d'entités.
- Ce que fait 003 par-dessus : avant que l'excédent ne sorte de la fenêtre, le
  persister comme souvenir épisodique dans Chroma, puis le **re-sélectionner**
  sémantiquement à la lecture et l'injecter — c'est le « sans perte » de R4 et le
  rappel cross-session.

## 4. Ce qui est explicitement déféré au chantier 003

- **R4 « résumer / sélectionner sans perte »** : persistance de l'excédent
  épisodique dans **Chroma** + récupération sémantique injectée au contexte.
- **Faits durables sémantiques** (`remember_fact`) et leur **extraction
  automatique** par l'agent (l'extracteur de faits du schéma de séquence).
- **Droit à l'oubli (R5)** et **inspection (R6)**, qui opèrent sur le Store.
- **Isolation des faits long terme (R3)** via namespace `user_id` du Store.
  (L'isolation *court terme* R3, elle, est déjà assurée en 002 par le `thread_id`.)

## 5. Stratégie de test

### 5.1 Recall sur 30+ messages (R1) — réécrit

Le test pilote **l'agent** (donc le nœud LLM tourne réellement à chaque tour),
puis asserte sur la **mémoire retenue**, pas sur la réponse du modèle :

```python
def test_recall_over_30_messages(reference_agent):
    user = "acc-recall"
    reference_agent.respond(user, "Ma commande prioritaire est O-2024-0101.")
    for i in range(30):
        reference_agent.respond(user, f"Question de suivi {i} sur un maillot.")

    state = reference_agent.get_state(user)          # -> graph.get_state(config)
    rendered = render_messages(state)                # concatène messages retenus
    assert "O-2024-0101" in rendered
```

Justification : en hors-ligne, `OfflineChatModel` ne fait qu'un écho et ne
saurait restituer `O-2024-0101` dans sa réponse. R1, c'est la **rétention du
fil** : on la vérifie là où elle vit — le state du checkpointer, lisible par
l'API haut niveau `graph.get_state(config)`. En soft window, le checkpointer
conserve l'historique complet, donc le message 1 y figure. Le « l'agent répond
correctement grâce à la mémoire » sera prouvé avec le vrai modèle Kimi dans la
suite d'éval MLOps (chantier 005).

`Agent` expose donc un accès de lecture au state (`Agent.get_state(user_id)` ou
un utilitaire `agent_graph.get_state(...)`) — surface minimale de traçabilité,
réutilisable plus tard par R6.

### 5.2 Tests unitaires nouveaux

- **Fenêtre glissante** : quand le thread dépasse 30 messages, le nœud LLM ne
  reçoit que les 30 derniers (on vérifie la liste effectivement passée au
  modèle), **mais** `get_state` en contient toujours plus (aucune perte).
- **Persistance de thread** : deux `respond` successifs sur le même `user_id`
  partagent l'historique ; deux `user_id` distincts ne le partagent pas
  (isolation court terme R3).

### 5.3 Tests long terme temporairement cassés

`test_cross_session_persistence` (R2), `test_isolation_between_customers` (R3
faits), `test_right_to_be_forgotten` (R5) appelaient `MemoryManager` supprimé.
Ils sont marqués `@pytest.mark.xfail(reason="chantier 003 — Store long terme")`
(ou `skip`) avec TODO explicite. On casse volontairement le long terme, il est
repris au chantier suivant.

`test_recall_over_30_turns` (rappel après overflow), lui, **passe en 002** grâce
à la soft window (il est réécrit comme en 5.1, pas xfaillé).

## 6. Fichiers touchés (indicatif)

- `src/velmo/memory/checkpointer.py` — **créé** : `get_checkpointer()`.
- `src/velmo/agent_graph.py` — **modifié** : param checkpointer sur
  `build_graph`, fenêtre glissante (`trim_messages` / `pre_model_hook`) dans
  `llm_node`, `thread_id` dans `answer`, helper `get_state`.
- `src/velmo/agent.py` — **modifié** : suppression du paramètre `memory` et des
  appels `memory.read/write` ; `respond` passe le `config` thread ; ajout
  `get_state`.
- `src/velmo/memory/__init__.py` — **modifié** : `MemoryManager`/`MemoryContext`
  retirés, package conservé (foyer du pilier mémoire).
- `tests/conftest.py` — **modifié** : fixtures agents sans `MemoryManager`,
  checkpointer branché.
- `tests/acceptance/test_memory.py` — **modifié** : recall réécrit (vert) ;
  R2/R3-faits/R5 `xfail`.
- `tests/test_agent_graph.py` — tests fenêtre glissante + persistance de thread.
- `CLAUDE.md` — **modifié** : section mémoire (checkpointer, plus de
  `MemoryManager`).

## 7. Points de vigilance

- **`PostgresSaver` en prod** nécessite `.setup()` (création des tables) et une
  gestion de cycle de vie (context manager / connexion persistante). Wiring prod
  best-effort, **non couvert par un test hors-ligne**, à valider quand une base
  Postgres réelle est branchée. Ne bloque pas 002.
- **Croissance du checkpointer (soft window)** : conserver l'historique complet
  fait grossir le state persisté à chaque tour (coût prod, surtout PostgresSaver).
  C'est assumé en 002 ; l'**élagage réel** (l'excédent part dans Chroma puis est
  retiré du thread) est précisément le travail du chantier 003.
- **Message bloqué par un garde-fou d'entrée** : le graphe n'est pas invoqué,
  donc le message n'entre pas dans l'historique du checkpointer. Comportement
  acceptable, voire souhaitable (on ne mémorise pas une requête refusée).
- **`create_agent` (ReAct interne) et le checkpointer** : le checkpointer est
  branché sur le **graphe externe** (source de vérité de l'historique). Le nœud
  `llm_node` invoque l'agent ReAct avec une **vue tronquée** (30 derniers
  messages) du state externe ; l'agent interne reste sans état propre. On vérifie
  que le merge `add_messages` (dédup par `id`) ne duplique pas les messages entre
  les deux niveaux.
- **`token_budget`** : l'ancien `MemoryManager(token_budget=2000)` disparaît. Le
  bornage se fait par nombre de messages (30). Un bornage par tokens s'ajouterait
  dans la même fenêtre glissante si besoin.

## 8. Exigences couvertes

| Exigence | Couverte en 002 ? | Mécanisme |
|---|---|---|
| R1 — fil de 30 messages | ✅ | checkpointer (historique thread-scoped) |
| Fenêtre glissante | ✅ | soft window : 30 derniers messages au LLM, state complet conservé |
| R3 — isolation (court terme) | ✅ | `thread_id = user_id` |
| R4 — résumer/sélectionner sans perte | ❌ → 003 | épisodique Chroma (persistance overflow + récupération) |
| R2 — persistance cross-session (faits) | ❌ → 003 | Store |
| R3 — isolation (faits long terme) | ❌ → 003 | namespace Store |
| R5 — droit à l'oubli | ❌ → 003 | `store.delete` |
| R6 — inspection | ⚠️ amorce | `get_state` (court terme) ; complet en 003 via Store |
