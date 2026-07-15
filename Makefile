.PHONY: install up down migrate seed seed-kb chat eval ci test fmt lint typecheck

install:
	uv sync

up:
	docker compose up -d

down:
	docker compose down

migrate:
	uv run alembic upgrade head

seed:
	uv run python scripts/seed.py

seed-kb:
	uv run python scripts/seed_kb.py

chat:
	uv run python -m velmo.cli

demo:
	ANONYMIZED_TELEMETRY=False TOKENIZERS_PARALLELISM=false \
		uv run --extra demo --extra llm --extra vector \
		streamlit run src/velmo/demo_app.py --server.fileWatcherType none

eval:
	uv run python -m velmo.mlops.score

ci: test

test:
	uv run pytest tests/ -v

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff check .

typecheck:
	uv run mypy src
