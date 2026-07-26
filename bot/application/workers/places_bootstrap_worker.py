"""Worker стартового заполнения и индексации мест."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from application.workers.handlers.handle_places_bootstrap import (
    handle_places_bootstrap,
)
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
                incoming_routing_key,
                settings=settings,
            )
        elif incoming_routing_key == "places.bootstrap.test1":
            logger.info(
                "Hello world: routing_key='places.bootstrap.test1', "
                "message={}.",
                message,
            )
        elif incoming_routing_key == "places.bootstrap.test2":
            logger.info(
                "Hello world: routing_key='places.bootstrap.test2', "
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
            "places.bootstrap.test1",
            "places.bootstrap.test2",
        ),
        message_handler=dispatch_message,
        prefetch_count=1,
    )


async def main() -> None:
    """Настроить логирование и запустить consumer."""
    setup_logger()
    settings = get_app_settings()
    await consume_topic(settings=settings)


if __name__ == "__main__":
    asyncio.run(main())
