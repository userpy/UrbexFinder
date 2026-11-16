"""Trusted links from place.description, with optional VK / Dzen / Maps / page photos."""
from __future__ import annotations
import logging
import re
from urllib.parse import quote, unquote, urlencode, urljoin, urlparse
import httpx
from .vk_album import parse_vk_album
from .osint_identity import primary_gallery, extract_page_identity
from .wikimapia import direct_photos, gallery_urls, is_object_url

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
_MAX_GENERIC_PHOTOS = 12
_MAX_GENERIC_PER_PAGE = 6
_URBAN3P_HOSTS = frozenset({'urban3p.ru', 'www.urban3p.ru', 'urban3p.com', 'www.urban3p.com'})
_GENERIC_BROWSER_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}
_GENERIC_IMG_RE = re.compile(
    r'<img\b[^>]*?\bsrc=["\']([^"\']+)["\']',
    re.IGNORECASE | re.DOTALL,
)
_GENERIC_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']'
    r'|<title[^>]*>(.*?)</title>',
    re.IGNORECASE | re.DOTALL,
)
_GENERIC_ARTICLE_RE = re.compile(
    r'itemprop=["\']articleBody["\'][^>]*>(.*?)(?:</div>\s*<div\b|</article>|</section>)',
    re.IGNORECASE | re.DOTALL,
)
_GENERIC_SKIP_FRAGMENTS = (
    'logo', 'favicon', 'sprite', 'emoji', 'icon', 'arrow', 'loader',
    'avatar', 'button', 'badge', 'pixel', 'tracker', 'spinner',
    '/media/system/', '/components/', '/templates/', '/modules/',
    'yandex.ru/watch', 'mc.yandex', 'counter', 'captcha',
    '1x1', 'blank.', 'spacer', 'placeholder',
)
_GENERIC_CONTENT_HINTS = (
    '/images/stories/', '/photos/', '/photo/', '/uploads/',
    '/wp-content/uploads/', '/media/', '/gallery/', '/content/',
    '/files/', '/img/', '/images/',
)
_URBAN3P_OBJECT_RE = re.compile(
    r'(?:https?:)?//(?:www\.)?urban3p\.(?:ru|com)/object(?P<oid>\d+)\b',
    re.IGNORECASE,
)
_URBAN3P_BLOG_RE = re.compile(
    r'(?:https?:)?//(?:www\.)?urban3p\.(?:ru|com)/blogs/(?P<bid>\d+)\b',
    re.IGNORECASE,
)
_URBAN3P_CDN_OBJECT_RE = re.compile(
    r'(?:https?:)?//(?:img\d*\.)?urban3p\.ru/up/o/(?P<oid>\d+)/',
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
_URBAN3P_DOC_TITLE_RE = re.compile(
    r'<title[^>]*>(.*?)</title>',
    re.IGNORECASE | re.DOTALL,
)
_URBAN3P_LOCATION_RE = re.compile(
    r'Месторасположение:</?\w*>\s*<[^>]+>([^<]{3,120})',
    re.IGNORECASE | re.DOTALL,
)
_URBAN3P_BLOG_BODY_RE = re.compile(
    r'class=["\'][^"\']*blogText[^"\']*["\'][^>]*>(.*?)'
    r'(?:class=["\'][^"\']*comment|id=["\']comments|id=["\']textComment)',
    re.IGNORECASE | re.DOTALL,
)
_URBAN3P_BLOG_IMG_SKIP = (
    'avatar', 'blank.gif', 'no_video', '/img/db/', '/img/touch',
    'favicon', 'sprite', 'lvl1.png', 'yatablo',
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
    'церковь', 'храм', 'собор', 'часовня', 'монастырь',
    'казанской', 'казанская', 'казанский', 'иконы', 'божией', 'божьей', 'матери',
    'пресвятой', 'богородицы', 'православный', 'православная',
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
        if match.group(1) is None:
            label = url
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
                else 'swalker' if _is_swalker_url(url)
                else 'youtube' if _is_youtube_url(url)
                else 'rutube' if _is_rutube_url(url)
                else 'geocache' if _is_geocache_url(url)
                else 'wikimapia' if is_object_url(url)
                else 'link'
            ),
            'score': 10.0,
            'query': 'description',
        })
    return items


def is_direct_image_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(re.search(r'\.(?:jpe?g|png|webp)$', parsed.path, re.IGNORECASE)) or (
        (parsed.hostname or '').endswith('.googleusercontent.com')
        and parsed.path.startswith('/umsh/')
    )


