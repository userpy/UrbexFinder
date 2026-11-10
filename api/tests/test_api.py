from io import BytesIO
from datetime import datetime
import httpx
from PIL import Image
from sqlalchemy import text
from fastapi.testclient import TestClient
from conftest import register, PLACE


def create(client, **values):
    r = client.post('/api/places', json={**PLACE, **values})
    assert r.status_code == 201, r.text
    return r.json()['id']


def approve(moderator, id, kind='places'):
    r = moderator.post(f'/api/admin/{kind}/{id}/decision', json={'status':'published'})
    assert r.status_code == 200, r.text


def test_vertical_registration_moderation_map_favorite_logout(client, moderator):
    user = register(client)
    assert user['role'] == 'user'
    id = create(client)
    assert client.get('/api/places').json()['total'] == 0
    guest = TestClient(client.app)
    assert guest.get(f'/api/places/{id}').status_code == 404
    assert client.post(f'/api/admin/places/{id}/decision', json={'status':'published'}).status_code == 403
    assert moderator.post(f'/api/admin/places/{id}/decision', json={'status':'rejected'}).status_code == 400
    assert moderator.post(f'/api/admin/places/{id}/decision', json={'status':'changes_requested','reason':'Нужен источник сведений'}).status_code == 200
    assert 'источник' in client.get('/api/me/places').json()['items'][0]['reason']
    assert client.put(f'/api/places/{id}', json=PLACE).status_code == 200
    approve(moderator, id)
    assert guest.get(f'/api/places/{id}').status_code == 200
    assert guest.get('/api/places?bbox=37,55,38,56').json()['total'] == 1
    assert guest.get('/api/places?bbox=10,10,11,11').json()['total'] == 0
    assert guest.get('/api/places?near_lon=37.62&near_lat=55.75&radius_km=1').json()['total'] == 1
    assert guest.get('/api/places?near_lon=35&near_lat=53&radius_km=1').json()['total'] == 0
    assert client.put(f'/api/places/{id}/favorite').status_code == 200
    assert client.put(f'/api/places/{id}/favorite').status_code == 200
    assert client.get('/api/me/favorites').json()['items'][0]['id'] == id
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/me/favorites').status_code == 401
    r = client.post('/api/auth/login', json={'email':user['email'],'password':'test-password-12345'})
    assert r.status_code == 200
    assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=lax' in r.headers['set-cookie']
    client.headers['X-CSRF-Token'] = r.json()['csrf']
    assert client.get('/api/me/favorites').json()['total'] == 1


def test_roles_csrf_block_and_session_revocation(client, moderator, admin):
    user = register(client)
    id = create(client)
    assert client.post('/api/places',json=PLACE,headers={'X-CSRF-Token':'bad'}).status_code == 403
    assert client.post('/api/places',json=PLACE,headers={'Origin':'https://evil.invalid'}).status_code == 403
    assert moderator.get('/api/admin/users').status_code == 403
    assert client.get('/api/admin/places').status_code == 403
    assert moderator.put(f"/api/admin/users/{user['id']}",json={'role':'admin','blocked':False}).status_code == 403
    assert admin.put(f"/api/admin/users/{user['id']}",json={'role':'user','blocked':True}).status_code == 200
    assert client.get('/api/me/places').status_code == 401
    assert client.get(f'/api/places/{id}').status_code == 404
    assert client.post('/api/auth/login',json={'email':user['email'],'password':'test-password-12345'}).status_code == 401
    assert admin.get('/api/admin/audit').json()['total'] >= 1
    assert 'password_hash' not in admin.get('/api/admin/users').text


def test_no_registration_role_escalation_and_login_throttle(client):
    assert client.post('/api/auth/register',json={'email':'h@example.com','name':'Hack','password':'test-password-12345','role':'admin'}).status_code == 422
    for _ in range(10):
        assert client.post('/api/auth/login',json={'email':'no@example.com','password':'test-password-12345'}).status_code == 401
    assert client.post('/api/auth/login',json={'email':'no@example.com','password':'test-password-12345'}).status_code == 429


def jpeg():
    b=BytesIO();Image.new('RGB',(20,20),'blue').save(b,'JPEG');return b.getvalue()


