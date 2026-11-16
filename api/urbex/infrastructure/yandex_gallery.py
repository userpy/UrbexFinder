"""Read photographs belonging to one Yandex organization, not all page images."""
from html.parser import HTMLParser
import json
from .osint_identity import source_key


class _StateParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts = []
        self.states = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and 'state-view' in attrs.get('class', '').split():
            self.active = True
            self.parts = []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.active:
            self.states.append(''.join(self.parts))
            self.active = False


def org_gallery(html: str, oid: str, url: str) -> dict | None:
    parser = _StateParser()
    parser.feed(html)
    if not parser.states:
        return None
    for raw in parser.states:
        try:
            state = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(state, dict):
            continue
        for entry in state.get('stack', []):
            if not isinstance(entry, dict):
                continue
            results = entry.get('results') or {}
            if not isinstance(results, dict):
                continue
            for item in results.get('items', []):
                if not isinstance(item, dict) or str(item.get('id')) != oid:
                    continue
                photos = item.get('photos') or {}
                if not isinstance(photos, dict):
                    continue
                # Never descend into relatedPlaces, reviews, adverts or other results.
                templates = [row.get('urlTemplate', '') for row in photos.get('items', []) if isinstance(row, dict)]
                if not templates and photos.get('urlTemplate'):
                    templates.append(photos['urlTemplate'])
                categories = ' '.join(str(row.get('name') or '') for row in item.get('categories', []) if isinstance(row, dict))
                identity = {'source_key': source_key(url),
                            'title': f"{item.get('title') or ''}, {categories}".strip(', '),
                            'address': str(item.get('address') or '')}
                coords = item.get('coordinates')
                if isinstance(coords, list) and len(coords) == 2:
                    identity.update(longitude=coords[0], latitude=coords[1])
                return {'templates': templates, 'identity': identity}
    # State exists but does not contain the requested organization: fail closed.
    return {}
