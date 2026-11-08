"""Publish committed photo events; retain them when RabbitMQ is unavailable."""
import asyncio

from loguru import logger
from sqlalchemy import text

from infrastructure.db.PgDb import AsyncDatabase
from infrastructure.messaging.rabbitmq.constants import EXCHANGE_NAME
from infrastructure.messaging.rabbitmq.producer import publish_message


async def publish_pending_photo_events(session_factory):
    # Lock one event per transaction, allowing multiple worker instances.
    for _ in range(100):
        async with session_factory() as session:
            async with session.begin():
                result = await session.execute(text(
                    "SELECT id, routing_key, payload FROM photo_event_outbox "
                    "ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
                ))
                event = result.mappings().first()
                if event is None:
                    return
                await publish_message(
                    exchange_name=EXCHANGE_NAME,
                    routing_key=event['routing_key'],
                    message=event['payload'],
                )
                # Publisher confirms arrive before removal. A crash can cause
                # redelivery; deleting the same S3 key again is safe.
                await session.execute(text(
                    "DELETE FROM photo_event_outbox WHERE id=:id"
                ), {'id': event['id']})


async def relay_photo_events(settings):
    db = AsyncDatabase(
        pg_user=settings.postgres_user, pg_password=settings.postgres_password,
        pg_database=settings.postgres_db, pg_host=settings.postgres_host,
        pg_port=settings.postgres_port,
    )
    try:
        await db.connect()
        while True:
            try:
                await publish_pending_photo_events(db.async_session)
            except Exception:
                logger.exception('Photo event publishing failed; retrying in 5 seconds')
            await asyncio.sleep(5)
    finally:
        await db.close()
