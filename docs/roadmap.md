# Roadmap Velmo 2.0

Reconstruction de l'agent de support sur trois piliers (Mémoire, Garde-fous, Évaluation & MLOps), découpée en features via le workflow Speckit.

Légende statut : ✅ fait · ⏳ en cours · 📝 spec/design seul(e) · ⬜ à démarrer.


| # | Feature | Portée | Spec | Plan | Tasks | Implémentation |
|---|---------|--------|:----:|:----:|:-----:|:--------------:|
| **001** | Création agent | Graphe LangGraph (routage déterministe + nœud LLM outillé) | ✅ | ✅ | ✅ | ✅ |
| **002** | Mémoire court terme | Fil de conversation (checkpointer LangGraph), fenêtre glissante 30 messages | ✅ | ✅ | ✅ | ✅ |
| **003** | Mémoire long terme & RGPD | Faits durables sémantiques + épisodiques (`FactStore` Chroma/local), droit à l'oubli, traçabilité | ✅ | ✅ | ✅ | ✅ |
| **003b** | Mémoire long terme — écriture auto | Extraction automatique des faits par tour (R4 sans perte, R2 automatique), extracteur LangMem en prod | ✅ | ✅ | ✅ | ✅ |
| **004** | Sécurité & Garde-fous | Garde-fous entrée/sortie, catégories bloquées, anti-injection, journalisation & escalade | ⬜ | ⬜ | ⬜ | ⬜ *(stub `GuardrailEngine`)* |
| **005** | Évaluation automatisée | Suites d'éval **headless** (mémoire, garde-fous, qualité) contre le pipeline, sans dépendre de l'API | 📝 *(design `boucle-qualite.md`, spec.md à écrire)* | ⬜ | ⬜ | ⬜ *(`eval/*.jsonl` déjà présents)* |
| **006** | Pipeline MLOps | CI `quality.yml` (seuil bloquant), versionnage prompt/config, `mlops/report.md` par version | ⬜ | ⬜ | ⬜ | ⬜ |
