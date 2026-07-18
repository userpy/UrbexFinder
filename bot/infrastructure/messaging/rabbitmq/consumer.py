"""Асинхронный consumer для RabbitMQ topic exchange."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Collection
from typing import Any

import aio_pika
from loguru import logger

from infrastructure.core.settings import AppSettings

MessageHandler = Callable[[dict[str, Any], str], Awaitable[None]]


async def consume_topic(
    *,
    settings: AppSettings,
    queue_name: str,
    routing_keys: Collection[str],
    message_handler: MessageHandler,
    prefetch_count: int = 1,
) -> None:
    """Подключиться к существующей очереди и слушать сообщения."""
    accepted_routing_keys = frozenset(routing_keys)
    if not queue_name or not accepted_routing_keys:
        raise ValueError("queue_name and routing_keys must not be empty.")
    if any(not routing_key for routing_key in accepted_routing_keys):
        raise ValueError("routing_keys must not contain empty values.")
    if prefetch_count < 1:
        raise ValueError("prefetch_count must be greater than zero.")

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
        await channel.set_qos(prefetch_count=prefetch_count)

        queue = await channel.get_queue(queue_name, ensure=True)

        logger.info(
            "RabbitMQ consumer listens queue '{}' with routing keys {}.",
            queue_name,
            sorted(accepted_routing_keys),
        )

        async with queue.iterator() as queue_iterator:
            async for incoming_message in queue_iterator:
                try:
                    async with incoming_message.process(requeue=False):
                        if (
                            incoming_message.routing_key
                            not in accepted_routing_keys
                        ):
                            raise ValueError(
                                "Unsupported routing key: "
                                f"{incoming_message.routing_key!r}."
                            )
                        payload = _decode_message(incoming_message.body)
                        await message_handler(
                            payload,
                            incoming_message.routing_key,
                        )
                    logger.info(
                        "RabbitMQ message acknowledged: id='{}', "
                        "routing_key='{}'.",
                        incoming_message.message_id,
                        incoming_message.routing_key,
                    )
                except Exception as exc:
                    logger.exception(
                        "RabbitMQ message rejected: id='{}', "
                        "routing_key='{}', error={}",
                        incoming_message.message_id,
                        incoming_message.routing_key,
                        exc,
                    )


def _decode_message(body: bytes) -> dict[str, Any]:
    """Декодировать JSON object из RabbitMQ message body."""
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("RabbitMQ message body must contain a JSON object.")
    return payload
