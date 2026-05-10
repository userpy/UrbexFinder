"""Main entry point for telegram bot."""

import asyncio

from aiogram import Bot, Dispatcher

from infrastructure.core.logger_config import setup_logger
from infrastructure.core.settings import get_app_settings
from infrastructure.db.EasticSearch import ElasticPlacesIndexer
from infrastructure.db.PgDb import AsyncDatabase
from interface.handlers import help, places, places_social, resources, start
from interface.middleware.db_middleware import DBMiddleware
from interface.middleware.elastic_middleware import ElasticMiddleware
from interface.middleware.event_bus_middleware import EventBusMiddleware
from infrastructure.core.event_bus import EventBus
from application.event_subscribers import register_event_subscribers
from application.startup.on_startup_places import (
    deduplicate_places,
    indexing_places_elastic_search,
    seed_places_from_kml,
    update_place_full_addres,
)
from application.startup.make_migrations import make_migrations

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
    await make_migrations()
    await db.connect()
    elastic = ElasticPlacesIndexer(
        db=db,
        es_url=settings.elastic_url,
        es_user=settings.elastic_user,
        es_password=settings.elastic_password,
    )
    event_bus = EventBus()
    register_event_subscribers(event_bus)
    dp.update.middleware(DBMiddleware(db))
    dp.update.middleware(ElasticMiddleware(elastic))
    dp.update.middleware(EventBusMiddleware(event_bus))
    await seed_places_from_kml(db, settings.kmz_path, settings.seed_places)
    await deduplicate_places(db)
    await update_place_full_addres(db)
    await indexing_places_elastic_search(elastic)
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
        logger.info(F"Bot start {settings.seed_places}")
        await dp.start_polling(bot)
    finally:
        # Закрываем базу и сессию бота при остановке
        await db.close()
        await bot.session.close()
        await elastic.close()

if __name__ == "__main__":
    asyncio.run(main())
