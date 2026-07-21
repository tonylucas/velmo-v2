# Roadmap Velmo 2.0

Reconstruction de l'agent de support sur trois piliers (Mémoire, Garde-fous, Évaluation & MLOps), découpée en features via le workflow Speckit.

Légende statut : ✅ fait · ⏳ en cours · 📝 spec/design seul(e) · ⬜ à démarrer.


| # | Feature | Portée | Spec | Plan | Tasks | Implémentation |
|---|---------|--------|:----:|:----:|:-----:|:--------------:|
| **001** | Création agent | Graphe LangGraph (routage déterministe + nœud LLM outillé) | ✅ | ✅ | ✅ | ✅ |
| **002** | Mémoire court terme | Fil de conversation (checkpointer LangGraph), fenêtre glissante 30 messages | ✅ | ✅ | ✅ | ✅ |
| **003** | Mémoire long terme & RGPD | Faits durables sémantiques + épisodiques (`FactStore` Chroma/local), droit à l'oubli, traçabilité | ✅ | ✅ | ✅ | ✅ |
| **003b** | Mémoire long terme — écriture auto | Extraction automatique des faits par tour (R4 sans perte, R2 automatique), extracteur LangMem en prod | ✅ | ✅ | ✅ | ✅ |
| **004** | Sécurité & Garde-fous | Garde-fous entrée/sortie déterministes hors-ligne + surcouche prod Content Safety (modération, anti-injection), masquage PII entrée, blocage identité-aware sortie, journalisation | ✅ | ✅ | ✅ | ✅ |
| **005a** | Évaluation automatisée | Suites d'éval **headless** (mémoire, garde-fous, qualité) rejouant `eval/*.jsonl`, note globale 55/45 avec effondrement à 0 sur brèche garde-fous, `enforce_threshold`, `mlops/report.md` | ✅ | ✅ | ✅ | ✅ |
| **005b** | Pipeline CI/CD | CI trunk-based (label `ready-for-eval` → gate, invalidation au commit), tag `v*.*.*` → gate → GitHub Release versionnée, déploiement ACA détachable conditionné au gate vert | ✅ | ✅ | ✅ | ✅ |
| **005c** | Observabilité prod | Traces Langfuse sur l'agent en prod : latence, coût par conversation, taux de blocage par catégorie, escalades, erreurs outils | ⬜ | ⬜ | ⬜ | ⬜ |
| **005d** | Qualité des réponses mesurée | Contexte mémoire exposé en observation `retriever`, et **score `relevance`** produit par un évaluateur Langfuse échantillonné (aucune dépendance ajoutée : le scoring est de la configuration). `faithfulness` écarté — voir `infra/README.md` | ✅ | ✅ | ✅ | ✅ |
