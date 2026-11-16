"""Trusted links from place.description, with optional VK / Dzen / Yandex Maps photos."""
from __future__ import annotations
import logging
import re
from urllib.parse import quote, unquote, urlencode, urlparse
import httpx

_log = logging.getLogger(__name__)
_LINK_RE = re.compile(
    r'\[([^\]\n]+)\]\(([^\s<>]+)\)|https?://[^\s<>"\']+',
    re.IGNORECASE,
)
_VK_HOSTS = frozenset({'vk.com', 'www.vk.com', 'm.vk.com', 'vk.ru', 'www.vk.ru', 'm.vk.ru'})
_DZEN_HOSTS = frozenset({
    'dzen.ru', 'www.dzen.ru', 'zen.yandex.ru', 'www.zen.yandex.ru',
})
_YMAPS_HOST_SUFFIXES = (
    'yandex.ru', 'yandex.com', 'yandex.by', 'yandex.kz', 'yandex.uz',
)
_VK_API = 'https://api.vk.com/method'
_VK_VERSION = '5.199'
_MAX_VK_PHOTOS = 12
_MAX_VK_SOURCES = 8
_MAX_VK_WALL_POSTS = 5
_VK_BROWSER_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}
_VK_JSON_URL_RE = re.compile(
    r'"url"\s*:\s*"(https:(?:\\/|/){2}(?:sun\d+-[\w.-]+|[\w.-]+)\.userapi\.com(?:\\/|/)[^"]+)"',
    re.IGNORECASE,
)
_VK_DESC_RE = re.compile(r'"description"\s*:\s*"((?:\\.|[^"\\]){8,800})"')
_VK_TEXT_RE = re.compile(r'"text"\s*:\s*"((?:\\.|[^"\\]){20,1200})"')
_VK_NAME_RE = re.compile(r'"name"\s*:\s*"((?:\\.|[^"\\]){2,200})"')
_VK_IMG_SKIP = (
    'emoji', 'sticker', 'deactivated', 'camera_50', 'camera_100',
    'gift', 'icon', 'logo', 'composite_activity',
)
_MAX_DZEN_PHOTOS = 12
_MAX_YMAPS_PHOTOS = 12
_MAX_URBAN3P_PHOTOS = 12
_URBAN3P_HOSTS = frozenset({'urban3p.ru', 'www.urban3p.ru'})
_URBAN3P_OBJECT_RE = re.compile(
    r'(?:https?:)?//(?:www\.)?urban3p\.ru/object(?P<oid>\d+)\b',
    re.IGNORECASE,
)
_URBAN3P_GALLERY_RE = re.compile(
    r'(?:https?:)?//(?P<host>img\d*\.urban3p\.ru)/up/o/(?P<oid>\d+)/gallery/(?P<pid>\d+)(?:_p)?\.jpg',
    re.IGNORECASE,
)
_URBAN3P_COVER_RE = re.compile(
    r'(?:https?:)?//(?P<host>img\d*\.urban3p\.ru)/up/o/(?P<oid>\d+)/photo\.jpg',
    re.IGNORECASE,
)
_URBAN3P_TITLE_RE = re.compile(
    r'<h1[^>]*>(.*?)</h1>',
    re.IGNORECASE | re.DOTALL,
)
_URBAN3P_BROWSER_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}
_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\']',
    re.IGNORECASE,
)
_DZEN_CDN_RE = re.compile(
    r'https://(?:avatars\.mds\.yandex\.net|s3\.dzeninfra\.ru)/[^"\\\s<>]+',
    re.IGNORECASE,
)
_DZEN_SKIP_FRAGMENTS = (
    'illustrations/404', 'favicon', 'logo', 'sprite', 'emoji', 'stub',
    'avatar/get', '/safe_image',
)
_YMAPS_ORG_RE = re.compile(
    r'/maps/org/(?P<slug>[^/]+)/(?P<oid>\d+)',
    re.IGNORECASE,
)
_YMAPS_ALTAY_RE = re.compile(
    r'https://avatars\.mds\.yandex\.net/get-altay/(?P<bucket>\d+)/(?P<photo>[0-9a-f]+)',
    re.IGNORECASE,
)
_YMAPS_BROWSER_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}
_YMAPS_NAME_STOP = frozenset({
    'лагерь', 'база', 'завод', 'фабрика', 'школа', 'дом', 'усадьба', 'парк',
    'площадка', 'территория', 'пионерский', 'детский', 'заброшенный', 'бывший',
    'бывшая', 'объект', 'место', 'здание', 'корпус', 'комплекс', 'центр',
})


def _http_url(value: object) -> str | None:
    text = str(value or '').strip()
    if not text.startswith(('http://', 'https://')):
        return None
    # Trim trailing punctuation often left from prose.
    text = text.rstrip(".,!?;:)}]\"'")
    try:
        parsed = urlparse(text)
    except ValueError:
        return None
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return None
    return text[:2000]


