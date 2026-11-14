import hmac
import json
import time
from hashlib import sha256
from urllib.parse import urlparse, parse_qs, urlencode
from fastapi.testclient import TestClient
from sqlalchemy import text


BOT_TOKEN = '123456:test-mini-app-token'


def mini_app_data(user_id=12345678901, auth_date=None):
    fields = {
        'auth_date': str(auth_date or int(time.time())),
        'user': json.dumps({'id': user_id, 'first_name': 'Исследователь'}, separators=(',', ':')),
    }
    data_check_string = '\n'.join(f'{key}={value}' for key, value in sorted(fields.items()))
    secret_key = hmac.new(b'WebAppData', BOT_TOKEN.encode(), sha256).digest()
    fields['hash'] = hmac.new(secret_key, data_check_string.encode(), sha256).hexdigest()
    return urlencode(fields)


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


def test_mini_app_login_verifies_data_and_reuses_telegram_account(client, app):
    app.state.config.telegram_bot_token = BOT_TOKEN
    init_data = mini_app_data()
    response = client.post('/api/auth/telegram/mini-app', json={'init_data': init_data})
    assert response.status_code == 200, response.text
    user = response.json()['user']
    assert user['email'] is None
    assert user['name'] == 'Исследователь'
    assert client.get('/api/auth/me').json()['user']['id'] == user['id']

    client.headers['X-CSRF-Token'] = response.json()['csrf']
    again = client.post('/api/auth/telegram/mini-app', json={'init_data': init_data})
    assert again.status_code == 200, again.text
    assert again.json()['user']['id'] == user['id']
    with app.state.engine.connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM web_users WHERE telegram_id=12345678901')) == 1
    app.state.config.telegram_bot_username = 'test_bot'
    with TestClient(app, base_url='http://localhost:3100', headers={'Origin': 'http://localhost:3100'}) as browser:
        approve(app, begin(browser, app))
        assert browser.post('/api/auth/telegram/complete').json()['user']['id'] == user['id']


def test_mini_app_rejects_bad_signature_and_expired_init_data(client, app):
    app.state.config.telegram_bot_token = BOT_TOKEN
    valid = mini_app_data()
    invalid = valid[:-1] + ('0' if valid[-1] != '0' else '1')
    assert client.post('/api/auth/telegram/mini-app', json={'init_data': invalid}).status_code == 401
    expired = mini_app_data(auth_date=int(time.time()) - 301)
    assert client.post('/api/auth/telegram/mini-app', json={'init_data': expired}).status_code == 401
