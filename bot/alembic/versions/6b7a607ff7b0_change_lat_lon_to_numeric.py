"""change lat lon to numeric

Revision ID: 6b7a607ff7b0
Revises: 43e0006c05eb
Create Date: 2026-02-16 16:42:50.921344
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6b7a607ff7b0"
down_revision: Union[str, Sequence[str], None] = "43e0006c05eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.alter_column(
        "places",
        "latitude",
        type_=sa.REAL,
        postgresql_using="latitude::real",
    )
    op.alter_column(
        "places",
        "longitude",
        type_=sa.REAL,
        postgresql_using="longitude::real",
    )