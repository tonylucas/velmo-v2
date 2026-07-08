# Chantier 001 — Agent LangGraph (design)

Statut : validé en brainstorming, prêt pour `writing-plans`.

## Contexte

Aujourd'hui, `Agent._handle()` (`src/velmo/agent.py`) fait un routage déterministe par
regex vers les outils métier (`O-\d{4}-\d{4}`, mots-clés « annul », « rembours », etc.),
et le seul cas non couvert retombe sur `self.llm.invoke(SYSTEM_PROMPT, "", message)` — un
simple echo/complétion sans tool-calling. Il n'y a pas de « vrai agent » : rien ne raisonne,
rien ne choisit un outil.

Le chantier 001 du roadmap (« Création agent ») n'avait pas de portée définie. Ce document
la fixe : construire un agent LangChain/LangGraph qui remplace ce comportement, tout en
préparant le terrain pour les chantiers suivants (mémoire, garde-fous, MLOps) sans les
implémenter ici.

## Non-objectifs (explicitement hors de ce chantier)

- `memory/` et `guardrails/` restent des stubs no-op. On ne les implémente pas ici.
- Pas de checkpointer LangGraph persistant. Le graphe est compilé sans `checkpointer`
  (paramètre `checkpointer=None`, avec un commentaire pointant vers le futur chantier
  mémoire qui en branchera un).
- Pas de flux de confirmation multi-tours robuste pour les outils de mutation via le
  nœud LLM (limite assumée, détaillée plus bas).

## Architecture

Tout l'agent Velmo devient **un seul `StateGraph` LangGraph**, avec deux nœuds :

```
StateGraph (= l'agent Velmo)
  entry
    └─▶ deterministic_node
          (même logique regex qu'aujourd'hui : order_id, "annul", "rembours", "taille",
           "retour", "dispo/stock", mots-clés FAQ ; appelle les outils métier directement,
           aucun appel LLM)
          │
          ├─ intention reconnue ──▶ END
          └─ aucune intention reconnue ──▶ llm_node
                                              (create_agent + tous les outils métier,
                                               vrai tool-calling ReAct)
                                              └─▶ END
```

Ce choix (un seul graphe plutôt que « routage Python + agent LLM accolé en fallback »)
est déterminant : il garantit que le futur checkpointer et les futurs nœuds de garde-fous
(chantiers suivants) s'appliqueront **uniformément** aux deux chemins, sans dupliquer
l'instrumentation. La logique de routage déterministe ne change pas ; elle change
d'emplacement (nœud de graphe au lieu de méthode Python isolée), avec un comportement
strictement identique — les tests d'acceptance existants qui exercent ce chemin
(`tests/acceptance/test_business.py`) ne doivent pas changer.

`Agent.respond()` (dans `agent.py`) reste l'enveloppe pipeline :

```
guardrails.check_input → memory.read → invoquer le graphe compilé → guardrails.check_output → memory.write
```

`Agent` perd `_handle()` et ses méthodes privées (`_confirm_or_act`, `_handle_stock`,
`_find_ref`, `_format_order`, `_format_tracking`, `_format_kb`) — elles déménagent dans le
nouveau module du graphe, sans changement de comportement.

## État du graphe

État minimal, centré sur les messages (compatible avec `create_agent`) :

```python
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    matched: bool  # True si deterministic_node a produit une réponse
```

`session`, `user_id`, `kb`, `chat_model` ne font **pas** partie de l'état : ils sont fixes
pour la durée d'une requête et fermés (closures) au moment de la construction du graphe,
exactement comme les outils (voir plus bas). Ça évite de les exposer au LLM ou de les
sérialiser inutilement.

`deterministic_node(state)` lit `state["messages"][-1].content`, applique la logique
regex existante, exécute l'outil correspondant si intention reconnue, et renvoie
`{"messages": [AIMessage(...)], "matched": True}` ou `{"matched": False}` sinon.

`route_after_deterministic(state) -> Literal["llm_node", END]` lit `state["matched"]`.

`llm_node(state)` invoque `create_agent(model=chat_model, tools=..., system_prompt=...)`
avec `state["messages"]` et renvoie les messages produits (y compris les éventuels
tool calls intermédiaires, utiles plus tard pour le checkpointer).

La réponse finale exposée à l'utilisateur est `result["messages"][-1].content`.

## Outils métier exposés au LLM — sécurité par fermeture

