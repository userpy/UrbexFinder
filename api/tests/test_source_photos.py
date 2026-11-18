import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from types import SimpleNamespace

from urbex.domain.rules import DomainError
from urbex.infrastructure import source_photos as sources
from urbex.presentation.http import router, context


def test_linked_cache_gallery_is_cached_without_search(monkeypatch):
    sources._cache.clear()
    photo = {'image_url': 'https://geocaching.su/photos/areas/123.jpg'}
    calls = []
    def fetch(links, **kwargs):
        calls.append(links)
        return [photo]
    monkeypatch.setattr(sources, 'generic_page_photos_for_links', fetch)
    place = {'description': 'Источник: https://geocaching.su/cache/18398 https://other.example/'}
    assert sources.source_photos(place) == [photo]
    assert sources.source_photos(place) == [photo]
    assert len(calls) == 1
    assert [link['url'] for link in calls[0]] == ['https://geocaching.su/cache/18398']


def test_missing_source_does_not_fetch_and_failure_has_short_cooldown(monkeypatch):
    sources._cache.clear()
    calls = []
    monkeypatch.setattr(sources, 'generic_page_photos_for_links', lambda *a, **k: calls.append(1) or [])
    assert sources.source_photos({'description': 'https://geocaching.su.evil.test/cache/18398'}) == []
    assert not calls
    for _ in range(2):
        with pytest.raises(DomainError) as exc:
            sources.source_photos({'description': 'https://geocaching.su/cache/18398'})
        assert exc.value.status == 502
    assert calls == [1]


def test_source_gallery_endpoint_checks_place_permissions_before_fetching():
    app = FastAPI()
    app.include_router(router)
    @app.exception_handler(DomainError)
    async def error(request, exc):
        return JSONResponse({'detail': exc.message}, status_code=exc.status)
    calls = []
    actor = object()
    def place(id, current_actor):
        assert current_actor is actor
        if id == 2:
            raise DomainError('Объект не найден', 404)
        return {'id': id}
    app.dependency_overrides[context] = lambda: (SimpleNamespace(places=SimpleNamespace(place=place)), None, actor)
    app.state.source_photos = lambda p: calls.append(p['id']) or [{'image_url': 'https://example.org/photo.jpg'}]
    with TestClient(app) as client:
        response = client.get('/api/places/1/source-photos')
        assert response.status_code == 200
        assert response.json()['total'] == 1
        assert client.get('/api/places/2/source-photos').status_code == 404
    assert calls == [1]


def test_saved_gallery_works_offline_and_excludes_other_caches(monkeypatch):
    monkeypatch.setattr(sources, 'generic_page_photos_for_links',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError('Network must not be needed')))
    photo = {'engine': 'geocache', 'source_url': 'https://geocaching.su/cache/18398',
             'image_url': 'https://geocaching.su/photos/areas/78302.jpg'}
    unrelated = dict(photo, source_url='https://geocaching.su/cache/123')
    wrong_host = dict(photo, image_url='https://unrelated.example/photo.jpg')
    report = {'photos': [unrelated, wrong_host, photo, photo]}
    assert sources.source_photos({'description': photo['source_url']}, report) == [photo]


def test_urban_description_gallery_and_saved_report(monkeypatch):
    sources._cache.clear()
    place = {'description': 'https://urban3p.com/object42/gallery', 'name': 'Завод'}
    photo = {'engine': 'urban3p', 'source_url': 'https://urban3p.ru/object42',
             'query': 'https://urban3p.ru/object42', 'title': 'Школа',
             'image_url': 'https://img01.urban3p.ru/up/o/42/gallery/123.jpg'}
    calls = []
    monkeypatch.setattr(sources, 'urban3p_photos_for_links', lambda links, limit: calls.append(links) or [photo])
    assert sources.source_photos(place) == [photo]
    assert sources.source_photos(place) == [photo]
    assert len(calls) == 1
    sources._cache.clear()
    assert sources.source_photos(place, {'photos': [photo]}) == [photo]
    assert len(calls) == 1


def test_wikimapia_description_gallery_is_loaded_and_verified(monkeypatch):
    sources._cache.clear()
    url = 'https://wikimapia.org/37454702/ru/Бывший-магазин'
    identity = {
        'source_key': sources.source_key(url),
        'title': 'Бывший магазин',
        'latitude': 53.095835,
        'longitude': 34.071292,
    }
    photo = {
        'engine': 'wikimapia',
        'source_url': url,
        'query': url,
        'page_identity': identity,
        'image_url': 'https://photos.wikimapia.org/p/00/01/02/03/04_1280.jpg',
    }
    calls = []

    def fetch(links, limit):
        calls.append((links, limit))
        return [photo]

    monkeypatch.setattr(sources, 'wikimapia_photos_for_links', fetch)
    place = {
        'name': 'Бывший магазин (ru)',
        'region': 'Брянская область',
        'latitude': 53.095835,
        'longitude': 34.071292,
        'description': url,
    }

    assert sources.source_photos(place) == [photo]
    assert sources.source_photos(place) == [photo]
    assert len(calls) == 1
    assert calls[0][0][0]['url'] == url
    assert calls[0][1] == 12


def test_vk_group_gallery_fetches_with_token_and_reuses_verified_saved_photos(monkeypatch):
    sources._cache.clear()
    url = 'https://vk.com/club42'
    photo = {'engine': 'vk', 'source_url': url, 'query': url,
             'image_url': 'https://sun9.userapi.com/factory.jpg'}
    calls = []
    def fetch(token, links, limit):
        calls.append((token, links[0]['url']))
        return [photo]
    monkeypatch.setattr(sources, 'vk_photos_for_links', fetch)
    monkeypatch.setattr(sources, 'generic_page_photos_for_links',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError('Use VK parser')))
    place = {'name': 'Завод', 'description': url}
    assert sources.source_photos(place, vk_token='token') == [photo]
    assert sources.source_photos(place, vk_token='token') == [photo]
    sources._cache.clear()
    assert sources.source_photos(place, {'photos': [photo]}, vk_token='token') == [photo]
    assert calls == [('token', url)]


def test_verified_search_galleries_share_budget_with_description_photos():
    urban = 'https://urban3p.ru/object42'
    wiki = 'https://wikimapia.org/123/ru/radar'
    place = {'name': 'Дунай', 'description': 'РЛС https://urban3p.ru/object42',
             'latitude': 55.48, 'longitude': 36.64}
    identity = {'source_key': sources.source_key(wiki), 'title': 'РЛС Дунай',
                'latitude': 55.48, 'longitude': 36.64}
    urban_photos = [dict(engine='urban3p', source_url=urban, query=urban,
                        image_url=f'https://img01.urban3p.ru/up/o/42/gallery/{i}.jpg') for i in range(12)]
    other = dict(engine='wikimapia', source_url=wiki, query=wiki, page_identity=identity,
                 image_url='https://photos.wikimapia.org/p/00/01/02/03/04.jpg')
    wrong = dict(other, image_url='https://photos.wikimapia.org/p/00/01/02/03/05.jpg',
                 source_url='https://wikimapia.org/999', query='https://wikimapia.org/999', page_identity={})
    result = sources.source_photos(place, {'photos': urban_photos + [other, wrong]})
    assert len(result) == 12
    assert result[1] == other
    assert wrong not in result
