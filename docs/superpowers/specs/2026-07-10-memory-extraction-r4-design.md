# Chantier 003b — Écriture mémoire : extraction automatique + R4

> Complète le pilier mémoire. Le 003 a livré le `FactStore` (R2/R3/R5/R6) mais un
> fait n'est écrit que si le LLM appelle explicitement `remember_fact`, et
> l'excédent au-delà de 30 messages n'est pas traité (R4). Ce chantier branche
> l'**écriture mémoire** du pipeline canonique : à chaque tour, on extrait les
> faits durables du message et on les écrit dans le `FactStore`.

## 1. Intention

Aujourd'hui la mémoire longue est **semi-manuelle** : le `DeterministicExtractor`
existe mais n'est appelé nulle part (code mort), et rien ne capte automatiquement
« tutoie-moi » ou une pointure au fil de la conversation. Ce chantier ajoute
l'étape **« mémoire (écriture) »** du pipeline du brief
(`… LLM → garde-fou de sortie → mémoire (écriture) → réponse`) et, ce faisant,
couvre **R4** (au-delà de 30 messages, ne rien perdre de critique).

## 2. Le mécanisme unifié — R4 et auto-extraction sont la même chose

À **chaque tour**, le message entrant passe dans un extracteur ; les faits
**éligibles** sont écrits dans le `FactStore`. Comme chaque message est extrait
**à son arrivée**, l'information durable est déjà persistée avant que le message
ne sorte de la fenêtre des 30 (soft window du 002).

- **R4 « sans perte »** est acquis par construction : rien n'attend l'overflow ;
  il n'y a pas de lot d'excédent à résumer séparément.
- **R2 automatique** : un fait dit dans une session courte (« tutoie-moi » au 3ᵉ
  message) est capté immédiatement, pas seulement si la conversation dépasse 30
  messages.
- L'excédent épisodique que R4 veut « persister en Chroma et repêcher
  sémantiquement » **est déjà** ce que fait le `FactStore` (les faits
  `order_info`/`dispute` = souvenirs épisodiques, en Chroma en prod, repêchés par
  tour via `select_memory`).

## 3. Extracteur — une interface, deux implémentations

Refactor du protocole existant pour qu'un extracteur soit un **singleton** réutilisé
à chaque tour (l'impl prod construit un `Runnable` LangMem coûteux, à ne pas
recréer par tour/user) :

```python
class Extractor(Protocol):
    def extract(self, user_id: str, messages: list[BaseMessage]) -> list[Fact]: ...
```

- **Hors-ligne — `DeterministicExtractor`** (existe ; devient sans état, `user_id`
  passé à `extract`). Épinglage d'entités par regex/mots-clés, sélectif par
  construction. **Ajout d'un motif « pointure/taille »** (« je chausse du L »,
  « je fais du XL » → `Fact(profile, "pointure", "L")`) pour rendre l'auto-capture
  R2 démontrable hors-ligne au-delà du seul « tutoie-moi ». Reste étroit.