def is_vk_group_url(url: str) -> bool:
    if not _is_vk_url(url):
        return False
    path = _vk_path(url)
    return bool(path) and '/' not in path and not re.match(
        r'(?:album|photo|wall|video|topic)-?\d+_', path,
    )


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
    """Object id from /objectN, gallery CDN, or cover photo URLs."""
    text = url or ''
    match = _URBAN3P_OBJECT_RE.search(text)
    if match:
        return match.group('oid')
    match = _URBAN3P_CDN_OBJECT_RE.search(text)
    return match.group('oid') if match else None


def _urban3p_blog_id(url: str) -> str | None:
    match = _URBAN3P_BLOG_RE.search(url or '')
    return match.group('bid') if match else None


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
    if _parse_owner_album(_vk_path(url)):
        album = parse_vk_album(html, url)
        photos = []
        for image in album['photos']:
            if len(photos) >= limit:
                break
            if image in seen:
                continue
            seen.add(image)
            photos.append({
                'title': album['title'] or title or 'Фото альбома VK',
                'image_url': image, 'thumbnail_url': image,
                'source_url': url, 'engine': 'vk', 'scope': 'album',
                'score': 12.0, 'query': url,
            })
        return photos
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
        if _parse_owner_album(path):
            album_photos = _vk_html_photos_for_url(
                url, title=str(link.get('title') or ''),
                limit=limit - len(photos), seen=seen,
            )
            if album_photos:
                photos.extend(album_photos)
                continue
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
        album = _parse_owner_album(_vk_path(url))
        if album:
            # An object album is not evidence about the owner's whole group.
            # Never replace it with group metadata or unrelated recent posts.
            parsed = parse_vk_album(_fetch_vk_html(url), url)
            if parsed['title']:
                add(_vk_source_item(
                    title=parsed['title'], url=url,
                    snippet=parsed['description'], query=url,
                ))
            elif token:
                owner_id, album_id = album
                data = _vk_call(token, 'photos.getAlbums', owner_id=owner_id, album_ids=album_id)
                rows = data.get('items', []) if isinstance(data, dict) else []
                for row in rows:
                    if not isinstance(row, dict) or str(row.get('id')) != str(album_id):
                        continue
                    add(_vk_source_item(
                        title=str(row.get('title') or 'Альбом VK'), url=url,
                        snippet=str(row.get('description') or ''), query=url,
                    ))
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
    org_label = title or slug.replace('_', ' ')
    if not _ymaps_names_match(name, org_label):
        return []
    # Drop famous namesakes in other cities (Казань vs «Казанской» church in Ryazan).
    address_blob = ' '.join(
        str(place.get(key) or '')
        for key in ('full_address', 'region', 'name')
    ).casefold()
    org_blob = f'{org_label} {slug}'.casefold()
    for foreign_city in (
        'казань', 'вахитовск', 'москва', 'санкт-петербург', 'петербург',
        'екатеринбург', 'новосибирск',
    ):
        if foreign_city in org_blob and foreign_city not in address_blob:
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


def _urban3p_blog_url(bid: str) -> str:
    return f'https://urban3p.ru/blogs/{bid}'


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


def _normalize_urban3p_blog_image(url: str, page_url: str = '') -> str | None:
    """Blog reports often host photos on VK CDN, not img*.urban3p.ru."""
    text = str(url or '').strip().replace('\\/', '/')
    if not text or text.startswith(('data:', 'javascript:')):
        return None
    if text.startswith('//'):
        text = 'https:' + text
    absolute = urljoin(page_url or 'https://urban3p.ru/', text)
    parsed = _http_url(absolute)
    if not parsed:
        return None
    lower = parsed.casefold()
    if any(skip in lower for skip in _URBAN3P_BLOG_IMG_SKIP):
        return None
    if not re.search(r'\.(jpe?g|png|webp)(\?|$)', lower):
        return None
    host = (urlparse(parsed).hostname or '').casefold()
    if 'userapi.com' in host or host.endswith('.vkuservideo.net'):
        return parsed
    if host.endswith('urban3p.ru'):
        if '/up/o/' in lower:
            return _normalize_urban3p_image(parsed)
        if '/uploaded/' in lower and 'avatar' not in lower:
            return parsed
    return None


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


