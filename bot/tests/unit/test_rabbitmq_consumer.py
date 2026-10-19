import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, call

import aio_pika
import pytest

import infrastructure.messaging.rabbitmq.consumer as consumer_module
from infrastructure.messaging.rabbitmq.constants import (
    CONNECTION_TIMEOUT_SECONDS,
    DEAD_LETTER_EXCHANGE_NAME,
    RETRY_EXCHANGE_NAME,
)
from infrastructure.messaging.rabbitmq.consumer import TopicConsumer
from infrastructure.messaging.rabbitmq.failure_router import FailureRouter


def _settings():
    return SimpleNamespace(
        rabbitmq_host="rabbitmq",
        rabbitmq_port=5672,
        rabbitmq_user="bot",
        rabbitmq_password="secret",
        rabbitmq_vhost="/",
        rabbitmq_max_retry_attempts=3,
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


@pytest.fixture
def processing():
    context = SimpleNamespace(
        incoming_message=_incoming_message(),
        message_handler=AsyncMock(),
        retry_exchange=SimpleNamespace(publish=AsyncMock()),
        dead_letter_exchange=SimpleNamespace(publish=AsyncMock()),
    )
    context.consumer = TopicConsumer(
        settings=_settings(),
        queue_name="places.bootstrap.queue",
        routing_keys=["places.bootstrap.requested"],
        message_handler=context.message_handler,
        prefetch_count=4,
    )
    context.failure_router = FailureRouter(
        retry_exchange=context.retry_exchange,
        dead_letter_exchange=context.dead_letter_exchange,
        max_retry_attempts=3,
    )
    return context


@pytest.fixture
def broker(processing, monkeypatch):
    iterator = MagicMock()
    iterator.__aenter__.return_value = iterator
    iterator.__aexit__.return_value = False
    iterator.__aiter__.return_value = [processing.incoming_message]
    queue = SimpleNamespace(iterator=Mock(return_value=iterator))
    exchanges = {
        RETRY_EXCHANGE_NAME: processing.retry_exchange,
        DEAD_LETTER_EXCHANGE_NAME: processing.dead_letter_exchange,
    }
    channel = SimpleNamespace(
        set_qos=AsyncMock(),
        get_queue=AsyncMock(return_value=queue),
        get_exchange=AsyncMock(side_effect=lambda name, **_: exchanges[name]),
    )
    connection = MagicMock()
    connection.__aenter__.return_value = connection
    connection.__aexit__.return_value = False
    connection.channel = AsyncMock(return_value=channel)
    connect = AsyncMock(return_value=connection)
    monkeypatch.setattr(consumer_module.aio_pika, "connect_robust", connect)
    return SimpleNamespace(
        connect=connect,
        connection=connection,
        channel=channel,
        queue=queue,
        iterator=iterator,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"queue_name": ""},
        {"routing_keys": []},
        {"routing_keys": [""]},
        {"routing_keys": ["places.bootstrap.requested", ""]},
        {"prefetch_count": 0},
        {"prefetch_count": -1},
    ],
)
def test_consumer_rejects_invalid_configuration(overrides):
    arguments = {
        "settings": _settings(),
        "queue_name": "places.bootstrap.queue",
        "routing_keys": ["places.bootstrap.requested"],
        "message_handler": AsyncMock(),
    }
    arguments.update(overrides)

    with pytest.raises(ValueError):
        TopicConsumer(**arguments)


async def test_consumer_run_processes_queue_and_closes_resources(
    processing, broker,
):
    await processing.consumer.run()

    broker.connect.assert_awaited_once_with(
        host="rabbitmq",
        port=5672,
        login="bot",
        password="secret",
        virtualhost="/",
        timeout=CONNECTION_TIMEOUT_SECONDS,
    )
    broker.connection.channel.assert_awaited_once_with(
        publisher_confirms=True, on_return_raises=True,
    )
    broker.channel.set_qos.assert_awaited_once_with(prefetch_count=4)
    broker.channel.get_queue.assert_awaited_once_with(
        "places.bootstrap.queue", ensure=True,
    )
    broker.channel.get_exchange.assert_has_awaits(
        [
            call(RETRY_EXCHANGE_NAME, ensure=True),
            call(DEAD_LETTER_EXCHANGE_NAME, ensure=True),
        ],
        any_order=True,
    )
    processing.message_handler.assert_awaited_once_with(
        {"seed_places": True}, "places.bootstrap.requested",
    )
    processing.incoming_message.ack.assert_awaited_once_with()
    broker.iterator.__aexit__.assert_awaited_once_with(None, None, None)
    broker.connection.__aexit__.assert_awaited_once_with(None, None, None)


