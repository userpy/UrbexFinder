"""OSINT report built from SearXNG (XNG) search results for a place card."""
import logging
import threading
import time
from collections import OrderedDict
import httpx
from urbex.domain.rules import DomainError
from urbex.infrastructure.osint_assess import assess_osint_items

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_last_request = 0.0
_MAX_RESULTS = 12
_MAX_PHOTOS = 12
# Keep cold reports under the Next.js rewrite proxy budget (~30s).
_MAX_QUERIES = 2
_MAX_IMAGE_QUERIES = 2
_CACHE_SIZE = 256
# Only successful non-empty answers are cached. Empty answers must not stick forever
# when engines were temporarily down.
_search_cache: OrderedDict[tuple[str, str, str, str], tuple[dict, ...]] = OrderedDict()


def _coords(place: dict) -> tuple[float, float] | None:
    try:
        latitude = float(place['latitude'])
        longitude = float(place['longitude'])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-85 <= latitude <= 85 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def _queries_for(place: dict) -> list[str]:
    """Build SearXNG queries: by name, by coordinates, by short region."""
    name = (place.get('name') or '').strip()
    region = (place.get('region') or '').strip()
    address = (place.get('full_address') or '').strip()
    # Prefer short region; huge address strings make engines return noise/empty.
    location = region if region and len(region) <= 80 else (
        address if address and len(address) <= 80 else ''
    )
    coords = _coords(place)

    queries: list[str] = []
    if name:
        queries.append(name[:200])
    # Coordinates before long location — more useful under _MAX_QUERIES=2.
    if coords:
        latitude, longitude = coords
        point = f'{latitude:.5f}, {longitude:.5f}'
        queries.append((f'{name} {point}' if name else point)[:200])
    if location and location.casefold() != name.casefold():
        queries.append((f'{name} {location}' if name else location)[:200])

    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        unique.append(query)
        if len(unique) >= _MAX_QUERIES:
            break
    return unique


def _image_queries_for(place: dict) -> list[str]:
    """Image queries: name/region plus name+coordinates when available."""
    name = (place.get('name') or '').strip()
    region = (place.get('region') or '').strip()
    coords = _coords(place)
    queries: list[str] = []
    # Prefer short "name + region" over full address (address pulls real-estate noise).
    if name and region and len(region) <= 80:
        queries.append(f'{name} {region}'[:200])
    elif name:
        queries.append(name[:200])
    if coords:
        latitude, longitude = coords
        point = f'{latitude:.5f}, {longitude:.5f}'
        queries.append((f'{name} {point}' if name else point)[:200])
    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        unique.append(query)
        if len(unique) >= _MAX_IMAGE_QUERIES:
            break
    return unique


def _http_url(value: object) -> str | None:
    text = str(value or '').strip()
    if text.startswith(('http://', 'https://')):
        return text[:2000]
    return None


def _engines_for(category: str) -> str:
    # Pin engines that work from this Docker network; DDG/Google CSE often hang.
    if category == 'images':
        return 'bing images'
    return 'bing,wikipedia'


def _cache_get(key: tuple[str, str, str, str]) -> tuple[dict, ...] | None:
    with _lock:
        if key not in _search_cache:
            return None
        _search_cache.move_to_end(key)
        return _search_cache[key]


def _cache_put(key: tuple[str, str, str, str], value: tuple[dict, ...]) -> None:
    if not value:
        return
    with _lock:
        _search_cache[key] = value
        _search_cache.move_to_end(key)
        while len(_search_cache) > _CACHE_SIZE:
            _search_cache.popitem(last=False)


def clear_search_cache() -> None:
    with _lock:
        _search_cache.clear()


