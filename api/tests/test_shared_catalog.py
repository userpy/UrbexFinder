from fastapi.testclient import TestClient
from sqlalchemy import text
from conftest import register, PLACE


def test_common_catalog_changes_and_moderation(client, moderator):
    with client.app.state.engine.begin() as c:
        published = c.scalar(text("INSERT INTO places(name,description,latitude,longitude,status) VALUES ('Из бота','Описание',55.75,37.62,'published') RETURNING id"))
        pending = c.scalar(text("INSERT INTO places(name,latitude,longitude,telegram_author_id) VALUES ('Заявка бота',55.7,37.6,9876543210123) RETURNING id"))
    guest = TestClient(client.app)
    assert guest.get(f'/api/places/{published}').json()['id'] == published
    assert guest.get(f'/api/places/{pending}').status_code == 404
    assert guest.get('/api/places').json()['total'] == 1
    assert moderator.post(f'/api/admin/places/{pending}/decision', json={'status':'published'}).status_code == 200
    with client.app.state.engine.begin() as c:
        assert c.scalar(text('SELECT status FROM places WHERE id=:id'), {'id': pending}) == 'published'
        c.execute(text("UPDATE places SET name='Изменение бота' WHERE id=:id"), {'id': published})
    assert guest.get(f'/api/places/{published}').json()['name'] == 'Изменение бота'
    register(client)
    new = client.post('/api/places', json=PLACE).json()['id']
    assert guest.get(f'/api/places/{new}').status_code == 404
    assert moderator.post(f'/api/admin/places/{new}/decision', json={'status':'published'}).status_code == 200
    with client.app.state.engine.begin() as c:
        assert c.scalar(text('SELECT status FROM places WHERE id=:id'), {'id': new}) == 'published'
        c.execute(text('UPDATE places SET nonexistent_reports_count=10 WHERE id=:id'), {'id': published})
    assert guest.get(f'/api/places/{published}').status_code == 404
    assert all(p['id'] != published for p in guest.get('/api/places').json()['items'])


def test_pending_place_without_author_appears_in_moderation(client, moderator):
    with client.app.state.engine.begin() as c:
        place = c.scalar(text("INSERT INTO places(name,latitude,longitude,status) VALUES ('Место без автора',55.75,37.62,'pending') RETURNING id"))
    queue = moderator.get('/api/admin/places?status=pending')
    assert queue.status_code == 200
    assert any(p['id'] == place for p in queue.json()['items'])
    guest = TestClient(client.app)
    assert guest.get(f'/api/places/{place}').status_code == 404
    assert moderator.post(f'/api/admin/places/{place}/decision', json={'status':'published'}).status_code == 200
    assert guest.get(f'/api/places/{place}').status_code == 200


def test_telegram_photos_permissions_and_no_secret_disclosure(client, moderator, monkeypatch):
    with client.app.state.engine.begin() as c:
        place = c.scalar(text("INSERT INTO places(name,latitude,longitude,status) VALUES ('Фото бота',55.75,37.62,'published') RETURNING id"))
        photo = c.scalar(text("INSERT INTO place_photos(place_id,user_id,file_id,status) VALUES (:id,9876543210123,'private-file-id','published') RETURNING id"), {'id': place})
    guest = TestClient(client.app)
    listing = guest.get(f'/api/places/{place}/photos')
    assert listing.json()['items'][0]['id'] == -photo
    assert 'private-file-id' not in listing.text and 'file_id' not in listing.text
    seen = []
    def fetch(file_id):
        seen.append(file_id)
        return b'jpeg-from-server'
    monkeypatch.setattr(client.app.state.storage, 'get_telegram', fetch)
    response = guest.get(f'/api/photos/{-photo}/content')
    assert response.status_code == 200 and response.content == b'jpeg-from-server'
    assert response.headers['cache-control'] == 'private, no-store'
    with client.app.state.engine.begin() as c:
        c.execute(text("UPDATE places SET status='pending' WHERE id=:id"), {'id': place})
    assert guest.get(f'/api/photos/{-photo}/content').status_code == 404
    assert seen == ['private-file-id']
    assert moderator.get(f'/api/photos/{-photo}/content').status_code == 200


def test_new_telegram_photo_requires_shared_moderation(client, moderator):
    with client.app.state.engine.begin() as c:
        place = c.scalar(text("INSERT INTO places(name,latitude,longitude,status) VALUES ('Фото на проверке',55.75,37.62,'published') RETURNING id"))
        photo = c.scalar(text("INSERT INTO place_photos(place_id,user_id,file_id) VALUES (:id,1,'pending-file') RETURNING id"), {'id': place})
    guest = TestClient(client.app)
    assert guest.get(f'/api/places/{place}/photos').json()['total'] == 0
    assert guest.get(f'/api/photos/{-photo}/content').status_code == 404
    queue = moderator.get('/api/admin/photos?status=pending').json()
    assert any(p['id'] == -photo for p in queue['items'])
    response = moderator.post(f'/api/admin/photos/{-photo}/decision', json={'status':'published'})
    assert response.status_code == 200
    assert 'file_id' not in response.text
    assert guest.get(f'/api/places/{place}/photos').json()['total'] == 1
    register(client)
    assert client.post('/api/reports', json={'target_type':'photos','target_id':-photo,'text':'Проверить фотографию'}).status_code == 201
    with client.app.state.engine.connect() as c:
        assert c.scalar(text('SELECT status FROM place_photos WHERE id=:id'), {'id': photo}) == 'published'


def test_telegram_transport_redacts_failure_and_sanitizes_image(monkeypatch):
    import httpx
    from io import BytesIO
    from PIL import Image
    from urbex.infrastructure.telegram import TelegramPhotos
    from urbex.domain.rules import DomainError
    import pytest
    original_client = httpx.Client
    data = BytesIO()
    Image.new('RGB', (4, 4), 'blue').save(data, 'PNG')
    def handler(request):
        if request.url.path.endswith('/getFile'):
            return httpx.Response(200, json={'ok':True,'result':{'file_path':'photos/photo.png','file_size':len(data.getvalue())}})
        return httpx.Response(200, content=data.getvalue())
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    result = TelegramPhotos('secret-token').get('file-id')
    assert result.startswith(b'\xff\xd8')
    def failure(request):
        return httpx.Response(401, text='secret-token')
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original_client(transport=httpx.MockTransport(failure), **kwargs))
    with pytest.raises(DomainError) as error:
        TelegramPhotos('secret-token').get('file-id')
    assert error.value.status == 502
    assert 'secret-token' not in error.value.message
