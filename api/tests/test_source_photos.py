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