def _extract_urban3p_blog_image_urls(html: str, page_url: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: object) -> None:
        url = _normalize_urban3p_blog_image(str(raw or ''), page_url)
        if not url:
            return
        key = url.rstrip('/').casefold()
        if key in seen:
            return
        seen.add(key)
        found.append(url)

    body_match = _URBAN3P_BLOG_BODY_RE.search(html or '')
    scan = body_match.group(1) if body_match else (html or '')
    for match in _OG_IMAGE_RE.finditer(html or ''):
        add(match.group(1) or match.group(2))
    for match in _GENERIC_IMG_RE.finditer(scan):
        add(match.group(1))
    # Object galleries sometimes appear inside a report too.
    for url in _extract_urban3p_image_urls(scan):
        add(url)
    return found


def _urban3p_object_ids_in_html(html: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _URBAN3P_OBJECT_RE.finditer(html or ''):
        oid = match.group('oid')
        if oid in seen:
            continue
        seen.add(oid)
        found.append(oid)
    for match in _URBAN3P_CDN_OBJECT_RE.finditer(html or ''):
        oid = match.group('oid')
        if oid in seen:
            continue
        seen.add(oid)
        found.append(oid)
    return found


def _urban3p_clean_text(value: str) -> str:
    text = re.sub(r'<[^>]+>', '', value or '')
    return re.sub(r'\s+', ' ', text).strip()


def _urban3p_title_from_html(html: str) -> str:
    """Prefer <title> — it usually includes «(Московская область)», unlike bare <h1>."""
    doc = _URBAN3P_DOC_TITLE_RE.search(html or '')
    if doc:
        title = _urban3p_clean_text(doc.group(1))
        if title:
            return title[:300]
    match = _URBAN3P_TITLE_RE.search(html or '')
    heading = _urban3p_clean_text(match.group(1)) if match else ''
    location = ''
    loc = _URBAN3P_LOCATION_RE.search(html or '')
    if loc:
        location = _urban3p_clean_text(loc.group(1))
    if heading and location and location.casefold() not in heading.casefold():
        return f'{heading} ({location})'[:300]
    return (heading or location)[:300]


def _urban3p_html_ok(text: str, final_url: str = '') -> str:
    body = text or ''
    if 'access/denied' in (final_url or '').casefold():
        return ''
    if len(body) < 400:
        return ''
    return body


# Urban3P fingerprinting is flaky; prefer modern Chrome profiles that still handshake.
_URBAN3P_IMPERSONATE = (
    'chrome136',
    'chrome131',
    'chrome124',
    'chrome110',
    'chrome120',
    'firefox135',
    'edge101',
)
_URBAN3P_IMG_HOSTS = ('img04', 'img03', 'img02', 'img01', 'img')


def _fetch_urban3p_html_impersonated(url: str) -> str:
    """Urban3P closes plain OpenSSL handshakes; browser TLS impersonation works."""
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return ''
    # First pass: all profiles; retry only the most reliable ones on SSL flaps.
    for batch in (_URBAN3P_IMPERSONATE, _URBAN3P_IMPERSONATE[:2]):
        for impersonate in batch:
            try:
                response = curl_requests.get(
                    url,
                    impersonate=impersonate,
                    timeout=12,
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


def _urban3p_cover_urls(oid: str) -> list[str]:
    """Stable cover URL(s) when the object HTML cannot be fetched."""
    return [f'https://{host}.urban3p.ru/up/o/{oid}/photo.jpg' for host in _URBAN3P_IMG_HOSTS[:1]]


def _urban3p_append_photos(
    photos: list[dict],
    *,
    images: list[str],
    title: str,
    source_url: str,
    seen: set[str],
    limit: int,
    score: float = 12.5,
) -> None:
    for image in images:
        if len(photos) >= limit:
            return
        key = image.rstrip('/').casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        photos.append({
            'title': title,
            'image_url': image,
            'thumbnail_url': image,
            'source_url': source_url,
            'engine': 'urban3p',
            'score': score,
            'query': source_url,
        })


def _urban3p_photos_from_object(
    oid: str,
    *,
    title_hint: str,
    photos: list[dict],
    seen: set[str],
    seen_objects: set[str],
    limit: int,
) -> None:
    if not oid or oid in seen_objects or len(photos) >= limit:
        return
    seen_objects.add(oid)
    page_url = _urban3p_object_url(oid)
    html = _fetch_urban3p_html(page_url)
    page_title = _urban3p_title_from_html(html) if html else ''
    hint = title_hint.strip()
    # Page <title> carries oblast; search snippets often omit it.
    if page_title and (
        not hint
        or (
            any(token in page_title.casefold() for token in ('област', 'край', 'республик', 'москов', 'мордов'))
            and not any(token in hint.casefold() for token in ('област', 'край', 'республик', 'москов', 'мордов'))
        )
    ):
        title = page_title
    else:
        title = hint or page_title or 'Фото с Urban3P'
    title = title[:300]
    need = max(0, limit - len(photos))
    images = _extract_urban3p_image_urls(html, oid) if html else []
    if not images:
        # Page TLS often flaps; cover path is enough to avoid an empty gallery.
        images = _urban3p_cover_urls(oid)
    elif need:
        images = images[: max(need, _MAX_URBAN3P_PHOTOS)]
    _urban3p_append_photos(
        photos,
        images=images,
        title=title,
        source_url=page_url,
        seen=seen,
        limit=limit,
        score=12.5,
    )


def _urban3p_photos_from_blog(
    bid: str,
    *,
    title_hint: str,
    photos: list[dict],
    seen: set[str],
    seen_blogs: set[str],
    seen_objects: set[str],
    limit: int,
) -> None:
    if not bid or bid in seen_blogs or len(photos) >= limit:
        return
    seen_blogs.add(bid)
    page_url = _urban3p_blog_url(bid)
    html = _fetch_urban3p_html(page_url)
    if not html:
        return
    title = (
        title_hint.strip()
        or _urban3p_title_from_html(html)
        or 'Фото с Urban3P'
    )[:300]
    images = _extract_urban3p_blog_image_urls(html, page_url)
    _urban3p_append_photos(
        photos,
        images=images,
        title=title,
        source_url=page_url,
        seen=seen,
        limit=limit,
        score=12.0,
    )
    # Follow object cards linked/mentioned inside the report.
    for oid in _urban3p_object_ids_in_html(html):
        if len(photos) >= limit:
            break
        _urban3p_photos_from_object(
            oid,
            title_hint=title,
            photos=photos,
            seen=seen,
            seen_objects=seen_objects,
            limit=limit,
        )


def _urban3p_link_sort_key(link: dict) -> tuple[int, int, str]:
    """Prefer local object cards over same-name camps in other regions."""
    url = str(link.get('url') or '')
    title = str(link.get('title') or '').casefold()
    rank = 0
    if _urban3p_object_id(url):
        rank += 2
    if _urban3p_blog_id(url):
        rank += 1
    if any(token in title for token in ('москов', 'подмосков', 'тульск', 'тула')):
        rank += 4
    if any(
        token in title
        for token in ('мордов', 'свердлов', 'ленинград', 'новосибир', 'казахстан')
    ):
        rank -= 6
    return (-rank, 0 if '/gallery' not in url.casefold() else 1, url)


def urban3p_photos_for_links(
    links: list[dict],
    limit: int = _MAX_URBAN3P_PHOTOS,
) -> list[dict]:
    """Soft-scrape Urban3P photos from object cards, blogs, and CDN image links."""
    if limit <= 0:
        return []
    photos: list[dict] = []
    seen: set[str] = set()
    seen_objects: set[str] = set()
    seen_blogs: set[str] = set()
    for link in sorted(links, key=_urban3p_link_sort_key):
        if len(photos) >= limit:
            break
        url = str(link.get('url') or '')
        if not url or not _is_urban3p_url(url):
            continue
        title_hint = str(link.get('title') or '')
        bid = _urban3p_blog_id(url)
        if bid:
            _urban3p_photos_from_blog(
                bid,
                title_hint=title_hint,
                photos=photos,
                seen=seen,
                seen_blogs=seen_blogs,
                seen_objects=seen_objects,
                limit=limit,
            )
            continue
        oid = _urban3p_object_id(url)
        if oid:
            _urban3p_photos_from_object(
                oid,
                title_hint=title_hint,
                photos=photos,
                seen=seen,
                seen_objects=seen_objects,
                limit=limit,
            )
    return photos


_MAX_SWALKER_PHOTOS = 12
_SWALKER_HOSTS = frozenset({'swalker.ru', 'www.swalker.ru', 'swalker.org', 'www.swalker.org'})
_SWALKER_UPLOAD_RE = re.compile(
    r'(?:https?:)?(?://(?:www\.)?swalker\.(?:ru|org))?(/uploads/posts/\d{4}-\d{2}/(?:thumbs/)?'
    r'[^\"\'\s<>]+\.(?:jpe?g|png|webp))',
    re.IGNORECASE,
)
_SWALKER_FOLDER_RE = re.compile(r'/uploads/posts/(\d{4}-\d{2})/', re.IGNORECASE)


def _is_swalker_url(url: str) -> bool:
    host = (urlparse(url).hostname or '').casefold()
    return host in _SWALKER_HOSTS or host.endswith('.swalker.ru') or host.endswith('.swalker.org')


_GEOCACHE_HOSTS = frozenset({
    'geocaching.su', 'www.geocaching.su',
    'geocaching.ru', 'www.geocaching.ru',
    'geocaching.com', 'www.geocaching.com',
    'opencaching.pl', 'www.opencaching.pl',
})


def _is_geocache_url(url: str) -> bool:
    host = (urlparse(url).hostname or '').casefold()
    if not host:
        return False
    return any(host == domain or host.endswith('.' + domain) for domain in _GEOCACHE_HOSTS)


def _normalize_swalker_image(url: str, page_url: str = 'https://swalker.ru/') -> str | None:
    text = str(url or '').strip().replace('\\/', '/')
    if text.startswith('//'):
        text = 'https:' + text
    absolute = urljoin(page_url, text)
    # Prefer full-size gallery files over CMS thumbs.
    absolute = re.sub(
        r'(/uploads/posts/\d{4}-\d{2}/)thumbs/',
        r'\1',
        absolute,
        flags=re.IGNORECASE,
    )
    parsed = _http_url(absolute)
    if not parsed:
        return None
    lower = parsed.casefold()
    if '/uploads/posts/' not in lower:
        return None
    if not re.search(r'\.(jpe?g|png|webp)(\?|$)', lower):
        return None
    if not _is_swalker_url(parsed):
        # Relative /uploads/… resolved against swalker host above.
        host = (urlparse(parsed).hostname or '').casefold()
        if 'swalker.' not in host:
            return None
    return parsed


def _extract_swalker_image_urls(html: str, page_url: str) -> list[str]:
    """Pull article gallery photos; ignore sidebar thumbs from other posts."""
    found: list[str] = []
    seen: set[str] = set()
    folders: list[str] = []

    def add(raw: object) -> None:
        url = _normalize_swalker_image(str(raw or ''), page_url)
        if not url:
            return
        key = url.rstrip('/').casefold()
        if key in seen:
            return
        seen.add(key)
        found.append(url)
        folder = _SWALKER_FOLDER_RE.search(url)
        if folder:
            folders.append(folder.group(1))

    for match in _OG_IMAGE_RE.finditer(html or ''):
        add(match.group(1) or match.group(2))
    # Highslide / lightbox links point at full-size report photos
    # (relative /uploads/… and absolute https://swalker.ru/uploads/…).
    for match in re.finditer(
        r'(?:href|src)=["\']([^"\']*uploads/posts/[^"\']+)["\']',
        html or '',
        re.IGNORECASE,
    ):
        add(match.group(1))
    if len(found) <= 1:
        for match in _SWALKER_UPLOAD_RE.finditer(html or ''):
            add(match.group(1))

    if not found:
        return []
    # Keep the article folder (from og:image / first gallery), drop other posts.
    primary = folders[0] if folders else None
    if primary:
        primary_urls = [url for url in found if f'/uploads/posts/{primary}/' in url.casefold()]
        if primary_urls:
            return primary_urls
    return found


def _fetch_swalker_html(url: str) -> str:
    try:
        with httpx.Client(
            timeout=15.0,
            follow_redirects=True,
            headers=_GENERIC_BROWSER_HEADERS,
        ) as client:
            response = client.get(url)
            if response.status_code >= 400:
                return ''
            text = response.text or ''
            if len(text) < 400:
                return ''
            return text
    except httpx.HTTPError:
        _log.warning('Swalker fetch failed for %s', url)
        return ''


def swalker_photos_for_links(
    links: list[dict],
    limit: int = _MAX_SWALKER_PHOTOS,
) -> list[dict]:
    """Soft-scrape report gallery photos from Swalker article links."""
    if limit <= 0:
        return []
    photos: list[dict] = []
    seen: set[str] = set()
    seen_pages: set[str] = set()
    for link in links:
        if len(photos) >= limit:
            break
        url = str(link.get('url') or '')
        if not url or not _is_swalker_url(url):
            continue
        page_key = url.rstrip('/').casefold()
        if page_key in seen_pages:
            continue
        seen_pages.add(page_key)
        html = _fetch_swalker_html(url)
        if not html:
            continue
        title = (
            str(link.get('title') or '').strip()
            or _generic_title_from_html(html)
            or 'Фото со Swalker'
        )[:300]
        for image in _extract_swalker_image_urls(html, url):
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
                'engine': 'swalker',
                'score': 12.0,
                'query': url,
            })
    return photos


