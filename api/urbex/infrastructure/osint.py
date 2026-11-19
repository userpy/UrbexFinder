"""OSINT report built from SearXNG (XNG) search results for a place card."""
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from urllib.parse import unquote, urlparse
import httpx
from sqlalchemy import text
from urbex.domain.rules import DomainError
from urbex.infrastructure.osint_identity import verify_report, verify_source, source_key
from urbex.infrastructure.osint_evidence import enrich_candidates, wikipedia_photos_for_sources
from urbex.infrastructure.semantic_ranking import rank_candidates
from urbex.infrastructure.osint_assess import assess_osint_items
from urbex.infrastructure.wikimapia import direct_photos, is_object_url
from urbex.infrastructure.osint_description import (
    description_photos_for_links,
    links_from_description,
    site_photos_for_links,
    urban3p_photos_for_links,
    vk_sources_for_links,
    vk_photos_for_links,
    generic_page_photos_for_links,
    wikimapia_photos_for_links,
    yandex_maps_photos_for_links,
    is_direct_image_url,
    is_vk_group_url,
)

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_last_request = 0.0
_MAX_RESULTS = 12
_MAX_PHOTOS = 12
# Keep cold reports under the Next.js rewrite proxy budget (~30s).
# One slot is reserved for urbex site: queries (Urban3P, Swalker, …).
_MAX_QUERIES = 3
_MAX_IMAGE_QUERIES = 3
# Prefer these RU urbex catalogs over generic web noise.
_URBEX_SITE_DOMAINS = (
    'urban3p.ru',
    'swalker.ru',
    'caves.ru',
    'planetadorog.ru',
    'urbexstalker.com',
    'geocaching.com',
    'geocaching.ru',
    'geocaching.su',
    'opencaching.pl',
    'wikimapia.org',
)
_URBEX_SITE_QUERY = (
    '('
    + ' OR '.join(f'site:{domain}' for domain in _URBEX_SITE_DOMAINS)
    + ')'
)
_URBEX_SITE_TEXT = (
    '(urban3p OR swalker OR caves.ru OR planetadorog OR "планета дорог" '
    'OR urbexstalker OR geocaching OR геокешинг OR opencaching)'
)
_CACHE_SIZE = 256
# Only successful non-empty answers are cached. Empty answers must not stick forever
# when engines were temporarily down.
_search_cache: OrderedDict[tuple[str, str, str, str], tuple[dict, ...]] = OrderedDict()

