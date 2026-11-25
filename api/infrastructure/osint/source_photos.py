"""Combine linked galleries with verified photos discovered by the report."""
from collections import OrderedDict
from threading import Lock
from time import monotonic
from urllib.parse import urlparse
import re

from domain.rules import DomainError
from .osint_identity import verify_report, source_key, diverse_photos
from .wikimapia_discovery import discover_photos
from .wikimapia import direct_photos
from .osint_description import (
    links_from_description,
    generic_page_photos_for_links,
    urban3p_photos_for_links,
    vk_photos_for_links,
    wikimapia_photos_for_links,
)

_cache = OrderedDict()
_lock = Lock()


def source_photos(place: dict, saved_report: dict | None = None, *, vk_token: str = '',
                  search_url: str = '', origin: str = '') -> list[dict]:
    failure = None
    try:
        photos = _linked_photos(place, saved_report, vk_token=vk_token)
    except DomainError as exc:
        photos, failure = [], exc
    if any(photo.get('engine') == 'wikimapia' for photo in photos):
        return photos
    # A populated VK/Urban3P gallery must not suppress automatic Wikimapia
    # discovery. Keep working sources visible if the additional source fails.
    try:
        discovered = discover_photos(place, search_url, origin)
    except DomainError:
        if not photos:
            if failure:
                raise failure
            raise
        discovered = []
    if not photos and not discovered and failure:
        raise failure
    return diverse_photos(photos + discovered)


def _linked_photos(place: dict, saved_report: dict | None = None, *, vk_token: str = '') -> list[dict]:
    description_links = links_from_description(str(place.get('description') or ''))
    links = [link for link in description_links
             if (urlparse(link['url']).hostname or '').lower() in {
                 'geocaching.su', 'www.geocaching.su', 'geocaching.ru', 'www.geocaching.ru',
                 'podmoskovnye.ru', 'www.podmoskovnye.ru',
                 'vk.com', 'www.vk.com', 'm.vk.com', 'vk.ru', 'www.vk.ru', 'm.vk.ru',
                 'urban3p.ru', 'www.urban3p.ru', 'urban3p.com', 'www.urban3p.com',
                 'wikimapia.org', 'www.wikimapia.org',
             }][:4]
    references = [link['url'] for link in description_links]
    checked_photos = direct_photos(description_links)
    checked_items = []
    if saved_report:
        checked = verify_report(saved_report, place, references)
        checked_photos = checked['photos'] + checked_photos
        checked_items = checked['items']
        seen_sources = {source_key(link['url']) for link in links}
        for source in checked_items:
            if len(links) >= 4:
                break
            candidate = links_from_description(str(source.get('url') or ''))
            if not candidate or candidate[0]['category'] not in {'urban3p', 'wikimapia'}:
                continue
            link = candidate[0]
            key = source_key(link['url'])
            if not key or key in seen_sources:
                continue
            link['title'] = source.get('title') or link['title']
            links.append(link)
            seen_sources.add(key)
    if not links:
        return diverse_photos(checked_photos)
    # Reuse only photos whose source and gallery membership pass verification.
    source_urls = {link['url'].rstrip('/') for link in links}
    podmoskovnye = {source_key(link['url']) for link in links
                    if (urlparse(link['url']).hostname or '').removeprefix('www.') == 'podmoskovnye.ru'}
    def verified_podmoskovnye(report):
        verified = verify_report(report, place, [link['url'] for link in links])
        return [photo for photo in verified['photos']
                if source_key(photo.get('source_url')) in podmoskovnye]
    urban = [link for link in links if link.get('category') == 'urban3p']
    urban_keys = {source_key(link['url']) for link in urban}
    urban_saved = [photo for photo in checked_photos
                   if source_key(photo.get('source_url')) in urban_keys]
    vk = [link for link in links if link.get('category') == 'vk']
    vk_keys = {source_key(link['url']) for link in vk}
    vk_saved = [photo for photo in checked_photos
                if source_key(photo.get('source_url')) in vk_keys]
    wikimapia = [link for link in links if link.get('category') == 'wikimapia']
    wikimapia_keys = {source_key(link['url']) for link in wikimapia}
    wikimapia_saved = [photo for photo in checked_photos
                       if source_key(photo.get('source_url')) in wikimapia_keys]
    saved = list(checked_photos)
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
    if (saved and (not urban or urban_saved) and (not vk or vk_saved)
            and (not wikimapia or wikimapia_saved)):
        return diverse_photos(saved)
    key = (tuple(link['url'] for link in links), bool(vk_token))
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > monotonic():
            _cache.move_to_end(key)
            if cached[1] is None and not saved:
                raise DomainError('Не удалось загрузить фото источника. Повторите позже.', 502)
            return diverse_photos((cached[1] or []) + saved)
    photos = []
    if urban:
        fetched_urban = urban3p_photos_for_links(urban, 12)
        photos += verify_report(
            {'items': checked_items + urban, 'photos': fetched_urban},
            place, references,
        )['photos']
    if wikimapia:
        fetched_wikimapia = wikimapia_photos_for_links(wikimapia, 12)
        photos += verify_report(
            {'items': checked_items + wikimapia, 'photos': fetched_wikimapia},
            place, references,
        )['photos']
    if vk:
        fetched_vk = vk_photos_for_links(vk_token, vk, 12)
        photos += verify_report({'photos': fetched_vk}, place, references)['photos']
    other_links = [
        link for link in links
        if link not in urban and link not in vk and link not in wikimapia
    ]
    if other_links:
        photos += generic_page_photos_for_links(other_links, limit=12, max_pages=2)
    if podmoskovnye:
        verified = verified_podmoskovnye({'photos': photos})
        photos = [photo for photo in photos if source_key(photo.get('source_url')) not in podmoskovnye] + verified
    # An empty response can be a temporary source failure; never label it as
    # proof that a linked source has no photos. Cache partial galleries briefly.
    available = photos + saved
    complete = (
        (not urban or any(photo.get('engine') == 'urban3p'
                         and source_key(photo.get('source_url')) in urban_keys for photo in available))
        and (not vk or any(photo.get('engine') == 'vk'
                           and source_key(photo.get('source_url')) in vk_keys for photo in available))
        and (not wikimapia or any(photo.get('engine') == 'wikimapia'
                                  and source_key(photo.get('source_url')) in wikimapia_keys
                                  for photo in available))
    )
    with _lock:
        _cache[key] = (monotonic() + (900 if complete else 30), photos or None)
        _cache.move_to_end(key)
        while len(_cache) > 256:
            _cache.popitem(last=False)
    photos = diverse_photos(photos + saved)
    if not photos:
        raise DomainError('Не удалось загрузить фото источника. Повторите позже.', 502)
    return photos
