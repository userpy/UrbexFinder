"""Перенаправление неудачных сообщений RabbitMQ в retry или DLQ."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aio_pika
from aio_pika.abc import AbstractExchange
from loguru import logger


@dataclass(kw_only=True)
class FailureRouter:
    """Сохранить неудачное сообщение перед подтверждением исходного."""

    retry_exchange: AbstractExchange
    dead_letter_exchange: AbstractExchange
    max_retry_attempts: int

    async def route(
        self,
        incoming_message: aio_pika.IncomingMessage,
        error: Exception,
        *,
        retryable: bool,
    ) -> None:
        """Отправить копию в retry/DLQ или вернуть исходное сообщение в очередь."""
        try:
            should_retry, retry_count = await self._publish_failure(
                incoming_message, error, retryable=retryable
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
        self._log_routed(incoming_message, error, should_retry, retry_count)

    async def _publish_failure(
        self,
        incoming_message: aio_pika.IncomingMessage,
        error: Exception,
        *,
        retryable: bool,
    ) -> tuple[bool, int]:
        retry_count = self._get_retry_count(incoming_message)
        should_retry = retryable and retry_count < self.max_retry_attempts
        if should_retry:
            retry_count += 1
        headers = self._build_headers(
            incoming_message,
            error,
            retryable=retryable,
            should_retry=should_retry,
            retry_count=retry_count,
        )
        exchange = self.retry_exchange if should_retry else self.dead_letter_exchange
        await exchange.publish(
            self._copy_message(incoming_message, headers),
            routing_key=incoming_message.routing_key,
            mandatory=True,
        )
        return should_retry, retry_count

    @staticmethod
    def _copy_message(
        incoming_message: aio_pika.IncomingMessage,
        headers: dict[str, Any],
    ) -> aio_pika.Message:
        return aio_pika.Message(
            body=incoming_message.body,
            headers=headers,
            content_type=incoming_message.content_type,
            content_encoding=incoming_message.content_encoding,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            correlation_id=incoming_message.correlation_id,
            message_id=incoming_message.message_id,
            type=incoming_message.type,
        )

    @staticmethod
    def _build_headers(
        incoming_message: aio_pika.IncomingMessage,
        error: Exception,
        *,
        retryable: bool,
        should_retry: bool,
        retry_count: int,
    ) -> dict[str, Any]:
        headers = dict(incoming_message.headers or {})
        headers.setdefault("x-original-exchange", incoming_message.exchange)
        headers.setdefault("x-original-routing-key", incoming_message.routing_key)
        headers["x-last-error"] = f"{type(error).__name__}: {error}"[:1024]
        headers["x-retry-count"] = retry_count
        if not should_retry:
            headers["x-failure-reason"] = (
                "retry-exhausted" if retryable else "invalid-message"
            )
        return headers

    def _log_routed(
        self,
        incoming_message: aio_pika.IncomingMessage,
        error: Exception,
        should_retry: bool,
        retry_count: int,
    ) -> None:
        logger.log(
            "WARNING" if should_retry else "ERROR",
            "RabbitMQ message moved to {}: retries={}/{}, id='{}', "
            "routing_key='{}', error={}",
            "retry" if should_retry else "dead-letter",
            retry_count,
            self.max_retry_attempts,
            incoming_message.message_id,
            incoming_message.routing_key,
            error,
        )

    @staticmethod
    def _get_retry_count(incoming_message: aio_pika.IncomingMessage) -> int:
        raw_retry_count = (incoming_message.headers or {}).get("x-retry-count", 0)
        try:
            retry_count = int(raw_retry_count)
        except (TypeError, ValueError):
            return 0
        return max(0, retry_count)
