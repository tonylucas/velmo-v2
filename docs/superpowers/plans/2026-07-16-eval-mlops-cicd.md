# Chantier 005b — CI/CD trunk-based & ACA deploy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Orchestrate delivery around the 005a eval gate (GitHub Actions: label→gate, invalidation, tag→Release) and add a detachable Azure Container Apps deployment of the Streamlit demo.

**Architecture:** Two layers. The **CI core** (workflows) needs no cloud: a PR label triggers the offline eval gate, a new commit invalidates it, a tag runs the gate and cuts a GitHub Release carrying the versioned scores. The **deploy layer** (`deploy.yml` + a Docker image + a startup script) is isolated: a tag builds the image and rolls a new ACA revision. Deleting `deploy.yml` reverts cleanly to the CI core.

**Tech Stack:** Python 3.11, uv, pytest, ruff, mypy; GitHub Actions (YAML); Docker; Azure Container Apps (`az` CLI); Streamlit; Chroma; Postgres.

## Global Constraints

- All code, identifiers, docstrings, comments, commit messages **in English**. Only user-facing product text stays French.
- `ruff format` + `ruff check` clean; `mypy src/velmo` clean on new/changed Python. `mypy src` (whole tree) has pre-existing unrelated errors — out of scope; only touched files must stay clean.
- Verification tooling available: `pytest`, `ruff`, `mypy`, `docker`, `python -c "import yaml"`. **Not** available: `shellcheck`, `hadolint`, `actionlint` — verify shell with `bash -n`, YAML with `yaml.safe_load`.
- Exact Azure names (verbatim): RG `tlucasRG`, ACA env `Velmo2Tony`, region `swedencentral`, app `velmo2-tony`, Postgres app `velmo2-tony-pg`, Chroma app `velmo2-tony-chroma`, storage `storagetonylucas`, file share `chromadata`, env storage name `chromastore`.
- Env var contract (from `.env.example`): `DB_URL` (`postgresql+psycopg://…`), `CHROMA_URL` (`http://host:port`), `AZURE_AI_INFERENCE_ENDPOINT/_API_KEY/_MODEL`, `AZURE_CONTENT_SAFETY_ENDPOINT/_KEY`, `EVAL_MIN_SCORE` (default `0.8`), `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE`.
- Content Safety resource already exists (`eagwu-0283-resource`) — reuse the `.env` endpoint/key, never create one.
- Embedding model `intfloat/multilingual-e5-small` is **baked into the image at build** (needs HuggingFace reachable during build only); runtime is offline (`HF_HUB_OFFLINE=1`).
- The gate command is `python -m velmo.mlops.score --min-score <n>` (delivered in 005a).

---

## File Structure

- Modify `src/velmo/kb_store.py` — add `parse_chroma_url()`; use it in `get_kb`.
- Modify `src/velmo/memory/fact_store.py` — use `parse_chroma_url()` in `get_fact_store`.
- Modify `src/velmo/sampledata.py` — add `seed_if_empty(session)`.
- Modify `scripts/seed.py` — call `seed_if_empty`.
- Modify `scripts/seed_kb.py` — use `parse_chroma_url()`; add `--if-empty`.
- Create `scripts/serve.sh` — container entrypoint (wait DB, migrate, seed, seed FAQ if empty, run Streamlit).
- Modify `Dockerfile` — Streamlit demo image with extras + baked model + entrypoint.
- Create `.github/workflows/eval.yml` — PR label→gate + invalidation.
- Create `.github/workflows/release.yml` — tag→gate→GitHub Release.
- Create `.github/workflows/deploy.yml` — tag→build→ACA revision (detachable).
- Create `infra/chroma-app.yaml` — Chroma Container App definition (volume mount).
- Create `infra/README.md` — provisioning + activation runbook + rollback.
- Modify `.env.example` — drop the stale `CHROMA_HOST`/`CHROMA_PORT` assumption note (all Chroma access is via `CHROMA_URL`).

Tests: `tests/test_vector_config.py`, `tests/test_seed_idempotent.py`.

---

## Task 1: Single `CHROMA_URL` parser, used everywhere

**Files:**
- Modify: `src/velmo/kb_store.py`
- Modify: `src/velmo/memory/fact_store.py`
- Modify: `scripts/seed_kb.py`
- Test: `tests/test_vector_config.py`