def links_from_description(description: str) -> list[dict]:
    """Extract markdown and bare http(s) links from a place description."""
    text = description or ''
    items: list[dict] = []
    seen: set[str] = set()
    for match in _LINK_RE.finditer(text):
        if match.group(1) is not None:
            label = (match.group(1) or '').strip() or 'Ссылка из описания'
            raw = match.group(2) or ''
        else:
            raw = match.group(0) or ''
            label = raw
        url = _http_url(raw)
        if not url:
            continue
        key = url.rstrip('/').casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append({
            'title': label[:300],
            'url': url,
            'snippet': 'Ссылка из описания места.',
            'engine': 'description',
            'category': (
                'vk' if _is_vk_url(url)
                else 'dzen' if _is_dzen_url(url)
                else 'yandex_maps' if _is_ymaps_url(url)
                else 'urban3p' if _is_urban3p_url(url)
                else 'link'
            ),
            'score': 10.0,
            'query': 'description',
        })
    return items


def _is_vk_url(url: str) -> bool:
    host = (urlparse(url).hostname or '').casefold()
    return host in _VK_HOSTS or host.endswith('.vk.com') or host.endswith('.vk.ru')


def _is_dzen_url(url: str) -> bool:
    host = (urlparse(url).hostname or '').casefold()
    return host in _DZEN_HOSTS or host.endswith('.dzen.ru') or host.endswith('.zen.yandex.ru')


def _is_urban3p_url(url: str) -> bool:
    host = (urlparse(url).hostname or '').casefold()
    return host in _URBAN3P_HOSTS or host.endswith('.urban3p.ru')


def _urban3p_object_id(url: str) -> str | None:
    match = _URBAN3P_OBJECT_RE.search(url or '')
    return match.group('oid') if match else None


def _is_ymaps_host(host: str) -> bool:
    host = (host or '').casefold()
    if not host:
        return False
    return any(host == suffix or host.endswith('.' + suffix) for suffix in _YMAPS_HOST_SUFFIXES)


def _is_ymaps_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or '').casefold()
    if not _is_ymaps_host(host):
        return False
    path = (parsed.path or '').casefold()
    return '/maps/' in path or host.startswith('maps.')


def _ymaps_org_from_url(url: str) -> tuple[str, str] | None:
    """Return (slug, org_id) for /maps/org/... links."""
    parsed = urlparse(url)
    match = _YMAPS_ORG_RE.search(unquote(parsed.path or ''))
    if match:
        return match.group('slug'), match.group('oid')
    query = unquote(parsed.query or '')
    oid_match = re.search(r'(?:^|[&?])oid=(\d+)', query, re.IGNORECASE)
    if oid_match and _is_ymaps_url(url):
        return 'org', oid_match.group(1)
    return None


def _vk_path(url: str) -> str:
    path = unquote(urlparse(url).path or '').strip('/')
    return path.split('?', 1)[0]


