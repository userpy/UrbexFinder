"""UrbexFinder OSINT report + query generation (single replacement file).

Requires the project's existing urbex.infrastructure helper modules, SQLAlchemy,
and httpx. No second *query-generator* module is needed.

v3: bounded concurrent SearXNG calls, cache TTL, safer geographic query parsing,
source-verified image results, diversified source/image pools and search diagnostics.
v3.1: expanded RU/international OSINT discovery sources with bounded site groups.
v3.2: isolated contextual-relevance review for sources lacking independent geolocation.
"""
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse
import httpx
from dataclasses import dataclass
from typing import Literal
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


# ---------------------------------------------------------------------------
# Integrated UrbexFinder query generator (single-file replacement).
# Query variants are search hypotheses, not confirmed alternative place names.
# Existing imports below this block remain the same as the original report.
# ---------------------------------------------------------------------------
OSINTQueryStrategy = Literal['exact', 'local', 'alias', 'site', 'coordinates', 'fallback', 'images']

# Public search scopes for UrbexFinder. A path is included where searching the
# entire domain would be too broad (Pikabu community, Yandex Maps).
# These are only discovery targets, not permission to copy map data or images.
_QG_SITES: tuple[str, ...] = (
    # Always start with the two historically high-yield catalogs.
    'urban3p.ru', 'swalker.ru',
    # Russian urbex forums, photo reports and object directories.
    'caves.ru', 'planetadorog.ru', 'stalk-zktmo.ru',
    'stalkersworld.ru', 'urban-explorer.ru', 'map-stalk-zktmo.ru',
    # Historical/geographic sources and geocaching.
    'wikimapia.org', 'geocaching.su', 'geocaching.ru', 'pastvu.com',
    'pikabu.ru/community/urbex', 'openstreetmap.org', 'yandex.ru/maps',
    # International urbex catalogs that also index Russian locations.
    'urbexstalker.com', 'urbex-maps.com', 'urbexology.com',
    'zuniz.com', 'carte-urbex.com',
)
_QG_MAX_QUERY_LENGTH = 200
_QG_MAX_TEXT_QUERIES = 6
_QG_MAX_IMAGE_QUERIES = 3

@dataclass(frozen=True)
class OSINTSearchQuery:
    strategy: OSINTQueryStrategy
    query: str
    priority: int

# These are search rewrites, NOT assertions that they are official names.
_QG_TYPE_PREFIX = re.compile(
    r'^(?:(?:заброшенн\w*|бывш\w*|стар\w*)\s+)*'
    r'(?:пионерлагер\w*|детлагер\w*|дол\s+|пионерск\w*\s+лагер\w*|детск\w*\s+оздоровительн\w*\s+лагер\w*|'
    r'детск\w*\s+лагер\w*|санатори\w*|баз[аыу]\s+отдыха)\s*',
    re.IGNORECASE,
)
_QG_ADMIN = re.compile(r'(?:област\w*|район\w*|округ\w*|республик\w*|кра[йя]\w*|федеральн\w*|росси\w*)', re.I)
_QG_REGION = re.compile(r'(?:[А-ЯЁа-яё\-]+\s+област\w*|[А-ЯЁа-яё\-]+\s+край|республика\s+[А-ЯЁа-яё\-]+|г\.?\s*Москва|\bМосква\b)', re.I)
_QG_SETTLEMENT_PREFIX = re.compile(r'^(?:(?:деревня|д\.|село|с\.|пос[её]лок|п\.|город|г\.)\s+)', re.I)
_QG_NON_SETTLEMENT = re.compile(r'^(?:СНТ|ДНТ|НСТ|ДОЛ|ТСН|ТСЖ|КП|ГСК|СНП|ДПК|ТОС)\b', re.I)
_QG_STREET = re.compile(r'\b(?:улица|ул\.|шоссе|проспект|переулок|дорога|набережная|дом|строение)\b', re.I)
_QG_QUOTED_NAME = re.compile(r'[«"]([^»"]{3,65})[»"]')
_QG_BAD_ALIASES = {'разное', 'без названия', 'неизвестно', 'нет', 'none', 'null'}
_QG_NEGATIVE_IMAGES = ('-pinterest', '-roblox', '-minecraft', '-avito', '-cian', '-wallpaper')


