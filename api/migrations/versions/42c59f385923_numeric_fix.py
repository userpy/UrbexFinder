"""numeric fix

Revision ID: 42c59f385923
Revises: 6b7a607ff7b0
Create Date: 2026-02-16 20:43:00.257356
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "42c59f385923"
down_revision: Union[str, Sequence[str], None] = "6b7a607ff7b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "places",
        "latitude",
        type_=sa.Numeric(10, 6),
        postgresql_using="latitude::numeric",
    )
    op.alter_column(
        "places",
        "longitude",
        type_=sa.Numeric(10, 6),
        postgresql_using="longitude::numeric",
    )


def downgrade() -> None:
    op.alter_column(
        "places",
        "latitude",
        type_=sa.Numeric(10, 7),
        postgresql_using="latitude::numeric",
    )
    op.alter_column(
        "places",
        "longitude",
        type_=sa.Numeric(10, 7),
        postgresql_using="longitude::numeric",
    )
