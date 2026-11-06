"""Exercise upgrade from populated pre-website bot and legacy web databases."""
import subprocess
from sqlalchemy import create_engine, text
from urbex.bootstrap.config import Settings

config = Settings()
assert config.environment == 'test' and config.database_url.endswith('/urbex_test')
engine = create_engine(config.database_url)
with engine.begin() as c:
    # Reproduce a deployed bot database with its original Alembic table.
    c.execute(text('ALTER TABLE web_alembic_version RENAME TO alembic_version'))
    c.execute(text("INSERT INTO roles(id,name) VALUES (9001,'compatibility')"))
    c.execute(text("INSERT INTO users(name,user_id,role_id) VALUES ('Sentinel',9876543210123,9001)"))
    c.execute(text("""INSERT INTO places(id,name,description,latitude,longitude,full_address,nonexistent_reports_count)
        VALUES (41,'Legacy sentinel','Existing bot record',55.75,37.62,'Москва',0),
               (42,'Hidden sentinel','Hidden bot record',55.76,37.63,'Москва',10)"""))
    c.execute(text("INSERT INTO place_photos(place_id,user_id,file_id) VALUES (41,9876543210123,'preserved-file-id')"))
    before = c.execute(text('SELECT id,name,description,latitude,longitude FROM places ORDER BY id')).all()
subprocess.run(['alembic','upgrade','web_001'],check=True)
with engine.begin() as c:
    c.execute(text("INSERT INTO web_users(id,email,name,password_hash) VALUES (1,'old@example.com','Old author','unused')"))
    c.execute(text("""INSERT INTO web_places(id,legacy_place_id,name,description,latitude,longitude,region,category_id,status,author_id)
        VALUES (1,41,'Imported editorial copy','Old copy',55.75,37.62,'Москва',1,'pending',1),
               (2,NULL,'Website original','Web record',55.77,37.64,'Москва',1,'published',1),
               (3,999,'Orphan import','Source removed',55.78,37.65,'Москва',1,'pending',1)"""))
    c.execute(text("INSERT INTO web_photos(place_id,author_id,object_key) VALUES (1,1,'preserved.jpg')"))
    c.execute(text("INSERT INTO web_reviews(place_id,author_id,text,score) VALUES (1,1,'Keep review',4)"))
    c.execute(text("INSERT INTO web_favorites(place_id,user_id) VALUES (1,1),(2,1)"))
    c.execute(text("INSERT INTO web_reports(author_id,target_type,target_id,text) VALUES (1,'places',1,'Keep report')"))
    c.execute(text("INSERT INTO web_audit(actor_id,action,target,detail) VALUES (1,'published','places:1','Keep history')"))
# Legacy and website migrations now share the API chain.
subprocess.run(['alembic','upgrade','head'],check=True)
subprocess.run(['alembic','upgrade','head'],check=True)
with engine.connect() as c:
    assert c.execute(text('SELECT id,name,description,latitude,longitude FROM places WHERE id IN (41,42) ORDER BY id')).all() == before
    assert c.scalar(text('SELECT count(*) FROM places')) == 4
    assert c.scalar(text("SELECT status FROM places WHERE id=41")) == 'published'
    assert c.scalar(text("SELECT status FROM places WHERE id=42")) == 'rejected'
    assert c.scalar(text('SELECT author_id FROM places WHERE id=41')) == 1
    assert c.scalar(text('SELECT count(*) FROM web_places_archive')) == 3
    assert c.scalar(text('SELECT count(*) FROM web_place_id_map')) == 3
    assert c.scalar(text('SELECT place_id FROM web_photos')) == 41
    assert c.scalar(text('SELECT place_id FROM web_reviews')) == 41
    assert c.scalar(text('SELECT target_id FROM web_reports')) == 41
    assert c.scalar(text('SELECT target FROM web_audit')) == 'places:41'
    assert c.scalar(text('SELECT count(*) FROM web_favorites')) == 2
    assert c.scalar(text('SELECT file_id FROM place_photos')) == 'preserved-file-id'
    assert c.scalar(text('SELECT user_id FROM users')) == 9876543210123
    assert c.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_name='web_places'")) == 0
print('PASS: legacy visibility, IDs, bigint users, authors, Telegram/S3 photos, reviews, favorites, reports, audit and orphan imports preserved; repeated upgrade is idempotent')
