# Chantier 003 — Mémoire long terme (Store LangGraph)

> Suite du chantier 002 (mémoire court terme = checkpointer). Ici on construit la
> mémoire **long terme** : faits durables cross-session (R2), isolation stricte
> par utilisateur (R3-faits), droit à l'oubli RGPD (R5), inspection/traçabilité
> (R6). L'ingestion « sans perte » de l'excédent au-delà de 30 messages (R4) et
> l'extraction automatique par LLM (LangMem) sont **différées** à un incrément
> ultérieur (voir §7).

## 1. Intention

Un client de Velmo qui revient plusieurs jours plus tard ne doit rien réexpliquer :
l'agent se souvient de ses faits et préférences durables (pointure, statut pro,
« tutoie-moi », équipe préférée, litige en cours), les rappelle et adapte son
comportement — sans jamais laisser fuiter la mémoire d'un client vers un autre.
Il peut aussi, sur demande, **oublier** une information (effacement effectif et
vérifiable) et **montrer** ce qu'il a retenu.

## 2. Modèle mémoire — le Store, jumeau du checkpointer

Le chantier 002 a établi le principe : une **primitive LangGraph native**, avec un
backend local en RAM pour les tests hors-ligne et un vrai backend en prod, choisi
par variable d'environnement. La mémoire longue reprend exactement ce patron avec
la primitive sœur du checkpointer : le **Store** (`BaseStore`).

| | Court terme (002) | Long terme (003) |
|---|---|---|
| Primitive LangGraph | Checkpointer | **Store (`BaseStore`)** |
| Hors-ligne / tests | `InMemorySaver` | **`InMemoryStore`** |
| Prod | `PostgresSaver` | Store adossé à Chroma (embeddings e5) |
| Sélection | présence de `DB_URL` | présence de `CHROMA_URL` |
| Isolation | `thread_id = user_id` | **namespace `(user_id,)`** |

Conséquence directe : **R3 (isolation des faits) est acquise par construction.**
Toute lecture/écriture passe par le namespace `(user_id,)` ; un fait d'un
utilisateur est physiquement inatteignable depuis le namespace d'un autre, même
si les contenus sont textuellement identiques.

### 2.1 Sémantique vs épisodique — un seul Store, `fact_type` discriminant

Tous les faits vivent dans le même Store ; le champ `fact_type` distingue leur
nature et leur règle de conflit (FR-009) :

| `fact_type` | nature | R en conflit de même type |
|---|---|---|
| `preference`, `profile` | **sémantique** — trait unique et mutable (pointure, tutoiement, statut pro) | **remplace** : on garde le plus récent, l'ancien est écarté |
| `order_info`, `dispute` | **épisodique** — événement daté, potentiellement multiple (une commande, un litige) | **ajoute** : chaque entrée est conservée, jamais écrasée |

Justification : écraser un fait épisodique ferait perdre un historique légitime
(un client peut avoir plusieurs commandes ou litiges simultanés) — contraire à R6.
Un trait sémantique, lui, n'a qu'une valeur vraie à la fois : garder deux
pointures contradictoires injecterait du bruit dans le contexte du LLM.

### 2.2 Le modèle `Fact`

Un `Fact` porte : `user_id`, `fact_type`, `content` (texte lisible), `created_at`,
`updated_at`, `source` (`"tool"` en écriture directe / `"extractor"` en prod). La
clé de stockage dans le namespace est un identifiant stable ; pour un fait
sémantique la clé dérive de `fact_type` (une seule valeur → remplacement in
place), pour un fait épisodique la clé est unique par entrée (accumulation).

## 3. Architecture — modules et branchement

```
src/velmo/memory/
  checkpointer.py   (002, court terme — inchangé)
  store.py          get_store() : InMemoryStore hors-ligne / Chroma en prod   ← NEW
  facts.py          modèle Fact + écriture/recherche + règle FR-009           ← NEW
  extract.py        interface Extractor + impl déterministe hors-ligne        ← NEW
src/velmo/tools/
  memory_tools.py   remember_fact / forget_user_data / inspect_user_memory    ← NEW
```

