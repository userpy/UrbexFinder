"""add place nonexistent reports

Revision ID: 20260217_0005
Revises: 20260217_0004
Create Date: 2026-02-17 23:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260217_0005"
down_revision: Union[str, Sequence[str], None] = "20260217_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "places",
        sa.Column(
            "nonexistent_reports_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_index(
        "ix_places_nonexistent_reports_count",
        "places",
        ["nonexistent_reports_count"],
        unique=False,
    )
    op.create_table(
        "place_nonexistent_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("place_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["place_id"], ["places.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("place_id", "user_id", name="uq_place_nonexistent_reports_place_user"),
    )
    op.create_index(
        "ix_place_nonexistent_reports_place_id",
        "place_nonexistent_reports",
        ["place_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_place_nonexistent_reports_place_id", table_name="place_nonexistent_reports")
    op.drop_table("place_nonexistent_reports")
    op.drop_index("ix_places_nonexistent_reports_count", table_name="places")
    op.drop_column("places", "nonexistent_reports_count")
