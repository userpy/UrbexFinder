"""Deterministic object identity checks. Never use a query or an image filename as evidence."""
from dataclasses import dataclass
from html.parser import HTMLParser
from math import asin, cos, radians, sin, sqrt, isfinite
import json
import re
from urllib.parse import parse_qsl, urlencode, unquote, urlparse, urljoin

VERSION = 2


def normalized(text):
    return re.sub(r'\s+', ' ', str(text or '').casefold().replace('ё', 'е')).strip()


def source_key(url):
    """Only documented object URLs share identity; arbitrary URL paths stay case sensitive."""
    try:
        p = urlparse(str(url or ''))
        host = (p.hostname or '').lower().removeprefix('www.')
        if p.scheme not in {'http', 'https'} or not host or p.username or p.password:
            return ''
        path = unquote(p.path).rstrip('/')
        families = {
            'wikimapia.org': r'^/(\d+)(?:/|$)',
            'geocaching.su': r'^/cache/(\d+)(?:/|$)',
            'urban3p.ru': r'^/object(\d+)(?:/|$)',
            'urban3p.com': r'^/object(\d+)(?:/|$)',
            'vk.com': r'^/(album-?\d+_\d+|photo-?\d+_\d+|wall-?\d+_\d+)$',
            'vk.ru': r'^/(album-?\d+_\d+|photo-?\d+_\d+|wall-?\d+_\d+)$',
        }
        if host in families and (m := re.match(families[host], path)):
            family = {'urban3p.com': 'urban3p.ru', 'vk.ru': 'vk.com'}.get(host, host)
            return f'{family}:{m[1]}'
        query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query)
                                 if not k.lower().startswith('utm_') and k not in {'fbclid', 'gclid'}))
        return f'{host}:{p.port or ""}{path}' + ('?' + query if query else '')
    except ValueError:
        return ''


_TYPES = {
    'shelter': r'\b(?:убежищ|бомбоубежищ|бункер)[а-я]*\b',
    'manor': r'\bусад(?:ьб|еб)[а-я]*\b',
    'housing': r'\bтаунхаус[а-я]*\b|\bкоттеджн[а-я]*\s+посел[а-я]*\b|\bжил[а-я]*\s+(?:комплекс|квартал)[а-я]*\b|\bжк\b',
    'camp': r'\b(?:пионерск[а-я]*\s+лагер[а-я]*|лагер[а-я]*|детск[а-я]*\s+лагер[а-я]*)\b',
    'factory': r'\b(?:завод|фабрик|комбинат)[а-я]*\b',
    'church': r'\b(?:церков|церкв|храм|собор|часовн)[а-я]*\b',
    'school': r'\b(?:школ|училищ|спту|пту)[а-я]*\b',
    'kindergarten': r'\bдетск[а-я]*\s+сад[а-я]*\b',
    'military': r'\b(?:воинск|войсков)[а-я]*\s+част[а-я]*\b',
    'hospital': r'\b(?:больниц|госпитал|санатори)[а-я]*\b',
}
_GENERIC = set('заброшенный заброшенная заброшенное заброшенные бывший бывшая старый старая старое новый новая летний детский пионерский оздоровительный стандартное подземное корпуса корпус территория территории новой гражданской обороны го ру ru en фото объект место на в и у имени им'.split())


def kinds(text):
    value = normalized(text)
    return {kind for kind, pattern in _TYPES.items() if re.search(pattern, value)}


def name_cues(name):
    text = normalized(re.sub(r'\((?:ru|en)\)', '', str(name or ''), flags=re.I))
    for pattern in _TYPES.values():
        text = re.sub(pattern, ' ', text)
    return {word for word in re.findall(r'[а-яa-z0-9]+', text)
            if len(word) >= 3 and word not in _GENERIC}


def words_present(cues, text):
    words = set(re.findall(r'[а-яa-z0-9]+', normalized(text)))
    return bool(cues) and cues <= words


