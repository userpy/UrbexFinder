from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from sqlalchemy import text

BOT_ROOT = Path(__file__).resolve().parents[1]
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

from infrastructure.db.PgDb import AsyncDatabase


@pytest_asyncio.fixture
async def database() -> AsyncIterator[AsyncDatabase]:
    """Return a database connected only to the isolated test PostgreSQL."""
    database = AsyncDatabase(
        pg_user=os.environ.get("POSTGRES_USER", "test"),
        pg_password=os.environ.get("POSTGRES_PASSWORD", "test"),
        pg_database=os.environ.get("POSTGRES_DB", "telegram_bot_test"),
        pg_host=os.environ.get("POSTGRES_HOST", "test-db"),
        pg_port=int(os.environ.get("POSTGRES_PORT", "5432")),
    )
    await database.connect()

    assert database.engine is not None
    async with database.engine.begin() as connection:
        await connection.execute(
            text(
                """
                TRUNCATE TABLE
                    place_nonexistent_reports,
                    place_ratings,
                    place_reviews,
                    place_photos,
                    places,
                    resources,
                    users
                RESTART IDENTITY CASCADE
                """
            )
        )

    try:
        yield database
    finally:
        await database.close()