**Interfaces:**
- Produces: `parse_chroma_url(url: str | None = None) -> tuple[str, int]` in `velmo.kb_store` — parses `CHROMA_URL` (or the given url) into `(host, port)`, defaulting host `localhost`, port `8000`.

**Why:** `scripts/seed_kb.py` reads `CHROMA_HOST`/`CHROMA_PORT` while `kb_store`/`fact_store` read `CHROMA_URL` — three copies, one inconsistent. One tested helper removes the divergence and lets the container wire a single `CHROMA_URL`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vector_config.py
import pytest

from velmo.kb_store import parse_chroma_url


def test_explicit_url():
    assert parse_chroma_url("http://localhost:8001") == ("localhost", 8001)


def test_internal_fqdn():
    assert parse_chroma_url("http://velmo2-tony-chroma.internal.foo.io:8000") == (
        "velmo2-tony-chroma.internal.foo.io",
        8000,
    )


def test_default_port_when_missing():
    assert parse_chroma_url("http://host") == ("host", 8000)


def test_reads_env_when_no_arg(monkeypatch):
    monkeypatch.setenv("CHROMA_URL", "http://envhost:9000")
    assert parse_chroma_url() == ("envhost", 9000)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_vector_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_chroma_url'`.

- [ ] **Step 3: Add the helper in `src/velmo/kb_store.py`**

Add near the top-level imports (the file already imports `os` and `from urllib.parse import urlparse`):

```python
def parse_chroma_url(url: str | None = None) -> tuple[str, int]:
    """Parse CHROMA_URL (or the given url) into (host, port).

    Defaults to localhost:8000. Single source of truth for the three call sites
    (kb_store, fact_store, seed_kb) so they cannot drift apart.
    """
    parsed = urlparse(url or os.environ["CHROMA_URL"])
    return parsed.hostname or "localhost", parsed.port or 8000
```

- [ ] **Step 4: Use it in `get_kb` (`src/velmo/kb_store.py`)**

Replace the existing two lines:

```python
    parsed = urlparse(os.environ["CHROMA_URL"])
    client = chromadb.HttpClient(host=parsed.hostname or "localhost", port=parsed.port or 8000)
```

with:

```python
    host, port = parse_chroma_url()
    client = chromadb.HttpClient(host=host, port=port)
```

- [ ] **Step 5: Use it in `get_fact_store` (`src/velmo/memory/fact_store.py`)**

At the top of `fact_store.py`, add the import:

```python
from velmo.kb_store import parse_chroma_url
```

Replace the existing two lines in `get_fact_store`:

```python
    parsed = urlparse(os.environ["CHROMA_URL"])
    client = chromadb.HttpClient(host=parsed.hostname or "localhost", port=parsed.port or 8000)
```

with:

```python
    host, port = parse_chroma_url()
    client = chromadb.HttpClient(host=host, port=port)
```

Remove the now-unused `from urllib.parse import urlparse` import from `fact_store.py` if present (ruff will flag it otherwise).

- [ ] **Step 6: Use it in `scripts/seed_kb.py` and add `--if-empty`**

Replace the body of `scripts/seed_kb.py`'s `main` with:

```python
def main() -> None:
    import argparse

    import chromadb
    from chromadb.utils import embedding_functions

    from velmo.kb_store import parse_chroma_url

    parser = argparse.ArgumentParser()
    parser.add_argument("--if-empty", action="store_true", help="skip when velmo_faq already has documents")
    args = parser.parse_args()

    host, port = parse_chroma_url()
    client = chromadb.HttpClient(host=host, port=port)
    embedder = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    )
    collection = client.get_or_create_collection("velmo_faq", embedding_function=embedder)

    if args.if_empty and collection.count() > 0:
        print("FAQ already ingested — skipping.")
        return

    docs, ids, metas = [], [], []
    for path in sorted(KB_DOCS_DIR.glob("*.md")):
        docs.append(path.read_text(encoding="utf-8"))
        ids.append(path.stem)
        metas.append({"source": path.name})

    collection.upsert(documents=docs, ids=ids, metadatas=metas)
    print(f"FAQ ingérée dans Chroma : {len(docs)} documents.")
```

- [ ] **Step 7: Run tests + gates**

Run: `uv run pytest tests/test_vector_config.py -v && uv run ruff check src/velmo scripts tests && uv run mypy src/velmo`
Expected: 4 passed; ruff clean; mypy Success.