_MAX_YOUTUBE_PHOTOS = 12
_MAX_RUTUBE_PHOTOS = 12
_YOUTUBE_ID_RE = re.compile(
    r'(?:youtube\.com/(?:watch\?(?:[^#]*&)?v=|embed/|shorts/|live/)|youtu\.be/)'
    r'(?P<id>[A-Za-z0-9_-]{6,})',
    re.IGNORECASE,
)
_RUTUBE_ID_RE = re.compile(
    r'rutube\.ru/(?:video|play/embed)/(?P<id>[0-9a-f]{32})',
    re.IGNORECASE,
)


def _is_youtube_url(url: str) -> bool:
    host = (urlparse(url).hostname or '').casefold()
    return host in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be', 'www.youtu.be'} or host.endswith('.youtube.com')


def _is_rutube_url(url: str) -> bool:
    host = (urlparse(url).hostname or '').casefold()
    return host in {'rutube.ru', 'www.rutube.ru', 'm.rutube.ru'} or host.endswith('.rutube.ru')


def _youtube_video_id(url: str) -> str | None:
    match = _YOUTUBE_ID_RE.search(url or '')
    return match.group('id') if match else None


def _rutube_video_id(url: str) -> str | None:
    match = _RUTUBE_ID_RE.search(url or '')
    return match.group('id') if match else None


