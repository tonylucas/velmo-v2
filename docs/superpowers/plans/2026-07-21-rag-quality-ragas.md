# Chantier 005d — Qualité RAG mesurée — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the memory facts retrieved for a turn as a dedicated Langfuse `retriever` observation, so a RAGAS evaluator configured in the Langfuse UI can score `faithfulness` and `answer_relevancy` against the context the model actually saw.

**Architecture:** `Turn` — the protocol `Agent.respond` already uses to open and close a traced turn — gains one method, `record_retrieval`. `agent_graph.answer` stops taking a bare `callbacks` list and takes the `Turn` itself, so it can record the memory retrieval where that retrieval happens. The documents are derived from `render_facts`, the same function that builds the prompt text, so the judge and the model can never see different context.

**Tech Stack:** Python 3.11, Langfuse SDK v4 (already a dependency via the `obs` extra), LangChain/LangGraph, pytest, ruff, uv. **No new dependency is added by this plan.**

## Global Constraints

- Everything in code is **English** — identifiers, filenames, commit messages, docstrings, comments. Only end-user-facing Velmo text (the agent's replies) and operator-facing docs (`infra/README.md`, `docs/superpowers/specs/*`) stay French.
- **No new dependency.** Not `ragas`, not anything else. The scoring is configuration in the Langfuse UI, not code. A task that adds a package to `pyproject.toml` has misread the spec.
- **Offline first.** With no `LANGFUSE_*` credentials, `get_tracer()` returns `NoOpTracer`, `record_retrieval` is a no-op, and behaviour is identical to today. No test may require network access or credentials.
- **Import `langfuse` lazily**, inside the production branch only. `import velmo.observability` must never import `langfuse`; `tests/test_observability.py` pins this in a subprocess.
- `ruff check .` and `ruff format` must be clean. Run `make fmt`, but **commit only the files you changed** — `make fmt` also reformats several files carrying unrelated pre-existing formatting debt.
- `uv run mypy src` reports **107** pre-existing errors when the `obs` extra is installed, **110** when it is not (the three extra are `import-not-found` on the lazy `langfuse` imports). Do not fix any of them; add none.
- Full suite baseline: **221 passed**. It must stay green at every commit.
- Use `uv run pytest` / `uv run ruff` / `uv run mypy`, never the bare commands.
- Each task is one PR in a Graphite stack. Every PR carries, in its description, a verification command **and its expected output**.

## File Structure

| File | Responsibility |
|---|---|
| `src/velmo/observability.py` | `Turn.record_retrieval` on the protocol, `NoOpTurn` and `LangfuseTurn` implementations, the `MEMORY_RETRIEVAL_NAME` span-name constant |
| `src/velmo/memory/facts.py` | `retrieved_documents(facts)` — the injected lines without their markdown bullet, derived from `render_facts` so the two cannot drift |
| `src/velmo/agent_graph.py` | `answer` takes `turn` instead of `callbacks`; records the memory retrieval |
| `src/velmo/agent.py` | passes `turn=turn` instead of `callbacks=turn.callbacks` |
| `tests/test_observability.py` | `record_retrieval` contract on the no-op path |
| `tests/test_facts.py` | `retrieved_documents` derives correctly from `render_facts` |
| `tests/test_agent_observability.py` | `respond` records one retrieval per turn, with the right documents |
| `infra/README.md` | runbook: configuring the RAGAS evaluator in the Langfuse UI |

## Verified facts (do not re-derive)

Checked against the running code and the installed SDK. Trust them.

1. `render_facts(facts)` (`src/velmo/memory/facts.py:54`) is exactly:
   ```python
   return "\n".join(f"- {f.key} : {f.content}" for f in facts)
   ```
   Note the leading `"- "` on every line, and that `render_facts([])` returns `""`.
2. `agent_graph.answer` builds the memory context inside an `if store is not None:` block (`src/velmo/agent_graph.py:161-175`) and already records a `Trace` step there with `count` and `keys` — but never the fact contents.
3. `agent_graph.answer` has exactly one production caller, `src/velmo/agent.py:102`. Five test call sites exist (`tests/test_agent_graph.py:164`, `tests/test_graph_trace.py:100,115,150,159`); none passes `callbacks`, so a keyword-only parameter with a `None` default leaves them untouched.
4. Langfuse 4.14.1 exposes `client.start_observation(*, name: str, as_type=…, input=…, output=…, …)`. `as_type` accepts the literal `"retriever"`. The returned object has `.end()`.
5. `LangfuseTurn.__init__` has already entered `start_as_current_observation`, so an observation started during the turn nests under `handle-turn` automatically — no parent needs to be passed.

## Langfuse best practices this plan follows

- **Observation type carries meaning.** A retrieval must be `as_type="retriever"`, not a generic span: the docs state that evaluators and dashboards filter on observation type.
- **Verb-first, low-cardinality names.** `retrieve-memory`, never a name carrying a user id or a fact count. Names are treated as an API — a rename silently breaks saved views and evaluators.
- **Meaningful input/output.** The retriever's `input` is the query that drove the search; its `output` is the list of documents. Both are what an evaluator maps to `question` and `contexts`.

---

### Task 1 (PR 2, branch `ragas-eval/record-retrieval`): the `record_retrieval` capability

Adds the method and its two implementations. **Nothing calls it yet** — that is Task 2. This task changes no behaviour, which is exactly why it is reviewable on its own.

**Files:**
- Modify: `src/velmo/observability.py` (the `Turn` protocol, `NoOpTurn`, `LangfuseTurn`, and the span-name constants near the top)
- Test: `tests/test_observability.py` (extend)

**Interfaces:**
- Consumes: nothing new.
- Produces, for Task 2:
  - `Turn.record_retrieval(self, name: str, query: str, documents: list[str]) -> None`
  - `MEMORY_RETRIEVAL_NAME = "retrieve-memory"` in `src/velmo/observability.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_observability.py`:

```python
def test_a_noop_turn_swallows_a_recorded_retrieval() -> None:
    turn = NoOpTracer().start_turn("C-marc-dubois", "bonjour")

    assert turn.record_retrieval("retrieve-memory", "bonjour", ["taille : fait du L"]) is None


def test_the_memory_retrieval_span_name_is_stable() -> None:
    # Langfuse treats observation names as an API: dashboards, saved views and
    # evaluators all match on them, so a rename silently breaks them. Pinning the
    # value here makes an accidental rename a test failure rather than a silent
    # gap in someone's dashboard.
    assert observability.MEMORY_RETRIEVAL_NAME == "retrieve-memory"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_observability.py -v`

Expected: FAIL — `AttributeError: 'NoOpTurn' object has no attribute 'record_retrieval'` and `AttributeError: module 'velmo.observability' has no attribute 'MEMORY_RETRIEVAL_NAME'`.

- [ ] **Step 3: Add the span-name constant**

In `src/velmo/observability.py`, just below the existing `TURN_SPAN_NAME` definition:

```python
# The memory RAG step, named by the action it performs. Same low-cardinality rule
# as TURN_SPAN_NAME: an evaluator or a saved view that matches on this name breaks
# silently if it changes, so it is pinned by a test.
MEMORY_RETRIEVAL_NAME = "retrieve-memory"
```

- [ ] **Step 4: Add the method to the protocol**

In `src/velmo/observability.py`, inside `class Turn(Protocol)`, between `callbacks` and `end`:

```python
    def record_retrieval(self, name: str, query: str, documents: list[str]) -> None:
        """Record one RAG retrieval as a child observation of this turn.

        `documents` is the retrieved context exactly as the model received it, so
        an evaluator scoring faithfulness judges what the model actually saw. An
        empty list is still worth recording: retrieving nothing is the diagnosis
        of an off-topic answer, not a reason to skip the observation."""
        ...
```

- [ ] **Step 5: Implement the no-op**

In `src/velmo/observability.py`, inside `class NoOpTurn`, above `end`:

```python
    def record_retrieval(self, name: str, query: str, documents: list[str]) -> None:
        return None
```

- [ ] **Step 6: Implement the Langfuse version**

In `src/velmo/observability.py`, inside `class LangfuseTurn`, above `end`:

```python
    def record_retrieval(self, name: str, query: str, documents: list[str]) -> None:
        # as_type="retriever" is not decoration: evaluators and dashboards filter
        # on observation type, so a retrieval typed as a plain span is invisible
        # to them. The observation nests under the turn's span automatically —
        # __init__ already entered start_as_current_observation.
        observation = self._client.start_observation(
            name=name, as_type="retriever", input=query, output=documents
        )
        observation.end()
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_observability.py -v`

Expected: PASS. The file had 7 tests, so it now reports **9 passed**.

- [ ] **Step 8: Run the full suite and the linters**

Run: `uv run pytest tests/ -q && make fmt && uv run ruff check .`

Expected: **223 passed**, ruff `All checks passed!`.

- [ ] **Step 9: Create the branch and commit**

```bash
git add src/velmo/observability.py tests/test_observability.py
gt create ragas-eval/record-retrieval -m "feat(obs): let a turn record a RAG retrieval as a retriever observation"
```

---

### Task 2 (PR 3, branch `ragas-eval/memory-retriever-span`): record the memory retrieval

The task that produces the visible effect. Two changes to `agent_graph.answer` that belong together: threading the `Turn` in, and using it. Threading it without using it would be dead code.

**Files:**
- Create nothing.
- Modify: `src/velmo/memory/facts.py` (add `retrieved_documents` beside `render_facts`)
- Modify: `src/velmo/agent_graph.py` (`answer` signature and the memory block, lines 145-186)
- Modify: `src/velmo/agent.py:102-113` (pass `turn=` instead of `callbacks=`)
- Test: `tests/test_facts.py` (extend), `tests/test_agent_observability.py` (extend)

**Interfaces:**
- Consumes from Task 1: `Turn.record_retrieval(name, query, documents)` and `MEMORY_RETRIEVAL_NAME`.
- Produces: `velmo.memory.facts.retrieved_documents(facts: list[Fact]) -> list[str]`; `agent_graph.answer(..., turn: Turn | None = None)` replacing the `callbacks` parameter.

- [ ] **Step 1: Write the failing test for the document derivation**

Append to `tests/test_facts.py`:

```python
from velmo.memory.facts import Fact, render_facts, retrieved_documents


def test_retrieved_documents_are_the_prompt_lines_without_the_bullet() -> None:
    # The judge must score the context the model saw. Deriving from render_facts
    # rather than re-formatting is what guarantees the two cannot drift apart;
    # asserting against a hand-written string would only freeze a typo.
    facts = [
        Fact.new(user_id="u", fact_type="preference", key="taille", content="fait du L"),
        Fact.new(user_id="u", fact_type="preference", key="couleur", content="bleu"),
    ]

    documents = retrieved_documents(facts)

    assert documents == [line.removeprefix("- ") for line in render_facts(facts).splitlines()]
    assert documents == ["taille : fait du L", "couleur : bleu"]


def test_no_facts_retrieves_no_documents() -> None:
    assert retrieved_documents([]) == []
```

Check `tests/test_facts.py` for how it already builds a `Fact` and reuse that shape — the constructor arguments above must match the real dataclass.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_facts.py -v`

Expected: FAIL — `ImportError: cannot import name 'retrieved_documents' from 'velmo.memory.facts'`.

- [ ] **Step 3: Implement the derivation**

In `src/velmo/memory/facts.py`, immediately below `render_facts`:

```python
def retrieved_documents(facts: list[Fact]) -> list[str]:
    """The injected memory lines, one per fact, without the markdown bullet.

    Derived from `render_facts` rather than re-formatted, so the context a judge
    scores can never drift from the context the model was given. The bullet is
    prompt presentation, not content: keeping it would put an artefact in every
    document that an evaluator has to learn to ignore.
    """
    return [line.removeprefix("- ") for line in render_facts(facts).splitlines()]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_facts.py -v`

Expected: PASS.

- [ ] **Step 5: Write the failing test for the wiring**

Append to `tests/test_agent_observability.py`. The file already defines `RecordingTurn` and `RecordingTracer`; extend `RecordingTurn` to capture retrievals, then add the tests:

```python
# Add to RecordingTurn.__init__:
#     self.retrievals: list[tuple[str, str, list[str]]] = []
#
# Add to RecordingTurn:
#     def record_retrieval(self, name: str, query: str, documents: list[str]) -> None:
#         self.retrievals.append((name, query, documents))


def test_a_turn_records_its_memory_retrieval() -> None:
    from velmo.memory.fact_store import LocalFactStore
    from velmo.memory.facts import Fact

    store = LocalFactStore()
    store.write(
        Fact.new(
            user_id="C-marc-dubois", fact_type="preference", key="taille", content="fait du L"
        )
    )
    tracer = RecordingTracer()
    agent = build_reference_agent(store, tracer=tracer)

    agent.respond("C-marc-dubois", "Quelle taille je prends ?")

    name, query, documents = tracer.turns[0].retrievals[0]
    assert name == "retrieve-memory"
    assert query == "Quelle taille je prends ?"
    assert "taille : fait du L" in documents


def test_a_turn_with_no_stored_facts_still_records_an_empty_retrieval() -> None:
    # Retrieving nothing is a diagnosis, not a reason to skip the observation.
    tracer = RecordingTracer()

    build_reference_agent(tracer=tracer).respond("C-inconnu-du-store", "Bonjour")

    assert tracer.turns[0].retrievals[0][2] == []


def test_exactly_one_retrieval_is_recorded_per_turn() -> None:
    tracer = RecordingTracer()

    build_reference_agent(tracer=tracer).respond(
        "C-marc-dubois", "Où en est ma commande O-2024-0101 ?"
    )

    assert len(tracer.turns[0].retrievals) == 1
```

`Fact` is a pydantic model whose `created_at` / `updated_at` are required, so build facts with the `Fact.new(user_id, fact_type, key, content)` factory — calling `Fact(...)` directly raises a validation error. `"preference"` is a valid semantic type (`SEMANTIC_TYPES = {"preference", "profile"}`), which is what makes the fact eligible for retrieval on any query.

- [ ] **Step 6: Run the test to verify it fails**

Run: `uv run pytest tests/test_agent_observability.py -v`

Expected: FAIL — `IndexError: list index out of range` on `retrievals[0]`, because nothing records yet.

- [ ] **Step 7: Swap `callbacks` for `turn` in `answer`**

In `src/velmo/agent_graph.py`, change the last parameter of `answer` from `callbacks: list[Any] | None = None` to:

```python
    turn: Turn | None = None,
```

and add the import at the top of the file:

```python
from .observability import MEMORY_RETRIEVAL_NAME, Turn
```

Then, inside `answer`, replace the `if callbacks:` line in the config block with:

```python
    callbacks = turn.callbacks if turn is not None else None
    if callbacks:
        config["callbacks"] = callbacks
```

Leave the `if checkpointer is not None:` line and the `config or None` call exactly as they are.

- [ ] **Step 8: Record the retrieval**

In `src/velmo/agent_graph.py`, inside `answer`'s `if store is not None:` block, after the existing `trace.add(...)` call and **before** `memory = render_facts(facts)`:

```python
        if turn is not None:
            # Recorded here rather than in respond(): this is where the retrieval
            # actually happens, and where the facts still exist as objects instead
            # of a flattened prompt string.
            turn.record_retrieval(MEMORY_RETRIEVAL_NAME, message, retrieved_documents(facts))
```

and extend the deferred import at the top of that block from

```python
        from .memory.facts import render_facts
```

to

```python
        from .memory.facts import render_facts, retrieved_documents
```

- [ ] **Step 9: Update the caller**

In `src/velmo/agent.py`, in the `agent_graph.answer(...)` call (around line 102-113), replace the line

```python
                callbacks=turn.callbacks,
```

with

```python
                turn=turn,
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `uv run pytest tests/test_agent_observability.py tests/test_facts.py -v`

Expected: PASS.

- [ ] **Step 11: Run the full suite and the linters**

Run: `uv run pytest tests/ -q && make fmt && uv run ruff check .`

Expected: **228 passed** (223 after Task 1, plus 2 in `test_facts.py` and 3 in `test_agent_observability.py`), ruff `All checks passed!`.

If `tests/test_agent_graph.py` or `tests/test_graph_trace.py` fail, the signature change broke a direct caller of `answer` — none of them passes `callbacks`, so a failure means the parameter was renamed positionally rather than as a keyword.

- [ ] **Step 12: Verify the eval gate did not move**

Run: `uv run python -m velmo.mlops.score`

Expected: `global=0.954`, exit code 0. Observability must never move the score.

- [ ] **Step 13: Commit on a new stacked branch**

```bash
git add src/velmo/agent_graph.py src/velmo/agent.py src/velmo/memory/facts.py \
        tests/test_facts.py tests/test_agent_observability.py
gt create ragas-eval/memory-retriever-span -m "feat(obs): record the memory retrieval as a retriever observation"
```

---

### Task 3 (PR 4, branch `ragas-eval/evaluator-runbook`): the evaluator runbook

Documentation only. The scoring itself is configuration in the Langfuse UI — there is no code to write, and inventing some would be the mistake this chantier exists to avoid.

**Files:**
- Modify: `infra/README.md` (append a section after the existing "Observabilité (Langfuse)" section)

**Interfaces:**
- Consumes: the `retrieve-memory` observation produced by Task 2.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Append the runbook section**

Add to `infra/README.md`, after the existing Langfuse section:

```markdown
### Qualité RAG (évaluateur RAGAS)

Les scores de qualité RAG — `faithfulness` (la réponse est-elle fidèle aux faits
récupérés ?) et `answer_relevancy` (répond-elle à la question ?) — sont produits par
un **évaluateur Langfuse**, pas par du code de ce dépôt. Le chantier 005d expose la
donnée dont l'évaluateur a besoin ; le scoring se configure dans l'interface.

Prérequis : les clés Langfuse sont posées (section précédente), et une **LLM
Connection** est configurée dans Langfuse (Settings → LLM Connections) avec un modèle
supportant les sorties structurées.

1. Dans le projet Langfuse : **Evaluations → Evaluators → New evaluator**.
2. Choisir dans le catalogue le template **RAGAS** correspondant (`faithfulness`,
   puis répéter pour `answer relevancy`).
3. Cibler les **observations**, filtrées sur le type `generation` — c'"'"'est là que
   vivent la question et la réponse du modèle.
4. Mapper les trois variables du template :
   - `question` → l'"'"'input de la trace (le message client, déjà masqué) ;
   - `contexts` → l'"'"'output de l'"'"'observation nommée **`retrieve-memory`** (type
     `retriever`) ;
   - `answer` → l'"'"'output de l'"'"'observation `generation`.
   L'"'"'aperçu en direct montre le prompt rempli avec de vraies données : vérifier que
   `contexts` contient bien les lignes de faits, et pas le prompt système entier.
5. Régler l'"'"'échantillonnage (5 % suffit pour commencer) et activer.

Les scores apparaissent ensuite sur les traces et sont agrégeables en dashboard.

**Ce qui n'"'"'est pas scoré, et pourquoi.** Les tours traités par le **routage
déterministe** n'"'"'appellent aucun modèle : ils répondent par un gabarit qui recopie
ses sources par construction. Mesurer leur « fidélité » ne dirait rien. Le filtre sur
les observations `generation` les écarte naturellement.

**Le gate CI reste hors-ligne.** Ces scores vivent sur les traces de production et
n'"'"'entrent jamais dans `mlops/report.md` : faire dépendre la note bloquante d'"'"'un juge
LLM la rendrait non déterministe, l'"'"'inverse de ce que garantit le chantier 005a.
```

Write the section with the Write or Edit tool, not a shell heredoc — the escaping above is an artefact of this plan file, and the real document must contain plain apostrophes.

- [ ] **Step 2: Check the whole suite is untouched**

Run: `uv run pytest tests/ -q`

Expected: **228 passed**. A documentation change must move nothing.

- [ ] **Step 3: Commit on a new stacked branch**

```bash
git add infra/README.md
gt create ragas-eval/evaluator-runbook -m "docs(obs): runbook for the RAGAS evaluator in the Langfuse UI"
```

---

### Submitting the stack

After Task 3, the stack is `main → ragas-eval/design → ragas-eval/record-retrieval → ragas-eval/memory-retriever-span → ragas-eval/evaluator-runbook`.

```bash
gt ls          # confirm the first branch's parent is main
gt submit --no-interactive
```

Then set each PR's description with `gh pr edit <n> --body-file <path>`, never a shell heredoc — heredocs break markdown tables and code blocks. Each description carries the stack context, why the PR exists, and the verification command with its expected output.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §1 one call site to instrument | Task 2, step 8 |
| §2 no new dependency | Global Constraints; no task touches `pyproject.toml` |
| §3a `record_retrieval` on `Turn`, both implementations | Task 1 |
| §3a `as_type="retriever"` | Task 1, step 6 |
| §3b `answer` takes `turn`, not `callbacks` | Task 2, steps 7 and 9 |
| §3c documents = prompt lines minus the bullet, same order | Task 2, steps 1-3 |
| §3c empty context still recorded | Task 2, step 5 (`test_a_turn_with_no_stored_facts_still_records_an_empty_retrieval`) |
| §3d no new data exposed | no code needed; already true — the facts were in the system prompt |
| §4 five test contracts | Tasks 1 and 2 |
| §5 four-PR stack | Task boundaries = PR boundaries; PR 1 is the spec + this plan |
| §6 nothing pulled into the CI gate | Task 2, step 12 asserts the score is unchanged |

**Placeholder scan:** no TBD, no "handle edge cases", every code step carries its code. Two steps deliberately tell the implementer to read the real constructor signature (`Fact`, `LocalFactStore.write`) rather than trust the plan's illustrative arguments — that is an instruction to verify, not a placeholder.

**Type consistency:** `record_retrieval(name: str, query: str, documents: list[str]) -> None` is spelled identically in the protocol, both implementations, the test double and the call site. `retrieved_documents(facts) -> list[str]` likewise. `MEMORY_RETRIEVAL_NAME` is defined in Task 1 and imported in Task 2.

**Two defects found and fixed in review:**

1. A draft of Task 2's end-to-end test asserted `... or document != ""` — an escape hatch that made it near-impossible to fail. It was deleted rather than weakened further: the contract it half-tested is fully covered by `test_retrieved_documents_are_the_prompt_lines_without_the_bullet`, which compares against `render_facts` directly.
2. The tests built facts with `Fact(user_id=…, fact_type=…, key=…, content=…)`. `Fact` is a pydantic model with required `created_at` / `updated_at`, so every one of those calls would have raised a validation error before testing anything. Corrected to the `Fact.new(...)` factory.
