"""Wikimapia photo links and object galleries (never map tiles or UI images)."""
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlparse


def photo_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or parsed.hostname != 'photos.wikimapia.org':
        return None
    if not re.fullmatch(r'/p/(?:\d{2}/){4}\d{2}(?:_\d+)?\.jpg', parsed.path):
        return None
    return 'https://photos.wikimapia.org' + parsed.path


def is_object_url(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.scheme in {'http', 'https'}
            and parsed.hostname in {'wikimapia.org', 'www.wikimapia.org'}
            and bool(re.match(r'^/\d+(?:/|$)', parsed.path)))


def gallery_urls(html: str, page_url: str) -> list[str]:
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
                identity = re.sub(r'_\d+(?=\.jpg$)', '', url)
                size = re.search(r'_(\d+)\.jpg$', url)
                rank = int(size[1]) if size else 0
                if identity not in self.photos or rank > self.photos[identity][0]:
                    self.photos[identity] = (rank, url)

    parser = Gallery()
    parser.feed(html)
    return [url for _, url in parser.photos.values()]


def direct_photos(links: list[dict]) -> list[dict]:
    return [dict(title='Фото объекта · Wikimapia', image_url=image,
                 thumbnail_url=image, source_url=link['url'], engine='wikimapia',
                 score=12.0, query=link['url'])
            for link in links if (image := photo_url(str(link.get('url') or '')))]