def youtube_photos_for_links(
    links: list[dict],
    limit: int = _MAX_YOUTUBE_PHOTOS,
) -> list[dict]:
    """Use public YouTube thumbnails for video links (no page scrape)."""
    if limit <= 0:
        return []
    photos: list[dict] = []
    seen: set[str] = set()
    for link in links:
        if len(photos) >= limit:
            break
        url = str(link.get('url') or '')
        video_id = _youtube_video_id(url)
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        image = f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'
        title = (str(link.get('title') or '').strip() or 'Видео на YouTube')[:300]
        photos.append({
            'title': title,
            'image_url': image,
            'thumbnail_url': image,
            'source_url': f'https://www.youtube.com/watch?v={video_id}',
            'engine': 'youtube',
            'score': 11.5,
            'query': url,
        })
    return photos


def _rutube_thumbnail(video_id: str) -> tuple[str | None, str]:
    """Return (thumbnail_url, title) via Rutube API."""
    try:
        with httpx.Client(
            timeout=12.0,
            follow_redirects=True,
            headers=_GENERIC_BROWSER_HEADERS,
        ) as client:
            response = client.get(f'https://rutube.ru/api/video/{video_id}/')
            if response.status_code >= 400:
                return None, ''
            data = response.json() if response.content else {}
            if not isinstance(data, dict):
                return None, ''
            thumb = _http_url(data.get('thumbnail_url') or data.get('poster_url'))
            title = str(data.get('title') or '').strip()
            return thumb, title
    except (httpx.HTTPError, ValueError, TypeError):
        _log.warning('Rutube API fetch failed for %s', video_id)
        return None, ''