# Image search often returns memes / game screenshots for words like «бомбоубежище».
_IMAGE_JUNK_HOSTS = (
    'pinterest.', 'pinimg.', 'pin.it',
    'tenor.com', 'giphy.com', 'imgflip.com',
    'deviantart.com', 'artstation.com',
    'steamcommunity.com', 'steamstatic.com', 'store.steampowered.com',
    'roblox.com', 'rbxcdn.com',
    'fandom.com', 'wikia.com',
    # Classifieds / realty — flood generic names like «заброшенный коттедж».
    'avito.ru', 'avito.st', 'cian.ru', 'cdn-cian.ru', 'youla.ru',
    'domclick.ru', 'mirkvartir.ru', 'realty.', 'n1.ru', 'move.ru',
    'sob.ru', 'jcat.ru', 'restate.ru',
    # Wire / news agencies — drown place searches with geopolitics.
    'tass.ru', 'tass.com', 'ria.ru', 'rbc.ru', 'lenta.ru', 'interfax.',
    'gazeta.ru', 'kommersant.ru', 'iz.ru', 'vedomosti.ru', 'forbes.ru',
    'bbc.', 'reuters.', 'cnn.', 'unian.', 'eurointegration.', 'pravda.com',
    'meduza.io', 'currenttime.tv', 'svoboda.org', 'dw.com',
)
_IMAGE_JUNK_TERMS = (
    'backrooms', 'creepypasta', 'liminal space', 'liminalspace',
    'roblox', 'minecraft', 'fortnite', 'gmod', 'garry\'s mod',
    'half-life', 'half life', 'source engine', 'unreal engine',
    'horror game', 'indie game', 'gameplay', 'fan art', 'fanart',
    'wallpaper', 'i can see you', 'found footage game',
    'scp-', 'scp foundation', 'call of duty', 'resident evil',
    'как оформить', 'недостроенный дом', 'недострой',
    'продам', 'продаётся', 'продается', 'объявление', 'м/кв', 'м²',
    ' сот.', ' сот ', 'уч.', 'лот ',
    # News / unrelated hangars often drown «заброшенный ангар».
    'полыхает', 'пожарные', 'тушили', 'загоревш', 'горит ангар',
    'space shuttle', 'шаттл', 'байконур', 'космодром', 'бурран',
    # Active tourism / realty noise for «база отдыха …».
    'купить ', 'купитe ', 'продажа', 'продать', ' в москве', 'га и ',
    ' квт', 'термальн', 'топ 15', 'топ-15', 'топ 10', 'лучших баз',
    'лучшие базы', 'снять номер', 'бронирован', 'цена от', 'путевк',
    # Weapons / air-defense PR — drowns «войсковая часть» image search.
    'воздушно-космическ', 'воздушно космическ', 'систем воздушно',
    'производитель систем', 'алмаз-антей', 'алмаз антей',
    'зрк ', ' зрк', 'с-300', 'с-400', 'с-500', 'с 300', 'с 400',
    'пусковая установ', 'пусковых установ', 'пусковую установ',
    'зенитн', 'ракетн комплекс', 'ракетной комплекс', 'ракетный комплекс',
    'индия формирует', 'единую систему', 'пво на базе', 'триумф»',
    'фапси', 'день фапси', 'фсб день', 'день вкс',
    # Agency / geopolitics noise (ТАСС logo thumbnails, etc.).
    ' агентство тасс', 'агентства тасс', 'тасс виключ', 'тасс исключ',
    'ріа новин', 'риа новости', 'european association',
    'європейськ', 'европейск', 'асоціац', 'ассоциац',
    'информационн агент', 'інформаційн агент',
)
_TOKEN_STOP = frozenset({
    'это', 'или', 'для', 'при', 'под', 'над', 'без', 'как', 'что',
    'the', 'and', 'for', 'with', 'from', 'near',
})
# Too common in urbex titles — matching them keeps unrelated listings.
_GENERIC_PLACE_TOKENS = frozenset({
    'заброшенный', 'заброшенная', 'заброшенное', 'заброшенные', 'заброшенн',
    'заброшка', 'заброшки', 'коттедж', 'коттеджа', 'коттеджи',
    'дом', 'дома', 'здание', 'объект', 'место', 'фото',
    'корпус', 'корпуса', 'корпусов', 'корпусах', 'корпусе', 'корпусом',
    'недостроенный', 'недостроенная', 'недострой',
    'лагерь', 'усадьба', 'территория', 'улица', 'город', 'район',
    'область', 'россия', 'федеральный', 'округ', 'центральный',
    'ангар', 'ангара', 'ангары', 'склад', 'цех', 'завод', 'фабрика',
    'база', 'базы', 'отдых', 'отдыха', 'оздоров', 'санаторий', 'пансионат',
    'турбаза', 'гостиница', 'отель', 'курорт',
    # Building types — «Церковь в Буняково» must not match every church hit.
    'церковь', 'церкви', 'храм', 'храма', 'часовня', 'собор', 'собора',
    'монастырь', 'монастыря', 'замок', 'замка', 'дворец', 'дворца',
    'войсковая', 'войсковой', 'войсковое', 'войсковые',
    'воинская', 'воинской', 'воинское', 'воинские',
    'часть', 'части', 'гарнизон', 'гарнизона', 'полигон', 'полигона',
    # Icon dedications — «Казанской … Матери» is not the city of Kazan,
    # and must not identify a specific church without a settlement cue.
    'казанской', 'казанская', 'казанский', 'казанское', 'казански',
    # Do NOT put смоленская/владимирская here — they are real oblast labels
    # and stripping them makes Urban3P «(Владимирская область)» look foreign.
    'покровской', 'покровская', 'никольской', 'никольская',
    'успенской', 'успенская', 'троицкой', 'троицкая',
    'преображения', 'преображенская', 'преображенской', 'преображенский',
    'спаса', 'господня', 'господнего', 'вознесения', 'рождества',
    'иконы', 'божией', 'божьей', 'матери', 'пресвятой', 'богородицы',
    'православный', 'православная', 'православное',
    'культура', 'архитектура',
    # Poetic geocache titles («Спите спокойно, верные сыны Отечества») must
    # not match every WWII page that only shares the word «Отечества».
    'спите', 'спокойно', 'верные', 'верный', 'сыны', 'сынов',
    'отечества', 'отечество',
    'защитников', 'защитники', 'героев', 'герои', 'героям',
    'памяти', 'память', 'павшим', 'павшие', 'вечная', 'вечной',
})
# Region aliases so «Московская область» also matches «Подмосковье».
_LOCATION_SYNONYMS = {
    'московская': ('московская', 'подмосковье', 'подмосковья', 'подмосковный', 'москва'),
    'москва': ('москва', 'московская', 'подмосковье', 'подмосковья'),
    # «под Тулой» / «Туле» must match a place tagged «Тульская область».
    'тульская': ('тульская', 'тула', 'тулой', 'туле', 'тульской'),
    'тула': ('тула', 'тульская', 'тулой', 'туле', 'тульской'),
}
# Oblast-level cues are too wide for generic titles («заброшенный ангар»).
_COARSE_LOCATION_TOKENS = frozenset({
    'московская', 'подмосковье', 'подмосковья', 'подмосковный', 'москва',
    'ленинградская', 'петербург', 'питер',
    'тульская', 'тула', 'калужская', 'рязанская', 'тверская', 'владимирская',
    'ярославская', 'смоленская', 'орловская', 'брянская', 'липецкая',
})
_STRUCTURE_TYPE_TOKENS = frozenset({
    'ангар', 'ангара', 'ангары', 'склад', 'цех', 'завод', 'фабрика',
    'коттедж', 'коттеджа', 'дом', 'дома', 'здание',
    'корпус', 'корпуса', 'корпусов', 'корпусах', 'корпусе', 'корпусом',
    'база', 'базы', 'отдых', 'отдыха',
    'войсковая', 'войсковой', 'воинская', 'воинской',
    'часть', 'части', 'гарнизон', 'полигон',
})
_MILITARY_PLACE_RE = re.compile(
    r'(?:\bв\s*/\s*ч\b|\bвч\b|войсков\w*\s+част|воинск\w*\s+част)',
    re.IGNORECASE,
)
_UNIT_NUMBER_RE = re.compile(r'\b(\d{4,6})\b')
# Drop hits that clearly name another city/oblast (skipped when it's our region).
_FOREIGN_GEO = (
    # Moscow / MO — truncated titles like «Огонёк (Московск…» lack «область».
    'московск', 'москва', 'подмосков',
    'сочи', 'краснодар', 'адыге', 'соузг', 'алтай', 'байкал',
    # «казань» — not bare «казан» (that false-hits icon dedication «Казанской»).
    'брянск', 'воронеж', 'казань', 'казани', 'казанью', 'вахитовск', 'самар', 'ростов',
    'екатеринбург', 'свердловск', 'свердл', 'сверд',
    'новосибирск', 'калининград', 'владивосток',
    'тюмен', 'ярославл', 'тула', 'рязан', 'твер', 'смоленск', 'псков', 'курск',
    'белгород', 'нижегород', 'новгород', 'novgorod', 'великий новгород',
    'ильине улице', 'на ильине', 'ruwiki.ru',
    'владимир', 'владимирск', 'иванов', 'костром',
    'калуж', 'орлов', 'липецк', 'тамбов', 'пенз', 'ульянов', 'саратов',
    'волгоград', 'астрахан', 'оренбург', 'перм', 'челябинск', 'курган',
    'омск', 'томск', 'кемеров', 'красноярск', 'иркутск', 'бурят',
    'якут', 'хабаровск', 'примор', 'сахалин', 'камчат', 'мурманск', 'архангельск',
    'вологод', 'карел', 'коми', 'ставропол', 'дагестан', 'чечен', 'крым',
    'севастопол', 'башкир', 'татарстан', 'удмурт', 'чуваш', 'марий',
    'мордов', 'удмурти', 'чуваши', 'марий эл',
    'шачино', 'зубова',
    # Cities often omitted when only the republic stem is listed.
    'ижевск', 'уфа', 'чебоксар', 'йошкар', 'сыктывкар', 'набережн',
    'тольятти', 'барнаул', 'магнитогорск', 'нижнекамск',
    # NW / Spb — many camps share names like «Волна» with MO sites.
    'ленинградск', 'ленинград', 'ленобласт', 'петербург', 'петроград',
    'питер', 'спб', 'кронштадт', 'выборг',
    # Far-north / other settlements often in «в/ч …» video titles.
    'африканд', 'хибин', 'кировск', 'апатит', 'североморск', 'полирн',
    'заполярн', 'кольск', 'мончегорск', 'кандалакш', 'печенг',
    # Ukraine / near abroad — same toponyms as MO villages («Воскресенки»).
    'киев', 'київ', 'києв', 'kyiv', 'kiev',
    'украин', 'україн', 'ukraine',
    'харьков', 'харків', 'одесс', 'львов', 'львів', 'днепр', 'дніпр',
    'запорож', 'запоріж', 'донець', 'донецк', 'луган', 'крымск',
    'минск', 'беларус', 'белорусс', 'казахстан', 'алматы', 'ташкент',
)
# Common camp/site names — alone they match dozens of places across Russia.
_COMMON_PLACE_NAMES = frozenset({
    'восток', 'запад', 'север', 'юг', 'атлант', 'заря', 'орленок', 'орлёнок',
    'смена', 'дружба', 'радуга', 'восход', 'сокол', 'олимп', 'спартак',
    'динамо', 'энергия', 'родина', 'победа', 'юность', 'изумрудный', 'изумруд',
    'березки', 'берёзки', 'березка', 'берёзка', 'сосенки', 'дубки', 'елочки',
    'ёлочки', 'рощин', 'лесной', 'лесная', 'речной', 'озерн',
    'волна', 'маяк', 'горизонт', 'рассвет', 'чайка', 'орёл', 'орел',
    'дзержинец', 'дзержинский', 'дзержинская',
    'огонек', 'огонёк',
    'сосновый', 'сосновая', 'сосновое',
    'воскресенки', 'воскресенка', 'воскресенск',
    'пушкино', 'пушкинский', 'пушкинская', 'пушкинское',
    'пионерский', 'пионер', 'детский', 'оздоровительный',
    'база', 'базы', 'отдых', 'отдыха', 'турбаза',
})
# Category words from _COMMON_PLACE_NAMES — not enough to identify a camp.
_NAME_FILLER_TOKENS = frozenset({
    'пионерский', 'пионер', 'детский', 'оздоровительный',
    'база', 'базы', 'отдых', 'отдыха', 'турбаза',
    'лагерь', 'лагеря',
})
_TOKEN_RE = re.compile(r'[0-9a-zа-яё]{3,}', re.IGNORECASE)
# «Ленинградская область» / «Краснодарский край» — explicit other-region labels.
_REGION_LABEL_RE = re.compile(
    r'([а-яё]{4,})\s+(?:област\w*|кра[йя]\w*|республик\w*|округа?\b)',
    re.IGNORECASE,
)
_REGION_LABEL_NOISE = frozenset({
    'российская', 'российский', 'федеральная', 'федеральный', 'автономная',
    'автономный', 'центральный', 'южный', 'северный', 'западный', 'восточный',
    # «городской округ Пушкинский» is a district form, not an oblast name.
    'городской', 'городская', 'муниципальный', 'муниципальная',
    'административный', 'административная',
})
# Museums / memorial expos often steal military image search.
_MILITARY_OFFTOPIC_TERMS = (
    'музей', 'museum', 'экспозиц', 'мемориальн', 'выставк',
    'бжрк', 'боевой железнодорож',
)
# «Лагерь завода Слава» vs «завод Слава» share the brand but are different sites.
_CAMP_STRUCTURE_MARKERS = (
    'лагер', 'пионерлагер', 'детлагер', 'оздоровлагер',
)
_FACTORY_STRUCTURE_MARKERS = (
    'завод', 'фабрика', 'комбинат', 'мануфактур',
)


