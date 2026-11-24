from collections import OrderedDict
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from urbex.infrastructure import osint, osint_description, osint_evidence
from urbex.infrastructure.osint_identity import source_key, verify_source
from urbex.infrastructure.osint_profile import build_place_profile
from urbex.infrastructure.semantic_ranking import _place_text


PLACE = {
    'name': 'Завод Северный ветер',
    'aliases': ['Завод Полярная звезда'],
    'full_address': 'улица Ленина, дом 5, город Истра, Московская область',
    'latitude': 55.9, 'longitude': 36.8,
}


def candidate(title='Завод Полярная звезда', **identity):
    url = 'https://yandex.ru/maps/org/factory/123/'
    return {'url': url, 'title': title, 'page_identity': {
        'source_key': source_key(url), 'title': title,
        'latitude': 55.9, 'longitude': 36.8, **identity,
    }}


def test_same_explicit_alias_reaches_search_ranking_and_verification():
    queries = osint.generate_osint_queries(PLACE)
    assert any(q.strategy == 'alias' and 'Завод Полярная звезда' in q.query for q in queries)
    assert 'Завод Полярная звезда' in _place_text(PLACE)
    assert verify_source(PLACE, candidate()).status == 'accepted'


@pytest.mark.parametrize('identity', [
    {'latitude': 56.1},
    {'address': 'Тверская область'},
    {'address': 'улица Ленина, дом 15, город Истра, Московская область'},
    {'address': 'улица Мира, дом 5, город Истра, Московская область'},
])
def test_alias_cannot_override_geographic_conflicts(identity):
    assert verify_source(PLACE, candidate(**identity)).status == 'rejected'


def test_alias_cannot_override_primary_type_or_number():
    place = dict(PLACE, aliases=['Лагерь Полярная звезда'])
    assert verify_source(place, candidate('Лагерь Полярная звезда')).status == 'rejected'
    place = dict(PLACE, name='СПТУ-23', aliases=['СПТУ-230'])
    assert verify_source(place, candidate('СПТУ-230')).status == 'rejected'


def test_profile_keeps_identity_and_search_hypotheses_separate():
    place = {'name': 'Заброшенный лагерь «Орбита» завода Янтарь'}
    profile = build_place_profile(place)
    assert 'Орбита' in profile.search_aliases
    assert 'Орбита' not in profile.identity_names
    assert verify_source(place, candidate('Лагерь Орбита')).status == 'unconfirmed'


def test_geographic_suffix_requires_card_evidence_and_preserves_proper_names():
    name = 'Церковь Спаса Нерукотворного образа. Пушкино (Клязьма)'
    place = {'name': name, 'full_address': 'микрорайон Клязьма, Пушкино, Московская область'}
    profile = build_place_profile(place)
    assert profile.identity_names == ('Церковь Спаса Нерукотворного образа',)
    assert {'пушкино', 'клязьма'} <= profile.localities
    assert profile.settlement == 'Пушкино'
    assert profile.region == 'Московская область'
    assert build_place_profile({'name': name}).identity_names == (name,)
    assert build_place_profile({
        'name': 'Усадьба Липки', 'full_address': 'деревня Липки, Московская область',
    }).identity_names == ('Усадьба Липки',)


def test_profile_merges_alias_formats_without_changing_card_or_identity_length():
    place = dict(PLACE, aliases=['Завод Ёлочка', None, 5],
                 alternative_names='["Завод Елочка", "Завод Полярная звезда"]',
                 alternate_names='Завод Северный ветер; Завод Южный ветер\nнет')
    original = deepcopy(place)
    references = ['https://example.org/one', 'https://example.org/one']
    profile = build_place_profile(place, reference_urls=references)
    assert profile.aliases == ('Завод Ёлочка', 'Завод Полярная звезда', 'Завод Южный ветер')
    assert profile.street == 'ленина' and profile.house == '5'
    assert profile.reference_urls == ('https://example.org/one',)
    assert place == original
    place['aliases'].append('Новое имя')
    assert 'Новое имя' not in profile.aliases
    with pytest.raises(FrozenInstanceError):
        profile.name = 'Изменение'

    name = 'Завод ' + 'Длинное название ' * 12 + '№ 123'
    profile = build_place_profile({'name': name})
    assert profile.identity_names == (name,)
    assert len(profile.search_name) <= 110


@pytest.mark.parametrize('point', [(None, 37), ('bad', 37), (float('nan'), 37),
                                   (55, float('inf')), (91, 37), (0, 0)])
def test_invalid_coordinates_are_consistent_across_search_and_verification(point):
    place = dict(PLACE, latitude=point[0], longitude=point[1])
    profile = build_place_profile(place)
    assert profile.point is None
    assert profile.coordinate_query == ''
    assert not any(q.strategy == 'coordinates' for q in osint.generate_osint_queries(place, max_queries=20))


def test_address_fallback_and_empty_card():
    place = {'name': 'Завод', 'address': 'город Истра, Московская область'}
    profile = build_place_profile(place)
    assert profile.settlement == 'Истра'
    assert profile.region == 'Московская область'
    assert osint.generate_osint_queries({}) == []
    assert verify_source({}, candidate()).status == 'unconfirmed'


def test_alias_is_used_when_prioritizing_primary_page_fetches(monkeypatch):
    fetched = []
    monkeypatch.setattr(osint_evidence, '_fetch', lambda url: fetched.append(url))
    rows = [{'url': f'https://wikimapia.org/{i}', 'title': 'Чужой объект'} for i in range(4)]
    rows.append({'url': 'https://wikimapia.org/99', 'title': 'Полярная звезда'})
    osint_evidence.enrich_candidates(PLACE, rows, [])
    assert 'https://wikimapia.org/99' in fetched
    assert len(fetched) == 4


def test_yandex_discovery_uses_card_alias_before_fetching_gallery(monkeypatch):
    page = ('<div data-id="123"><div class="search-business-snippet-view__title">'
            'Завод Полярная звезда</div><a href="/maps/org/factory/123/"></a></div>')
    monkeypatch.setattr(osint_description, '_fetch_ymaps_html', lambda url: page)
    calls = []
    monkeypatch.setattr(osint_description, '_ymaps_photos_from_org',
                        lambda slug, oid, **kw: calls.append(oid) or [])
    osint_description.yandex_maps_photos_for_place(PLACE)
    assert calls == ['123']


def test_cached_candidate_is_rechecked_when_aliases_change():
    place = dict(PLACE, aliases=[])
    source = candidate()
    cached = osint._refilter_report({'items': [source]}, place)
    assert cached['confirmed_total'] == 0
    updated = osint._refilter_report(cached, PLACE)
    assert updated['confirmed_total'] == 1
    assert osint._refilter_report(updated, place)['confirmed_total'] == 0


def test_wikimapia_queries_and_cache_follow_profile_changes(monkeypatch):
    from urbex.infrastructure import wikimapia_discovery as discovery

    monkeypatch.setattr(discovery, '_cache', OrderedDict())
    calls = []
    monkeypatch.setattr(discovery, '_discover', lambda place, *a: calls.append(place) or [])
    assert any('Завод Полярная звезда' in q for q in discovery._search_queries(PLACE))
    discovery.discover_photos(PLACE, 'http://search', '')
    discovery.discover_photos(PLACE, 'http://search', '')
    discovery.discover_photos(dict(PLACE, aliases=[]), 'http://search', '')
    assert len(calls) == 2
