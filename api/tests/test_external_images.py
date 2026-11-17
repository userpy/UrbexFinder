from hashlib import sha256
from io import BytesIO
from threading import Event
import httpx
import pytest
from PIL import Image
from botocore.exceptions import ClientError
from urbex.infrastructure.external_images import ExternalImages, supported, download
from urbex.infrastructure.storage import S3Storage
from urbex.domain.rules import DomainError

URL = 'https://avatars.mds.yandex.net/get-altay/123/photo/XXL_height'
PHOTO = {'image_url': URL, 'source_url': 'https://yandex.ru/maps/org/camp/123/', 'title': 'Лагерь'}


class Storage:
    def __init__(self):
        self.objects = {}
        self.writes = 0

    def exists(self, key):
        return key in self.objects

    def put(self, key, data):
        self.objects[key] = data
        self.writes += 1

    def get(self, key):
        if key not in self.objects:
            raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        return self.objects[key]


def test_async_copy_deduplicates_and_preserves_provenance():
    gate = Event()
    storage = Storage()
    cache = ExternalImages(storage, lambda url: gate.wait(5) and b'jpeg')
    try:
        photos = cache.photos([PHOTO, PHOTO])
        assert photos[0]['image_url'] == photos[1]['image_url']
        assert photos[0]['source_url'] == PHOTO['source_url']
        assert photos[0]['original_image_url'] == URL
        assert PHOTO['image_url'] == URL
        assert storage.writes == 0
        gate.set()
        digest = photos[0]['image_url'].rsplit('/', 1)[-1]
        assert cache.content(digest) == b'jpeg'
        assert storage.writes == 1
    finally:
        gate.set()
        cache.close()


def test_restart_reads_s3_without_redownloading():
    storage = Storage()
    digest = sha256(URL.encode()).hexdigest()
    storage.objects[ExternalImages.key(digest)] = b'saved'
    def unexpected(url):
        pytest.fail('Already stored image was downloaded again')
    cache = ExternalImages(storage, unexpected)
    try:
        assert cache.content(digest) == b'saved'
        cache.photos([PHOTO])
        assert cache.content(digest) == b'saved'
        assert storage.writes == 0
    finally:
        cache.close()


def test_failure_falls_back_and_retries_after_cooldown():
    storage = Storage()
    def fail(url):
        raise OSError('offline')
    cache = ExternalImages(storage, fail)
    try:
        digest = cache.photos([PHOTO])[0]['image_url'].rsplit('/', 1)[-1]
        with pytest.raises(DomainError) as exc:
            cache.content(digest)
        assert exc.value.status == 503
        url, future, _ = cache.jobs[digest]
        cache.jobs[digest] = (url, future, -1000)
        cache.fetch = lambda url: b'recovered'
        cache.photos([PHOTO])
        assert cache.content(digest) == b'recovered'
    finally:
        cache.close()


@pytest.mark.parametrize('url', ['http://127.0.0.1/test', 'http://minio:9000/x',
    'https://avatars.mds.yandex.net.evil.org/x', 'https://user@avatars.mds.yandex.net/x',
    'https://avatars.mds.yandex.net:9000/x', 'file:///etc/passwd', '/api/photos/1/content'])
def test_disallowed_origins_are_not_queued(url):
    assert not supported(url)
    cache = ExternalImages(Storage())
    try:
        assert cache.photos([{'image_url': url}]) == []
        assert not cache.jobs
    finally:
        cache.close()


def test_rejects_invalid_object_key_and_missing_image():
    cache = ExternalImages(Storage())
    try:
        for key in ['../private', 'a' * 64]:
            with pytest.raises(DomainError) as exc:
                cache.content(key)
            assert exc.value.status == 404
    finally:
        cache.close()


def test_fetch_sanitizes_and_rejects_redirects_and_nonimages(monkeypatch):
    image = BytesIO()
    Image.new('RGB', (4, 4)).save(image, format='PNG')
    response = httpx.Response(200, content=image.getvalue())
    original_client = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original_client(
        transport=httpx.MockTransport(lambda request: response), **kwargs))
    assert download(URL).startswith(b'\xff\xd8\xff')
    response = httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
    with pytest.raises((ValueError, httpx.HTTPStatusError)):
        download(URL)
    response = httpx.Response(200, content=b'<html>not a photo</html>')
    with pytest.raises(DomainError):
        download(URL)


def test_head_failure_is_not_a_cache_miss():
    storage = object.__new__(S3Storage)
    storage.bucket = 'test'
    class Client:
        def head_object(self, **kwargs):
            raise ClientError({'Error': {'Code': 'AccessDenied'}}, 'HeadObject')
    storage.client = Client()
    with pytest.raises(ClientError):
        storage.exists('external-images/v1/test.jpg')


def test_queue_overflow_never_exposes_original():
    gate = Event()
    cache = ExternalImages(Storage(), lambda url: gate.wait(5) and b'jpeg')
    try:
        photos = [dict(PHOTO, image_url=URL + f'?photo={i}') for i in range(49)]
        result = cache.photos(photos)
        assert len(cache.jobs) == 49
        assert result[-1]['image_url'].startswith('/api/source-images/')
        assert cache.jobs[result[-1]['image_url'].rsplit('/', 1)[-1]][1] is None
    finally:
        gate.set()
        cache.close()


def test_http_failure_never_redirects_to_source():
    from fastapi.testclient import TestClient
    from urbex.bootstrap.main import create_app
    from urbex.bootstrap.config import Settings
    app = create_app(Settings(environment='test', elasticsearch_url=''), Storage())
    def fail(url):
        raise OSError('unreachable')
    app.state.external_images.fetch = fail
    with TestClient(app) as client:
        photo = app.state.external_images.photos([PHOTO])[0]
        response = client.get(photo['image_url'], follow_redirects=False)
        assert response.status_code == 503
        assert 'location' not in response.headers
        assert response.headers['retry-after'] == '3'
        assert response.headers['cache-control'] == 'no-store'
        assert client.get('/api/source-images/invalid').status_code == 404