Les 10 outils (`get_order`, `track_shipment`, `check_stock`, `search_kb`,
`update_order_item`, `update_shipping_address`, `cancel_order`, `create_return`,
`trigger_refund`, `escalate_to_human`) sont donnés au `llm_node`. Leurs implémentations
actuelles (`tools/*.py`) prennent `session`/`user_id`/`kb` en paramètres positionnels : le
LLM ne doit **jamais** pouvoir choisir `user_id` (ce serait une brèche d'isolation).

`build_tools(session, user_id, kb)` construit donc des `@tool` LangChain qui ferment sur
`session`/`user_id`/`kb` et n'exposent au LLM que les paramètres métier qu'il doit
réellement choisir (`order_id`, `new_size`, `amount`, `reason`, `query`...). Ces wrappers
sont reconstruits à chaque requête (comme le graphe complet), jamais mis en cache au
niveau module.

Le filet de sécurité réel reste **les règles métier déjà présentes dans les outils**
(`owned_order`, `MODIFIABLE_STATUSES`, `REFUND_CAP`) — elles s'appliquent de la même façon
que l'appelant soit `deterministic_node` ou `llm_node`.

## Modèle de chat / mode hors-ligne

- `src/velmo/llm.py` gagne `get_chat_model() -> BaseChatModel` : `AzureAIOpenAIApiChatModel`
  si `AZURE_AI_INFERENCE_ENDPOINT` est configuré, sinon un nouveau `OfflineChatModel` —
  factice, **sans tool-calling**, qui renvoie un message texte simple (même esprit que
  l'`EchoLLM` actuel). Ça préserve `make chat` sans credentials.
- `EchoLLM` et le `LLM` Protocol (actuels) deviennent probablement morts une fois
  `Agent.__init__` migré vers `chat_model` — à vérifier/supprimer pendant le plan si plus
  rien ne les utilise.
- Pour les **tests**, on injecte directement un `FakeMessagesListChatModel`
  (`langchain_core`) dans `build_graph(..., chat_model=fake)` : séquence scriptée de
  réponses (avec `tool_calls`), pour tester déterministiquement l'enchaînement
  outil → observation → réponse sans dépendre d'un vrai LLM ni écrire notre propre fausse
  implémentation.

## Limite assumée : confirmation multi-tours côté LLM

Sans checkpointer, chaque invocation du graphe est un aller simple : pas d'historique
inter-tours mémorisé par le graphe lui-même. Le system prompt du `llm_node` demande
explicitement de toujours redemander confirmation avant un outil de mutation, mais un flux
de confirmation qui s'étale sur deux messages séparés du client ne sera fiable qu'une fois
la mémoire court terme (chantier 002/003) branchée comme contexte fourni au graphe (via
`memory.read(...).render()`, déjà appelé dans `Agent.respond()` mais actuellement ignoré —
on le branchera en entrée du graphe dès ce chantier, même si `MemoryManager` ne renvoie
encore rien d'utile, pour ne pas retoucher ce point d'intégration plus tard).

Le chemin déterministe garde sa logique de confirmation actuelle (mot-clé « je confirme »
dans le message courant), inchangée.

## Pourquoi `memory.write()` reste le point d'enregistrement, pas le checkpointer

Les faits durables à retenir en mémoire long terme (chantiers 002/003) prennent leur
source dans **les messages de l'utilisateur**, pas dans les événements internes du graphe.
`Agent.respond()` appelle déjà `memory.write(user_id, message, answer)` après l'exécution
du graphe, uniformément pour les deux chemins (déterministe ou LLM). C'est ce point qui
reste la source de vérité pour l'extraction de faits durables plus tard — le futur
checkpointer LangGraph, lui, ne servira que la mémoire de travail interne du `llm_node`
(raisonnement multi-étapes au sein d'une même requête), pas le magasin mémoire global de
Velmo.

## Fichiers touchés

- **Nouveau** `src/velmo/agent_graph.py` : `AgentState`, `deterministic_node`,
  `route_after_deterministic`, `build_tools`, `llm_node`, `build_graph(session, user_id,
  kb, chat_model=None)`, `answer(session, user_id, kb, message, context="",
  chat_model=None) -> str`. Contient aussi les helpers de formatage déménagés de
  `agent.py` (`_confirm_or_act`, `_handle_stock`, `_find_ref`, `_format_order`,
  `_format_tracking`, `_format_kb`).
- `src/velmo/llm.py` : ajoute `get_chat_model()` + `OfflineChatModel`. Nettoyage de
  `EchoLLM`/`LLM` Protocol si devenus morts.
- `src/velmo/agent.py` : `Agent` perd `_handle` et ses helpers ; `respond()` invoque
  `agent_graph.answer(...)`. `Agent.__init__` remplace `llm: LLM` par
  `chat_model: BaseChatModel | None = None`.
- `src/velmo/db.py`, `tools/*.py` : **inchangés**.
- `pyproject.toml` : aucune nouvelle dépendance (`langgraph` déjà tiré transitivement par
  `langchain` 1.3.11 dans l'extra `llm`).
- `tests/conftest.py` : adapté au nouveau constructeur `Agent` (pas un fichier de contrat,
  contrairement à `tests/acceptance/`).
- **Nouveau** `tests/test_agent_graph.py` : couvre le routage (le chemin déterministe
  n'invoque jamais le `chat_model`), le tool-calling LLM (cas lecture et cas action avec
  le fake scripté), et l'isolation toujours respectée via le chemin LLM.

## Critères de validation de ce chantier

- Tous les tests de `tests/acceptance/` passent sans modification de leur contenu
  (comportement du chemin déterministe strictement identique).
- `make chat` fonctionne sans credentials Azure (mode hors-ligne, `OfflineChatModel`).
- Un message hors du périmètre des regex déclenche bien le `llm_node` et obtient une
  réponse cohérente s'appuyant sur au moins un outil (vérifié par test avec le fake
  scripté).
- Aucune nouvelle dépendance ajoutée à `pyproject.toml`.