def rutube_photos_for_links(
    links: list[dict],
    limit: int = _MAX_RUTUBE_PHOTOS,
) -> list[dict]:
    """Fetch Rutube video posters for video links."""
    if limit <= 0:
        return []
    photos: list[dict] = []
    seen: set[str] = set()
    for link in links:
        if len(photos) >= limit:
            break
        url = str(link.get('url') or '')
        video_id = _rutube_video_id(url)
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        image, api_title = _rutube_thumbnail(video_id)
        if not image:
            continue
        title = (
            str(link.get('title') or '').strip()
            or api_title
            or 'Видео на Rutube'
        )[:300]
        source = f'https://rutube.ru/video/{video_id}/'
        photos.append({
            'title': title,
            'image_url': image,
            'thumbnail_url': image,
            'source_url': source,
            'engine': 'rutube',
            'score': 11.5,
            'query': url,
        })
    return photos


def _is_specialized_photo_url(url: str) -> bool:
    return (
        _is_vk_url(url)
        or _is_dzen_url(url)
        or _is_urban3p_url(url)
        or _is_ymaps_url(url)
        or _is_swalker_url(url)
        or _is_youtube_url(url)
        or _is_rutube_url(url)
    )


def _generic_engine_for(url: str) -> str:
    host = (urlparse(url).hostname or '').casefold()
    if is_object_url(url):
        return 'wikimapia'
    if host in {'geocaching.su', 'www.geocaching.su', 'geocaching.ru', 'www.geocaching.ru'}:
        return 'geocache'
    if 'planetadorog' in host:
        return 'planetadorog'
    if host == 'caves.ru' or host.endswith('.caves.ru'):
        return 'caves'
    if 'urbexstalker' in host:
        return 'urbexstalker'
    if 'swalker' in host:
        return 'swalker'
    return 'web_page'


