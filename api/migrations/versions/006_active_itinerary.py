"""One active itinerary per account."""
from alembic import op
revision = 'web_006'
down_revision = 'web_005'
branch_labels = None
depends_on = None

def upgrade():
    op.execute('ALTER TABLE web_itineraries ADD COLUMN active boolean NOT NULL DEFAULT false')
    op.execute('CREATE UNIQUE INDEX web_itineraries_one_active ON web_itineraries(author_id) WHERE active')

def downgrade():
    op.execute('DROP INDEX web_itineraries_one_active')
    op.execute('ALTER TABLE web_itineraries DROP COLUMN active')
