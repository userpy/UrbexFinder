"""Bounded image relay for Urban3P's intermittently unavailable image hosts."""
from functools import lru_cache
import re
import httpx
from domain.rules import DomainError

_IMAGE = re.compile(r'https?://(img(?:0[1-4])?)\.urban3p\.(?:ru|com)/up/o/(\d+)/(gallery/)?(photo|\d+)(_p)?\.jpg(?:\?.*)?$', re.I)
_MAX_BYTES = 2 * 1024 * 1024


def relay_report_images(report):
    def relay(url):
        match = _IMAGE.fullmatch(str(url or ''))
        if not match:
            return url
        host, oid, gallery, name, thumb = match.groups()
        # Cached generic-parser entries may still point to 64px thumbnails.
        filename = name + '.jpg'
        return f'/api/osint/urban3p/{host}/{oid}/{"gallery" if gallery else "cover"}/{filename}'
    return dict(report, photos=[dict(photo,
        image_url=relay(photo.get('image_url')),
        thumbnail_url=relay(photo.get('thumbnail_url')),
    ) for photo in report.get('photos', [])])


@lru_cache(maxsize=64)
def fetch_image(host: str, oid: int, kind: str, filename: str) -> bytes:
    if (not re.fullmatch(r'img(?:0[1-4])?', host) or oid <= 0
            or kind not in {'gallery', 'cover'}
            or not re.fullmatch(r'(?:photo|\d+)(?:_p)?\.jpg', filename)):
        raise DomainError('Некорректная ссылка на фото', 422)
    path = 'gallery/' if kind == 'gallery' else ''
    urls = [f'https://{host}.urban3p.{domain}/up/o/{oid}/{path}{filename}' for domain in ('ru', 'com')]
    for url in urls:
        try:
            with httpx.Client(timeout=httpx.Timeout(10, connect=4)) as client:
                with client.stream('GET', url) as response:
                    response.raise_for_status()
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > _MAX_BYTES:
                            raise DomainError('Фотография слишком большая', 502)
                    if not data.startswith(b'\xff\xd8\xff'):
                        raise DomainError('Источник вернул не фотографию', 502)
                    return bytes(data)
        except (httpx.HTTPError, DomainError):
            continue
    # The same browser TLS profile is used by the existing Urban3P scraper.
    # Some CDN connections reject OpenSSL while accepting a browser handshake.
    for url in urls:
        try:
            from curl_cffi import requests
            response = requests.get(url, impersonate='chrome136', timeout=6, allow_redirects=False)
            data = response.content
            if response.status_code == 200 and len(data) <= _MAX_BYTES and data.startswith(b'\xff\xd8\xff'):
                return data
        except Exception:
            pass
    raise DomainError('Urban3P временно не отдаёт фотографию', 502)
