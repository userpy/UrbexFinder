"""Bounded HTML extraction. Structured data is evidence only for a single main place."""
import re
from urllib.parse import urljoin, urlparse

import extruct
from selectolax.lexbor import LexborHTMLParser

PRIMARY = 'article, [itemprop~="articleBody"], .item-page, .entry-content, .article-content'
PLACE_TYPES = {'Place', 'LandmarksOrHistoricalBuildings', 'TouristAttraction', 'Residence', 'House'}
NOISE = re.compile(r'footer|sidebar|related|recommend|comment|advert|banner', re.I)


def http_url(raw, base):
    if not isinstance(raw, str):
        return ''
    url = urljoin(base, raw.strip())
    try:
        p = urlparse(url)
        return url if p.scheme in {'http', 'https'} and p.hostname and not p.username and not p.password else ''
    except ValueError:
        return ''


def _micro(node):
    if isinstance(node, list):
        values = [_micro(x) for x in node]
        return values[0] if len(values) == 1 else values
    if not isinstance(node, dict):
        return node
    if 'properties' in node:
        return {'@type': node.get('type', []), **{k: _micro(v) for k, v in node['properties'].items()}}
    return {k: _micro(v) for k, v in node.items()}


def main_entity(html, url, key):
    try:
        data = extruct.extract(html, base_url=url, syntaxes=['json-ld', 'microdata'])
    except (ValueError, TypeError, RecursionError):
        return None
    roots = list(data.get('json-ld', [])) + [_micro(n) for n in data.get('microdata', [])]
    candidates = []
    for root in roots:
        if not isinstance(root, dict):
            continue
        # Never traverse arbitrary @graph, publisher, related objects or ItemList.
        node = root.get('mainEntity', root)
        if not isinstance(node, dict):
            continue
        types = node.get('@type', [])
        types = [types] if isinstance(types, str) else types
        if not isinstance(types, list) or not {str(t).rstrip('/').split('/')[-1] for t in types} & PLACE_TYPES:
            continue
        declared = node.get('url')
        if declared and (not isinstance(declared, str) or key(urljoin(url, declared)) != key(url)):
            continue
        if node not in candidates:
            candidates.append(node)
    # Multiple independent places on a page cannot provide unambiguous identity.
    return candidates[0] if len(candidates) == 1 else None


def parse_page(html, url, key):
    html = str(html or '')[:1_000_000]
    tree = LexborHTMLParser(html)
    for node in reversed(tree.css('nav, aside, footer, style, [class], [id]')):
        if node.tag in {'html', 'body'}:
            continue
        if node.tag in {'nav', 'aside', 'footer', 'style'} or NOISE.search(
                node.attributes.get('class', '') + ' ' + node.attributes.get('id', '')):
            node.decompose()
    heading = tree.css_first('h1') or tree.css_first('title')
    result = {'source_key': key(url), 'title': heading.text(separator=' ', strip=True)[:300] if heading else '', 'text': ''}
    entity = main_entity(tree.html, url, key)
    for node in tree.css('script'):
        node.decompose()
    containers = tree.css(PRIMARY)
    if not containers:
        containers = tree.css('main')
    result['text'] = ' '.join(n.text(separator=' ', strip=True) for n in containers)[:4000]
    images = []
    for container in containers:
        for node in container.css('img, picture source, a[href]'):
            attrs = node.attributes
            if node.tag == 'a':
                value = attrs.get('href', '')
                if re.search(r'\.(?:jpe?g|png|webp)(?:\?|$)', value, re.I):
                    images.append(value)
                continue
            # Prefer the largest responsive variant, then lazy loading, then src.
            responsive = attrs.get('data-srcset') or attrs.get('srcset') or ''
            variants = []
            for part in responsive.split(','):
                match = re.fullmatch(r'\s*(\S+)\s+(\d+(?:\.\d+)?)[wx]\s*', part)
                if match:
                    variants.append((float(match[2]), match[1]))
            value = max(variants)[1] if variants else (
                attrs.get('data-src') or attrs.get('data-original') or attrs.get('data-lazy-src') or attrs.get('src'))
            if value:
                images.append(value)
    if entity:
        if isinstance(entity.get('name'), str):
            result['title'] = entity['name'][:300]
        address = entity.get('address')
        if isinstance(address, dict):
            result['locality'] = str(address.get('addressLocality') or '')[:300]
            result['address'] = ', '.join(address[k] for k in ('streetAddress', 'addressLocality', 'addressRegion') if isinstance(address.get(k), str))[:500]
        elif isinstance(address, str):
            result['address'] = address[:500]
        geo = entity.get('geo')
        if isinstance(geo, dict):
            for field in ('latitude', 'longitude'):
                if isinstance(geo.get(field), (str, int, float)):
                    result[field] = geo[field]
        media = entity.get('image', [])
        for item in media if isinstance(media, list) else [media]:
            if isinstance(item, dict):
                item = item.get('contentUrl') or item.get('url')
            if isinstance(item, str):
                images.append(item)
    urls = list(dict.fromkeys(u for raw in images if (u := http_url(raw, url))))
    return result, bool(containers or entity), urls[:100]
