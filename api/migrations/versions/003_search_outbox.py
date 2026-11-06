"""Durable search updates from both services, including direct SQL changes."""
from alembic import op
revision = 'web_003'
down_revision = 'web_002'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE SEQUENCE web_search_revision')
    op.execute("CREATE TABLE web_search_outbox (place_id integer PRIMARY KEY, revision bigint NOT NULL DEFAULT nextval('web_search_revision'))")
    op.execute("""CREATE FUNCTION enqueue_place_search() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE place integer;
    BEGIN
      IF TG_OP='DELETE' THEN place := OLD.id; ELSE place := NEW.id; END IF;
      INSERT INTO web_search_outbox(place_id) VALUES (place)
        ON CONFLICT(place_id) DO UPDATE SET revision=nextval('web_search_revision');
      RETURN NULL;
    END $$""")
    op.execute('CREATE TRIGGER places_search_queue AFTER INSERT OR UPDATE OR DELETE ON places FOR EACH ROW EXECUTE FUNCTION enqueue_place_search()')
    op.execute('INSERT INTO web_search_outbox(place_id) SELECT id FROM places')


def downgrade():
    op.execute('DROP TRIGGER places_search_queue ON places')
    op.execute('DROP FUNCTION enqueue_place_search()')
    op.execute('DROP TABLE web_search_outbox')
    op.execute('DROP SEQUENCE web_search_revision')
