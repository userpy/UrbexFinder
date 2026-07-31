from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from infrastructure.messaging.rabbitmq.consumer import (
    _decode_message,
    _get_retry_count,
    _route_failed_message,
    _route_or_requeue,
)


def _incoming_message(*, headers=None):
    return SimpleNamespace(
        body=b'{"seed_places": true}',
        headers=headers or {},
        exchange="bot.commands.exchange",
        routing_key="places.bootstrap.requested",
        content_type="application/json",
        content_encoding="utf-8",
        correlation_id="correlation-1",
        message_id="message-1",
        type="places.bootstrap.requested",
        ack=AsyncMock(),
        nack=AsyncMock(),
    )


def test_decode_message_returns_json_object():
    assert _decode_message(b'{"seed_places": true}') == {
        "seed_places": True,
    }


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"[]",
        b'"text"',
    ],
)
def test_decode_message_rejects_invalid_payload(body):
    with pytest.raises(ValueError):
        _decode_message(body)


@pytest.mark.parametrize(
    ("raw_retry_count", "expected"),
    [
        (None, 0),
        ("invalid", 0),
        (-1, 0),
        ("2", 2),
    ],
)
def test_get_retry_count_is_defensive(raw_retry_count, expected):
    headers = (
        {}
        if raw_retry_count is None
        else {"x-retry-count": raw_retry_count}
    )
    assert _get_retry_count(_incoming_message(headers=headers)) == expected


async def test_failed_message_is_published_to_retry_exchange():
    incoming = _incoming_message()
    retry_exchange = SimpleNamespace(publish=AsyncMock())
    dead_exchange = SimpleNamespace(publish=AsyncMock())

    destination, retry_count = await _route_failed_message(
        incoming_message=incoming,
        retry_exchange=retry_exchange,
        dead_letter_exchange=dead_exchange,
        error=RuntimeError("temporary failure"),
        max_retry_attempts=3,
        retryable=True,
    )

    assert (destination, retry_count) == ("retry", 1)
    retry_exchange.publish.assert_awaited_once()
    dead_exchange.publish.assert_not_awaited()

    published_message = retry_exchange.publish.await_args.args[0]
    assert published_message.headers["x-retry-count"] == 1
    assert "RuntimeError" in published_message.headers["x-last-error"]


async def test_invalid_message_is_published_directly_to_dead_letter():
    incoming = _incoming_message()
    retry_exchange = SimpleNamespace(publish=AsyncMock())
    dead_exchange = SimpleNamespace(publish=AsyncMock())

    destination, retry_count = await _route_failed_message(
        incoming_message=incoming,
        retry_exchange=retry_exchange,
        dead_letter_exchange=dead_exchange,
        error=ValueError("invalid payload"),
        max_retry_attempts=3,
        retryable=False,
    )

    assert (destination, retry_count) == ("dead-letter", 0)
    retry_exchange.publish.assert_not_awaited()
    dead_exchange.publish.assert_awaited_once()

    published_message = dead_exchange.publish.await_args.args[0]
    assert published_message.headers["x-failure-reason"] == "invalid-message"


async def test_original_message_is_requeued_when_retry_publish_fails():
    incoming = _incoming_message()
    retry_exchange = SimpleNamespace(
        publish=AsyncMock(side_effect=RuntimeError("broker unavailable")),
    )
    dead_exchange = SimpleNamespace(publish=AsyncMock())

    await _route_or_requeue(
        incoming_message=incoming,
        retry_exchange=retry_exchange,
        dead_letter_exchange=dead_exchange,
        error=RuntimeError("handler failed"),
        max_retry_attempts=3,
        retryable=True,
    )

    incoming.nack.assert_awaited_once_with(requeue=True)
    incoming.ack.assert_not_awaited()
