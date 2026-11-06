from alembic import op
revision='web_007'
down_revision='web_006'
branch_labels=None
depends_on=None

def upgrade():
    op.execute('ALTER TABLE web_users ADD COLUMN deleted boolean NOT NULL DEFAULT false')

def downgrade():
    op.execute('ALTER TABLE web_users DROP COLUMN deleted')