def _coords(place: dict) -> tuple[float, float] | None:
    try:
        latitude = float(place['latitude'])
        longitude = float(place['longitude'])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-85 <= latitude <= 85 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def _is_urbex_site_url(url: str) -> bool:
    host = _host_of(url)
    if not host:
        return False
    return any(host == domain or host.endswith('.' + domain) for domain in _URBEX_SITE_DOMAINS)


_STREET_PART_RE = re.compile(
    r'\b(?:улица|ул\.|проспект|пр-т|переулок|пер\.|шоссе|проезд|набережная|'
    r'тупик|площадь|бульвар|аллея|дорога)\b',
    re.IGNORECASE,
)
_ADMIN_PART_RE = re.compile(
    r'\b(?:область|край|республик\w*|федеральн\w*|район|округ|россия)\b',
    re.IGNORECASE,
)
_PLACE_TYPE_PART_RE = re.compile(
    r'\b(?:лагер|усадьб|завод|фабрик|школ|храм|церк|дворец|памятник|здание|'
    r'бассейн|территория)\w*\b',
    re.IGNORECASE,
)
_COMPACT_REGION_RE = re.compile(
    r'((?:[А-Яа-яЁёA-Za-z-]{3,}(?:\s+[А-Яа-яЁёA-Za-z-]{3,})?\s+'
    r'(?:область|край))|республика\s+[А-Яа-яЁёA-Za-z-]+|'
    r'г\.?\s*Москва|\bМосква\b)',
    re.IGNORECASE,
)
_SITE_PREFIX_RE = re.compile(
    r'^(?:СНТ|ДНТ|НСТ|ДОЛ|ТОС)\s*[«"\']?\s*',
    re.IGNORECASE,
)


def _compact_region_label(place: dict) -> str:
    """«Московская область» from a long Nominatim-style address dump."""
    for field in ('region', 'full_address'):
        match = _COMPACT_REGION_RE.search(str(place.get(field) or ''))
        if match:
            return match.group(1).strip()
    region = (place.get('region') or '').strip()
    return region if region and len(region) <= 80 else ''


def _settlement_label(place: dict) -> str:
    """Locality from address/content: «Анашкино», «Лесниково», …"""
    for field in ('full_address', 'region'):
        text = str(place.get(field) or '')
        for raw in re.split(r'\s*,\s*', text):
            part = raw.strip().strip(' «»"\'')
            if len(part) < 3:
                continue
            okrug = re.match(r'городской\s+округ\s+(.+)$', part, re.IGNORECASE)
            if okrug:
                name = okrug.group(1).strip(' «»"\'')
                if len(name) >= 3 and not _ADMIN_PART_RE.search(name):
                    return name[:80]
                continue
            if _STREET_PART_RE.search(part) or _ADMIN_PART_RE.search(part):
                continue
            if _PLACE_TYPE_PART_RE.search(part):
                continue
            if re.search(r'\d{3,}', part):
                continue
            cleaned = _SITE_PREFIX_RE.sub('', part).strip(' «»"\'')
            if len(cleaned) < 3 or cleaned.isdigit():
                continue
            return cleaned[:80]
    return ''


def _search_location(place: dict) -> str:
    """Settlement + compact region for SearXNG (avoids bare oblast-only queries)."""
    settlement = _settlement_label(place)
    region = _compact_region_label(place)
    parts: list[str] = []
    if settlement:
        parts.append(settlement)
    if region:
        region_key = region.casefold()
        settlement_key = settlement.casefold()
        if region_key != settlement_key and settlement_key not in region_key:
            parts.append(region)
    if parts:
        return ' '.join(parts)[:120]
    return _short_location(place)


def _search_name(place: dict) -> str:
    from html import unescape
    from .osint_identity import kinds, name_cues, words_present
    name = str(place.get('name') or '').strip()
    description = unescape(re.sub(r'<[^>]+>', ' ', str(place.get('description') or '')))
    opening = re.split(r'[.!?\n]', description, maxsplit=1)[0].strip()
    if (name and not kinds(name) and kinds(opening) and len(opening) <= 160
            and words_present(name_cues(name), opening)):
        return opening
    return name


def _urbex_site_query(place: dict) -> str:
    """Restrict SearXNG to known RU urbex catalogs."""
    name = _search_name(place)
    location = _search_location(place)
    subject = ' '.join(part for part in (name, location) if part).strip()
    if not subject:
        return ''
    # Do not cut the domain expression in half (or lose its final sources).
    return f'{subject[:160]} {_URBEX_SITE_QUERY}'


def _queries_for(place: dict) -> list[str]:
    """Build SearXNG queries: urbex sites, then name+settlement/region, then coords."""
    name = _search_name(place)
    location = _search_location(place)
    settlement = _settlement_label(place)
    coords = _coords(place)

    queries: list[str] = []
    # Bias toward Urban3P / Swalker / Caves / Планета дорог / UrbexStalker.
    site_query = _urbex_site_query(place)
    if site_query:
        queries.append(site_query)
    # Settlement/region before bare name — «Атлант» alone pulls Sochi camps.
    if name and location and location.casefold() != name.casefold():
        queries.append(f'{name} {location}'[:200])
    elif name and settlement:
        queries.append(f'{name} {settlement}'[:200])
    elif name:
        queries.append(name[:200])
    if coords:
        latitude, longitude = coords
        point = f'{latitude:.5f}, {longitude:.5f}'
        queries.append((f'{name} {point}' if name else point)[:200])
    if location and not name:
        queries.append(location[:200])

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


def _short_location(place: dict) -> str:
    region = _compact_region_label(place)
    if region:
        return region
    address = (place.get('full_address') or '').strip()
    if address and len(address) <= 80:
        return address
    return ''


def _is_military_place_name(name: str) -> bool:
    return bool(_MILITARY_PLACE_RE.search(name or ''))


def _unit_numbers(text: str) -> set[str]:
    return set(_UNIT_NUMBER_RE.findall(text or ''))


def _image_queries_for(place: dict) -> list[str]:
    """Image queries: prefer settlement/region+coords; avoid bare generic names."""
    name = _search_name(place)
    location = _search_location(place)
    coords = _coords(place)
    distinctive = _distinctive_tokens(name)
    # Steer engines away from memes, games and classifieds.
    negative = (
        ' -tass -риа -новости -агентство -музей'
        ' -backrooms -roblox -minecraft -wallpaper -pinterest'
        ' -avito -cian -продам -недострой'
    )
    if _is_military_place_name(name):
        # Keep short military negatives first — query strings are capped at 200 chars.
        negative = (
            ' -с-400 -с-300 -с-500 -пво -алмаз-антей -триумф -бжрк -музей'
            + negative
        )
    queries: list[str] = []
    # Push image engines toward RU urbex catalogs first.
    if name and location and (distinctive or coords):
        queries.append(
            f'{name} {location} {_URBEX_SITE_TEXT} фото{negative}'[:200]
        )
        queries.append(f'{name} {location} фото{negative}'[:200])
    elif name and distinctive:
        queries.append(f'{name} {_URBEX_SITE_TEXT} фото{negative}'[:200])
        queries.append(f'{name} фото{negative}'[:200])
    if coords:
        latitude, longitude = coords
        point = f'{latitude:.5f}, {longitude:.5f}'
        if name:
            queries.append(f'{name} {point}{negative}'[:200])
        elif location:
            queries.append(f'{location} {point} фото{negative}'[:200])
        else:
            queries.append(f'{point}{negative}'[:200])
    # Last resort for distinctive names without coords/region.
    if not queries and name and distinctive:
        queries.append(f'{name} {_URBEX_SITE_TEXT} фото{negative}'[:200])
        queries.append(f'{name} фото{negative}'[:200])
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


def _significant_tokens(text: str) -> set[str]:
    tokens = set()
    for match in _TOKEN_RE.finditer(text or ''):
        token = match.group(0).casefold()
        if token in _TOKEN_STOP or token.isdigit():
            continue
        tokens.add(token)
    return tokens


def _distinctive_tokens(text: str) -> set[str]:
    return {
        token for token in _significant_tokens(text)
        if token not in _GENERIC_PLACE_TOKENS and len(token) >= 4
    }


