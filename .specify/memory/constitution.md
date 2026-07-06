<!--
SYNC IMPACT REPORT
==================
Version change: 1.0.0 → 1.1.0
Bump rationale: MINOR — nouveau principe ajouté (VIII. Posture pédagogique), aucune règle existante
retirée ni redéfinie.

Modified principles: N/A

Added sections:
  - Core Principles : VIII. Posture pédagogique — remise en question et bonnes pratiques

Removed sections: N/A

Clarifications de périmètre :
  - Feature "FAQ" explicitement hors périmètre du projet (non spécifiée, non planifiée).

Templates requiring updates:
  - .specify/templates/plan-template.md   ✅ aligné (aucune section liée à la posture pédagogique requise)
  - .specify/templates/spec-template.md   ✅ aligné (pas d'impact — principe comportemental, pas fonctionnel)
  - .specify/templates/tasks-template.md  ✅ aligné (pas d'impact)

Follow-up TODOs:
  - TODO(RATIFICATION_DATE): date inconnue — à confirmer par le formateur lors de la validation du dossier de conception.
  - Azure Foundry credentials: à configurer dans les secrets GitHub Actions avant le premier run CI.
-->

# Velmo 2.0 Constitution

## Core Principles

### I. Conception avant le code (NON-NÉGOCIABLE)

Aucune ligne de code ne DOIT être écrite avant que le dossier de conception soit validé par le formateur.
Le dossier comprend : schéma d'architecture global, modèle de données mémoire, tableau des garde-fous,
schéma de la boucle qualité.
Les rapports de conception sont produits en Markdown dans `docs/`.

### II. Architecture en pipeline

Le flux de traitement DOIT respecter l'ordre suivant sans exception :

```
entrée → garde-fou d'entrée → mémoire (lecture) → LLM → garde-fou de sortie → mémoire (écriture) → réponse
```

Toute modification de l'ordre ou tout court-circuit de ce pipeline DOIT être justifié et documenté.

### III. Mémoire exemplaire — exigences R1–R6

L'implémentation DOIT satisfaire les six exigences suivantes, chacune vérifiable par test d'acceptance :

| Réf | Exigence |
|-----|----------|
| R1 | Tenir le fil d'une conversation de 30 tours (messages). |
| R2 | Mémoire long terme persistante entre sessions (faits/préférences durables) |
| R3 | Isolation stricte par utilisateur — aucune fuite inter-utilisateur |
| R4 | Au-delà des 30 messages, résumer / sélectionner sans perdre l'information critique. |
| R5 | Droit à l'oubli RGPD : suppression effective et vérifiable |
| R6 | Traçabilité : inspection de la mémoire d'un utilisateur |

La mémoire long terme n'est PAS un outil de l'agent — c'est le magasin persistant des faits durables.

### IV. Garde-fous systématiques — entrée ET sortie

Chaque catégorie interdite ci-dessous DOIT être bloquée à l'entrée et/ou en sortie selon le tableau de
conception. Toute violation déclenche : refus poli à l'utilisateur + journalisation + escalade humaine
pour les cas graves.

Catégories interdites :
- Contenus haineux, discriminatoires, harcèlement
- Violence, menaces, incitation à se nuire
- Contenus sexuels / NSFW
- PII sensibles en sortie (n° de carte, mots de passe, données d'autres clients)
- Sorties hors périmètre (conseil juridique/médical, engagement Velmo au-delà du support)
- Injections de prompt / tentatives de contournement
- Fuite de secrets ou de configuration interne

Le taux de faux positifs DOIT rester sous le seuil défini dans `mlops/report.md`.

### V. Qualité mesurée en continu

Trois suites d'évaluation DOIVENT être implémentées et exécutées à chaque version :

1. **Mémoire** : rejouer `memorycases.jsonl` → note mémoire
2. **Garde-fous** : taux de blocage sur `guardrailcases.jsonl` + taux de faux positifs
3. **Qualité générale** : note globale comparable d'une version à l'autre

La CI (GitHub Actions — `.github/workflows/quality.yml`) DOIT bloquer la livraison si la note globale
chute sous le seuil. Chaque version (prompt + config mémoire + config garde-fous) DOIT être versionnée
avec sa note dans `mlops/report.md`.

### VI. Confirmation avant toute action irréversible

L'agent NE DOIT PAS exécuter un outil d'action (`updateorderitem`, `cancelorder`, `createreturn`,
`triggerrefund`) sans confirmation explicite de l'utilisateur. Il DOIT escalader via `escalateto_human`
au-delà des seuils : remboursement > 50 €, commande déjà expédiée, litige d'authenticité.

### VII. Code en anglais, communications en français

Tous les identifiants, commentaires dans le code, noms de fichiers et messages de commit DOIVENT être
en anglais. Les échanges avec l'utilisateur final et la documentation de conception DOIVENT être en
français.

### VIII. Posture pédagogique — remise en question et bonnes pratiques

Ce projet est un projet de formation individuel : l'utilisateur apprend en le construisant. Par
conséquent, l'assistant DOIT :

- Remettre en question tout choix technique ou de conception proposé par l'utilisateur s'il n'est
  pas pertinent, sous-optimal, ou s'écarte des pratiques usuelles — au lieu de l'exécuter sans recul.
- Préciser systématiquement, quand c'est utile à la décision, ce qui est fait communément dans
  l'industrie ou dans l'écosystème concerné (LangChain, RAG, mémoire d'agent, garde-fous, MLOps),
  avec une justification brève plutôt qu'une simple affirmation.
- Signaler explicitement quand une proposition de l'utilisateur diverge d'un pattern reconnu, en
  expliquant le compromis, plutôt que de la valider silencieusement.

Cette exigence prime sur la complaisance : un accord silencieux avec un choix inadapté nuit à
l'apprentissage visé et n'est pas considéré comme une aide de qualité.

## Stack & Tooling

- **Langage** : Python (géré via `uv`)
- **Framework agent** : LangChain
- **LLM** : Azure AI Foundry (Azure OpenAI ou modèles déployés sur Azure)
- **Intégration Continue** : GitHub Actions
- **Tests** : pytest
- **Stockage mémoire long terme** : à définir dans le dossier de conception (fichier JSON isolé par
  utilisateur, SQLite, ou autre — le choix DOIT satisfaire R3/R5)

Les dépendances DOIVENT être déclarées dans `pyproject.toml` et verrouillées via `uv.lock`.

## Workflow & Delivery

1. **Conception** : produire et faire valider `docs/` avant tout code.
2. **Développement par chantier** : Mémoire → Garde-fous → Évaluation & MLOps.
3. **Tests d'acceptance** : chaque chantier DOIT passer ses tests d'acceptance avant le suivant.
4. **CI** : `quality.yml` s'exécute à chaque push ; échec = livraison bloquée.
5. **Versionnage** : chaque version de l'agent (prompt + configs) est taggée ; la note correspondante
   est ajoutée à `mlops/report.md`. Un commit est suggéré après chaque modification de code.
6. **Travail individuel** : pas de revue de PR obligatoire, mais la CI reste bloquante.

## Governance

Cette constitution est la référence de gouvernance du projet Velmo 2.0. Elle prime sur tout choix
d'implémentation ad hoc. Toute exception DOIT être documentée dans le dossier de conception avec
justification explicite.

Procédure d'amendement : modifier ce fichier, incrémenter la version (MAJOR si principe retiré ou
redéfini, MINOR si ajout, PATCH si clarification), et mettre à jour le Sync Impact Report en entête.

**Périmètre** : la feature "FAQ" est explicitement hors périmètre de ce projet — elle ne DOIT pas
être spécifiée, planifiée, ni implémentée sauf décision contraire actée dans un futur amendement.

**Version**: 1.1.0 | **Ratified**: TODO(RATIFICATION_DATE): à confirmer par le formateur | **Last Amended**: 2026-07-01
