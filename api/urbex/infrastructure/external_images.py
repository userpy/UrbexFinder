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

# Exact trusted image origins; unknown origins retain their original URLs.
HOSTS = frozenset({
    'avatars.mds.yandex.net', 'photos.wikimapia.org', 'geocaching.su',
    'www.geocaching.su', 'geocaching.ru', 'www.geocaching.ru',
    'podmoskovnye.ru', 'www.podmoskovnye.ru', 'upload.wikimedia.org',
    'img.urban3p.ru', 'img01.urban3p.ru', 'img02.urban3p.ru',
    'img03.urban3p.ru', 'img04.urban3p.ru', 'swalker.ru',
    'planetadorog.ru', 'www.planetadorog.ru', 's3.dzeninfra.ru',
})


def supported(url):
    try:
        p = urlparse(url)
        return (p.scheme in {'http', 'https'} and p.hostname in HOSTS
                and not p.username and not p.password and p.port in {None, 80, 443})
    except (ValueError, TypeError):
        return False


def download(url):
    if not supported(url):
        raise ValueError('Unsupported image origin')
    with httpx.Client(timeout=httpx.Timeout(8, connect=3), follow_redirects=False) as client:
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

    def photos(self, photos):
        output = []
        for photo in photos:
            url = photo.get('image_url')
            if not supported(url):
                output.append(dict(photo))
                continue
            digest = sha256(url.encode()).hexdigest()
            with self.lock:
                job = self.jobs.get(digest)
                if job and job[1].done() and not job[1].result() and monotonic() - job[2] > 60:
                    del self.jobs[digest]
                    job = None
                if job is None and self.slots.acquire(blocking=False):
                    job = (url, self.pool.submit(self.copy, digest, url), monotonic())
                    self.jobs[digest] = job
                if job:
                    self.jobs.move_to_end(digest)
                while len(self.jobs) > 512:
                    self.jobs.popitem(last=False)
            if job:
                output.append(dict(photo, original_image_url=url,
                                   original_thumbnail_url=photo.get('thumbnail_url'),
                                   image_url=f'/api/source-images/{digest}',
                                   thumbnail_url=f'/api/source-images/{digest}'))
            else:
                output.append(dict(photo))
        return output

    def content(self, digest):
        key = self.key(digest)
        with self.lock:
            job = self.jobs.get(digest)
        if job:
            try:
                job[1].result(timeout=15)
            except TimeoutError:
                return None, job[0]
        try:
            return self.storage.get(key), None
        except ClientError as exc:
            if not job and exc.response.get('Error', {}).get('Code') in {'NoSuchKey', '404'}:
                raise DomainError('Фото не найдено', 404) from None
        except Exception:
            pass
        if job:
            return None, job[0]
        raise DomainError('Хранилище фотографий временно недоступно', 503)

    def close(self):
        self.pool.shutdown(wait=True)
