from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aio_pika.exceptions import (
    AMQPConnectionError,
    ProbableAuthenticationError,
)

import infrastructure.messaging.rabbitmq.exchange_queue_topology as topology


def _settings(**overrides):
    values = {
        "rabbitmq_host": "rabbitmq",
        "rabbitmq_port": 5672,
        "rabbitmq_user": "bot",
        "rabbitmq_password": "secret",
        "rabbitmq_vhost": "/",
        "rabbitmq_connection_max_attempts": 3,
        "rabbitmq_connection_retry_delay_ms": 100,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def test_connect_retries_temporary_failure(monkeypatch):
    connection = object()
    connect = AsyncMock(
        side_effect=[
            AMQPConnectionError("broker is starting"),
            connection,
        ],
    )
    sleep = AsyncMock()
    monkeypatch.setattr(topology.aio_pika, "connect_robust", connect)
    monkeypatch.setattr(topology.asyncio, "sleep", sleep)

    result = await topology._connect_with_retry(_settings())

    assert result is connection
    assert connect.await_count == 2
    sleep.assert_awaited_once_with(0.1)


async def test_connect_raises_after_attempts_are_exhausted(monkeypatch):
    error = AMQPConnectionError("broker unavailable")
    connect = AsyncMock(side_effect=error)
    sleep = AsyncMock()
    monkeypatch.setattr(topology.aio_pika, "connect_robust", connect)
    monkeypatch.setattr(topology.asyncio, "sleep", sleep)

    with pytest.raises(AMQPConnectionError, match="broker unavailable"):
        await topology._connect_with_retry(_settings())

    assert connect.await_count == 3
    assert [call.args for call in sleep.await_args_list] == [
        (0.1,),
        (0.2,),
    ]


async def test_connect_does_not_retry_authentication_error(monkeypatch):
    connect = AsyncMock(
        side_effect=ProbableAuthenticationError("bad credentials"),
    )
    sleep = AsyncMock()
    monkeypatch.setattr(topology.aio_pika, "connect_robust", connect)
    monkeypatch.setattr(topology.asyncio, "sleep", sleep)

    with pytest.raises(ProbableAuthenticationError, match="bad credentials"):
        await topology._connect_with_retry(_settings())

    connect.assert_awaited_once()
    sleep.assert_not_awaited()


async def test_topology_binds_photo_deletion(monkeypatch):
    from unittest.mock import MagicMock, call

    connection = MagicMock()
    channel = AsyncMock()
    connection.channel = AsyncMock(return_value=channel)
    monkeypatch.setattr(topology, '_connect_with_retry', AsyncMock(return_value=connection))
    await topology.declare_startup_topology(_settings(rabbitmq_retry_delay_ms=5000))
    queue = channel.declare_queue.return_value
    assert call(channel.declare_exchange.return_value, routing_key='places.photo.s3.delete') in queue.bind.await_args_list