@pytest.mark.parametrize("failure_point", ["handler", "ack"])
async def test_consumer_run_closes_resources_on_cancellation_or_failure(
    processing, broker, failure_point,
):
    if failure_point == "handler":
        error = asyncio.CancelledError("consumer cancelled")
        processing.message_handler.side_effect = error
    else:
        error = RuntimeError("ack failed")
        processing.incoming_message.ack.side_effect = error

    with pytest.raises(type(error)):
        await processing.consumer.run()

    for context in (broker.iterator, broker.connection):
        context.__aexit__.assert_awaited_once()
        assert context.__aexit__.await_args.args[1] is error
    processing.incoming_message.nack.assert_not_awaited()
    processing.retry_exchange.publish.assert_not_awaited()
    processing.dead_letter_exchange.publish.assert_not_awaited()


@pytest.mark.parametrize("prefetch_options", [{}, {"prefetch_count": 5}])
async def test_consume_topic_forwards_configuration_and_runs_consumer(
    monkeypatch, prefetch_options,
):
    instance = SimpleNamespace(run=AsyncMock())
    factory = Mock(return_value=instance)
    monkeypatch.setattr(consumer_module, "TopicConsumer", factory)
    arguments = {
        "settings": _settings(),
        "queue_name": "places.bootstrap.queue",
        "routing_keys": ["places.bootstrap.requested"],
        "message_handler": AsyncMock(),
    }

    await consumer_module.consume_topic(**arguments, **prefetch_options)

    factory.assert_called_once_with(
        **arguments, prefetch_count=prefetch_options.get("prefetch_count", 1),
    )
    instance.run.assert_awaited_once_with()


async def test_valid_message_is_handled_and_acknowledged(processing):
    await processing.consumer.process_message(
        processing.incoming_message, processing.failure_router,
    )

    processing.message_handler.assert_awaited_once_with(
        {"seed_places": True}, "places.bootstrap.requested",
    )
    processing.incoming_message.ack.assert_awaited_once_with()
    processing.incoming_message.nack.assert_not_awaited()
    processing.retry_exchange.publish.assert_not_awaited()
    processing.dead_letter_exchange.publish.assert_not_awaited()


@pytest.mark.parametrize(
    ("body", "routing_key"),
    [
        (b"{}", "unsupported"),
        (b"\xff", "places.bootstrap.requested"),
        (b"not-json", "places.bootstrap.requested"),
        (b"[]", "places.bootstrap.requested"),
    ],
)
async def test_invalid_message_bypasses_handler_and_retry(
    processing, body, routing_key,
):
    processing.incoming_message.body = body
    processing.incoming_message.routing_key = routing_key

    await processing.consumer.process_message(
        processing.incoming_message, processing.failure_router,
    )

    processing.message_handler.assert_not_awaited()
    processing.retry_exchange.publish.assert_not_awaited()
    processing.dead_letter_exchange.publish.assert_awaited_once()
    published = processing.dead_letter_exchange.publish.await_args.args[0]
    assert published.headers["x-failure-reason"] == "invalid-message"
    processing.incoming_message.ack.assert_awaited_once_with()
    processing.incoming_message.nack.assert_not_awaited()


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
async def test_handler_error_is_retryable(processing, error_type):
    processing.message_handler.side_effect = error_type("handler failed")

    await processing.consumer.process_message(
        processing.incoming_message, processing.failure_router,
    )

    processing.retry_exchange.publish.assert_awaited_once()
    processing.dead_letter_exchange.publish.assert_not_awaited()
    processing.incoming_message.ack.assert_awaited_once_with()
    processing.incoming_message.nack.assert_not_awaited()


