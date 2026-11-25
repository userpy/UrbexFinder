"""Parse only the requested public VK album, excluding group/sidebar content."""
import re
from html.parser import HTMLParser
from urllib.parse import urlparse


class AlbumParser(HTMLParser):
    def __init__(self, album_path: str):
        super().__init__(convert_charrefs=True)
        self.album_path = album_path
        self.canonical = ''
        self.stack = []
        self.title = []
        self.description = []
        self.photos = []
        self.owner = album_path.removeprefix('album').split('_')[0]

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get('class', '').split())
        if tag == 'meta' and (attrs.get('property') or attrs.get('name')) == 'og:url':
            self.canonical = attrs.get('content') or attrs.get('value') or ''
        scopes = set().union(*(frame[1] for frame in self.stack)) if self.stack else set()
        own = set()
        if 'photos_album_intro' in classes:
            own.add('intro')
        if 'photos_album_intro_desc' in classes:
            own.add('description')
        if tag == 'h1' and 'intro' in scopes:
            own.add('title')
        if attrs.get('id') == 'photos_container_photos':
            own.add('gallery')
        if 'gallery' in scopes and 'photos_row' in classes:
            photo_id = attrs.get('data-id', '')
            match = re.search(r'''background-image\s*:\s*url\(\s*["']?([^\s)'"<>]+)''', attrs.get('style', ''))
            if match and re.fullmatch(re.escape(self.owner) + r'_\d+', photo_id):
                image = match.group(1)
                parsed = urlparse(image)
                host = (parsed.hostname or '').lower()
                if parsed.scheme == 'https' and any(
                    host == domain or host.endswith('.' + domain)
                    for domain in ('userapi.com', 'vkuserphoto.ru')
                ):
                    if image not in self.photos:
                        self.photos.append(image)
        if tag == 'br':
            self.handle_data('\n')
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append((tag, own))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        scopes = set().union(*(frame[1] for frame in self.stack)) if self.stack else set()
        if any(frame[0] in {'script', 'style'} for frame in self.stack):
            return
        if 'title' in scopes:
            self.title.append(data)
        if 'description' in scopes:
            self.description.append(data)


def parse_vk_album(html: str, url: str) -> dict:
    path = urlparse(url).path.strip('/')
    parser = AlbumParser(path)
    parser.feed(html)
    canonical = urlparse(parser.canonical)
    if (canonical.hostname not in {'vk.com', 'www.vk.com', 'vk.ru', 'www.vk.ru', 'm.vk.com', 'm.vk.ru'}
            or canonical.path.strip('/') != path):
        return {'title': '', 'description': '', 'photos': []}
    return {
        'title': ''.join(parser.title).strip()[:300],
        'description': ''.join(parser.description).strip()[:800],
        'photos': parser.photos,
    }
