"""Exercise gallery SQL in temporary tables, without changing stored photos."""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from infrastructure.repository.places import PlacesRepository


pytestmark = pytest.mark.integration


async def check_unified_gallery(engine):
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            statements = [
                "CREATE TEMP TABLE places (id integer, status text, nonexistent_reports_count integer)",
                "CREATE TEMP TABLE web_users (id integer, telegram_id bigint, name text)",
                "CREATE TEMP TABLE place_photos (id integer, place_id integer, user_id bigint, user_name text, file_id text, caption text, created_at timestamp, status text)",
                "CREATE TEMP TABLE web_photos (id integer, place_id integer, author_id integer, object_key text, created_at timestamp, status text)",
                "INSERT INTO places VALUES (1, 'published', 0), (2, 'pending', 0)",
                "INSERT INTO web_users VALUES (1, NULL, 'Website author')",
                "INSERT INTO place_photos VALUES (1, 1, 100, 'Telegram author', 'tg-file', 'caption', '2026-01-01', 'published')",
                "INSERT INTO web_photos VALUES (1, 1, 1, 'photos/site.jpg', '2026-01-02', 'published'), (2, 1, 1, 'photos/pending.jpg', '2026-01-03', 'pending'), (3, 1, 1, 'photos/deleted.jpg', '2026-01-04', 'rejected'), (4, 2, 1, 'photos/hidden.jpg', '2026-01-05', 'published')",
            ]
            for statement in statements:
                await connection.execute(text(statement))
            repo = PlacesRepository(async_sessionmaker(bind=connection))
            assert await repo.get_place_photos_count(1) == 2
            page = await repo.get_photos_page(1)
            assert page['total'] == 2
            assert page['items'][0]['object_key'] == 'photos/site.jpg'
            assert page['items'][0]['user_name'] == 'Website author'
            assert page['items'][0]['id'] == -1
            assert (await repo.get_photos_page(1, offset=1))['items'][0]['file_id'] == 'tg-file'
            assert len(await repo.get_recent_photos(1)) == 2
            assert await repo.get_place_photos_count(2) == 0
            await connection.execute(text("UPDATE web_photos SET status='rejected' WHERE id=1"))
            assert await repo.get_place_photos_count(1) == 1
            await connection.execute(text('UPDATE places SET nonexistent_reports_count=10 WHERE id=1'))
            assert await repo.get_place_photos_count(1) == 0
        finally:
            await transaction.rollback()


async def test_unified_gallery(database):
    await check_unified_gallery(database.engine)
