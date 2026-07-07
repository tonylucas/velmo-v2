# Décision d'architecture : agent runtime LangGraph

**Date** : 2026-07-06 (révisé 2026-07-07)
**Statut** : Validé

## Contexte

`ROADMAP.md` note que les artefacts `plan.md`/`tasks.md` des specs 001 (mémoire court terme) et
002 (mémoire long terme), migrés d'un prototype spec-kit antérieur, décrivaient une architecture
LangGraph + checkpointer Postgres + LangMem jugée à l'époque incompatible avec le scaffold
(`Agent.respond()` synchrone). Ce document tranche la question et documente la décision retenue,
en amont de la régénération de ces `plan.md` via `/speckit-plan`.

Précision factuelle : la phrase de `docs/reco_expert.md` sur un agent « rapiécé une fois de
trop » désigne bien le code actuel de ce dépôt (`src/velmo/agent.py` et son routage regex,
`MemoryManager`/`GuardrailEngine` stubbés), tel qu'il existe avant les chantiers de
reconstruction. L'historique git de ce dépôt est court (6 commits) uniquement parce qu'il a été
forké aujourd'hui depuis le projet où le code et les specs 001-006 avaient déjà été élaborés
séparément — cette brièveté ne signifie pas que le code est neuf ou non rapiécé. Les specs
décrivent précisément le plan de reconstruction propre visé par la note de l'expert ; c'est ce
que les chantiers 001-007, et la décision ci-dessous, exécutent.

Les `spec.md` de 001 et 002 (déjà migrées, considérées stables) anticipent déjà cette forme
d'architecture dans leurs schémas de séquence (composants `Checkpointer` et `LangMemExtractor`)
sans jamais l'imposer dans leurs exigences fonctionnelles, qui restent volontairement agnostiques
de l'outillage. **Aucune modification de ces spec.md n'est nécessaire** : la décision ci-dessous
relève du `plan.md` (implémentation), pas de la spec (comportement attendu).

**Contraintes découvertes en préparant le plan d'implémentation** (relecture de
`src/velmo/mlops/__init__.py`, `tests/conftest.py`, `tests/acceptance/test_memory.py`,
`.github/workflows/quality.yml`) :

1. `Evaluable` (`src/velmo/mlops/__init__.py`) définit `respond(self, user_id: str, message: str)
   -> str` comme **surface publique stable, synchrone**. `cli.py` et `tests/conftest.py`
   l'appellent en synchrone. La rendre asynchrone casserait ce contrat et toute la suite de
   tests existante — inutile de toute façon : un futur endpoint HTTP async (feature 004) peut
   appeler une fonction sync sans bloquer sa boucle d'événements (FastAPI exécute les `def`
   classiques dans un thread pool ; sinon `anyio.to_thread.run_sync`). `ROADMAP.md` le dit déjà :
   *« `src/velmo/agent.py` reste agnostique du framework web »*.
2. La CI (`.github/workflows/quality.yml`) ne provisionne ni Postgres ni Chroma : `uv sync` puis
   `pytest tests/acceptance/`, rien d'autre. `tests/conftest.py` le confirme : *« tout
   hors-ligne »*. `MemoryManager()` doit donc fonctionner par défaut sans connexion réelle.
3. `tests/acceptance/test_memory.py` teste `MemoryManager` **directement**, sans passer par
   `Agent` ni par un LLM. `test_cross_session_persistence` instancie **deux** `MemoryManager()`
   séparés et attend que le second retrouve ce que le premier a écrit : la persistance doit
   survivre à l'objet Python, par défaut, sans configuration externe.
4. `test_right_to_be_forgotten` demande d'oublier une information mentionnée **une seule fois**,
   encore dans la fenêtre courte (jamais promue en fait durable). `specs/002` limite pourtant R5
   à la mémoire long terme et renvoie la suppression court terme vers `specs/001`, qui ne la
   traite pas explicitement non plus — un angle mort entre les deux specs. L'implémentation doit
   le combler : `forget()` doit pouvoir purger l'information **quel que soit son emplacement**
   (fenêtre courte ou faits durables).
