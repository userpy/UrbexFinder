from copy import deepcopy

import pytest

from urbex.domain.rules import DomainError
from urbex.infrastructure import wikimapia_discovery as discovery
from urbex.infrastructure.source_photos import source_photos


PLACE = {
    'id': 730, 'name': 'Детский оздоровительный лагерь «Сатурн»',
    'description': None, 'latitude': 55.656389, 'longitude': 38.133056,
    'full_address': 'Капустино, Московская область',
    'category': 'Заброшенные пионерские лагеря',
}
URL = 'https://wikimapia.org/9686676/ru/'


def photo(url=URL, **identity):
    return {
        'engine': 'wikimapia', 'source_url': url, 'query': url,
        'image_url': 'https://photos.wikimapia.org/p/00/02/23/70/06_big.jpg',
        'page_identity': {
            'source_key': discovery.source_key(url), 'title': PLACE['name'],
            'latitude': 55.6565614, 'longitude': 38.1333008, **identity,
        },
    }


@pytest.fixture(autouse=True)
def reset_cache():
    discovery._cache.clear()
    yield
    discovery._cache.clear()


def test_card_without_description_or_report_discovers_gallery_and_keeps_description(monkeypatch):
    searches, galleries = [], []
    def search(url, origin, query):
        searches.append((url, origin, query))
        return [{'url': URL, 'title': PLACE['name']}]
    monkeypatch.setattr(discovery, '_search', search)
    monkeypatch.setattr(discovery, 'wikimapia_photos_for_links',
                        lambda links, limit: galleries.append(links) or [photo()])
    place = deepcopy(PLACE)
    for _ in range(2):
        assert source_photos(place, search_url='http://search', origin='http://app') == [photo()]
    assert place == PLACE
    assert len(searches) == len(galleries) == 1
    assert searches[0][:2] == ('http://search', 'http://app')
    assert 'site:wikimapia.org' in searches[0][2]
    assert 'Капустино' in searches[0][2]


def test_distant_namesake_is_skipped_and_later_nearby_object_is_used(monkeypatch):
    distant = 'https://wikimapia.org/10477858/ru/'
    monkeypatch.setattr(discovery, '_search', lambda *a: [
        {'url': distant, 'title': PLACE['name']},
        {'url': URL, 'title': PLACE['name']},
    ])
    monkeypatch.setattr(discovery, 'wikimapia_photos_for_links', lambda links, limit: [
        photo(distant, latitude=54.8, longitude=39.8) if links[0]['url'] == distant else photo(),
    ])
    assert discovery.discover_photos(PLACE, 'http://search', '') == [photo()]


@pytest.mark.parametrize('identity', [
    {'latitude': None},
    {'source_key': 'wikimapia.org:999'},
    {'latitude': 55.658258, 'longitude': 38.131464},  # neighbouring camp
    {'title': 'Пионерский лагерь имени Лени Голикова'},
    {'title': 'Завод «Сатурн»'},
])
def test_search_title_cannot_override_primary_page_identity(monkeypatch, identity):
    monkeypatch.setattr(discovery, '_search', lambda *a: [{'url': URL, 'title': PLACE['name']}])
    monkeypatch.setattr(discovery, 'wikimapia_photos_for_links', lambda *a: [photo(**identity)])
    assert discovery.discover_photos(PLACE, 'http://search', '') == []


def test_unrelated_hosts_and_map_pages_are_not_fetched(monkeypatch):
    monkeypatch.setattr(discovery, '_search', lambda *a: [
        {'url': url, 'title': PLACE['name']} for url in (
            'https://wikimapia.org.evil.test/9686676',
            'https://wikimapia.org/street/9686676', 'https://example.com/camp',
        )
    ])
    monkeypatch.setattr(discovery, 'wikimapia_photos_for_links',
                        lambda *a: pytest.fail('Non-object page fetched'))
    assert discovery.discover_photos(PLACE, 'http://search', '') == []


@pytest.mark.parametrize('search_failure', [True, False])
def test_transient_search_or_gallery_failure_retries_after_short_cooldown(monkeypatch, search_failure):
    now = [100]
    calls = []
    monkeypatch.setattr(discovery, 'monotonic', lambda: now[0])
    def search(*args):
        calls.append(1)
        if search_failure and now[0] == 100:
            raise DomainError('Search unavailable', 502)
        return [{'url': URL, 'title': PLACE['name']}]
    monkeypatch.setattr(discovery, '_search', search)
    monkeypatch.setattr(discovery, 'wikimapia_photos_for_links',
                        lambda *a: [] if now[0] == 100 else [photo()])
    for _ in range(2):
        with pytest.raises(DomainError) as exc:
            discovery.discover_photos(PLACE, 'http://search', '')
        assert exc.value.status == 502
    assert calls == [1]
    now[0] += 31
    assert discovery.discover_photos(PLACE, 'http://search', '') == [photo()]
    assert calls == [1, 1]


def test_cached_photos_are_not_reused_after_coordinates_change(monkeypatch):
    monkeypatch.setattr(discovery, '_search', lambda *a: [{'url': URL, 'title': PLACE['name']}])
    monkeypatch.setattr(discovery, 'wikimapia_photos_for_links', lambda *a: [photo()])
    assert discovery.discover_photos(PLACE, 'http://search', '') == [photo()]
    assert discovery.discover_photos(dict(PLACE, latitude=56), 'http://search', '') == []


def test_no_search_without_configuration_name_or_coordinates(monkeypatch):
    monkeypatch.setattr(discovery, '_search', lambda *a: pytest.fail('Unexpected search'))
    assert discovery.discover_photos(PLACE, '', '') == []
    assert discovery.discover_photos(dict(PLACE, name=''), 'http://search', '') == []
    assert discovery.discover_photos(dict(PLACE, latitude=None), 'http://search', '') == []
