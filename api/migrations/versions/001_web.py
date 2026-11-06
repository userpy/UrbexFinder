"""Add website tables and spatial indexes without changing Telegram records."""
from alembic import op
from sqlalchemy import text
from migrations.legacy_web_models import Base

revision = 'web_001'
down_revision = '20261106_0008'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS postgis')
    Base.metadata.create_all(op.get_bind())
    op.execute("ALTER TABLE web_users ADD CONSTRAINT web_user_role CHECK (role IN ('user','moderator','admin'))")
    op.execute("ALTER TABLE web_places ADD CONSTRAINT web_coordinates CHECK (latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)")
    op.execute("ALTER TABLE web_places ADD COLUMN geom geometry(Point,4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude,latitude),4326)) STORED")
    op.execute('CREATE INDEX web_places_geom_idx ON web_places USING gist(geom)')
    op.execute('CREATE INDEX web_places_geography_idx ON web_places USING gist((geom::geography))')
    op.execute("CREATE INDEX web_places_search_idx ON web_places USING gin(to_tsvector('simple', name || ' ' || description))")
    op.execute('CREATE INDEX web_places_status_idx ON web_places(status, id)')
    op.execute('CREATE TABLE web_login_attempts (key text PRIMARY KEY, attempts integer NOT NULL, expires_at timestamptz NOT NULL)')
    op.execute("INSERT INTO web_categories(name) VALUES ('Промышленность'), ('Архитектура'), ('Инфраструктура'), ('Другое')")


def downgrade():
    # Explicit rollback removes only website data, never Telegram tables/PostGIS extension.
    op.execute('DROP TABLE web_login_attempts')
    Base.metadata.drop_all(op.get_bind())
