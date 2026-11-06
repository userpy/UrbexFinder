"""Personal itineraries and moderation of shared Telegram reviews."""
from alembic import op
revision='web_004'
down_revision='web_003'
branch_labels=None
depends_on=None

def upgrade():
    op.execute("""CREATE TABLE web_itineraries (
        id serial PRIMARY KEY, author_id integer NOT NULL REFERENCES web_users(id),
        name varchar(120) NOT NULL, trip_date date, notes text NOT NULL DEFAULT '',
        stops jsonb NOT NULL DEFAULT '[]', version integer NOT NULL DEFAULT 1,
        created_at timestamptz NOT NULL DEFAULT now())""")
    op.execute('CREATE INDEX web_itineraries_owner_idx ON web_itineraries(author_id,id)')
    op.execute("ALTER TABLE place_reviews ADD COLUMN status varchar(30) NOT NULL DEFAULT 'published', ADD COLUMN reason text NOT NULL DEFAULT ''")

def downgrade():
    raise RuntimeError('Restore from a verified backup instead of deleting route data')