def _vk_call(token: str, method: str, **params) -> dict | list | None:
    try:
        response = httpx.get(
            f'{_VK_API}/{method}',
            params={**params, 'access_token': token, 'v': _VK_VERSION},
            timeout=12.0,
            follow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        _log.warning('VK API %s failed', method)
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get('error'):
        _log.warning('VK API %s error: %s', method, payload['error'].get('error_msg'))
        return None
    return payload.get('response')


def _best_size_url(photo: dict) -> str | None:
    sizes = photo.get('sizes')
    if isinstance(sizes, list) and sizes:
        best = max(
            (row for row in sizes if isinstance(row, dict) and row.get('url')),
            key=lambda row: int(row.get('width') or 0) * int(row.get('height') or 0),
            default=None,
        )
        if best:
            return _http_url(best.get('url'))
    for key in ('photo_2560', 'photo_1280', 'photo_807', 'photo_604', 'photo_130'):
        url = _http_url(photo.get(key))
        if url:
            return url
    return None


def _photo_item(photo: dict, query: str) -> dict | None:
    image = _best_size_url(photo)
    if not image:
        return None
    owner = photo.get('owner_id')
    photo_id = photo.get('id')
    source = (
        f'https://vk.com/photo{owner}_{photo_id}'
        if owner is not None and photo_id is not None
        else image
    )
    title = str(photo.get('text') or '').strip() or 'Фото из VK'
    return {
        'title': title[:300],
        'image_url': image,
        'thumbnail_url': image,
        'source_url': source[:2000],
        'engine': 'vk',
        'score': 12.0,
        'query': query,
    }


def _parse_owner_album(path: str) -> tuple[int, str | int] | None:
    # album-123_456 / album123_456
    match = re.fullmatch(r'album(-?\d+)_(\d+)', path)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def _parse_owner_photo(path: str) -> tuple[int, int] | None:
    match = re.fullmatch(r'photo(-?\d+)_(\d+)', path)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def _parse_club_id(path: str) -> int | None:
    for prefix in ('club', 'public', 'event'):
        if path.startswith(prefix) and path[len(prefix):].isdigit():
            return int(path[len(prefix):])
    return None


def _resolve_screen_name(token: str, screen_name: str) -> int | None:
    data = _vk_call(token, 'utils.resolveScreenName', screen_name=screen_name)
    if not isinstance(data, dict):
        return None
    object_id = data.get('object_id')
    kind = data.get('type')
    if not isinstance(object_id, int):
        return None
    if kind in ('group', 'page', 'event'):
        return -object_id
    if kind == 'user':
        return object_id
    return None


def _owner_from_vk_url(token: str, url: str) -> tuple[int, str | int] | None:
    """Return (owner_id, album_id) for photos.get, or None."""
    path = _vk_path(url)
    if not path:
        return None
    album = _parse_owner_album(path)
    if album:
        return album
    club = _parse_club_id(path.split('/')[0])
    if club:
        return -club, 'wall'
    # wall-123_456 — still use wall album of the owner
    wall = re.fullmatch(r'wall(-?\d+)_\d+', path)
    if wall:
        return int(wall.group(1)), 'wall'
    # Single path segment screen name (skip reserved)
    segment = path.split('/')[0]
    if segment and not segment.startswith(('album', 'photo', 'wall', 'video', 'topic')):
        owner = _resolve_screen_name(token, segment)
        if owner is not None:
            return owner, 'wall'
    return None


def _photos_get(token: str, owner_id: int, album_id: str | int, count: int) -> list[dict]:
    data = _vk_call(
        token,
        'photos.get',
        owner_id=owner_id,
        album_id=album_id,
        count=count,
        rev=1,
        photo_sizes=1,
    )
    if not isinstance(data, dict):
        return []
    items = data.get('items') or []
    return [row for row in items if isinstance(row, dict)]


def _photos_get_by_id(token: str, owner_id: int, photo_id: int) -> list[dict]:
    data = _vk_call(token, 'photos.getById', photos=f'{owner_id}_{photo_id}', photo_sizes=1)
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _vk_public_page_url(url: str) -> str:
    """Prefer vk.ru for anonymous public pages."""
    parsed = urlparse(url)
    path = parsed.path or '/'
    host = 'vk.ru'
    return f'https://{host}{path}'


def _vk_unescape(text: str) -> str:
    value = (text or '').replace('\\/', '/').replace('\\"', '"').replace('\\n', '\n')
    if '\\u' in value:
        try:
            return value.encode('utf-8').decode('unicode_escape')
        except UnicodeDecodeError:
            return value
    return value


def _fetch_vk_html(url: str) -> str:
    page = _vk_public_page_url(url)
    try:
        with httpx.Client(
            timeout=18.0,
            follow_redirects=True,
            headers=_VK_BROWSER_HEADERS,
        ) as client:
            response = client.get(page)
            if response.status_code >= 400:
                return ''
            text = response.text or ''
            if len(text) < 800:
                return ''
            if 'что-то пошло не так' in text.casefold() and 'userapi.com' not in text:
                return ''
            return text
    except httpx.HTTPError:
        _log.warning('VK HTML fetch failed for %s', page)
        return ''


def _vk_image_ok(url: str) -> bool:
    lower = url.casefold()
    if not lower.startswith('https://'):
        return False
    if 'userapi.com' not in lower:
        return False
    if any(skip in lower for skip in _VK_IMG_SKIP):
        return False
    if not re.search(r'\.(jpe?g|png|webp)(\?|$)', lower):
        return False
    return True


def _vk_image_rank(url: str) -> tuple[int, int]:
    lower = url.casefold()
    score = 0
    if '/impg/' in lower:
        score += 8
    if '/s/v1/' in lower:
        score += 2
    if 'quality=' in lower:
        score += 1
    if re.search(r'(?:720|960|1080|1280|2560)', lower):
        score += 4
    if 'as=32x32' in lower and not re.search(r'(?:360|720|1080|1280)', lower):
        score -= 5
    return score, len(url)


def _extract_vk_image_urls(html: str) -> list[str]:
    best: dict[str, str] = {}
    for match in _VK_JSON_URL_RE.finditer(html or ''):
        url = _http_url(_vk_unescape(match.group(1)))
        if not url or not _vk_image_ok(url):
            continue
        path = urlparse(url).path.casefold()
        previous = best.get(path)
        if previous is None or _vk_image_rank(url) > _vk_image_rank(previous):
            best[path] = url
    ranked = sorted(best.values(), key=_vk_image_rank, reverse=True)
    return ranked


def _extract_vk_texts(html: str) -> tuple[str, str, list[str]]:
    """Return (name, description, wall texts) from public group HTML."""
    name = ''
    for match in _VK_NAME_RE.finditer(html or ''):
        candidate = _vk_unescape(match.group(1)).strip()
        if candidate and candidate.casefold() not in {'vk', 'vkontakte'}:
            name = candidate
            break
    description = ''
    for match in _VK_DESC_RE.finditer(html or ''):
        candidate = _vk_unescape(match.group(1)).strip()
        if candidate and 'что-то пошло не так' not in candidate.casefold():
            description = candidate
            break
    posts: list[str] = []
    seen: set[str] = set()
    for match in _VK_TEXT_RE.finditer(html or ''):
        text = _vk_unescape(match.group(1)).strip()
        if not text or 'что-то пошло не так' in text.casefold():
            continue
        key = text[:120].casefold()
        if key in seen:
            continue
        seen.add(key)
        posts.append(text)
        if len(posts) >= _MAX_VK_WALL_POSTS:
            break
    return name, description, posts


def _vk_html_photos_for_url(url: str, *, title: str, limit: int, seen: set[str]) -> list[dict]:
    html = _fetch_vk_html(url)
    if not html:
        return []
    name, _, _ = _extract_vk_texts(html)
    label = (title or name or 'Фото из VK')[:300]
    photos: list[dict] = []
    for image in _extract_vk_image_urls(html):
        if len(photos) >= limit:
            break
        key = image.rstrip('/').casefold()
        if key in seen:
            continue
        seen.add(key)
        photos.append({
            'title': label,
            'image_url': image,
            'thumbnail_url': image,
            'source_url': _vk_public_page_url(url)[:2000],
            'engine': 'vk',
            'score': 11.0,
            'query': url,
        })
    return photos


def _vk_html_sources_for_url(url: str, *, title: str, limit: int, seen: set[str]) -> list[dict]:
    html = _fetch_vk_html(url)
    if not html:
        return []
    name, description, posts = _extract_vk_texts(html)
    page = _vk_public_page_url(url)
    items: list[dict] = []

    def add(item: dict) -> None:
        if len(items) >= limit:
            return
        key = str(item.get('url') or '').rstrip('/').casefold()
        if not key or key in seen:
            return
        seen.add(key)
        items.append(item)

    if description or name:
        add(_vk_source_item(
            title=f'VK: {(name or title or "Группа").strip()}',
            url=page,
            snippet=description or 'Публичная группа VK.',
            query=url,
            score=12.0,
        ))
    for index, text in enumerate(posts):
        if len(items) >= limit:
            break
        post_title = text.split('\n', 1)[0].strip() or 'Пост VK'
        add(_vk_source_item(
            title=post_title[:300],
            url=f'{page}#post-{index + 1}',
            snippet=text,
            query=url,
            score=11.0,
        ))
    return items


def vk_photos_for_links(token: str, links: list[dict], limit: int = _MAX_VK_PHOTOS) -> list[dict]:
    """Fetch photos for VK links via API when possible, else public HTML scrape."""
    if limit <= 0:
        return []
    photos: list[dict] = []
    seen: set[str] = set()
    for link in links:
        if len(photos) >= limit:
            break
        url = str(link.get('url') or '')
        if not _is_vk_url(url):
            continue
        path = _vk_path(url)
        rows: list[dict] = []
        if token:
            single = _parse_owner_photo(path)
            if single:
                rows = _photos_get_by_id(token, single[0], single[1])
            else:
                target = _owner_from_vk_url(token, url)
                if target:
                    owner_id, album_id = target
                    rows = _photos_get(token, owner_id, album_id, min(limit, _MAX_VK_PHOTOS))
        for row in rows:
            if len(photos) >= limit:
                break
            item = _photo_item(row, url)
            if not item:
                continue
            key = item['image_url'].rstrip('/').casefold()
            if key in seen:
                continue
            seen.add(key)
            photos.append(item)
        if len(photos) >= limit:
            break
        # Public groups open without login — scrape wall images when API is blocked.
        photos.extend(_vk_html_photos_for_url(
            url,
            title=str(link.get('title') or ''),
            limit=limit - len(photos),
            seen=seen,
        ))
    return photos


def _owner_id_from_vk_url(token: str, url: str) -> int | None:
    path = _vk_path(url)
    single = _parse_owner_photo(path)
    if single:
        return single[0]
    if token:
        target = _owner_from_vk_url(token, url)
        if target:
            return target[0]
    club = _parse_club_id(path.split('/')[0] if path else '')
    if club:
        return -club
    return None


def _groups_get_by_id(token: str, group_id: int) -> dict | None:
    data = _vk_call(
        token,
        'groups.getById',
        group_id=group_id,
        fields='description,status,activity,members_count',
    )
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        groups = data.get('groups')
        if isinstance(groups, list) and groups and isinstance(groups[0], dict):
            return groups[0]
    return None


def _wall_get(token: str, owner_id: int, count: int) -> list[dict]:
    data = _vk_call(
        token,
        'wall.get',
        owner_id=owner_id,
        count=count,
        filter='owner',
    )
    if not isinstance(data, dict):
        return []
    items = data.get('items') or []
    return [row for row in items if isinstance(row, dict)]


def _vk_source_item(
    *,
    title: str,
    url: str,
    snippet: str,
    query: str,
    score: float = 11.0,
) -> dict:
    return {
        'title': (title or 'VK').strip()[:300] or 'VK',
        'url': url[:2000],
        'snippet': (snippet or '').strip()[:800],
        'engine': 'vk',
        'category': 'vk',
        'score': score,
        'query': query,
    }


def vk_sources_for_links(
    token: str,
    links: list[dict],
    limit: int = _MAX_VK_SOURCES,
) -> list[dict]:
    """Pull group description + wall posts via API or public HTML scrape."""
    if limit <= 0:
        return []
    items: list[dict] = []
    seen: set[str] = set()
    seen_owners: set[int] = set()
    scraped_urls: set[str] = set()

    def add(item: dict) -> None:
        if len(items) >= limit:
            return
        key = str(item.get('url') or '').rstrip('/').casefold()
        if not key or key in seen:
            return
        seen.add(key)
        items.append(item)

    for link in links:
        if len(items) >= limit:
            break
        url = str(link.get('url') or '')
        if not _is_vk_url(url):
            continue
        got_api = False
        owner_id = _owner_id_from_vk_url(token, url) if token else None
        if owner_id is not None and owner_id not in seen_owners and token:
            seen_owners.add(owner_id)
            if owner_id < 0:
                group = _groups_get_by_id(token, -owner_id)
                if group:
                    got_api = True
                    name = str(group.get('name') or link.get('title') or 'Группа VK').strip()
                    description = str(group.get('description') or '').strip()
                    status = str(group.get('status') or '').strip()
                    activity = str(group.get('activity') or '').strip()
                    snippet_parts = [part for part in (description, status, activity) if part]
                    page = f'https://vk.com/club{-owner_id}'
                    add(_vk_source_item(
                        title=f'VK: {name}',
                        url=page,
                        snippet=' '.join(snippet_parts) or 'Группа VK из описания места.',
                        query=url,
                        score=12.0,
                    ))

            for post in _wall_get(token, owner_id, _MAX_VK_WALL_POSTS):
                if len(items) >= limit:
                    break
                text = str(post.get('text') or '').strip()
                if not text:
                    continue
                got_api = True
                post_id = post.get('id')
                post_url = (
                    f'https://vk.com/wall{owner_id}_{post_id}'
                    if post_id is not None
                    else url
                )
                title = text.split('\n', 1)[0].strip() or 'Пост VK'
                add(_vk_source_item(
                    title=title[:300],
                    url=post_url,
                    snippet=text,
                    query=url,
                    score=11.0,
                ))

        if got_api or url.rstrip('/').casefold() in scraped_urls:
            continue
        scraped_urls.add(url.rstrip('/').casefold())
        for item in _vk_html_sources_for_url(
            url,
            title=str(link.get('title') or ''),
            limit=limit - len(items),
            seen=seen,
        ):
            items.append(item)
            if len(items) >= limit:
                break
    return items


def _dzen_image_ok(url: str) -> bool:
    lower = url.casefold()
    if not lower.startswith('https://'):
        return False
    if any(skip in lower for skip in _DZEN_SKIP_FRAGMENTS):
        return False
    if not any(cdn in lower for cdn in (
        'avatars.mds.yandex.net', 's3.dzeninfra.ru', 'avatars.dzeninfra.ru',
    )):
        # Allow generic https images from og:image on dzen pages.
        if 'dzen' not in lower and 'yandex' not in lower:
            return bool(re.search(r'\.(jpe?g|png|webp)(\?|$)', lower))
    return True


def _extract_dzen_image_urls(html: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: object) -> None:
        url = _http_url(str(raw or '').replace('\\/', '/').replace('\\u002F', '/'))
        if not url or not _dzen_image_ok(url):
            return
        key = url.rstrip('/').casefold()
        if key in seen:
            return
        seen.add(key)
        found.append(url)

    for match in _OG_IMAGE_RE.finditer(html or ''):
        add(match.group(1) or match.group(2))
    for match in _DZEN_CDN_RE.finditer(html or ''):
        add(match.group(0))
    for match in re.finditer(r'"(?:image_url|url|contentUrl|originalUrl)"\s*:\s*"([^"]+)"', html or ''):
        add(match.group(1))
    return found


def _fetch_dzen_html(url: str) -> str:
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9',
    }
    try:
        # Do not follow Yandex SSO redirects — keep the first useful body.
        with httpx.Client(timeout=15.0, follow_redirects=False, headers=headers) as client:
            response = client.get(url)
            hops = 0
            while response.is_redirect and hops < 5:
                location = response.headers.get('location') or ''
                if 'sso.passport.yandex' in location or 'sso.dzen.ru' in location:
                    break
                response = client.get(httpx.URL(url).join(location))
                hops += 1
                url = str(response.url)
            if response.status_code >= 400:
                return ''
            text = response.text or ''
            if 'sso.passport.yandex' in text and 'avatars.mds.yandex.net' not in text:
                return ''
            if not _extract_dzen_image_urls(text) and len(text) < 1200:
                return ''
            return text
    except httpx.HTTPError:
        _log.warning('Dzen fetch failed for %s', url)
        return ''


