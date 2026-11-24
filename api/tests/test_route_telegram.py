from conftest import register
from sqlalchemy import text


def test_send_route_only_to_owner_telegram(client, admin, monkeypatch):
    user = register(client)
    route = client.post('/api/itineraries', json={'name': 'Поездка'}).json()
    url = f"/api/itineraries/{route['id']}/telegram"
    assert client.post(url).status_code == 400
    assert admin.post(url).status_code == 404
    with client.app.state.engine.begin() as c:
        c.execute(text('UPDATE web_users SET telegram_id=12345 WHERE id=:id'), {'id': user['id']})
    calls = []
    monkeypatch.setattr(client.app.state, 'send_route', lambda chat, itinerary: calls.append((chat, itinerary)))
    assert client.post(url).status_code == 200
    assert calls[0][0] == 12345
    assert calls[0][1]['name'] == 'Поездка'


def test_prepare_share_uses_owner_and_server_url(client, admin, monkeypatch):
    user = register(client)
    route = client.post('/api/itineraries', json={'name': 'Поездка'}).json()
    url = f"/api/itineraries/{route['id']}/share-message"
    assert client.post(url).status_code == 400
    assert admin.post(url).status_code == 404
    with client.app.state.engine.begin() as c:
        c.execute(text('UPDATE web_users SET telegram_id=12345 WHERE id=:id'), {'id': user['id']})
    calls = []
    def prepare(owner, itinerary, link):
        calls.append((owner, itinerary, link))
        return {'id': 'prepared-message'}
    monkeypatch.setattr(client.app.state, 'prepare_route_share', prepare)
    def unexpected_send(*args):
        raise AssertionError('Preparation must not send a message')
    monkeypatch.setattr(client.app.state, 'send_route', unexpected_send)
    response = client.post(url, json={'user_id': 999, 'url': 'https://evil.example'})
    assert response.status_code == 200
    assert response.json() == {'id': 'prepared-message'}
    owner, itinerary, link = calls[0]
    assert owner == 12345 and itinerary['id'] == route['id']
    token = client.post(f"/api/itineraries/{route['id']}/share").json()['token']
    assert link == f"{client.app.state.config.origin}/routes/share?token={token}"
    assert client.get(f'/api/itineraries/shared/{token}').status_code == 200
