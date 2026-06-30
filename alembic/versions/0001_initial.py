"""Schéma initial Velmo 2.0.

Revision ID: 0001_initial
Revises:
Create Date: 2024-05-01
"""

from __future__ import annotations

from alembic import op

from velmo.db import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Schéma initial : créé directement depuis les modèles SQLAlchemy
    # (source de vérité unique pour catalogue, commandes, retours, remboursements).
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
