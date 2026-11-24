"""Wikimapia photo links and object galleries (never map tiles or UI images)."""
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse


def object_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or parsed.hostname not in {'wikimapia.org', 'www.wikimapia.org'}:
        return None
    try:
        if parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
            return None
    except ValueError:
        return None
    match = re.match(r'^/(\d+)(?:/|$)', parsed.path)
    if match:
        return url
    shown = parse_qs(parsed.fragment).get('show', [''])[0]
    # Map shares can include a translated slug and an open gallery photo.
    # Only the object ID and explicit language belong in the page request.
    match = re.fullmatch(
        r'/(\d+)(?:/([a-z]{2})(?=/|$))?(?:/(?!photo(?:/|$))[^/?#]+)?'
        r'(?:/photo/\d+)?/?', shown, re.I,
    )
    if not match:
        return None
    language = f'/{match[2]}' if match[2] else ''
    return f'https://wikimapia.org/{match[1]}{language}'


def photo_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or parsed.hostname != 'photos.wikimapia.org':
        return None
    if not re.fullmatch(r'/p/(?:\d{2}/){4}\d{2}(?:_(?:\d+|big))?\.jpg', parsed.path):
        return None
    return 'https://photos.wikimapia.org' + parsed.path


def is_object_url(url: str) -> bool:
    return object_url(url) is not None


def gallery_source_links(photos: list[dict], place: dict) -> list[dict]:
    """Present object sources as map links after verification and extraction."""
    from .osint_identity import coordinates, source_key
    output = []
    for photo in photos:
        source = str(photo.get('source_url') or '')
        target = object_url(source)
        identity = photo.get('page_identity') or {}
        if identity.get('source_key') != source_key(source):
            identity = {}
        point = coordinates(place) or coordinates(identity)
        if not target or not point:
            output.append(photo)
            continue
        parts = urlparse(target).path.strip('/').split('/')
        language = parts[1] if len(parts) > 1 and re.fullmatch('[a-z]{2}', parts[1]) else 'ru'
        shown = f'/{parts[0]}/{language}'
        title = str(identity.get('title') or '').strip()
        if title:
            shown += '/' + re.sub(r'[\s/?#&=]+', '-', title[:300])
        fragment = urlencode({
            'lang': 'en', 'lat': f'{point[0]:.6f}', 'lon': f'{point[1]:.6f}',
            'z': 13, 'm': 'w', 'show': shown,
        }, safe='/', quote_via=quote)
        output.append(dict(photo, original_source_url=photo.get('original_source_url') or source,
                           source_url='https://wikimapia.org/#' + fragment))
    return output


def gallery_urls(html: str, page_url: str) -> list[str]:
    return [photo['image_url'] for photo in gallery_images(html, page_url)]


def gallery_images(html: str, page_url: str) -> list[dict]:
    class Gallery(HTMLParser):
        def __init__(self):
            super().__init__()
            self.photos = {}

        def handle_starttag(self, tag, attrs):
            if tag not in {'a', 'img'}:
                return
            for key, value in attrs:
                if key not in {'href', 'src', 'data-src'} or not value:
                    continue
                url = photo_url(urljoin(page_url, value))
                if not url:
                    continue
                identity = re.sub(r'_(?:\d+|big)(?=\.jpg$)', '', url)
                size = re.search(r'_(\d+)\.jpg$', url)
                rank = 10000 if url.endswith('_big.jpg') else int(size[1]) if size else 0
                self.photos.setdefault(identity, {})[url] = rank

    parser = Gallery()
    parser.feed(html)
    result = []
    for variants in parser.photos.values():
        full = max(variants, key=variants.get)
        thumbnail = min(variants, key=variants.get)
        result.append({'image_url': full, 'thumbnail_url': thumbnail})
    return result


def direct_photos(links: list[dict]) -> list[dict]:
    return [dict(title='Фото объекта · Wikimapia', image_url=image,
                 thumbnail_url=image, source_url=link['url'], engine='wikimapia',
                 attribution='Wikimapia', score=12.0, query=link['url'])
            for link in links if (image := photo_url(str(link.get('url') or '')))]


def fetch_html(url: str) -> str:
    """Recover a broken translation from the same object's English page."""
    target = object_url(url)
    if not target:
        return ''
    html = _fetch_html(target)
    if re.search(r'ошибка\s+RK\s+n\.22', html, re.I):
        parts = urlparse(target).path.strip('/').split('/')
        if len(parts) < 2 or parts[1] != 'en':
            fallback = _fetch_html(f'https://wikimapia.org/{parts[0]}/en/')
            if fallback and not re.search(r'ошибка\s+RK\s+n\.22', fallback, re.I):
                return fallback
    return html


def _fetch_html(url: str) -> str:
    """Handle Wikimapia's session-cookie refresh without executing page scripts."""
    import httpx
    from time import monotonic
    url = object_url(url)
    if not url:
        return ''
    original = urlparse(url)
    try:
        if original.username or original.password or original.port not in {None, 80, 443}:
            return ''
    except ValueError:
        return ''
    object_id = original.path.strip('/').split('/')[0]
    target = original._replace(scheme='https', netloc='wikimapia.org', fragment='').geturl()
    cookie_refreshes = 0
    try:
        with httpx.Client(
            timeout=httpx.Timeout(8, connect=5),
            transport=httpx.HTTPTransport(retries=1),
            follow_redirects=False,
            headers={
                'User-Agent': (
                    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ),
                'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
            },
        ) as client:
            started = monotonic()
            for _ in range(4):
                with client.stream('GET', target) as response:
                    if response.is_redirect:
                        redirect = urlparse(urljoin(target, response.headers.get('location', '')))
                        if (redirect.scheme not in {'http', 'https'}
                                or redirect.hostname not in {'wikimapia.org', 'www.wikimapia.org'}
                                or redirect.username or redirect.password or redirect.port not in {None, 80, 443}
                                or redirect.path.strip('/').split('/')[0] != object_id):
                            return ''
                        target = redirect._replace(scheme='https', netloc='wikimapia.org').geturl()
                        continue
                    if response.status_code != 200:
                        return ''
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 1_000_000 or monotonic() - started > 15:
                            return ''
                    html = body.decode(response.encoding or 'utf-8', errors='replace')
                cookie = re.search(r'document\.cookie\s*=\s*["\']nsess=([a-f0-9]{32})["\']', html)
                if cookie and len(html) < 2000 and cookie_refreshes < 2:
                    client.cookies.set('nsess', cookie[1], domain='wikimapia.org', path='/')
                    cookie_refreshes += 1
                    continue
                return html if not cookie and len(html) >= 400 else ''
    except (httpx.HTTPError, ValueError):
        pass
    return ''


def enrich_identity(identity: dict, html: str, url: str) -> dict:
    """Read coordinates of the object, never nearby objects or the map viewport."""
    if not is_object_url(url):
        return identity
    from selectolax.lexbor import LexborHTMLParser
    from math import isfinite
    tree = LexborHTMLParser(html)
    canonical = tree.css_first('meta[property="og:url"]')
    if canonical:
        declared = canonical.attributes.get('content', '')
        if (not is_object_url(declared)
                or urlparse(declared).path.strip('/').split('/')[0] != urlparse(url).path.strip('/').split('/')[0]):
            return identity
    result = dict(identity)
    for field, bound in [('latitude', 90), ('longitude', 180)]:
        node = tree.css_first(f'meta[property="place:location:{field}"]')
        try:
            value = float(node.attributes.get('content', '')) if node else float('nan')
            if isfinite(value) and -bound <= value <= bound:
                result[field] = value
        except ValueError:
            pass
    return result
