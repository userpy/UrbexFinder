"""Browser-bound Telegram login approvals."""
from alembic import op
revision='web_005'
down_revision='web_004'
branch_labels=None
depends_on=None

def upgrade():
    op.execute('ALTER TABLE web_users ALTER COLUMN email DROP NOT NULL')
    op.execute('ALTER TABLE web_users ADD COLUMN telegram_id bigint UNIQUE')
    op.execute('''CREATE TABLE web_telegram_logins (
        id serial PRIMARY KEY, browser_hash varchar(64) UNIQUE NOT NULL,
        link_hash varchar(64) UNIQUE NOT NULL, code varchar(6) NOT NULL,
        telegram_id bigint, display_name varchar(100), confirmed boolean NOT NULL DEFAULT false,
        consumed boolean NOT NULL DEFAULT false, expires_at timestamptz NOT NULL)''')
    op.execute('CREATE INDEX web_telegram_login_expiry ON web_telegram_logins(expires_at)')

def downgrade():
    raise RuntimeError('Restore a backup instead of removing identities')
