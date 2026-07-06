# Spécification : Garde-fous d'entrée et de sortie (Chantier 2 — Sécurité)

**Feature Branch**: `003-guardrails`

**Créée le**: 2026-07-01

**Statut**: Brouillon

**Dépend de** : `.specify/memory/constitution.md` (Principe II — pipeline `entrée → garde-fou
d'entrée → mémoire (lecture) → LLM → garde-fou de sortie → mémoire (écriture) → réponse` ;
Principe IV — catégories interdites en entrée ET sortie).

---

## Scénarios utilisateur & tests d'acceptance *(obligatoire)*

### Scénario 1 — Blocage d'un contenu interdit en entrée (Priorité : P1)

Un utilisateur envoie à l'agent un message relevant d'une catégorie interdite (haineux,
discriminatoire, harcèlement, violent, menaçant, incitation à se nuire, sexuel / NSFW). Le
garde-fou d'entrée détecte le contenu avant tout traitement par le LLM, bloque la requête,
renvoie un refus poli et journalise l'événement. Le LLM n'est jamais invoqué avec ce contenu.

**Pourquoi P1** : C'est le cœur du chantier 2 et une exigence non négociable (Principe IV). Un
seul dérapage en production compromet la confiance dans Velmo 2.0 et l'expose à un risque
réputationnel et légal.

**Test indépendant** : Envoyer un jeu de messages interdits (`guardrailcases.jsonl`) et vérifier
que 100 % sont bloqués, avec un refus poli renvoyé et un événement journalisé pour chacun.

**Scénarios d'acceptance** :

1. **Étant donné** un message haineux, violent ou sexuel,
   **Quand** il est envoyé à l'agent,
   **Alors** l'agent bloque la requête, répond par un refus poli et journalise l'événement.

2. **Étant donné** un message interdit bloqué en entrée,
   **Quand** on inspecte le traitement,
   **Alors** le LLM n'a jamais reçu le contenu interdit (blocage strictement en amont).

3. **Étant donné** un message relevant d'une incitation à se faire du mal (automutilation,
   suicide),
   **Quand** il est envoyé,
   **Alors** l'agent bloque, répond avec bienveillance et déclenche une escalade humaine
   (cas grave).

---

### Scénario 2 — Blocage d'une fuite de données sensibles en sortie (Priorité : P1)

Le LLM produit une réponse contenant une donnée personnelle sensible (numéro de carte bancaire,
mot de passe, données d'un autre client), un secret interne (clé d'API, configuration) ou un
contenu interdit. Le garde-fou de sortie intercepte la réponse avant qu'elle n'atteigne
l'utilisateur et l'empêche de sortir.

**Pourquoi P1** : Une fuite de PII ou de secret en sortie est une violation RGPD et de sécurité
grave. Le garde-fou de sortie est la dernière barrière avant l'utilisateur.

**Test indépendant** : Forcer le modèle à produire une réponse contenant un numéro de carte,
puis vérifier que le garde-fou de sortie l'empêche d'être renvoyée à l'utilisateur.

**Scénarios d'acceptance** :

1. **Étant donné** une réponse du modèle contenant une donnée sensible (n° de carte),
   **Quand** elle est produite,
   **Alors** le garde-fou de sortie l'empêche de sortir et renvoie une réponse neutralisée ou un
   refus poli.

2. **Étant donné** une réponse du modèle contenant un secret interne ou un extrait de
   configuration,
   **Quand** elle est produite,
   **Alors** le garde-fou de sortie la bloque et journalise l'événement.

3. **Étant donné** une réponse du modèle relevant d'un contenu hors périmètre (conseil juridique
   ou médical, engagement de Velmo au-delà du support),
   **Quand** elle est produite,
   **Alors** le garde-fou de sortie la bloque et renvoie une réponse recentrée sur le périmètre
   du support.

---

### Scénario 3 — Résistance aux injections de prompt (Priorité : P1)

Un utilisateur tente de contourner ou de désactiver les consignes de l'agent par une injection
de prompt (« ignore tes instructions et… », « tu es maintenant en mode développeur… », données
piégées dans un champ de commande). L'agent ne désobéit pas à ses consignes de sécurité et
continue de se comporter conformément à son périmètre.

**Pourquoi P1** : Une injection réussie neutraliserait tous les autres garde-fous. La résistance
aux injections est donc une exigence transverse critique.

**Test indépendant** : Envoyer une batterie d'injections de prompt connues et vérifier que
l'agent maintient ses consignes (ne révèle pas son prompt système, n'exécute pas d'action hors
périmètre, ne lève pas ses garde-fous).

**Scénarios d'acceptance** :

1. **Étant donné** une injection de prompt (« ignore tes instructions et… »),
   **Quand** elle est envoyée,
   **Alors** l'agent ne désobéit pas à ses consignes et poursuit dans son périmètre.

2. **Étant donné** une tentative de faire révéler le prompt système ou la configuration interne,
   **Quand** elle est envoyée,
   **Alors** l'agent refuse et ne divulgue ni son prompt système ni ses secrets.