async def test_exhausted_handler_error_is_sent_to_dead_letter(processing):
    processing.incoming_message.headers["x-retry-count"] = 3
    processing.message_handler.side_effect = RuntimeError("handler failed")

    await processing.consumer.process_message(
        processing.incoming_message, processing.failure_router,
    )

    processing.retry_exchange.publish.assert_not_awaited()
    processing.dead_letter_exchange.publish.assert_awaited_once()
    published = processing.dead_letter_exchange.publish.await_args.args[0]
    assert published.headers["x-failure-reason"] == "retry-exhausted"
    processing.incoming_message.ack.assert_awaited_once_with()
    processing.incoming_message.nack.assert_not_awaited()


@pytest.mark.parametrize("retryable", [True, False])
async def test_failed_publish_requeues_original_message(processing, retryable):
    if retryable:
        processing.message_handler.side_effect = RuntimeError("handler failed")
        exchange = processing.retry_exchange
    else:
        processing.incoming_message.body = b"not-json"
        exchange = processing.dead_letter_exchange
    exchange.publish.side_effect = RuntimeError("broker unavailable")

    await processing.consumer.process_message(
        processing.incoming_message, processing.failure_router,
    )

    exchange.publish.assert_awaited_once()
    processing.incoming_message.nack.assert_awaited_once_with(requeue=True)
    processing.incoming_message.ack.assert_not_awaited()


async def test_handler_cancellation_propagates_without_ack_or_retry(processing):
    processing.message_handler.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await processing.consumer.process_message(
            processing.incoming_message, processing.failure_router,
        )

    processing.incoming_message.ack.assert_not_awaited()
    processing.incoming_message.nack.assert_not_awaited()
    processing.retry_exchange.publish.assert_not_awaited()
    processing.dead_letter_exchange.publish.assert_not_awaited()


async def test_ack_failure_propagates_without_retry(processing):
    processing.incoming_message.ack.side_effect = RuntimeError("ack failed")

    with pytest.raises(RuntimeError, match="ack failed"):
        await processing.consumer.process_message(
            processing.incoming_message, processing.failure_router,
        )

    processing.message_handler.assert_awaited_once()
    processing.incoming_message.ack.assert_awaited_once_with()
    processing.incoming_message.nack.assert_not_awaited()
    processing.retry_exchange.publish.assert_not_awaited()
    processing.dead_letter_exchange.publish.assert_not_awaited()


@pytest.mark.parametrize("retryable", [True, False])
async def test_publish_cancellation_leaves_original_unacknowledged(
    processing, retryable,
):
    processing.message_handler.side_effect = RuntimeError("handler failed")
    if not retryable:
        processing.incoming_message.body = b"not-json"
    exchange = (
        processing.retry_exchange if retryable
        else processing.dead_letter_exchange
    )
    exchange.publish.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await processing.consumer.process_message(
            processing.incoming_message, processing.failure_router,
        )

    exchange.publish.assert_awaited_once()
    processing.incoming_message.ack.assert_not_awaited()
    processing.incoming_message.nack.assert_not_awaited()


@pytest.mark.parametrize("retryable", [True, False])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_ack_failure_after_routing_propagates_without_requeue(
    processing, retryable, error_type,
):
    processing.message_handler.side_effect = RuntimeError("handler failed")
    if not retryable:
        processing.incoming_message.body = b"not-json"
    processing.incoming_message.ack.side_effect = error_type("ack failed")

    with pytest.raises(error_type, match="ack failed"):
        await processing.consumer.process_message(
            processing.incoming_message, processing.failure_router,
        )

    exchange = (
        processing.retry_exchange if retryable
        else processing.dead_letter_exchange
    )
    exchange.publish.assert_awaited_once()
    processing.incoming_message.ack.assert_awaited_once_with()
    processing.incoming_message.nack.assert_not_awaited()


