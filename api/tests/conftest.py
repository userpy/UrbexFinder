import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient
from urbex.bootstrap.main import create_app
from urbex.bootstrap.config import Settings
from urbex.infrastructure.auth import hasher


@pytest.fixture
def app():
    config = Settings()
    assert config.environment == 'test' and config.database_url.endswith('/urbex_test'), 'Tests require the isolated test database'
    app = create_app(config)
    with app.state.engine.begin() as c:
        c.execute(text('TRUNCATE photo_event_outbox,web_telegram_logins,web_users,web_sessions,places,web_photos,web_reviews,web_reports,web_favorites,web_audit,web_login_attempts,web_search_outbox RESTART IDENTITY CASCADE'))
        c.execute(text('TRUNCATE web_categories RESTART IDENTITY CASCADE'))
        c.execute(text("INSERT INTO web_categories(name) VALUES ('Промышленность'), ('Архитектура'), ('Инфраструктура'), ('Другое')"))
    assert config.elasticsearch_index.startswith('urbex_test_')
    with app.state.search.client() as search_client:
        response = search_client.delete('/'+config.elasticsearch_index)
        assert response.status_code in (200, 404)
    yield app
    app.state.engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app, base_url='http://localhost:3100', headers={'Origin':'http://localhost:3100'}) as c:
        yield c


def register(client, email='reader@example.com'):
    response = client.post('/api/auth/register', json={'email':email,'name':'Исследователь','password':'test-password-12345'})
    assert response.status_code == 201, response.text
    client.headers['X-CSRF-Token'] = response.json()['csrf']
    return response.json()['user']


def role_client(app, role):
    client = TestClient(app, base_url='http://localhost:3100', headers={'Origin':'http://localhost:3100'})
    user = register(client, role+'@example.com')
    with app.state.engine.begin() as c:
        c.execute(text('UPDATE web_users SET role=:role WHERE id=:id'), {'role':role,'id':user['id']})
    return client


@pytest.fixture
def moderator(app):
    with role_client(app, 'moderator') as c:
        yield c


@pytest.fixture
def admin(app):
    with role_client(app, 'admin') as c:
        yield c


PLACE = {'name':'Старая фабрика','description':'Историческая фабрика. Состояние требует проверки на месте.', 'latitude':55.75,'longitude':37.62,'region':'Москва','category_id':1,'condition':'standing','access':'Сведения о доступе не подтверждены.'}

