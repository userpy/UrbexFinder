"""Deterministic identification of UrbexFinder sources and photo galleries.

v23. Drop-in replacement for urbex.infrastructure.osint_identity.

Contextual name + locality matches are review-only, not verified sources.

Safety principles:
* Search rank, query strings, images' file names and snippets alone do not prove identity.
* Contradicting address/coordinates/numbered identity outrank name matches.
* A distinctive multiword name + matching object type can identify an object when
  a card has no usable address, but a lone generic name cannot.
* Unverified pages are never promoted to accepted photo galleries.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from urllib.parse import parse_qsl, unquote, urlencode, urlparse
import re

from .osint_profile import (
    PlaceProfile, build_place_profile, normalized, _words, kinds, name_cues,
    words_present, address_parts, locality_cues, settlement_cues, coordinates,
    radio_center_numbers, institution_codes as _institution_codes,
)

VERSION = 23

# Names common to many sites must not be accepted without a precise cue.
_COMMON_NAMES = set("""
волна дружба заря радуга восход юность смена орленок орленок чайка березки
сокол маяк родина победа восток лесной огонек сосновый спартак динамо
елочки елки солнышко искра звездочка звезда лесная лесное простор надежда
""".split())

def source_key(url) -> str:
    """Canonicalize documented object URLs, avoiding arbitrary path lowercasing."""
    try:
        p = urlparse(str(url or ""))
        host = (p.hostname or "").lower().removeprefix("www.")
        if p.scheme not in {"http", "https"} or not host or p.username or p.password:
            return ""
        path = unquote(p.path).rstrip("/")
        if host in {"yandex.ru", "yandex.com", "yandex.by", "yandex.kz", "yandex.uz"}:
            if m := re.match(r"^/maps/org/[^/]+/(\d+)(?:/|$)", path):
                return f"yandex_maps:{m[1]}"
        if host == "wikimapia.org":
            if m := re.match(r"^/(\d+)(?:/|$)", path):
                return f"wikimapia.org:{m[1]}"
            from .wikimapia import object_url
            if target := object_url(str(url)):
                return f"wikimapia.org:{urlparse(target).path.split('/')[1]}"
        if host in {"urban3p.ru", "urban3p.com"}:
            if m := re.match(r"^/blogs/(\d+)(?:/|$)", path):
                return f"urban3p.ru:blog:{m[1]}"
        if host in {"vk.com", "vk.ru", "m.vk.com", "m.vk.ru"}:
            host = "vk.com"
            if m := re.fullmatch(r"/(?:club|public)(\d+)", path):
                return f"vk.com:group:{m[1]}"
        families = {
            "wikimapia.org": r"^/(\d+)(?:/|$)",
            "geocaching.su": r"^/cache/(\d+)(?:/|$)",
            "urban3p.ru": r"^/object(\d+)(?:/|$)",
            "urban3p.com": r"^/object(\d+)(?:/|$)",
            "vk.com": r"^/(album-?\d+_\d+|photo-?\d+_\d+|wall-?\d+_\d+)$",
        }
        if host in families and (m := re.match(families[host], path)):
            family = "urban3p.ru" if host == "urban3p.com" else host
            return f"{family}:{m[1]}"
        query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query)
                                 if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}))
        return f"{host}:{p.port or ''}{path}" + ("?" + query if query else "")
    except (ValueError, TypeError):
        return ""


def exact_place_title(name, title) -> bool:
    name = normalized(name)
    title = normalized(title)
    return bool(name) and (title == name or any(title.startswith(name + suffix)
                    for suffix in (" (", " /", " — ", " – ", " - ", " | ")))


def _title_has_name_phrase(name: str, title: str) -> bool:
    """Ignore 'abandoned/former' adjectives and object types, not name tokens."""
    place_words = [w for w in _words(name) if w in name_cues(name)]
    if not place_words:
        return False
    title_words = _words(title)
    if not set(place_words) <= set(title_words):
        return False
    # Preserve order and adjacency; do not match independent words in a directory.
    n = len(place_words)
    return any(title_words[i:i + n] == place_words for i in range(len(title_words) - n + 1))


# A relevant search hit is not necessarily a *verified* object.  A distinctive
# name (especially an acronym) AND a precise place locality are useful cues,
# but a search title cannot independently prove geographic identity.
_CONTEXT_EXCLUDED_HOSTS = frozenset({
    "ozon.ru", "wildberries.ru", "market.yandex.ru", "aliexpress.ru",
})
_CONTEXT_GENERIC_ACRONYMS = frozenset({
    "СНТ", "ДНТ", "ДОЛ", "СНП", "ДПК", "ГСК", "ЖК", "СМИ", "РФ", "ГО",
})
_CONTEXT_BAD_LOCALITIES = frozenset({
    "россия", "рф", "москва", "московская область", "область", "район",
    "поселок", "посёлок", "городской округ", "муниципальный округ",
})


def _context_has_phrase(text: str, phrase: str) -> bool:
    """Whole-word normalized matching; СНУР must not match longer acronyms."""
    needle = " ".join(_words(phrase))
    return bool(needle) and (" " + needle + " ") in (" " + " ".join(_words(text)) + " ")


def _context_localities(place: dict) -> set[str]:
    """Collect *fine* place names from card metadata, not the searched pages."""
    found: set[str] = set()
    for field in ("settlement", "locality", "city"):
        raw = str(place.get(field) or "").strip()
        if raw:
            found.add(raw)
    for field in ("full_address", "address"):
        address = str(place.get(field) or "")
        found.update(settlement_cues(address))
        # Support common human-readable forms: «Николо-Урюпино, район, область».
        for part in re.split(r"[,;]", address):
            part = part.strip()
            part = re.sub(r"^(?:д(?:еревня)?\.?|с(?:ело)?\.?|пос[её]лок|г(?:ород)?\.?)\s+", "", part, flags=re.I)
            if re.fullmatch(r"[а-яёА-ЯЁ-]{4,60}", part):
                found.add(part)
    result = set()
    for value in found:
        value = normalized(value)
        if (value in _CONTEXT_BAD_LOCALITIES or len(value) < 5
                or any(stop in value.split() for stop in ("область", "район", "округ", "шоссе", "улица", "снт", "россия"))):
            continue
        result.add(value)
    return result


def contextual_match(place: dict, source: dict) -> tuple[str, ...]:
    """Return name + locality evidence for MANUAL REVIEW, never for acceptance.

    Both cues must occur in the human-readable source title. Search query,
    source URL, and image filename are deliberately ignored as evidence.
    """
    title = str(source.get("title") or "")
    place_name = str(place.get("name") or "")
    if not title or not place_name:
        return ()
    localities = sorted(_context_localities(place), key=len, reverse=True)
    matched_locality = next((x for x in localities if _context_has_phrase(title, x)), None)
    if not matched_locality:
        return ()
    acronyms = {
        token for token in re.findall(r"(?<![\w])[А-ЯЁA-Z]{3,9}(?![\w])", place_name)
        if token not in _CONTEXT_GENERIC_ACRONYMS
    }
    matched_name = next((x for x in sorted(acronyms) if _context_has_phrase(title, x)), None)
    if not matched_name:
        # Only multiword distinctive names: one generic name like «Дружба»
        # plus a village does not uniquely identify a camp.
        cues = name_cues(place_name) - _COMMON_NAMES
        cues -= {"полигон", "сооружение", "объект", "завод", "лагерь", "снт"}
        if len(cues) < 2 or not all(_context_has_phrase(title, x) for x in cues):
            return ()
        matched_name = ", ".join(sorted(cues))
    return (f"Название: {matched_name}", f"Населённый пункт: {matched_locality}")


def distance(a, b) -> float:
    la, lo, lb, lob = map(radians, (*a, *b))
    return 6371000 * 2 * asin(min(1, sqrt(sin((lb - la)/2)**2 + cos(la)*cos(lb)*sin((lob - lo)/2)**2)))


@dataclass(frozen=True)
class Decision:
    status: str
    reasons: tuple[str, ...]
    evidence: tuple[str, ...] = ()

    def json(self) -> dict:
        return {"status": self.status, "reasons": list(self.reasons),
                "evidence": list(self.evidence), "version": VERSION}


def _candidate_codes(text: str, acronym: str) -> set[str]:
    return set(re.findall(rf"\b{re.escape(acronym)}\s*(?:[-–—№]\s*|\s+)(\d+)\b", normalized(text)))


def _is_dedicated_catalog_object(key: str) -> bool:
    """True only for a stable *individual object* URL in known catalogs.

    A search result, general article, tag/category page or Urban3P blog cannot
    certify that a single one-word proper name denotes the object in the card.
    """
    return bool(re.fullmatch(r"(?:wikimapia\.org|urban3p\.ru):\d+", key))


def _source_type_is_compatible(place_types: set[str], source_types: set[str]) -> bool:
    if place_types and source_types:
        return bool(place_types & source_types)
    return False


def _is_vk_group_url(url: str) -> bool:
    try:
        from .osint_description import is_vk_group_url
        return is_vk_group_url(url)
    except ImportError:
        return bool(re.search(r"/(?:club|public)\d+(?:$|[?#])", str(url)))


def verify_source(place, source, reference_urls=(), *, profile: PlaceProfile | None = None) -> Decision:
    """Classify candidate as accepted / rejected / unconfirmed.

    The v20 rules preserve the v17 *multiword* name behavior,
    regardless of category, with no site-specific title whitelist.
    """
    profile = profile or build_place_profile(place, reference_urls=reference_urls)
    key = source_key(source.get("url") or source.get("source_url"))
    if not key:
        return Decision("rejected", ("Некорректная ссылка источника",))
    host = (urlparse(str(source.get("url") or source.get("source_url") or "")).hostname or "").lower()
    if any(host == excluded or host.endswith("." + excluded)
           for excluded in _CONTEXT_EXCLUDED_HOSTS):
        return Decision("rejected", ("Торговая площадка не является подтверждением объекта",))
    reference_keys = {source_key(url) for url in (*profile.reference_urls, *reference_urls)} - {""}
    if key in reference_keys and key.startswith(("urban3p.ru:", "podmoskovnye.ru:")):
        return Decision("accepted", ("Прямая ссылка на объект из описания",), ("reference",))
    if key in reference_keys and _is_vk_group_url(source.get("url") or source.get("source_url") or ""):
        return Decision("accepted", ("Прямая ссылка на группу VK из описания",), ("reference",))

    primary = source.get("page_identity") or {}
    if not isinstance(primary, dict) or primary.get("source_key") != key:
        primary = {}  # Don't trust page metadata attached to another URL.

    place_name = profile.name
    title = str(primary.get("title") or source.get("title") or "")
    text = " ".join(str(x or "") for x in (title, primary.get("text"), source.get("snippet")))
    place_types = profile.object_types
    source_types = kinds(title)
    if not source_types and primary.get("type"):
        source_types = kinds(primary["type"])
    compatible = _source_type_is_compatible(place_types, source_types)
    place_address = profile.location_text
    candidate_address = str(primary.get("address") or title)
    street, house = profile.street, profile.house
    candidate_street, candidate_house = address_parts(candidate_address)
    a, b = profile.point, coordinates(primary)
    metres = distance(a, b) if a and b else None

    place_radio_numbers = profile.radio_numbers
    radio_match = ("radio_center" in place_types and "radio_center" in source_types
                   and bool(place_radio_numbers & radio_center_numbers(text)))
    conflicts: list[str] = []
    # An owner may be named in the place card: "лагерь завода Слава"
    # identifies a camp, not the factory named "Слава".
    primary_camp = "camp" in profile.name_types
    primary_factory = "factory" in profile.name_types and not primary_camp
    if primary_camp and "factory" in source_types and "camp" not in source_types:
        conflicts.append("Вместо лагеря найдена страница завода")
    if primary_factory and "camp" in source_types and "factory" not in source_types:
        conflicts.append("Вместо завода найдена страница лагеря")
    if "housing" in source_types and place_types - {"housing"}:
        conflicts.append("Жилая застройка вместо искомого объекта")
    # A page may call the same technical facility a «полигон» even when
    # the place card is categorized as a military/sport/other facility.
    # Keep the strong (acronym + specific locality) match for MANUAL REVIEW.
    # This never accepts the source, and cannot override hard conflicts above
    # (housing/camp-vs-factory, different address, region, coordinates).
    contextual_title_match = bool(contextual_match(place, {"title": title}))
    ambiguous_test_site = ("test_site" in source_types and contextual_title_match
                           and not {"housing", "factory", "camp"} & source_types)
    if source_types and place_types and not compatible and not ambiguous_test_site:
        conflicts.append("Не совпадает тип объекта")
    place_regions = set(re.findall(r"\b([а-я-]+)\s+область\b", normalized(place_address)))
    candidate_regions = set(re.findall(r"\b([а-я-]+)\s+область\b", normalized(candidate_address)))
    if place_regions and candidate_regions and not place_regions & candidate_regions:
        conflicts.append("Указан другой регион")
    locality = normalized(primary.get("locality"))
    if locality:
        place_cities = set(re.findall(r"\b(?:город|г\.)\s+([а-я-]+)", normalized(place_address)))
        if "москва" in (part.strip() for part in normalized(place_address).split(",")):
            place_cities.add("москва")
        if place_cities and locality not in place_cities:
            conflicts.append("Указан другой населённый пункт")
    if street and candidate_street and street != candidate_street:
        conflicts.append("Указана другая улица")
    if street and candidate_street == street and house and candidate_house and house != candidate_house:
        conflicts.append("Указан другой номер дома")
    if metres is not None and metres > 1500 and not radio_match:
        conflicts.append("Координаты источника дальше 1,5 км от объекта")

    codes = profile.codes
    numbered_match = bool(codes)
    for code, num in codes:
        found = _candidate_codes(text, code)
        numbered_match &= num in found
        if found and num not in found:
            conflicts.append("Не совпадает номер объекта")
    if conflicts:
        return Decision("rejected", tuple(dict.fromkeys(conflicts)))

    # Explicit reference is stronger than a missing type label, but never than
    # contradictory primary evidence already handled above.
    if key in reference_keys:
        return Decision("accepted", ("Исходная ссылка или тот же идентификатор объекта",), ("reference",))

    # Card aliases can match the source name, but never replace the primary
    # object's number, type, address or coordinates in the conflict checks.
    place_name = profile.matching_name(title)
    if (metres is not None and metres <= 100 and exact_place_title(place_name, title)
            and _is_dedicated_catalog_object(key)):
        return Decision("accepted", ("Совпали полное название и координаты объекта",),
                        ("name", "coordinates"))

    cues = name_cues(place_name)
    same_name = words_present(cues, title)
    phrase_match = _title_has_name_phrase(place_name, title)
    same_core_name = same_name and len(cues) >= 2
    fine_local = profile.districts
    settlements = profile.localities
    same_settlement = bool(settlements) and any(words_present({sett},
                    candidate_address + " " + str(primary.get("locality") or "")) for sett in settlements)

    if ("radio_center" in place_types and "radio_center" in source_types
        and "пдрц" in _words(place_name) and "пдрц" in _words(title)
        and metres is not None and metres <= 100):
        return Decision("accepted", ("Совпали ПДРЦ и координаты",), ("name", "coordinates", "type"))
    if (exact_place_title(place_name, title) and compatible
            and (len(cues) >= 2 or (cues and not cues <= _COMMON_NAMES)
                 or (metres is not None and metres <= 100))):
        return Decision("accepted", ("Совпали полное название и тип объекта",), ("name", "type"))
    if radio_match and compatible:
        return Decision("accepted", ("Совпали номер и тип радиоцентра",), ("name", "type"))
    if ("airport" in place_types and "airport" in source_types and same_name
            and (metres is None or metres <= 1000)):
        return Decision("accepted", ("Совпали название и тип аэродрома",), ("name", "type"))
    if compatible and same_settlement and street and street == candidate_street and house and house == candidate_house:
        return Decision("accepted", ("Совпали населённый пункт, улица, дом и тип",), ("address", "type"))
    if metres is not None and metres <= 100 and compatible and (same_name or same_core_name):
        return Decision("accepted", ("Совпали координаты, название и тип",), ("coordinates", "name", "type"))
    if compatible and same_name and (len(cues) >= 2 or bool(codes)):
        if any(words_present({cue}, text + " " + candidate_address) for cue in fine_local):
            return Decision("accepted", ("Совпали название, местоположение и тип",),
                            ("name", "location", "type"))

    # Core v17 fix: distinctive *two-word phrase* in a page title with the same
    # named object type is a strong match even if the user's card lacks address
    # and coordinates.  Only apply if no evidence of another place was found.
    if (compatible and len(cues) >= 2 and phrase_match
            and not (cues <= _COMMON_NAMES)
            and (not codes or numbered_match)):
        return Decision("accepted", ("Совпали отличительное составное название и тип объекта",),
                        ("name", "type"))

    # v19: one distinctive proper name (e.g. Доватор) + the same object type
    # may be enough when a dedicated Wikimapia/Urban3P object page names it.
    # The previous >=2-token requirement accidentally discarded such pages,
    # preventing their own galleries from even being requested. This exception
    # DOES NOT apply to general web results, catalogs, broad articles or common
    # camp names (Дружба, Волна...). All explicit contradictions were rejected
    # above, before we reach this branch.
    if (compatible and len(cues) == 1 and phrase_match
            and not (cues & _COMMON_NAMES)
            and _is_dedicated_catalog_object(key)
            and ("camp" in place_types and "camp" in source_types
                 or len(place_types & source_types) == 1)):
        return Decision(
            "accepted",
            ("Совпали отличительное название и тип на отдельной странице объекта; "
             "географическая привязка не подтверждена",),
            ("name", "type", "catalog_object", "geo_unverified"),
        )

    # Generic place names and title-only category matches are *not* identities.
    if not cues and compatible:
        micro = settlement_cues(place_address) - fine_local - {"москва"}
        if any(len(cue) >= 4 and words_present({cue}, title) for cue in micro):
            return Decision("accepted", ("Совпали тип объекта и микрорайон",),
                            ("location", "type"))
    context = contextual_match(place, {"title": title})
    if context:
        return Decision(
            "unconfirmed",
            ("Вероятно относится к объекту, но независимая геопривязка не подтверждена",),
            ("contextual_name_location", *context),
        )
    return Decision("unconfirmed", ("Недостаточно данных для привязки к конкретному объекту",),
                    tuple(k for k, yes in (("name", same_name), ("type", compatible)) if yes))


def catalog_gallery_matches(photo) -> bool:
    """Verify legacy Podmoskovnye estate photo directories by URL structure."""
    page = urlparse(str(photo.get("source_url") or ""))
    image = urlparse(str(photo.get("image_url") or ""))
    hosts = {"podmoskovnye.ru", "www.podmoskovnye.ru"}
    if (page.hostname not in hosts or image.hostname not in hosts
            or page.scheme not in {"http", "https"}
            or image.scheme not in {"http", "https"}):
        return False
    m = re.fullmatch(r"/usadba/[^/]+/\d+-([a-z-]+)/\d+-([a-z0-9-]+)", unquote(page.path).rstrip("/"))
    if not m:
        return False
    region, estate = m.groups()
    parts = unquote(image.path).split("/")
    return (len(estate) >= 4 and len(parts) == 7
            and parts[:6] == ["", "images", "stories", "photos", region, estate]
            and bool(re.fullmatch(r"[^/]+\.(?:jpe?g|png|webp)", parts[6], re.I)))



def _wikimapia_object_gallery_photo(photo: dict, parent: str) -> bool:
    """Recognize backend-extracted Wikimapia object photos, not search thumbnails.

    A search query is *not* a source URL; Wikimapia photos often have a human
    text query or no query at all. Instead require an already verified object
    page, a matching source_url and a Wikimapia-hosted photograph. We do not
    infer object identity from a CDN filename or from a gallery engine alone.
    """
    if photo.get("engine") != "wikimapia" or not parent.startswith("wikimapia.org:"):
        return False
    if source_key(photo.get("source_url")) != parent:
        return False

    scoped_key = str(photo.get("gallery_source_key") or "")
    if scoped_key and scoped_key != parent:
        return False
    # A URL-shaped query to a *different* Wikimapia object is conflicting
    # provenance. A normal SearXNG search string is not a URL and is ignored.
    query_key = source_key(photo.get("query"))
    if query_key.startswith("wikimapia.org:") and query_key != parent:
        return False

    try:
        image = urlparse(str(photo.get("image_url") or ""))
        if (image.scheme not in {"http", "https"}
                or image.hostname != "photos.wikimapia.org"
                or image.username or image.password):
            return False
    except (ValueError, TypeError):
        return False

    path = unquote(image.path)
    # Established Wikimapia photo-CDN path (including resized variants).
    canonical = bool(re.fullmatch(
        r"/p/(?:\d{2}/){4}\d{2}(?:_(?:\d+|big))?\.(?:jpe?g|png|webp)",
        path, re.IGNORECASE,
    ))
    # Newer parsers can provide explicit, same-object primary-gallery scope.
    scoped = (photo.get("gallery_scope") in {"primary", "object", "wikimapia_object"}
              and scoped_key == parent)
    return canonical or scoped


def primary_gallery(html, url):
    from .page_parser import parse_page
    _, scoped, images = parse_page(html, url, source_key)
    return scoped, images


def extract_page_identity(html, url):
    from .page_parser import parse_page
    from .wikimapia import enrich_identity
    identity, _, _ = parse_page(html, url, source_key)
    return enrich_identity(identity, html, url)


def diverse_photos(photos: list[dict], limit: int = 12) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for photo in photos:
        image_url = str(photo.get("image_url") or "")
        if not image_url or image_url in seen:
            continue
        seen.add(image_url)
        key = source_key(photo.get("source_url")) or str(photo.get("engine") or "")
        groups.setdefault(key, []).append(photo)
    result = []
    while len(result) < limit and any(groups.values()):
        for group in groups.values():
            if group and len(result) < limit:
                result.append(group.pop(0))
    return result


def verify_report(report, place, reference_urls, *, junk_source=lambda item: False,
                  junk_photo=lambda item: False):
    """Recalculate source and photo decisions from all available candidate evidence."""
    profile = build_place_profile(place, reference_urls=reference_urls)
    reference_urls = profile.reference_urls
    output = dict(report)
    prior = report.get("verification") or {}
    sources = list(report.get("items") or []) + list(report.get("source_candidates") or [])
    sources += [row["candidate"] for row in prior.get("sources", [])
                if isinstance(row.get("candidate"), dict)]
    photos = list(report.get("photos") or []) + list(report.get("photo_candidates") or [])
    photos += [row["candidate"] for row in prior.get("photos", [])
               if isinstance(row.get("candidate"), dict)]
    reference_keys = {source_key(url) for url in reference_urls} - {""}
    for photo in photos:
        photo_url = str(photo.get("source_url") or "")
        if not photo_url or photo_url == photo.get("image_url"):
            continue
        parent_key = source_key(photo_url)
        primary = photo.get("page_identity")
        verified_page_metadata = (isinstance(primary, dict)
                                  and primary.get("source_key") == parent_key
                                  and bool(primary.get("title") or primary.get("address")))
        # A photo's own caption/title is NOT evidence about its landing page.
        # Add the parent only when it was explicitly referenced by the place
        # card or when the parser extracted identity from that exact page.
        if parent_key in reference_keys or verified_page_metadata:
            sources.append({"url": photo_url,
                            "title": (primary or {}).get("title", "") if verified_page_metadata else "",
                            "snippet": "", "engine": photo.get("engine"),
                            "page_identity": primary if verified_page_metadata else None,
                            "query": ""})
    unique: dict[str, dict] = {}
    for item in sources:
        key = source_key(item.get("url"))
        if not key:
            continue
        if key not in unique:
            unique[key] = dict(item)
        else:
            # Prefer primary-page identity; never make search query evidence.
            for field in ("page_identity", "title", "snippet"):
                if item.get(field) and not unique[key].get(field):
                    unique[key][field] = item[field]
    decisions = {}
    audits = []
    accepted = []
    related = []
    for key, item in list(unique.items())[:60]:
        decision = verify_source(place, item, profile=profile)
        if junk_source(item) and "reference" not in decision.evidence:
            decision = Decision("rejected", ("Общая страница, служебный материал или неподходящий источник",))
        decisions[key] = decision
        audits.append({"candidate": item, **decision.json()})
        if decision.status == "accepted":
            accepted.append(item)
        elif decision.status == "unconfirmed" and "contextual_name_location" in decision.evidence:
            if len(related) < 20:
                related.append({
                    "url": item.get("url") or item.get("source_url") or "",
                    "title": item.get("title") or "",
                    "snippet": item.get("snippet") or "",
                    "status": "needs_geographic_confirmation",
                    "reason": decision.reasons[0],
                    "evidence": "; ".join(decision.evidence[1:]),
                    "relevance": "probable",
                })
    # Keep the highest-trust decision for each image. An earlier search-engine
    # thumbnail must not hide a later verified Wikimapia gallery record for the
    # *same image URL* (the old `seen` check silently discarded the latter).
    photo_choices: dict[str, dict] = {}
    reference_keys = {source_key(url) for url in reference_urls} - {""}
    gallery_engines = {"wikimapia", "geocache", "vk", "urban3p", "swalker", "web_page",
                       "planetadorog", "caves", "urbexstalker", "dzen", "yandex_maps", "youtube", "rutube"}
    trust_order = {"rejected": 0, "unconfirmed": 1, "accepted": 2}
    for photo in photos:
        image_url = str(photo.get("image_url") or "")
        if not image_url:
            continue
        if image_url not in photo_choices and len(photo_choices) >= 48:
            continue
        if (image_url in photo_choices
                and photo_choices[image_url]["status"] == "accepted"):
            continue
        parent = source_key(photo.get("source_url"))
        decision = decisions.get(parent, Decision("unconfirmed", ("Нет подтверждённой страницы источника",)))
        direct = source_key(image_url) in reference_keys
        wikimapia_gallery = _wikimapia_object_gallery_photo(photo, parent)
        if direct:
            decision = Decision("accepted", ("Прямая ссылка на фото из описания объекта",), ("reference_image",))
        elif decision.status == "accepted":
            gallery = photo.get("engine") in gallery_engines and source_key(photo.get("query")) == parent
            if photo.get("engine") == "yandex_maps" and photo.get("gallery_scope") == "organization":
                gallery = (photo.get("gallery_source_key") == parent and parent.startswith("yandex_maps:"))
            image_parts = urlparse(image_url)
            legacy_gallery = (
                photo.get("engine") == "geocache"
                and image_parts.hostname in {"geocaching.su", "www.geocaching.su"}
                and bool(re.fullmatch(r"/photos/areas/\d+\.(?:jpg|png|webp)", image_parts.path))
            ) or (
                photo.get("engine") == "wikimapia" and image_parts.hostname == "photos.wikimapia.org"
                and bool(re.fullmatch(r"/p/(?:\d{2}/){4}\d{2}(?:_(?:\d+|big))?\.jpg", image_parts.path))
            )
            gallery = gallery or wikimapia_gallery or (parent in reference_keys and legacy_gallery)
            if photo.get("engine") in {"web_page", "planetadorog", "caves", "urbexstalker"}:
                gallery = gallery and (photo.get("gallery_scope") == "primary" or catalog_gallery_matches(photo))
            if gallery:
                decision = Decision("accepted", ("Фото из галереи подтверждённого источника",), ("gallery", parent))
            else:
                decision = Decision("unconfirmed", ("Не подтверждено, что фото входит в галерею принятого источника",))
        # Accepted Wikimapia gallery has object-level provenance. Its caption
        # may contain generic anti-noise phrases (e.g. «в Москве»), so apply
        # junk filtering to URLs/media, as already done for explicit references.
        trusted_photo = (direct or
                         (decision.status == "accepted" and wikimapia_gallery))
        wiki_conflict = (photo.get("engine") == "wikimapia" and parent.startswith("wikimapia.org:")
                         and ((photo.get("gallery_source_key")
                               and photo.get("gallery_source_key") != parent)
                              or (source_key(photo.get("query")).startswith("wikimapia.org:")
                                  and source_key(photo.get("query")) != parent)))
        if wiki_conflict and not direct:
            decision = Decision("rejected", ("Галерея ссылается на другой объект Wikimapia",))
        junk_candidate = dict(photo, title="") if trusted_photo or parent in reference_keys else photo
        if junk_photo(junk_candidate):
            decision = Decision("rejected", ("Служебное или неподходящее изображение",))
        candidate = {"candidate": photo, **decision.json()}
        old = photo_choices.get(image_url)
        if old is None or trust_order[decision.status] > trust_order[old["status"]]:
            photo_choices[image_url] = candidate
    photo_audits = list(photo_choices.values())
    accepted_photos = [row["candidate"] for row in photo_audits if row["status"] == "accepted"]
    output.pop("source_candidates", None)
    output.pop("photo_candidates", None)
    output.update(items=accepted[:12], photos=diverse_photos(accepted_photos),
                  total=min(12, len(accepted)), photos_total=min(12, len(accepted_photos)),
                   related_sources=related, related_total=len(related),
                  verification={"version": VERSION, "sources": audits, "photos": photo_audits})
    return output
