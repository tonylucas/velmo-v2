# Décision d'architecture : agent runtime LangGraph

**Date** : 2026-07-06
**Statut** : Validé

## Contexte

`ROADMAP.md` note que les artefacts `plan.md`/`tasks.md` des specs 001 (mémoire court terme) et
002 (mémoire long terme), migrés d'un prototype spec-kit antérieur, décrivaient une architecture
LangGraph + `AsyncPostgresSaver` + LangMem jugée à l'époque incompatible avec le scaffold
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

## Décision

L'agent passe d'un routage déterministe par regex à un **agent LangGraph** :

- `Agent.respond()` devient `async def respond()`, orchestrant un `StateGraph` LangGraph compilé
  avec `AsyncPostgresSaver` comme checkpointer (`thread_id = user_id`).
- Topologie du graphe : `garde-fou-in → mémoire-read → agent (create_react_agent + outils
  métier) → garde-fou-out → mémoire-write`.
- Le nœud agent utilise `langgraph.prebuilt.create_react_agent` avec le modèle Azure déjà
  intégré (`AzureAIOpenAIApiChatModel`) et les outils métier exposés en `@tool` LangChain — le
  LLM choisit l'outil à appeler, remplaçant `_handle()`.
- LangMem est utilisé uniquement pour sa fonction d'extraction de faits (pas son `Store`/graphe) :
  appelée depuis le nœud `mémoire-write`, ses résultats sont persistés directement dans Chroma
  (métadonnées `user_id` + `fact_type`), conformément à `specs/002-long-term-memory/spec.md`. Pas
  de table SQL dédiée : un fait durable extrait par LLM est du texte libre (pointure, tutoiement,
  litige...), pas une colonne typée — Chroma est le store naturel, et une copie SQL n'apporterait
  rien (schéma rigide/JSON pour du texte libre, migration à chaque nouveau `fact_type`) tout en
  dupliquant ce que spec 002 spécifie déjà. `docs/reco_expert.md` a été corrigé en conséquence :
  la ligne imposant Postgres comme source de vérité des faits durables a été retirée (elle
  entrait en contradiction directe avec spec 002, déjà validée).

## Mémoire (R1–R6)

| Exigence | Mécanisme |
|---|---|
| R1 (fil de conversation 30+ messages) | Canal `messages` du state LangGraph, checkpointé par `AsyncPostgresSaver` |
| R4 (résumé au-delà de 30 messages) | Nœud de troncature/résumé qui borne le canal `messages` (fenêtre glissante) |
| R2 (persistance durable entre sessions) | Chroma (hors checkpoint), alimenté par l'extracteur LangMem, métadonnées `user_id`/`fact_type` |
| R3 (isolation stricte par utilisateur) | `thread_id = user_id` pour le checkpointer + filtre `user_id` sur Chroma |
| R5 (droit à l'oubli vérifiable) | `collection.delete(where={"user_id": ..., "fact_id": ...})` — filtre exact, pas de similarité — puis vérification par `collection.get(where=...)` vide. Jamais de dépendance à `delete_thread` |
| R6 (traçabilité/inspection) | `collection.get(where={"user_id": ...})` — lecture exacte, pas de similarité |

Point clé : le checkpoint ne doit contenir **que** la fenêtre courte bornée (R1/R4), jamais les
faits durables. C'est ce qui rend R5 vérifiable — la suppression grossière `delete_thread` n'est
jamais le mécanisme de suppression RGPD, réservé à un effacement de compte complet. Les filtres de
métadonnées Chroma (`where=`) sont des correspondances exactes, pas des recherches par similarité :
ils suffisent à garantir une suppression et une inspection vérifiables, sans nécessiter de copie
SQL des faits.

FR-008/FR-009 de la spec 001 (persistance synchrone du message utilisateur avant l'appel LLM,
puis de la réponse juste après) sont satisfaites nativement : `AsyncPostgresSaver` checkpointe
l'état après chaque super-step du graphe. Comme `garde-fou-in`/`mémoire-read` s'exécutent avant
le nœud agent, le message utilisateur est déjà durci en base avant l'appel LLM, sans nœud de
persistance dédié.

## Garde-fous

Inchangés conceptuellement : deux nœuds Python purs (`garde-fou-in`, `garde-fou-out`) entourant
l'agent, mêmes catégories bloquées, même journalisation. Le choix LangGraph n'a pas d'impact ici.

## Frontière synchrone/asynchrone

Pour limiter le rayon d'impact, `db.py` et `tools/*.py` restent **synchrones** tels quels (pas de
réécriture SQLAlchemy async). Chaque nœud async qui a besoin d'un outil l'appelle via
`asyncio.to_thread(...)`. Changent uniquement : la signature de `Agent.respond()` (async),
`cli.py` (`asyncio.run(...)` par tour), et les points d'appel dans les tests/l'éval
(`asyncio.run()`, sans besoin de `pytest-asyncio`).

## Nouvelles dépendances

`langgraph`, `langgraph-checkpoint-postgres` (fournit `AsyncPostgresSaver`, compatible avec le
driver `psycopg[binary]` v3 déjà présent — pas besoin d'`asyncpg`), `langmem`.

## Hors périmètre (explicitement écarté)

- Réécriture async de `db.py`/`tools/*.py`.
- Stockage des faits durables dans l'état checkpointé (uniquement la fenêtre courte).
- Toute table SQL dédiée aux faits durables : Chroma est l'unique source de vérité pour R2/R5/R6,
  conformément à `specs/002-long-term-memory/spec.md` et à `docs/reco_expert.md` (corrigé).

## Prochaine étape

Régénérer `plan.md`/`tasks.md` pour 001 puis 002 via `/speckit-plan`, en référence à ce document.
