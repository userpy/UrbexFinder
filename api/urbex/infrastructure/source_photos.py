"""Load the linked cache gallery without running a general web search."""
from collections import OrderedDict
from threading import Lock
from time import monotonic
from urllib.parse import urlparse
import re

from urbex.domain.rules import DomainError
from .osint_description import links_from_description, generic_page_photos_for_links

_cache = OrderedDict()
_lock = Lock()


def source_photos(place: dict, saved_report: dict | None = None) -> list[dict]:
    links = [link for link in links_from_description(str(place.get('description') or ''))
             if (urlparse(link['url']).hostname or '').lower() in {
                 'geocaching.su', 'www.geocaching.su', 'geocaching.ru', 'www.geocaching.ru',
             }][:2]
    if not links:
        return []
    # Reports persist the provenance of each image. Reuse only the gallery
    # linked by this card, never general search results or another cache.
    source_urls = {link['url'].rstrip('/') for link in links}
    saved = []
    seen = set()
    for photo in (saved_report or {}).get('photos', []):
        image = urlparse(str(photo.get('image_url') or ''))
        if (photo.get('engine') == 'geocache'
                and str(photo.get('source_url') or '').rstrip('/') in source_urls
                and image.scheme in {'http', 'https'}
                and image.hostname in {'geocaching.su', 'www.geocaching.su', 'geocaching.ru', 'www.geocaching.ru'}
                and re.fullmatch(r'/photos/areas/\d+\.(?:jpe?g|png|webp)', image.path, re.IGNORECASE)
                and image.geturl() not in seen):
            seen.add(image.geturl())
            saved.append(photo)
    if saved:
        return saved[:12]
    key = tuple(link['url'] for link in links)
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > monotonic():
            _cache.move_to_end(key)
            if cached[1] is None:
                raise DomainError('Не удалось загрузить фото Geocaching. Повторите позже.', 502)
            return cached[1]
    photos = generic_page_photos_for_links(links, limit=12, max_pages=2)
    # An empty response can be a temporary source failure; never label it as
    # proof that the linked cache has no photos, and retry after a short cooldown.
    with _lock:
        _cache[key] = (monotonic() + (900 if photos else 30), photos or None)
        _cache.move_to_end(key)
        while len(_cache) > 256:
            _cache.popitem(last=False)
    if not photos:
        raise DomainError('Не удалось загрузить фото Geocaching. Повторите позже.', 502)
    return photos
