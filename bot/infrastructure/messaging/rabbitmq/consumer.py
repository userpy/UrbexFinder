"""Асинхронный consumer для RabbitMQ topic exchange."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Collection
from typing import Any

import aio_pika
from aio_pika.abc import AbstractExchange
from loguru import logger

from infrastructure.core.settings import AppSettings
from infrastructure.messaging.rabbitmq.constants import (
    CONNECTION_TIMEOUT_SECONDS,
    DEAD_LETTER_EXCHANGE_NAME,
    RETRY_EXCHANGE_NAME,
)

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
        timeout=CONNECTION_TIMEOUT_SECONDS,
    )

    async with connection:
        channel = await connection.channel(
            publisher_confirms=True,
            on_return_raises=True,
        )
        await channel.set_qos(prefetch_count=prefetch_count)

        queue = await channel.get_queue(queue_name, ensure=True)
        retry_exchange = await channel.get_exchange(
            RETRY_EXCHANGE_NAME,
            ensure=True,
        )
        dead_letter_exchange = await channel.get_exchange(
            DEAD_LETTER_EXCHANGE_NAME,
            ensure=True,
        )

        logger.info(
            "RabbitMQ consumer listens queue '{}' with routing keys {}.",
            queue_name,
            sorted(accepted_routing_keys),
        )

        async with queue.iterator() as queue_iterator:
            async for incoming_message in queue_iterator:
                try:
                    if (
                        incoming_message.routing_key
                        not in accepted_routing_keys
                    ):
                        raise ValueError(
                            "Unsupported routing key: "
                            f"{incoming_message.routing_key!r}."
                        )
                    payload = _decode_message(incoming_message.body)
                except (UnicodeDecodeError, ValueError) as exc:
                    await _route_or_requeue(
                        incoming_message=incoming_message,
                        retry_exchange=retry_exchange,
                        dead_letter_exchange=dead_letter_exchange,
                        error=exc,
                        max_retry_attempts=settings.rabbitmq_max_retry_attempts,
                        retryable=False,
                    )
                    continue

                try:
                    await message_handler(
                        payload,
                        incoming_message.routing_key,
                    )
                except Exception as exc:
                    await _route_or_requeue(
                        incoming_message=incoming_message,
                        retry_exchange=retry_exchange,
                        dead_letter_exchange=dead_letter_exchange,
                        error=exc,
                        max_retry_attempts=settings.rabbitmq_max_retry_attempts,
                        retryable=True,
                    )
                else:
                    await incoming_message.ack()
                    logger.info(
                        "RabbitMQ message acknowledged: id='{}', "
                        "routing_key='{}'.",
                        incoming_message.message_id,
                        incoming_message.routing_key,
                    )


async def _route_or_requeue(
    *,
    incoming_message: aio_pika.IncomingMessage,
    retry_exchange: AbstractExchange,
    dead_letter_exchange: AbstractExchange,
    error: Exception,
    max_retry_attempts: int,
    retryable: bool,
) -> None:
    """Отправить сообщение на retry или в DLQ, не теряя его при ошибке брокера."""
    try:
        destination, retry_count = await _route_failed_message(
            incoming_message=incoming_message,
            retry_exchange=retry_exchange,
            dead_letter_exchange=dead_letter_exchange,
            error=error,
            max_retry_attempts=max_retry_attempts,
            retryable=retryable,
        )
    except Exception as routing_error:
        await incoming_message.nack(requeue=True)
        logger.exception(
            "RabbitMQ failed-message routing failed; original message "
            "was requeued: id='{}', routing_key='{}', error={}",
            incoming_message.message_id,
            incoming_message.routing_key,
            routing_error,
        )
        return

    await incoming_message.ack()
    if destination == "retry":
        logger.warning(
            "RabbitMQ message scheduled for retry {}/{}: id='{}', "
            "routing_key='{}', error={}",
            retry_count,
            max_retry_attempts,
            incoming_message.message_id,
            incoming_message.routing_key,
            error,
        )
    else:
        logger.error(
            "RabbitMQ message moved to DLQ after {} retries: id='{}', "
            "routing_key='{}', error={}",
            retry_count,
            incoming_message.message_id,
            incoming_message.routing_key,
            error,
        )


async def _route_failed_message(
    *,
    incoming_message: aio_pika.IncomingMessage,
    retry_exchange: AbstractExchange,
    dead_letter_exchange: AbstractExchange,
    error: Exception,
    max_retry_attempts: int,
    retryable: bool,
) -> tuple[str, int]:
    retry_count = _get_retry_count(incoming_message)
    headers = dict(incoming_message.headers or {})
    headers.setdefault(
        "x-original-exchange",
        incoming_message.exchange,
    )
    headers.setdefault(
        "x-original-routing-key",
        incoming_message.routing_key,
    )
    headers["x-last-error"] = (
        f"{type(error).__name__}: {error}"[:1024]
    )

    if retryable and retry_count < max_retry_attempts:
        next_retry_count = retry_count + 1
        headers["x-retry-count"] = next_retry_count
        await _publish_message_copy(
            exchange=retry_exchange,
            incoming_message=incoming_message,
            headers=headers,
        )
        return "retry", next_retry_count

    headers["x-retry-count"] = retry_count
    headers["x-failure-reason"] = (
        "retry-exhausted" if retryable else "invalid-message"
    )
    await _publish_message_copy(
        exchange=dead_letter_exchange,
        incoming_message=incoming_message,
        headers=headers,
    )
    return "dead-letter", retry_count


async def _publish_message_copy(
    *,
    exchange: AbstractExchange,
    incoming_message: aio_pika.IncomingMessage,
    headers: dict[str, Any],
) -> None:
    await exchange.publish(
        aio_pika.Message(
            body=incoming_message.body,
            headers=headers,
            content_type=incoming_message.content_type,
            content_encoding=incoming_message.content_encoding,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            correlation_id=incoming_message.correlation_id,
            message_id=incoming_message.message_id,
            type=incoming_message.type,
        ),
        routing_key=incoming_message.routing_key,
        mandatory=True,
    )


def _get_retry_count(incoming_message: aio_pika.IncomingMessage) -> int:
    raw_retry_count = (incoming_message.headers or {}).get(
        "x-retry-count",
        0,
    )
    try:
        retry_count = int(raw_retry_count)
    except (TypeError, ValueError):
        return 0
    return max(0, retry_count)


def _decode_message(body: bytes) -> dict[str, Any]:
    """Декодировать JSON object из RabbitMQ message body."""
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("RabbitMQ message body must contain a JSON object.")
    return payload
