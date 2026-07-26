"""Асинхронный RabbitMQ producer для отправки команд и событий."""

from __future__ import annotations

import json
from typing import Any

import aio_pika

from infrastructure.core.settings import get_app_settings
from infrastructure.messaging.rabbitmq.constants import (
    CONNECTION_TIMEOUT_SECONDS,
)


async def publish_message(
    *,
    exchange_name: str,
    routing_key: str,
    message: dict[str, Any],
) -> None:
    """Отправить сохраняемое JSON-сообщение через topic exchange."""
    if not exchange_name or not routing_key:
        raise ValueError("exchange_name and routing_key must not be empty.")

    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    settings = get_app_settings()
    message_id = message.get("message_id")
    if message_id is not None and not isinstance(message_id, str):
        raise TypeError("message_id must be a string or null.")

    connection = await aio_pika.connect_robust(
        host=settings.rabbitmq_host,
        port=settings.rabbitmq_port,
        login=settings.rabbitmq_user,
        password=settings.rabbitmq_password,
        virtualhost=settings.rabbitmq_vhost,
        timeout=CONNECTION_TIMEOUT_SECONDS,
    )

    async with connection:
        channel = await connection.channel(
            publisher_confirms=True,
            on_return_raises=True,
        )
        exchange = await channel.declare_exchange(
            exchange_name,
            type=aio_pika.ExchangeType.TOPIC,
            durable=True,
        )

        await exchange.publish(
            aio_pika.Message(
                body=body,
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                content_type="application/json",
                message_id=message_id,
                type=routing_key,
            ),
            routing_key=routing_key,
            mandatory=True,
        )
