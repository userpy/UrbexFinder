"""Main entry point for telegram bot."""

import asyncio
import os

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from infrastructure.core.logger_config import setup_logger
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

logger = setup_logger()
load_dotenv()
TOKEN = os.getenv("TOKEN")
ADMIN_NAME = os.getenv("ADMIN_NAME")
ADMIN_ID = os.getenv("ADMIN_ID")
KMZ_PATH = os.getenv("KMZ_PATH")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_PORT = os.getenv("POSTGRES_PORT")

async def main() -> None:
    """Initialize and run the telegram bot."""
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    db = AsyncDatabase(
        user_admin_name=ADMIN_NAME,
        user_admin_id=ADMIN_ID,
        pg_user=POSTGRES_USER,
        pg_password=POSTGRES_PASSWORD,
        pg_database=POSTGRES_DB,
        pg_host=POSTGRES_HOST,
        pg_port=POSTGRES_PORT,
    )
    await db.connect()
    elastic = ElasticPlacesIndexer(db=db)
    event_bus = EventBus()
    register_event_subscribers(event_bus)
    dp.update.middleware(DBMiddleware(db))
    dp.update.middleware(ElasticMiddleware(elastic))
    dp.update.middleware(EventBusMiddleware(event_bus))
    await seed_places_from_kml(db, KMZ_PATH)
    await deduplicate_places(db)
    await update_place_full_addres(db)
    await indexing_places_elastic_search(elastic)
    dp.include_routers(
        places.router,
        places_social.router,
        help.router,
        start.router,
        resources.router,
    )
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Bot start")
        await dp.start_polling(bot)
    finally:
        # Закрываем базу и сессию бота при остановке
        await db.close()
        await bot.session.close()
        await elastic.close()

if __name__ == "__main__":
    asyncio.run(main())