- [ ] **Step 8: Commit**

```bash
uv run ruff format src/velmo scripts tests
git add src/velmo/kb_store.py src/velmo/memory/fact_store.py scripts/seed_kb.py tests/test_vector_config.py
git commit -m "refactor(vector): single CHROMA_URL parser; seed_kb --if-empty"
```

---

## Task 2: Idempotent business seed

**Files:**
- Modify: `src/velmo/sampledata.py`
- Modify: `scripts/seed.py`
- Test: `tests/test_seed_idempotent.py`

**Interfaces:**
- Consumes: `seed(session) -> None` (existing), `fresh_sqlite_session()` (existing).
- Produces: `seed_if_empty(session) -> bool` in `velmo.sampledata` — seeds only when no customer exists; returns `True` if it seeded, `False` if it skipped.

**Why:** the ephemeral Postgres is re-seeded on every container start (§3 of the spec). The seed must be safe to re-run without duplicate-key errors.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_seed_idempotent.py
from sqlalchemy import select

from velmo.db import Customer, fresh_sqlite_session
from velmo.sampledata import seed_if_empty


def test_seed_if_empty_is_idempotent():
    session = fresh_sqlite_session()
    assert seed_if_empty(session) is True  # first run seeds
    count = len(session.scalars(select(Customer)).all())
    assert count > 0
    assert seed_if_empty(session) is False  # second run skips
    assert len(session.scalars(select(Customer)).all()) == count  # no duplicates
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_seed_idempotent.py -v`
Expected: FAIL with `ImportError: cannot import name 'seed_if_empty'`.

- [ ] **Step 3: Add `seed_if_empty` in `src/velmo/sampledata.py`**

At the end of the module (after `seed`):

```python
def seed_if_empty(session) -> bool:
    """Seed only when the database has no customers yet. Returns whether it seeded."""
    from sqlalchemy import select

    from velmo.db import Customer

    if session.scalars(select(Customer)).first() is not None:
        return False
    seed(session)
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_seed_idempotent.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Route `scripts/seed.py` through it**

Replace the body of `main` in `scripts/seed.py` with:

```python
def main() -> None:
    from velmo.db import Base, make_engine, session_factory
    from velmo.sampledata import seed_if_empty

    engine = make_engine()
    Base.metadata.create_all(engine)
    session = session_factory()()
    if seed_if_empty(session):
        print("Base Velmo peuplée (catalogue, clients, commandes).")
    else:
        print("Base déjà peuplée — rien à faire.")
```

Remove now-unused top-level imports from `scripts/seed.py` (ruff will flag them).

- [ ] **Step 6: Gates + commit**

```bash
uv run ruff format src/velmo scripts tests && uv run ruff check src/velmo scripts tests && uv run mypy src/velmo
git add src/velmo/sampledata.py scripts/seed.py tests/test_seed_idempotent.py
git commit -m "feat(seed): idempotent seed_if_empty for ephemeral Postgres"
```

---

## Task 3: Container entrypoint `scripts/serve.sh`

**Files:**
- Create: `scripts/serve.sh`

**Interfaces:**
- Consumes: `scripts/seed.py` (idempotent), `scripts/seed_kb.py --if-empty` (Task 1), `alembic upgrade head` (reads `DB_URL` via `alembic/env.py`), `src/velmo/demo_app.py`.

**Why:** the image's single entrypoint prepares the data stores then launches Streamlit on 0.0.0.0:8000 with the watcher off (the segfault fix from the demo chantier).

- [ ] **Step 1: Write the script**

```bash
# scripts/serve.sh
#!/usr/bin/env bash
# Container entrypoint: prepare the data stores, then serve the Streamlit demo.
# Postgres is ephemeral (re-seeded each start); Chroma is persistent (seed FAQ once).
set -euo pipefail

echo "Waiting for Postgres at ${DB_URL%%\?*} ..."
until uv run python -c "import os, sqlalchemy as sa; sa.create_engine(os.environ['DB_URL']).connect().close()" 2>/dev/null; do
  sleep 2
done

echo "Applying migrations and seeding business data..."
uv run alembic upgrade head
uv run python scripts/seed.py

echo "Ingesting FAQ into Chroma if empty..."
uv run python scripts/seed_kb.py --if-empty

echo "Starting Streamlit..."
exec uv run streamlit run src/velmo/demo_app.py \
  --server.port 8000 --server.address 0.0.0.0 --server.fileWatcherType none
```

