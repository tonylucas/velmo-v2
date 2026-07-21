# Chantier 005d — Qualité RAG mesurée (RAGAS) — conception

> Statut : validé (brainstorming). Dernier des quatre sous-chantiers du volet
> Évaluation & MLOps. Expose les contextes récupérés en spans `retriever`, puis
> branche un évaluateur RAGAS natif Langfuse — configuré dans l'UI, pas en code.

## 1. Objectif et périmètre

005c a livré six des sept métriques du bloc « Monitoring » du schéma de séquence :
latence, coût par conversation, volume, taux de blocage par catégorie, taux
d'escalade, taux d'erreur technique outils. Il manque la septième — **la qualité
du RAG mémoire** : `faithfulness` (la réponse est-elle fidèle aux documents
récupérés, ou le modèle a-t-il inventé ?) et `answer_relevancy` (répond-elle
vraiment à la question posée ?).

005d comble ce trou. Le travail de code est plus étroit qu'il n'y paraît, pour
trois raisons établies en explorant :

1. **`search_kb` est déjà tracé.** Le `CallbackHandler` LangChain capture chaque
   appel d'outil avec son résultat complet ; les extraits FAQ sont donc déjà dans
   Langfuse quand le modèle les demande.
2. **RAGAS n'a de sens que sur les tours LLM.** Un tour déterministe répond par un
   gabarit (`routing._format_kb`) qui recopie ses sources par construction :
   mesurer sa « fidélité » ne dit rien.
3. **Seule la mémoire est réellement invisible.** `agent_graph.select_memory`
   récupère les faits, puis `render_facts` les aplatit en texte dans le prompt
   système. Le `Trace` local en note le `count` et les `keys`, jamais le contenu,
   et rien ne part vers Langfuse sous forme de champ exploitable.

**Un seul site d'appel est donc à instrumenter.**

Hors périmètre : retyper `search_kb` en `retriever` (gain cosmétique, plomberie
disproportionnée) ; le chronométrage isolé de la recherche sémantique ; un job
Python autour de la bibliothèque `ragas` (l'évaluateur natif rend la dépendance
inutile) ; les alertes sur dérive de score.

## 2. Pourquoi l'évaluateur natif plutôt qu'un job Python

Langfuse exécute des évaluateurs **LLM-as-a-judge côté serveur**, sur un
pourcentage échantillonné des traces de production, et attache le score à la
trace. Son catalogue contient des templates **maintenus par RAGAS**. La
fonctionnalité est incluse dans l'offre gratuite (Hobby : 50 k unités/mois,
30 jours de rétention, 2 utilisateurs).

Un job Python autour de `ragas` ferait la même chose en demandant un
ordonnanceur, une clé API, une dépendance lourde et son propre code de
reconstruction des triplets. À capacité égale, c'est du code à maintenir pour
rien.

**Conséquence structurante : le chantier n'ajoute aucune dépendance.** Ni `ragas`,
ni rien d'autre. Le code livré expose une donnée ; le scoring est de la
configuration.

## 3. Architecture

### 3a. Une méthode de plus sur `Turn`

```python
class Turn(Protocol):
    callbacks: list[Any]
    def record_retrieval(self, name: str, query: str, documents: list[str]) -> None: ...
    def end(self, *, answer: str, **metadata: Any) -> None: ...
```

- `NoOpTurn` : ne fait rien — le chemin hors-ligne reste inchangé et gratuit.
- `LangfuseTurn` : `client.start_observation(name=…, as_type="retriever",
  input=query, output=documents)` puis `.end()`.

L'observation s'accroche au **span courant**, que `LangfuseTurn.__init__` a déjà
ouvert (`start_as_current_observation`). Elle devient donc enfant de `handle-turn`
sans qu'on ait à gérer la parenté nous-mêmes.

`as_type="retriever"` n'est pas décoratif : les bonnes pratiques Langfuse veulent
qu'une récupération apparaisse comme telle dans l'arbre, et les évaluateurs
peuvent filtrer sur le type d'observation.

### 3b. `answer()` reçoit le tour, plus les callbacks

`agent_graph.answer` prend aujourd'hui `callbacks: list[Any] | None`. Elle prendra
`turn: Turn | None` et lira `turn.callbacks` elle-même — **un paramètre au lieu de
deux**, et la récupération mémoire devient traçable là où elle a lieu.

Un seul appelant en production (`agent.py:102`). Les tests qui appellent `answer`
directement ne passent pas ce paramètre et restent inchangés.

### 3c. Ce que le juge reçoit