def _qg_clean(value: object, *, max_len: int = 120) -> str:
    if value is None:
        return ''
    value = re.sub(r'\s+', ' ', str(value)).strip()
    # Do not allow precomposed SearXNG operators from untrusted place metadata.
    value = re.sub(r'(?i)\b(?:site|intitle|inurl|filetype):', '', value)
    value = value.replace('(', ' ').replace(')', ' ').replace('|', ' ')
    return value[:max_len].strip()


def _qg_explicit_aliases(place: dict) -> list[str]:
    raw = place.get('aliases') or place.get('alternative_names') or place.get('alternate_names') or []
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            raw = parsed if isinstance(parsed, list) else re.split(r'[;\n]+', raw)
        except (TypeError, ValueError):
            raw = re.split(r'[;\n]+', raw)
    if not isinstance(raw, (list, tuple)):
        return []
    found = []
    for item in raw[:30]:
        name = _qg_fix_quotes(_qg_clean(item if isinstance(item, str) else '', max_len=90))
        if name and name.casefold() not in _QG_BAD_ALIASES:
            found.append(name)
    return found


def _qg_fix_quotes(value: str) -> str:
    """Remove unbalanced punctuation (from pasted/truncated card names)."""
    if value.count('«') != value.count('»'):
        value = value.replace('«', '').replace('»', '')
    if value.count('"') % 2:
        value = value.replace('"', '')
    return value.strip()


def _qg_names(place: dict) -> tuple[str, list[str]]:
    primary = _qg_clean(place.get('name'), max_len=110)
    primary = _qg_fix_quotes(primary)
    aliases = _qg_explicit_aliases(place)
    if primary:
        match = _QG_QUOTED_NAME.search(primary)
        if match:
            aliases.append(match.group(1).strip())
        reduced = _QG_TYPE_PREFIX.sub('', primary).strip(' «»"')
        reduced = _qg_fix_quotes(reduced)
        if len(reduced) >= 4 and reduced.casefold() != primary.casefold():
            aliases.append(reduced)
    seen = {primary.casefold()}
    unique = []
    for alias in aliases:
        if alias.casefold() not in seen:
            seen.add(alias.casefold())
            unique.append(alias)
    return primary, unique


def _qg_location(place: dict) -> tuple[str, str]:
    region = _qg_clean(place.get('region'), max_len=90)
    full = _qg_clean(place.get('full_address'), max_len=500)
    if not region:
        m = _QG_REGION.search(full)
        if m:
            region = m.group(0)
    explicit = _qg_clean(place.get('settlement') or place.get('locality') or place.get('city'), max_len=70)
    if explicit:
        return explicit, region
    # In Nominatim-style addresses the closest settlement is usually the last
    # usable component before the administrative district/region. The first
    # component often names the object itself, a patron or a garden association.
    candidates: list[str] = []
    for raw in re.split(r'\s*,\s*', full):
        raw = raw.strip()
        if not raw or _QG_NON_SETTLEMENT.match(raw):
            continue
        # «Холмогоры» as a standalone address component is often a named site,
        # not a village. A.P. Гайдар is a dedication rather than a settlement.
        if ((raw.startswith(('«', '"')) and raw.endswith(('»', '"')))
                or re.match(r'^(?:[А-ЯЁ]\.\s*){1,3}', raw)):
            continue
        part = _QG_SETTLEMENT_PREFIX.sub('', raw.strip(' «»"')).strip()
        if (not 3 <= len(part) <= 65 or re.search(r'\d', part) or
                _QG_ADMIN.search(part) or _QG_STREET.search(part) or
                part.casefold() == region.casefold() or
                part.casefold() == str(place.get('name') or '').casefold()):
            continue
        if re.search(r'\b(?:лагерь|санаторий|усадьба|завод|бункер|церковь|храм)\b', part, re.I):
            continue
        candidates.append(part)
    return (candidates[-1] if candidates else ''), region


def _qg_coordinate_string(place: dict) -> str:
    try:
        lat = float(place['latitude'])
        lon = float(place['longitude'])
    except (TypeError, KeyError, ValueError):
        return ''
    if not (-85 <= lat <= 85 and -180 <= lon <= 180):
        return ''
    return f'{lat:.5f}, {lon:.5f}'


def _qg_compose(*parts: str, limit: int = _QG_MAX_QUERY_LENGTH) -> str:
    """Add only whole terms; never truncate a search operator mid-expression."""
    words = []
    length = 0
    for raw in parts:
        term = _qg_clean(raw, max_len=160) if not raw.startswith('site:') else raw
        if not term:
            continue
        new_length = length + len(term) + (1 if words else 0)
        if new_length > limit:
            continue
        words.append(term)
        length = new_length
    return ' '.join(words)


