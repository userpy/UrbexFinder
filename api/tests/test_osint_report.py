import httpx
from fastapi.testclient import TestClient
from conftest import register, PLACE
from test_elasticsearch import insert
from urbex.infrastructure import osint
from urbex.infrastructure.osint_assess import assess_osint_items


def test_osint_assessment_security_and_condition_signals():
    assessment = assess_osint_items([
        {
            'title': 'Заброшенная фабрика под охраной ЧОП',
            'snippet': 'Территория с видеонаблюдением, вход через КПП.',
            'url': 'https://example.org/guarded',
        },
        {
            'title': 'Репортаж: руины цеха',
            'snippet': 'Частично разрушенный корпус, обрушилась крыша.',
            'url': 'https://example.org/ruins',
        },
    ])
    assert assessment['security']['level'] == 'high'
    assert assessment['security']['label'] == 'Высокая'
    assert assessment['condition']['level'] == 'abandoned'
    assert assessment['condition']['label'] == 'Заброшен'
    assert assessment['security']['signals']
    assert assessment['condition']['signals']
    assert 'эвристика' in assessment['disclaimer'].casefold()

    active = assess_osint_items([
        {
            'title': 'Музей работает',
            'snippet': 'Объект действует и открыт для посещения.',
            'url': 'https://example.org/active',
        },
    ])
    assert active['condition']['level'] == 'active'
    assert active['condition']['label'] == 'Действует'

    empty = assess_osint_items([
        {'title': 'Каталог адресов', 'snippet': 'Список улиц района', 'url': 'https://example.org/x'},
    ])
    assert empty['security']['level'] == 'unknown'
    assert empty['condition']['level'] == 'unknown'


def test_osint_queries_cover_name_address_and_coordinates():
    queries = osint._queries_for({
        'name': 'Усадьба Липки',
        'full_address': 'Владимирская область, Александров',
        'region': 'Владимирская область',
        'latitude': 56.4,
        'longitude': 38.72,
    })
    assert queries == [
        'Усадьба Липки',
        'Усадьба Липки 56.40000, 38.72000',
    ]
    assert osint._queries_for({'name': 'Только имя'}) == ['Только имя']
    assert osint._queries_for({
        'region': 'Москва', 'latitude': 55.75, 'longitude': 37.62,
    }) == ['55.75000, 37.62000', 'Москва']
    # Long address/region is skipped; coordinates take the second slot.
    assert osint._queries_for({
        'name': 'Лагерь',
        'region': 'СНТ "Краснофлотский", городской округ Щёлково, Московская область, Центральный федеральный округ, Россия',
        'full_address': 'СНТ "Краснофлотский", городской округ Щёлково, Московская область, Центральный федеральный округ, Россия',
        'latitude': 55.9,
        'longitude': 38.0,
    }) == ['Лагерь', 'Лагерь 55.90000, 38.00000']
    assert osint._queries_for({
        'name': 'Лагерь',
        'region': 'Московская область',
        'latitude': 55.9,
        'longitude': 38.0,
    }) == ['Лагерь', 'Лагерь 55.90000, 38.00000']

    image_queries = osint._image_queries_for({
        'name': 'Карьер',
        'region': 'Московская область',
        'latitude': 55.87326,
        'longitude': 37.38085,
    })
    assert image_queries == [
        'Карьер Московская область',
        'Карьер 55.87326, 37.38085',
    ]
    assert osint._image_queries_for({
        'name': 'Карьер', 'latitude': 55.87, 'longitude': 37.38,
    }) == ['Карьер', 'Карьер 55.87000, 37.38000']