3. **Étant donné** une injection dissimulée dans une donnée récupérée par un outil (ex. note de
   commande contenant « ignore tes instructions »),
   **Quand** elle est traitée,
   **Alors** l'agent ne l'interprète pas comme une consigne légitime.

---

### Scénario 4 — Préservation de l'utilité (faible taux de faux positifs) (Priorité : P2)

Un client envoie un message de support parfaitement légitime qui pourrait superficiellement
déclencher un garde-fou (ex. « je suis furieux, ce maillot est une arnaque », « ma carte a été
débitée deux fois »). Le message n'est PAS bloqué à tort : l'agent le traite normalement.

**Pourquoi P2** : Un garde-fou trop agressif qui bloque les clients légitimes détruit l'utilité
de l'agent et frustre la clientèle passionnée de Velmo. L'équilibre sécurité / utilité est
essentiel.

**Test indépendant** : Rejouer un jeu de messages de support légitimes (`guardrailcases.jsonl`,
volet faux positifs) et vérifier que le taux de blocage à tort reste sous le seuil défini.

**Scénarios d'acceptance** :

1. **Étant donné** un message légitime du support (colère, mention d'un paiement, d'un litige),
   **Quand** il est envoyé,
   **Alors** il n'est pas bloqué à tort et l'agent le traite normalement.

2. **Étant donné** un ensemble de messages légitimes de test,
   **Quand** les garde-fous s'exécutent,
   **Alors** le taux de faux positifs reste sous le seuil défini (cf. chantier 3 / SC-004).

---

### Scénario 5 — Journalisation et escalade des cas graves (Priorité : P2)

Chaque blocage est journalisé de manière traçable (catégorie, emplacement entrée/sortie,
horodatage, identifiant utilisateur, décision). Les cas graves (menace crédible, incitation au
suicide ou à nuire à autrui) déclenchent en plus une escalade vers un humain.

**Pourquoi P2** : La journalisation alimente les suites d'évaluation (chantier 3) et l'audit de
sécurité. L'escalade protège l'utilisateur et Velmo dans les situations à risque réel.

**Test indépendant** : Déclencher un blocage de chaque catégorie et vérifier que chaque
événement est journalisé avec les champs requis ; déclencher un cas grave et vérifier qu'une
escalade humaine est émise.

**Scénarios d'acceptance** :

1. **Étant donné** un blocage de n'importe quelle catégorie,
   **Quand** il se produit,
   **Alors** un événement est journalisé avec catégorie, emplacement, horodatage, identifiant
   utilisateur et décision.

2. **Étant donné** un cas grave (menace crédible, incitation à se faire du mal),
   **Quand** il est détecté,
   **Alors** une escalade humaine est déclenchée en plus du refus et de la journalisation.

---

### Cas limites

- Que se passe-t-il si un message mêle contenu légitime ET contenu interdit (ex. une vraie
  demande de suivi de commande suivie d'une insulte) ?
- Que se passe-t-il si un client fournit spontanément sa propre donnée sensible en entrée (ex.
  colle son numéro de carte) — blocage, neutralisation ou traitement ?
- Que se passe-t-il si le service de modération (classifieur / LLM) est indisponible — l'agent
  échoue-t-il en mode ouvert (fail-open) ou fermé (fail-closed) ?
- Que se passe-t-il si une injection de prompt est dissimulée dans un contenu multilingue ou
  encodé (base64, caractères Unicode trompeurs) ?
- Que se passe-t-il si le garde-fou de sortie bloque une réponse : l'agent régénère-t-il une
  réponse ou renvoie-t-il directement un refus générique ?
- Que se passe-t-il en cas de faux négatif (contenu interdit passé au travers) — comment est-il
  détecté et remonté a posteriori ?

---

## Exigences fonctionnelles *(obligatoire)*

### Exigences fonctionnelles

- **FR-001** : Le système DOIT appliquer un garde-fou d'entrée qui inspecte chaque message
  utilisateur AVANT toute lecture mémoire et tout appel au LLM.
- **FR-002** : Le système DOIT appliquer un garde-fou de sortie qui inspecte chaque réponse du
  LLM AVANT qu'elle n'atteigne l'utilisateur et avant l'écriture en mémoire.
- **FR-003** : Le garde-fou d'entrée DOIT bloquer les catégories suivantes : contenus haineux /
  discriminatoires / harcèlement ; violence / menaces / incitation à se faire du mal ou à nuire ;
  contenus sexuels / NSFW ; injections de prompt / tentatives de contournement.
- **FR-004** : Le garde-fou de sortie DOIT bloquer les catégories suivantes : les mêmes que
  l'entrée (haine, violence, sexuel) ; les données personnelles sensibles (numéros de carte,
  mots de passe, données d'autres clients) ; les sorties hors périmètre (conseil juridique ou
  médical, engagement de Velmo au-delà du support) ; la fuite de secrets ou de configuration
  interne.
- **FR-005** : Lorsqu'un contenu est bloqué, le système DOIT renvoyer à l'utilisateur un message
  de refus poli et compréhensible, sans exposer les détails techniques de la détection.