def _qg_site_queries(name: str) -> list[str]:
    """Batch discovery sites into bounded SearXNG queries.

    There are more sources than the per-report search budget. Urban3P/Swalker
    are always included, while other domains rotate deterministically across
    objects; otherwise sites appended to _QG_SITES would never be queried.
    Search engines may vary in their handling of grouped site: operators.
    """
    # Use whole words to leave sufficient room for multiple domain operators.
    subject = _qg_compose(*name.split(), limit=72) or _qg_clean(name, max_len=72)
    # Rotation has no Python hash-randomization and is repeatable for a place.
    core = _QG_SITES[:2]
    other = _QG_SITES[2:]
    offset = sum(ord(char) for char in name.casefold()) % len(other) if other else 0
    sites = core + other[offset:] + other[:offset]

    queries: list[str] = []
    batch: list[str] = []
    for site in sites:
        operator = f'site:{site}'
        proposed = ' OR '.join((*batch, operator))
        if batch and len(f'{subject} ({proposed})') > _QG_MAX_QUERY_LENGTH:
            queries.append(f"{subject} ({' OR '.join(batch)})")
            batch = [operator]
        else:
            batch.append(operator)
    if batch:
        queries.append(f"{subject} ({' OR '.join(batch)})")
    return queries


def generate_osint_queries(place: dict, *, max_queries: int = _QG_MAX_TEXT_QUERIES,
                     image: bool = False) -> list[OSINTSearchQuery]:
    """Return prioritized *diverse* queries. Defaults work with SearXNG JSON API."""
    if max_queries <= 0:
        return []
    name, aliases = _qg_names(place)
    settlement, region = _qg_location(place)
    coords = _qg_coordinate_string(place)
    location = _qg_compose(settlement, region) if settlement.casefold() != region.casefold() else region
    candidates: list[OSINTSearchQuery] = []

    def add(strategy: OSINTQueryStrategy, priority: int, *parts: str) -> None:
        q = _qg_compose(*parts)
        if q:
            candidates.append(OSINTSearchQuery(strategy, q, priority))

    if image:
        if name:
            add('images', 100, name, settlement, 'фото')
            for alias in aliases[:2]:
                add('images', 90, alias, location, 'фото')
            add('images', 85, name, region, 'фото')
            if coords:
                add('images', 65, name, coords, 'фото')
            for site in _QG_SITES[:2]:
                add('images', 70, name, f'site:{site}', 'фото')
        elif coords:
            add('images', 70, coords, 'фото')
        elif location:
            add('images', 50, location, 'фото')
        # Postfilter junk hosts as well: engine support for negative terms varies.
        enriched = []
        for item in candidates:
            suffix = []
            for negative in _QG_NEGATIVE_IMAGES:
                if len(item.query) + sum(len(x) + 1 for x in suffix) + len(negative) + 1 <= _QG_MAX_QUERY_LENGTH:
                    suffix.append(negative)
            enriched.append(OSINTSearchQuery(item.strategy, ' '.join([item.query] + suffix), item.priority))
        candidates = enriched
    else:
        if name:
            add('exact', 110, name, settlement or region)
            for index, query in enumerate(_qg_site_queries(name)):
                candidates.append(OSINTSearchQuery('site', query, 100 - index))
            for alias in aliases[:5]:
                add('alias', 95, alias, settlement or region)
            if settlement and region:
                add('local', 90, name, location)
            if coords:
                add('coordinates', 75, name, coords)
                add('coordinates', 67, coords)
            add('fallback', 30, name)
        else:
            if coords:
                add('coordinates', 80, coords)
            if location:
                add('local', 60, location)

    # Query quotas: favor three *different groups* of sites without adding
    # HTTP requests. Keep exact, alias and local search for identity matching.
    order = (['images'] if image else
             ['exact', 'site', 'alias', 'site', 'local', 'site', 'coordinates', 'fallback'])
    by_strategy: dict[str, list[OSINTSearchQuery]] = {}
    seen: set[str] = set()
    for item in candidates:
        key = item.query.casefold()
        if key in seen:
            continue
        seen.add(key)
        by_strategy.setdefault(item.strategy, []).append(item)
    for bucket in by_strategy.values():
        bucket.sort(key=lambda row: -row.priority)
    chosen: list[OSINTSearchQuery] = []
    for strategy in order:
        bucket = by_strategy.get(strategy, [])
        if bucket and len(chosen) < max_queries:
            chosen.append(bucket.pop(0))
    remaining = sorted((x for bucket in by_strategy.values() for x in bucket),
                       key=lambda row: -row.priority)
    chosen.extend(remaining[:max(0, max_queries - len(chosen))])
    return chosen[:max_queries]




