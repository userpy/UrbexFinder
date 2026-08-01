"""Инициализация RabbitMQ exchange, queue и binding."""

from __future__ import annotations

import asyncio

import aio_pika
from aio_pika.abc import AbstractRobustConnection
from aio_pika.exceptions import (
    AMQPConnectionError,
    AuthenticationError,
    ProbableAuthenticationError,
)
from loguru import logger

from infrastructure.core.logger_config import setup_logger
from infrastructure.core.settings import AppSettings, get_app_settings
from infrastructure.messaging.rabbitmq.constants import (
    CONNECTION_MAX_RETRY_DELAY_SECONDS,
    CONNECTION_TIMEOUT_SECONDS,
    DEAD_LETTER_EXCHANGE_NAME,
    DEAD_LETTER_QUEUE_NAME,
    EXCHANGE_NAME,
    RETRY_EXCHANGE_NAME,
    RETRY_QUEUE_NAME,
    STARTUP_QUEUE_NAME,
)


async def _connect_with_retry(
    settings: AppSettings,
) -> AbstractRobustConnection:
    """Подключиться к RabbitMQ с ограниченными повторами при старте."""
    retry_delay_seconds = settings.rabbitmq_connection_retry_delay_ms / 1_000

    for attempt in range(1, settings.rabbitmq_connection_max_attempts + 1):
        try:
            return await aio_pika.connect_robust(
                host=settings.rabbitmq_host,
                port=settings.rabbitmq_port,
                login=settings.rabbitmq_user,
                password=settings.rabbitmq_password,
                virtualhost=settings.rabbitmq_vhost,
                timeout=CONNECTION_TIMEOUT_SECONDS,
            )
        except (AuthenticationError, ProbableAuthenticationError):
            raise
        except (AMQPConnectionError, TimeoutError) as exc:
            if attempt >= settings.rabbitmq_connection_max_attempts:
                logger.error(
                    "RabbitMQ connection failed after {}/{} attempts: {}",
                    attempt,
                    settings.rabbitmq_connection_max_attempts,
                    exc,
                )
                raise

            logger.warning(
                "RabbitMQ connection attempt {}/{} failed; retrying in "
                "{:.3f} seconds: {}",
                attempt,
                settings.rabbitmq_connection_max_attempts,
                retry_delay_seconds,
                exc,
            )
            await asyncio.sleep(retry_delay_seconds)
            retry_delay_seconds = min(
                retry_delay_seconds * 2,
                CONNECTION_MAX_RETRY_DELAY_SECONDS,
            )

    raise RuntimeError("RabbitMQ connection retry loop ended unexpectedly")


async def declare_startup_topology(settings: AppSettings) -> None:
    """Создать основную, retry и dead-letter topology."""
    connection = await _connect_with_retry(settings)

    async with connection:
        channel = await connection.channel()
        main_exchange = await channel.declare_exchange(
            EXCHANGE_NAME,
            type=aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        retry_exchange = await channel.declare_exchange(
            RETRY_EXCHANGE_NAME,
            type=aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        dead_letter_exchange = await channel.declare_exchange(
            DEAD_LETTER_EXCHANGE_NAME,
            type=aio_pika.ExchangeType.TOPIC,
            durable=True,
        )

        main_queue = await channel.declare_queue(
            STARTUP_QUEUE_NAME,
            durable=True,
        )
        retry_queue = await channel.declare_queue(
            RETRY_QUEUE_NAME,
            durable=True,
            arguments={
                "x-message-ttl": settings.rabbitmq_retry_delay_ms,
                "x-dead-letter-exchange": EXCHANGE_NAME,
            },
        )
        dead_letter_queue = await channel.declare_queue(
            DEAD_LETTER_QUEUE_NAME,
            durable=True,
        )

        routing_keys = (
            "places.bootstrap.*",
        )
        for routing_key in routing_keys:
            await main_queue.bind(main_exchange, routing_key=routing_key)
            logger.info(
                "RabbitMQ topology is ready: exchange='{}', "
                "queue='{}', binding_key='{}'.",
                EXCHANGE_NAME,
                STARTUP_QUEUE_NAME,
                routing_key,
            )

        await retry_queue.bind(retry_exchange, routing_key="#")
        await dead_letter_queue.bind(
            dead_letter_exchange,
            routing_key="#",
        )
        logger.info(
            "RabbitMQ retry topology is ready: retry_queue='{}', "
            "delay_ms={}, dead_letter_queue='{}'.",
            RETRY_QUEUE_NAME,
            settings.rabbitmq_retry_delay_ms,
            DEAD_LETTER_QUEUE_NAME,
        )


async def main() -> None:
    """Объявить topology и завершить one-shot процесс успешно."""
    setup_logger()
    await declare_startup_topology(get_app_settings())


if __name__ == "__main__":
    asyncio.run(main())