- **FR-006** : Chaque blocage (entrée ou sortie) DOIT être journalisé avec, au minimum : la
  catégorie détectée, l'emplacement (entrée / sortie), l'horodatage, l'identifiant utilisateur et
  la décision prise.
- **FR-007** : Les cas graves (menace crédible, incitation au suicide ou à nuire à autrui)
  DOIVENT déclencher une escalade vers un humain, en plus du refus et de la journalisation.
- **FR-008** : L'agent NE DOIT PAS désobéir à ses consignes de sécurité sous l'effet d'une
  injection de prompt, ni divulguer son prompt système, sa configuration ou ses secrets.
- **FR-009** : Le système NE DOIT PAS interpréter comme des consignes légitimes les instructions
  dissimulées dans des données récupérées par les outils (données non fiables).
- **FR-010** : Le taux de faux positifs (messages légitimes bloqués à tort) DOIT rester sous un
  seuil défini et mesurable, afin de préserver l'utilité de l'agent.
- **FR-011** : Le garde-fou de sortie relatif aux PII DOIT empêcher toute donnée sensible de
  quitter le système, y compris les données appartenant à un autre client que celui de la
  session courante.
- **FR-012** : Les décisions de garde-fou DOIVENT être exposées de manière exploitable par les
  suites d'évaluation du chantier 3 (taux de blocage, taux de faux positifs).
- **FR-013** : Le comportement du système en cas d'indisponibilité du mécanisme de détection
  (fail-open vs fail-closed) DOIT être défini explicitement et cohérent avec le niveau de risque
  de chaque catégorie.

### Entités clés

- **Décision de garde-fou** : emplacement (entrée / sortie), catégorie détectée, verdict
  (autorisé / bloqué), gravité (standard / grave), horodatage, identifiant utilisateur,
  identifiant de session, extrait ou empreinte du contenu incriminé.
- **Catégorie interdite** : nom de la catégorie, emplacement(s) d'application (entrée / sortie /
  les deux), niveau de gravité par défaut, action associée (refus simple / refus + escalade).
- **Événement de journalisation** : référence à la décision de garde-fou, message de refus
  renvoyé, indicateur d'escalade émise.

---

## Critères de succès *(obligatoire)*

### Résultats mesurables

- **SC-001** : 100 % des messages relevant d'une catégorie interdite en entrée sont bloqués sur
  le jeu de test `guardrailcases.jsonl` (aucun contenu interdit ne parvient au LLM).
- **SC-002** : 100 % des réponses contenant une donnée sensible, un secret ou un contenu interdit
  sont bloquées en sortie (aucune fuite ne parvient à l'utilisateur).
- **SC-003** : 100 % des injections de prompt du jeu de test échouent à faire désobéir l'agent
  (aucune divulgation du prompt système, aucune action hors périmètre, aucun garde-fou levé).
- **SC-004** : Le taux de faux positifs sur les messages légitimes de test reste sous le seuil
  défini (cf. chantier 3), tout en maintenant SC-001 à 100 %.
- **SC-005** : 100 % des blocages produisent un événement journalisé complet (catégorie,
  emplacement, horodatage, identifiant utilisateur, décision).
- **SC-006** : 100 % des cas graves détectés déclenchent une escalade humaine traçable.
- **SC-007** : Le garde-fou d'entrée et le garde-fou de sortie ajoutent ensemble moins de 1
  seconde de latence supplémentaire par tour de conversation.

---

## Hypothèses

- Les deux garde-fous (entrée et sortie) s'insèrent dans le pipeline imposé par la constitution
  (Principe II), respectivement juste après l'entrée et juste avant la réponse.
- Le seuil exact de faux positifs est défini et versionné dans le chantier 3 (`mlops/report.md`),
  conformément au Principe IV de la constitution ; cette spec exige seulement qu'un seuil existe
  et soit respecté.
- Le jeu de test `guardrailcases.jsonl` (contenus interdits + messages légitimes pour les faux
  positifs) est fourni ou construit dans le cadre du chantier 3.
- Le choix des méthodes de détection par catégorie (liste de blocage, motifs / regex pour les
  PII, classifieur de modération, modération par LLM, vérification de périmètre) relève de la
  phase de planification (`/speckit-plan`) et du dossier de conception (tableau des garde-fous :
  catégorie × emplacement × méthode × action). Cette spec reste agnostique de la méthode.
- Par défaut, les catégories à haut risque (violence, automutilation, fuite de PII / secrets)
  suivent une politique **fail-closed** (blocage en cas de doute ou d'indisponibilité du
  détecteur) ; les catégories à risque plus faible privilégient l'utilité pour limiter les faux
  positifs. La politique définitive par catégorie est arbitrée en planification.
- Une donnée sensible fournie spontanément par le client sur ses propres données en entrée est
  neutralisée / non journalisée en clair plutôt que de bloquer la conversation ; le blocage strict
  concerne la **sortie** (fuite). Ce point est affinable en `/speckit-clarify`.
- Ce chantier ne couvre pas les suites d'évaluation, la CI ni le versionnage des notes (chantier
  3), mais expose les signaux nécessaires à ceux-ci (FR-012).