5. `eval/quality_cases.jsonl` et `tests/acceptance/test_business.py::test_no_fabulation_when_out_of_stock`
   exigent des réponses métier **correctes et reproductibles avec `EchoLLM`** (pas de vrai LLM
   Azure) : « statut O-2024-0101 » → `prepared`, « om-1993 taille M disponible ? » → `indisponible`,
   etc. `EchoLLM` ne fait ni raisonnement ni tool-calling — ces réponses viennent entièrement du
   routage déterministe de `Agent._handle()`. Un agent LangGraph à tool-calling généralisé à
   **toutes** les intentions rendrait ces suites dépendantes d'un vrai LLM (coûteux, non
   déterministe) — contraire à l'objectif de qualité reproductible en CI.

## Décision

Le routage déterministe par regex de `Agent._handle()` **reste en place pour les intentions
connues** (commande, suivi, stock, FAQ, remboursement, retour, annulation...) : c'est lui qui
garantit des réponses correctes et reproductibles avec `EchoLLM` en test/CI (point 5
ci-dessus). Seul le fallback libre final (`self.llm.invoke(SYSTEM_PROMPT, "", message)`, pour les
messages qui ne matchent aucune règle) est remplacé par un **agent LangGraph à tool-calling
réel**, entièrement synchrone :

- `Agent.respond()` reste `def respond(self, user_id: str, message: str) -> str` — signature
  inchangée, conforme au `Protocol Evaluable`.
- `_handle()` garde sa structure actuelle ; seule sa dernière ligne change : au lieu d'un appel
  LLM brut, elle invoque `langgraph.prebuilt.create_react_agent`, en synchrone (`.invoke()`,
  jamais `.ainvoke()`), avec le modèle Azure déjà intégré et les outils métier exposés en `@tool`
  LangChain. Avec `EchoLLM` (test/CI), ce chemin n'est jamais exercé par les suites d'éval
  existantes (elles ciblent toutes des intentions connues du routage déterministe) ; avec un vrai
  LLM Azure en prod, le fallback peut réellement raisonner et choisir un outil pour les demandes
  hors gabarit.
- Garde-fous et mémoire (`mémoire-read`/`mémoire-write`) entourent `_handle()` exactement comme
  aujourd'hui dans `Agent.respond()` — aucun changement de flux au niveau orchestration.
- **`MemoryManager` possède toute la persistance inter-tours**, avec sélection d'arrière-plan
  pilotée par l'environnement (même pattern que `llm.py`/`db.py` : repli hors-ligne par défaut,
  vrai backend si configuré) :
  - **Fenêtre courte (R1/R4)** : checkpointer LangGraph, `thread_id = user_id`. `PostgresSaver`
    (sync, de `langgraph-checkpoint-postgres`) si `DB_URL` est configuré ; sinon `InMemorySaver`
    (`langgraph.checkpoint.memory`), instance **partagée au niveau module** pour que deux
    `MemoryManager()` du même process voient le même état (requis par
    `test_cross_session_persistence`).
  - **Faits durables (R2/R3/R5/R6)** : Chroma. Client HTTP réel (`chromadb.HttpClient`, via
    `CHROMA_URL`) si configuré ; sinon `chromadb.EphemeralClient()` (en process, repli
    hors-ligne), conformément à `specs/002-long-term-memory/spec.md`. Extraction via **LangMem**,
    utilisé uniquement pour sa fonction d'extraction (pas son `Store`/graphe) — métadonnées
    `user_id` + `fact_type`.
  - **`forget(user_id, target)`** purge les **deux** stores : réécrit/filtre l'historique
    checkpointé (fenêtre courte) et supprime les faits correspondants dans Chroma (métadonnées
    exactes) — couvre le cas testé où l'information n'a pas encore été promue en fait durable.

## Mémoire (R1–R6)

