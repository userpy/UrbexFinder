"""Persist photo deletion events in the photo transaction."""
from alembic import op

revision = 'web_009'
down_revision = 'web_008'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE photo_event_outbox (
        id bigserial PRIMARY KEY,
        routing_key text NOT NULL,
        payload jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now()
    )""")


def downgrade():
    op.execute('DROP TABLE photo_event_outbox')
