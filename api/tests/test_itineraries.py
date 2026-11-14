from fastapi.testclient import TestClient
from sqlalchemy import text
from conftest import register
from test_elasticsearch import insert


def test_private_itinerary_lifecycle_and_concurrency(client):
    a=insert(client.app,'Первое'); b=insert(client.app,'Второе')
    assert client.get('/api/itineraries').status_code==401
    register(client)
    data={'name':'Выходные','trip_date':'2026-11-07','stops':[{'place_id':a},{'place_id':b}]}
    response=client.post('/api/itineraries',json=data)
    assert response.status_code==201,response.text
    route=response.json(); id=route['id']
    assert client.get(f'/api/places/{a}/favorite').json()['saved']
    assert client.get(f'/api/places/{b}/favorite').json()['saved']
    other=TestClient(client.app,base_url='http://localhost:3100',headers={'Origin':'http://localhost:3100'})
    register(other,'other@example.com')
    assert other.get(f'/api/itineraries/{id}').status_code==404
    assert other.delete(f'/api/itineraries/{id}').status_code==404
    assert other.put(f'/api/itineraries/{id}',json={**data,'version':1}).status_code==404
    changed={**data,'version':1,'stops':[{'place_id':b,'note':'Взять камеру','status':'visited'},{'place_id':a}]}
    assert client.put(f'/api/itineraries/{id}',json=changed).status_code==200
    assert client.put(f'/api/itineraries/{id}',json=changed).status_code==409
    detail=client.get(f'/api/itineraries/{id}').json()
    assert detail['items'][0]['place']['id']==b
    assert detail['stops'][0]['note']=='Взять камеру'
    assert client.post('/api/itineraries',json={**data,'stops':[{'place_id':a},{'place_id':a}]}).status_code==422
    with client.app.state.engine.begin() as c:c.execute(text("UPDATE places SET status='rejected' WHERE id=:id"),{'id':b})
    assert client.get(f'/api/itineraries/{id}').json()['items'][0]['place'] is None
    assert client.delete(f'/api/itineraries/{id}').status_code==200
    assert client.get(f'/api/itineraries/{id}').status_code==404


def test_itinerary_share_link_is_public_read_only_and_hides_private_notes(client):
    place=insert(client.app,'Место для общей ссылки')
    register(client)
    route=client.post('/api/itineraries',json={
        'name':'Маршрут для друзей',
        'notes':'Личные заметки',
        'stops':[{'place_id':place,'note':'Взять фонарь','status':'planned'}],
    }).json()
    share=client.post(f"/api/itineraries/{route['id']}/share")
    assert share.status_code==200,share.text
    token=share.json()['token']
    assert len(token)>=40
    assert client.post(f"/api/itineraries/{route['id']}/share").json()['token']==token
    assert 'share_token' not in client.get(f"/api/itineraries/{route['id']}").json()
    assert 'share_token' not in client.get('/api/itineraries').json()['items'][0]
    with TestClient(client.app,base_url='http://localhost:3100',headers={'Origin':'http://localhost:3100'}) as visitor:
        response=visitor.get(f'/api/itineraries/shared/{token}')
        assert response.status_code==200,response.text
        data=response.json()
        assert data['name']=='Маршрут для друзей'
        assert data['items'][0]['place']['name']=='Место для общей ссылки'
        assert 'author_id' not in data['items'][0]['place']
        assert data['items'][0]['status']=='planned'
        assert 'notes' not in data and 'note' not in data['items'][0]
        assert visitor.get('/api/itineraries').status_code==401
        assert visitor.get('/api/itineraries/shared/not-a-token').status_code==404


def test_only_route_owner_can_enable_public_sharing(client):
    register(client)
    route=client.post('/api/itineraries',json={'name':'Приватный маршрут'}).json()
    with TestClient(client.app,base_url='http://localhost:3100',headers={'Origin':'http://localhost:3100'}) as visitor:
        assert visitor.post(f"/api/itineraries/{route['id']}/share").status_code==401
        register(visitor,'visitor@example.com')
        assert visitor.post(f"/api/itineraries/{route['id']}/share").status_code==404


def test_telegram_reviews_are_public_and_moderatable(client,moderator):
    id=insert(client.app,'Место')
    with client.app.state.engine.begin() as c:
        review=c.scalar(text("INSERT INTO place_reviews(place_id,user_id,user_name,text) VALUES (:id,123,'Путешественник','Отзыв из Telegram') RETURNING id"),{'id':id})
    data=client.get(f'/api/places/{id}/reviews').json()
    assert data['total']==1
    assert data['items'][0]['id']==-review
    assert data['items'][0]['source']=='telegram'
    assert 'user_id' not in data['items'][0]
    response=moderator.post(f'/api/admin/reviews/{-review}/decision',json={'status':'rejected','reason':'Проверка скрытия'})
    assert response.status_code==200,response.text
    assert client.get(f'/api/places/{id}/reviews').json()['total']==0
    assert client.get('/api/places').json()['items'][0]['reviews_count']==0