def test_photo_validation_private_s3_moderation_and_limits(client, moderator):
    register(client)
    id = create(client)
    assert client.post(f'/api/places/{id}/photos',files={'file':('fake.jpg',b'<script>alert(1)</script>','image/jpeg')}).status_code == 400
    assert client.post(f'/api/places/{id}/photos',files={'file':('big.jpg',b'x'*(8*1024*1024+1),'image/jpeg')}).status_code == 413
    r=client.post(f'/api/places/{id}/photos',files={'file':('../../evil.html',jpeg(),'text/html')})
    assert r.status_code == 201, r.text
    photo=r.json();pid=photo['id']
    assert photo['object_key'].startswith('photos/') and photo['object_key'].endswith('.jpg')
    guest=TestClient(client.app)
    assert guest.get(f'/api/photos/{pid}/content').status_code == 404
    assert moderator.get(f'/api/photos/{pid}/content').status_code == 200
    approve(moderator,id)
    assert guest.get(f'/api/photos/{pid}/content').status_code == 404
    assert guest.get(f'/api/places/{id}/photos').json()['total'] == 0
    approve(moderator,pid,'photos')
    r=guest.get(f'/api/photos/{pid}/content');assert r.status_code == 200 and r.headers['content-type']=='image/jpeg'
    store=client.app.state.storage
    assert httpx.get(f'{client.app.state.config.s3_endpoint}/{store.bucket}/{photo["object_key"]}').status_code == 403
    for _ in range(19):
        assert client.post(f'/api/places/{id}/photos',files={'file':('x.jpg',jpeg())}).status_code == 201
    assert client.post(f'/api/places/{id}/photos',files={'file':('x.jpg',jpeg())}).status_code == 409


def test_reviews_ownership_and_reports(client,moderator,admin):
    register(client);id=create(client);approve(moderator,id)
    r=client.put(f'/api/places/{id}/reviews',json={'text':'Отличное место для изучения истории','score':4})
    assert r.status_code==200;rid=r.json()['id']
    assert client.put(f'/api/places/{id}/reviews',json={'text':'Обновлённое наблюдение','score':3}).json()['id']==rid
    assert moderator.post(f'/api/admin/reviews/{rid}/decision',json={'status':'rejected','reason':'Требует проверки'}).status_code==200
    assert TestClient(client.app).get(f'/api/places/{id}/reviews').json()['total']==0
    assert client.put(f'/api/places/{id}/reviews',json={'text':'Исправленный отзыв','score':3}).json()['status']=='pending'
    assert admin.put(f'/api/places/{id}',json=PLACE).status_code==403
    assert client.post('/api/reports',json={'target_type':'places','target_id':id,'text':'Уточните сведения о доступе'}).status_code==201
    assert moderator.get('/api/admin/reports').json()['total']==1
    assert client.post('/api/admin/categories',json={'name':'Secret'}).status_code==403
    assert admin.post('/api/admin/categories',json={'name':'Новая категория'}).status_code==201


def test_spatial_validation_search_pagination(client,moderator):
    register(client)
    a=create(client);b=create(client,name='Усадьба на берегу',description='Заброшенная усадьба у берега. Сведения требуют проверки на месте.',longitude=170);approve(moderator,a);approve(moderator,b)
    assert client.get('/api/places?q=фабрика').json()['total']==1
    assert client.get('/api/places?bbox=160,-85,-160,85').json()['total']==1
    assert client.get('/api/places?bbox=nan,0,1,2').status_code==422
    assert client.get('/api/places?bbox=1,2').status_code==422
    assert client.get('/api/places?near_lon=10').status_code==422
    assert client.get('/api/places?limit=100000').status_code==422
    first=client.get('/api/places?limit=1').json();second=client.get('/api/places?limit=1&page=2').json()
    assert first['total']==2 and first['items'][0]['id']!=second['items'][0]['id']


def test_expired_and_revoked_sessions(client):
    user=register(client)
    with client.app.state.engine.begin() as c:
        c.execute(text("UPDATE web_sessions SET expires_at=now()-interval '1 second'"))
    assert client.get('/api/me/places').status_code==401
    r=client.post('/api/auth/login',json={'email':user['email'],'password':'test-password-12345'})
    assert r.status_code==200
    client.headers['X-CSRF-Token']=r.json()['csrf']
    token=client.cookies.get('urbex_session')
    assert client.post('/api/auth/revoke-all').status_code==200
    client.cookies.set('urbex_session',token)
    assert client.get('/api/me/places').status_code==401


