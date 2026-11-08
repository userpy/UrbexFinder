from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import BufferedInputFile
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageMedia

import application.places_view as view
import infrastructure.storage.s3 as storage


@pytest.mark.parametrize('fallback', [False, True])
async def test_website_photo_uploaded_from_s3(monkeypatch, fallback):
    photo = {'id': -12, 'user_name': 'Автор сайта', 'file_id': None, 'object_key': 'photos/site.jpg'}
    db = SimpleNamespace(places=SimpleNamespace(get_photos_page=AsyncMock(return_value={'total': 1, 'items': [photo]})))
    message = SimpleNamespace(photo=None, edit_media=AsyncMock(), answer_photo=AsyncMock(), delete=AsyncMock())
    if fallback:
        message.edit_media.side_effect = TelegramBadRequest(method=EditMessageMedia(media={'type': 'photo', 'media': 'test'}), message='Cannot edit')
    get = AsyncMock(return_value=b'jpeg-data')
    monkeypatch.setattr(view, 'get_app_settings', lambda: object())
    monkeypatch.setattr(view, 'S3Storage', lambda settings: SimpleNamespace(get_object=get))
    assert await view.PlacesView.show_photos_page(message, db, 42, 0)
    get.assert_awaited_once_with('photos/site.jpg')
    media = message.edit_media.call_args.kwargs['media'].media
    assert isinstance(media, BufferedInputFile)
    assert media.data == b'jpeg-data'
    if fallback:
        assert message.answer_photo.call_args.kwargs['photo'] is media


async def test_telegram_photo_uses_file_id_without_s3(monkeypatch):
    photo = {'id': 12, 'user_name': 'Автор', 'file_id': 'telegram-file'}
    db = SimpleNamespace(places=SimpleNamespace(get_photos_page=AsyncMock(return_value={'total': 1, 'items': [photo]})))
    message = SimpleNamespace(photo=True, edit_media=AsyncMock())
    factory = MagicMock()
    monkeypatch.setattr(view, 'S3Storage', factory)
    assert await view.PlacesView.show_photos_page(message, db, 42, 0)
    assert message.edit_media.call_args.kwargs['media'].media == 'telegram-file'
    factory.assert_not_called()


async def test_s3_read_closes_body_and_client(monkeypatch):
    client = MagicMock()
    body = client.get_object.return_value['Body']
    body.read.return_value = b'jpeg'
    monkeypatch.setattr(storage.S3Storage, '_client', lambda self: client)
    assert await storage.S3Storage(SimpleNamespace(s3_bucket='test')).get_object('photos/test.jpg') == b'jpeg'
    client.get_object.assert_called_once_with(Bucket='test', Key='photos/test.jpg')
    body.close.assert_called_once()
    client.close.assert_called_once()
