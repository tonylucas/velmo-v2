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

## 2. Portabilité — agent hybride

Par défaut, l'app doit tourner **sans Docker ni credential** (pour être projetable partout) :

- **Données métier** : `fresh_sqlite_session()` + `seed()` — le vrai catalogue, les clients et
  les ~14 commandes d'exemple, en SQLite mémoire. Toujours, quelle que soit la config.
- **Mémoire long terme** : `get_fact_store()` — bascule automatiquement sur `ChromaFactStore`
  (collection `velmo_memory`) si `CHROMA_URL` est défini et `chromadb` importable, sinon
  `LocalFactStore`. C'est ce qui permet à l'onglet « Faits durables » d'afficher le contenu réel
  de Chroma quand `docker compose up` tourne.
- **FAQ** : `get_kb()` (Chroma `velmo_faq` si configuré, sinon `LocalKB`).
- **Modèle de chat** : `get_chat_model()` (Azure Kimi si `AZURE_AI_INFERENCE_ENDPOINT`, sinon
  `OfflineChatModel`).
- **Mémoire court terme** : `InMemorySaver` explicite (le fil de conversation vit dans le process
  Streamlit, réinitialisé au redémarrage — suffisant pour une démo ; la persistance long terme,
  elle, passe par le `FactStore`).
- **Garde-fous** : `GuardrailEngine()` (déterministe, toujours actif hors-ligne).

Une seule instance d'`Agent` sert tous les clients : l'isolation repose sur `user_id`
(checkpointer keyé par `thread_id = user_id`, `FactStore` filtré par `user_id`), exactement comme
en prod. L'agent est mis en cache via `st.cache_resource` pour survivre aux reruns Streamlit.

## 3. Disposition (deux onglets + barre latérale)

**Barre latérale** :
- Sélecteur de **client** (liste des 10 clients seedés, ex. `C-marc-dubois`). Changer de client
  démontre l'isolation R3 en un clic.
- Bouton « Réinitialiser la conversation affichée » (vide l'historique d'affichage du client
  courant ; ne touche pas la mémoire long terme).
- Badge indiquant le **backend mémoire actif** : « Chroma (velmo_memory) » ou « Local ».

**Onglet 1 — Chat** :
- `st.chat_message` / `st.chat_input`, historique d'affichage dans `st.session_state`, keyé par
  client.
- À chaque message, avant `respond`, l'app appelle `guardrails.check_input(message)` pour
  connaître la décision (opération pure et déterministe, donc cohérente avec ce que `respond`
  refait en interne) et l'affiche :
  - **bloqué** → badge rouge « Bloqué — {catégorie} », la bulle assistant montre le refus poli.
  - **masqué** → badge ambre « Secret masqué », affiche le message caviardé réellement transmis.
  - **autorisé** → conversation normale.

**Onglet 2 — Faits durables (mémoire long terme)** :
- Badge du backend actif (Chroma `velmo_memory` vs Local).
- Table des `Fact` du client courant, lue via `agent.inspect_memory(user_id)` : colonnes
  `fact_type`, `key`, `content`, `created_at`, `source`. Quand Chroma est actif, c'est
  littéralement le contenu de la collection `velmo_memory` filtré par `user_id` (isolation R3
  visible : changer de client change la table, aucun fait d'un autre client n'apparaît).
- Message clair si la mémoire est vide pour ce client.

## 4. Ce que ça touche côté code

- **Créé** : `src/velmo/demo_app.py` (toute l'UI + assemblage de l'agent hybride).
- **Modifié** : `pyproject.toml` — nouvel extra optionnel `demo = ["streamlit>=1.30,<2"]`
  (hors dépendances cœur). `Makefile` — cible `demo:` lançant
  `uv run --extra demo streamlit run src/velmo/demo_app.py`.
- **Aucun changement** dans `guardrails/`, `agent.py`, `memory/`, `db.py` : l'app consomme la
  surface publique existante (`respond`, `inspect_memory`, `guardrails.check_input`,
  `get_fact_store`, `get_kb`, `get_chat_model`).

## 5. Différé / hors périmètre

- Badges de blocage **en sortie** : `respond` ne renvoie que le texte final (déjà neutralisé) ;
  le détail du blocage de sortie (identité-aware) n'est pas exposé. Les blocages de sortie sont
  rares hors-ligne ; on montre uniquement les décisions d'**entrée** (bloc / masquage), qui sont
  les plus démonstratives.
- Visualisation du journal des garde-fous (`events`) : dépend de la persistance en DB, brainstorming
  reporté.
- Édition/suppression manuelle de faits depuis l'UI : le droit à l'oubli (R5) se démontre déjà
  dans le chat (« oublie mon adresse »).

## 6. Stratégie de test

Outil de démo : pas de suite d'acceptance dédiée. Vérification : `uv run python -c "import
velmo.demo_app"` (l'import ne doit pas planter — pas d'appel Streamlit au niveau module au-delà
des `st.*` d'UI, l'assemblage de l'agent est dans une fonction cachée), et lancement manuel de
`make demo`. La logique métier sous-jacente (agent, garde-fous, mémoire) est déjà couverte par les
suites des chantiers 001-004.