- [ ] **Step 2: Verify shell syntax**

Run: `bash -n scripts/serve.sh && echo "syntax ok"`
Expected: `syntax ok` (no output from `bash -n`, then the echo).

- [ ] **Step 3: Commit**

```bash
git add scripts/serve.sh
git commit -m "feat(deploy): container entrypoint serve.sh (migrate, seed, serve)"
```

---

## Task 4: Dockerfile for the Streamlit demo image

**Files:**
- Modify: `Dockerfile`

**Interfaces:**
- Consumes: `scripts/serve.sh` (Task 3), the `demo`/`llm`/`vector` extras from `pyproject.toml`, `uv.lock`.

**Why:** the current image installs `--no-dev` and runs the CLI. The deploy needs the demo extras, the embedding model baked in (offline runtime), and `serve.sh` as entrypoint.

- [ ] **Step 1: Replace `Dockerfile` with:**

```dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TOKENIZERS_PARALLELISM=false \
    ANONYMIZED_TELEMETRY=False \
    HF_HUB_OFFLINE=0

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
COPY src ./src
COPY eval ./eval
COPY kb ./kb
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts

RUN uv sync --extra demo --extra llm --extra vector

# Bake the embedding model into the image so runtime never contacts HuggingFace.
# Requires the HuggingFace Hub reachable DURING BUILD (one-shot).
RUN uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"

# From here on, embeddings load from the baked cache, fully offline.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

EXPOSE 8000
ENTRYPOINT ["bash", "scripts/serve.sh"]
```

- [ ] **Step 2: Verify the build (contingent on HuggingFace being reachable)**

Run: `docker build -t velmo-demo:test .`
Expected: image builds. **If HuggingFace is down** (the bake step fails with a hub/network error), the Dockerfile is still correct — record the failure as HF-dependent and re-run when HF recovers; do not work around by removing the bake. All other layers (uv sync, copies) must succeed up to the bake step.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile
git commit -m "feat(deploy): Streamlit demo image with baked embedding model"
```

---

## Task 5: CI core — PR label gate + invalidation (`eval.yml`)

**Files:**
- Create: `.github/workflows/eval.yml`

**Why:** the gate is the required check, but only on demand: labelling `ready-for-eval` runs it; a new commit removes the label (so the passed check no longer applies to stale code).

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/eval.yml
name: eval

on:
  pull_request:
    types: [labeled, synchronize]

permissions:
  contents: read
  pull-requests: write

jobs:
  gate:
    if: github.event.action == 'labeled' && github.event.label.name == 'ready-for-eval'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv python install 3.11
      - run: uv sync
      - name: Quality gate
        run: uv run python -m velmo.mlops.score --min-score "${MIN_SCORE:-0.8}"
        env:
          MIN_SCORE: ${{ vars.EVAL_MIN_SCORE }}

  invalidate:
    if: github.event.action == 'synchronize'
    runs-on: ubuntu-latest
    steps:
      - name: Drop ready-for-eval label on new commit
        run: gh pr edit "$PR" --repo "$REPO" --remove-label ready-for-eval || true
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          PR: ${{ github.event.pull_request.number }}
          REPO: ${{ github.repository }}
```

- [ ] **Step 2: Verify YAML parses**

Run: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/eval.yml')); print('yaml ok')"`
Expected: `yaml ok`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/eval.yml
git commit -m "ci: PR label-gated eval + invalidation on new commit"
```

---

## Task 6: CI core — tag → gate → Release (`release.yml`)

**Files:**
- Create: `.github/workflows/release.yml`

**Why:** a `v*.*.*` tag re-runs the gate on the tagged commit and publishes a GitHub Release whose notes carry the versioned scores (the per-version record). `mlops/report.md` is attached as an asset.

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/release.yml
name: release

on:
  push:
    tags: ['v*.*.*']

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv python install 3.11
      - run: uv sync
      - name: Eval gate + report
        run: uv run python -m velmo.mlops.score --min-score "${MIN_SCORE:-0.8}" --report mlops/report.md | tee /tmp/score.txt
        env:
          MIN_SCORE: ${{ vars.EVAL_MIN_SCORE }}
      - name: Publish GitHub Release
        run: gh release create "$TAG" mlops/report.md --title "$TAG" --notes "$(tail -1 /tmp/score.txt)"
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          TAG: ${{ github.ref_name }}
```

