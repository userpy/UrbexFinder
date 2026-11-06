from hashlib import sha256
from urllib.parse import urlparse, parse_qs
from fastapi.testclient import TestClient
from sqlalchemy import text


def begin(client, app):
    app.state.config.telegram_bot_username = 'test_bot'
    response = client.post('/api/auth/telegram/start')
    assert response.status_code == 200
    data = response.json()
    assert len(data['code']) == 6
    token = parse_qs(urlparse(data['url']).query)['start'][0].removeprefix('login_')
    return sha256(token.encode()).hexdigest()


def approve(app, link_hash, user=12345678901):
    with app.state.engine.begin() as c:
        c.execute(text("UPDATE web_telegram_logins SET confirmed=true, telegram_id=:user, display_name='Исследователь' WHERE link_hash=:hash"), {'user': user, 'hash': link_hash})


def test_browser_bound_single_use_identity(client, app):
    link = begin(client, app)
    assert client.post('/api/auth/telegram/complete').json() == {'pending': True}
    secret = client.cookies.get('urbex_tg_login')
    approve(app, link)
    with TestClient(app, base_url='http://localhost:3100', headers={'Origin': 'http://localhost:3100'}) as other:
        assert other.post('/api/auth/telegram/complete').status_code == 401
    result = client.post('/api/auth/telegram/complete')
    assert result.status_code == 200, result.text
    user = result.json()['user']
    assert user['role'] == 'user' and user['email'] is None
    assert client.get('/api/auth/me').json()['user']['id'] == user['id']
    with TestClient(app, base_url='http://localhost:3100', headers={'Origin': 'http://localhost:3100'}) as replay:
        replay.cookies.set('urbex_tg_login', secret)
        assert replay.post('/api/auth/telegram/complete').status_code == 410
    with TestClient(app, base_url='http://localhost:3100', headers={'Origin': 'http://localhost:3100'}) as again:
        approve(app, begin(again, app))
        assert again.post('/api/auth/telegram/complete').json()['user']['id'] == user['id']


def test_expired_and_origin(client, app):
    begin(client, app)
    with app.state.engine.begin() as c:
        c.execute(text("UPDATE web_telegram_logins SET expires_at=now()-interval '1 minute'"))
    assert client.post('/api/auth/telegram/complete').status_code == 410
    assert client.post('/api/auth/telegram/start', headers={'Origin':'https://evil.example'}).status_code == 403


def test_blocked_telegram_user(client, app):
    approve(app, begin(client, app))
    user = client.post('/api/auth/telegram/complete').json()['user']
    with app.state.engine.begin() as c:
        c.execute(text('UPDATE web_users SET blocked=true WHERE id=:id'), {'id':user['id']})
    client.cookies.clear()
    approve(app, begin(client, app))
    assert client.post('/api/auth/telegram/complete').status_code == 403
