# Chantier 005c — Observabilité prod (Langfuse) — conception

> Statut : validé (brainstorming). Troisième des quatre sous-chantiers du volet
> Évaluation & MLOps. Un module `observability.py` sur le patron `get_kb()` /
> `get_chat_model()` : backend Langfuse si les clés sont présentes, no-op sinon.

## 1. Objectif et périmètre

Le gate d'éval (005a) mesure la qualité **avant** livraison, sur des cas figés et
hors-ligne. Il ne dit rien du comportement **en production** : combien coûte une
conversation réelle, quelle latence voient les clients, quelles catégories de
garde-fous se déclenchent, combien de tours finissent en escalade humaine.

005c branche **Langfuse** sur l'agent en prod pour couvrir la partie « Monitoring »
du schéma de séquence du chantier 005 : latence p50/p95/p99, coût par conversation,
taux de blocage par catégorie, taux d'escalade, taux d'erreur outils, volume.

Hors périmètre : RAGAS et le job d'échantillonnage périodique (→ 005d) ; les alertes
et la décision de rollback (manuelles, depuis le dashboard) ; l'export du journal de
conformité `GuardrailEngine.events` (reste **local**, cf. §4).

## 2. Architecture

### 2a. Un seul module nouveau — `src/velmo/observability.py`

Le dépôt a déjà un patron pour « backend réel si l'env le permet, sinon substitut
hors-ligne » : `get_kb()`, `get_chat_model()`, `get_fact_store()`, `get_checkpointer()`,
`get_extractor()`. `get_tracer()` le suit à l'identique.

```python
def get_tracer() -> Tracer:
    """LangfuseTracer si LANGFUSE_PUBLIC_KEY et LANGFUSE_SECRET_KEY sont définies
    et que `langfuse` est importable ; NoOpTracer sinon."""
```

Conséquence structurante : **sans clés, rien ne change.** Toute la suite de tests
tourne sur le `NoOpTracer`, aucun test existant n'est modifié, aucune dépendance
réseau n'apparaît en CI. L'import de `langfuse` est **différé** dans la branche
prod (comme `langchain-azure-ai` dans `llm.py`).

### 2b. Surface publique

Deux protocoles, volontairement minimaux :

```python
class Turn(Protocol):
    callbacks: list[Any]     # handlers à passer au graphe (vide en no-op)
    def end(self, *, answer: str, **metadata: Any) -> None: ...

class Tracer(Protocol):
    def start_turn(self, user_id: str, message: str) -> Turn: ...
```

`NoOpTurn.callbacks` est une liste vide et `end()` ne fait rien : le chemin
hors-ligne ne coûte que deux appels de méthode par tour.

### 2c. Branchement dans `Agent.respond`

Un seul point d'insertion, autour du pipeline existant :

```
respond(user_id, message)
  ├─ turn = tracer.start_turn(user_id, safe_message)   ← après check_input
  ├─ agent_graph.answer(..., callbacks=turn.callbacks) ← le handler capture le LLM
  └─ turn.end(answer=..., **metadata)                  ← après check_output
```

`agent_graph.answer` gagne un paramètre `callbacks: list | None = None`, injecté
dans le `config` passé à `graph.invoke`. Attention au cas existant : `config` vaut
`None` quand il n'y a pas de checkpointer — il faut construire le dict dans les deux
cas dès qu'il y a des callbacks.

### 2d. Réutilisation de la `Trace` existante

`src/velmo/trace.py` enregistre déjà, par tour, quels détecteurs ont tiré et quels
nœuds ont été traversés. `Agent.respond` crée donc une `Trace` interne quand le
tracer est actif et qu'aucune n'a été fournie par l'appelant (la démo Streamlit en
passe déjà une, elle est alors réutilisée telle quelle). **Aucun des 10 outils
métier n'est modifié.**

