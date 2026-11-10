"""Assign explicit defaults once, preserving manually selected category icons."""
from alembic import op

revision = 'web_011'
down_revision = 'web_010'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE web_categories
        SET icon = CASE lower(trim(name))
            WHEN 'промышленность' THEN 'industry'
            WHEN 'архитектура' THEN 'architecture'
            WHEN 'инфраструктура' THEN 'infrastructure'
            WHEN 'дом культуры' THEN 'culture'
            WHEN 'военное' THEN 'military'
            WHEN 'школы/колледжи/институты' THEN 'school'
            WHEN 'geocaching' THEN 'geocache'
            WHEN 'бомбоубежища' THEN 'shelter'
            WHEN 'заброшенные пионерские лагеря' THEN 'camp'
            WHEN 'красивые природные места' THEN 'nature'
            WHEN 'церкви' THEN 'church'
            WHEN 'заброшенное технологическое' THEN 'industry'
            WHEN 'заброшенные усадьбы,дома отдыха,санатории' THEN 'estate'
            ELSE 'other'
        END
        WHERE icon IS NULL OR trim(icon) = ''
    """)


def downgrade():
    # Keep saved icons: they may have been edited since the migration ran.
    pass