def dzen_photos_for_links(links: list[dict], limit: int = _MAX_DZEN_PHOTOS) -> list[dict]:
    """Soft-scrape article images from Dzen links in the description."""
    if limit <= 0:
        return []
    photos: list[dict] = []
    seen: set[str] = set()
    for link in links:
        if len(photos) >= limit:
            break
        url = str(link.get('url') or '')
        if not _is_dzen_url(url):
            continue
        html = _fetch_dzen_html(url)
        if not html:
            continue
        title = str(link.get('title') or 'Фото из Дзена')[:300]
        for image in _extract_dzen_image_urls(html):
            if len(photos) >= limit:
                break
            key = image.rstrip('/').casefold()
            if key in seen:
                continue
            seen.add(key)
            photos.append({
                'title': title,
                'image_url': image,
                'thumbnail_url': image,
                'source_url': url[:2000],
                'engine': 'dzen',
                'score': 11.0,
                'query': url,
            })
    return photos


def _ymaps_org_page_url(slug: str, oid: str, *, gallery: bool = True) -> str:
    path = f'/maps/org/{slug}/{oid}/'
    if gallery:
        path = f'{path}gallery/'
    return f'https://yandex.com{path}'


def _normalize_altay_url(bucket: str, photo: str, *, size: str = 'XXL_height') -> str:
    return f'https://avatars.mds.yandex.net/get-altay/{bucket}/{photo}/{size}'