_log = logging.getLogger(__name__)
_lock = threading.Lock()  # protects cache and the shared rate limiter only
_last_request = 0.0
_SEARCH_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix='urbex-searxng')
_SEARCH_DEADLINE = 26.0  # soft retrieval budget; enrichment has its own runtime
_REQUEST_SPACING = 0.25
_REPORT_TTL_SECONDS = 7 * 24 * 3600  # the HTTP-facing cache is independent

_MAX_RESULTS = 12
_MAX_PHOTOS = 12
# Keep cold reports under the Next.js rewrite proxy budget (~30s).
# One slot is reserved for urbex site: queries (Urban3P, Swalker, …).
_MAX_QUERIES = 6
_MAX_IMAGE_QUERIES = 3
# Specialized catalogs and location-history sources, used for source
# prioritization after identity verification. Generic hostnames (pikabu.ru,
# yandex.ru, openstreetmap.org) must NOT be treated as dedicated urbex hosts.
_URBEX_SITE_DOMAINS = (
    'urban3p.ru',
    'swalker.ru',
    'caves.ru',
    'planetadorog.ru',
    'stalk-zktmo.ru',
    'stalkersworld.ru',
    'urban-explorer.ru',
    'map-stalk-zktmo.ru',
    'urbexstalker.com',
    'urbex-maps.com',
    'urbexology.com',
    'zuniz.com',
    'carte-urbex.com',
    'geocaching.com',
    'geocaching.ru',
    'geocaching.su',
    'opencaching.pl',
    'wikimapia.org',
    'pastvu.com',
)
_URBEX_SITE_QUERY = (
    '('
    + ' OR '.join(f'site:{domain}' for domain in _URBEX_SITE_DOMAINS)
    + ')'
)
_URBEX_SITE_TEXT = (
    '(urban3p OR swalker OR caves.ru OR planetadorog OR "планета дорог" '
    'OR stalk-zktmo OR stalkersworld OR urban-explorer OR map-stalk-zktmo '
    'OR urbexstalker OR urbex-maps OR urbexology OR zuniz OR carte-urbex '
    'OR geocaching OR геокешинг OR opencaching OR wikimapia OR pastvu)'
)
_CACHE_SIZE = 256
# Only successful non-empty answers are cached. Empty answers must not stick forever
# when engines were temporarily down.
_SEARCH_CACHE_TTL_SECONDS = 15 * 60
_search_cache: OrderedDict[tuple[str, str, str, str], tuple[float, tuple[dict, ...]]] = OrderedDict()

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


def _query_generator_place(place: dict) -> dict:
    """Build query metadata, preserving any richer name from the old logic."""
    query_place = dict(place)
    enriched_name = _search_name(place)
    raw_name = str(place.get('name') or '').strip()
    if enriched_name and enriched_name != raw_name:
        aliases = _qg_explicit_aliases(place)
        if raw_name:
            aliases.insert(0, raw_name)
        query_place['aliases'] = aliases
        query_place['name'] = enriched_name
    return query_place


def _queries_for(place: dict) -> list[str]:
    """Generate diverse text queries without external generator imports."""
    return [item.query for item in generate_osint_queries(
        _query_generator_place(place), max_queries=_MAX_QUERIES,
    )]


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
    """Generate length-safe image queries without external generator imports."""
    return [item.query for item in generate_osint_queries(
        _query_generator_place(place), max_queries=_MAX_IMAGE_QUERIES, image=True,
    )]


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
    now = time.monotonic()
    with _lock:
        entry = _search_cache.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= now:
            del _search_cache[key]
            return None
        _search_cache.move_to_end(key)
        return value


