from unittest.mock import AsyncMock, MagicMock

import pytest

import application.workers.photo_event_outbox as outbox


def session_factory(events):
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.begin.return_value.__aenter__ = AsyncMock()
    session.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    results = []
    for event in events:
        result = MagicMock()
        result.mappings.return_value.first.return_value = event
        results.append(result)
    session.execute = AsyncMock(side_effect=results)
    return MagicMock(return_value=session), session


async def test_publishes_before_removing_event(monkeypatch):
    payload = {'message_id': 'event-1', 'object_key': 'photos/test.jpg', 'photo_id': 1}
    event = {'id': 1, 'routing_key': 'places.photo.s3.delete', 'payload': payload}
    factory, session = session_factory([event, None, None])

    async def publish(**kwargs):
        assert session.execute.await_count == 1
        assert kwargs['message'] == payload
        assert kwargs['routing_key'] == 'places.photo.s3.delete'
        assert kwargs['exchange_name'] == outbox.EXCHANGE_NAME

    publisher = AsyncMock(side_effect=publish)
    monkeypatch.setattr(outbox, 'publish_message', publisher)
    await outbox.publish_pending_photo_events(factory)
    publisher.assert_awaited_once()
    delete_call = session.execute.await_args_list[1]
    assert str(delete_call.args[0]).startswith('DELETE FROM photo_event_outbox')
    assert delete_call.args[1] == {'id': 1}


async def test_broker_failure_keeps_event_for_retry(monkeypatch):
    event = {'id': 1, 'routing_key': 'places.photo.s3.delete', 'payload': {}}
    factory, session = session_factory([event])
    monkeypatch.setattr(outbox, 'publish_message', AsyncMock(side_effect=RuntimeError('unavailable')))
    with pytest.raises(RuntimeError, match='unavailable'):
        await outbox.publish_pending_photo_events(factory)
    assert session.execute.await_count == 1
    assert session.begin.return_value.__aexit__.call_args.args[0] is RuntimeError


async def test_empty_outbox_does_not_publish(monkeypatch):
    factory, session = session_factory([None])
    publisher = AsyncMock()
    monkeypatch.setattr(outbox, 'publish_message', publisher)
    await outbox.publish_pending_photo_events(factory)
    publisher.assert_not_awaited()
