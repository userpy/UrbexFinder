"""Main entry point for telegram bot."""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from aiogram import Bot, Dispatcher

from infrastructure.core.logger_config import setup_logger
from infrastructure.core.settings import get_app_settings
from infrastructure.db.EasticSearch import ElasticPlacesIndexer
from infrastructure.db.PgDb import AsyncDatabase
from infrastructure.messaging.rabbitmq.producer import publish_message
from interface.handlers import help, places, places_social, resources, start
from interface.middleware.db_middleware import DBMiddleware
from interface.middleware.elastic_middleware import ElasticMiddleware

logger = setup_logger()


async def main() -> None:
    """Initialize and run the telegram bot."""
    settings = get_app_settings()
    bot = Bot(token=settings.token)
    dp = Dispatcher()

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

    elastic = ElasticPlacesIndexer(
        db=db,
        es_url=settings.elastic_url,
        es_user=settings.elastic_user,
        es_password=settings.elastic_password,
    )
    dp.update.middleware(DBMiddleware(db))
    dp.update.middleware(ElasticMiddleware(elastic))

    routers = [
        places.router,
        places_social.router,
        help.router,
        start.router,
        resources.router,
    ]
    dp.include_routers(*routers)

    try:
        await bot.delete_webhook(drop_pending_updates=True)

        if settings.enqueue_places_sync_on_startup:
            await publish_message(
                exchange_name=settings.rabbitmq_exchange,
                routing_key=settings.rabbitmq_startup_routing_key,
                message={"seed_places": settings.seed_places},
            )
        else:
            logger.info(
                "RabbitMQ startup producer is disabled "
                "(ENQUEUE_PLACES_SYNC_ON_STARTUP=false).",
            )

        await dp.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()
        await elastic.close()


if __name__ == "__main__":
    asyncio.run(main())