def _search(url: str, origin: str, query: str, category: str = 'general') -> tuple[dict, ...]:
    global _last_request
    cache_key = (url, origin, query, category)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # SearXNG waits on slow engines, then returns partial JSON — cut too early and we get empty/502.
    timeout = 15.0 if category == 'images' else 12.0
    with _lock:
        time.sleep(max(0, 0.25 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        try:
            response = httpx.get(
                url.rstrip('/') + '/search',
                params={
                    'q': query,
                    'format': 'json',
                    'language': 'ru',
                    'categories': category,
                    'engines': _engines_for(category),
                    'pageno': 1,
                },
                headers={'User-Agent': f'UrbexFinder/1.0 ({origin})'},
                timeout=timeout,
                follow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            raise DomainError('Не удалось получить данные SearXNG. Повторите попытку позже.', 502)
    results = payload.get('results') if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return ()
    parsed = _parse_images(results, query) if category == 'images' else _parse_general(results, query)
    _cache_put(cache_key, parsed)
    return parsed


def _search_soft(url: str, origin: str, query: str, category: str) -> tuple[dict, ...]:
    try:
        return _search(url, origin, query, category)
    except DomainError:
        _log.warning('OSINT %s search failed for %r', category, query)
        return ()


def _parse_general(results: list, query: str) -> tuple[dict, ...]:
    items = []
    for row in results:
        if not isinstance(row, dict):
            continue
        title = str(row.get('title') or '').strip()
        link = _http_url(row.get('url'))
        if not title or not link:
            continue
        items.append({
            'title': title[:300],
            'url': link,
            'snippet': str(row.get('content') or '').strip()[:600],
            'engine': str(row.get('engine') or '').strip()[:80] or None,
            'category': str(row.get('category') or '').strip()[:40] or None,
            'score': float(row['score']) if isinstance(row.get('score'), (int, float)) else None,
            'query': query,
        })
    return tuple(items)


def _parse_images(results: list, query: str) -> tuple[dict, ...]:
    items = []
    for row in results:
        if not isinstance(row, dict):
            continue
        image = _http_url(row.get('img_src')) or _http_url(row.get('thumbnail_src'))
        thumbnail = _http_url(row.get('thumbnail_src')) or image
        source = _http_url(row.get('url')) or _http_url(row.get('source')) or image
        if not image or not source:
            continue
        title = str(row.get('title') or '').strip() or 'Фото из открытых источников'
        items.append({
            'title': title[:300],
            'image_url': image,
            'thumbnail_url': thumbnail,
            'source_url': source,
            'engine': str(row.get('engine') or '').strip()[:80] or None,
            'score': float(row['score']) if isinstance(row.get('score'), (int, float)) else None,
            'query': query,
        })
    return tuple(items)


def _sources_from_photos(photos: list[dict]) -> list[dict]:
    """When general search is empty, still surface photo landing pages as sources."""
    items: list[dict] = []
    seen: set[str] = set()
    for photo in photos:
        url = str(photo.get('source_url') or '').rstrip('/').casefold()
        if not url or url in seen:
            continue
        seen.add(url)
        items.append({
            'title': photo.get('title') or 'Источник фото',
            'url': photo['source_url'],
            'snippet': 'Страница источника изображения из открытого поиска.',
            'engine': photo.get('engine'),
            'category': 'images',
            'score': photo.get('score'),
            'query': photo.get('query') or '',
        })
        if len(items) >= _MAX_RESULTS:
            break
    return items


def _merge(results: list[tuple[dict, ...]], key_name: str, limit: int) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for batch in results:
        for item in batch:
            key = str(item[key_name]).rstrip('/').casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(dict(item))
            if len(merged) >= limit:
                return merged
    return merged


def build_osint_report(url: str, origin: str, place: dict) -> dict:
    if not url:
        raise DomainError('Сервис OSINT-поиска (SearXNG) не настроен', 503)
    queries = _queries_for(place)
    if not queries:
        raise DomainError('Недостаточно данных места для поиска', 422)
    image_queries = (_image_queries_for(place) or queries[:1])[:_MAX_IMAGE_QUERIES]

    general_batches: list[tuple[dict, ...]] = []
    for query in queries:
        # Soft-fail each query: one timed-out engine family must not blank the report.
        batch = _search_soft(url, origin, query, 'general')
        general_batches.append(batch)
        if sum(len(rows) for rows in general_batches) >= _MAX_RESULTS:
            break

    image_batches = [
        _search_soft(url, origin, query, 'images') for query in image_queries
    ]

    merged = _merge(general_batches, 'url', _MAX_RESULTS)
    photos = _merge(image_batches, 'image_url', _MAX_PHOTOS)
    if not merged and photos:
        merged = _sources_from_photos(photos)
    if not merged and not photos:
        # Distinguishes "SearXNG down" from "nothing relevant found".
        probe = _search_soft(url, origin, queries[0], 'general')
        if not probe:
            raise DomainError('Не удалось получить данные SearXNG. Повторите попытку позже.', 502)
        general_batches = [probe]
        merged = _merge(general_batches, 'url', _MAX_RESULTS)

    merged.sort(key=lambda item: (-(item['score'] or 0), item['title']))
    photos.sort(key=lambda item: (-(item['score'] or 0), item['title']))
    return {
        'place_id': place['id'],
        'place_name': place.get('name'),
        'queries': queries,
        'image_queries': image_queries,
        'source': 'searxng',
        'total': len(merged),
        'items': merged,
        'photos': photos,
        'photos_total': len(photos),
        'assessment': assess_osint_items(merged),
    }
