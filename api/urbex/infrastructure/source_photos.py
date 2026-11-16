"""Load the linked cache gallery without running a general web search."""
from collections import OrderedDict
from threading import Lock
from time import monotonic
from urllib.parse import urlparse
import re

from urbex.domain.rules import DomainError
from .osint_identity import verify_report, source_key
from .osint_description import links_from_description, generic_page_photos_for_links

_cache = OrderedDict()
_lock = Lock()


def source_photos(place: dict, saved_report: dict | None = None) -> list[dict]:
    links = [link for link in links_from_description(str(place.get('description') or ''))
             if (urlparse(link['url']).hostname or '').lower() in {
                 'geocaching.su', 'www.geocaching.su', 'geocaching.ru', 'www.geocaching.ru',
                 'podmoskovnye.ru', 'www.podmoskovnye.ru',
             }][:2]
    references = [link['url'] for link in links_from_description(str(place.get('description') or ''))]
    maps = []
    if saved_report:
        checked = verify_report(saved_report, place, references)
        maps = [photo for photo in checked['photos'] if photo.get('engine') == 'yandex_maps']
    if not links:
        return maps
    # Reports persist the provenance of each image. Reuse only the gallery
    # linked by this card, never general search results or another cache.
    source_urls = {link['url'].rstrip('/') for link in links}
    podmoskovnye = {source_key(link['url']) for link in links
                    if (urlparse(link['url']).hostname or '').removeprefix('www.') == 'podmoskovnye.ru'}
    def verified_podmoskovnye(report):
        verified = verify_report(report, place, [link['url'] for link in links])
        return [photo for photo in verified['photos']
                if source_key(photo.get('source_url')) in podmoskovnye]
    saved = maps + (verified_podmoskovnye(saved_report or {}) if podmoskovnye else [])
    seen = {photo['image_url'] for photo in saved}
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
                raise DomainError('Не удалось загрузить фото источника. Повторите позже.', 502)
            return cached[1]
    photos = generic_page_photos_for_links(links, limit=12, max_pages=2)
    if podmoskovnye:
        verified = verified_podmoskovnye({'photos': photos})
        photos = [photo for photo in photos if source_key(photo.get('source_url')) not in podmoskovnye] + verified
    # An empty response can be a temporary source failure; never label it as
    # proof that the linked cache has no photos, and retry after a short cooldown.
    with _lock:
        _cache[key] = (monotonic() + (900 if photos else 30), photos or None)
        _cache.move_to_end(key)
        while len(_cache) > 256:
            _cache.popitem(last=False)
    if not photos:
        raise DomainError('Не удалось загрузить фото источника. Повторите позже.', 502)
    return photos