def _location_tokens(place: dict) -> set[str]:
    region = (place.get('region') or '').strip()
    address = (place.get('full_address') or '').strip()
    blob = f'{region} {address}'
    tokens = _distinctive_tokens(blob)
    # Keep short region labels («Москва») even if they look generic.
    # Do not re-import church dedications / building types from the address
    # line («Церковь Преображения Господня, …, Тверская область»).
    for token in _significant_tokens(region):
        if token in {'россия', 'область', 'район', 'округ', 'край', 'город'}:
            continue
        if (
            token in _GENERIC_PLACE_TOKENS
            or token in _STRUCTURE_TYPE_TOKENS
            or token in _NAME_FILLER_TOKENS
        ):
            continue
        if len(token) >= 4 or token in {'москва', 'сочи'}:
            tokens.add(token)
    for token in _significant_tokens(address):
        if (
            token in _GENERIC_PLACE_TOKENS
            or token in _STRUCTURE_TYPE_TOKENS
            or token in _NAME_FILLER_TOKENS
        ):
            continue
        if token in {'россия', 'область', 'район', 'округ', 'край', 'город', 'улица'}:
            continue
        if len(token) >= 4 or token in {'москва', 'сочи'}:
            tokens.add(token)
    expanded = set(tokens)
    for token in tokens:
        for alias in _LOCATION_SYNONYMS.get(token, ()):
            expanded.add(alias)
    return expanded


def _item_text_blob(item: dict, keys: tuple[str, ...]) -> str:
    return ' '.join(str(item.get(key) or '') for key in keys).casefold()


def _region_stem(token: str) -> str:
    text = (token or '').casefold()
    for suffix in (
        'ская', 'ской', 'ские', 'ский', 'ского', 'скому', 'ским', 'ском',
        'ная', 'ной', 'ный', 'ного', 'ному', 'ным', 'ном',
    ):
        if text.endswith(suffix) and len(text) - len(suffix) >= 4:
            return text[:-len(suffix)]
    return text


def _location_covers(word: str, location_tokens: set[str]) -> bool:
    """True when word (e.g. ленинградская) belongs to the place's region."""
    stem = _region_stem(word)
    if not stem:
        return False
    for token in location_tokens:
        token_stem = _region_stem(token)
        if (
            stem == token_stem
            or stem in token
            or token in stem
            or stem in token_stem
            or token_stem in stem
        ):
            return True
        for alias in _LOCATION_SYNONYMS.get(token, ()):
            alias_stem = _region_stem(alias)
            if stem == alias_stem or stem in alias or alias in stem:
                return True
    return False


def _location_owns_geo_hint(hint: str, location_tokens: set[str]) -> bool:
    """True when the hint names our region/city — not a longer lookalike.

    «казан» must not be covered by icon dedication «казанской»;
    «московск» may be covered by «московская».
    """
    hint = (hint or '').casefold()
    if not hint:
        return False
    for token in location_tokens:
        if hint == token or token == hint:
            return True
        # Dedication / generic place words in the address are not geo ownership.
        if token in _GENERIC_PLACE_TOKENS:
            continue
        if hint in token or token in hint:
            shorter, longer = (hint, token) if len(hint) <= len(token) else (token, hint)
            # Allow short inflection/suffix growth (московск→московская), not
            # city stem inside an unrelated longer adjective (казан→казанской).
            if longer.startswith(shorter) and len(longer) - len(shorter) <= 4:
                return True
            if shorter in longer and len(longer) - len(shorter) <= 2:
                return True
        for alias in _LOCATION_SYNONYMS.get(token, ()):
            if hint == alias or alias.startswith(hint) or hint.startswith(alias):
                if abs(len(alias) - len(hint)) <= 4:
                    return True
    return False


def _has_foreign_geo(blob: str, location_tokens: set[str]) -> bool:
    for hint in _FOREIGN_GEO:
        # City stems must start a word: Новокузьминская is not Минск.
        if not re.search(r'(?<!\w)' + re.escape(hint), blob):
            continue
        # Hint is part of our own location (e.g. place in Sochi).
        if _location_owns_geo_hint(hint, location_tokens):
            continue
        return True
    # Titles often spell the wrong oblast explicitly even when the stem
    # is missing from _FOREIGN_GEO («Ленинградская область», «Томская…»).
    for match in _REGION_LABEL_RE.finditer(blob):
        region_word = match.group(1).casefold()
        if region_word in _REGION_LABEL_NOISE:
            continue
        if _location_covers(region_word, location_tokens):
            continue
        return True
    return False


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or '').casefold()
    except ValueError:
        return ''


def _is_junk_photo(item: dict) -> bool:
    if _is_generic_shelter_article(item):
        return True
    # MediaWiki interface graphics are not photographs of the object.
    for key in ('image_url', 'thumbnail_url'):
        path = unquote(urlparse(str(item.get(key) or '')).path).casefold()
        if re.search(r'(?:^|/|\d+px-)(?:commons-logo|wikipedia-logo|disambig|ambox|question_book|question_book-new|dialog-warning|edit-clear)(?:[_.-]|$)', path):
            return True
    blob = ' '.join(
        str(item.get(key) or '')
        for key in ('title', 'source_url', 'image_url', 'thumbnail_url')
    ).casefold()
    if any(term in blob for term in _IMAGE_JUNK_TERMS):
        return True
    for url in (item.get('source_url'), item.get('image_url'), item.get('thumbnail_url')):
        host = _host_of(str(url or ''))
        if host and any(junk in host or host.endswith(junk.rstrip('.')) for junk in _IMAGE_JUNK_HOSTS):
            return True
    return False


def _blob_has_any(blob: str, tokens: set[str]) -> bool:
    if not tokens:
        return False
    ranked = sorted(tokens, key=len, reverse=True)[:8]
    for token in ranked:
        if token in blob:
            return True
        # Light morphology: Мытищи ↔ Мытищ / Истринский ↔ Истра.
        if len(token) >= 5 and token[:-1] in blob:
            return True
        if len(token) >= 6 and token[: max(4, len(token) - 2)] in blob:
            return True
    return False


def _unique_name_tokens(name: str) -> set[str]:
    """Tokens that can identify a place without a region (АЗЛК / Жохово)."""
    tokens = {
        token for token in _distinctive_tokens(name)
        if token not in _COMMON_PLACE_NAMES
        and token not in _STRUCTURE_TYPE_TOKENS
        and token not in _NAME_FILLER_TOKENS
    }
    acronyms = {
        match.group(0).casefold() for match in _TOKEN_RE.finditer(name)
        if match.group(0).isupper() and 3 <= len(match.group(0)) <= 6
        and match.group(0).casefold() not in (
            _GENERIC_PLACE_TOKENS | _STRUCTURE_TYPE_TOKENS | _NAME_FILLER_TOKENS | _TOKEN_STOP
        )
    }
    if acronyms:
        return acronyms
    if len(tokens) <= 1:
        return tokens
    # Prefer the longest token(s): toponym «жохово» over leftover noise.
    ranked = sorted(tokens, key=len, reverse=True)
    longest = len(ranked[0])
    strong = {token for token in ranked if len(token) >= max(5, longest - 1)}
    return strong or {ranked[0]}


def _oblast_tokens_from_place(place: dict) -> set[str]:
    """Tokens that only mean the oblast/krai label itself."""
    blob = f"{place.get('region') or ''} {place.get('full_address') or ''}".casefold()
    found: set[str] = set()
    for match in _REGION_LABEL_RE.finditer(blob):
        word = match.group(1).casefold()
        found.add(word)
        found.add(_region_stem(word))
    return found


def _fine_location_tokens(place: dict) -> set[str]:
    """Settlement/district cues — not just «Московская / Тульская область»."""
    oblast = _oblast_tokens_from_place(place)
    return {
        token for token in _location_tokens(place)
        if token not in _COARSE_LOCATION_TOKENS
        and token not in oblast
        and _region_stem(token) not in oblast
    }


_RELIGIOUS_NAME_MARKERS = frozenset({
    'церковь', 'церкви', 'храм', 'храма', 'часовня', 'собор', 'собора',
    'монастырь', 'монастыря',
    'казанской', 'казанская', 'преображения', 'преображенская',
    'покровской', 'покровская', 'никольской', 'никольская',
    'успенской', 'успенская', 'успения', 'троицкой', 'троицкая',
    'смоленской', 'смоленская', 'владимирской', 'владимирская',
    'спаса', 'господня', 'иконы', 'божией', 'божьей', 'богородицы',
    'вознесения', 'рождества', 'покрова', 'николая', 'димитрия',
})
# «в Соснице» / «в Буняково» — another village in the same oblast.
_SETTLEMENT_IN_TITLE_RE = re.compile(
    r'(?:^|[^\w])в\s+([а-яё]{4,})(?:\s|,|\)|/|$)',
    re.IGNORECASE,
)
_SETTLEMENT_PREPOSITION_NOISE = frozenset({
    'области', 'районе', 'округе', 'городе', 'селе', 'деревне', 'поселке',
    'посёлке', 'центре', 'россии', 'честь', 'имя', 'годы', 'году',
    'руинах', 'аварийном', 'состоянии',
})


