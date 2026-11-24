from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from urbex.infrastructure.source_gallery_cache import SourceGalleryCache


PLACE = {'id': 3687, 'name': 'Карьер', 'description': 'https://urban3p.ru/object9433/',
         'latitude': 55.873264, 'longitude': 37.380853}
PHOTO = {'image_url': 'https://img04.urban3p.ru/up/o/9433/photo.jpg',
         'source_url': 'https://urban3p.ru/object9433', 'engine': 'urban3p'}


class Storage:
    def __init__(self):
        self.objects = {}
        self.content_types = {}

    def get(self, key):
        return self.objects[key]

    def exists(self, key):
        return key in self.objects

    def put(self, key, data, *, content_type='image/jpeg'):
        self.objects[key] = data
        self.content_types[key] = content_type


def test_reopen_and_restart_use_saved_gallery_without_external_requests():
    storage = Storage()
    calls = []
    cache = SourceGalleryCache(storage, lambda *args: calls.append(args) or [PHOTO])
    try:
        assert cache.photos(PLACE, None) == [PHOTO]
        assert cache.photos(PLACE, None) == [PHOTO]
        assert len(calls) == 1
        assert list(storage.content_types.values()) == ['application/json']
    finally:
        cache.close()
    restarted = SourceGalleryCache(storage, lambda *args: pytest.fail('External source requested again'))
    try:
        assert restarted.photos(PLACE, None) == [PHOTO]
    finally:
        restarted.close()


@pytest.mark.parametrize('outcome', ['success', 'empty', 'failure'])
def test_expired_gallery_is_immediate_while_one_background_refresh_runs(outcome):
    storage = Storage()
    now = [0]
    initial = SourceGalleryCache(storage, lambda *args: [PHOTO], clock=lambda: now[0])
    initial.photos(PLACE, None)
    initial.close()
    now[0] = SourceGalleryCache.FRESH_SECONDS + 1
    started, release = Event(), Event()
    calls = []
    updated = dict(PHOTO, image_url=PHOTO['image_url'].replace('photo.jpg', 'new.jpg'))

    def refresh(*args):
        calls.append(args)
        started.set()
        assert release.wait(5)
        if outcome == 'failure':
            raise OSError('Source unavailable')
        return [updated] if outcome == 'success' else []

    cache = SourceGalleryCache(storage, refresh, clock=lambda: now[0])
    try:
        # No wait for the source, including after an API restart and expired TTL.
        assert cache.photos(PLACE, None) == [PHOTO]
        assert started.wait(1)
        with ThreadPoolExecutor(max_workers=4) as pool:
            assert list(pool.map(lambda _: cache.photos(PLACE, None), range(8))) == [[PHOTO]] * 8
        assert len(calls) == 1
    finally:
        release.set()
        cache.close()
    assert cache.photos(PLACE, None) == ([updated] if outcome == 'success' else [PHOTO])
    assert len(calls) == 1


@pytest.mark.parametrize('change', ['name', 'description', 'latitude', 'aliases', 'report'])
def test_changed_card_or_report_does_not_reuse_old_gallery(change):
    calls = []
    cache = SourceGalleryCache(Storage(), lambda *args: calls.append(args) or [PHOTO])
    try:
        cache.photos(PLACE, None)
        place, report = dict(PLACE), None
        if change == 'report':
            report = {'updated_at': '2026-11-25T00:30:00', 'photos': []}
        else:
            place[change] = {'name': 'Другой объект', 'description': '',
                             'latitude': 56.0, 'aliases': ['Другое название']}[change]
        cache.photos(place, report)
        assert len(calls) == 2
    finally:
        cache.close()


def test_concurrent_first_visits_share_discovery_and_do_not_mutate_cached_photos():
    calls = []
    cache = SourceGalleryCache(Storage(), lambda *args: calls.append(args) or [dict(PHOTO)])
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: cache.photos(PLACE, None), range(8)))
        assert results == [[PHOTO]] * 8
        assert len(calls) == 1
        results[0][0]['image_url'] = 'changed'
        assert cache.photos(PLACE, None) == [PHOTO]
    finally:
        cache.close()


def test_empty_gallery_is_not_persisted_and_can_recover():
    calls = []
    storage = Storage()
    cache = SourceGalleryCache(storage, lambda *args: calls.append(args) or ([] if len(calls) == 1 else [PHOTO]))
    try:
        assert cache.photos(PLACE, None) == []
        assert storage.objects == {}
        assert cache.photos(PLACE, None) == [PHOTO]
    finally:
        cache.close()


def test_storage_outage_does_not_hide_photos_or_break_memory_cache():
    class UnavailableStorage:
        def get(self, key):
            raise OSError('Storage offline')

        def put(self, *args, **kwargs):
            raise OSError('Storage offline')

    calls = []
    cache = SourceGalleryCache(UnavailableStorage(), lambda *args: calls.append(args) or [PHOTO])
    try:
        assert cache.photos(PLACE, None) == [PHOTO]
        assert cache.photos(PLACE, None) == [PHOTO]
        assert len(calls) == 1
    finally:
        cache.close()


def test_api_restart_reuses_gallery_and_s3_image_without_source_access(monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from urbex.bootstrap import main
    from urbex.bootstrap.config import Settings
    from urbex.presentation.http import context

    storage = Storage()
    discoveries, downloads = [], []
    monkeypatch.setattr(main, 'load_osint_report', lambda *args: None)
    monkeypatch.setattr(main, 'source_photos', lambda *args, **kwargs: discoveries.append(1) or [PHOTO])
    config = Settings(environment='test', elasticsearch_url='')
    for _ in range(2):
        app = main.create_app(config, storage)
        app.dependency_overrides[context] = lambda: (
            SimpleNamespace(places=SimpleNamespace(place=lambda *args: PLACE)), None, None,
        )
        app.state.external_images.fetch = lambda url: downloads.append(url) or b'saved jpeg'
        with TestClient(app) as client:
            for _ in range(2):
                response = client.get('/api/places/3687/source-photos')
                assert response.status_code == 200
                photo = response.json()['items'][0]
                assert photo['image_url'].startswith('/api/source-images/')
                image = client.get(photo['image_url'])
                assert image.status_code == 200
                assert image.content == b'saved jpeg'
                assert image.headers['cache-control'] == 'public, max-age=86400'
    assert discoveries == [1]
    assert downloads == [PHOTO['image_url']]
    assert sorted(storage.content_types.values()) == ['application/json', 'image/jpeg']


def test_s3_metadata_has_json_type_and_image_uploads_keep_jpeg_type():
    from types import SimpleNamespace
    from urbex.infrastructure.storage import S3Storage

    storage = object.__new__(S3Storage)
    storage.bucket = 'test'
    calls = []
    storage.client = SimpleNamespace(put_object=lambda **kwargs: calls.append(kwargs))
    storage.put('photo.jpg', b'jpeg')
    storage.put('gallery.json', b'{}', content_type='application/json')
    assert [call['ContentType'] for call in calls] == ['image/jpeg', 'application/json']
