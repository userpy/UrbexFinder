"""Find a nearby object's gallery without adding links to its description."""
from collections import OrderedDict
from threading import Lock
from time import monotonic

from urbex.domain.rules import DomainError
from .osint import _search, _search_location
from .osint_description import wikimapia_photos_for_links
from .osint_identity import (
    coordinates, distance, name_cues, source_key, verify_report, words_present,
)
from .wikimapia import object_url

_cache = OrderedDict()
_lock = Lock()
# Collapse concurrent requests for the same card without holding the cache lock
# during network I/O. Different cards can still load concurrently.
_requests = [Lock() for _ in range(32)]


def discover_photos(place: dict, search_url: str, origin: str) -> list[dict]:
    if not search_url or not str(place.get('name') or '').strip() or not coordinates(place):
        return []
    key = (search_url, origin, *(str(place.get(field) or '') for field in (
        'name', 'description', 'latitude', 'longitude', 'full_address', 'region',
        'category', 'category_name',
    )))
    with _requests[hash(key) % len(_requests)]:
        with _lock:
            cached = _cache.get(key)
            if cached and cached[0] > monotonic():
                _cache.move_to_end(key)
                if cached[1] is None:
                    raise DomainError('Фото источника временно недоступны. Повторите позже.', 502)
                return list(cached[1])
        try:
            photos = _discover(place, search_url, origin)
        except DomainError:
            _remember(key, None, 30)
            raise
        _remember(key, tuple(photos), 900 if photos else 30)
        return photos


def _remember(key, photos, ttl):
    with _lock:
        _cache[key] = (monotonic() + ttl, photos)
        _cache.move_to_end(key)
        while len(_cache) > 256:
            _cache.popitem(last=False)


def _discover(place, search_url, origin):
    subject = ' '.join((str(place['name']).strip(), _search_location(place))).strip()
    rows = _search(search_url, origin, f'{subject[:180]} site:wikimapia.org')
    cues = name_cues(place['name'])
    seen = set()
    missing_gallery = False
    for row in rows:
        url = object_url(str(row.get('url') or ''))
        if not url or (cues and not words_present(cues, row.get('title', ''))):
            continue
        key = source_key(url)
        if key in seen:
            continue
        if len(seen) >= 4:
            break
        seen.add(key)
        # Page extraction supplies both photos and primary-object coordinates;
        # search snippets alone cannot authorize a gallery.
        gallery = wikimapia_photos_for_links([{'url': url}], 12)
        if not gallery:
            missing_gallery = True
            continue
        nearby = []
        for photo in gallery:
            identity = photo.get('page_identity') or {}
            point = coordinates(identity)
            if (identity.get('source_key') == key
                    and source_key(photo.get('source_url')) == key
                    and point and distance(coordinates(place), point) <= 100):
                nearby.append(photo)
        photos = verify_report({'photos': nearby}, place, [])['photos']
        if photos:
            return photos
    if missing_gallery:
        raise DomainError('Фото источника временно недоступны. Повторите позже.', 502)
    return []
