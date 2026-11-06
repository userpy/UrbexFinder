"""Add explicit moderation and website fields to the existing catalog."""
from alembic import op

revision = "20261106_0007"
down_revision = "20260726_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""ALTER TABLE places
        ADD COLUMN region varchar(200) NOT NULL DEFAULT 'Не указан',
        ADD COLUMN category_id integer,
        ADD COLUMN condition varchar(30) NOT NULL DEFAULT 'unknown',
        ADD COLUMN access text NOT NULL DEFAULT 'Сведения о доступе не подтверждены',
        ADD COLUMN author_id integer,
        ADD COLUMN telegram_author_id bigint,
        ADD COLUMN status varchar(30) NOT NULL DEFAULT 'pending',
        ADD COLUMN reason text NOT NULL DEFAULT '',
        ADD COLUMN created_at timestamptz NOT NULL DEFAULT now(),
        ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now()""")
    # The old bot has no approval status. Its public catalog is exactly the
    # records below the reports threshold; preserve that visibility explicitly.
    op.execute("""UPDATE places SET
        status = CASE WHEN nonexistent_reports_count < 10 THEN 'published' ELSE 'rejected' END,
        region = COALESCE(NULLIF(left(full_address,200),''),'Не указан')""")
    op.execute("""ALTER TABLE places ADD CONSTRAINT places_status_check
        CHECK (status IN ('pending','published','rejected','changes_requested'))""")


def downgrade():
    raise RuntimeError('Shared catalog rollback requires restoring a coordinated database backup; see URBEXFINDER.md')