def test_decode_message_returns_json_object(processing):
    assert processing.consumer._decode_message(processing.incoming_message) == {
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
def test_decode_message_rejects_invalid_payload(processing, body):
    processing.incoming_message.body = body
    with pytest.raises(ValueError):
        processing.consumer._decode_message(processing.incoming_message)


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
    assert FailureRouter._get_retry_count(
        _incoming_message(headers=headers),
    ) == expected


async def test_failed_message_is_published_to_retry_exchange():
    incoming = _incoming_message()
    retry_exchange = SimpleNamespace(publish=AsyncMock())
    dead_exchange = SimpleNamespace(publish=AsyncMock())

    router = FailureRouter(
        retry_exchange=retry_exchange,
        dead_letter_exchange=dead_exchange,
        max_retry_attempts=3,
    )
    await router.route(
        incoming,
        RuntimeError("temporary failure"),
        retryable=True,
    )

    incoming.ack.assert_awaited_once_with()
    incoming.nack.assert_not_awaited()
    retry_exchange.publish.assert_awaited_once()
    dead_exchange.publish.assert_not_awaited()

    published_message = retry_exchange.publish.await_args.args[0]
    assert published_message.headers["x-retry-count"] == 1
    assert "RuntimeError" in published_message.headers["x-last-error"]


async def test_invalid_message_is_published_directly_to_dead_letter():
    incoming = _incoming_message()
    retry_exchange = SimpleNamespace(publish=AsyncMock())
    dead_exchange = SimpleNamespace(publish=AsyncMock())

    router = FailureRouter(
        retry_exchange=retry_exchange,
        dead_letter_exchange=dead_exchange,
        max_retry_attempts=3,
    )
    await router.route(
        incoming,
        ValueError("invalid payload"),
        retryable=False,
    )

    incoming.ack.assert_awaited_once_with()
    incoming.nack.assert_not_awaited()
    retry_exchange.publish.assert_not_awaited()
    dead_exchange.publish.assert_awaited_once()

    published_message = dead_exchange.publish.await_args.args[0]
    assert published_message.headers["x-failure-reason"] == "invalid-message"


@pytest.mark.parametrize("retryable", [True, False])
async def test_routed_copy_preserves_metadata_and_original_headers(retryable):
    headers = {
        "x-original-exchange": "first.exchange",
        "x-original-routing-key": "first.key",
        "x-retry-count": 1,
        "custom": "value",
    }
    original_headers = headers.copy()
    incoming = _incoming_message(headers=headers)
    retry_exchange = SimpleNamespace(publish=AsyncMock())
    dead_exchange = SimpleNamespace(publish=AsyncMock())

    router = FailureRouter(
        retry_exchange=retry_exchange,
        dead_letter_exchange=dead_exchange,
        max_retry_attempts=3,
    )
    await router.route(
        incoming,
        RuntimeError("x" * 2000),
        retryable=retryable,
    )

    exchange = retry_exchange if retryable else dead_exchange
    published = exchange.publish.await_args.args[0]
    assert exchange.publish.await_args.kwargs == {
        "routing_key": incoming.routing_key, "mandatory": True,
    }
    for field in (
        "body", "content_type", "content_encoding", "correlation_id",
        "message_id", "type",
    ):
        assert getattr(published, field) == getattr(incoming, field)
    assert published.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
    assert headers == original_headers
    assert published.headers["x-original-exchange"] == "first.exchange"
    assert published.headers["x-original-routing-key"] == "first.key"
    assert published.headers["custom"] == "value"
    assert published.headers["x-retry-count"] == (2 if retryable else 1)
    assert len(published.headers["x-last-error"]) == 1024


async def test_original_message_is_requeued_when_retry_publish_fails():
    incoming = _incoming_message()
    retry_exchange = SimpleNamespace(
        publish=AsyncMock(side_effect=RuntimeError("broker unavailable")),
    )
    dead_exchange = SimpleNamespace(publish=AsyncMock())

    router = FailureRouter(
        retry_exchange=retry_exchange,
        dead_letter_exchange=dead_exchange,
        max_retry_attempts=3,
    )
    await router.route(
        incoming,
        RuntimeError("handler failed"),
        retryable=True,
    )

    incoming.nack.assert_awaited_once_with(requeue=True)
    incoming.ack.assert_not_awaited()