def test_osint_report_public_config_and_searxng_results(client, monkeypatch):
    place_id = insert(client.app, 'Усадьба Липки')
    url = f'/api/places/{place_id}/osint-report'

    monkeypatch.setattr(client.app.state.config, 'searxng_url', '')
    assert client.get(url).status_code == 503

    osint.clear_search_cache()
    monkeypatch.setattr(client.app.state.config, 'searxng_url', 'https://xng.example')
    calls = []

    def handler(request: httpx.Request):
        calls.append(str(request.url))
        assert request.url.params.get('format') == 'json'
        category = request.url.params.get('categories')
        engines = request.url.params.get('engines') or ''
        if category == 'images':
            assert 'bing images' in engines
        else:
            assert 'bing' in engines
        if category == 'images':
            return httpx.Response(200, json={
                'results': [
                    {
                        'title': 'Усадьба Липки зимой',
                        'url': 'https://example.org/photo-page',
                        'img_src': 'https://cdn.example.org/lipki.jpg',
                        'thumbnail_src': 'https://cdn.example.org/lipki-thumb.jpg',
                        'engine': 'duckduckgo images',
                        'score': 3.1,
                    },
                    {
                        'title': 'Дубликат фото',
                        'url': 'https://example.org/other',
                        'img_src': 'https://cdn.example.org/lipki.jpg',
                        'thumbnail_src': 'https://cdn.example.org/lipki-thumb.jpg',
                        'engine': 'bing images',
                        'score': 1.0,
                    },
                    {
                        'title': 'Без изображения',
                        'url': 'https://example.org/no-image',
                        'img_src': '',
                    },
                ],
            })
        return httpx.Response(200, json={
            'results': [
                {
                    'title': 'Усадьба Липки — заброшенная история',
                    'url': 'https://example.org/lipki',
                    'content': 'Заброшенный объект без охраны, свободный вход.',
                    'engine': 'duckduckgo',
                    'category': 'general',
                    'score': 4.2,
                },
                {
                    'title': 'Дубликат',
                    'url': 'https://example.org/lipki/',
                    'content': 'Тот же URL с слэшем.',
                    'engine': 'bing',
                    'score': 1.0,
                },
                {
                    'title': 'Без ссылки',
                    'url': '',
                    'content': 'Пропуск',
                },
            ],
        })

    transport = httpx.MockTransport(handler)
    original = httpx.Client
    monkeypatch.setattr(
        osint.httpx,
        'get',
        lambda *args, **kwargs: original(transport=transport).get(*args, **kwargs),
    )

    result = client.get(url)
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload['place_id'] == place_id
    assert payload['source'] == 'searxng'
    assert payload['total'] == 1
    assert payload['items'][0]['title'] == 'Усадьба Липки — заброшенная история'
    assert payload['items'][0]['url'] == 'https://example.org/lipki'
    assert payload['queries'][0] == 'Усадьба Липки'
    assert any('Владимирская' in query or 'Александров' in query or 'Москва' in query for query in payload['queries']) or len(payload['queries']) >= 1
    assert payload['assessment']['security']['level'] == 'low'
    assert payload['assessment']['security']['label'] == 'Низкая'
    assert payload['assessment']['condition']['level'] == 'abandoned'
    assert payload['assessment']['condition']['label'] == 'Заброшен'
    assert payload['photos_total'] == 1
    assert payload['photos'][0]['title'] == 'Усадьба Липки зимой'
    assert payload['photos'][0]['image_url'] == 'https://cdn.example.org/lipki.jpg'
    assert payload['photos'][0]['source_url'] == 'https://example.org/photo-page'
    assert any('categories=images' in call for call in calls)
    assert any('categories=general' in call for call in calls)
    assert calls

    osint.clear_search_cache()
    monkeypatch.setattr(
        osint.httpx,
        'get',
        lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError('down')),
    )
    assert client.get(url).status_code == 502


def test_osint_report_keeps_sources_when_images_fail(client, monkeypatch):
    place_id = insert(client.app, 'Усадьба Липки')
    url = f'/api/places/{place_id}/osint-report'
    osint.clear_search_cache()
    monkeypatch.setattr(client.app.state.config, 'searxng_url', 'https://xng.example')

    def handler(request: httpx.Request):
        if request.url.params.get('categories') == 'images':
            raise httpx.ConnectTimeout('images down')
        return httpx.Response(200, json={
            'results': [{
                'title': 'Усадьба Липки — заброшенная история',
                'url': 'https://example.org/lipki',
                'content': 'Заброшенный объект без охраны.',
                'score': 2.0,
            }],
        })

    transport = httpx.MockTransport(handler)
    original = httpx.Client
    monkeypatch.setattr(
        osint.httpx,
        'get',
        lambda *args, **kwargs: original(transport=transport).get(*args, **kwargs),
    )
    result = client.get(url)
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload['total'] >= 1
    assert payload['photos_total'] == 0
    assert payload['photos'] == []


def test_osint_report_keeps_photos_when_general_fails(client, monkeypatch):
    place_id = insert(client.app, 'Усадьба Липки')
    url = f'/api/places/{place_id}/osint-report'
    osint.clear_search_cache()
    monkeypatch.setattr(client.app.state.config, 'searxng_url', 'https://xng.example')

    def handler(request: httpx.Request):
        if request.url.params.get('categories') == 'images':
            return httpx.Response(200, json={
                'results': [{
                    'title': 'Фото усадьбы',
                    'url': 'https://example.org/photo-page',
                    'img_src': 'https://cdn.example.org/photo.jpg',
                    'thumbnail_src': 'https://cdn.example.org/thumb.jpg',
                    'score': 2.5,
                }],
            })
        raise httpx.ReadTimeout('general down')

    transport = httpx.MockTransport(handler)
    original = httpx.Client
    monkeypatch.setattr(
        osint.httpx,
        'get',
        lambda *args, **kwargs: original(transport=transport).get(*args, **kwargs),
    )
    result = client.get(url)
    assert result.status_code == 200, result.text
    payload = result.json()
    # Photo landing pages are promoted into sources when general search is empty.
    assert payload['photos_total'] == 1
    assert payload['total'] == 1
    assert payload['items'][0]['url'] == 'https://example.org/photo-page'
    assert payload['photos'][0]['source_url'] == 'https://example.org/photo-page'


def test_osint_report_hides_pending_from_strangers(client, monkeypatch):
    register(client)
    pending = client.post('/api/places', json=PLACE).json()['id']
    monkeypatch.setattr(
        client.app.state,
        'osint_report',
        lambda place: {'place_id': place['id'], 'items': [], 'total': 0, 'queries': [], 'source': 'searxng'},
    )
    assert client.get(f'/api/places/{pending}/osint-report').status_code == 200

    stranger = TestClient(client.app, base_url='http://localhost:3100', headers={'Origin': 'http://localhost:3100'})
    assert stranger.get(f'/api/places/{pending}/osint-report').status_code == 404
    register(stranger, 'stranger@example.com')
    assert stranger.get(f'/api/places/{pending}/osint-report').status_code == 404