def _cache_put(key: tuple[str, str, str, str], value: tuple[dict, ...]) -> None:
    # Cache positive results only: a transient empty SearXNG response is not evidence.
    if not value:
        return
    with _lock:
        _search_cache[key] = (time.monotonic() + _SEARCH_CACHE_TTL_SECONDS, value)
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

    # Reserve a start time while locked; NEVER sleep or perform I/O under this lock.
    # Allows concurrent searches while limiting bursts against our SearXNG instance.
    timeout = 15.0 if category == 'images' else 12.0
    with _lock:
        scheduled = max(time.monotonic(), _last_request + _REQUEST_SPACING)
        _last_request = scheduled
    pause = scheduled - time.monotonic()
    if pause > 0:
        time.sleep(pause)
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
    except (httpx.HTTPError, ValueError) as exc:
        raise DomainError('Не удалось получить данные из открытых источников. Повторите попытку позже.', 502) from exc
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


def _search_capture(url: str, origin: str, query: str, category: str) -> tuple[tuple[dict, ...], bool]:
    """Empty successful response is distinct from a failed transport request."""
    try:
        return _search(url, origin, query, category), True
    except DomainError:
        _log.warning('OSINT %s search failed for %r', category, query)
        return (), False
    except Exception:
        _log.exception('Unexpected OSINT %s search error for %r', category, query)
        return (), False


def _search_many(
    url: str, origin: str, queries: list[str], image_queries: list[str],
) -> tuple[list[tuple[dict, ...]], list[tuple[dict, ...]], dict]:
    """Parallel, limited global worker pool; results stay in original query order.

    This is a soft timeout: pending futures are cancelled if not yet running;
    running HTTP calls finish at their own request timeouts.
    """
    jobs = [('general', q) for q in queries] + [('images', q) for q in image_queries]
    futures = [_SEARCH_POOL.submit(_search_capture, url, origin, query, category)
               for category, query in jobs]
    done, pending = wait(futures, timeout=_SEARCH_DEADLINE)
    batches: list[tuple[dict, ...]] = []
    success = 0
    for future in futures:
        if future in done:
            batch, ok = future.result()
            success += int(ok)
            batches.append(batch)
        else:
            future.cancel()
            batches.append(())
    _log.info('OSINT search: %d/%d completed successfully, %d pending at deadline',
              success, len(jobs), len(pending))
    return (batches[:len(queries)], batches[len(queries):], {
        'requested': len(jobs),
        'successful': success,
        'failed_or_timed_out': len(jobs) - success,
        'pending_at_deadline': len(pending),
    })


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

    # Search images and text together, keeping a bounded global pool and a soft
    # deadline. One failed engine must not erase results from another engine.
    general_batches, image_batches, search_diagnostics = _search_many(
        url, origin, queries, image_queries,
    )

    references = [link['url'] for link in description_links]
    photo_candidates = _merge_round_robin(image_batches, 'image_url', _MAX_PHOTOS * 2)
    diverse_sources = _merge_round_robin(
        general_batches, 'url', _MAX_RESULTS * 3,
    )
    candidate_pool = _merge_round_robin(
        [diverse_sources, _sources_from_photos(photo_candidates)],
        'url', _MAX_RESULTS * 3,
    )
    candidate_pool = rank_candidates(semantic_url, place, candidate_pool)
    source_candidates = enrich_candidates(place, candidate_pool, references)
    # Only verified pages can seed gallery extraction or secondary VK fetching.
    searched = [item for item in source_candidates
                if not _is_junk_source(item)
                and verify_source(place, item, references).status == 'accepted']
    # Only images whose landing-page identity was VERIFIED can reach the gallery.
    # Raw search-engine thumbnails alone are not proof of the depicted place.
    accepted_keys = {source_key(item.get('url')) for item in searched
                     if item.get('url')}
    verified_image_photos = [photo for photo in photo_candidates
                            if photo.get('source_url')
                            and source_key(photo['source_url']) in accepted_keys
                            and not _is_junk_photo(photo)]
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
    # The STALK_ZKTMO map forbids copying map content without written consent.
    # Treat its pages as search evidence only; never auto-extract its galleries.
    gallery_links = [item for item in scrape_links
                     if _host_of(str(item.get('url') or '')) != 'map-stalk-zktmo.ru'
                     and not _host_of(str(item.get('url') or '')).endswith('.map-stalk-zktmo.ru')]
    site_from_search = site_photos_for_links(
        gallery_links, limit=other_budget, vk_token=vk_token,
    ) if other_budget else []
    # Interleave Urban3P with Maps/web so one family cannot fill all slots.
    photos = _merge_round_robin(
        [
            tuple(urban_from_search),
            tuple(site_from_search),
            tuple(curated_photos),
            tuple(searched_photos),
            tuple(verified_image_photos),
        ],
        'image_url',
        _MAX_PHOTOS,
    )
    if not merged and photos:
        # Photos already filtered; still re-check promoted landing pages.
        merged = _sources_from_photos(photos)
    if not merged and not photos and not search_diagnostics['successful']:
        # Search outage is different from a valid search with no matching place.
        # Never promote an unverified raw search result into the report.
        raise DomainError('Не удалось получить данные из открытых источников. Повторите попытку позже.', 502)

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
        'search_diagnostics': search_diagnostics,
        'search_completed_at': time.time(),
        'total': len(merged),
        'items': merged,
        'photos': photos,
        'photos_total': len(photos),
        'assessment': assess_osint_items(merged),
    }



