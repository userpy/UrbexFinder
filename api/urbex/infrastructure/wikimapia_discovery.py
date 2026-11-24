"""Find a nearby object's gallery without adding links to its description."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import monotonic
import re

from urbex.domain.rules import DomainError
from .osint import _search
from .osint_profile import build_place_profile, search_text
from .osint_description import wikimapia_photos_for_links
from .osint_identity import (
    coordinates, distance, kinds, name_cues, source_key, verify_report, verify_source, normalized,
)
from .wikimapia import object_url
from .wikimapia_map import nearby_places

_cache = OrderedDict()
_lock = Lock()
# Collapse concurrent requests for the same card without holding the cache lock
# during network I/O. Different cards can still load concurrently.
_requests = [Lock() for _ in range(32)]
# A process-wide pool bounds source traffic across concurrent card requests.
_pages = ThreadPoolExecutor(max_workers=3, thread_name_prefix='wikimapia-discovery')
_STATE_WORDS = re.compile(
    r'\b(?:(?:полу)?заброшенн[а-я]*|бывш(?:ий|ая|ее|ие)|стар(?:ый|ая|ое|ые))\b', re.I,
)


def discover_photos(place: dict, search_url: str, origin: str) -> list[dict]:
    profile = build_place_profile(place)
    if not profile.name or not profile.point:
        return []
    key = (search_url, origin, profile)
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


def _search_queries(place):
    profile = build_place_profile(place)
    name = profile.search_name
    compact = re.sub(r'\s+', ' ', _STATE_WORDS.sub('', name)).strip()
    location = ' '.join(dict.fromkeys(part for part in (profile.settlement, profile.region) if part))
    # An imported address may contain only an administrative district, without
    # a settlement. Keep that useful local cue in the fallback search.
    district = re.search(
        r'([А-ЯЁа-яё-]+)\s+(?:муниципальный|городской)\s+(?:округ|район)',
        str(place.get('full_address') or place.get('region') or ''), re.I,
    )
    local = district[1] if district else location
    suffix = re.split(r'\s+(?:у|возле|рядом\s+с)\s+', compact, flags=re.I)[-1]
    lat, lon = profile.point
    subjects = [f'{name[:180]} {location}',
                *(f'{search_text(alias, max_len=180)} {location}' for alias in profile.aliases[:2]),
                f'{compact[:180]} {local}',
                f'{suffix[:180]} {local}', f'{compact[:150]} {lat:.5f} {lon:.5f}']
    return list(dict.fromkeys(' '.join(s.split()) + ' site:wikimapia.org' for s in subjects))


def _candidate_rank(row, place):
    # Search titles are often truncated or empty; rank them, never treat them
    # as authoritative identity or require every word before opening the page.
    profile = build_place_profile(place)
    title = set(re.findall(r'[а-яa-z0-9]+', normalized(row.get('title'))))
    return max((len(name_cues(_STATE_WORDS.sub('', name)) & title)
                for name in profile.identity_names), default=0)


def _map_name_matches(place, identity):
    source = {'url': identity['url'], 'page_identity': identity}
    decision = verify_source(place, source)
    if decision.status == 'accepted':
        return True
    if decision.status == 'rejected':
        return False
    # Imported camp titles can include a former owner after the camp's name.
    # Match the quoted camp name, never a quoted factory name or a nearby
    # building. Retain the full-title conflict checks above and the 100 m gate.
    point, candidate_point = coordinates(place), coordinates(identity)
    if (point and candidate_point and distance(point, candidate_point) <= 100
            and 'camp' in kinds(identity['title'])):
        camp = re.search(
            r'\b(?:лагер[а-я]*|пионерлагер[а-я]*)\s+(?:отдыха\s+)?[«"„“]([^»"“”]+)[»"“”]',
            str(place['name']), re.I,
        )
        if camp and name_cues(camp[1]):
            named_camp = dict(place, name=f'Лагерь «{camp[1]}»')
            if verify_source(named_camp, source).status == 'accepted':
                return True
    def tokens(value):
        value = normalized(_STATE_WORDS.sub('', str(value)))
        value = re.sub(r'\bртц\b', 'радиотехнический центр', value)
        return set(re.findall(r'[а-яa-z0-9]+', value)) - {'у', 'на', 'в', 'и', 'ru', 'en'}
    title = tokens(identity['title'])
    name = str(place['name'])
    variants = [name, re.split(r'\s+(?:у|возле|рядом\s+с)\s+', name, flags=re.I)[-1]]
    return any(len(cues := tokens(variant)) >= 2 and cues <= title for variant in variants)


def _map_gallery(place, rows):
    candidates = [row for row in rows if _map_name_matches(place, row)][:2]
    for row in candidates:
        gallery = wikimapia_photos_for_links([{'url': row['url']}], 12)
        photos = []
        for photo in gallery:
            primary = dict(photo.get('page_identity') or {})
            key = row['source_key']
            if primary.get('source_key') != key or source_key(photo.get('source_url')) != key:
                continue
            # Both metadata records came from this exact Wikimapia object.
            # Fill gaps in an RK n.22 page; never overwrite conflicting data.
            if not str(primary.get('title') or '').strip():
                primary['title'] = row['title']
            for field in ('latitude', 'longitude'):
                if primary.get(field) in (None, ''):
                    primary[field] = row[field]
            if (not coordinates(primary) or distance(coordinates(place), coordinates(primary)) > 100
                    or not _map_name_matches(place, dict(primary, url=row['url']))):
                continue
            photos.append(dict(photo, page_identity=primary, match_method='name_coordinates'))
        # Only independently matched map metadata grants a reference here.
        # The normal verifier still rejects conflicting types/addresses.
        verified = verify_report({'photos': photos}, place, [row['url']])['photos']
        if verified:
            return verified
    return []


def _discover(place, search_url, origin):
    queries = _search_queries(place) if search_url else []
    seen = set()
    missing_gallery = False
    search_failed = False
    try:
        mapped = _map_gallery(place, nearby_places(place))
        if mapped:
            return mapped
    except DomainError:
        search_failed = True
    compact_place = dict(place, name=re.sub(r'\s+', ' ', _STATE_WORDS.sub('', place['name'])).strip())
    for query in queries:
        if len(seen) >= 8:
            break
        try:
            rows = _search(search_url, origin, query)
        except DomainError:
            search_failed = True
            continue
        candidates = []
        for row in sorted(rows, key=lambda row: _candidate_rank(row, place), reverse=True):
            url = object_url(str(row.get('url') or ''))
            key = source_key(url) if url else ''
            if not key or key in seen:
                continue
            seen.add(key)
            candidates.append((key, url))
            # Reserve a page budget for later, less restrictive queries.
            if len(candidates) >= 2 or len(seen) >= 8:
                break
        jobs = [_pages.submit(wikimapia_photos_for_links, [{'url': url}], 12)
                for _, url in candidates]
        matches = []
        for (key, _), job in zip(candidates, jobs):
            gallery = job.result()
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
            if not photos and compact_place['name'] != place['name']:
                photos = verify_report({'photos': nearby}, compact_place, [])['photos']
            if photos:
                metres = distance(coordinates(place), coordinates(photos[0]['page_identity']))
                matches.append((metres, photos))
        if matches:
            return min(matches, key=lambda match: match[0])[1]
    if missing_gallery or search_failed:
        raise DomainError('Фото источника временно недоступны. Повторите позже.', 502)
    return []