- [ ] **Step 2: Verify YAML parses**

Run: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml')); print('yaml ok')"`
Expected: `yaml ok`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: tag-triggered eval gate and versioned GitHub Release"
```

---

## Task 7: Deploy layer — `deploy.yml` + `infra/chroma-app.yaml` (detachable)

**Files:**
- Create: `.github/workflows/deploy.yml`
- Create: `infra/chroma-app.yaml`

**Why:** on a tag, after the gate, build the image in ACR and roll a new revision of `velmo2-tony`. Isolated so it can be deleted to fall back to the CI core. `chroma-app.yaml` is the Chroma Container App definition (volume mount) referenced by the phase-0 runbook.

- [ ] **Step 1: Write `deploy.yml`**

```yaml
# .github/workflows/deploy.yml
# Detachable deploy layer. Delete this file to revert to the CI core (eval + release).
name: deploy

on:
  push:
    tags: ['v*.*.*']

permissions:
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Azure login
        uses: azure/login@v2
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}
      - name: Build and push image to ACR
        run: az acr build --registry "$ACR" --image "velmo:$TAG" .
        env:
          ACR: ${{ secrets.ACR_NAME }}
          TAG: ${{ github.ref_name }}
      - name: Roll a new Container App revision
        run: az containerapp update -g tlucasRG -n velmo2-tony --image "$ACR.azurecr.io/velmo:$TAG"
        env:
          ACR: ${{ secrets.ACR_NAME }}
          TAG: ${{ github.ref_name }}
```

- [ ] **Step 2: Write `infra/chroma-app.yaml`**

```yaml
# infra/chroma-app.yaml — Chroma Container App with the persistent Azure Files volume.
# Referenced by the phase-0 runbook: az containerapp create ... --yaml infra/chroma-app.yaml
# Replace <sub> with the subscription id before running.
properties:
  environmentId: /subscriptions/<sub>/resourceGroups/tlucasRG/providers/Microsoft.App/managedEnvironments/Velmo2Tony
  configuration:
    ingress:
      external: false
      transport: http
      targetPort: 8000
  template:
    containers:
      - name: chroma
        image: chromadb/chroma:0.5.23
        resources:
          cpu: 0.5
          memory: 1.0Gi
        volumeMounts:
          - volumeName: chromadata
            mountPath: /chroma/chroma
    scale:
      minReplicas: 1
      maxReplicas: 1
    volumes:
      - name: chromadata
        storageType: AzureFile
        storageName: chromastore
```

- [ ] **Step 3: Verify both YAML files parse**

Run: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml')); yaml.safe_load(open('infra/chroma-app.yaml')); print('yaml ok')"`
Expected: `yaml ok`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/deploy.yml infra/chroma-app.yaml
git commit -m "ci(deploy): detachable ACA deploy on tag + chroma app definition"
```

---

## Task 8: Ops runbook + env cleanup

**Files:**
- Create: `infra/README.md`
- Modify: `.env.example`

**Why:** the whole cohort is new to Azure — the provisioning (phase 0) and activation (phase 2) commands must live in the repo as a readable runbook, plus the rollback procedure. `.env.example` should stop implying `CHROMA_HOST`/`CHROMA_PORT` (all access is via `CHROMA_URL` after Task 1).

- [ ] **Step 1: Write `infra/README.md`**

Copy the annotated phase-0 runbook and the activation/rollback sections from
`docs/superpowers/specs/2026-07-16-eval-mlops-cicd-design.md` (§6 and §2b), verbatim, into
`infra/README.md` under three headings: `## Phase 0 — provisioning (once)`,
`## Phase 2 — activation (once)`, `## Rollback`. The `## Rollback` body is:

```markdown
## Rollback

List revisions and reactivate the previous good one (instant, no rebuild):

    az containerapp revision list -g tlucasRG -n velmo2-tony -o table
    az containerapp revision set-active -g tlucasRG -n velmo2-tony --revision <previous-revision>
```

The `## Phase 2 — activation (once)` body is:

