"""Инициализация RabbitMQ exchange, queue и binding."""

from __future__ import annotations

import asyncio

import aio_pika
from loguru import logger

from infrastructure.core.logger_config import setup_logger
from infrastructure.core.settings import AppSettings, get_app_settings


async def declare_startup_topology(settings: AppSettings) -> None:
    """Создать exchange, единую очередь и bindings команд мест."""
    connection = await aio_pika.connect_robust(
        host=settings.rabbitmq_host,
        port=settings.rabbitmq_port,
        login=settings.rabbitmq_user,
        password=settings.rabbitmq_password,
        virtualhost=settings.rabbitmq_vhost,
        timeout=settings.rabbitmq_connect_timeout,
    )

    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            "bot.commands",
            type=aio_pika.ExchangeType.TOPIC,
            durable=True,
        )

        queue = await channel.declare_queue(
            "places.bootstrap.commands",
            durable=True,
        )
        routing_keys = (
            "places.bootstrap.requested",
            "places.bootstrap.test1",
            "places.bootstrap.test2",
        )
        for routing_key in routing_keys:
            await queue.bind(exchange, routing_key=routing_key)
            logger.info(
                "RabbitMQ topology is ready: exchange='bot.commands', "
                "queue='places.bootstrap.commands', binding_key='{}'.",
                routing_key,
            )


async def main() -> None:
    """Объявить topology и завершить one-shot процесс успешно."""
    setup_logger()
    await declare_startup_topology(get_app_settings())


if __name__ == "__main__":
    asyncio.run(main())
