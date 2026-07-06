# Roadmap Velmo 2.0

Reconstruction de l'agent de support sur trois piliers (Mémoire, Garde-fous,
Évaluation & MLOps), découpée en features via le workflow Speckit.

Légende statut : ✅ fait · ⏳ en cours · 📝 spec/design seul(e) · ⬜ à démarrer.

> Ce repo est le scaffold réel (Postgres/SQLAlchemy/Alembic, `src/velmo/`, LLM Azure AI
> Inference — cf. `docs/reco_expert.md`). Les specs 001/002 migrées depuis le prototype
> spec-kit ont été volontairement délestées de leur `plan.md`/`tasks.md`/`data-model.md` :
> ces artefacts décrivaient une architecture LangGraph + AsyncPostgresSaver + ChromaDB/LangMem
> incompatible avec le scaffold existant (`Agent.respond()` synchrone, `MemoryManager`/
> `GuardrailEngine` déjà stubbés, `langchain-azure-ai`). Ils doivent être regénérés ici via
> `/speckit-plan` en tenant compte de cette réalité.

| # | Feature | Portée | Spec | Plan | Tasks | Implémentation |
|---|---------|--------|:----:|:----:|:-----:|:--------------:|
| **001** | Mémoire court terme | Fil de conversation, fenêtre glissante, overflow → long terme | ✅ | ⬜ *(à regénérer)* | ⬜ | ⬜ *(stub `MemoryManager`)* |
| **002** | Mémoire long terme & RGPD | Faits durables (Postgres relationnel), épisodique (ChromaDB), droit à l'oubli, traçabilité | ✅ | ⬜ *(à regénérer)* | ⬜ | ⬜ |
| **003** | Sécurité & Garde-fous | Garde-fous entrée/sortie, catégories bloquées, anti-injection, journalisation & escalade | ✅ | ⬜ | ⬜ | ⬜ *(stub `GuardrailEngine`)* |
| **004** | API | Exposition HTTP de l'agent (couche transport séparée, appelle `Agent.respond`) | ✅ | ⬜ | ⬜ | ⬜ |
| **005** | Frontend | UI web pour dialoguer avec l'agent, consomme l'API (004) | ⬜ | ⬜ | ⬜ | ⬜ |
| **006** | Évaluation automatisée | Suites d'éval **headless** (mémoire, garde-fous, qualité) contre le pipeline, sans dépendre de l'API | 📝 *(design `boucle-qualite.md`, spec.md à écrire)* | ⬜ | ⬜ | ⬜ *(`eval/*.jsonl` déjà présents)* |
| **007** | Pipeline MLOps | CI `quality.yml` (seuil bloquant), versionnage prompt/config, `mlops/report.md` par version | ⬜ | ⬜ | ⬜ | ⬜ |

## Ordre & dépendances

```
001 ──► 002 ──► 003 ──► 004 ──► 005 ──► 006 ──► 007
 mémoire  mémoire  garde-   API     front-  éval    MLOps
 court    long     fous     HTTP    end     qualité CI+versions
                                    │
                            005 dépend de 004
```

- **004 (API) après 002 + 003** : on n'expose l'agent via HTTP qu'une fois la mémoire long terme et les
  garde-fous en place (un agent exposé doit être gardé). L'API reste une **couche transport séparée** —
  `src/velmo/memory/` et `src/velmo/agent.py` restent agnostiques du framework web.
- **005 (Frontend) après 004** : l'UI consomme l'API ; elle en dépend directement.
- **006 avant 007** : l'éval fournit la note de qualité que la CI MLOps (007) transforme en seuil
  bloquant et en historique versionné.
- **Contrainte 006** : les suites d'évaluation tournent **headless** contre le pipeline
  (`Agent.respond`), **pas** via l'API/le frontend — 004 et 005 sont un confort d'exploration, jamais
  une dépendance de l'éval.
