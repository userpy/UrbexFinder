"""Assign defaults to categories imported after the initial icon backfill."""
from alembic import op

revision = 'web_012'
down_revision = 'web_011'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE FUNCTION web_category_default_icon(category_name text)
        RETURNS text LANGUAGE sql IMMUTABLE AS $$
            SELECT CASE lower(trim(category_name))
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
        $$
    """)
    op.execute("""
        UPDATE web_categories SET icon = web_category_default_icon(name)
        WHERE icon IS NULL OR trim(icon) = ''
    """)
    op.execute("""
        CREATE FUNCTION web_category_assign_icon()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.icon IS NULL OR trim(NEW.icon) = '' THEN
                NEW.icon := web_category_default_icon(NEW.name);
            END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER web_category_assign_icon
        BEFORE INSERT ON web_categories
        FOR EACH ROW EXECUTE FUNCTION web_category_assign_icon()
    """)


def downgrade():
    op.execute('DROP TRIGGER web_category_assign_icon ON web_categories')
    op.execute('DROP FUNCTION web_category_assign_icon()')
    op.execute('DROP FUNCTION web_category_default_icon(text)')
    # Preserve assigned and manually selected icons.