def _is_religious_dedication_name(name: str) -> bool:
    """True for «Церковь Спаса Преображения» / «Казанской иконы…»."""
    return bool(_significant_tokens(name) & _RELIGIOUS_NAME_MARKERS)


def _has_other_settlement(blob: str, fine_location: set[str]) -> bool:
    """True when the hit names another village («в Соснице») not on our card."""
    if not fine_location:
        return False
    for match in _SETTLEMENT_IN_TITLE_RE.finditer(blob):
        word = match.group(1).casefold()
        if word in _SETTLEMENT_PREPOSITION_NOISE or word in _GENERIC_PLACE_TOKENS:
            continue
        if _blob_has_any(word, fine_location):
            continue
        # Morphology: «Соснице» vs settlement token «сосница» if we had it —
        # here we only accept overlap with OUR fine tokens.
        if any(
            word.startswith(token[: max(4, len(token) - 2)])
            or token.startswith(word[: max(4, len(word) - 2)])
            for token in fine_location
            if len(token) >= 4 and len(word) >= 4
        ):
            continue
        return True
    return False


def _is_structure_only_name(name: str) -> bool:
    """True for «Заброшенный ангар» / «коттедж», false for «лагерь Атлант»."""
    tokens = _significant_tokens(name) - _TOKEN_STOP
    tokens = {
        token for token in tokens
        if not token.startswith('заброшен') and token not in {
            'недостроенный', 'недостроенная', 'недострой', 'бывший', 'бывшая',
        }
    }
    if not tokens:
        return True
    named = tokens - _STRUCTURE_TYPE_TOKENS - _GENERIC_PLACE_TOKENS
    # «Войсковая часть» without a unique toponym is structure-only,
    # even when a unit number is present (numbers handled separately).
    if _is_military_place_name(name) and not named:
        return True
    return not named


def _has_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    blob = (text or '').casefold()
    return any(marker in blob for marker in markers)


def _structure_type_clash(place_name: str, blob: str) -> bool:
    """True when the hit is clearly another site type (camp ↔ factory)."""
    place_camp = _has_any_marker(place_name, _CAMP_STRUCTURE_MARKERS)
    place_factory = _has_any_marker(place_name, _FACTORY_STRUCTURE_MARKERS)
    item_camp = _has_any_marker(blob, _CAMP_STRUCTURE_MARKERS)
    item_factory = _has_any_marker(blob, _FACTORY_STRUCTURE_MARKERS)
    # Place is a camp (name may still mention an owner factory).
    if place_camp and item_factory and not item_camp:
        return True
    # Place is a factory / plant, not a camp.
    if place_factory and not place_camp and item_camp and not item_factory:
        return True
    return False


def _matches_military_place(
    item: dict,
    place: dict,
    *,
    location_tokens: set[str],
    fine_location: set[str],
) -> bool:
    """Military units: unit number + region, else a fine settlement cue."""
    name = str(place.get('name') or '')
    # Ignore image CDN paths — random digits there collide with unit numbers.
    text_blob = _item_text_blob(item, ('title', 'snippet', 'source_url', 'url'))
    if any(term in text_blob for term in _MILITARY_OFFTOPIC_TERMS):
        return False
    if location_tokens and _has_foreign_geo(text_blob, location_tokens):
        return False
    unit_nums = _unit_numbers(name)
    if unit_nums:
        if not any(num in text_blob for num in unit_nums):
            return False
        # «в/ч 12345» without Тула/Москва in the caption is usually another unit.
        if location_tokens and not _blob_has_any(text_blob, location_tokens):
            return False
        return True
    # Bare «войсковая часть» + only oblast → weapons-news flood; need town/district.
    if fine_location:
        return _blob_has_any(text_blob, fine_location)
    return False


def _matches_place(
    item: dict,
    place: dict,
    keys: tuple[str, ...],
) -> bool:
    """Keep hits for this place; with a known region, drop other cities."""
    blob = _item_text_blob(item, keys)
    name = str(place.get('name') or '')
    name_tokens = _distinctive_tokens(name)
    unique_tokens = _unique_name_tokens(name)
    location_tokens = _location_tokens(place)
    fine_location = _fine_location_tokens(place)

    # Manor cards often contain only a toponym in their name. Use the card's
    # description/category to distinguish them from namesake housing estates.
    manor = r'\bусад(?:ьб|еб)[а-яё]*\b'
    context = _item_text_blob(place, ('name', 'description', 'category', 'category_name'))
    if re.search(manor, context):
        housing = (
            r'\bтаунхаус[а-яё]*\b|\bкоттеджн[а-яё]*\s+пос[её]л[а-яё]*\b'
            r'|\bжил[а-яё]*\s+(?:комплекс|квартал)[а-яё]*\b|\bжк\b'
        )
        title = str(item.get('title') or '').casefold()
        evidence = _item_text_blob(item, ('title', 'snippet'))
        # A housing title is off topic even if its snippet mentions a nearby
        # manor. Conversely, a historical article may mention nearby housing.
        if re.search(housing, title):
            return False
        if re.search(housing, evidence) and not re.search(manor, title):
            return False

    if re.search(r'\b(?:бомбоубежищ|убежищ|бункер)[а-яё]*\b', name.casefold()):
        if not _matches_shelter_identity(item, place):
            return False

    # A company's headquarters is not its remote testing facility.
    if re.search(r'\bполигон[а-яё]*\b', name.casefold()):
        evidence = _item_text_blob(item, ('title', 'snippet', 'source_url', 'url'))
        if not re.search(r'\bполигон[а-яё]*\b', evidence):
            return False

    # The number is part of an institution's identity, not a disposable token.
    # Require the same acronym + full number in human-readable evidence;
    # unrelated dates, URL IDs and image filenames cannot establish a match.
    numbered_codes = re.findall(
        r'(?<!\w)([A-ZА-ЯЁ]{2,10})\s*(?:[-–—]\s*№?\s*|№\s*|\s+)(\d+)(?!\w)', name,
    )
    evidence = ' '.join(str(item.get(key) or '') for key in ('title', 'snippet'))
    for code, number in numbered_codes:
        pattern = rf'(?<!\w){re.escape(code)}\s*(?:[-–—]\s*№?\s*|№\s*|\s+){re.escape(number)}(?!\w)'
        if not re.search(pattern, evidence, re.IGNORECASE):
            return False

    # Preserve compound object types: "летний" alone also matches ages
    # such as "21-летний" in biographies, which are not kindergarten hits.
    kindergarten = r'\bдетск[а-яё]*\s+сад[а-яё]*\b'
    if re.search(kindergarten, name.casefold()) and not re.search(kindergarten, blob):
        return False

    # Geocache names are often poetic: one shared adjective ("Забытая" /
    # "Забытое") cannot identify the object, even within the same oblast.
    description_links = links_from_description(str(place.get('description') or ''))
    if any(link.get('category') == 'geocache' for link in description_links):
        name_cues = name_tokens - _NAME_FILLER_TOKENS - _STRUCTURE_TYPE_TOKENS
        if len(name_cues) >= 2 and sum(
            _blob_has_any(blob, {token}) for token in name_cues
        ) < 2:
            return False

    if _structure_type_clash(name, blob):
        return False

    if _is_military_place_name(name):
        return _matches_military_place(
            item, place, location_tokens=location_tokens, fine_location=fine_location,
        )

    if location_tokens:
        if _has_foreign_geo(blob, location_tokens):
            return False
        # «Заброшенный ангар» + only oblast → too many unrelated MO hangars.
        # Dedication-only church names («Спаса Преображения») may keep
        # same-oblast catalog hits; foreign regions are already rejected above.
        if _is_structure_only_name(name):
            if fine_location and _has_other_settlement(blob, fine_location):
                return False
            if fine_location and _blob_has_any(blob, fine_location):
                return True
            if _is_religious_dedication_name(name):
                if fine_location and _has_other_settlement(blob, fine_location):
                    return False
                # Oblast-only hits must still look like the same church family,
                # not a random manor («особняк») or another dedication.
                blob_tokens = _significant_tokens(blob)
                if not (blob_tokens & _RELIGIOUS_NAME_MARKERS):
                    return False
                place_dedication = (
                    _significant_tokens(name) & _RELIGIOUS_NAME_MARKERS
                ) - {
                    'церковь', 'церкви', 'храм', 'храма', 'часовня',
                    'собор', 'собора', 'монастырь', 'монастыря',
                }
                if place_dedication and not _blob_has_any(blob, place_dedication):
                    return False
                oblast_tokens = set(_oblast_tokens_from_place(place))
                for token in location_tokens:
                    if token in _COARSE_LOCATION_TOKENS:
                        oblast_tokens.add(token)
                    for alias in _LOCATION_SYNONYMS.get(token, ()):
                        oblast_tokens.add(alias)
                if oblast_tokens and _blob_has_any(blob, oblast_tokens):
                    return True
            return False
        # Prefer rare codes (АЗЛК); otherwise keep toponym cues («Сосновый»),
        # not category fillers like «пионерский лагерь».
        place_cues = unique_tokens or {
            token for token in name_tokens
            if token not in _GENERIC_PLACE_TOKENS
            and token not in _STRUCTURE_TYPE_TOKENS
            and token not in _NAME_FILLER_TOKENS
        }
        if not place_cues:
            return _blob_has_any(blob, location_tokens)
        # Region alone is not enough — that lets ТАСС/news through.
        if not _blob_has_any(blob, place_cues):
            return False
        # Shared toponyms also need a region/district cue when we know one.
        if not unique_tokens or (place_cues & _COMMON_PLACE_NAMES):
            settlement = _settlement_label(place)
            settlement_tokens = {
                token for token in _significant_tokens(settlement)
                if len(token) >= 4
            }
            # Prefer the locality from the card («Анашкино») over bare oblast.
            if settlement_tokens and _blob_has_any(blob, settlement_tokens):
                return True
            if settlement_tokens and not _blob_has_any(blob, location_tokens):
                return False
            return _blob_has_any(blob, location_tokens)
        return True

    if unique_tokens or name_tokens:
        return _blob_has_any(blob, unique_tokens or name_tokens)
    return False


