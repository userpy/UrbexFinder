"""Асинхронный consumer для RabbitMQ topic exchange."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Collection
from typing import Any

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractRobustConnection
from loguru import logger

from infrastructure.core.settings import AppSettings
from infrastructure.messaging.rabbitmq.constants import (
    CONNECTION_TIMEOUT_SECONDS,
    DEAD_LETTER_EXCHANGE_NAME,
    RETRY_EXCHANGE_NAME,
)
from infrastructure.messaging.rabbitmq.failure_router import FailureRouter

MessageHandler = Callable[[dict[str, Any], str], Awaitable[None]]


class TopicConsumer:
    """Подключение к очереди и последовательная обработка сообщений."""

    def __init__(
        self,
        *,
        settings: AppSettings,
        queue_name: str,
        routing_keys: Collection[str],
        message_handler: MessageHandler,
        prefetch_count: int = 1,
    ) -> None:
        self.settings = settings
        self.queue_name = queue_name
        self.routing_keys = frozenset(routing_keys)
        self.message_handler = message_handler
        self.prefetch_count = prefetch_count
        self._validate_options()

    def _validate_options(self) -> None:
        if not self.queue_name or not self.routing_keys:
            raise ValueError("queue_name and routing_keys must not be empty.")
        if any(not routing_key for routing_key in self.routing_keys):
            raise ValueError("routing_keys must not contain empty values.")
        if self.prefetch_count < 1:
            raise ValueError("prefetch_count must be greater than zero.")

    async def run(self) -> None:
        """Слушать очередь до остановки; закрыть соединение при выходе."""
        connection = await self._connect()
        async with connection:
            channel = await connection.channel(
                publisher_confirms=True,
                on_return_raises=True,
            )
            await self._consume(channel)

    async def _connect(self) -> AbstractRobustConnection:
        return await aio_pika.connect_robust(
            host=self.settings.rabbitmq_host,
            port=self.settings.rabbitmq_port,
            login=self.settings.rabbitmq_user,
            password=self.settings.rabbitmq_password,
            virtualhost=self.settings.rabbitmq_vhost,
            timeout=CONNECTION_TIMEOUT_SECONDS,
        )

    async def _consume(self, channel: AbstractChannel) -> None:
        await channel.set_qos(prefetch_count=self.prefetch_count)
        queue = await channel.get_queue(self.queue_name, ensure=True)
        failure_router = FailureRouter(
            retry_exchange=await channel.get_exchange(
                RETRY_EXCHANGE_NAME, ensure=True,
            ),
            dead_letter_exchange=await channel.get_exchange(
                DEAD_LETTER_EXCHANGE_NAME, ensure=True,
            ),
            max_retry_attempts=self.settings.rabbitmq_max_retry_attempts,
        )
        logger.info(
            "RabbitMQ consumer listens queue '{}' with routing keys {}.",
            self.queue_name,
            sorted(self.routing_keys),
        )
        async with queue.iterator() as messages:
            async for incoming_message in messages:
                await self.process_message(incoming_message, failure_router)

    async def process_message(
        self,
        incoming_message: aio_pika.IncomingMessage,
        failure_router: FailureRouter,
    ) -> None:
        """Различать ошибки входных данных и ошибки выполнения обработчика."""
        try:
            payload = self._decode_message(incoming_message)
        except ValueError as exc:
            await failure_router.route(incoming_message, exc, retryable=False)
            return

        try:
            await self.message_handler(payload, incoming_message.routing_key)
        except Exception as exc:
            await failure_router.route(incoming_message, exc, retryable=True)
        else:
            await self._acknowledge(incoming_message)

    def _decode_message(
        self, incoming_message: aio_pika.IncomingMessage,
    ) -> dict[str, Any]:
        if incoming_message.routing_key not in self.routing_keys:
            raise ValueError(
                f"Unsupported routing key: {incoming_message.routing_key!r}."
            )
        payload = json.loads(incoming_message.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("RabbitMQ message body must contain a JSON object.")
        return payload

    @staticmethod
    async def _acknowledge(incoming_message: aio_pika.IncomingMessage) -> None:
        await incoming_message.ack()
        logger.info(
            "RabbitMQ message acknowledged: id='{}', routing_key='{}'.",
            incoming_message.message_id,
            incoming_message.routing_key,
        )


async def consume_topic(
    *,
    settings: AppSettings,
    queue_name: str,
    routing_keys: Collection[str],
    message_handler: MessageHandler,
    prefetch_count: int = 1,
) -> None:
    """Запустить consumer через прежний интерфейс worker."""
    consumer = TopicConsumer(
        settings=settings,
        queue_name=queue_name,
        routing_keys=routing_keys,
        message_handler=message_handler,
        prefetch_count=prefetch_count,
    )
    await consumer.run()