```markdown
## Phase 2 — activation (once)

1. GitHub → Settings → Secrets and variables → Actions, add:
   - `AZURE_CREDENTIALS` (the service-principal JSON from phase 0)
   - `ACR_NAME` (the Azure Container Registry name)
   - repository variable `EVAL_MIN_SCORE` = `0.8`
2. Set the app's runtime config once (env vars + secrets carry across revisions):

       az containerapp update -g tlucasRG -n velmo2-tony \
         --set-env-vars \
           DB_URL="postgresql+psycopg://app:<pgpass>@velmo2-tony-pg.internal.<domain>:5432/velmo" \
           CHROMA_URL="http://velmo2-tony-chroma.internal.<domain>:8000" \
           AZURE_AI_INFERENCE_ENDPOINT="<kimi-endpoint>" AZURE_AI_INFERENCE_MODEL="Kimi-K2.6" \
           AZURE_CONTENT_SAFETY_ENDPOINT="<safety-endpoint>" \
           HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
         --secrets azkey=<kimi-key> pgpass=<pgpass> safetykey=<safety-key> \
         --replace-env-vars AZURE_AI_INFERENCE_API_KEY=secretref:azkey \
           AZURE_CONTENT_SAFETY_KEY=secretref:safetykey \
         --cpu 1.0 --memory 2.0Gi --target-port 8000 --ingress external

   `<domain>` = `az containerapp env show -g tlucasRG -n Velmo2Tony --query properties.defaultDomain -o tsv`.
3. Branch protection on `main`: require the `eval / gate` check to pass before merge.
4. First deploy: push a tag `v1.0.0` (or run `az containerapp up --source .` once to
   create the ACR and the first image), then confirm the public URL loads.
```

- [ ] **Step 2: Clean `.env.example`**

The current `.env.example` already uses `CHROMA_URL` (no `CHROMA_HOST`/`CHROMA_PORT`), so no
key changes are needed. Add one clarifying comment above the `CHROMA_URL` line:

```
# Base vectorielle (mémoire long terme épisodique). Unique variable de connexion Chroma
# (host+port en sont dérivés) — utilisée par kb_store, fact_store et seed_kb.
CHROMA_URL=http://localhost:8001
```

- [ ] **Step 3: Verify + commit**

```bash
uv run python -c "print(open('infra/README.md').read()[:1] and 'readme ok')"
git add infra/README.md .env.example
git commit -m "docs(deploy): infra runbook (provision, activate, rollback) + env note"
```

---

## Self-Review

**1. Spec coverage.**
- §2a CI core (label→gate, invalidation, push-main gate, tag→Release) → Tasks 5, 6 (push-main gate already lives in the 005a `quality.yml`, unchanged). ✅
- §2b detachable deploy (tag→build→revision, rollback, SP auth) → Task 7 + Task 8 rollback. ✅
- §3 topology (Chroma volume) → `infra/chroma-app.yaml` Task 7; runbook Task 8. ✅
- §4 runtime env wiring → Task 8 activation. ✅
- §5 code changes: Dockerfile → Task 4; serve.sh → Task 3; idempotent seed → Task 2; seed_kb `CHROMA_URL` → Task 1. ✅
- §6 runbook → Task 8. ✅
- §7 off-ramps → documented in spec; deploy detachability realized by isolating `deploy.yml` (Task 7). ✅

**2. Placeholder scan.** Code steps carry full content. Remaining `<…>` (`<sub>`, `<domain>`, `<pgpass>`, `<previous-revision>`, `<kimi-endpoint>`…) are user-supplied runtime secrets/ids in a runbook, not plan gaps. No `TBD`/`TODO`.

**3. Type consistency.** `parse_chroma_url(url=None) -> tuple[str,int]` consumed identically in kb_store, fact_store, seed_kb. `seed_if_empty(session) -> bool` consumed by `scripts/seed.py` and the idempotency test. `serve.sh` calls the exact CLIs the earlier tasks define (`seed_kb.py --if-empty`, `seed.py`). Workflow gate command matches 005a's `python -m velmo.mlops.score --min-score`. Consistent.

**4. Testability note.** Only Tasks 1-2 are pytest-TDD (pure Python). Tasks 3-8 are infra: verified by `bash -n`, `yaml.safe_load`, and `docker build` (build contingent on HuggingFace reachability). End-to-end deploy is validated by the user at activation (phase 2), not in CI.
