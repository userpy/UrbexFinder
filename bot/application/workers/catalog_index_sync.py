"""Refresh search after changes from either interface, including moderation."""
import asyncio
from loguru import logger
from infrastructure.db.PgDb import AsyncDatabase
from infrastructure.db.EasticSearch import ElasticPlacesIndexer


async def sync_catalog_index(settings):
    db = AsyncDatabase(pg_user=settings.postgres_user, pg_password=settings.postgres_password,
                       pg_database=settings.postgres_db, pg_host=settings.postgres_host,
                       pg_port=settings.postgres_port)
    indexer = ElasticPlacesIndexer(db=db, es_url=settings.elasticsearch_host,
                                  es_user=settings.elasticsearch_user,
                                  es_password=settings.elasticsearch_password)
    try:
        await db.connect()
        while True:
            try:
                await indexer.reindex()
            except Exception:
                logger.warning('Catalog index refresh failed; will retry in 60 seconds')
            await asyncio.sleep(60)
    finally:
        await indexer.close()
        await db.close()
