# Feature Specification: API de conversation (chat avec l'agent Velmo)

**Feature Branch**: `004-api`

**Created**: 2026-07-02

**Status**: Draft

**Input**: User description: "faisons les specs de l'API. selon moi c'est une api classique qui
permet de communiquer avec un agent IA via un chat. faisons simple et suivons les bonnes pratiques."

**Dépend de** : `specs/001-short-term-memory` (fil de conversation, `Agent.respond`), et — une fois
livrées — `specs/002-long-term-memory` (RAG/RGPD) et `specs/003-guardrails` (garde-fous entrée/sortie).
L'API est une **couche transport** : elle expose le pipeline agent existant, sans réimplémenter la
mémoire ni les garde-fous.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dialoguer avec l'agent (Priority: P1)

Une application cliente (le frontend, feature 005, ou un simple client HTTP) envoie le message d'un
utilisateur à l'agent et reçoit sa réponse. La conversation se poursuit sur plusieurs tours : chaque
nouveau message tient compte des précédents de la même conversation.

**Why this priority** : C'est la raison d'être de l'API. Sans échange message → réponse, rien
d'autre n'a de valeur. C'est le MVP.

**Independent Test** : Envoyer un message dans une nouvelle conversation, vérifier qu'une réponse
cohérente est renvoyée ; envoyer un second message faisant référence au premier, vérifier que la
réponse tient compte du contexte antérieur.

**Acceptance Scenarios** :

1. **Étant donné** un utilisateur authentifié sans conversation en cours,
   **Quand** il envoie un premier message,
   **Alors** l'API crée une conversation, renvoie la réponse de l'agent et un identifiant de
   conversation réutilisable.

2. **Étant donné** une conversation existante avec un premier échange,
   **Quand** l'utilisateur envoie un message qui référence le précédent (« et en taille 42 ? »),
   **Alors** la réponse de l'agent tient compte du contexte de la conversation.

3. **Étant donné** un message vide ou mal formé,
   **Quand** il est envoyé,
   **Alors** l'API le rejette avec une erreur claire et structurée, sans planter.

---

### User Story 2 - Isolation et continuité des conversations (Priority: P1)

Chaque utilisateur retrouve ses propres conversations et ne voit jamais celles d'un autre. Reprendre
une conversation par son identifiant restitue le fil ; en démarrer une nouvelle repart d'un contexte
vierge.

**Why this priority** : Exigence de confidentialité (isolation R3, RGPD) directement héritée de la
mémoire. Une fuite inter-utilisateurs via l'API serait une faille grave. La continuité est la valeur
même d'un agent à mémoire.

**Independent Test** : Ouvrir une conversation pour U1, envoyer des messages ; avec U2, tenter
d'accéder à la conversation de U1 → refus ; démarrer une nouvelle conversation pour U2 → contexte
vierge.

**Acceptance Scenarios** :

1. **Étant donné** une conversation appartenant à l'utilisateur U1,
   **Quand** l'utilisateur U2 tente d'y envoyer un message ou de la lire,
   **Alors** l'API refuse l'accès sans révéler l'existence ni le contenu de la conversation.

2. **Étant donné** une conversation antérieure de l'utilisateur,
   **Quand** il la reprend via son identifiant,
   **Alors** l'agent répond en tenant compte de l'historique de cette conversation.

3. **Étant donné** un identifiant de conversation inconnu ou expiré,
   **Quand** l'utilisateur l'utilise,
   **Alors** l'API renvoie une erreur claire (conversation introuvable) sans divulguer d'autre
   information.

---

### User Story 3 - Supervision de l'état du service (Priority: P2)

Un opérateur (ou une sonde de monitoring / orchestrateur) interroge l'état de santé du service pour
savoir s'il est disponible et si ses dépendances (persistance) sont joignables.

**Why this priority** : Nécessaire à l'exploitation et au déploiement (readiness/liveness), mais ne
délivre pas de valeur directe à l'utilisateur final — d'où P2.

**Independent Test** : Interroger le point de santé quand tout va bien → état « sain » ; couper la
persistance → état « dégradé/indisponible ».

**Acceptance Scenarios** :

1. **Étant donné** un service opérationnel,
   **Quand** le point de santé est interrogé,
   **Alors** il répond « sain » rapidement.

2. **Étant donné** une dépendance critique injoignable (persistance),
   **Quand** le point de santé est interrogé,
   **Alors** il répond « indisponible » et l'information est exploitable par une sonde.

---

### Edge Cases

- Message vide, uniquement des espaces, ou dépassant une taille maximale raisonnable.
- Identifiant de conversation inconnu, expiré, ou appartenant à un autre utilisateur.
- Requête non authentifiée ou avec une identité invalide.
- Échec ou dépassement de délai de l'agent/LLM en amont : l'API doit renvoyer une erreur propre sans
  état corrompu (cohérent avec 001 FR-011 : le message utilisateur reste persisté, aucune réponse de
  substitution inventée).
- Message bloqué par les garde-fous (feature 003) : l'API relaie le refus poli produit par le
  pipeline, pas une erreur technique.
- Deux messages envoyés quasi simultanément dans la même conversation (ordonnancement / concurrence).
- Indisponibilité de la persistance au moment d'un échange.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** : L'API DOIT accepter un message utilisateur dans le contexte d'une conversation et
  renvoyer la réponse de l'agent en une seule réponse (non-streaming pour cette version).
- **FR-002** : L'API DOIT préserver la continuité conversationnelle : les messages d'une même
  conversation s'appuient sur les tours précédents (en s'appuyant sur la mémoire, features 001/002).
