"""Bounded primary-page enrichment for known public catalog sites."""
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from html import unescape
import re
from threading import Lock
from time import monotonic
from urllib.parse import quote, unquote, urlparse
import httpx
from .osint_identity import extract_page_identity, source_key, verify_source
from .osint_profile import build_place_profile

_HOSTS = {'wikimapia.org', 'geocaching.su', 'urban3p.ru', 'urban3p.com',
          'swalker.ru', 'podmoskovnye.ru', 'planetadorog.ru',
          'ru.wikipedia.org', 'en.wikipedia.org'}
_cache = OrderedDict()
_lock = Lock()


def _fetch(url):
    # Exact allowlist, no redirects/credentials/ports: arbitrary search results
    # cannot make this fetcher follow a redirect into the internal network.
    parsed = urlparse(url)
    try:
        if (parsed.scheme not in {'http', 'https'} or parsed.hostname not in _HOSTS
                or parsed.username or parsed.password or parsed.port not in {None, 80, 443}):
            return None
    except ValueError:
        return None
    key = source_key(url)
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > monotonic(): return cached[1]
    evidence = None
    from .wikimapia import is_object_url, fetch_html
    if is_object_url(url):
        html = fetch_html(url)
        evidence = extract_page_identity(html, url) if html else None
        with _lock:
            _cache[key] = (monotonic() + (900 if evidence else 60), evidence)
            _cache.move_to_end(key)
            while len(_cache) > 128: _cache.popitem(last=False)
        return evidence
    if parsed.hostname in {'ru.wikipedia.org', 'en.wikipedia.org'}:
        evidence = _fetch_wikipedia(url)
        with _lock:
            _cache[key] = (monotonic() + (900 if evidence else 60), evidence)
            _cache.move_to_end(key)
            while len(_cache) > 128: _cache.popitem(last=False)
        return evidence
    try:
        with httpx.Client(timeout=httpx.Timeout(3, connect=2), follow_redirects=False) as client:
            with client.stream('GET', url) as response:
                if response.status_code == 200 and 'text/html' in response.headers.get('content-type', ''):
                    body = bytearray()
                    started = monotonic()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 1_000_000 or monotonic() - started > 3: break
                    else:
                        evidence = extract_page_identity(body.decode(response.encoding or 'utf-8', errors='replace'), url)
    except (httpx.HTTPError, ValueError, UnicodeError):
        pass
    with _lock:
        _cache[key] = (monotonic() + (900 if evidence else 60), evidence)
        _cache.move_to_end(key)
        while len(_cache) > 128: _cache.popitem(last=False)
    return evidence


def _fetch_wikipedia(url):
    parsed = urlparse(url)
    if parsed.path.startswith('/wiki/'):
        title = unquote(parsed.path[len('/wiki/'):]).replace('_', ' ').strip()
    else:
        return None
    if not title or ':' in title or len(title) > 200:
        return None
    host = parsed.hostname
    headers = {'User-Agent': 'UrbexFinder/1.0 (place photo verification)'}
    try:
        with httpx.Client(timeout=httpx.Timeout(5, connect=3), follow_redirects=False,
                          headers=headers) as client:
            response = client.get(
                f'https://{host}/w/api.php',
                params={
                    'action': 'query', 'format': 'json',
                    'prop': 'coordinates|pageimages|extracts',
                    'titles': title, 'colimit': 1, 'piprop': 'original',
                    'exintro': 1, 'explaintext': 1,
                },
            )
            response.raise_for_status()
            pages = response.json().get('query', {}).get('pages', {})
            page = next(iter(pages.values()), {})
            if not page or page.get('missing') is not None or page.get('ns') != 0:
                return None
            image_url = page.get('original', {}).get('source', '')
            image_parts = urlparse(image_url)
            if (image_parts.scheme != 'https' or image_parts.hostname != 'upload.wikimedia.org'
                    or not re.fullmatch(r'/wikipedia/commons/.+\.(?:jpe?g|png|webp)', image_parts.path, re.I)):
                return {
                    'source_key': source_key(url), 'title': page.get('title', ''),
                    'text': page.get('extract', ''),
                    **_wikipedia_coordinates(page),
                }

            filename = unquote(image_parts.path.rsplit('/', 1)[-1])
            commons = client.get(
                'https://commons.wikimedia.org/w/api.php',
                params={
                    'action': 'query', 'format': 'json',
                    'prop': 'imageinfo', 'iiprop': 'url|extmetadata',
                    'titles': f'File:{filename}',
                },
            )
            commons.raise_for_status()
            commons_pages = commons.json().get('query', {}).get('pages', {})
            file_info = next(iter(commons_pages.values()), {}).get('imageinfo', [{}])[0]
            metadata = file_info.get('extmetadata', {})
            license_name = _metadata_text(metadata.get('LicenseShortName', {}).get('value', ''))
            if not _open_commons_license(license_name):
                image_url = ''
            coordinates = _wikipedia_coordinates(page)
            image = None
            if image_url:
                file_title = f'File:{filename.replace(" ", "_")}'
                image = {
                    'image_url': image_url,
                    'title': _metadata_text(metadata.get('ImageDescription', {}).get('value', ''))
                             or page.get('title', ''),
                    'attribution': ' · '.join(part for part in (
                        'Wikimedia Commons',
                        _metadata_text(metadata.get('Artist', {}).get('value', '')),
                        license_name,
                    ) if part),
                    'license_url': metadata.get('LicenseUrl', {}).get('value', ''),
                    'source_url': f'https://commons.wikimedia.org/wiki/{quote(file_title, safe=":/()")}',
                }
            return {
                'source_key': source_key(url),
                'title': page.get('title', ''),
                'text': page.get('extract', ''),
                **coordinates,
                **({'wikipedia_image': image} if image else {}),
            }
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None


