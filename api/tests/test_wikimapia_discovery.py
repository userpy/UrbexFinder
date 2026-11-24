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
def reset_cache(monkeypatch):
    discovery._cache.clear()
    monkeypatch.setattr(discovery, 'nearby_places', lambda place: [])
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
    attempts = len(discovery._search_queries(PLACE))
    assert calls == [1] * attempts
    now[0] += 31
    assert discovery.discover_photos(PLACE, 'http://search', '') == [photo()]
    assert calls == [1] * (attempts + 1)


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


def test_fallback_search_uses_name_and_coordinates_without_changing_description(monkeypatch):
    searches = []
    def search(url, origin, query):
        searches.append(query)
        return [] if len(searches) == 1 else [{'url': URL, 'title': 'Сатурн…'}]
    monkeypatch.setattr(discovery, '_search', search)
    fetched = []
    monkeypatch.setattr(discovery, 'wikimapia_photos_for_links',
                        lambda links, limit: fetched.extend(links) or [photo()])
    place = deepcopy(PLACE)
    assert source_photos(place, search_url='http://search') == [photo()]
    assert place == PLACE
    assert len(searches) == 2
    assert '55.65639 38.13306' in searches[1]
    assert len(fetched) == 1


def test_search_title_need_not_contain_every_word_when_page_confirms_identity(monkeypatch):
    monkeypatch.setattr(discovery, '_search', lambda *a: [{'url': URL, 'title': '- Wikimapia'}])
    monkeypatch.setattr(discovery, 'wikimapia_photos_for_links', lambda *a: [photo()])
    assert discovery.discover_photos(PLACE, 'http://search', '') == [photo()]


def test_simplified_name_is_verified_against_page_and_coordinates(monkeypatch):
    place = dict(PLACE, name='Полузаброшенный узел связи', category='разное')
    image = photo(title='Узел связи')
    queries = []
    def search(url, origin, query):
        queries.append(query)
        return [] if 'Полузаброшенный' in query else [{'url': URL, 'title': 'Узел связи'}]
    monkeypatch.setattr(discovery, '_search', search)
    monkeypatch.setattr(discovery, 'wikimapia_photos_for_links', lambda *a: [image])
    assert discovery.discover_photos(place, 'http://search', '') == [image]
    assert any('узел связи' in q and 'Полузаброшенный' not in q for q in queries)


def test_failed_search_does_not_prevent_successful_fallback(monkeypatch):
    calls = []
    def search(*args):
        calls.append(args)
        if len(calls) == 1:
            raise DomainError('Temporarily unavailable', 502)
        return [{'url': URL, 'title': PLACE['name']}]
    monkeypatch.setattr(discovery, '_search', search)
    monkeypatch.setattr(discovery, 'wikimapia_photos_for_links', lambda *a: [photo()])
    assert discovery.discover_photos(PLACE, 'http://search', '') == [photo()]
    assert len(calls) == 2


def test_page_fetches_are_bounded_across_fallback_queries(monkeypatch):
    calls = []
    def search(*args):
        return [{'url': f'https://wikimapia.org/{i}', 'title': PLACE['name']}
                for i in range(100, 200)]
    def fetch(links, limit):
        calls.append(links[0]['url'])
        return [photo(links[0]['url'], latitude=54, longitude=30)]
    monkeypatch.setattr(discovery, '_search', search)
    monkeypatch.setattr(discovery, 'wikimapia_photos_for_links', fetch)
    assert discovery.discover_photos(PLACE, 'http://search', '') == []
    assert len(calls) <= 8
    assert len(calls) == len(set(calls))


@pytest.mark.parametrize('search_url', ['', 'http://search'])
def test_map_finds_gallery_by_name_and_coordinates_when_page_metadata_is_broken(monkeypatch, search_url):
    place = dict(PLACE, name='Полузаброшенный узел связи у РТЦ С-25', category='разное')
    title = 'Заброшенный радиотехнический центр зенитного ракетного комплекса С-25'
    row = dict(photo()['page_identity'], url=URL, title=title)
    broken = photo(title=' ', latitude=None, longitude=None)
    monkeypatch.setattr(discovery, 'nearby_places', lambda p: [row])
    monkeypatch.setattr(discovery, '_search', lambda *a: pytest.fail('Map match needs no web search'))
    monkeypatch.setattr(discovery, 'wikimapia_photos_for_links', lambda *a: [broken])
    original = deepcopy(place)
    result = source_photos(place, search_url=search_url)
    assert place == original
    assert len(result) == 1
    assert result[0]['image_url'] == broken['image_url']
    assert result[0]['page_identity']['title'] == title
    assert result[0]['match_method'] == 'name_coordinates'


@pytest.mark.parametrize('changes', [
    {'latitude': 54, 'longitude': 30}, {'title': 'Завод «Сатурн»'},
    {'latitude': 54, 'longitude': None},
    {'source_key': 'wikimapia.org:999'},
])
def test_map_metadata_never_overwrites_conflicting_page_evidence(monkeypatch, changes):
    row = dict(photo()['page_identity'], url=URL)
    monkeypatch.setattr(discovery, 'nearby_places', lambda p: [row])
    monkeypatch.setattr(discovery, '_search', lambda *a: [])
    monkeypatch.setattr(discovery, 'wikimapia_photos_for_links', lambda *a: [photo(**changes)])
    assert discovery.discover_photos(PLACE, 'http://search', '') == []