def address_parts(text):
    """Extract street+house without treating arbitrary dates as house numbers."""
    value = normalized(text)
    street = ''
    house = ''
    marker = r'(?:улица|ул\.|проспект|пр-т|переулок|пер\.|шоссе|набережная|аллея)'
    m = re.search(rf'(?:^|[,;])\s*{marker}\s+([^,;]+)', value)
    if not m:
        m = re.search(rf'(?:^|[,;])\s*([^,;]+?)\s+{marker}(?=\s|[,;]|$)', value)
    if m:
        street = m[1].strip()
        number = re.search(r'(?:,\s*|\s+(?:дом|д\.)\s*)(\d+[а-яa-z]?(?:[/\-]\d+[а-яa-z]?)?(?:\s*(?:к(?:орпус)?\.?|стр\.?)\s*\d+)?)', value[m.end():])
        if number:
            house = re.sub(r'\s+', '', number[1])
    return street, house


def locality_cues(text):
    value = normalized(text)
    result = set()
    for pattern in [r'\b(?:деревня|село|поселок|город|г\.|д\.)\s+([а-я-]+)',
                    r'\b([а-я-]+)\s+(?:район|муниципальный округ|городской округ|область)\b']:
        result.update(re.findall(pattern, value))
    # A region on its own is too coarse for namesakes.
    result -= {'московская', 'москва', 'россия', 'центральный'}
    return result


def settlement_cues(address):
    value = normalized(address)
    cities = set(re.findall(r'\b(?:город|г\.|деревня|село|поселок)\s+([а-я-]+)', value))
    cities.update(part.strip() for part in value.split(',')
                  if re.fullmatch(r'[а-я-]+', part.strip()) and part.strip() not in {'россия', 'рф'})
    return cities


def coordinates(data):
    try:
        lat, lon = float(data['latitude']), float(data['longitude'])
        if isfinite(lat) and isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    except (KeyError, TypeError, ValueError):
        pass
    return None


def distance(a, b):
    la, lo, lb, lob = map(radians, (*a, *b))
    return 6371000 * 2 * asin(min(1, sqrt(sin((lb-la)/2)**2 + cos(la)*cos(lb)*sin((lob-lo)/2)**2)))


@dataclass(frozen=True)
class Decision:
    status: str
    reasons: tuple[str, ...]
    evidence: tuple[str, ...] = ()

    def json(self):
        return dict(status=self.status, reasons=list(self.reasons), evidence=list(self.evidence), version=VERSION)


