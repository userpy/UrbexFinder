"""Add opaque public links for read-only itinerary sharing."""
from alembic import op
import sqlalchemy as sa

revision = "20261114_0009"
down_revision = "web_012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("web_itineraries", sa.Column("share_token", sa.String(64), nullable=True))
    op.create_index(
        "web_itineraries_share_token_key",
        "web_itineraries",
        ["share_token"],
        unique=True,
    )


def downgrade():
    op.drop_index("web_itineraries_share_token_key", table_name="web_itineraries")
    op.drop_column("web_itineraries", "share_token")