def _generic_image_ok(url: str) -> bool:
    lower = url.casefold()
    if not lower.startswith(('http://', 'https://')):
        return False
    if any(skip in lower for skip in _GENERIC_SKIP_FRAGMENTS):
        return False
    path = (urlparse(url).path or '').casefold()
    if path.endswith(('.svg', '.gif', '.ico', '.webp.svg')):
        return False
    if re.search(r'\.(jpe?g|png|webp)(\?|$)', lower):
        return True
    # Some CMSes omit extension but put photos under clear paths.
    return any(hint in lower for hint in _GENERIC_CONTENT_HINTS)


def _extract_generic_image_urls(html: str, page_url: str) -> list[str]:
    if is_object_url(page_url):
        return gallery_urls(html, page_url)
    if _generic_engine_for(page_url) == 'geocache':
        # Cache galleries contain full-size links and thumbnail <img> tags.
        # Ignore UI icons and notebook/user images outside the area gallery.
        photos = []
        for raw in re.findall(r'''(?:href|src)\s*=\s*["']([^"']+)["']''', html or '', re.IGNORECASE):
            image = urljoin(page_url, raw)
            parsed = urlparse(image)
            if (parsed.scheme not in {'http', 'https'}
                    or _generic_engine_for(image) != 'geocache'
                    or not re.fullmatch(r'/photos/areas/(?:thumbnails/)?\d+\.(?:jpe?g|png|webp)', parsed.path, re.IGNORECASE)):
                continue
            image = image.replace('/areas/thumbnails/', '/areas/')
            if image not in photos:
                photos.append(image)
        return photos
    scoped, images = primary_gallery(html, page_url)
    if scoped:
        return [image for image in images if _generic_image_ok(image)]
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: object) -> None:
        text = str(raw or '').strip()
        if not text or text.startswith(('data:', 'javascript:')):
            return
        absolute = urljoin(page_url, text.replace('\\/', '/'))
        url = _http_url(absolute)
        if not url or not _generic_image_ok(url):
            return
        key = url.rstrip('/').casefold()
        if key in seen:
            return
        seen.add(key)
        found.append(url)

    for match in _OG_IMAGE_RE.finditer(html or ''):
        add(match.group(1) or match.group(2))

    article = ''
    article_match = _GENERIC_ARTICLE_RE.search(html or '')
    if article_match:
        article = article_match.group(1) or ''
    scan = article or (html or '')
    for match in _GENERIC_IMG_RE.finditer(scan):
        add(match.group(1))

    # Prefer content-looking paths first (stories/photos over random CDN).
    found.sort(
        key=lambda u: (
            0 if any(h in u.casefold() for h in _GENERIC_CONTENT_HINTS) else 1,
            len(u),
        ),
    )
    return found


def _generic_title_from_html(html: str) -> str:
    match = _GENERIC_TITLE_RE.search(html or '')
    if not match:
        return ''
    title = match.group(1) or match.group(2) or ''
    title = re.sub(r'<[^>]+>', '', title)
    title = re.sub(r'\s+', ' ', title).strip()
    return title[:300]


def _fetch_generic_html(url: str) -> str:
    try:
        with httpx.Client(
            timeout=httpx.Timeout(15.0, connect=5.0),
            transport=httpx.HTTPTransport(retries=1),
            follow_redirects=True,
            headers=_GENERIC_BROWSER_HEADERS,
        ) as client:
            response = client.get(url)
            if response.status_code >= 400:
                return ''
            text = response.text or ''
            if len(text) < 400:
                return ''
            return text
    except httpx.HTTPError:
        _log.warning('Generic page fetch failed for %s', url)
        return ''


