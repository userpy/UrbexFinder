from sqlalchemy import text
from fastapi.testclient import TestClient
from conftest import register, PLACE


def insert(app, name, description='Историческое место', **extra):
    values = dict(name=name, description=description, status='published', latitude=55.75, longitude=37.62, category_id=1, **extra)
    with app.state.engine.begin() as c:
        return c.scalar(text('INSERT INTO places(name,description,status,latitude,longitude,category_id) VALUES (:name,:description,:status,:latitude,:longitude,:category_id) RETURNING id'), values)


def test_morphology_typos_relevance_and_live_changes(client):
    first = insert(client.app, 'Усадьба Липки')
    second = insert(client.app, 'Старая фабрика', 'Поблизости находится усадьба Липки')
    response = client.get('/api/places', params={'q':'усадьбе'})
    assert response.status_code == 200, response.text
    assert response.json()['items'][0]['id'] == first
    assert client.get('/api/places', params={'q':'фабрка'}).json()['items'][0]['id'] == second
    assert client.get('/api/places', params={'q':'усадьбе','bbox':'10,10,11,11'}).json()['total'] == 0
    with client.app.state.engine.begin() as c:
        c.execute(text("UPDATE places SET name='Водонапорная башня',description='Памятник' WHERE id=:id"), {'id': first})
    assert client.get('/api/places', params={'q':'усадьба'}).json()['total'] == 1
    assert client.get('/api/places', params={'q':'водонапорная'}).json()['items'][0]['id'] == first
    with client.app.state.engine.begin() as c:
        c.execute(text('DELETE FROM places WHERE id=:id'), {'id': first})
    assert client.get('/api/places', params={'q':'водонапорная'}).json()['total'] == 0


def test_stale_index_cannot_expose_pending_or_report_hidden_places(client, moderator, monkeypatch):
    register(client)
    pending = client.post('/api/places', json=PLACE).json()['id']
    public = insert(client.app, 'Старая фабрика')
    client.app.state.search.sync()
    with client.app.state.search.client() as es:
        response = es.put(f'/{client.app.state.search.index}/_doc/{pending}', params={'refresh':'true'}, json={'id':pending,'name':PLACE['name']})
        assert response.is_success
    with client.app.state.engine.begin() as c:
        c.execute(text('UPDATE places SET nonexistent_reports_count=10 WHERE id=:id'), {'id': public})
    # Deliberately leave both stale hits in ES. DB visibility must still win.
    monkeypatch.setattr(client.app.state.search, 'sync', lambda: 0)
    guest = TestClient(client.app)
    assert guest.get('/api/places?q=фабрика').json()['total'] == 0
    assert guest.get('/api/map?q=фабрика&bbox=37,55,38,56').json()['total'] == 0


def test_more_than_10000_matches_have_complete_map_and_pagination(client):
    with client.app.state.engine.begin() as c:
        c.execute(text("""INSERT INTO places(name,description,latitude,longitude,category_id,status)
            SELECT 'Башня водонапорная '||n, 'Контроль полной выдачи', 55.75+n*0.000001,
              37.62+n*0.000001, 1, 'published' FROM generate_series(1,10025) n"""))
    result = client.get('/api/places?q=водонапорная&limit=30&page=335')
    assert result.status_code == 200, result.text
    assert result.json()['total'] == 10025
    assert len(result.json()['items']) == 5
    result = client.get('/api/map?q=водонапорная&bbox=37,55,38,56').json()
    assert result['total'] == 10025
    assert sum(f['properties'].get('point_count', 1) for f in result['features']) == 10025


def test_outage_preserves_queue_and_plain_browsing(client, monkeypatch):
    insert(client.app, 'Усадьба после сбоя')
    search = client.app.state.search
    url = search.url
    monkeypatch.setattr(search, 'url', 'http://127.0.0.1:1')
    response = client.get('/api/places?q=усадьба')
    assert response.status_code == 503
    assert '127.0.0.1' not in response.text
    assert client.get('/api/places').json()['total'] == 1
    with client.app.state.engine.connect() as c:
        assert c.scalar(text('SELECT count(*) FROM web_search_outbox')) == 1
    monkeypatch.setattr(search, 'url', url)
    assert client.get('/api/places?q=усадьба').json()['total'] == 1
    with client.app.state.engine.connect() as c:
        assert c.scalar(text('SELECT count(*) FROM web_search_outbox')) == 0


