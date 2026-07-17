#!/usr/bin/env bash
# Container entrypoint: prepare the data stores, then serve the Streamlit demo.
# Postgres is ephemeral (re-seeded each start); Chroma is persistent (seed FAQ once).
set -euo pipefail

echo "Waiting for Postgres..."
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