_MAX_GENERIC_PAGES = 5


def generic_page_photos_for_links(
    links: list[dict],
    limit: int = _MAX_GENERIC_PHOTOS,
    *,
    max_pages: int = _MAX_GENERIC_PAGES,
) -> list[dict]:
    """Soft-scrape article images from ordinary http(s) links (Планета дорог, caves, web)."""
    if limit <= 0:
        return []
    photos: list[dict] = []
    seen: set[str] = set()
    seen_pages: set[str] = set()
    pages_fetched = 0
    for link in links:
        if len(photos) >= limit or pages_fetched >= max_pages:
            break
        url = str(link.get('url') or '')
        if not url or _is_specialized_photo_url(url) or is_direct_image_url(url):
            continue
        page_key = url.rstrip('/').casefold()
        if page_key in seen_pages:
            continue
        seen_pages.add(page_key)
        html = _fetch_generic_html(url)
        pages_fetched += 1
        if not html:
            continue
        title = (
            (_generic_title_from_html(html) if _generic_engine_for(url) in {'geocache', 'wikimapia'} else '')
            or str(link.get('title') or '').strip()
            or _generic_title_from_html(html)
            or 'Фото со страницы'
        )[:300]
        engine = _generic_engine_for(url)
        primary_scope, _ = primary_gallery(html, url)
        page_identity = extract_page_identity(html, url)
        page_count = 0
        for image in _extract_generic_image_urls(html, url):
            if len(photos) >= limit or page_count >= _MAX_GENERIC_PER_PAGE:
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
                'engine': engine,
                'gallery_scope': 'primary' if primary_scope else 'unknown',
                'page_identity': page_identity,
                'score': 10.5 if engine == 'web_page' else 11.0,
                'query': url,
            })
            page_count += 1
    return photos


def wikimapia_photos_for_links(links: list[dict], limit: int = 12) -> list[dict]:
    """Give object galleries their own page budget, independent of other sites."""
    return generic_page_photos_for_links(
        [link for link in links if is_object_url(str(link.get('url') or ''))],
        limit,
    )


def site_photos_for_links(
    links: list[dict],
    limit: int = _MAX_VK_PHOTOS,
    *,
    vk_token: str = '',
) -> list[dict]:
    """VK + Urban3P + Swalker + YouTube + Rutube + Планета/caves/web galleries."""
    if limit <= 0:
        return []
    # Fetch each family with its own budget, then round-robin so one report
    # cannot crowd out YouTube/Rutube/Планета/VK.
    family_limit = max(limit, 4)
    buckets = [
        wikimapia_photos_for_links(links, family_limit),
        vk_photos_for_links(vk_token, links, family_limit),
        urban3p_photos_for_links(links, family_limit),
        swalker_photos_for_links(links, family_limit),
        youtube_photos_for_links(links, family_limit),
        rutube_photos_for_links(links, family_limit),
        generic_page_photos_for_links(
            [link for link in links if not is_object_url(str(link.get('url') or ''))],
            family_limit,
        ),
    ]
    photos: list[dict] = []
    seen: set[str] = set()
    index = 0
    while len(photos) < limit and any(buckets):
        bucket = buckets[index % len(buckets)]
        index += 1
        if not bucket:
            continue
        item = bucket.pop(0)
        key = str(item.get('image_url') or '').rstrip('/').casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        photos.append(item)
    return photos


def description_photos_for_links(
    links: list[dict],
    *,
    vk_token: str = '',
    limit: int = _MAX_VK_PHOTOS,
    place: dict | None = None,
) -> list[dict]:
    """VK + Dzen + Maps + site/web/video photos from description links."""
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

    absorb(direct_photos(links))
    absorb(dzen_photos_for_links(links, limit))
    if len(photos) < limit:
        absorb(yandex_maps_photos_for_links(links, limit - len(photos)))
    # Reserve room for Urban3P/Swalker galleries before Maps org photos fill the budget.
    site_reserve = min(6, max(0, limit - len(photos)))
    maps_budget = max(0, limit - len(photos) - site_reserve)
    if place is not None and maps_budget > 0:
        absorb(yandex_maps_photos_for_place(place, maps_budget))
    if len(photos) < limit:
        absorb(site_photos_for_links(
            links, limit - len(photos), vk_token=vk_token,
        ))
    return photos