def test_concurrent_update_during_indexing_is_not_lost(client, monkeypatch):
    id = insert(client.app, 'Старая усадьба')
    search = client.app.state.search
    original = search.request
    changed = False
    def request(es, method, path, **kwargs):
        nonlocal changed
        result = original(es, method, path, **kwargs)
        if path == '/_bulk' and not changed:
            changed = True
            with client.app.state.engine.begin() as c:
                c.execute(text("UPDATE places SET name='Новая обсерватория' WHERE id=:id"), {'id':id})
        return result
    monkeypatch.setattr(search, 'request', request)
    search.sync()
    assert client.get('/api/places?q=обсерватория').json()['total'] == 1
    assert client.get('/api/places?q=усадьба').json()['total'] == 0


def test_concurrent_searches_initialize_once_without_pool_deadlock(client):
    from concurrent.futures import ThreadPoolExecutor
    insert(client.app, 'Усадьба для параллельного поиска')
    def search(_):
        response = TestClient(client.app).get('/api/places?q=усадьба')
        assert response.status_code == 200, response.text
        return response.json()['total']
    with ThreadPoolExecutor(max_workers=20) as executor:
        assert list(executor.map(search, range(20))) == [1] * 20


def test_deleted_index_is_rebuilt_from_catalog(client):
    insert(client.app, 'Усадьба для восстановления')
    assert client.get('/api/places?q=усадьба').json()['total'] == 1
    with client.app.state.search.client() as es:
        assert es.delete('/'+client.app.state.search.index).status_code == 200
    assert client.get('/api/places?q=усадьба').json()['total'] == 1


def test_geocaching_last_before_pagination_with_and_without_text_search(client):
    with client.app.state.engine.begin() as c:
        category = c.scalar(text("INSERT INTO web_categories(name) VALUES (' GeoCaching ') RETURNING id"))
        ids = []
        for category_id, name, description in (
            (1, 'Усадьба', 'Историческое место'),
            (1, 'Объект', 'Поблизости находится усадьба'),
            (category, 'Усадьба', 'Историческое место'),
            (category, 'Объект', 'Поблизости находится усадьба'),
        ):
            ids.append(c.scalar(text("""INSERT INTO places(name,description,latitude,longitude,category_id,status)
                VALUES (:name,:description,55.75,37.62,:category,'published') RETURNING id"""),
                {'name':name,'description':description,'category':category_id}))
    for query, expected in [('', [ids[1], ids[0], ids[3], ids[2]]), ('усадьба', [ids[0], ids[1], ids[2], ids[3]])]:
        actual = []
        for page in range(1, 5):
            response = client.get('/api/places', params={'q':query,'page':page,'limit':1})
            assert response.status_code == 200, response.text
            assert response.json()['total'] == 4
            actual.append(response.json()['items'][0]['id'])
        assert actual == expected
    filtered = client.get('/api/places', params={'category_id':category}).json()
    assert [p['id'] for p in filtered['items']] == [ids[3], ids[2]]
    assert client.get('/api/map?q=усадьба&bbox=37,55,38,56').json()['total'] == 4


def test_search_field_selection_applies_to_list_and_map(client):
    named = insert(client.app, 'Обсерватория', 'Историческое место')
    described = insert(client.app, 'Здание', 'Обсерватория на холме')
    addressed = insert(client.app, 'Башня', 'Историческое место')
    with client.app.state.engine.begin() as c:
        c.execute(text("UPDATE places SET full_address='Обсерватория, Москва' WHERE id=:id"), {'id':addressed})
    for scope, expected in [('name',named), ('description',described), ('address',addressed)]:
        params = {'q':'обсерватория', 'search_in':scope}
        result = client.get('/api/places', params=params)
        assert result.status_code == 200, result.text
        assert [p['id'] for p in result.json()['items']] == [expected]
        assert client.get('/api/map', params={**params,'bbox':'37,55,38,56'}).json()['total'] == 1
    assert client.get('/api/places?q=обсерватория').json()['total'] == 3
    assert client.get('/api/places?search_in=invalid').status_code == 422