Un document est `f"{fact.key} : {fact.content}"` — la ligne que `render_facts`
place dans le prompt système, **moins sa puce markdown** (`"- "`). La puce est de
la mise en forme de prompt, pas du contenu : la garder polluerait chaque contexte
d'un artefact que le juge devrait ignorer. Le contenu, lui, est identique au
caractère près, donc le juge évalue ce que le modèle a réellement vu.

Un seul document par fait, dans l'ordre où `select_memory` les renvoie
(sémantiques d'abord, puis épisodiques) — le même ordre que dans le prompt.

```
handle-turn
 ├─ retrieve-memory   (retriever)  input : le message · output : ["taille : fait du L", …]
 ├─ tool: search_kb   (tool)       ← déjà présent, inchangé
 └─ generation        (LLM)        output : la réponse
```

Mapping dans l'UI Langfuse : `question` ← input de la racine, `contexts` ← output
du `retriever`, `answer` ← output du `generation`.

**Un contexte vide est enregistré aussi**, et il ne faut pas le lire comme le
diagnostic d'une réponse hors-sujet : c'est l'état normal de tout utilisateur
qui n'a encore aucun fait stocké, y compris quand le tour est parfaitement
fondé sur la FAQ (`search_kb`, hors périmètre de ce span — §6). Enregistrer la
récupération même vide reste nécessaire pour que l'échantillonnage reste
cohérent ; c'est à l'évaluateur, pas à ce span, de traiter ce cas comme N/A
plutôt que de le noter (voir le runbook `infra/README.md`).

### 3d. Protection des données

Ces faits partaient **déjà** vers Langfuse : ils sont dans le prompt système, ce
que la spec 005c §4 documente explicitement. 005d n'expose aucune donnée nouvelle,
il structure la même. Le hook `mask_otel_spans` s'applique aux attributs de ce
span comme aux autres.

## 4. Stratégie de test

Le SDK Langfuse n'est jamais exercé hors-ligne (mêmes raisons qu'en 005c). On teste
le contrat :

1. `NoOpTurn.record_retrieval` est sans effet et un tour se déroule à l'identique.
2. Un `RecordingTracer` vérifie que `respond` enregistre **une** récupération par
   tour, sous le nom attendu, avec la question en `query`.
3. Les documents enregistrés correspondent, contenu pour contenu et dans le même
   ordre, aux lignes injectées dans le prompt — c'est le test qui garantit que le
   juge évalue le bon contexte. Il se vérifie en comparant à `render_facts`
   débarrassé de ses puces, pas en recopiant une chaîne attendue à la main.
4. Un tour sans aucun fait durable enregistre quand même la récupération, avec une
   liste vide.
5. La réponse de l'agent est identique avec et sans tracer (non-régression).

`LangfuseTurn.record_retrieval` reste non testé hors-ligne, au même titre que
`ChromaFactStore`, `AzureAIOpenAIApiChatModel` et le reste de `LangfuseTurn`.

## 5. Découpage en pile de PR

Conformément à `CLAUDE.md` : pile Graphite, chaque PR sous 400 lignes, une seule
préoccupation, ses propres tests, et une commande de vérification avec sa sortie
attendue dans la description.

| PR | Branche | Contenu | Taille |
|---|---|---|---|
| 1 | `ragas-eval/design` | cette spec + le plan d'implémentation | docs |
| 2 | `ragas-eval/record-retrieval` | `Turn.record_retrieval`, ses deux implémentations, ses tests | ~120 l. |
| 3 | `ragas-eval/memory-retriever-span` | `turn` dans `answer()`, span de récupération mémoire, tests | ~180 l. |
| 4 | `ragas-eval/evaluator-runbook` | runbook : configurer l'évaluateur RAGAS dans l'UI | docs |

PR 2 n'a aucun appelant : elle pose l'outil sans changer de comportement, donc elle
se relit isolément et ne peut rien casser. PR 3 porte les deux changements de
`agent_graph` ensemble parce que faire descendre le `turn` sans l'utiliser serait
du code mort.

## 6. Ce qui n'est délibérément PAS fait

- **Aucune nouvelle dépendance.** Pas de `ragas` : l'évaluateur natif la rend
  inutile, et le cœur reste installable sans rien de plus.
- **Le gate CI n'est pas touché.** Les scores RAGAS vivent sur les traces de
  production, jamais dans `mlops/report.md` : faire dépendre la note bloquante d'un
  juge LLM la rendrait non déterministe, l'inverse de ce que 005a garantit.
- **Pas d'alerte sur dérive de score.** Le dashboard Langfuse la montre ; la
  décision de rollback reste humaine, comme le prévoit le schéma du chantier 005.
- **Pas de retypage de `search_kb`.** Déjà capturé par le handler ; le retyper
  demanderait de faire descendre le tour jusque dans `build_tools` et `routing`.
