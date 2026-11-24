"""Shared, deterministic place metadata for OSINT discovery and verification.

Built from card metadata only; no network calls or search-result feedback.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from math import isfinite
import json
import re

_TYPES = {
    "radar": r"\bрлс\b|\bрадиолокационн[а-я]*\s+станци[а-я]*\b",
    "radio_center": r"\b(?:радиоцентр[а-я]*|пдрц)\b",
    "shelter": r"\b(?:убежищ|бомбоубежищ|бункер)[а-я]*\b",
    "manor": r"\bусад(?:ьб|еб)[а-я]*\b",
    "housing": r"\bтаунхаус[а-я]*\b|\bкоттеджн[а-я]*\s+посел[а-я]*\b|\bжил[а-я]*\s+(?:комплекс|квартал)[а-я]*\b|\bжк\b",
    "camp": r"\b(?:п\s*/\s*л|пионерлагер[а-я]*|пионерск[а-я]*\s+лагер[а-я]*|детск[а-я]*\s+лагер[а-я]*|детск[а-я]*\s+оздоровительн[а-я]*\s+город(?:ок|ка|ке|ку|ком)|лагер[а-я]*)\b",
    "airport": r"\b(?:аэродром[а-я]*|аэропорт[а-я]*|aerodrome|airport|airfield)\b",
    "factory": r"\b(?:завод|фабрик|комбинат)[а-я]*\b",
    "church": r"\b(?:церков|церкв|храм|собор|часовн)[а-я]*\b",
    "school": r"\b(?:школ|училищ|спту|пту)[а-я]*\b",
    "kindergarten": r"\bдетск[а-я]*\s+сад[а-я]*\b",
    "military": r"\b(?:воинск|войсков)[а-я]*\s+част[а-я]*\b",
    "test_site": r"\bполигон[а-я]*\b",
    # The Istra installation is named «Катушки Тесла» in the card and
    # «Башни Тесла» in Maps. Keep «Тесла» as the name cue: these aliases
    # still need matching coordinates to confirm the Maps organization.
    "tesla_coil": r"\b(?:катушк[а-я]*|башн[а-я]*)\s+(?=тесл[аы]\b)",
    "hospital": r"\b(?:больниц|госпитал|санатори)[а-я]*\b",
    # A missing hotel type made «Трудовые резервы» look unrelated to its card.
    "hotel": r"\b(?:гостиниц|отел|хостел)[а-я]*\b|\bhotel\b",
    "sport": r"\b(?:спортивн[а-я]*\s+комплекс|стадион[а-я]*|спорткомплекс[а-я]*|спортшкол[а-я]*|бассейн[а-я]*)\b",
}

_GENERIC = set("""
заброшенный заброшенная заброшенное заброшенные заброшен заброшено заброшка
бывший бывшая бывшее бывшие старый старая старое новый новая летний детский
пионерский оздоровительный стандартное подземное корпуса корпус территория
территории новой гражданской обороны го ру ru en фото фотографии объект место
на в и у имени им города город городской район районы область края россия рф
строение здание здания сооружение бывшего бывшей недействующий официальный
""".split())


_GEO_ADMIN_NOISE = {"россия", "рф", "центральный", "городской", "муниципальный", "московская", "область", "край"}
_STREET = r"(?:улица|ул\.|проспект|пр-т|переулок|пер\.|шоссе|набережная|аллея|проезд)"
_HOUSE = r"\d+[а-яa-z]?(?:[/\-]\d+[а-яa-z]?)?(?:\s*(?:к(?:орпус)?\.?|стр\.?)\s*\d+)?"


def normalized(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold().replace("ё", "е")).strip()


def _words(value) -> list[str]:
    return re.findall(r"[а-яa-z0-9]+", normalized(value))


def kinds(value) -> set[str]:
    value = normalized(value)
    return {kind for kind, pattern in _TYPES.items() if re.search(pattern, value)}


def radio_center_numbers(value) -> set[str]:
    text = normalized(value)
    patterns = (
        r"\bрадиоцентр[а-я]*\s*(?:№|номер)?\s*(\d+)\b",
        r"\b(\d+)\s*(?:-?(?:й|ый|ой))?\s+радиоцентр[а-я]*\b",
    )
    return {num for pattern in patterns for num in re.findall(pattern, text)}


def name_cues(name) -> set[str]:
    text = normalized(re.sub(r"\((?:ru|en)\)", "", str(name or ""), flags=re.I))
    for pattern in _TYPES.values():
        text = re.sub(pattern, " ", text)
    return {word for word in _words(text) if len(word) >= 3 and word not in _GENERIC}


def words_present(cues, text) -> bool:
    words = set(_words(text))
    return bool(cues) and set(cues) <= words


def address_parts(text) -> tuple[str, str]:
    value = normalized(text)
    leading = re.search(rf"(?:^|[,;])\s*({_HOUSE})\s*[,;]\s*([^,;]+?)\s+{_STREET}(?=\s|[,;]|$)", value)
    if leading:
        return leading[2].strip(), re.sub(r"\s+", "", leading[1])
    match = re.search(rf"(?:^|[,;])\s*{_STREET}\s+([^,;]+)", value)
    if not match:
        match = re.search(rf"(?:^|[,;])\s*([^,;]+?)\s+{_STREET}(?=\s|[,;]|$)", value)
    if not match:
        return "", ""
    street = match[1].strip()
    # Handle «улица Ленина, дом 5» and «улица Ленина, 5».
    next_piece = re.split(r"[,;]", value[match.end():].lstrip(" ,;"), maxsplit=1)[0]
    number = re.match(rf"(?:(?:дом|д\.)\s*)?({_HOUSE})(?=\s|$)", next_piece)
    return street, re.sub(r"\s+", "", number[1]) if number else ""


def locality_cues(text) -> set[str]:
    value = normalized(text)
    result = set()
    for pattern in (
        r"\b(?:городской|муниципальный)\s+округ\s+([а-я-]+)",
        r"\b(?:деревня|село|поселок|город|г\.|д\.)\s+([а-я-]+)",
        r"\b([а-я-]+)\s+(?:район|муниципальный округ|городской округ|область)\b",
    ):
        result.update(re.findall(pattern, value))
    return result - _GEO_ADMIN_NOISE - {"москва"}


def settlement_cues(address) -> set[str]:
    value = normalized(address)
    result = set(re.findall(r"\b(?:город|г\.|деревня|село|поселок)\s+([а-я-]+)", value))
    result.update(re.findall(r"\b(?:микрорайон|мкр\.)\s+([а-я-]+)", value))
    result.update(piece.strip() for piece in value.split(",")
                  if re.fullmatch(r"[а-я-]+", piece.strip()) and piece.strip() not in _GEO_ADMIN_NOISE)
    # СНТ/ДНТ names alone are not independent settlement evidence.
    return result


def coordinates(data):
    try:
        lat, lon = float(data["latitude"]), float(data["longitude"])
        if isfinite(lat) and isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            if abs(lat) < 1e-9 and abs(lon) < 1e-9:
                return None
            return lat, lon
    except (KeyError, TypeError, ValueError):
        pass
    return None


def institution_codes(name: str) -> list[tuple[str, str]]:
    return [(a.casefold(), b) for a, b in re.findall(
        r"\b([А-ЯЁA-Z]{2,10})\s*(?:[-–—№]\s*|\s+)(\d+)\b", str(name or ""))]


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


def search_text(value: object, *, max_len: int = 120) -> str:
    if value is None:
        return ''
    value = re.sub(r'\s+', ' ', str(value)).strip()
    # Do not allow precomposed SearXNG operators from untrusted place metadata.
    value = re.sub(r'(?i)\b(?:site|intitle|inurl|filetype):', '', value)
    value = value.replace('(', ' ').replace(')', ' ').replace('|', ' ')
    return value[:max_len].strip()


def explicit_aliases(place: dict) -> list[str]:
    found = []
    for field in ('aliases', 'alternative_names', 'alternate_names'):
        raw = place.get(field) or []
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                raw = parsed if isinstance(parsed, list) else re.split(r'[;\n]+', raw)
            except (TypeError, ValueError):
                raw = re.split(r'[;\n]+', raw)
        if not isinstance(raw, (list, tuple)):
            continue
        for item in raw[:30]:
            if not isinstance(item, str):
                continue
            name = _fix_quotes(re.sub(r'\s+', ' ', item).strip())
            if name and normalized(name) not in _QG_BAD_ALIASES:
                found.append(name)
    return list(_unique_names(found))[:30]


def _fix_quotes(value: str) -> str:
    """Remove unbalanced punctuation (from pasted/truncated card names)."""
    if value.count('«') != value.count('»'):
        value = value.replace('«', '').replace('»', '')
    if value.count('"') % 2:
        value = value.replace('"', '')
    return value.strip()


def _search_names(place: dict) -> tuple[str, list[str]]:
    primary = search_text(place.get('name'), max_len=110)
    primary = _fix_quotes(primary)
    aliases = explicit_aliases(place)
    if primary:
        match = _QG_QUOTED_NAME.search(primary)
        if match:
            aliases.append(match.group(1).strip())
        reduced = _QG_TYPE_PREFIX.sub('', primary).strip(' «»"')
        reduced = _fix_quotes(reduced)
        if len(reduced) >= 4 and reduced.casefold() != primary.casefold():
            aliases.append(reduced)
    seen = {primary.casefold()}
    unique = []
    for alias in aliases:
        if alias.casefold() not in seen:
            seen.add(alias.casefold())
            unique.append(alias)
    return primary, unique


def place_location(place: dict) -> tuple[str, str]:
    region = search_text(place.get('region'), max_len=90)
    full = search_text(place.get('full_address') or place.get('address'), max_len=2000)
    if not region:
        m = _QG_REGION.search(full)
        if m:
            region = m.group(0)
    explicit = search_text(place.get('settlement') or place.get('locality') or place.get('city'), max_len=70)
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


def _unique_names(values) -> tuple[str, ...]:
    seen = set()
    result = []
    for value in values:
        key = normalized(value)
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return tuple(result)


def _identity_name(name: str, localities: frozenset[str]) -> str:
    """Remove only trailing geography corroborated by the card's address.

    Keep embedded names and unknown parentheses: «Усадьба Липки» must not
    lose «Липки» simply because it stands in the village of the same name.
    """
    result = re.sub(r'\s*\((?:ru|en)\)\s*$', '', name, flags=re.I).strip()
    while result:
        previous = result
        for locality in sorted(localities, key=len, reverse=True):
            pattern = (rf'(?:\s*\(\s*{re.escape(locality)}\s*\)'
                       rf'|(?:\s*[,.;]|\s+[—–-]|\s+в)\s+{re.escape(locality)})\s*$')
            match = re.search(pattern, result.replace('ё', 'е').replace('Ё', 'Е'), flags=re.I)
            if match and name_cues(result[:match.start()]):
                result = result[:match.start()].rstrip(' ,.;—–-')
                break
        if result == previous:
            break
    return result


@dataclass(frozen=True)
class PlaceProfile:
    """Immutable card snapshot; search hypotheses are separate from identities."""

    name: str
    aliases: tuple[str, ...]
    identity_names: tuple[str, ...]
    search_name: str
    search_aliases: tuple[str, ...]
    object_types: frozenset[str]
    name_types: frozenset[str]
    category: str
    description: str
    address: str
    settlement: str
    region: str
    localities: frozenset[str]
    districts: frozenset[str]
    street: str
    house: str
    point: tuple[float, float] | None
    codes: tuple[tuple[str, str], ...]
    radio_numbers: frozenset[str]
    reference_urls: tuple[str, ...]

    @property
    def location_text(self) -> str:
        return ', '.join(_unique_names((self.address, self.settlement, self.region)))

    @property
    def coordinate_query(self) -> str:
        return f'{self.point[0]:.5f}, {self.point[1]:.5f}' if self.point else ''

    def matching_name(self, title: str) -> str:
        matches = [name for name in self.identity_names if words_present(name_cues(name), title)]
        default = self.identity_names[0] if self.identity_names else ''
        return max(matches, key=lambda name: len(name_cues(name)), default=default)

    def matches_name(self, title: str) -> bool:
        return any(words_present(name_cues(name), title) for name in self.identity_names)


def build_place_profile(place: dict, *, reference_urls=()) -> PlaceProfile:
    """Use explicit card facts only; never learn identity from search results.

    The caller supplies reference URLs through the existing description-link
    parser. Query cleaning/length limits do not alter the stored identity name.
    """
    name = re.sub(r'\s+', ' ', str(place.get('name') or '')).strip()
    description = str(place.get('description') or '')
    category = str(place.get('category_name') or place.get('category') or '')
    address = str(place.get('full_address') or place.get('address') or '').strip()
    settlement, region = place_location(place)
    localities = frozenset(settlement_cues(address) | ({normalized(settlement)} if settlement else set()))
    aliases = tuple(alias for alias in explicit_aliases(place) if normalized(alias) != normalized(name))
    identities = _unique_names(_identity_name(value, localities) for value in (name, *aliases))
    name_types = frozenset(kinds(name))
    object_types = kinds(' '.join(str(place.get(field) or '') for field in ('name', 'category_name', 'category')))
    if not object_types:
        object_types = kinds(description[:300])

    # A descriptive opening and shortened/quoted names are query hypotheses,
    # not extra aliases capable of confirming a source on their own.
    opening = re.split(r'[.!?\n]', unescape(re.sub(r'<[^>]+>', ' ', description)), maxsplit=1)[0].strip()
    search_name = name
    if (name and not name_types and kinds(opening) and len(opening) <= 160
            and words_present(name_cues(name), opening)):
        search_name = opening
    query_name, rewrites = _search_names(dict(name=search_name, aliases=list(aliases)))
    search_aliases = _unique_names(search_text(value, max_len=110) for value in (
        *identities, name, *rewrites,
    ) if normalized(search_text(value, max_len=110)) != normalized(query_name))
    street, house = address_parts(address or region)
    return PlaceProfile(
        name=name, aliases=aliases, identity_names=identities,
        search_name=query_name, search_aliases=search_aliases,
        object_types=frozenset(object_types), name_types=name_types,
        category=category, description=description, address=address,
        settlement=settlement, region=region, localities=localities,
        districts=frozenset(locality_cues(', '.join((address, region)))),
        street=street, house=house, point=coordinates(place),
        codes=tuple(institution_codes(name)), radio_numbers=frozenset(radio_center_numbers(name)),
        reference_urls=tuple(dict.fromkeys(reference_urls)),
    )
