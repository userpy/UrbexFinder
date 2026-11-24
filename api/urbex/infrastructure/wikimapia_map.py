"""Read public Wikimapia object metadata around a point, without an API key.

The site's interactive map uses /z1/itiles/{quadkey}.xy. Rows contain an
object ID, bounding box and translated names even when its HTML page is broken.
Only those fields are used; map tiles themselves are never treated as photos.
"""
from math import asinh, cos, floor, pi, radians, tan
import re
from urllib.parse import urljoin, urlparse

import httpx

from urbex.domain.rules import DomainError
from .osint_identity import coordinates, distance

_PATH = re.compile(r'/z1/itiles/(?:[0-3]{3}/)*[0-3]{1,3}\.xy')


def _tile_paths(latitude, longitude):
    depth = 12
    paths = set()
    dy = 100 / 111320
    dx = dy / max(cos(radians(latitude)), 0.001)
    for lat in (latitude - dy, latitude + dy):
        for lon in (longitude - dx, longitude + dx):
            lat = min(85.051128, max(-85.051128, lat))
            lon = (lon + 180) % 360 - 180
            x = floor((lon + 180) / 360 * (1 << depth))
            y = floor((1 + asinh(tan(radians(lat))) / pi) / 2 * (1 << depth))
            quad = '0' + ''.join(str(((x >> bit) & 1) + 2 * ((y >> bit) & 1))
                                 for bit in range(depth - 1, -1, -1))
            paths.add('/z1/itiles/' + '/'.join(quad[i:i+3] for i in range(0, len(quad), 3)) + '.xy')
    return sorted(paths)


def _fetch_tile(path):
    target = 'https://wikimapia.org' + path
    with httpx.Client(timeout=httpx.Timeout(8, connect=5),
                      transport=httpx.HTTPTransport(retries=1),
                      follow_redirects=False) as client:
        for _ in range(3):
            with client.stream('GET', target) as response:
                if response.is_redirect:
                    redirect = urlparse(urljoin(target, response.headers.get('location', '')))
                    if (redirect.scheme not in {'https', 'http'} or redirect.hostname != 'wikimapia.org'
                            or redirect.username or redirect.password or redirect.port not in {None, 80, 443}
                            or not _PATH.fullmatch(redirect.path)):
                        raise ValueError('Unexpected map redirect')
                    target = 'https://wikimapia.org' + redirect.path
                    continue
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 1_000_000:
                        raise ValueError('Map response too large')
                return body.decode('utf-8')
    raise ValueError('Too many map redirects')


def _parse_tile(body, point):
    lines = body.splitlines()
    if not lines or not re.fullmatch(r'0[0-3]*\|[01]\|\d+', lines[0]):
        raise ValueError('Invalid map response')
    result = []
    # Split on newline only: title translations use the ASCII unit separator.
    for line in body.split('\n')[1:]:
        fields = line.split('|', 7)
        if len(fields) < 7 or not fields[0].isdigit():
            continue
        try:
            left, right, bottom, top = (int(n) / 1e7 for n in fields[2].split(','))
            if not (-180 <= left <= right <= 180 and -90 <= bottom <= top <= 90):
                continue
            identity = {'latitude': (bottom + top) / 2, 'longitude': (left + right) / 2}
            metres = distance(point, coordinates(identity))
            if metres > 100:
                continue
            titles = {ord(t[0]) - 32: t[1:] for t in fields[5].split('\x1f') if len(t) > 1}
            title = titles.get(1) or titles.get(0) or next(iter(titles.values()), '')
            if not title:
                continue
            result.append(dict(identity, source_key='wikimapia.org:' + fields[0],
                               url=f'https://wikimapia.org/{fields[0]}/ru/', title=title,
                               distance=metres))
        except (ValueError, TypeError):
            continue
    return result


def nearby_places(place):
    point = coordinates(place)
    if not point:
        return []
    rows = {}
    failed = False
    for path in _tile_paths(*point):
        try:
            for row in _parse_tile(_fetch_tile(path), point):
                rows[row['source_key']] = row
        except (httpx.HTTPError, ValueError):
            failed = True
    if failed and not rows:
        raise DomainError('Данные карты Wikimapia временно недоступны.', 502)
    return sorted(rows.values(), key=lambda row: row['distance'])[:12]