def test_telegram_review_filter_counts_only_telegram(client):
    id=insert(client.app,'Место с отзывами')
    register(client)
    assert client.put(f'/api/places/{id}/reviews', json={'text':'Отзыв с сайта','score':5}).status_code == 200
    with client.app.state.engine.begin() as c:
        c.execute(text("INSERT INTO place_reviews(place_id,user_id,user_name,text) VALUES (:id,123,'Автор','Отзыв из Telegram')"),{'id':id})
    data=client.get(f'/api/places/{id}/reviews?source=telegram').json()
    assert data['total']==1
    assert len(data['items'])==1
    assert data['items'][0]['source']=='telegram'


def test_only_one_active_itinerary_and_private_selection(client):
    register(client)
    a=client.post('/api/itineraries',json={'name':'Первый'}).json()
    b=client.post('/api/itineraries',json={'name':'Второй'}).json()
    assert a['created_at'] and not a['active']
    assert client.put(f"/api/itineraries/{a['id']}/active").status_code==200
    assert client.put(f"/api/itineraries/{b['id']}/active").status_code==200
    rows=client.get('/api/itineraries').json()['items']
    assert [r['id'] for r in rows if r['active']]==[b['id']]
    with TestClient(client.app,base_url='http://localhost:3100',headers={'Origin':'http://localhost:3100'}) as other:
        register(other,'another@example.com')
        assert other.put(f"/api/itineraries/{b['id']}/active").status_code==404
    assert client.put(f"/api/itineraries/{b['id']}/active?active=false").status_code==200
    assert not any(r['active'] for r in client.get('/api/itineraries').json()['items'])
    assert client.put(f"/api/itineraries/{b['id']}/active").status_code==200
    assert client.delete(f"/api/itineraries/{b['id']}").status_code==200


def test_add_to_active_creates_route_and_is_idempotent(client):
    place=insert(client.app,'Для маршрута')
    assert client.post(f'/api/places/{place}/itinerary').status_code==401
    register(client)
    added=client.post(f'/api/places/{place}/itinerary')
    assert added.status_code==200, added.text
    route_id=added.json()['route_id']
    route=client.get(f'/api/itineraries/{route_id}').json()
    assert route['active'] and len(route['stops'])==1
    assert client.get(f'/api/places/{place}/favorite').json()['saved']
    assert client.post(f'/api/places/{place}/itinerary').json()['already_added']
    assert len(client.get(f'/api/itineraries/{route_id}').json()['stops'])==1
    other=client.post('/api/itineraries',json={'name':'Выбранный'}).json()
    client.put(f"/api/itineraries/{other['id']}/active")
    assert client.post(f'/api/places/{place}/itinerary').json()['route_id']==other['id']
    version=client.get(f"/api/itineraries/{other['id']}").json()['version']
    assert version==2


def test_remove_place_from_active_preserves_other_routes(client):
    place=insert(client.app,'Удаление из маршрута')
    register(client)
    first=client.post(f'/api/places/{place}/itinerary').json()['route_id']
    second=client.post('/api/itineraries',json={'name':'Другой','stops':[{'place_id':place}]}).json()['id']
    assert client.get(f'/api/places/{place}/itinerary').json()['added']
    assert client.delete(f'/api/places/{place}/itinerary').status_code==200
    assert not client.get(f'/api/places/{place}/itinerary').json()['added']
    assert client.get(f'/api/itineraries/{first}').json()['stops']==[]
    assert len(client.get(f'/api/itineraries/{second}').json()['stops'])==1
    assert client.delete(f'/api/places/{place}/itinerary').status_code==200
    assert not client.post(f'/api/places/{place}/itinerary').json()['already_added']


def test_active_itinerary_precedes_newer_routes_across_pages(client):
    register(client)
    oldest=client.post('/api/itineraries',json={'name':'Старый активный'}).json()['id']
    for i in range(31):
        assert client.post('/api/itineraries',json={'name':f'Маршрут {i}'}).status_code==201
    assert client.put(f'/api/itineraries/{oldest}/active').status_code==200
    first=client.get('/api/itineraries').json()
    assert first['items'][0]['id']==oldest
    second=client.get('/api/itineraries?page=2').json()
    assert oldest not in [r['id'] for r in second['items']]
    assert len({r['id'] for r in first['items']+second['items']})==32


def test_delete_telegram_comment_requires_staff(client, moderator):
    place=insert(client.app,'Комментарий для удаления')
    with client.app.state.engine.begin() as c:
        id=c.scalar(text("INSERT INTO place_reviews(place_id,user_id,text) VALUES (:p,123,'Комментарий') RETURNING id"),{'p':place})
    url=f'/api/admin/reviews/{-id}'
    assert client.delete(url).status_code==401
    register(client)
    assert client.delete(url).status_code==403
    assert moderator.delete(url).status_code==200
    assert client.get(f'/api/places/{place}/reviews?source=telegram').json()['total']==0
