from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import application.workers.handlers.handle_photo_s3_delete as handler
import application.workers.places_bootstrap_worker as worker
import infrastructure.storage.s3 as storage


async def test_deletes_photo(monkeypatch):
    delete = AsyncMock()
    monkeypatch.setattr(handler, 'S3Storage', lambda settings: SimpleNamespace(delete_object=delete))
    await handler.handle_photo_s3_delete({'object_key': 'photos/test.jpg'}, settings=object())
    delete.assert_awaited_once_with('photos/test.jpg')


@pytest.mark.parametrize('payload', [{}, {'object_key': None}, {'object_key': 42}, {'object_key': ''}, {'object_key': '  '}])
async def test_rejects_invalid_key(payload, monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr(handler, 'S3Storage', factory)
    with pytest.raises(ValueError, match='object_key'):
        await handler.handle_photo_s3_delete(payload, settings=object())
    factory.assert_not_called()


async def test_s3_failure_reaches_consumer(monkeypatch):
    delete = AsyncMock(side_effect=RuntimeError('S3 unavailable'))
    monkeypatch.setattr(handler, 'S3Storage', lambda settings: SimpleNamespace(delete_object=delete))
    with pytest.raises(RuntimeError, match='S3 unavailable'):
        await handler.handle_photo_s3_delete({'object_key': 'photos/test.jpg'}, settings=object())


async def test_worker_dispatches_deletion(monkeypatch):
    consume = AsyncMock()
    delete = AsyncMock()
    monkeypatch.setattr(worker, 'consume_rabbitmq_topic', consume)
    monkeypatch.setattr(worker, 'handle_photo_s3_delete', delete)
    settings = object()
    await worker.consume_topic(settings=settings)
    options = consume.call_args.kwargs
    assert 'places.photo.s3.delete' in options['routing_keys']
    payload = {'object_key': 'photos/test.jpg'}
    await options['message_handler'](payload, 'places.photo.s3.delete')
    delete.assert_awaited_once_with(payload, settings=settings)


async def test_storage_deletes_from_configured_bucket_and_closes_client(monkeypatch):
    factory = MagicMock()
    client = factory.return_value
    monkeypatch.setattr(storage.boto3, 'client', factory)
    settings = SimpleNamespace(s3_endpoint='http://minio:9000', s3_access_key='test', s3_secret_key='secret', s3_bucket='photos-test')
    s3 = storage.S3Storage(settings)
    # Redelivery of a successful command must also succeed.
    await s3.delete_object('photos/test.jpg')
    await s3.delete_object('photos/test.jpg')
    assert client.delete_object.call_count == 2
    client.delete_object.assert_called_with(Bucket='photos-test', Key='photos/test.jpg')
    assert client.close.call_count == 2


async def test_storage_closes_client_after_s3_failure(monkeypatch):
    factory = MagicMock()
    client = factory.return_value
    client.delete_object.side_effect = RuntimeError('S3 unavailable')
    monkeypatch.setattr(storage.boto3, 'client', factory)
    settings = SimpleNamespace(s3_endpoint='http://minio:9000', s3_access_key='test', s3_secret_key='secret', s3_bucket='photos-test')
    with pytest.raises(RuntimeError, match='S3 unavailable'):
        await storage.S3Storage(settings).delete_object('photos/test.jpg')
    client.close.assert_called_once()