def _wikipedia_coordinates(page):
    coords = (page.get('coordinates') or [{}])[0]
    result = {}
    for field in ('lat', 'lon'):
        try:
            result['latitude' if field == 'lat' else 'longitude'] = float(coords[field])
        except (KeyError, TypeError, ValueError):
            pass
    return result


def _metadata_text(value):
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]*>', ' ', str(value or '')))).strip()


def _open_commons_license(value):
    license_name = value.strip().casefold()
    return (license_name in {'cc0', 'public domain'}
            or bool(re.fullmatch(r'cc by(?:-sa)?(?:\s+\d+(?:\.\d+)*)?', license_name)))


def wikipedia_photos_for_sources(sources, limit=12):
    photos = []
    seen = set()
    for source in sources:
        identity = source.get('page_identity') or {}
        image = identity.get('wikipedia_image') or {}
        image_url = image.get('image_url')
        source_url = source.get('url')
        key = source_key(source_url)
        if not image_url or not key or image_url in seen or len(photos) >= limit:
            continue
        seen.add(image_url)
        photos.append({
            'title': image.get('title') or identity.get('title') or source.get('title') or 'Фото объекта',
            'image_url': image_url,
            'thumbnail_url': image_url,
            'source_url': source_url,
            'image_source_url': image.get('source_url'),
            'engine': 'web_page',
            'gallery_scope': 'primary',
            'query': source_url,
            'page_identity': identity,
            'attribution': image.get('attribution'),
            'license_url': image.get('license_url'),
            'score': 15.0,
        })
    return photos


def enrich_candidates(place, candidates, reference_urls):
    profile = build_place_profile(place, reference_urls=reference_urls)
    rows = [dict(row) for row in candidates]
    from .wikimapia import is_object_url
    pending = []
    for row in rows:
        url = str(row.get('url') or '')
        if urlparse(url).hostname not in _HOSTS:
            continue
        identity = row.get('page_identity') or {}
        missing_coordinates = (
            is_object_url(url)
            and (identity.get('latitude') is None or identity.get('longitude') is None)
        )
        if verify_source(place, row, profile=profile).status == 'unconfirmed' or missing_coordinates:
            pending.append(row)
    def priority(row):
        score = row.get('reranker_score')
        if isinstance(score, (int, float)):
            return (0, -score, not profile.matches_name(row.get('title', '')))
        return (1, 0, not profile.matches_name(row.get('title', '')))

    pending.sort(key=priority)
    pending = pending[:4]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for row, evidence in zip(pending, pool.map(_fetch, [row.get('url', '') for row in pending])):
            if evidence: row['page_identity'] = evidence
    return rows
