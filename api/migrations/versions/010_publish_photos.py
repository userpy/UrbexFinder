"""Temporarily publish uploads without prior photo moderation."""
from alembic import op

revision = 'web_010'
down_revision = 'web_009'
branch_labels = None
depends_on = None


def upgrade():
    for table in ('web_photos', 'place_photos'):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN status SET DEFAULT 'published'")
        op.execute(f"UPDATE {table} SET status='published', reason='' WHERE status='pending'")


def downgrade():
    for table in ('web_photos', 'place_photos'):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN status SET DEFAULT 'pending'")
    # Existing published photos retain their visibility.
