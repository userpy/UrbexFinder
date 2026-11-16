"""OSINT report built from SearXNG (XNG) search results for a place card."""
import logging
import re
import threading
import time
from collections import OrderedDict
from urllib.parse import urlparse
import httpx
from urbex.domain.rules import DomainError
from urbex.infrastructure.osint_assess import assess_osint_items
from urbex.infrastructure.osint_description import (
    description_photos_for_links,
    links_from_description,
    urban3p_photos_for_links,
    vk_sources_for_links,
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
)
_URBEX_SITE_QUERY = (
    '('
    + ' OR '.join(f'site:{domain}' for domain in _URBEX_SITE_DOMAINS)
    + ')'
)
_URBEX_SITE_TEXT = (
    '(urban3p OR swalker OR caves.ru OR planetadorog OR "планета дорог" OR urbexstalker)'
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
    'недостроенный', 'недостроенная', 'недострой',
    'лагерь', 'усадьба', 'территория', 'улица', 'город', 'район',
    'область', 'россия', 'федеральный', 'округ', 'центральный',
    'ангар', 'ангара', 'ангары', 'склад', 'цех', 'завод', 'фабрика',
    'база', 'базы', 'отдых', 'отдыха', 'оздоров', 'санаторий', 'пансионат',
    'турбаза', 'гостиница', 'отель', 'курорт',
    'войсковая', 'войсковой', 'войсковое', 'войсковые',
    'воинская', 'воинской', 'воинское', 'воинские',
    'часть', 'части', 'гарнизон', 'гарнизона', 'полигон', 'полигона',
})
# Region aliases so «Московская область» also matches «Подмосковье».
_LOCATION_SYNONYMS = {
    'московская': ('московская', 'подмосковье', 'подмосковья', 'подмосковный', 'москва'),
    'москва': ('москва', 'московская', 'подмосковье', 'подмосковья'),
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
    'база', 'базы', 'отдых', 'отдыха',
    'войсковая', 'войсковой', 'воинская', 'воинской',
    'часть', 'части', 'гарнизон', 'полигон',
})
_MILITARY_PLACE_RE = re.compile(
    r'(?:\bв\s*/\s*ч\b|\bвч\b|войсков\w*\s+част|воинск\w*\s+част)',
    re.IGNORECASE,
)
_UNIT_NUMBER_RE = re.compile(r'\b(\d{4,6})\b')
# If the place is in Moscow region, drop hits that clearly name another city/oblast.
_FOREIGN_GEO = (
    'сочи', 'краснодар', 'адыге', 'соузг', 'алтай', 'байкал',
    'брянск', 'воронеж', 'казан', 'самар', 'ростов',
    'екатеринбург', 'свердловск', 'новосибирск', 'калининград', 'владивосток',
    'тюмен', 'ярославл', 'тула', 'рязан', 'твер', 'смоленск', 'псков', 'курск',
    'белгород', 'нижегород', 'владимир', 'владимирск', 'иванов', 'костром',
    'калуж', 'орлов', 'липецк', 'тамбов', 'пенз', 'ульянов', 'саратов',
    'волгоград', 'астрахан', 'оренбург', 'перм', 'челябинск', 'курган',
    'омск', 'томск', 'кемеров', 'красноярск', 'иркутск', 'бурят',
    'якут', 'хабаровск', 'примор', 'сахалин', 'камчат', 'мурманск', 'архангельск',
    'вологод', 'карел', 'коми', 'ставропол', 'дагестан', 'чечен', 'крым',
    'севастопол', 'башкир', 'татарстан', 'удмурт', 'чуваш', 'марий',
    'шачино', 'зубова',
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
    'воскресенки', 'воскресенка', 'воскресенск',
    'пионерский', 'пионер', 'детский', 'оздоровительный',
    'база', 'базы', 'отдых', 'отдыха', 'турбаза',
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
})


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


def _urbex_site_query(place: dict) -> str:
    """Restrict SearXNG to known RU urbex catalogs."""
    name = (place.get('name') or '').strip()
    location = _short_location(place)
    subject = ' '.join(part for part in (name, location) if part).strip()
    if not subject:
        return ''
    return f'{subject} {_URBEX_SITE_QUERY}'[:200]


def _queries_for(place: dict) -> list[str]:
    """Build SearXNG queries: urbex sites, then name+region, then coordinates."""
    name = (place.get('name') or '').strip()
    location = _short_location(place)
    coords = _coords(place)

    queries: list[str] = []
    # Bias toward Urban3P / Swalker / Caves / Планета дорог / UrbexStalker.
    site_query = _urbex_site_query(place)
    if site_query:
        queries.append(site_query)
    # Region before bare name — «Атлант» alone pulls Sochi camps.
    if name and location and location.casefold() != name.casefold():
        queries.append(f'{name} {location}'[:200])
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
    region = (place.get('region') or '').strip()
    address = (place.get('full_address') or '').strip()
    if region and len(region) <= 80:
        return region
    if address and len(address) <= 80:
        return address
    return ''


def _is_military_place_name(name: str) -> bool:
    return bool(_MILITARY_PLACE_RE.search(name or ''))


def _unit_numbers(text: str) -> set[str]:
    return set(_UNIT_NUMBER_RE.findall(text or ''))


