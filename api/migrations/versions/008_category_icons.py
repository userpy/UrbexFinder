from alembic import op
revision = 'web_008'
down_revision = 'web_007'
branch_labels = None
depends_on = None

def upgrade():
    op.execute('ALTER TABLE web_categories ADD COLUMN icon varchar(32)')

def downgrade():
    op.execute('ALTER TABLE web_categories DROP COLUMN icon')
