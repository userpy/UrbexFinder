"""Main entry point for telegram bot."""

import asyncio
from contextlib import AsyncExitStack

from aiogram import Bot, Dispatcher

from infrastructure.core.logger_config import setup_logger
from infrastructure.core.settings import get_app_settings
from infrastructure.db.EasticSearch import ElasticPlacesIndexer
from infrastructure.db.PgDb import AsyncDatabase
from infrastructure.messaging.rabbitmq.producer import publish_message
from infrastructure.telegram.webhook import delete_webhook_with_retry
from interface.handlers import help, places, places_social, resources, start
from interface.middleware.db_middleware import DBMiddleware
from interface.middleware.elastic_middleware import ElasticMiddleware

logger = setup_logger()


async def main() -> None:
    """Initialize and run the telegram bot."""
    settings = get_app_settings()

    async with AsyncExitStack() as stack:
        bot = Bot(token=settings.token)
        stack.push_async_callback(bot.session.close)

        db = AsyncDatabase(
            user_admin_name=settings.admin_name,
            user_admin_id=settings.admin_id,
            pg_user=settings.postgres_user,
            pg_password=settings.postgres_password,
            pg_database=settings.postgres_db,
            pg_host=settings.postgres_host,
            pg_port=settings.postgres_port,
        )
        stack.push_async_callback(db.close)
        await db.connect()

        elastic = ElasticPlacesIndexer(
            db=db,
            es_url=settings.elasticsearch_host,
            es_user=settings.elasticsearch_user,
            es_password=settings.elasticsearch_password,
        )
        stack.push_async_callback(elastic.close)

        dp = Dispatcher()
        dp.update.middleware(DBMiddleware(db))
        dp.update.middleware(ElasticMiddleware(elastic))
        dp.include_routers(
            places.router,
            places_social.router,
            help.router,
            start.router,
            resources.router,
        )

        await delete_webhook_with_retry(bot)

        if settings.enqueue_places_sync_on_startup:
            await publish_message(
                exchange_name="bot.commands.exchange",
                routing_key="places.bootstrap.requested",
                message={"seed_places": settings.seed_places},
            )
        else:
            logger.info(
                "RabbitMQ startup producer is disabled "
                "(ENQUEUE_PLACES_SYNC_ON_STARTUP=false).",
            )

        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
