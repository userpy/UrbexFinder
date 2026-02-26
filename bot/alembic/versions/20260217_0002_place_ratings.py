"""add place ratings

Revision ID: 20260217_0002
Revises: 42c59f385923
Create Date: 2026-02-17 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260217_0002"
down_revision: Union[str, Sequence[str], None] = "42c59f385923"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "places",
        sa.Column("rating_avg", sa.Numeric(precision=3, scale=2), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "places",
        sa.Column("rating_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "places",
        sa.Column("rating_score", sa.Numeric(precision=5, scale=3), nullable=False, server_default=sa.text("0")),
    )

    op.create_table(
        "place_ratings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("place_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_place_ratings_score_range"),
        sa.ForeignKeyConstraint(["place_id"], ["places.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("place_id", "user_id", name="uq_place_ratings_place_user"),
    )


def downgrade() -> None:
    op.drop_table("place_ratings")
    op.drop_column("places", "rating_score")
    op.drop_column("places", "rating_count")
    op.drop_column("places", "rating_avg")
