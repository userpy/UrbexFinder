"""Bounded, restart-safe S3 cache for already verified external galleries."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from hashlib import sha256
from threading import Lock, BoundedSemaphore
from time import monotonic
from urllib.parse import urlparse
import re
import httpx
from botocore.exceptions import ClientError
from .storage import sanitize_photo, MAX_PHOTO_BYTES
from urbex.domain.rules import DomainError

# Trusted image origins; unsupported images are withheld from the gallery.
HOSTS = frozenset({
    'avatars.mds.yandex.net', 'photos.wikimapia.org', 'geocaching.su',
    'www.geocaching.su', 'geocaching.ru', 'www.geocaching.ru',
    'podmoskovnye.ru', 'www.podmoskovnye.ru', 'upload.wikimedia.org',
    'img.urban3p.ru', 'img01.urban3p.ru', 'img02.urban3p.ru',
    'img03.urban3p.ru', 'img04.urban3p.ru', 'swalker.ru',
    'urban3p.ru', 'www.urban3p.ru', 'urban3p.com', 'www.urban3p.com',
    'img.urban3p.com', 'img01.urban3p.com', 'img02.urban3p.com',
    'img03.urban3p.com', 'img04.urban3p.com',
    'planetadorog.ru', 'www.planetadorog.ru', 's3.dzeninfra.ru',
})
VK_IMAGE_DOMAINS = ('userapi.com', 'vkuserphoto.ru')


def supported(url):
    try:
        p = urlparse(url)
        host = p.hostname or ''
        vk_image = p.scheme == 'https' and any(
            host == domain or host.endswith('.' + domain) for domain in VK_IMAGE_DOMAINS
        )
        return (p.scheme in {'http', 'https'} and (host in HOSTS or vk_image)
                and not p.username and not p.password and p.port in {None, 80, 443})
    except (ValueError, TypeError):
        return False


def download(url):
    if not supported(url):
        raise ValueError('Unsupported image origin')
    parsed = urlparse(url)
    if parsed.scheme == 'http' and parsed.hostname in {'podmoskovnye.ru', 'www.podmoskovnye.ru'}:
        url = parsed._replace(scheme='https').geturl()
    try:
        return _download_image(url)
    except (httpx.HTTPError, ValueError, DomainError) as exc:
        parsed = urlparse(url)
        host = parsed.hostname or ''
        # Wikimapia intermittently times out during TCP/TLS setup. Retry once
        # before leaving the photo unavailable until the cache cooldown ends.
        if host == 'photos.wikimapia.org' and isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            return _download_image(url)
        if host != 'urban3p.ru' and not host.endswith('.urban3p.ru'):
            raise
        mirror = parsed._replace(netloc=host.removesuffix('.ru') + '.com').geturl()
        if not supported(mirror):
            raise
        return _download_image(mirror)


def _download_image(url):
    headers = {'User-Agent': 'UrbexFinder/1.0 (open-source photo cache)'}
    if urlparse(url).hostname == 'upload.wikimedia.org':
        headers['Referer'] = 'https://commons.wikimedia.org/'
    connect_timeout = 8 if urlparse(url).hostname == 'photos.wikimapia.org' else 3
    with httpx.Client(timeout=httpx.Timeout(8, connect=connect_timeout), follow_redirects=False,
                      headers=headers) as client:
        with client.stream('GET', url) as response:
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError('Image redirects are not cached')
            data = bytearray()
            start = monotonic()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > MAX_PHOTO_BYTES or monotonic() - start > 12:
                    raise ValueError('Image download limit exceeded')
    return sanitize_photo(bytes(data))


class ExternalImages:
    def __init__(self, storage, fetch=download):
        self.storage, self.fetch = storage, fetch
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='external-images')
        self.slots = BoundedSemaphore(48)
        self.lock = Lock()
        self.jobs = OrderedDict()

    @staticmethod
    def key(digest):
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise DomainError('Фото не найдено', 404)
        return f'external-images/v1/{digest}.jpg'

    def copy(self, digest, url):
        try:
            key = self.key(digest)
            if not self.storage.exists(key):
                self.storage.put(key, self.fetch(url))
            return True
        except Exception:
            # A later gallery request retries failures; never cache an error as success.
            return False
        finally:
            self.slots.release()

    def schedule(self, digest, url):
        # Caller holds the lock. Keep queued URLs even when workers are busy.
        job = self.jobs.get(digest)
        retry = job and job[1] is not None and job[1].done() and not job[1].result() and monotonic() - job[2] > 60
        if job is None or job[1] is None or retry:
            future = None
            if self.slots.acquire(blocking=False):
                future = self.pool.submit(self.copy, digest, url)
            job = (url, future, monotonic())
            self.jobs[digest] = job
        self.jobs.move_to_end(digest)
        while len(self.jobs) > 512:
            self.jobs.popitem(last=False)
        return job

    def photos(self, photos):
        output = []
        for photo in photos:
            url = photo.get('image_url')
            if not supported(url):
                continue
            digest = sha256(url.encode()).hexdigest()
            thumbnail = photo.get('thumbnail_url')
            thumbnail_digest = digest
            # Cache actual Wikimapia previews independently. A missing original
            # must neither hide the preview nor replace the stored original.
            if thumbnail != url and supported(thumbnail):
                from .wikimapia import photo_url
                full, small = photo_url(url), photo_url(thumbnail)
                if (full and small and re.sub(r'_(?:\d+|big)(?=\.jpg$)', '', full)
                        == re.sub(r'_(?:\d+|big)(?=\.jpg$)', '', small)):
                    thumbnail_digest = sha256(thumbnail.encode()).hexdigest()
            with self.lock:
                if thumbnail_digest != digest:
                    self.schedule(thumbnail_digest, thumbnail)
                self.schedule(digest, url)
            output.append(dict(photo, original_image_url=url,
                               original_thumbnail_url=photo.get('thumbnail_url'),
                               image_url=f'/api/source-images/{digest}',
                               thumbnail_url=f'/api/source-images/{thumbnail_digest}'))
        return output

    def content(self, digest):
        key = self.key(digest)
        with self.lock:
            job = self.jobs.get(digest)
            if job:
                job = self.schedule(digest, job[0])
        if job:
            if job[1] is None:
                raise DomainError('Фотография ожидает загрузки в хранилище', 503)
            try:
                ready = job[1].result(timeout=1)
            except TimeoutError:
                ready = False
            if not ready:
                raise DomainError('Фотография загружается в хранилище. Повторите позже.', 503)
        try:
            return self.storage.get(key)
        except ClientError as exc:
            if not job and exc.response.get('Error', {}).get('Code') in {'NoSuchKey', '404'}:
                raise DomainError('Фото не найдено', 404) from None
            # An externally removed object can be re-created on the next request.
            if job and exc.response.get('Error', {}).get('Code') in {'NoSuchKey', '404'}:
                with self.lock:
                    self.jobs[digest] = (job[0], None, 0)
        except Exception:
            pass
        raise DomainError('Хранилище фотографий временно недоступно', 503)

    def close(self):
        self.pool.shutdown(wait=True)