- **`store.py`** — `get_store()` renvoie un `InMemoryStore` si `CHROMA_URL` est
  absent (ou `chromadb` non importable), sinon un Store adossé à Chroma avec la
  fonction d'embedding e5 déjà utilisée par `kb_store`. Interface exposée aux
  couches supérieures, indépendante du backend.
- **`facts.py`** — le modèle `Fact` (pydantic) et les opérations pures :
  `write_fact(store, fact)` (applique FR-009 selon `fact_type`),
  `search_facts(store, user_id, query, fact_types=None, k=5)`,
  `all_facts(store, user_id)`, `delete_facts(store, user_id, target=None)`.
- **`extract.py`** — une interface `Extractor.extract(messages) -> list[Fact]`.
  Impl **déterministe hors-ligne** : épinglage d'entités par regex/mots-clés
  (n° de commande `O-\d{4}-\d{4}`, taille, « tutoie-moi » → préférence,
  « client pro/revendeur » → profil). L'impl **LangMem/LLM** de prod est différée
  (§7) mais l'interface est posée maintenant pour ne pas la casser plus tard.
- **`memory_tools.py`** — les trois outils métier, fermés sur `store`/`user_id`
  (même discipline d'isolation que les outils commande, cf. `_common.owned_order`).

Branchement dans l'agent (parallèle à `session`/`kb`) :

- `Agent.__init__` reçoit un `store` (défaut `get_store()`), le passe au graphe.
- `agent_graph.answer` gagne une étape de **recherche par tour** : avant l'appel
  LLM, `search_facts(store, user_id, message)` remplit le paramètre `context`
  **déjà existant** (injecté dans le system prompt sous « Mémoire: »). R2 se
  branche donc sur une couture qui existe déjà, sans nouveau nœud.
- Les **intentions mémoire** sont routées dans le **nœud déterministe**
  (`velmo.routing`), comme les opérations de commande (voir §4).

## 4. Routage déterministe des intentions mémoire

`OfflineChatModel` ne sait pas appeler d'outils ; et FR-010 exige que la
confirmation d'un oubli soit produite par un **gabarit déterministe, jamais par
le LLM**. Les deux contraintes convergent : les intentions mémoire sont
reconnues par regex dans le nœud déterministe et appellent directement les outils.

- « oublie mon… », « supprime mes données/informations » → `forget_user_data`,
  précédé d'une **demande de confirmation par gabarit** ; l'effacement n'a lieu
  qu'après confirmation explicite (réutilise le mécanisme `_confirm_or_act`).
- « que sais-tu de moi », « quelles infos as-tu sur moi » → `inspect_user_memory`.

Double bénéfice : R5/R6 fonctionnent **à travers le vrai agent, hors-ligne et de
façon déterministe**, et FR-010 est satisfait par construction. La **recherche R2**,
elle, est une étape du graphe exécutée à chaque tour, indépendante du chemin
LLM/déterministe. En prod, les mêmes outils restent également exposés au nœud LLM.

## 5. Exigences couvertes

| Exigence | Couverte en 003 ? | Mécanisme |
|---|---|---|
| R2 — faits durables cross-session | ✅ | Store persistant + recherche par tour → `context` |
| R3 — isolation des faits | ✅ | namespace `(user_id,)` du Store |
| R4 — résumer/sélectionner sans perte au-delà de 30 msg | ❌ → incrément suivant | ingestion de l'excédent + Chroma épisodique |
| R5 — droit à l'oubli | ✅ | `forget_user_data` → `delete_facts`, confirmation gabarit |
| R6 — traçabilité/inspection | ✅ | `inspect_user_memory` → `all_facts` |

## 6. Stratégie de test

Principe hérité du 002 : piloter le **vrai agent**, asserter sur le **stocké /
injecté**, jamais sur la réponse de l'écho. Tout tourne sur `InMemoryStore`, sans
Docker, sans Chroma, déterministe.

### 6.1 Réécriture des 3 tests xfail (→ verts)

Les tests actuels (`tests/acceptance/test_memory.py`) appellent l'ancien
`MemoryManager` supprimé et sont marqués `xfail(strict=True)`. Ils sont réécrits
pour piloter l'agent :

- `test_cross_session_persistence` (R2) : un agent enregistre trois faits durables
  (via `remember_fact`) pour un utilisateur ; un **nouvel agent, même user, même
  Store** les retrouve — vérifié soit sur les faits injectés dans le `context`,
  soit sur le contenu du Store. Le retrait du marqueur `xfail` est délibéré.
- `test_isolation_between_customers` (R3) : faits distincts pour U1 et U2 ; la
  recherche/inspection de U2 ne contient **aucun** fait de U1 (namespaces
  disjoints), même contenus proches.
- `test_right_to_be_forgotten` (R5) : `remember_fact` → oubli déclenché via
  l'agent (message « oublie… » + confirmation) → le fait a **disparu** du Store et
  ne ressort plus sur les tours suivants.

### 6.2 Tests nouveaux

- `test_inspect_user_memory` (R6) : trois faits enregistrés → l'inspection les
  restitue tous les trois, aucun oubli, aucun fait supprimé inclus.
- **FR-009 sémantique** : deux `preference`/`profile` de même type → seule la plus
  récente subsiste.
- **FR-009 épisodique** : deux `order_info` distincts → les deux subsistent.
- **FR-010** : la demande d'oubli produit d'abord un message de confirmation
  **littéral et stable** (gabarit), et n'efface qu'après confirmation.
- **Isolation via recherche sémantique** : la recherche pour un user ne retourne
  que ses faits, même si un autre user a un fait textuellement très proche.

### 6.3 Le partage court/long terme reste intègre

Les tests existants du chantier 002 (`test_recall_over_30_messages`, isolation
court terme) doivent rester verts : la mémoire longue s'ajoute **à côté** du
checkpointer, elle ne le modifie pas.

## 7. Ce qui est explicitement différé (incrément suivant)

- **R4 « résumer / sélectionner sans perte »** : au-delà de 30 messages, persister
  l'excédent comme souvenir épisodique dans Chroma puis le re-sélectionner
  sémantiquement. C'est la partie la plus lourde et la moins testable hors-ligne ;
  la découpler garde 003 net et livrable.
- **Extraction automatique par LangMem (LLM)** : l'implémentation prod de
  l'interface `Extractor`, qui lit la conversation et en extrait/résume les faits.
  L'interface et l'impl déterministe hors-ligne sont posées en 003 ; l'impl LLM et
  la dépendance `langmem` (extra optionnel) sont ajoutées ensuite.
- **Ingestion asynchrone / non bloquante** : 003 est synchrone (YAGNI).
  L'interface laisse la couture pour un hook background ultérieur.

## 8. Points de vigilance

- **Fournir le Store à l'agent partout.** `Agent` reçoit un `store` comme il reçoit
  `session`/`kb`. `build_default_agent` appelle `get_store()` ; `conftest` passe un
  `InMemoryStore` neuf par test (isolation entre tests, comme `fresh_sqlite_session`).
- **Latence de la recherche par tour (SC-007).** La recherche R2 s'exécute à chaque
  tour ; hors-ligne elle est lexicale et instantanée, en prod elle doit rester
  sous ~500 ms. Le filtre `fact_type` optionnel sert à réduire le bruit (ex.
  exclure les litiges résolus), pas à contourner la latence.
- **Effacement vérifiable (R5).** `forget_user_data` doit non seulement supprimer
  mais permettre de **vérifier l'absence** ; l'oubli global (tout le namespace)
  est distinct de l'oubli ciblé.
- **Oubli d'une donnée inexistante.** Une demande d'oubli sans cible correspondante
  ne doit pas échouer bruyamment : message neutre, aucun effet de bord.
- **Cycle de vie du backend Chroma en prod.** Comme pour le `PostgresSaver` du 002,
  la connexion/collection Chroma du Store doit être gérée proprement (création
  paresseuse, réutilisation). Non exercé hors-ligne.