def _matches_shelter_identity(item: dict, place: dict) -> bool:
    """A shelter category and a shared city cannot identify an individual site."""
    urls = {str(item.get(key) or '').rstrip('/') for key in ('url', 'source_url')}
    for link in links_from_description(str(place.get('description') or '')):
        if link['url'].rstrip('/') in urls:
            return True
        # Wikimapia URLs may differ in language and title but share the object ID.
        reference = re.match(r'https?://(?:www\.)?wikimapia\.org/(\d+)(?:/|$)', link['url'])
        if reference and any(re.match(
            rf'https?://(?:www\.)?wikimapia\.org/{reference[1]}(?:/|$)', url,
        ) for url in urls):
            return True

    evidence = _item_text_blob(item, ('title', 'snippet')).replace('ё', 'е')
    address = str(place.get('full_address') or place.get('region') or '')
    # Require the street name, not the city, district, CDN path or search query.
    street = re.search(
        r'(?:^|,)\s*(?:улица|ул\.)\s+([^,]+)|(?:^|,)\s*([^,]+?)\s+улица\b',
        address, re.IGNORECASE,
    )
    if street:
        tokens = _significant_tokens(street[1] or street[2])
        if tokens:
            return all(_blob_has_any(evidence, {token.replace('ё', 'е')}) for token in tokens)

    name = re.sub(r'\((?:ru|en)\)', '', str(place.get('name') or ''), flags=re.IGNORECASE)
    generic = {'убежище', 'убежища', 'бомбоубежище', 'бомбоубежища', 'бункер',
               'гражданской', 'обороны', 'го', 'подземное', 'стандартное'}
    name = re.sub(r'\b(?:' + '|'.join(map(re.escape, generic)) + r')\b', '', name,
                  flags=re.IGNORECASE)
    cues = _unique_name_tokens(name)
    return bool(cues) and all(_blob_has_any(evidence, {cue}) for cue in cues)


def _filter_photos(photos: list[dict], place: dict) -> list[dict]:
    description_urls = {
        item['url'].rstrip('/')
        for item in links_from_description(str(place.get('description') or ''))
    }
    return [
        photo for photo in photos
        if not _is_junk_photo(photo)
        and (
            ((photo.get('engine') in {'geocache', 'wikimapia'} or
              (photo.get('engine') == 'vk' and photo.get('scope') == 'album'))
             and str(photo.get('source_url') or '').rstrip('/') in description_urls)
            or _matches_place(photo, place, ('title', 'source_url', 'image_url'))
        )
    ]


def _is_generic_shelter_article(item: dict) -> bool:
    """Reject category definitions, including every image sourced from them."""
    generic_titles = {
        'убежище', 'убежище гражданской обороны', 'бомбоубежище',
        'противорадиационное укрытие', 'бункер', 'гражданская оборона',
        'bomb shelter', 'air raid shelter', 'fallout shelter',
    }
    title = str(item.get('title') or '').casefold().strip()
    title = re.sub(r'\s*[—–|\-]\s*(?:википедия|wikipedia)\s*$', '', title).strip()
    # Search titles often append the publisher's domain, e.g. "... - fire.info".
    # Strip only a domain/publisher matching the URL, not an object address.
    parts = re.split(r'\s+[—–|\-]\s+', title)
    if len(parts) > 1:
        publisher = parts[-1].strip().removeprefix('www.')
        hosts = {
            _host_of(str(item.get(key) or '')).removeprefix('www.')
            for key in ('source_url', 'url')
        } - {''}
        if publisher in hosts or re.fullmatch(r'(?:[\w-]+\.)+[a-zа-я]{2,}', publisher):
            title = ' - '.join(parts[:-1]).strip()
    if title in generic_titles:
        return True
    for key in ('source_url', 'url'):
        url = str(item.get(key) or '')
        host = _host_of(url)
        if host == 'wikipedia.org' or host.endswith('.wikipedia.org'):
            page = unquote(urlparse(url).path).removeprefix('/wiki/').replace('_', ' ').casefold()
            if page in generic_titles:
                return True
    return False


def _is_junk_source(item: dict) -> bool:
    """Drop catalog listing pages that are not about one place."""
    if _is_generic_shelter_article(item):
        return True
    blob = ' '.join(
        str(item.get(key) or '')
        for key in ('title', 'snippet', 'url')
    ).casefold()
    if '/category/' in blob or '/categories/' in blob:
        return True
    if 'заброшенные усадьбы, церкви, замки' in blob:
        return True
    # Broad memorial / landmark indexes («список, карта, фото»).
    if 'список, карта, фото' in blob or 'список карта фото' in blob:
        return True
    if 'полный список рунета' in blob or 'заброшенные объекты в' in blob:
        return True
    return False


def _filter_sources(items: list[dict], place: dict) -> list[dict]:
    kept: list[dict] = []
    description_urls = {link['url'] for link in links_from_description(str(place.get('description') or ''))}
    for item in items:
        if is_direct_image_url(str(item.get('url') or '')):
            continue
        if is_vk_group_url(str(item.get('url') or '')):
            if source_key(item.get('url')) in {source_key(url) for url in description_urls}:
                kept.append(item)
            continue
        if item.get('engine') == 'vk' and item.get('url') in description_urls:
            kept.append(item)
            continue
        # Links taken from the place description are trusted as-is.
        if str(item.get('engine') or '') == 'description':
            kept.append(item)
            continue
        if _is_junk_source(item):
            continue
        if _matches_place(item, place, ('title', 'snippet', 'url')):
            kept.append(item)
    return kept


def _http_url(value: object) -> str | None:
    text = str(value or '').strip()
    if text.startswith(('http://', 'https://')):
        return text[:2000]
    return None


def _engines_for(category: str) -> str:
    # Keep aligned with searxng/settings.yml; use regular Google, not CSE.
    if category == 'images':
        return 'bing images,google images,yandex images'
    return 'bing,wikipedia,google,yandex'


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
            raise DomainError('Не удалось получить данные из открытых источников. Повторите попытку позже.', 502)
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


