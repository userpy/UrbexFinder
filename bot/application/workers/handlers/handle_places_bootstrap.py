"""Обработчик команды стартового заполнения и индексации мест."""

from __future__ import annotations

from typing import Any

from loguru import logger

from application.startup.on_startup_places import (
    deduplicate_places,
    indexing_places_elastic_search,
    seed_places_from_kml,
    update_place_full_addres,
)
from infrastructure.core.settings import AppSettings
from infrastructure.db.EasticSearch import ElasticPlacesIndexer
from infrastructure.db.PgDb import AsyncDatabase
from infrastructure.messaging.rabbitmq.constants import (
    PLACES_BOOTSTRAP_ROUTING_KEY,
)


async def handle_places_bootstrap(
    message: dict[str, Any],
    routing_key: str,
    *,
    settings: AppSettings,
) -> None:
    """Выполнить команду синхронизации мест."""
    if routing_key != PLACES_BOOTSTRAP_ROUTING_KEY:
        raise ValueError(f"Unsupported routing key: {routing_key!r}.")

    should_seed_places = message.get(
        "seed_places",
        settings.seed_places,
    )
    if not isinstance(should_seed_places, bool):
        raise ValueError("seed_places must be a boolean.")

    logger.info(
        "Places bootstrap started: routing_key='{}', seed_places={}.",
        routing_key,
        should_seed_places,
    )

    db = AsyncDatabase(
        user_admin_name=settings.admin_name,
        user_admin_id=settings.admin_id,
        pg_user=settings.postgres_user,
        pg_password=settings.postgres_password,
        pg_database=settings.postgres_db,
        pg_host=settings.postgres_host,
        pg_port=settings.postgres_port,
    )
    await db.connect()

    try:
        indexer = ElasticPlacesIndexer(
            db=db,
            es_url=settings.elastic_url,
            es_user=settings.elastic_user,
            es_password=settings.elastic_password,
        )

        try:
            await seed_places_from_kml(
                db,
                settings.kmz_path,
                should_seed_places,
            )
            await deduplicate_places(db)
            await update_place_full_addres(db, settings.csv_path)
            await indexing_places_elastic_search(
                indexer,
                close_indexer=False,
            )
        finally:
            await indexer.close()
    finally:
        await db.close()

    logger.info("Places bootstrap completed: routing_key='{}'.", routing_key)