# ---------------------------------------------------------------------------
# Contextual relevance is NOT independent geographical identity verification.
# Keep strong name + locality matches visible for manual review when a source
# omits coordinates/oblast. Never use these to seed photo galleries, assign
# protection/condition scores, or change verified `items`.
# ---------------------------------------------------------------------------
_REVIEW_COMMERCE_HOSTS = frozenset({
    'ozon.ru', 'www.ozon.ru', 'wildberries.ru', 'www.wildberries.ru',
    'market.yandex.ru', 'aliexpress.ru', 'www.aliexpress.ru',
})
_REVIEW_GENERIC_ACRONYMS = frozenset({
    'СНТ', 'ДНТ', 'ДОЛ', 'СНП', 'ДПК', 'ГСК', 'ЖК', 'СМИ', 'РФ',
})


def _review_normalize(value: object) -> str:
    """Normalize human-readable text for a conservative lexical check."""
    value = str(value or '').casefold().replace('ё', 'е')
    return ' ' + re.sub(r'[^0-9a-zа-я]+', ' ', value).strip() + ' '


def _review_contains_phrase(haystack: str, needle: str) -> bool:
    text = _review_normalize(needle).strip()
    return bool(text) and f' {text} ' in _review_normalize(haystack)


def _contextual_relevance(place: dict, item: dict) -> dict | None:
    """Find review-worthy *unconfirmed* search hits using independent cues.

    Two cues must come from the source's human-readable title/snippet:
    (1) the object's distinctive name/acronym; (2) the card's locality.
    The search query/URL alone is NEVER considered proof.
    """
    url = str(item.get('url') or '')
    if not url.startswith(('https://', 'http://')) or _is_junk_source(item):
        return None
    host = _host_of(url)
    if host in _REVIEW_COMMERCE_HOSTS:
        return None

    title = str(item.get('title') or '')
    snippet = str(item.get('snippet') or '')
    evidence = f'{title} {snippet}'
    locality, _ = _qg_location(place)
    if not locality or len(_review_normalize(locality).strip()) < 5:
        return None
    if not _review_contains_phrase(evidence, locality):
        return None

    primary, aliases = _qg_names(place)
    names = [primary, *aliases]
    # Exact distinct acronyms are high-signal ('СНУР'), but common structure
    # abbreviations ('ДОЛ', 'СНТ') are not sufficient.
    acronyms = {
        match.group(0) for name in names
        for match in re.finditer(r'(?<![A-Za-zА-ЯЁа-яё])[A-ZА-ЯЁ]{3,9}(?![A-Za-zА-ЯЁа-яё])', name)
        if match.group(0) not in _REVIEW_GENERIC_ACRONYMS
    }
    for acronym in sorted(acronyms, key=len, reverse=True):
        if _review_contains_phrase(evidence, acronym):
            return {
                'evidence': f'Упоминаются {acronym} и {locality}',
                'relevance': 'probable',
            }

    # Otherwise, require a distinctive proper-name word other than locality,
    # building category, or common camp labels. Bare locality + "сталкеры"
    # does not identify one particular structure.
    locality_tokens = set(_review_normalize(locality).split())
    cue_tokens = set()
    for name in names:
        cue_tokens.update(_unique_name_tokens(name))
    cue_tokens = {
        word for word in cue_tokens
        if len(word) >= 5 and word not in locality_tokens
        and word not in _GENERIC_PLACE_TOKENS
        and word not in _COMMON_PLACE_NAMES
    }
    for cue in sorted(cue_tokens, key=len, reverse=True):
        if _review_contains_phrase(evidence, cue):
            return {
                'evidence': f'Совпадают «{cue}» и населённый пункт {locality}',
                'relevance': 'probable',
            }
    return None


