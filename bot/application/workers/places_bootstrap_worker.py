"""Worker стартового заполнения и индексации мест."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from application.workers.handlers.handle_places_bootstrap import (
    handle_places_bootstrap,
)
from application.workers.handlers.handle_photo_s3_delete import handle_photo_s3_delete
from infrastructure.core.logger_config import setup_logger
from infrastructure.core.settings import AppSettings, get_app_settings
from infrastructure.messaging.rabbitmq.consumer import (
    consume_topic as consume_rabbitmq_topic,
)


async def consume_topic(
    *,
    settings: AppSettings,
) -> None:
    """Слушать единую очередь и направлять команды обработчикам."""
    async def dispatch_message(
        message: dict[str, Any],
        incoming_routing_key: str,
    ) -> None:
        if incoming_routing_key == "places.bootstrap.requested":
            await handle_places_bootstrap(
                message,
                settings=settings,
            )
        elif incoming_routing_key == "places.photo.s3.delete":
            await handle_photo_s3_delete(message, settings=settings)
        elif incoming_routing_key == "places.bootstrap.test":
            logger.info(
                "Hello world: routing_key='places.bootstrap.test', "
                "message={}.",
                message,
            )
        else:
            raise ValueError(
                f"Unsupported routing key: {incoming_routing_key!r}."
            )

    await consume_rabbitmq_topic(
        settings=settings,
        queue_name="bot.commands",
        routing_keys=(
            "places.bootstrap.requested",
            "places.bootstrap.test",
            "places.photo.s3.delete",
        ),
        message_handler=dispatch_message,
        prefetch_count=1,
    )


async def main() -> None:
    """Настроить логирование и запустить consumer."""
    setup_logger()
    settings = get_app_settings()
    from application.workers.catalog_index_sync import sync_catalog_index
    from application.workers.photo_event_outbox import relay_photo_events
    await asyncio.gather(
        consume_topic(settings=settings),
        sync_catalog_index(settings),
        relay_photo_events(settings),
    )


if __name__ == "__main__":
    asyncio.run(main())