def _merge_round_robin(
    results: list[tuple[dict, ...] | list[dict]],
    key_name: str,
    limit: int,
) -> list[dict]:
    """Interleave batches so Urban3P galleries and web image hits both survive."""
    queues = [list(batch) for batch in results if batch]
    merged: list[dict] = []
    seen: set[str] = set()
    index = 0
    while len(merged) < limit and any(queues):
        queue = queues[index % len(queues)]
        index += 1
        if not queue:
            continue
        item = queue.pop(0)
        key = str(item.get(key_name) or '').rstrip('/').casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(dict(item))
    return merged


def _build_osint_report(
    url: str,
    origin: str,
    place: dict,
    *,
    vk_token: str = '',
    semantic_url: str = '',
) -> dict:
    description_links = links_from_description(str(place.get('description') or ''))
    curated_photos = description_photos_for_links(
        description_links, vk_token=vk_token, limit=_MAX_PHOTOS, place=place,
    )
    vk_sources = vk_sources_for_links(vk_token, description_links, limit=_MAX_RESULTS)
    description_links = [link for link in description_links
                         if not is_direct_image_url(link['url'])]

    if not url:
        if description_links or curated_photos or vk_sources:
            merged = _merge(
                [tuple(vk_sources), tuple(description_links)],
                'url',
                _MAX_RESULTS,
            )
            photos = curated_photos[:_MAX_PHOTOS]
            return {
                'place_id': place['id'],
                'place_name': place.get('name'),
                'queries': [],
                'image_queries': [],
                'source': 'description',
                'total': len(merged),
                'items': merged,
                'photos': photos,
                'photos_total': len(photos),
                'assessment': assess_osint_items(merged),
            }
        raise DomainError('Сервис поиска по открытым источникам не настроен', 503)
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

    references = [link['url'] for link in description_links]
    photo_candidates = _merge(image_batches, 'image_url', _MAX_PHOTOS)
    candidate_pool = _merge_round_robin(
        [_merge(general_batches, 'url', _MAX_RESULTS), _sources_from_photos(photo_candidates)],
        'url', _MAX_RESULTS * 2,
    )
    candidate_pool = rank_candidates(semantic_url, place, candidate_pool)
    source_candidates = enrich_candidates(place, candidate_pool, references)
    # Only verified pages can seed gallery extraction or secondary VK fetching.
    searched = [item for item in source_candidates
                if not _is_junk_source(item)
                and verify_source(place, item, references).status == 'accepted']
    # Wikipedia lead photos are used only after their article passes identity
    # checks and Commons reports an open license with attribution.
    searched_photos = wikipedia_photos_for_sources(searched, _MAX_PHOTOS)
    # Description / VK wall are curated — prepend and skip geo filter.
    # Also enrich VK links found by SearXNG (same soft-fail helpers).
    vk_from_search = vk_sources_for_links(
        vk_token,
        [row for row in searched if str(row.get('url') or '')],
        limit=_MAX_RESULTS,
    )
    merged = _merge(
        [tuple(vk_sources), tuple(vk_from_search), tuple(description_links), tuple(searched)],
        'url',
        _MAX_RESULTS,
    )
    # Always scrape Urban3P/Swalker/… galleries — Yandex/Maps curated hits
    # must not consume the whole photo budget before catalog pages run.
    _SITE_GALLERY_RESERVE = 6
    catalog_budget = max(_SITE_GALLERY_RESERVE, min(_MAX_PHOTOS, (_MAX_PHOTOS * 2) // 3))
    # Seed Urban3P object URLs from image CDN hits when general search omitted them.
    scrape_links = list(merged)
    seen_scrape = {
        str(item.get('url') or '').rstrip('/').casefold()
        for item in scrape_links
    }
    for photo in searched_photos:
        for raw in (photo.get('source_url'), photo.get('image_url')):
            text = str(raw or '')
            if 'urban3p' not in text.casefold():
                continue
            key = text.rstrip('/').casefold()
            if key in seen_scrape:
                continue
            seen_scrape.add(key)
            scrape_links.append({
                'url': text,
                'title': str(photo.get('title') or ''),
            })
    # Pull Urban3P object galleries with their own reserve — site_photos
    # round-robin otherwise shares the budget with YouTube/Rutube thumbs.
    urban_budget = min(8, _MAX_PHOTOS)
    urban_from_search = urban3p_photos_for_links(scrape_links, urban_budget)
    other_budget = max(0, catalog_budget - min(len(urban_from_search), _SITE_GALLERY_RESERVE))
    site_from_search = site_photos_for_links(
        scrape_links, limit=other_budget, vk_token=vk_token,
    ) if other_budget else []
    # Interleave Urban3P with Maps/web so one family cannot fill all slots.
    photos = _merge_round_robin(
        [
            tuple(urban_from_search),
            tuple(site_from_search),
            tuple(curated_photos),
            tuple(searched_photos),
        ],
        'image_url',
        _MAX_PHOTOS,
    )
    if not merged and photos:
        # Photos already filtered; still re-check promoted landing pages.
        merged = _sources_from_photos(photos)
    if not merged and not photos:
        # Distinguishes "SearXNG down" from "nothing relevant found".
        probe = _search_soft(url, origin, queries[0], 'general')
        if not probe and not description_links and not photo_candidates and not source_candidates:
            raise DomainError('Не удалось получить данные из открытых источников. Повторите попытку позже.', 502)
        if probe:
            general_batches = [probe]
            source_candidates = _merge([tuple(source_candidates), probe], 'url', _MAX_RESULTS)
            merged = _merge(general_batches, 'url', _MAX_RESULTS)
            merged = _merge([tuple(description_links), tuple(merged)], 'url', _MAX_RESULTS)
        else:
            merged = description_links[:_MAX_RESULTS]

    # Curated first, then known urbex catalogs, then the rest of the web.
    def _source_rank(item: dict, *, url_key: str) -> int:
        engine = str(item.get('engine') or '')
        if engine in (
            'description', 'vk', 'dzen', 'yandex_maps', 'urban3p', 'swalker',
            'youtube', 'rutube', 'planetadorog', 'caves', 'urbexstalker', 'web_page',
            'description_page', 'wikimapia',
        ):
            return 0
        url = str(item.get(url_key) or item.get('source_url') or item.get('url') or '')
        if _is_urbex_site_url(url) or engine in _URBEX_SITE_DOMAINS:
            return 1
        return 2

    merged.sort(key=lambda item: (
        _source_rank(item, url_key='url'),
        -(item.get('reranker_score') or 0),
        -(item.get('embedding_score') or 0),
        -(item['score'] or 0),
        item['title'],
    ))
    photos.sort(key=lambda item: (
        _source_rank(item, url_key='source_url'),
        -(item['score'] or 0),
        item['title'],
    ))
    return {
        'place_id': place['id'],
        'place_name': place.get('name'),
        'queries': queries,
        'image_queries': image_queries,
        'source': 'searxng',
        'source_candidates': source_candidates,
        'photo_candidates': photo_candidates,
        'total': len(merged),
        'items': merged,
        'photos': photos,
        'photos_total': len(photos),
        'assessment': assess_osint_items(merged),
    }


def _verify_report(payload: dict, place: dict) -> dict:
    references = [link['url'] for link in links_from_description(str(place.get('description') or ''))]
    report = verify_report(payload, place, references,
                           junk_source=_is_junk_source, junk_photo=_is_junk_photo)
    report['assessment'] = assess_osint_items(report['items'])
    return report


def build_osint_report(
    url: str,
    origin: str,
    place: dict,
    *,
    vk_token: str = '',
    semantic_url: str = '',
) -> dict:
    return _verify_report(
        _build_osint_report(
            url, origin, place, vk_token=vk_token, semantic_url=semantic_url,
        ),
        place,
    )


def _report_for_response(payload: dict, *, cached: bool, updated_at) -> dict:
    report = dict(payload)
    report['cached'] = cached
    if updated_at is not None:
        report['updated_at'] = (
            updated_at.isoformat() if hasattr(updated_at, 'isoformat') else str(updated_at)
        )
    else:
        report.pop('updated_at', None)
    return report


def _refilter_report(payload: dict, place: dict) -> dict:
    """Re-apply current geo/junk filters to a stored report."""
    report = dict(payload)
    items = list(report.get('items') or [])
    photos = list(report.get('photos') or [])
    description_links = links_from_description(str(place.get('description') or ''))
    filtered = items  # Identity verification below is authoritative for cached reports.
    description_links = [link for link in description_links
                         if not is_direct_image_url(link['url'])]
    # Description URLs are authoritative — keep them even if an older report
    # omitted them or a prior filter drop removed the row.
    report['items'] = _merge(
        [tuple(filtered), tuple(description_links)],
        'url',
        _MAX_RESULTS,
    )
    report['photos'] = _merge(
        [tuple(direct_photos(links_from_description(str(place.get('description') or '')))),
         tuple(photos)], 'image_url', _MAX_PHOTOS,
    )
    report['total'] = len(report['items'])
    report['photos_total'] = len(report['photos'])
    return _verify_report(report, place)


def load_osint_report(engine, place_id: int) -> dict | None:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                'SELECT payload, updated_at FROM web_osint_reports WHERE place_id = :place_id'
            ),
            {'place_id': place_id},
        ).mappings().first()
    if not row:
        return None
    payload = row['payload']
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        return None
    return _report_for_response(payload, cached=True, updated_at=row['updated_at'])


