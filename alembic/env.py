"""Environnement Alembic — cible le schéma SQLAlchemy de Velmo."""

from __future__ import annotations

import os

from alembic import context

from velmo.db import Base, make_engine

config = context.config
target_metadata = Base.metadata


def run_migrations_online() -> None:
    connectable = make_engine(os.getenv("DB_URL"))
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    context.configure(url=os.getenv("DB_URL"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()
