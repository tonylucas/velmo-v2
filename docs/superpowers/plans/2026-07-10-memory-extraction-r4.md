# Écriture mémoire : extraction automatique + R4 (chantier 003b) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Brancher l'étape « mémoire (écriture) » du pipeline : à chaque tour, extraire les faits durables du message et les écrire dans le `FactStore` (couvre R4 et rend R2 automatique).

**Architecture:** Un extracteur derrière une interface (`Extractor.extract(user_id, messages)`), avec l'impl déterministe hors-ligne (existante, enrichie) et l'impl prod `LangMemExtractor` (LangMem stateless sur Kimi, seam non testé offline), sélectionnés par `get_extractor()`. L'`Agent` appelle l'extracteur après chaque réponse et écrit via le `FactStore`, dont la consolidation (FR-009) reste l'autorité unique ; la clé épisodique devient dérivée du contenu pour dédupliquer les ré-extractions.

**Tech Stack:** Python 3.11, `uv`, pydantic v2, pytest. `langmem` = dépendance optionnelle de l'extra `llm` (prod seulement). Pas de dépendance nouvelle en test.

## Global Constraints

- Gestionnaire de paquets : `uv` (`uv run pytest …`). Pas de mypy — vérification **pytest uniquement**. Code **ruff-clean** (imports en tête).
- Tout le code (identifiants, docstrings, commentaires, commits) en **anglais**. Seuls les textes produits pour le client final restent en français.
- **Extraction par tour** : chaque message user → `extractor.extract(user_id, [HumanMessage(message)])` → `store.write(fact)`. Synchrone (async différé).
- **Contrat d'éligibilité** (respecté par les deux extracteurs) : n'extraire que des faits **durables sur le client**, des 4 `fact_type` (`preference`, `profile`, `order_info`, `dispute`) ; ignorer l'éphémère/hors-sujet. Un message hors-sujet → **0 fait**.
- **Consolidation = FR-009** dans `FactStore.write` (sémantique remplace sur `(fact_type, key)`, épisodique ajoute). Autorité unique ; LangMem n'extrait pas de logique de consolidation.
- **Clé épisodique = hash du contenu** (`f"{user_id}:{fact_type}:{key}:{sha256(content)[:16]}"`) → ré-extraire le même contenu est idempotent ; deux contenus distincts coexistent.
- **`Extractor.extract(user_id, messages)`** (refactor de l'actuel `extract(messages)` ; `DeterministicExtractor` devient sans état).
- **`LangMemExtractor`** = seam de prod (comme `ChromaFactStore`) : **non exercé hors-ligne** (`langmem` absent en test). Sélection via `get_extractor()` : LangMem si `AZURE_AI_INFERENCE_ENDPOINT` défini **et** `langmem` importable, sinon `DeterministicExtractor`.
- Isolation R3 : l'extracteur produit des `Fact` fermés sur le `user_id` du tour ; jamais un autre `user_id`.

---

### Task 1: Clé épisodique dérivée du contenu (`memory/fact_store.py`)

**Files:**
- Modify: `src/velmo/memory/fact_store.py`
- Test: `tests/test_fact_store.py` (append)

**Interfaces:**
- Consumes: `velmo.memory.facts.Fact`.
- Produces: `episodic_storage_key(fact: Fact) -> str` (désormais déterministe, dérivé du contenu ; même signature).

- [ ] **Step 1: Write the failing tests**

Ajouter à la fin de `tests/test_fact_store.py` :

```python
from velmo.memory.fact_store import episodic_storage_key


def test_episodic_storage_key_is_content_derived():
    f1 = Fact.new("u1", "order_info", "order", "O-2024-0101")
    f2 = Fact.new("u1", "order_info", "order", "O-2024-0101")
    f3 = Fact.new("u1", "order_info", "order", "O-2024-0102")
    assert episodic_storage_key(f1) == episodic_storage_key(f2)
    assert episodic_storage_key(f1) != episodic_storage_key(f3)


def test_episodic_write_is_idempotent_on_same_content():
    store = LocalFactStore()
    store.write(Fact.new("u1", "order_info", "order", "O-2024-0101"))
    store.write(Fact.new("u1", "order_info", "order", "O-2024-0101"))
    orders = [f for f in store.all("u1") if f.fact_type == "order_info"]
    assert len(orders) == 1
```

> Note : `Fact` et `LocalFactStore` sont déjà importés en tête de `tests/test_fact_store.py` ; n'ajouter que l'import `episodic_storage_key` — **en haut du fichier** avec les autres imports, pas au milieu (ruff E402).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fact_store.py -q -k "content_derived or idempotent"`
Expected: FAIL (`test_episodic_write_is_idempotent_on_same_content` : 2 entrées au lieu de 1, car la clé uuid diffère à chaque écriture).

- [ ] **Step 3: Change the episodic key derivation**

Dans `src/velmo/memory/fact_store.py` :

Remplacer l'import `from uuid import uuid4` par `import hashlib` (uuid4 n'est plus utilisé ailleurs dans ce fichier).

Remplacer la fonction `episodic_storage_key` par :

```python
def episodic_storage_key(fact: Fact) -> str:
    """Content-derived id: re-extracting the same content is idempotent, while
    two distinct episodic contents coexist (FR-009 episodic append)."""
    digest = hashlib.sha256(fact.content.encode("utf-8")).hexdigest()[:16]
    return f"{fact.user_id}:{fact.fact_type}:{fact.key}:{digest}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fact_store.py -q`
Expected: PASS (existants + 2 nouveaux ; `test_episodic_facts_accumulate` reste vert car deux contenus distincts → deux hash).

- [ ] **Step 5: Commit**

```bash
git add src/velmo/memory/fact_store.py tests/test_fact_store.py
git commit -m "feat: derive episodic storage key from content for idempotent writes"
```

---

### Task 2: Extracteur déterministe — refactor interface + pointure + sélectivité (`memory/extract.py`)

**Files:**
- Modify: `src/velmo/memory/extract.py`
- Modify: `tests/test_extract.py` (rewrite for the new signature)

**Interfaces:**
- Consumes: `velmo.memory.facts.Fact`; `langchain_core.messages.BaseMessage`, `HumanMessage`.
- Produces:
  - `class Extractor(Protocol)` : `extract(self, user_id: str, messages: list[BaseMessage]) -> list[Fact]`.
  - `class DeterministicExtractor` : **sans argument de constructeur** ; `extract(user_id, messages)`.

- [ ] **Step 1: Rewrite the tests for the new signature (with pointure + selectivity)**

Remplacer **intégralement** `tests/test_extract.py` par :

```python
"""Unit tests for the deterministic offline fact extractor."""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from velmo.memory.extract import DeterministicExtractor


def _facts(text: str):
    return DeterministicExtractor().extract("u1", [HumanMessage(content=text)])


def test_extracts_order_number_as_episodic():
    facts = _facts("Ma commande O-2024-0101 n'est pas arrivée.")
    assert any(f.fact_type == "order_info" and f.content == "O-2024-0101" for f in facts)


def test_extracts_tutoiement_preference():
    facts = _facts("Tu peux me tutoyer, c'est plus simple.")
    prefs = [f for f in facts if f.fact_type == "preference" and f.key == "tutoiement"]
    assert prefs and prefs[0].content == "oui"


def test_extracts_pro_status_as_profile():
    facts = _facts("Je suis client pro / revendeur.")
    profiles = [f for f in facts if f.fact_type == "profile" and f.key == "segment"]
    assert profiles and "pro" in profiles[0].content.lower()


def test_extracts_pointure_as_profile():
    for text in ("Je chausse du L.", "Je fais du XL.", "Ma pointure est M."):
        facts = _facts(text)
        pointures = [f for f in facts if f.fact_type == "profile" and f.key == "pointure"]
        assert pointures, f"no pointure extracted from {text!r}"


def test_off_topic_message_extracts_nothing():
    # Selectivity contract: no durable fact -> empty.
    assert _facts("Il fait beau aujourd'hui, merci !") == []


def test_facts_are_bound_to_the_given_user():
    facts = _facts("Tu peux me tutoyer.")
    assert facts and all(f.user_id == "u1" for f in facts)


def test_source_is_extractor():
    facts = _facts("Ma commande O-2024-0101 est en retard.")
    assert facts and all(f.source == "extractor" for f in facts)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_extract.py -q`
Expected: FAIL (`DeterministicExtractor()` takes no user_id yet / `extract()` signature mismatch; `test_extracts_pointure_as_profile` fails — no pointure pattern).

- [ ] **Step 3: Refactor the extractor**

Remplacer **intégralement** `src/velmo/memory/extract.py` par :

```python
"""Fact extraction from conversation.

The ``Extractor`` protocol has two implementations behind it: this deterministic
one (regex/keyword entity pinning, offline, testable) and — in production — a
LangMem-backed one (see ``get_extractor``). Both honour the same eligibility
contract: only durable facts about the customer, across the four fact types;
off-topic or ephemeral content yields nothing.
"""

from __future__ import annotations

import re
from typing import Protocol

from langchain_core.messages import BaseMessage, HumanMessage

from .facts import Fact

_ORDER_RE = re.compile(r"O-\d{4}-\d{4}")
_SIZE_RE = re.compile(
    # First-person statements of one's own size — avoids matching stock questions
    # like "la taille L est-elle dispo ?" (no "je"/"ma" cue).
    r"\b(?:je\s+chausse|je\s+fais|je\s+taille|ma\s+pointure)\b[^.\n]*?\b(XXL|XL|XS|S|M|L)\b",
    re.IGNORECASE,
)
_TUTOIEMENT_HINTS = ("tutoie", "tutoyer")
_PRO_HINTS = ("client pro", "revendeur", "professionnel", "compte pro")


class Extractor(Protocol):
    def extract(self, user_id: str, messages: list[BaseMessage]) -> list[Fact]: ...


class DeterministicExtractor:
    """Offline entity-pinning extractor. Selective by construction: it only pins
    known patterns, so it cannot emit off-topic facts."""

    def extract(self, user_id: str, messages: list[BaseMessage]) -> list[Fact]:
        text = " ".join(str(m.content) for m in messages if isinstance(m, HumanMessage))
        low = text.lower()
        facts: list[Fact] = []

        for order_id in dict.fromkeys(_ORDER_RE.findall(text)):
            facts.append(Fact.new(user_id, "order_info", "order", order_id, source="extractor"))
        if any(h in low for h in _TUTOIEMENT_HINTS):
            facts.append(Fact.new(user_id, "preference", "tutoiement", "oui", source="extractor"))
        if any(h in low for h in _PRO_HINTS):
            facts.append(Fact.new(user_id, "profile", "segment", "client pro", source="extractor"))
        size = _SIZE_RE.search(text)
        if size:
            facts.append(
                Fact.new(user_id, "profile", "pointure", size.group(1).upper(), source="extractor")
            )
        return facts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_extract.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/velmo/memory/extract.py tests/test_extract.py
git commit -m "feat: extractor takes user_id, pins pointure, stays selective"
```

---

### Task 3: Extracteur de prod LangMem + fabrique `get_extractor` (`memory/extract.py`, `pyproject.toml`)

**Files:**
- Modify: `src/velmo/memory/extract.py`
- Modify: `pyproject.toml` (extra `llm`)
- Test: `tests/test_extract.py` (append)

**Interfaces:**
- Consumes: `velmo.memory.facts.Fact`, `FACT_TYPES`; `velmo.llm.get_chat_model` (prod branch only).
- Produces:
  - `class MemoryFact(BaseModel)` (schéma d'extraction LangMem : `fact_type`, `key`, `content`).
  - `class LangMemExtractor` (seam prod).
  - `get_extractor() -> Extractor`.
  - `ELIGIBILITY_INSTRUCTIONS: str` (contrat, passé à LangMem).

- [ ] **Step 1: Write the failing test**

Ajouter à la fin de `tests/test_extract.py` :

```python
from velmo.memory.extract import get_extractor


def test_get_extractor_offline_is_deterministic(monkeypatch):
    monkeypatch.delenv("AZURE_AI_INFERENCE_ENDPOINT", raising=False)
    assert isinstance(get_extractor(), DeterministicExtractor)
```

> Import `get_extractor` **en haut** du fichier avec les autres imports (ruff E402), pas au milieu.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_extract.py -q -k get_extractor`
Expected: FAIL (`cannot import name 'get_extractor'`).

- [ ] **Step 3: Add the prod extractor + factory**

Dans `src/velmo/memory/extract.py`, ajouter `import os` en tête (après `import re`), importer `FACT_TYPES` (`from .facts import FACT_TYPES, Fact`), `from pydantic import BaseModel`, et ajouter à la fin du module :

```python
ELIGIBILITY_INSTRUCTIONS = (
    "Extract only durable facts about the customer that fit one of these types: "
    "preference (e.g. wants to be addressed informally / 'tutoiement'), "
    "profile (e.g. shoe/jersey size 'pointure', pro-customer segment), "
    "order_info (an order number the customer refers to), "
    "dispute (an ongoing dispute the customer raises). "
    "Use a short 'key' (the attribute name, e.g. 'tutoiement', 'pointure', 'segment', 'order') "
    "and a concise 'content' value. Ignore small talk, ephemeral remarks and anything off-topic. "
    "If there is no durable fact, extract nothing."
)


class MemoryFact(BaseModel):
    """Schema LangMem extracts into (mapped to velmo Fact by LangMemExtractor)."""

    fact_type: str
    key: str
    content: str


class LangMemExtractor:
    """Production extractor: LangMem's stateless memory manager over the project
    LLM. Storage-agnostic — the manager only extracts; persistence and FR-009
    consolidation stay in FactStore.write. Not exercised offline (langmem absent);
    this is the prod seam, like ChromaFactStore."""

    def __init__(self, model) -> None:
        from langmem import create_memory_manager

        self._manager = create_memory_manager(
            model,
            schemas=[MemoryFact],
            instructions=ELIGIBILITY_INSTRUCTIONS,
            enable_inserts=True,
            enable_updates=True,
            enable_deletes=False,
        )

    def extract(self, user_id: str, messages: list[BaseMessage]) -> list[Fact]:
        extracted = self._manager.invoke({"messages": messages})
        facts: list[Fact] = []
        for item in extracted:
            memory = item.content
            if memory.fact_type in FACT_TYPES:
                facts.append(
                    Fact.new(
                        user_id, memory.fact_type, memory.key, memory.content, source="extractor"
                    )
                )
        return facts


def get_extractor() -> Extractor:
    """Return the LangMem extractor if the LLM and langmem are available, else the
    deterministic one. Mirrors get_chat_model() / get_fact_store()."""
    if os.getenv("AZURE_AI_INFERENCE_ENDPOINT"):
        try:
            import langmem  # noqa: F401
        except ImportError:
            return DeterministicExtractor()
        from ..llm import get_chat_model

        return LangMemExtractor(get_chat_model())
    return DeterministicExtractor()
```

- [ ] **Step 4: Add langmem to the optional `llm` extra**

Dans `pyproject.toml`, l'extra `llm` devient :

```toml
llm = [
    "langchain-azure-ai>=1.0,<2.0",
    "azure-ai-inference>=1.0.0b9",
    "langmem>=0.0.1",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_extract.py -q`
Expected: PASS (8 tests). `langmem` reste **non installé** ; le test hors-ligne n'atteint jamais la branche LangMem.

Run: `uv run ruff check src/velmo/memory/extract.py tests/test_extract.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/velmo/memory/extract.py tests/test_extract.py pyproject.toml
git commit -m "feat: add LangMem prod extractor and get_extractor factory"
```

---

### Task 4: Brancher l'écriture mémoire dans l'agent (`agent.py`)

**Files:**
- Modify: `src/velmo/agent.py`
- Test: `tests/test_agent.py` (append)

**Interfaces:**
- Consumes: `velmo.memory.extract.get_extractor`, `Extractor`; `velmo.memory.fact_store.FactStore.write`; `langchain_core.messages.HumanMessage`.
- Produces: `Agent.__init__(..., extractor=None)` (défaut `get_extractor()`) ; l'écriture mémoire dans `Agent.respond`.

- [ ] **Step 1: Write the failing test**

Ajouter à la fin de `tests/test_agent.py` :

```python
from velmo.memory.fact_store import LocalFactStore


def test_respond_captures_durable_fact_automatically():
    # 003b: a durable fact stated in conversation is extracted and written,
    # with no explicit remember_fact call.
    from conftest import build_reference_agent

    store = LocalFactStore()
    agent = build_reference_agent(store)
    agent.respond("u-auto", "Tu peux me tutoyer.")
    keys = {f.key for f in agent.inspect_memory("u-auto")}
    assert "tutoiement" in keys


def test_respond_off_topic_writes_nothing():
    from conftest import build_reference_agent

    store = LocalFactStore()
    agent = build_reference_agent(store)
    agent.respond("u-quiet", "Il fait beau aujourd'hui !")
    assert agent.inspect_memory("u-quiet") == []
```

> Place the two imports at the top of `tests/test_agent.py` if not already present (ruff E402). `build_reference_agent` may be imported inside the test bodies as shown, matching the file's existing style — keep whichever the file already uses; do not introduce mid-file module-level imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent.py -q -k "captures_durable or off_topic"`
Expected: FAIL (`inspect_memory` empty — nothing writes facts yet).

- [ ] **Step 3: Wire the extractor into the agent**

Dans `src/velmo/agent.py` :

Ajouter les imports en tête :

```python
from langchain_core.messages import HumanMessage

from .memory.extract import Extractor, get_extractor
```

Dans `Agent.__init__`, ajouter le paramètre et l'attribut (après `store`) :

```python
    def __init__(
        self,
        chat_model: BaseChatModel | None,
        guardrails: GuardrailEngine,
        session=None,
        kb=None,
        checkpointer: BaseCheckpointSaver | None = None,
        store=None,
        extractor: Extractor | None = None,
    ) -> None:
        self.chat_model = chat_model
        self.guardrails = guardrails
        self.session = session
        self.kb = kb
        self.checkpointer: BaseCheckpointSaver = checkpointer or get_checkpointer()
        self.store = store if store is not None else get_fact_store()
        self.extractor: Extractor = extractor if extractor is not None else get_extractor()
```

Dans `Agent.respond`, insérer l'écriture mémoire **après `answer`, avant le garde-fou de sortie** :

```python
        answer = agent_graph.answer(
            self.session,
            user_id,
            self.kb,
            message,
            chat_model=self.chat_model,
            checkpointer=self.checkpointer,
            thread_id=user_id,
            store=self.store,
        )

        # Memory write step of the pipeline: extract durable facts from the user
        # message and persist them (FactStore.write applies FR-009 consolidation).
        for fact in self.extractor.extract(user_id, [HumanMessage(content=message)]):
            self.store.write(fact)

        gate_out = self.guardrails.check_output(answer)
        if not gate_out.allowed:
            answer = gate_out.refusal or DEFAULT_REFUSAL
        return answer
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_agent.py -q`
Expected: PASS (existants + 2 nouveaux).

Run: `uv run pytest tests/ -q`
Expected: no new failures — 8 pré-existants (guardrails ×5, mlops ×3) inchangés. (L'écriture mémoire est un effet de bord inoffensif pour les autres tests.)

- [ ] **Step 5: Commit**

```bash
git add src/velmo/agent.py tests/test_agent.py
git commit -m "feat: wire per-turn fact extraction into Agent.respond (memory write step)"
```

---

### Task 5: Acceptance R2 automatique + R4 sans perte + docs

**Files:**
- Modify: `tests/acceptance/test_memory.py` (append)
- Modify: `CLAUDE.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `conftest.build_reference_agent(store=None)`; `velmo.memory.fact_store.LocalFactStore`.
- Produces: (aucune API — tests + docs)

- [ ] **Step 1: Add the acceptance tests**

Ajouter à la fin de `tests/acceptance/test_memory.py` (les imports `LocalFactStore` et `build_reference_agent` y sont déjà en tête) :

```python
def test_cross_session_automatic_capture():
    # R2 automatique : un fait durable énoncé en conversation (sans remember_fact
    # manuel) est capté, puis retrouvé dans une nouvelle session (même Store).
    store = LocalFactStore()
    s1 = build_reference_agent(store)
    s1.respond("acc-auto", "Bonjour, tu peux me tutoyer. Je chausse du L.")

    s2 = build_reference_agent(store)  # nouvelle session, même client, même Store
    facts = {f.key: f.content for f in s2.inspect_memory("acc-auto")}
    assert facts.get("tutoiement") == "oui"
    assert facts.get("pointure") == "L"


def test_r4_no_loss_beyond_window():
    # R4 : un fait donné au 1er tour survit au-delà de 30 messages (capté à
    # l'arrivée, jamais perdu par la fenêtre glissante).
    store = LocalFactStore()
    agent = build_reference_agent(store)
    user = "acc-r4"
    agent.respond(user, "Tu peux me tutoyer.")
    for i in range(31):
        agent.respond(user, f"Question de suivi {i} sur un maillot.")

    keys = {f.key for f in agent.inspect_memory(user)}
    assert "tutoiement" in keys


def test_repeated_order_not_duplicated():
    # L'extraction par tour revoit le même numéro plusieurs fois -> une entrée.
    store = LocalFactStore()
    agent = build_reference_agent(store)
    user = "acc-dedup"
    agent.respond(user, "Ma commande O-2024-0101 est en retard.")
    agent.respond(user, "Des nouvelles de O-2024-0101 ?")
    orders = [f for f in agent.inspect_memory(user) if f.fact_type == "order_info"]
    assert len(orders) == 1
```

- [ ] **Step 2: Run the acceptance tests**

Run: `uv run pytest tests/acceptance/test_memory.py -q`
Expected: PASS (existants + 3 nouveaux).

- [ ] **Step 3: Update the documentation**

Dans `CLAUDE.md`, à la fin du bullet **Mémoire long terme** de la section « Trois modules à construire » (ou équivalent décrivant la mémoire), ajouter :

```markdown
  L'**écriture mémoire** est branchée (chantier 003b) : à chaque tour,
  `Agent.respond` passe le message dans `velmo.memory.extract.get_extractor()`
  (`DeterministicExtractor` hors-ligne / `LangMemExtractor` — LangMem stateless sur
  Kimi — en prod) et écrit les faits durables via le `FactStore`. Contrat
  d'éligibilité : seulement des faits durables sur le client (hors-sujet → rien).
  Couvre R4 (extraction à l'arrivée → rien de perdu au-delà des 30 messages) et
  rend R2 automatique.
```

Dans `README.md`, section « Features », remplacer la ligne mémoire durable par :

```markdown
- Mémoire durable et isolée par client : extraction automatique des faits durables (FactStore Chroma/local), droit à l'oubli (RGPD) et inspection
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest tests/ -q`
Expected: tous les tests mémoire passent ; seuls restent rouges les 8 pré-existants (guardrails ×5, mlops ×3). Zéro xfail.

Run: `uv run ruff check .`
Expected: All checks passed.

- [ ] **Step 5: Commit**

```bash
git add tests/acceptance/test_memory.py CLAUDE.md README.md
git commit -m "test: automatic fact capture (R2) and no-loss beyond window (R4) + docs"
```

---

## Self-Review

**1. Spec coverage :**
- Mécanisme unifié / extraction par tour → Task 4 (branchement dans `respond`), acceptance Task 5. ✅
- R4 sans perte → Task 4 + `test_r4_no_loss_beyond_window` Task 5. ✅
- R2 automatique → Task 4 + `test_cross_session_automatic_capture` Task 5. ✅
- Extracteur : refactor `extract(user_id, messages)` + `DeterministicExtractor` + pointure → Task 2. ✅
- `LangMemExtractor` + `get_extractor()` + `langmem` extra → Task 3. ✅
- Contrat d'éligibilité testable (hors-sujet → 0 fait) → Task 2 (`test_off_topic_message_extracts_nothing`) + Task 4 (`test_respond_off_topic_writes_nothing`). ✅
- Consolidation FR-009 seule autorité → inchangée (`FactStore.write`), ré-écriture sémantique via clé existante ; épisodique dédup → Task 1. ✅
- Clé épisodique = hash contenu → Task 1. ✅
- Différé (async, résumé riche, LangMem stateful, test Chroma) → non implémenté, documenté dans la spec §8. ✅

**2. Placeholder scan :** aucun TBD/TODO ; chaque étape porte le code complet. Le `LangMemExtractor` est un seam prod complet (non testé offline, comme `ChromaFactStore`). ✅

**3. Type consistency :** `Extractor.extract(user_id: str, messages: list[BaseMessage]) -> list[Fact]` identique Task 2 (déf) ↔ Task 3 (`LangMemExtractor`) ↔ Task 4 (appel `self.extractor.extract(user_id, [HumanMessage(...)])`). `episodic_storage_key(fact) -> str` même signature Task 1. `get_extractor() -> Extractor` cohérent Task 3 ↔ Task 4. `Fact.new(user_id, fact_type, key, content, source="extractor")` partout. `MemoryFact(fact_type, key, content)` mappé en `Fact` dans `LangMemExtractor`. ✅
