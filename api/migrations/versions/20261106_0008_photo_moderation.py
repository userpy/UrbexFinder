"""Keep existing Telegram photos public; queue newly submitted photos."""
from alembic import op
revision = '20261106_0008'
down_revision = '20261106_0007'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE place_photos ADD COLUMN status varchar(30) NOT NULL DEFAULT 'pending', ADD COLUMN reason text NOT NULL DEFAULT ''")
    op.execute("UPDATE place_photos SET status='published'")
    op.execute("ALTER TABLE place_photos ADD CONSTRAINT place_photos_status_check CHECK(status IN ('pending','published','rejected','changes_requested'))")


def downgrade():
    raise RuntimeError('Restore a coordinated backup to preserve photo moderation states')