def test_map_covers_all_pages_and_applies_filters(client, moderator):
    register(client)
    # More than one list page, but map totals must include every matching object.
    with client.app.state.engine.begin() as connection:
        connection.execute(text("""INSERT INTO places
            (name,description,latitude,longitude,region,category_id,status)
            SELECT 'Карта ' || n, 'Тест пространственной выдачи', 55.75+n*0.00001,
                   37.62+n*0.00001, 'Москва', 1, 'published'
            FROM generate_series(1,75) n"""))
    hidden = create(client)
    assert client.get('/api/places?limit=30').json()['total'] == 75
    result = client.get('/api/map?bbox=37,55,38,56&zoom=9').json()
    assert result['total'] == 75
    points = client.get('/api/map?bbox=37,55,38,56&zoom=9&cluster=false').json()
    assert points['total'] == len(points['features']) == 75
    assert all('point_count' not in f['properties'] for f in points['features'])
    assert len({f['properties']['id'] for f in points['features']}) == 75
    assert hidden not in {f['properties']['id'] for f in points['features']}
    assert client.get('/api/map?bbox=37,55,38,56&cluster=false&category_id=2').json()['total'] == 0

    assert sum(f['properties'].get('point_count', 1) for f in result['features']) == 75
    assert len(result['features']) <= 2401
    assert all(f['properties'].get('id') != hidden for f in result['features'])
    assert client.get('/api/map?bbox=37,55,38,56&region=Другой').json()['total'] == 0
    assert client.get('/api/map?bbox=10,10,11,11').json()['total'] == 0
    assert client.get('/api/map').status_code == 422
    assert client.get('/api/map?bbox=37,55,38,56&zoom=23').status_code == 422
    assert client.get('/api/map?bbox=37,55,38,56&near_lon=35&near_lat=53&radius_km=1').json()['total'] == 0


def test_map_antimeridian_and_bounded_world_response(client, moderator):
    register(client)
    for lon in (179, -179, 0):
        approve(moderator, create(client, longitude=lon))
    result = client.get('/api/map?bbox=170,-80,-170,80&zoom=22').json()
    assert result['total'] == 2
    assert all(f['properties']['category'] == 'Промышленность' for f in result['features'])
    assert all(abs(f['geometry']['coordinates'][0]) >= 170 for f in result['features'])
    with client.app.state.engine.begin() as connection:
        connection.execute(text("""INSERT INTO places
            (name,description,latitude,longitude,region,category_id,status)
            SELECT 'Точка', 'Равномерное распределение', y, x, 'Тест', 1, 'published'
            FROM generate_series(-179,179,2) x CROSS JOIN generate_series(-79,79,2) y"""))
    result = client.get('/api/map?bbox=-180,-85,180,85&zoom=22').json()
    assert result['total'] == 14403
    assert len(result['features']) <= 2401
    assert sum(f['properties'].get('point_count', 1) for f in result['features']) == 14403


def test_favorite_state_and_admin_photo_filter(client, moderator):
    register(client)
    a, b = create(client), create(client, name='Другая фабрика')
    approve(moderator, a)
    assert client.get(f'/api/places/{a}/favorite').json() == {'saved': False}
    client.put(f'/api/places/{a}/favorite')
    assert client.get(f'/api/places/{a}/favorite').json() == {'saved': True}
    assert TestClient(client.app).get(f'/api/places/{a}/favorite').status_code == 401
    client.delete(f'/api/places/{a}/favorite')
    assert client.get(f'/api/places/{a}/favorite').json() == {'saved': False}
    for id in (a, b):
        assert client.post(f'/api/places/{id}/photos', files={'file': ('a.jpg', jpeg())}).status_code == 201
    result = moderator.get(f'/api/admin/photos?place_id={a}').json()
    assert result['total'] == 1 and result['items'][0]['place_id'] == a
    assert client.get(f'/api/admin/photos?place_id={a}').status_code == 403


def test_full_address_survives_submission_and_resubmission(client, moderator):
    register(client)
    address = 'Московская область, городской округ Щёлково, улица Лесная, 12'
    id = create(client, full_address=address)
    assert client.get(f'/api/places/{id}').json()['full_address'] == address
    assert moderator.post(f'/api/admin/places/{id}/decision', json={
        'status': 'changes_requested', 'reason': 'Уточните описание',
    }).status_code == 200
    # Older clients that omit the optional field must not erase the address.
    result = client.put(f'/api/places/{id}', json=PLACE)
    assert result.status_code == 200, result.text
    assert result.json()['full_address'] == address
    assert result.json()['region'] == PLACE['region']
