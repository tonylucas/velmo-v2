"""Peuple la base Postgres avec le jeu de données de référence Velmo.

Usage : uv run python scripts/seed.py
"""

from __future__ import annotations


def main() -> None:
    from dotenv import load_dotenv

    from velmo.db import Base, make_engine, session_factory
    from velmo.sampledata import seed_if_empty

    # Same first line as the other entrypoints (cli.py, demo_app.py). Without it
    # `make_engine()` falls back to the built-in DB_URL default and silently
    # seeds a different database than the one the developer configured — worse
    # than the crash its sibling script produced, because nothing signals it.
    load_dotenv()

    engine = make_engine()
    Base.metadata.create_all(engine)
    session = session_factory()()
    if seed_if_empty(session):
        print("Base Velmo peuplée (catalogue, clients, commandes).")
    else:
        print("Base déjà peuplée — rien à faire.")


if __name__ == "__main__":
    main()