def verify_source(place, source, reference_urls=()):
    key = source_key(source.get('url') or source.get('source_url'))
    if not key:
        return Decision('rejected', ('Некорректная ссылка источника',))
    # A prior decision or an engine label cannot grant trust.
    reference_keys = {source_key(url) for url in reference_urls} - {''}
    primary = source.get('page_identity') or {}
    if primary.get('source_key') != key:
        primary = {}
    title = primary.get('title') or source.get('title') or ''
    text = ' '.join(str(x or '') for x in (title, primary.get('text'), source.get('snippet')))
    place_types = kinds(' '.join(str(place.get(k) or '') for k in ('name', 'category_name', 'category', 'description')))
    source_types = kinds(title)
    compatible = bool(place_types & source_types)
    conflicts = []
    if 'housing' in source_types and place_types - {'housing'}:
        conflicts.append('Жилая застройка вместо искомого объекта')
    if source_types and place_types and not compatible:
        conflicts.append('Не совпадает тип объекта')
    place_address = place.get('full_address') or place.get('region') or ''
    street, house = address_parts(place_address)
    candidate_address = primary.get('address') or title
    candidate_street, candidate_house = address_parts(candidate_address)
    place_regions = set(re.findall(r'\b([а-я-]+)\s+область\b', normalized(place_address)))
    candidate_regions = set(re.findall(r'\b([а-я-]+)\s+область\b', normalized(candidate_address)))
    if place_regions and candidate_regions and not place_regions & candidate_regions:
        conflicts.append('Указан другой регион')
    locality = normalized(primary.get('locality'))
    if locality:
        # Explicit locality in structured primary evidence must occur in the
        # card address; an oblast-only address cannot contradict a city.
        place_cities = set(re.findall(r'\b(?:город|г\.)\s+([а-я-]+)', normalized(place_address)))
        if 'москва' in normalized(place_address).split(', '): place_cities.add('москва')
        if place_cities and locality not in place_cities:
            conflicts.append('Указан другой населённый пункт')
    if street and candidate_street and street != candidate_street:
        conflicts.append('Указана другая улица')
    if street and street == candidate_street and house and candidate_house and house != candidate_house:
        conflicts.append('Указан другой номер дома')
    a, b = coordinates(place), coordinates(primary)
    metres = distance(a, b) if a and b else None
    if metres is not None and metres > 1500:
        conflicts.append('Координаты источника дальше 1,5 км от объекта')
    # Institution numbers must not be supplied by dates or unrelated URL IDs.
    codes = re.findall(r'\b([А-ЯA-Z]{2,10})\s*(?:[-–—№]\s*|\s+)(\d+)\b', str(place.get('name') or ''))
    numbered_match = bool(codes)
    for code, number in codes:
        found = re.findall(rf'\b{re.escape(code)}\s*(?:[-–—№]\s*|\s+)(\d+)\b', text, re.I)
        numbered_match = numbered_match and number in found
        if found and number not in found:
            conflicts.append('Не совпадает номер объекта')
    if conflicts:
        return Decision('rejected', tuple(conflicts))
    if key in reference_keys:
        return Decision('accepted', ('Исходная ссылка или тот же идентификатор объекта',), ('reference',))
    cues = name_cues(place.get('name'))
    same_name = words_present(cues, title) or numbered_match
    settlements = settlement_cues(place_address)
    same_settlement = bool(settlements) and words_present(settlements, str(candidate_address) + ' ' + str(primary.get('locality') or ''))
    if compatible and same_settlement and street and street == candidate_street and house and house == candidate_house:
        return Decision('accepted', ('Совпали населённый пункт, улица, дом и тип объекта',), ('address', 'type'))
    # Require precise proximity, not a whole-city search coordinate or a map centre.
    if metres is not None and metres <= 100 and compatible and same_name:
        return Decision('accepted', ('Совпали координаты, название и тип объекта',), ('coordinates', 'name', 'type'))
    local = locality_cues(place_address)
    # A lone common name needs more than a region. Multiple distinctive words
    # (or a numbered institution) plus location can establish a match.
    strong_name = same_name and (len(cues) >= 2 or bool(codes))
    if strong_name and compatible and any(words_present({cue}, text) for cue in local):
        return Decision('accepted', ('Совпали отличительные признаки названия, местоположение и тип',), ('name', 'location', 'type'))
    return Decision('unconfirmed', ('Недостаточно данных для привязки к конкретному объекту',),
                    tuple(x for x, ok in [('name', same_name), ('type', compatible)] if ok))


def _primary_container(tag, attrs):
    return (tag in {'main', 'article'}
            or 'articleBody' in str(attrs.get('itemprop', '')).split()
            or bool(set(str(attrs.get('class', '')).split()) & {'item-page', 'entry-content', 'article-content'}))


def catalog_gallery_matches(photo):
    """Podmoskovnye's per-estate photo directory can verify old parsed galleries."""
    page = urlparse(str(photo.get('source_url') or ''))
    image = urlparse(str(photo.get('image_url') or ''))
    hosts = {'podmoskovnye.ru', 'www.podmoskovnye.ru'}
    if (page.hostname not in hosts or image.hostname not in hosts
            or page.scheme not in {'http', 'https'} or image.scheme not in {'http', 'https'}):
        return False
    match = re.fullmatch(r'/usadba/[^/]+/\d+-([a-z-]+)/\d+-([a-z0-9-]+)', unquote(page.path).rstrip('/'))
    if not match:
        return False
    region, estate = match.groups()
    parts = unquote(image.path).split('/')
    return (len(estate) >= 4 and len(parts) == 7
            and parts[:6] == ['', 'images', 'stories', 'photos', region, estate]
            and bool(re.fullmatch(r'[^/]+\.(?:jpe?g|png|webp)', parts[6], re.I)))