- **Prod — `LangMemExtractor`** : enveloppe
  `create_memory_manager(get_chat_model(), schemas=[…], instructions=<contrat §4>)`
  (mode **stateless** de LangMem : storage-agnostic, l'appelant persiste). Mappe
  chaque `ExtractedMemory` → notre `Fact` → écrit via le `FactStore`. `langmem`
  est une **dépendance optionnelle** de l'extra `llm`, jamais requise hors-ligne.
- **`get_extractor() -> Extractor`** : renvoie `LangMemExtractor` si
  `AZURE_AI_INFERENCE_ENDPOINT` est défini **et** `langmem` importable, sinon
  `DeterministicExtractor`. Même patron que `get_chat_model()` / `get_kb()` /
  `get_fact_store()`.

## 4. Contrat d'éligibilité (sélectivité)

Règle explicite, respectée par **les deux** extracteurs :

> N'extraire que des faits **durables sur le client**, relevant des 4 `fact_type`
> (`preference`, `profile`, `order_info`, `dispute`). Ignorer l'éphémère, le
> bavardage et le hors-sujet.

- Hors-ligne : le `DeterministicExtractor` est sélectif par construction (il
  n'épingle que des motifs connus ; il ne *peut pas* produire de hors-sujet).
- Prod : le contrat est passé mot pour mot en `instructions` à
  `create_memory_manager`, plus le `schemas` pydantic qui borne les types.
- **Testable** : un message hors-sujet (« il fait beau aujourd'hui ») produit
  **zéro fait**.

## 5. Consolidation — FR-009 seule autorité

`FactStore.write` reste le seul maître de la consolidation (sémantique remplace
sur `(fact_type, key)` ; épisodique ajoute). LangMem ne fait qu'**extraire** ; on
mappe sa sortie en `Fact` et on écrit — pas de double autorité.

**Changement dans `fact_store.py`** : la clé de stockage épisodique passe d'un
`uuid4()` aléatoire à un **hash déterministe du contenu** :
`f"{user_id}:{fact_type}:{key}:{sha(content)}"`. Raison : l'extraction par tour
(§2) revoit forcément les mêmes n° de commande à plusieurs tours ; avec l'uuid on
créait un doublon à chaque fois. Avec le hash de contenu, ré-extraire le même
contenu est **idempotent** (même id → `upsert` écrase la même ligne), tandis que
deux contenus distincts restent deux entrées (FR-009 épisodique préservé).

## 6. Branchement — l'étape « mémoire (écriture) »

Dans `Agent.respond`, après avoir produit la réponse :

```
gate entrée → answer (lecture mémoire + réponse) → EXTRACTION+ÉCRITURE → gate sortie → réponse
```

- L'`Agent` reçoit un `extractor` (défaut `get_extractor()`), comme il reçoit déjà
  `store`.
- Après `answer`, on extrait depuis le **message user** du tour
  (`extractor.extract(user_id, [HumanMessage(message)])`) et on écrit chaque fait
  via `self.store.write(...)`.
- **Synchrone** : l'écriture est séquentielle dans le tour. L'async (non bloquant)
  est différé — non requis par le brief.

## 7. Stratégie de test (hors-ligne, déterministe)

- **Sélectivité** : « il fait beau » → l'extracteur renvoie `[]` ; rien n'est
  écrit.
- **Auto-capture end-to-end (R2 automatique)** : `agent.respond(user, "tu peux me
  tutoyer")` (aucun appel manuel à `remember_fact`) → une **nouvelle session**
  (même `store`) → `agent.inspect_memory(user)` contient `tutoiement`. Idem avec
  une pointure. Ceci **renforce le test d'acceptance #2** du brief (« le client
  revient, l'agent se souvient ») en prouvant la capture *automatique*.
- **R4 sans perte** : après 30+ messages dont un « tutoie-moi » au 1er tour, le
  fait est toujours dans `inspect_memory` (capté à l'arrivée, pas perdu par la
  fenêtre).
- **Dédup épisodique** : même n° de commande extrait à deux tours → **une** entrée
  `order_info` ; deux n° distincts → **deux** entrées.
- **`LangMemExtractor`** : seam de prod, **non exercé hors-ligne** (`langmem`
  absent en test), même statut que `ChromaFactStore`. Garanti par le contrat
  `Extractor` testé sur l'impl déterministe + revue statique.

## 8. Ce qui est différé (hors périmètre brief)

- **Async / non bloquant** : l'écriture reste synchrone.
- **Résumé LLM plus riche de l'excédent** (au-delà de l'extraction de faits) :
  possible via LangMem mais non requis ; le `FactStore` couvre le « sans perte ».
- **Mode stateful de LangMem** (`create_memory_store_manager` sur `BaseStore`) :
  écarté — conflit avec notre `FactStore`.
- **Test d'intégration Chroma** (fermer le seam prod) : durcissement, non requis.

## 9. Exigences couvertes

| Exigence | Avant 003b | Après 003b |
|---|---|---|
| R2 faits cross-session | ✅ mais écriture manuelle (`remember_fact`) | ✅ **automatique** (extraction par tour) |
| R4 sans perte >30 msg | ❌ | ✅ extraction à l'arrivée → rien ne sort non capté |
| « écriture sélective » (brief l.94) | ❌ | ✅ contrat d'éligibilité §4 |
| Pipeline « mémoire (écriture) » (brief l.78) | ❌ | ✅ §6 |

R1/R3/R5/R6 restent couverts par 002/003, inchangés. **À l'issue de 003b, le
pilier mémoire couvre R1–R6 + l'écriture sélective + l'étape d'écriture du
pipeline** ; le reste (async, résumé riche, test Chroma) est de l'optimisation
hors brief.

## 10. Points de vigilance

- **Ne pas dupliquer l'écriture.** Un fait sémantique ré-observé chaque tour
  (« tutoie-moi » répété) → FR-009 remplace, pas de doublon. Un fait épisodique
  ré-observé → dédup par hash de contenu (§5). Ces deux garde-fous doivent tenir.
- **Isolation R3 maintenue.** L'extraction produit des `Fact` fermés sur le
  `user_id` du tour ; l'écriture passe par le `FactStore` (dict par user offline /
  filtre `user_id` prod). L'extracteur ne choisit jamais un autre `user_id`.
- **Coût/latence (SC-007).** L'extraction ajoute un appel par tour ; hors-ligne
  c'est du regex instantané, en prod c'est un appel LLM — à surveiller, et la
  raison pour laquelle l'async est identifié comme suite possible.
- **Mapping `ExtractedMemory` → `Fact`.** Le seam prod doit convertir proprement
  (types, `key`, `source="extractor"`) ; non couvert hors-ligne, à relire
  statiquement.
- **Refactor du protocole `Extractor`.** `extract(messages)` →
  `extract(user_id, messages)` casse la signature actuelle et `tests/test_extract.py`
  (mis à jour dans ce chantier).