> **Correction apportée à l'écriture du plan.** Une version antérieure de cette
> section affirmait que la `Trace` enregistrait déjà les outils « avec leur
> `outcome` ». Vérification faite sur le code : c'est faux. `agent_graph.py`
> écrit systématiquement `outcome="called"` sans jamais lire le résultat, et le
> chemin **déterministe** — qui traite la majorité des tours — n'enregistre
> **aucun** pas `stage="tool"` : l'escalade se décide dans `routing._confirm_or_act`,
> qui ne reçoit pas de trace. L'escalade et les erreurs d'outils étaient donc
> inobservables.
>
> Le chantier ajoute donc une étape préalable : faire enregistrer le **verdict**
> de l'outil — `escalate`, `error` (échec technique), `not_found_or_forbidden`
> (refus d'isolation : la commande n'appartient pas à l'appelant), ou le verbe
> d'action du tool. Ce sont deux choses différentes et elles ne doivent pas se
> confondre : un client qui se trompe de numéro de commande ne doit pas gonfler
> le « taux d'erreur technique outils ».
>
> Deux chemins, deux portées. Sur le chemin **déterministe**, seules les
> opérations **modifiantes** sont instrumentées (`_confirm_or_act`, 5 sites
> d'appel) ; les consultations restent hors traçage. Sur le chemin **LLM**, tous
> les appels sont enregistrés, lectures comprises, parce qu'ils sont relus depuis
> les `ToolMessage` — c'est aussi ce qui rend l'arbre d'exécution lisible dans
> Langfuse. L'asymétrie est sans effet sur les métriques : `escalated` est un
> booléen par tour (une lecture de plus ne le dilue pas) et `tool_errors` ne
> compte que `error`.

## 3. Ce qui est capturé, et par quoi

| Métrique (schéma 005) | Source | Mécanisme |
|---|---|---|
| Latence p50/p95/p99 | automatique | durée du span racine |
| Coût par conversation | automatique | `CallbackHandler` lit l'usage de tokens du modèle |
| Volume conversations / tours | automatique | `session_id = user_id` regroupe les tours |
| Taux de blocage par catégorie | `Decision.category` | metadata `guardrail_in` / `guardrail_out` |
| Taux d'escalade humaine | `Trace` | pas `stage="tool"` d'`outcome` escalade (cf. §2d) |
| Taux d'erreur technique outils | `Trace` | pas `stage="tool"` en erreur (cf. §2d) |

Le coût n'est disponible **que** via le `CallbackHandler` LangChain : lui seul voit
l'usage de tokens remonté par le modèle. C'est la raison du choix « handler + nos
signaux » plutôt que « nos signaux seuls ».

### 3a. Métadonnées attachées au tour

- `session_id = user_id` — regroupe les tours d'un client en une conversation, ce qui
  donne le « coût par conversation » du schéma.
- `user_id` — permet de filtrer par client (et de purger sur demande, R5).
- Metadata : `guardrail_in` (action + catégorie), `guardrail_out` (action + catégorie),
  `escalated` (bool), `tool_errors` (int), `facts_written` (int), `version`
  (`mlops.current_version()`, pour corréler une dérive avec une version livrée).

## 4. Protection des données — décision structurante

Langfuse Cloud est un service **externe**. Envoyer le message client brut violerait
les exigences PII du brief.

**Ce qui atteint le span racine : `safe_message` en `input`, la réponse finale en
`output`** — le message *après* masquage PII par `check_input`. Mais ceci ne décrit
que la racine du tour, pas ce qui part réellement sur Langfuse Cloud : `turn.callbacks`
(le `CallbackHandler` LangChain) est transmis à `graph.invoke`, et LangChain
instrumente **tous les runs imbriqués** du graphe, pas seulement la racine. Concrètement,
part aussi sur Langfuse :

- l'historique de conversation restauré par le checkpointer, jusqu'à 30 messages
  (`agent_graph.window_messages`) ;
- **dès qu'un tour atteint le nœud LLM** — un tour traité en déterministe n'appelle
  aucun modèle et n'en produit rien : le prompt système envoyé au modèle, **avec les
  faits mémoire injectés** pour ce client (`agent_graph.select_memory` /
  `memory.facts.render_facts`), et le contenu des `ToolMessage` — en particulier
  `order_to_dict` (`tools/_common.py`) renvoie `shipping_address` en clair pour tout
  appel outil qui lit ou modifie une commande ;
- la réponse finale elle-même, qui peut légitimement contenir l'**email du client** :
  le garde-fou de sortie (`foreign_email`) ne bloque que les emails qui ne sont **pas**
  celui du client identifié — le sien, lui, passe, puisque c'est le comportement voulu
  côté client.

Activer les clés Langfuse revient donc à envoyer, vers un service externe, l'historique
de conversation, le contexte mémoire du client et le contenu structuré des appels
d'outils — pas seulement le message masqué de ce tour. C'est le prix de « voir le coût
et la latence par tour » avec le SDK v4 : la structure en spans imbriqués qui rend ces
métriques automatiques est la même qui exporte tout ce que le modèle a vu.

**Ce qui est masqué avant export : uniquement les numéros de carte (Luhn valide) et les
IBAN**, via `guardrails.detectors.scan_secrets` — la même détection que le garde-fou
d'entrée, réutilisée telle quelle (cf. §4a). Une adresse postale, un email ou un fait
mémoire stocké (`remember_fact`) traversent ce masquage **sans y être détectés** : ce
n'est pas un oubli à corriger dans ce chantier, c'est la portée assumée de
`scan_secrets`. Poser les clés `LANGFUSE_*` en prod, c'est donc consentir à ce que ces
données atteignent Langfuse Cloud non masquées — « masquage des secrets bancaires » et
« anonymisation de la conversation » sont deux choses différentes, et ce chantier ne
livre que la première.

**Ce qui n'est jamais envoyé :**
- le message brut, avant masquage par `check_input` — seule sa version *après* masquage
  atteint le span racine ; le secret détecté (carte/IBAN) ne quitte jamais le processus
  sous sa forme brute ;
- `GuardrailEngine.events`, qui reste le **journal de conformité local** — seules des
  métadonnées agrégées (action, catégorie) partent sur la trace ;
- un message dont `check_input` a refusé le passage : `start_turn` est appelé **après**
  le garde-fou d'entrée, avec le littéral `"[blocked input]"` et non le message — donc
  un tour bloqué n'envoie aucun contenu. Le blocage lui-même est compté via un événement
  sans texte, pour que le taux de blocage reste mesurable ;
- quoi que ce soit lié au gate d'éval en CI : `velmo.mlops.score` (sans `--prod`)
  construit l'agent avec `tracer=NoOpTracer()` **explicitement**, pas via l'absence de
  clés dans l'environnement — le gate reste hors-ligne même si `LANGFUSE_*` est présent
  sur la machine qui l'exécute (cf. §6).

### 4a. Le trou que le masquage amont ne bouche pas

Masquer l'entrée ne suffit pas. Le `CallbackHandler` capture la **sortie brute du LLM**
au moment de la génération ; `check_output` ne rejette une fuite de secret (carte, IBAN)
qu'**après coup**, quand le contenu est déjà posé sur le span — et ne couvre de toute
façon ni les adresses, ni l'email du client, ni les faits mémoire, absents de son
périmètre de détection. Un numéro de carte halluciné ou recopié par le modèle partirait
donc chez Langfuse alors même que le client, lui, ne le verrait jamais.

Correctif : le client Langfuse est construit avec le hook **`mask_otel_spans`** (SDK v4),
qui s'exécute à l'export, après le handler, et couvre les attributs de spans issus des
instrumentations tierces — précisément ce que le hook `mask` hérité ne couvre pas. Il
réutilise `guardrails.detectors.scan_secrets` : une seule définition de « secret » pour
le produit et pour l'observabilité — avec la même portée étroite (cartes/IBAN) que
partout ailleurs dans le produit ; ce hook ne masque pas les adresses ou les emails,
pour la même raison que `check_input`/`check_output` ne les masquent pas.

Contrainte imposée par le SDK, vérifiée sur l'implémentation installée
(`langfuse/_client/span_exporter.py`, `langfuse/types.py`) : si `mask_otel_spans`
**lève**, Langfuse jette tout le lot d'export — rien n'est envoyé, le coût est de
l'observabilité perdue pour ce lot, jamais une fuite. S'il **renvoie `None`** au lieu de
lever, en revanche, le lot part **non masqué** : un `except Exception: return None`
transformerait donc la dernière porte en passoire, exactement dans le cas où elle est
censée servir. Le hook du produit laisse donc l'exception se propager plutôt que de
l'avaler ; il reste par ailleurs rapide et déterministe (il tourne sur le thread
d'export OpenTelemetry).

## 5. Configuration

Trois variables, toutes optionnelles (`.env.example`) :

```
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
```

Hébergement retenu : **Langfuse Cloud**, offre gratuite. Rien à provisionner, rien
qui dépende de l'abonnement Azure bridé (cf. 005b §3) — ce chantier n'est donc pas
bloqué par les accès manquants.

Dépendance : nouvel extra `obs = ["langfuse>=4,<5"]` dans `pyproject.toml`, ajouté
à l'extra `demo` pour que l'image de la démo l'embarque. Le cœur reste inchangé.

### 5a. API Langfuse (vérifiée sur 4.14.1)

Le SDK v4 est basé sur OpenTelemetry ; l'API diffère nettement de v2/v3 :

- `Langfuse(public_key=…, secret_key=…, host=…, mask_otel_spans=…)` — client ;
  `auth_check()` valide les clés.
- `from langfuse.langchain import CallbackHandler` — handler passé dans `config["callbacks"]`.
  Il résout son client via `get_client(public_key=…)` : le singleton que le constructeur
  `Langfuse(...)` enregistre. Le client qu'on construit est donc bien celui qu'il utilise,
  masquage compris — à condition de lui passer `public_key` explicitement.
- `client.start_as_current_observation(name=…, as_type="span", input=…)` — context manager.
- `propagate_attributes(user_id=…, session_id=…, version=…, tags=…)` — context manager
  qui attache les attributs à la trace courante.
- `client.update_current_span(output=…, metadata=…)` puis `client.flush()`. **Il n'existe
  pas d'`update_current_trace`** en v4 : les métadonnées connues seulement en fin de tour
  se posent sur le span racine.

### 5b. Bonnes pratiques Langfuse suivies

Vérifiées sur `langfuse.com/docs/observability/best-practices` :

- **Une trace par tour, une session par conversation** — c'est littéralement la structure
  que la doc prescrit pour un chatbot (« on ne sait pas d'avance quand une conversation
  se termine »). `session_id = user_id`.
- **Entrée/sortie de l'observation racine = le message client et la réponse** — la doc en
  fait le champ que lisent les relecteurs, les évaluateurs et les expériences. Pas de
  blob JSON.
- **Noms d'observation à l'impératif et sans valeur dynamique** : le span racine est
  `handle-turn`. La doc traite les noms « comme une API » — les renommer casse
  silencieusement dashboards et évaluateurs, et y glisser un identifiant fait exploser
  leur cardinalité.

## 6. Ce qui n'est délibérément PAS fait

- **Pas de requête Langfuse depuis la CI.** `cost=0.0` dans `mlops/report.md` reste
  exact : l'éval est hors-ligne et ne consomme aucun token **par construction** —
  `mlops.score.build_offline_agent` passe `tracer=NoOpTracer()` explicitement plutôt
  que de compter sur l'absence de `LANGFUSE_*` dans l'environnement d'exécution. Le
  coût réel est une métrique de dashboard, pas un terme de la note bloquante. Faire
  dépendre le gate d'un service externe le rendrait non déterministe — l'inverse de
  ce que 005a garantit.
- **Pas de projets Langfuse DEV/PROD séparés** tant qu'aucune prod n'est déployée
  (cf. 005b §3). Un jeu de variables d'env suffit ; la séparation se fera en changeant
  les clés, sans changer le code.
- **Pas de wrapper d'instrumentation sur chaque outil métier.** La `Trace` existante
  les couvre déjà (§2d).
- **Pas de scoring dans les traces** — c'est 005d (RAGAS).

## 7. Stratégie de test

Le tracer réel n'est pas testable hors-ligne (service externe, clés). On teste donc
le **contrat**, pas le SDK :

1. `get_tracer()` renvoie un `NoOpTracer` quand les variables d'env sont absentes.
2. `NoOpTurn.callbacks` est vide et `end()` est sans effet — un tour se déroule à
   l'identique, tracer actif ou non (test de non-régression sur `respond`).
3. Un `RecordingTracer` de test (implémentant le protocole, sans Langfuse) vérifie
   que `respond` appelle `start_turn` puis `end` avec les bonnes métadonnées :
   catégorie de blocage, escalade, erreurs outils, comptage des faits.
4. Le message passé à `start_turn` est le message **masqué**, jamais le brut
   (test de non-fuite PII — c'est le test le plus important du chantier).

Le seam `LangfuseTracer` lui-même reste non testé hors-ligne, au même titre que
`ChromaFactStore`, `AzureAIOpenAIApiChatModel` et `LangMemExtractor`.

## 8. Découpage prévisionnel

1. Verdict des outils dans la `Trace` (`routing._confirm_or_act` + `_trace_tool_calls`), cf. §2d.
2. `observability.py` : protocoles, `NoOpTracer`, `get_tracer()`, `LangfuseTracer`.
3. `callbacks` dans `agent_graph.answer` + branchement dans `Agent.respond` (+ `Trace` interne).
4. Extra `obs`, `.env.example`, `Dockerfile`, runbook de mise en route Langfuse.
