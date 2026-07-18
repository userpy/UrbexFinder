"""Worker стартового заполнения и индексации мест."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from application.startup.on_startup_places import (
    deduplicate_places,
    indexing_places_elastic_search,
    seed_places_from_kml,
    update_place_full_addres,
)
from infrastructure.core.logger_config import setup_logger
from infrastructure.core.settings import AppSettings, get_app_settings
from infrastructure.db.EasticSearch import ElasticPlacesIndexer
from infrastructure.db.PgDb import AsyncDatabase
from infrastructure.messaging.rabbitmq.consumer import (
    consume_topic as consume_rabbitmq_topic,
)


async def handle_places_bootstrap(
    message: dict[str, Any],
    routing_key: str,
    *,
    settings: AppSettings,
    db: AsyncDatabase,
    indexer: ElasticPlacesIndexer,
) -> None:
    """Выполнить команду синхронизации мест."""
    if routing_key != settings.rabbitmq_startup_routing_key:
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

    await seed_places_from_kml(
        db,
        settings.kmz_path,
        should_seed_places,
    )
    await deduplicate_places(db)
    await update_place_full_addres(db, settings.csv_path)
    await indexing_places_elastic_search(indexer, close_indexer=False)

    logger.info("Places bootstrap completed: routing_key='{}'.", routing_key)


async def consume_topic(
    *,
    settings: AppSettings,
    db: AsyncDatabase,
    indexer: ElasticPlacesIndexer,
) -> None:
    """Слушать topic стартового заполнения мест и запускать сидинг."""
    queue_name = settings.rabbitmq_startup_queue
    routing_key = settings.rabbitmq_startup_routing_key

    async def run_seeding(
        message: dict[str, Any],
        incoming_routing_key: str,
    ) -> None:
        if incoming_routing_key != routing_key:
            raise ValueError(
                f"Unsupported routing key: {incoming_routing_key!r}."
            )
        await handle_places_bootstrap(
            message,
            incoming_routing_key,
            settings=settings,
            db=db,
            indexer=indexer,
        )

    await consume_rabbitmq_topic(
        settings=settings,
        queue_name=queue_name,
        message_handler=run_seeding,
        prefetch_count=1,
    )


async def main() -> None:
    """Инициализировать зависимости и запустить consumer."""
    setup_logger()
    settings = get_app_settings()
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

    indexer = ElasticPlacesIndexer(
        db=db,
        es_url=settings.elastic_url,
        es_user=settings.elastic_user,
        es_password=settings.elastic_password,
    )

    try:
        await consume_topic(
            settings=settings,
            db=db,
            indexer=indexer,
        )
    finally:
        await indexer.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