def save_osint_report(engine, place_id: int, report: dict) -> dict:
    to_store = {
        key: value
        for key, value in report.items()
        if key not in ('cached', 'updated_at')
    }
    with engine.begin() as connection:
        row = connection.execute(
            text(
                '''
                INSERT INTO web_osint_reports (place_id, payload, created_at, updated_at)
                VALUES (
                    :place_id,
                    CAST(:payload AS jsonb),
                    NOW(),
                    NOW()
                )
                ON CONFLICT (place_id) DO UPDATE
                SET payload = EXCLUDED.payload,
                    updated_at = NOW()
                RETURNING updated_at
                '''
            ),
            {
                'place_id': place_id,
                'payload': json.dumps(to_store, ensure_ascii=False),
            },
        ).mappings().one()
    return _report_for_response(to_store, cached=False, updated_at=row['updated_at'])


def get_or_build_osint_report(
    engine,
    url: str,
    origin: str,
    place: dict,
    *,
    vk_token: str = '',
    semantic_url: str = '',
    refresh: bool = False,
) -> dict:
    """Serve a persisted report when present; otherwise build and store it."""
    place_id = int(place['id'])
    if not refresh:
        stored = load_osint_report(engine, place_id)
        if stored is not None:
            filtered = _refilter_report(stored, place)
            missing_identity = []
            for row in filtered.get('verification', {}).get('sources', []):
                candidate = row.get('candidate') or {}
                identity = candidate.get('page_identity') or {}
                if (is_object_url(str(candidate.get('url') or ''))
                        and (row.get('status') == 'unconfirmed'
                             or identity.get('latitude') is None
                             or identity.get('longitude') is None)):
                    missing_identity.append(candidate)
            if missing_identity and time.time() - stored.get('wikimapia_identity_checked_at', 0) >= 300:
                references = [link['url'] for link in links_from_description(str(place.get('description') or ''))]
                recovered_sources = enrich_candidates(place, missing_identity, references)
                filtered['items'] = recovered_sources + filtered['items']
                filtered = _refilter_report(filtered, place)
                filtered['wikimapia_identity_checked_at'] = time.time()
            gallery_urls = {photo.get('source_url') for photo in filtered['photos']
                            if photo.get('engine') == 'wikimapia'}
            missing_wikimapia = [
                link for link in filtered['items']
                if is_object_url(str(link.get('url') or ''))
                and link['url'] not in gallery_urls
            ]
            if missing_wikimapia and time.time() - stored.get('wikimapia_checked_at', 0) >= 300:
                recovered = wikimapia_photos_for_links(missing_wikimapia, _MAX_PHOTOS)
                filtered['wikimapia_checked_at'] = time.time()
                filtered['photos'] = _merge(
                    [tuple(recovered), tuple(filtered['photos'])], 'image_url', _MAX_PHOTOS,
                )
                filtered['photos_total'] = len(filtered['photos'])
                return save_osint_report(engine, place_id, _verify_report(filtered, place))
            vk_parents = {source_key(photo.get('source_url')) for photo in filtered['photos']
                          if photo.get('engine') == 'vk'}
            missing_vk = [link for link in links_from_description(str(place.get('description') or ''))
                          if is_vk_group_url(link['url']) and source_key(link['url']) not in vk_parents]
            if missing_vk and time.time() - stored.get('vk_photos_checked_at', 0) >= 300:
                recovered = vk_photos_for_links(vk_token, missing_vk, _MAX_PHOTOS)
                filtered['vk_photos_checked_at'] = time.time()
                filtered['photos'] = _merge([tuple(recovered), tuple(filtered['photos'])], 'image_url', _MAX_PHOTOS)
                return save_osint_report(engine, place_id, _verify_report(filtered, place))
            urban_parents = {source_key(photo.get('source_url')) for photo in filtered['photos']
                             if photo.get('engine') == 'urban3p'}
            missing_urban = [link for link in links_from_description(str(place.get('description') or ''))
                             if link.get('category') == 'urban3p'
                             and source_key(link['url']) not in urban_parents]
            if missing_urban and time.time() - stored.get('urban3p_photos_checked_at', 0) >= 300:
                recovered = urban3p_photos_for_links(missing_urban, _MAX_PHOTOS)
                filtered['urban3p_photos_checked_at'] = time.time()
                filtered['photos'] = _merge([tuple(recovered), tuple(filtered['photos'])], 'image_url', _MAX_PHOTOS)
                return save_osint_report(engine, place_id, _verify_report(filtered, place))
            # A transient source failure must not freeze an empty gallery forever.
            # Retry missing description galleries, at most once per five minutes.
            gallery_sources = {
                str(photo.get('source_url') or '').rstrip('/')
                for photo in filtered.get('photos', [])
                if photo.get('engine') == 'geocache'
            }
            missing = [
                link for link in links_from_description(str(place.get('description') or ''))
                if (urlparse(link['url']).hostname or '').lower() in {
                    'geocaching.su', 'www.geocaching.su', 'geocaching.ru', 'www.geocaching.ru',
                } and link['url'].rstrip('/') not in gallery_sources
            ]
            if missing and time.time() - stored.get('geocache_photos_checked_at', 0) >= 300:
                recovered = generic_page_photos_for_links(missing, limit=_MAX_PHOTOS)
                filtered['geocache_photos_checked_at'] = time.time()
                filtered['photos'] = _merge(
                    [tuple(recovered), tuple(filtered.get('photos', []))],
                    'image_url', _MAX_PHOTOS,
                )
                filtered['photos_total'] = len(filtered['photos'])
                return save_osint_report(engine, place_id, _verify_report(filtered, place))
            # Re-read confirmed Yandex organizations whose legacy search thumbnails
            # lack gallery provenance. Keep failures under a five-minute cooldown.
            yandex_parents = {source_key(photo.get('source_url')) for photo in filtered['photos']
                              if photo.get('engine') == 'yandex_maps'}
            missing_yandex = [item for item in filtered['items']
                              if source_key(item.get('url')).startswith('yandex_maps:')
                              and source_key(item.get('url')) not in yandex_parents][:2]
            if missing_yandex and time.time() - stored.get('yandex_photos_checked_at', 0) >= 300:
                recovered = yandex_maps_photos_for_links(missing_yandex, _MAX_PHOTOS)
                filtered['yandex_photos_checked_at'] = time.time()
                filtered['photos'] = _merge([tuple(recovered), tuple(filtered['photos'])], 'image_url', _MAX_PHOTOS)
                return save_osint_report(engine, place_id, _verify_report(filtered, place))
            # Persist tightened filters so junk does not return next time.
            if (
                filtered.get('verification') != stored.get('verification')
                or filtered.get('wikimapia_identity_checked_at') != stored.get('wikimapia_identity_checked_at')
                or filtered.get('items') != stored.get('items')
                or filtered.get('total') != stored.get('total')
                or filtered.get('photos_total') != stored.get('photos_total')
                or filtered.get('photos') != stored.get('photos')
            ):
                return save_osint_report(engine, place_id, _verify_report(filtered, place))
            return filtered
    report = build_osint_report(
        url, origin, place, vk_token=vk_token, semantic_url=semantic_url,
    )
    return save_osint_report(engine, place_id, report)