def _image_queries_for(place: dict) -> list[str]:
    """Image queries: prefer location+coords; avoid bare generic names."""
    name = (place.get('name') or '').strip()
    location = _short_location(place)
    coords = _coords(place)
    distinctive = _distinctive_tokens(name)
    # Steer engines away from memes, games and classifieds.
    negative = (
        ' -backrooms -roblox -minecraft -wallpaper -pinterest'
        ' -avito -cian -продам -недострой'
    )
    if _is_military_place_name(name):
        negative += (
            ' -зрк -с-300 -с-400 -с-500 -пво'
            ' -воздушно-космической -алмаз-антей -триумф'
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
    for token in _significant_tokens(region):
        if token in {'россия', 'область', 'район', 'округ', 'край', 'город'}:
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


def _has_foreign_geo(blob: str, location_tokens: set[str]) -> bool:
    for hint in _FOREIGN_GEO:
        if hint not in blob:
            continue
        # Hint is part of our own location (e.g. place in Sochi).
        if any(hint in token or token in hint for token in location_tokens):
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
    }
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

    if _is_military_place_name(name):
        return _matches_military_place(
            item, place, location_tokens=location_tokens, fine_location=fine_location,
        )

    if location_tokens:
        if _has_foreign_geo(blob, location_tokens):
            return False
        # «Заброшенный ангар» + only oblast → too many unrelated MO hangars.
        if _is_structure_only_name(name):
            if fine_location:
                return _blob_has_any(blob, fine_location)
            return False
        if not unique_tokens:
            return _blob_has_any(blob, location_tokens)
        if _blob_has_any(blob, location_tokens):
            return True
        # Rare exception: unique codes/names (АЗЛК) with no competing geo.
        return _blob_has_any(blob, unique_tokens)

    if name_tokens:
        return _blob_has_any(blob, name_tokens)
    return False


def _filter_photos(photos: list[dict], place: dict) -> list[dict]:
    return [
        photo for photo in photos
        if not _is_junk_photo(photo)
        and _matches_place(photo, place, ('title', 'source_url', 'image_url'))
    ]


def _filter_sources(items: list[dict], place: dict) -> list[dict]:
    return [
        item for item in items
        if _matches_place(item, place, ('title', 'snippet', 'url'))
    ]


def _http_url(value: object) -> str | None:
    text = str(value or '').strip()
    if text.startswith(('http://', 'https://')):
        return text[:2000]
    return None


def _engines_for(category: str) -> str:
    # Pin engines that work from this Docker network; DDG/Google CSE often hang.
    if category == 'images':
        return 'bing images'
    return 'bing,wikipedia'


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


def build_osint_report(
    url: str,
    origin: str,
    place: dict,
    *,
    vk_token: str = '',
) -> dict:
    description_links = links_from_description(str(place.get('description') or ''))
    curated_photos = description_photos_for_links(
        description_links, vk_token=vk_token, limit=_MAX_PHOTOS, place=place,
    )
    vk_sources = vk_sources_for_links(vk_token, description_links, limit=_MAX_RESULTS)

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

    searched = _filter_sources(_merge(general_batches, 'url', _MAX_RESULTS), place)
    searched_photos = _filter_photos(_merge(image_batches, 'image_url', _MAX_PHOTOS), place)
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
    # When SearXNG finds Urban3P object pages, pull their gallery photos too.
    urban3p_from_search: list[dict] = []
    remaining = _MAX_PHOTOS - len(curated_photos)
    if remaining > 0:
        urban3p_from_search = urban3p_photos_for_links(merged, limit=remaining)
    photos = _merge(
        [tuple(curated_photos), tuple(urban3p_from_search), tuple(searched_photos)],
        'image_url',
        _MAX_PHOTOS,
    )
    if not merged and photos:
        # Photos already filtered; still re-check promoted landing pages.
        merged = _filter_sources(_sources_from_photos(photos), place)
    if not merged and not photos:
        # Distinguishes "SearXNG down" from "nothing relevant found".
        probe = _search_soft(url, origin, queries[0], 'general')
        if not probe and not description_links:
            raise DomainError('Не удалось получить данные из открытых источников. Повторите попытку позже.', 502)
        if probe:
            general_batches = [probe]
            merged = _filter_sources(_merge(general_batches, 'url', _MAX_RESULTS), place)
            merged = _merge([tuple(description_links), tuple(merged)], 'url', _MAX_RESULTS)
        else:
            merged = description_links[:_MAX_RESULTS]

    # Curated first, then known urbex catalogs, then the rest of the web.
    def _source_rank(item: dict, *, url_key: str) -> int:
        engine = str(item.get('engine') or '')
        if engine in ('description', 'vk', 'dzen', 'yandex_maps', 'urban3p'):
            return 0
        url = str(item.get(url_key) or item.get('source_url') or item.get('url') or '')
        if _is_urbex_site_url(url) or engine in _URBEX_SITE_DOMAINS:
            return 1
        return 2

    merged.sort(key=lambda item: (
        _source_rank(item, url_key='url'),
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
        'total': len(merged),
        'items': merged,
        'photos': photos,
        'photos_total': len(photos),
        'assessment': assess_osint_items(merged),
    }
