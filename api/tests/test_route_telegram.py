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