class _PrimaryHTML(HTMLParser):
    """Read main/article content; never mine navigation, footer or sidebars for addresses."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.title = []
        self.heading = []
        self.body = []
        self.scripts = []
        self.script = []
        self.images = []
        self.has_primary = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if _primary_container(tag, attrs):
            self.has_primary = True
        tags = {frame[0] for frame in self.stack}
        excluded = tags & {'nav', 'aside', 'footer'} or any(
            re.search(r'footer|sidebar|related|recommend|comment|advert|banner', str(a.get('class', '')), re.I)
            for _, a in self.stack + [(tag, attrs)]
        )
        inside_primary = any(_primary_container(t, a) for t, a in self.stack)
        if tag in {'img', 'a'} and inside_primary and not excluded:
            for attr in ('src', 'data-src', 'href'):
                value = attrs.get(attr, '')
                if re.search(r'\.(?:jpg|jpeg|png|webp)(?:\?|$)', value, re.I):
                    self.images.append(value)
        self.stack.append((tag, attrs)) if tag not in {'meta','link','img','br','hr','input','source','wbr','area','base','embed','param'} else None
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.script = []

    def handle_endtag(self, tag):
        if tag == 'script' and self.stack and self.stack[-1][1].get('type') == 'application/ld+json':
            self.scripts.append(''.join(self.script))
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, value):
        tags = {x[0] for x in self.stack}
        if 'script' in tags:
            self.script.append(value)
            return
        excluded = {'nav','aside','footer','style'}
        if tags & excluded or any(re.search(r'footer|sidebar|related|recommend|comment', str(a.get('class','')), re.I) for _, a in self.stack):
            return
        if 'title' in tags: self.title.append(value)
        if 'h1' in tags: self.heading.append(value)
        if any(_primary_container(t, a) for t, a in self.stack): self.body.append(value)


def primary_gallery(html, url):
    parser = _PrimaryHTML()
    parser.feed(html[:1_000_000])
    return parser.has_primary, list(dict.fromkeys(urljoin(url, image) for image in parser.images))


def extract_page_identity(html, url):
    parser = _PrimaryHTML()
    parser.feed(html[:1_000_000])
    result = {'source_key': source_key(url), 'title': ' '.join(parser.heading or parser.title)[:300],
              'text': ' '.join(parser.body)[:4000]}
    # Only the page's main entity/root Place is eligible. Ignore publishers,
    # recommendations, ItemList and arbitrary nested Organization addresses.
    allowed = {'Place', 'LandmarksOrHistoricalBuildings', 'TouristAttraction', 'Residence', 'House'}
    for raw in parser.scripts:
        try: node = json.loads(raw)
        except (ValueError, TypeError): continue
        if not isinstance(node, dict): continue
        node = node.get('mainEntity', node)
        if not isinstance(node, dict): continue
        types = node.get('@type', [])
        if isinstance(types, str): types = [types]
        if not set(types) & allowed: continue
        if node.get('url') and source_key(node['url']) != source_key(url): continue
        result['title'] = str(node.get('name') or result['title'])[:300]
        address = node.get('address')
        if isinstance(address, dict):
            result['locality'] = str(address.get('addressLocality') or '')
            result['address'] = ', '.join(str(address[k]) for k in ('streetAddress', 'addressLocality', 'addressRegion') if address.get(k))
        elif isinstance(address, str): result['address'] = address[:500]
        geo = node.get('geo')
        if isinstance(geo, dict) and coordinates(geo):
            result.update(latitude=geo['latitude'], longitude=geo['longitude'])
        break
    return result


def verify_report(report, place, reference_urls, *, junk_source=lambda item: False, junk_photo=lambda item: False):
    """Recompute decisions from original evidence, including previously withheld candidates."""
    output = dict(report)
    prior = report.get('verification') or {}
    sources = list(report.get('items') or []) + list(report.get('source_candidates') or [])
    sources += [row['candidate'] for row in prior.get('sources', []) if isinstance(row.get('candidate'), dict)]
    photos = list(report.get('photos') or []) + list(report.get('photo_candidates') or [])
    photos += [row['candidate'] for row in prior.get('photos', []) if isinstance(row.get('candidate'), dict)]
    # A parsed gallery may supply primary-page evidence absent in a search snippet.
    for photo in photos:
        if photo.get('source_url') and photo.get('source_url') != photo.get('image_url'):
            sources.append({'url': photo['source_url'], 'title': photo.get('title', ''),
                            'snippet': '', 'engine': photo.get('engine'),
                            'page_identity': photo.get('page_identity'), 'query': ''})
    unique = {}
    for item in sources:
        key = source_key(item.get('url'))
        if key and key not in unique:
            unique[key] = dict(item)
        elif key and item.get('page_identity') and not unique[key].get('page_identity'):
            unique[key]['page_identity'] = item['page_identity']
    decisions = {}
    audits = []
    accepted = []
    for key, item in list(unique.items())[:60]:
        decision = verify_source(place, item, reference_urls)
        if junk_source(item) and 'reference' not in decision.evidence:
            decision = Decision('rejected', ('Общая страница, служебный материал или неподходящий источник',))
        decisions[key] = decision
        audits.append(dict(candidate=item, **decision.json()))
        if decision.status == 'accepted': accepted.append(item)
    photo_audits = []
    accepted_photos = []
    seen = set()
    reference_keys = {source_key(url) for url in reference_urls}
    gallery_engines = {'wikimapia', 'geocache', 'vk', 'urban3p', 'swalker', 'web_page',
                       'planetadorog', 'caves', 'urbexstalker', 'dzen', 'yandex_maps', 'youtube', 'rutube'}
    for photo in photos:
        image = photo.get('image_url')
        if not image or image in seen: continue
        seen.add(image)
        if len(photo_audits) >= 48: break
        parent = source_key(photo.get('source_url'))
        decision = decisions.get(parent, Decision('unconfirmed', ('Нет подтверждённой страницы источника',)))
        direct = source_key(image) in reference_keys
        if direct:
            decision = Decision('accepted', ('Прямая ссылка на фото из описания объекта',), ('reference_image',))
        elif decision.status == 'accepted':
            gallery = photo.get('engine') in gallery_engines and source_key(photo.get('query')) == parent
            # Older parser-produced gallery records predate the query field.
            image_parts = urlparse(str(image))
            legacy_gallery = (
                photo.get('engine') == 'geocache'
                and image_parts.hostname in {'geocaching.su', 'www.geocaching.su'}
                and bool(re.fullmatch(r'/photos/areas/\d+\.(?:jpg|png|webp)', image_parts.path))
            ) or (
                photo.get('engine') == 'wikimapia' and image_parts.hostname == 'photos.wikimapia.org'
                and bool(re.fullmatch(r'/p/(?:\d{2}/){4}\d{2}(?:_\d+)?\.jpg', image_parts.path))
            )
            gallery = gallery or (parent in reference_keys and legacy_gallery)
            if photo.get('engine') in {'web_page', 'planetadorog', 'caves', 'urbexstalker'}:
                gallery = gallery and (photo.get('gallery_scope') == 'primary' or catalog_gallery_matches(photo))
            if not gallery:
                decision = Decision('unconfirmed', ('Не подтверждено, что фото входит в галерею принятого источника',))
            else:
                decision = Decision('accepted', ('Фото извлечено из галереи подтверждённого источника',), ('gallery', parent))
        junk_candidate = dict(photo, title='') if parent in reference_keys else photo
        if junk_photo(junk_candidate):
            decision = Decision('rejected', ('Служебное или неподходящее изображение',))
        photo_audits.append(dict(candidate=photo, **decision.json()))
        if decision.status == 'accepted': accepted_photos.append(photo)
    output.pop('source_candidates', None)
    output.pop('photo_candidates', None)
    output.update(items=accepted[:12], photos=accepted_photos[:12], total=min(12, len(accepted)),
                  photos_total=min(12, len(accepted_photos)),
                  verification={'version': VERSION, 'sources': audits, 'photos': photo_audits})
    return output
