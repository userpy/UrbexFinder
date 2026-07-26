"""Инициализация RabbitMQ exchange, queue и binding."""

from __future__ import annotations

import asyncio

import aio_pika
from loguru import logger

from infrastructure.core.logger_config import setup_logger
from infrastructure.core.settings import AppSettings, get_app_settings
from infrastructure.messaging.rabbitmq.constants import (
    CONNECTION_TIMEOUT_SECONDS,
    EXCHANGE_NAME,
    STARTUP_QUEUE_NAME,
)


async def declare_startup_topology(settings: AppSettings) -> None:
    """Создать exchange, единую очередь и bindings команд мест."""
    connection = await aio_pika.connect_robust(
        host=settings.rabbitmq_host,
        port=settings.rabbitmq_port,
        login=settings.rabbitmq_user,
        password=settings.rabbitmq_password,
        virtualhost=settings.rabbitmq_vhost,
        timeout=CONNECTION_TIMEOUT_SECONDS,
    )

    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            EXCHANGE_NAME,
            type=aio_pika.ExchangeType.TOPIC,
            durable=True,
        )

        queue = await channel.declare_queue(
            STARTUP_QUEUE_NAME,
            durable=True,
        )
        routing_keys = (
            "places.bootstrap.*",
        )
        for routing_key in routing_keys:
            await queue.bind(exchange, routing_key=routing_key)
            logger.info(
                "RabbitMQ topology is ready: exchange='{}', "
                "queue='{}', binding_key='{}'.",
                EXCHANGE_NAME,
                STARTUP_QUEUE_NAME,
                routing_key,
            )


async def main() -> None:
    """Объявить topology и завершить one-shot процесс успешно."""
    setup_logger()
    await declare_startup_topology(get_app_settings())


if __name__ == "__main__":
    asyncio.run(main())
