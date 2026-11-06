"""Use bigint for Telegram user identifiers.

Revision ID: 20260726_0006
Revises: 20260217_0005
Create Date: 2026-07-26 08:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260726_0006"
down_revision: Union[str, Sequence[str], None] = "20260217_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_USER_ID_TABLES = (
    "users",
    "place_ratings",
    "place_reviews",
    "place_photos",
    "place_nonexistent_reports",
)


def upgrade() -> None:
    for table_name in _USER_ID_TABLES:
        op.alter_column(
            table_name,
            "user_id",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
            postgresql_using="user_id::bigint",
        )


def downgrade() -> None:
    for table_name in reversed(_USER_ID_TABLES):
        op.alter_column(
            table_name,
            "user_id",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
            postgresql_using="user_id::integer",
        )
