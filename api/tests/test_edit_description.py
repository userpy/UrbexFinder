from sqlalchemy import text
from conftest import register
from test_elasticsearch import insert


def test_description_edit_requires_staff_preserves_state_and_detects_conflicts(client, moderator):
    id = insert(client.app, 'Усадьба', 'Исходное описание')
    url = f'/api/admin/places/{id}/description'
    data = {'description':'Обновлённое описание обсерватории', 'expected_description':'Исходное описание'}
    assert client.patch(url, json=data).status_code == 401
    register(client)
    assert client.patch(url, json=data).status_code == 403
    result = moderator.patch(url, json=data)
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'published'
    assert result.json()['name'] == 'Усадьба'
    assert client.get(f'/api/places/{id}').json()['description'] == data['description']
    assert client.get('/api/places?q=обсерватории').json()['items'][0]['id'] == id
    assert moderator.patch(url, json=data).status_code == 409
    assert moderator.patch(url, json={'description':' '}).status_code == 422
    with client.app.state.engine.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM web_audit WHERE action='description.update'")) == 1


def test_edit_location_address_and_description_atomically(client, moderator):
    id = insert(client.app, 'Усадьба', 'Исходное описание')
    original = client.get(f'/api/places/{id}').json()
    data = dict(name='Обсерватория', description='Изменённое описание', latitude=56.4, longitude=38.72,
                address='Новый адрес, Александров', category_id=2, expected_updated_at=original['updated_at'])
    url = f'/api/admin/places/{id}'
    assert client.patch(url, json=data).status_code == 401
    result = moderator.patch(url, json=data)
    assert result.status_code == 200, result.text
    result = result.json()
    assert (result['latitude'],result['longitude']) == (56.4,38.72)
    assert result['full_address'] == result['region'] == data['address']
    assert result['status'] == original['status']
    assert result['name'] == 'Обсерватория'
    assert result['category_id'] == 2
    assert client.get(f'/api/places/{id}').json()['category_id'] == 2
    assert client.get('/api/places?q=Обсерватория').json()['items'][0]['id'] == id
    assert moderator.patch(url, json=data).status_code == 409
    assert moderator.patch(url, json={**data,'latitude':100}).status_code == 422
    assert client.get('/api/map?bbox=38.7,56.3,38.8,56.5').json()['total'] == 1
    assert client.get('/api/map?bbox=37.5,55.7,37.7,55.8').json()['total'] == 0


def test_reverse_address_permissions_errors_and_cache(client, moderator, monkeypatch):
    import httpx
    from urbex.infrastructure import geocoding
    geocoding.reverse_address.cache_clear()
    monkeypatch.setattr(client.app.state.config, 'geocoder_url', 'https://geocoder.example')
    calls = []
    def response(*args, **kwargs):
        calls.append(kwargs)
        return httpx.Response(200, json={'display_name':'Адрес из геокодера'}, request=httpx.Request('GET',args[0]))
    monkeypatch.setattr(geocoding.httpx, 'get', response)
    url='/api/admin/geocode/reverse?latitude=56.4&longitude=38.72'
    assert client.get(url).status_code == 401
    for _ in range(2):
        result=moderator.get(url)
        assert result.status_code == 200, result.text
        assert result.json()['address'] == 'Адрес из геокодера'
    assert len(calls) == 1
    assert moderator.get('/api/admin/geocode/reverse?latitude=999&longitude=0').status_code == 422
    geocoding.reverse_address.cache_clear()
    def fail(*args, **kwargs):raise httpx.ConnectError('Unavailable')
    monkeypatch.setattr(geocoding.httpx, 'get', fail)
    assert moderator.get(url).status_code == 502


def test_region_lookup_for_signed_user(client, monkeypatch):
    url='/api/geocode/reverse?latitude=55.75&longitude=37.62'
    assert client.get(url).status_code==401
    register(client)
    monkeypatch.setattr(client.app.state,'reverse_address',lambda lat,lon: {'address':'Москва, Россия','region':'Москва'})
    assert client.get(url).json()['region']=='Москва'
    assert client.get('/api/geocode/reverse?latitude=999&longitude=0').status_code==422