def _attach_relevance_review(report: dict, payload: dict, place: dict) -> dict:
    """Expose probable matches separately without bypassing verify_report().

    The frontend can show `related_sources` as a third, non-confirmed
    category. Entries are *not* part of `items` or `photos`.
    """
    # Identity v20 already did the full audit (including explicit geo conflicts).
    # Never broaden its decisions with the older, title/snippet-only fallback.
    if (report.get('verification') or {}).get('version', 0) >= 20:
        report['related_sources'] = list(report.get('related_sources') or [])[:20]
        report['related_total'] = len(report['related_sources'])
        return report
    accepted = {
        source_key(item.get('url')) for item in report.get('items', [])
        if item.get('url')
    }
    raw_candidates = list(payload.get('source_candidates') or [])
    for source in (payload, report):
        for row in (source.get('verification') or {}).get('sources', []):
            if row.get('status') == 'accepted':
                continue
            candidate = row.get('candidate') or {}
            if candidate:
                raw_candidates.append(candidate)
    reviewed: list[dict] = list(report.get('related_sources') or [])[:20]
    seen: set[str] = {
        source_key(item.get('url')) for item in reviewed if item.get('url')
    }
    # Never re-label a verifier-rejected candidate as probable.
    rejected = {
        source_key(row['candidate'].get('url') or row['candidate'].get('source_url'))
        for row in (report.get('verification') or {}).get('sources', [])
        if row.get('status') == 'rejected' and isinstance(row.get('candidate'), dict)
    }
    for item in raw_candidates:
        if len(reviewed) >= 20:
            break
        url = str(item.get('url') or '')
        key = source_key(url) if url else ''
        if not key or key in accepted or key in seen or key in rejected:
            continue
        seen.add(key)
        match = _contextual_relevance(place, item)
        if not match:
            continue
        reviewed.append({
            'url': url,
            'title': str(item.get('title') or ''),
            'snippet': str(item.get('snippet') or ''),
            'status': 'needs_geographic_confirmation',
            'reason': 'Похоже на нужный объект, но точная геопривязка пока не подтверждена',
            **match,
        })
        if len(reviewed) >= 20:
            break
    report['related_sources'] = reviewed
    report['related_total'] = len(reviewed)
    return report


def _verify_report(payload: dict, place: dict) -> dict:
    references = [link['url'] for link in links_from_description(str(place.get('description') or ''))]
    report = verify_report(payload, place, references,
                           junk_source=_is_junk_source, junk_photo=_is_junk_photo)
    report = _attach_relevance_review(report, payload, place)
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


def _report_is_stale(report: dict, *, now: float | None = None) -> bool:
    """Use latest full search time rather than DB updated_at from photo refreshes."""
    now = time.time() if now is None else now
    stamp = report.get('search_completed_at')
    if isinstance(stamp, (float, int)):
        return now - stamp >= _REPORT_TTL_SECONDS
    updated = report.get('updated_at')
    if not updated:
        return True
    try:
        dt = datetime.fromisoformat(str(updated).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return now - dt.timestamp() >= _REPORT_TTL_SECONDS
    except (TypeError, ValueError, OverflowError):
        return True


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
    stored = load_osint_report(engine, place_id) if not refresh else None
    # Only use the stored result without searching when the full search is fresh.
    # Explicit refresh=True always performs a new search.
    if stored is not None and (not url or not _report_is_stale(stored)):
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
    try:
        report = build_osint_report(
            url, origin, place, vk_token=vk_token, semantic_url=semantic_url,
        )
    except DomainError as exc:
        # Stale-while-error: do not blank out a previously verified report on a
        # temporary SearXNG failure. Caller can display stale=True explicitly.
        status = (getattr(exc, 'status_code', None)
                  or getattr(exc, 'status', None)
                  or getattr(exc, 'code', None))
        if stored is not None and status in (502, 503):
            fallback = _refilter_report(stored, place)
            fallback['stale'] = True
            return fallback
        raise
    if (stored is not None and not report.get('items') and not report.get('photos')
            and (stored.get('items') or stored.get('photos'))):
        # A successful but empty index lookup should not silently erase an older
        # verified dossier. Keep it explicitly stale until someone refreshes it
        # with fresh evidence or confirms the old sources are gone.
        fallback = _refilter_report(stored, place)
        fallback['stale'] = True
        return fallback
    return save_osint_report(engine, place_id, report)