| Exigence | Mécanisme |
|---|---|
| R1 (fil de conversation 30+ messages) | Checkpointer LangGraph (`PostgresSaver`/`InMemorySaver`), `thread_id = user_id` |
| R4 (résumé au-delà de 30 messages) | Troncature/résumé du canal `messages` du checkpoint (fenêtre glissante) avant transfert vers Chroma |
| R2 (persistance durable entre sessions) | Chroma, alimenté par l'extracteur LangMem, métadonnées `user_id`/`fact_type` |
| R3 (isolation stricte par utilisateur) | `thread_id = user_id` pour le checkpointer + filtre `user_id` sur Chroma |
| R5 (droit à l'oubli vérifiable) | `forget()` : purge checkpoint (fenêtre courte) + `collection.delete(where={"user_id":..., "fact_id":...})` (faits durables) — filtres exacts, jamais de similarité |
| R6 (traçabilité/inspection) | `collection.get(where={"user_id": ...})` — lecture exacte, pas de similarité |

Les filtres de métadonnées Chroma (`where=`) sont des correspondances exactes, pas des recherches
par similarité : ils suffisent à garantir une suppression et une inspection vérifiables, sans
nécessiter de copie SQL des faits.

FR-008/FR-009 de la spec 001 (persistance synchrone du message utilisateur avant l'appel LLM,
puis de la réponse juste après) sont satisfaites par construction : `MemoryManager.write()` est
appelé de façon synchrone par `Agent.respond()` avant/après l'appel LLM, exactement comme
aujourd'hui dans `agent.py`.

## Garde-fous

Inchangés conceptuellement : deux étapes Python pures (`garde-fou-in`, `garde-fou-out`) entourant
l'agent, mêmes catégories bloquées, même journalisation. Le choix LangGraph n'a pas d'impact ici.

## Mode hors-ligne / repli

Comme `llm.py` (`EchoLLM`/`AzureLLM`) et `db.py` (`fresh_sqlite_session`), `MemoryManager`
sélectionne son backend selon l'environnement, jamais en dur :

- `DB_URL` absent → `InMemorySaver` (partagé au niveau module) ; présent → `PostgresSaver`.
- `CHROMA_URL` absent → `chromadb.EphemeralClient()` ; présent → `chromadb.HttpClient(...)`.

Ce repli garantit que `tests/acceptance/test_memory.py` et la CI (`quality.yml`, sans service
Postgres/Chroma) passent sans infrastructure externe, tout en gardant le vrai backend en
production (`make up`, docker-compose).

## Nouvelles dépendances

`langgraph`, `langgraph-checkpoint-postgres` (fournit `PostgresSaver`, compatible avec le driver
`psycopg[binary]` v3 déjà présent), `langmem`. `chromadb` est déjà présent (extra `vector`).

## Hors périmètre (explicitement écarté)

- `Agent.respond()` asynchrone, ou tout appel `.ainvoke()`/`AsyncPostgresSaver` — inutile compte
  tenu du contrat `Evaluable` synchrone et du plan pour l'API (004, couche transport séparée).
- Réécriture async de `db.py`/`tools/*.py`.
- Stockage des faits durables dans l'état checkpointé (uniquement la fenêtre courte).
- Toute table SQL dédiée aux faits durables : Chroma est l'unique source de vérité pour R2/R5/R6,
  conformément à `specs/002-long-term-memory/spec.md` et à `docs/reco_expert.md` (corrigé).
- Remplacement du routage regex de `_handle()` par du tool-calling LLM généralisé : casserait
  `eval/quality_cases.jsonl` et `test_no_fabulation_when_out_of_stock`, qui exigent des réponses
  correctes avec `EchoLLM` (sans raisonnement LLM). Le tool-calling LangGraph ne couvre que le
  fallback libre, jamais exercé par les suites d'éval actuelles.

## Prochaine étape

Plan d'implémentation détaillé via `/superpowers:writing-plans`, en référence à ce document.