- **FR-003** : L'API DOIT permettre de démarrer une nouvelle conversation et d'en reprendre une
  existante au moyen d'un identifiant de conversation.
- **FR-004** : L'API DOIT authentifier l'appelant et en dériver une identité utilisateur de
  confiance ; toute requête non authentifiée DOIT être rejetée.
- **FR-005** : L'API DOIT isoler les conversations par utilisateur : un appelant ne peut accéder
  qu'à ses propres conversations et à leur historique (hérité de R3).
- **FR-006** : L'API DOIT valider les données entrantes et renvoyer des erreurs claires et
  structurées en cas de requête mal formée (message vide, identifiant manquant, format invalide).
- **FR-007** : Lorsqu'un message est bloqué par les garde-fous (feature 003), l'API DOIT relayer le
  refus poli produit par le pipeline avec un statut approprié, sans exposer de détail technique.
- **FR-008** : En cas d'échec ou de dépassement de délai de l'agent en amont, l'API DOIT renvoyer une
  erreur propre et n'inventer aucune réponse ; aucun état partiel ou corrompu ne DOIT subsister.
- **FR-009** : L'API NE DOIT jamais divulguer d'erreurs internes, de secrets ou de configuration au
  client ; les défaillances internes renvoient une erreur générique, l'erreur détaillée étant
  journalisée côté serveur avec un identifiant de corrélation.
- **FR-010** : L'API DOIT exposer un point de santé/disponibilité indiquant l'état du service et la
  joignabilité de ses dépendances critiques (persistance), exploitable par une sonde de monitoring.
- **FR-011** : L'API DOIT traiter chaque requête de manière indépendante (sans état conservé en
  mémoire entre requêtes), afin de servir plusieurs utilisateurs et conversations en parallèle sans
  interférence (cohérent avec le traitement stateless de 001, FR-010).
- **FR-012** : L'API DOIT journaliser chaque échange (identité, conversation, horodatage, issue :
  succès / bloqué / erreur) sans stocker de contenu sensible au-delà de ce que la mémoire conserve
  déjà, à des fins d'exploitation et d'évaluation ultérieure (feature 006).

### Key Entities *(include if feature involves data)*

- **Requête de conversation** : identité utilisateur (issue de l'authentification), identifiant de
  conversation (absent = nouvelle conversation), texte du message.
- **Réponse de conversation** : identifiant de conversation, texte de la réponse de l'agent,
  horodatage, indicateur d'issue (réponse normale / refus par garde-fou).
- **Conversation** : identifiant, utilisateur propriétaire, date de création, date de dernière
  activité. Adossée au fil de mémoire existant (thread `user_id:session_id` de 001) — l'API n'invente
  pas un stockage parallèle.
- **État de santé** : état global (sain / dégradé / indisponible), état par dépendance critique.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001** : Un utilisateur peut envoyer un message et recevoir une réponse cohérente qui tient
  compte des tours précédents dans au moins 95 % des conversations multi-tours de test.
- **SC-002** : 0 fuite inter-utilisateurs — aucun appelant ne peut lire ou influencer la conversation
  d'un autre utilisateur, vérifié sur l'ensemble des cas de test d'isolation.
- **SC-003** : 100 % des requêtes mal formées reçoivent une erreur claire et structurée (jamais un
  plantage ni une réponse incohérente).
- **SC-004** : Le surcoût introduit par l'API au-delà du temps de traitement de l'agent reste
  imperceptible pour l'utilisateur (moins de 200 ms ajoutés par échange, hors temps de l'agent).
- **SC-005** : Le point de santé reflète une panne de dépendance critique en moins de 5 secondes
  (passe à « indisponible » quand la persistance est coupée).
- **SC-006** : Le service traite au moins 50 conversations simultanées de test sans erreur ni
  mélange de contextes entre utilisateurs.
- **SC-007** : Aucune réponse de l'API ne contient d'information technique interne, de secret ou de
  trace d'erreur brute, vérifié sur l'ensemble des cas d'erreur de test.

---

## Assumptions

- **Authentification** : l'appelant présente une identité vérifiable (jeton/porteur ou clé d'API)
  qui se résout en un `user_id` stable et de confiance. L'intégration d'un fournisseur d'identité
  complet (SSO/OAuth d'entreprise) est **hors périmètre** de cette feature ; un mécanisme simple mais
  correct suffit. La profondeur exacte de l'authentification est un point à préciser
  (`/speckit-clarify`).
- **Identifiant de conversation** : généré par le service au démarrage d'une nouvelle conversation et
  renvoyé au client, qui le fournit pour poursuivre. Il correspond au fil de mémoire de 001
  (`session_id` d'un `user_id`).
- **Réponse unique (non-streaming)** pour cette version ; la diffusion incrémentale (streaming) est
  une amélioration possible ultérieure, hors périmètre ici (« faisons simple »).
- **Rôle de transport** : l'API est un adaptateur au-dessus du pipeline agent existant (`Agent.respond`) ;
  elle ne réimplémente ni la mémoire (001/002) ni les garde-fous (003), qui restent la source de
  vérité de ces comportements.
- **RGPD (droit à l'oubli / inspection)** : exposé via la conversation (outils de l'agent, 002), pas
  via des points d'API dédiés dans cette feature.
- **Frontend** : interface utilisateur traitée séparément (feature 005) ; cette feature ne couvre que
  l'API.
- **Persistance** : réutilise l'infrastructure existante (PostgreSQL pour 001, ChromaDB pour 002) ;
  l'API n'introduit pas de nouveau magasin de données.