def _extract_ymaps_altay_urls(html: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _YMAPS_ALTAY_RE.finditer(html or ''):
        key = f"{match.group('bucket')}/{match.group('photo')}".casefold()
        if key in seen:
            continue
        seen.add(key)
        found.append(_normalize_altay_url(match.group('bucket'), match.group('photo')))
    return found


def _ymaps_org_from_html(html: str) -> tuple[str, str] | None:
    canonical = re.search(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
        html or '',
        re.IGNORECASE,
    )
    if canonical:
        org = _ymaps_org_from_url(canonical.group(1))
        if org:
            return org
    match = _YMAPS_ORG_RE.search(html or '')
    if match:
        return match.group('slug'), match.group('oid')
    return None


def _ymaps_title_from_html(html: str) -> str:
    for pattern in (
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
        r'"title"\s*:\s*"([^"\\]{2,120})"',
    ):
        match = re.search(pattern, html or '', re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            if title:
                return title[:300]
    return ''


def _ymaps_name_tokens(text: str) -> set[str]:
    tokens = {
        token for token in re.findall(r'[а-яёa-z0-9]{3,}', (text or '').casefold())
        if token not in _YMAPS_NAME_STOP
    }
    return tokens


def _ymaps_names_match(place_name: str, org_title: str) -> bool:
    place = (place_name or '').strip()
    title = (org_title or '').strip()
    if not place or not title:
        return False
    place_cf = place.casefold()
    title_cf = title.casefold()
    if place_cf in title_cf or title_cf in place_cf:
        return True
    left = _ymaps_name_tokens(place)
    right = _ymaps_name_tokens(title)
    if not left or not right:
        return False
    shared = left & right
    if not shared:
        return False
    # Require a distinctive shared token (len>=4) when the place has one.
    distinctive = {token for token in left if len(token) >= 4}
    if distinctive:
        return bool(distinctive & right)
    return bool(shared)


def _fetch_ymaps_html(url: str) -> str:
    try:
        with httpx.Client(
            timeout=18.0,
            follow_redirects=True,
            headers=_YMAPS_BROWSER_HEADERS,
        ) as client:
            response = client.get(url)
            if response.status_code >= 400:
                return ''
            text = response.text or ''
            if len(text) < 800 and 'get-altay' not in text:
                return ''
            return text
    except httpx.HTTPError:
        _log.warning('Yandex Maps fetch failed for %s', url)
        return ''


def _ymaps_photos_from_org(
    slug: str,
    oid: str,
    *,
    title: str,
    source_url: str,
    limit: int,
    seen: set[str],
) -> list[dict]:
    photos: list[dict] = []
    html = _fetch_ymaps_html(_ymaps_org_page_url(slug, oid, gallery=True))
    if not html or not _extract_ymaps_altay_urls(html):
        html = _fetch_ymaps_html(_ymaps_org_page_url(slug, oid, gallery=False))
    if not html:
        return []
    label = (title or _ymaps_title_from_html(html) or 'Фото с Яндекс.Карт')[:300]
    for image in _extract_ymaps_altay_urls(html):
        if len(photos) >= limit:
            break
        key = image.rstrip('/').casefold()
        if key in seen:
            continue
        seen.add(key)
        photos.append({
            'title': label,
            'image_url': image,
            'thumbnail_url': image,
            'source_url': source_url[:2000],
            'engine': 'yandex_maps',
            'score': 11.5,
            'query': source_url,
        })
    return photos


def yandex_maps_photos_for_links(
    links: list[dict],
    limit: int = _MAX_YMAPS_PHOTOS,
) -> list[dict]:
    """Soft-scrape org gallery photos from Yandex Maps links in the description."""
    if limit <= 0:
        return []
    photos: list[dict] = []
    seen: set[str] = set()
    for link in links:
        if len(photos) >= limit:
            break
        url = str(link.get('url') or '')
        org = _ymaps_org_from_url(url)
        if not org:
            continue
        slug, oid = org
        batch = _ymaps_photos_from_org(
            slug,
            oid,
            title=str(link.get('title') or ''),
            source_url=url,
            limit=limit - len(photos),
            seen=seen,
        )
        photos.extend(batch)
    return photos


def yandex_maps_photos_for_place(
    place: dict,
    limit: int = _MAX_YMAPS_PHOTOS,
) -> list[dict]:
    """Resolve org near place coords by name and soft-scrape its Maps gallery."""
    if limit <= 0:
        return []
    name = str(place.get('name') or '').strip()
    try:
        lat = float(place.get('latitude'))
        lon = float(place.get('longitude'))
    except (TypeError, ValueError):
        return []
    if not name or not _ymaps_name_tokens(name):
        return []
    query = urlencode({
        'text': name,
        'll': f'{lon},{lat}',
        'z': '15',
        'mode': 'search',
    }, quote_via=quote)
    search_url = f'https://yandex.com/maps/?{query}'
    html = _fetch_ymaps_html(search_url)
    if not html:
        return []
    org = _ymaps_org_from_html(html)
    if not org:
        return []
    slug, oid = org
    title = _ymaps_title_from_html(html)
    if not _ymaps_names_match(name, title or slug.replace('_', ' ')):
        return []
    source = _ymaps_org_page_url(slug, oid, gallery=False)
    # Prefer photos already embedded in the search/org landing HTML.
    seen: set[str] = set()
    embedded = _extract_ymaps_altay_urls(html)
    if embedded:
        photos: list[dict] = []
        label = (title or name or 'Фото с Яндекс.Карт')[:300]
        for image in embedded:
            if len(photos) >= limit:
                break
            key = image.rstrip('/').casefold()
            if key in seen:
                continue
            seen.add(key)
            photos.append({
                'title': label,
                'image_url': image,
                'thumbnail_url': image,
                'source_url': source[:2000],
                'engine': 'yandex_maps',
                'score': 11.5,
                'query': search_url,
            })
        if photos:
            return photos
    return _ymaps_photos_from_org(
        slug,
        oid,
        title=title or name,
        source_url=source,
        limit=limit,
        seen=seen,
    )


def _urban3p_object_url(oid: str) -> str:
    return f'https://urban3p.ru/object{oid}'


def _normalize_urban3p_image(url: str) -> str | None:
    text = str(url or '').strip().replace('\\/', '/')
    if text.startswith('//'):
        text = 'https:' + text
    parsed = _http_url(text)
    if not parsed:
        return None
    lower = parsed.casefold()
    if 'avatar' in lower or 'no_video' in lower or '/img/db/' in lower:
        return None
    # Prefer full gallery image over *_p.jpg thumbnails.
    parsed = re.sub(r'(_p)(\.jpe?g)(?:\?.*)?$', r'\2', parsed, flags=re.IGNORECASE)
    if not re.search(r'urban3p\.ru/.+\.(?:jpe?g|png|webp)(?:\?|$)', parsed, re.I):
        return None
    if '/up/o/' not in parsed.casefold():
        return None
    return parsed


def _extract_urban3p_image_urls(html: str, oid: str | None = None) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        url = _normalize_urban3p_image(raw)
        if not url:
            return
        if oid and f'/up/o/{oid}/' not in url.casefold():
            return
        key = url.rstrip('/').casefold()
        if key in seen:
            return
        seen.add(key)
        found.append(url)

    for match in _URBAN3P_GALLERY_RE.finditer(html or ''):
        host = match.group('host')
        obj = match.group('oid')
        pid = match.group('pid')
        add(f'https://{host}/up/o/{obj}/gallery/{pid}.jpg')
    for match in _URBAN3P_COVER_RE.finditer(html or ''):
        host = match.group('host')
        obj = match.group('oid')
        add(f'https://{host}/up/o/{obj}/photo.jpg')
    return found


def _urban3p_title_from_html(html: str) -> str:
    match = _URBAN3P_TITLE_RE.search(html or '')
    if not match:
        return ''
    title = re.sub(r'<[^>]+>', '', match.group(1))
    title = re.sub(r'\s+', ' ', title).strip()
    return title[:300]


def _urban3p_html_ok(text: str, final_url: str = '') -> str:
    body = text or ''
    if 'access/denied' in (final_url or '').casefold():
        return ''
    if len(body) < 400:
        return ''
    return body


def _fetch_urban3p_html_impersonated(url: str) -> str:
    """Urban3P closes plain OpenSSL handshakes; browser TLS impersonation works."""
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return ''
    # Prefer profiles that currently complete the handshake from this image.
    for impersonate in ('edge101', 'chrome120', 'chrome110', 'safari17_0'):
        try:
            response = curl_requests.get(
                url,
                impersonate=impersonate,
                timeout=20,
                headers=_URBAN3P_BROWSER_HEADERS,
                allow_redirects=True,
            )
            if int(getattr(response, 'status_code', 0) or 0) >= 400:
                continue
            html = _urban3p_html_ok(
                response.text or '',
                str(getattr(response, 'url', '') or url),
            )
            if html:
                return html
        except Exception:
            continue
    _log.warning('Urban3P impersonated fetch failed for %s', url)
    return ''


def _fetch_urban3p_html(url: str) -> str:
    html = _fetch_urban3p_html_impersonated(url)
    if html:
        return html
    try:
        with httpx.Client(
            timeout=18.0,
            follow_redirects=True,
            headers=_URBAN3P_BROWSER_HEADERS,
        ) as client:
            response = client.get(url)
            if response.status_code >= 400:
                return ''
            return _urban3p_html_ok(response.text or '', str(response.url))
    except httpx.HTTPError:
        _log.warning('Urban3P fetch failed for %s', url)
        return ''


def urban3p_photos_for_links(
    links: list[dict],
    limit: int = _MAX_URBAN3P_PHOTOS,
) -> list[dict]:
    """Soft-scrape object gallery photos from Urban3P (urbantrip) links."""
    if limit <= 0:
        return []
    photos: list[dict] = []
    seen: set[str] = set()
    seen_objects: set[str] = set()
    for link in links:
        if len(photos) >= limit:
            break
        url = str(link.get('url') or '')
        oid = _urban3p_object_id(url)
        if not oid or oid in seen_objects:
            continue
        seen_objects.add(oid)
        page_url = _urban3p_object_url(oid)
        html = _fetch_urban3p_html(page_url)
        if not html:
            continue
        title = (
            str(link.get('title') or '').strip()
            or _urban3p_title_from_html(html)
            or 'Фото с Urban3P'
        )[:300]
        for image in _extract_urban3p_image_urls(html, oid):
            if len(photos) >= limit:
                break
            key = image.rstrip('/').casefold()
            if key in seen:
                continue
            seen.add(key)
            photos.append({
                'title': title,
                'image_url': image,
                'thumbnail_url': image,
                'source_url': page_url,
                'engine': 'urban3p',
                'score': 12.5,
                'query': page_url,
            })
    return photos


def description_photos_for_links(
    links: list[dict],
    *,
    vk_token: str = '',
    limit: int = _MAX_VK_PHOTOS,
    place: dict | None = None,
) -> list[dict]:
    """VK + Dzen + Yandex Maps + Urban3P photos from description / place lookup."""
    photos: list[dict] = []
    seen: set[str] = set()

    def absorb(batch: list[dict]) -> None:
        for item in batch:
            if len(photos) >= limit:
                return
            key = str(item.get('image_url') or '').rstrip('/').casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            photos.append(item)

    absorb(vk_photos_for_links(vk_token, links, limit))
    if len(photos) < limit:
        absorb(urban3p_photos_for_links(links, limit - len(photos)))
    if len(photos) < limit:
        absorb(dzen_photos_for_links(links, limit - len(photos)))
    if len(photos) < limit:
        absorb(yandex_maps_photos_for_links(links, limit - len(photos)))
    if place is not None and len(photos) < limit:
        absorb(yandex_maps_photos_for_place(place, limit - len(photos)))
    return photos
