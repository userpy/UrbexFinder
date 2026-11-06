"""Converge the website projection into the existing bot catalog atomically."""
from alembic import op
from sqlalchemy import inspect, text

revision = 'web_002'
down_revision = 'web_001'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if 'places' not in inspect(connection).get_table_names() or 'status' not in {
        c['name'] for c in inspect(connection).get_columns('places')
    }:
        raise RuntimeError('Run bot Alembic upgrade head before website migrations')
    op.execute('LOCK TABLE places, web_places IN ACCESS EXCLUSIVE MODE')
    op.execute("INSERT INTO web_categories(name) SELECT DISTINCT category FROM places WHERE category IS NOT NULL AND category <> '' ON CONFLICT(name) DO NOTHING")
    op.execute("""UPDATE places p SET category_id = COALESCE(
        (SELECT id FROM web_categories WHERE name=p.category),
        (SELECT id FROM web_categories WHERE name='Другое')) WHERE category_id IS NULL""")
    op.execute('CREATE TABLE web_place_id_map (old_id integer PRIMARY KEY, place_id integer NOT NULL REFERENCES places(id))')
    op.execute("SELECT setval(pg_get_serial_sequence('places','id'), GREATEST(COALESCE((SELECT max(id) FROM places),0),1), EXISTS(SELECT 1 FROM places))")
    rows = connection.execute(text('SELECT * FROM web_places ORDER BY id')).mappings().all()
    for row in rows:
        target = connection.scalar(text('SELECT id FROM places WHERE id=:id'), {'id': row['legacy_place_id']}) if row['legacy_place_id'] else None
        if target is None:
            fields = ('name','description','latitude','longitude','region','category_id','condition','access','author_id','status','reason','created_at','updated_at')
            target = connection.scalar(text('INSERT INTO places ('+','.join(fields)+') VALUES ('+','.join(':'+f for f in fields)+') RETURNING id'), dict(row))
        else:
            connection.execute(text('UPDATE places SET author_id=COALESCE(author_id,:author) WHERE id=:id'), {'author': row['author_id'], 'id': target})
        # Existing bot records retain their canonical content and publication state.
        # The old editorial version, including its author and history, is archived.
        connection.execute(text('INSERT INTO web_place_id_map VALUES (:old,:new)'), {'old': row['id'], 'new': target})
    for table in ('web_photos', 'web_reviews', 'web_favorites'):
        for fk in inspect(connection).get_foreign_keys(table):
            if fk['referred_table'] == 'web_places':
                op.drop_constraint(fk['name'], table, type_='foreignkey')
        op.execute(f'UPDATE {table} t SET place_id=m.place_id FROM web_place_id_map m WHERE t.place_id=m.old_id')
        op.create_foreign_key(table+'_catalog_fk', table, 'places', ['place_id'], ['id'])
    op.execute("UPDATE web_reports t SET target_id=m.place_id FROM web_place_id_map m WHERE t.target_type='places' AND t.target_id=m.old_id")
    op.execute("UPDATE web_audit t SET target='places:' || m.place_id FROM web_place_id_map m WHERE t.target='places:' || m.old_id")
    op.execute('ALTER TABLE web_places RENAME TO web_places_archive')
    op.execute("""CREATE FUNCTION protect_catalog_archive() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Catalog migration archive is read only'; END $$""")
    op.execute('CREATE TRIGGER archive_read_only BEFORE INSERT OR UPDATE OR DELETE ON web_places_archive FOR EACH STATEMENT EXECUTE FUNCTION protect_catalog_archive()')
    op.create_foreign_key('places_web_author_fk','places','web_users',['author_id'],['id'])
    op.create_foreign_key('places_category_fk','places','web_categories',['category_id'],['id'])
    op.execute('ALTER TABLE places ADD COLUMN geom geometry(Point,4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude::double precision,latitude::double precision),4326)) STORED')
    op.execute('CREATE INDEX places_geom_idx ON places USING gist(geom)')
    op.execute('CREATE INDEX places_geography_idx ON places USING gist((geom::geography))')
    op.execute("CREATE INDEX places_search_idx ON places USING gin(to_tsvector('simple', name || ' ' || coalesce(description,'')))")
    op.execute('CREATE INDEX places_status_idx ON places(status,id)')
    # New bot inserts receive a website category, without depending on web code.
    op.execute("""CREATE FUNCTION catalog_defaults() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='UPDATE' AND NEW.category IS DISTINCT FROM OLD.category
              AND NEW.category_id IS NOT DISTINCT FROM OLD.category_id THEN
            NEW.category_id := NULL;
          END IF;
          IF NEW.category_id IS NULL THEN
            IF NULLIF(NEW.category,'') IS NOT NULL THEN
              INSERT INTO web_categories(name) VALUES (NEW.category) ON CONFLICT(name) DO NOTHING;
            END IF;
            NEW.category_id := (SELECT id FROM web_categories WHERE name=COALESCE(NEW.category,'Другое'));
            IF TG_OP='UPDATE' AND NEW.category IS DISTINCT FROM OLD.category
              AND NEW.category_id IS NOT DISTINCT FROM OLD.category_id THEN
            NEW.category_id := NULL;
          END IF;
          IF NEW.category_id IS NULL THEN
            IF NULLIF(NEW.category,'') IS NOT NULL THEN
              INSERT INTO web_categories(name) VALUES (NEW.category) ON CONFLICT(name) DO NOTHING;
            END IF;
              NEW.category_id := (SELECT id FROM web_categories WHERE name='Другое');
            END IF;
          END IF;
          NEW.category := (SELECT name FROM web_categories WHERE id=NEW.category_id);
          NEW.updated_at := now();
          RETURN NEW;
        END $$""")
    op.execute('CREATE TRIGGER places_defaults BEFORE INSERT OR UPDATE ON places FOR EACH ROW EXECUTE FUNCTION catalog_defaults()')

    op.execute("""CREATE FUNCTION catalog_category_rename() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          UPDATE places SET category=NEW.name WHERE category_id=NEW.id;
          RETURN NEW;
        END $$""")
    op.execute('CREATE TRIGGER catalog_category_rename AFTER UPDATE OF name ON web_categories FOR EACH ROW EXECUTE FUNCTION catalog_category_rename()')


def downgrade():
    raise RuntimeError('Restore coordinated backup to roll back the shared catalog; see URBEXFINDER.md')
