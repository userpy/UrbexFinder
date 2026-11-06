from sqlalchemy import text
from conftest import register
from test_elasticsearch import insert


def test_public_card_counts_and_rating_exclude_unpublished_content(client):
    user = register(client)
    place = insert(client.app, 'Место с отзывами')
    empty = insert(client.app, 'Пустое место')
    with client.app.state.engine.begin() as c:
        c.execute(text('INSERT INTO place_ratings(place_id,user_id,score) VALUES (:id,123,3),(:id,456,3)'), {'id':place})
        c.execute(text("INSERT INTO web_reviews(place_id,author_id,text,score,status) VALUES (:id,:user,'Отзыв',5,'published')"), {'id':place,'user':user['id']})
        c.execute(text("INSERT INTO place_reviews(place_id,user_id,text) VALUES (:id,123,'Отзыв из бота')"), {'id':place})
        for status in ['published','pending','rejected']:
            c.execute(text('INSERT INTO web_photos(place_id,author_id,object_key,status) VALUES (:id,:user,:status,:status)'), {'id':place,'user':user['id'],'status':status})
            c.execute(text("INSERT INTO place_photos(place_id,user_id,file_id,status) VALUES (:id,123,:status,:status)"), {'id':place,'status':status})
    items = {p['id']:p for p in client.get('/api/places').json()['items']}
    assert items[place]['reviews_count'] == 1
    assert items[place]['photos_count'] == 2
    assert items[place]['rating_count'] == 3
    assert items[place]['rating_avg'] == 3.67
    assert items[empty]['photos_count'] == items[empty]['reviews_count'] == items[empty]['rating_count'] == 0
    with client.app.state.engine.begin() as c:
        c.execute(text("UPDATE web_reviews SET status='rejected' WHERE place_id=:id"), {'id':place})
    item = next(p for p in client.get('/api/places').json()['items'] if p['id']==place)
    assert item['reviews_count'] == 1
    assert item['rating_count'] == 2
    assert item['rating_avg'] == 3


def test_shared_telegram_rating_changes_visible_without_snapshot(client):
    place = insert(client.app, 'Объект общей базы')
    with client.app.state.engine.begin() as c:
        c.execute(text('INSERT INTO place_ratings(place_id,user_id,score) VALUES (:id,123,5)'), {'id':place})
    assert client.get('/api/places').json()['items'][0]['rating_avg'] == 5
    with client.app.state.engine.begin() as c:
        c.execute(text('UPDATE place_ratings SET score=4 WHERE place_id=:id'), {'id':place})
    assert client.get('/api/places').json()['items'][0]['rating_avg'] == 4
    with client.app.state.engine.begin() as c:
        c.execute(text('DELETE FROM place_ratings WHERE place_id=:id'), {'id':place})
    assert client.get('/api/places').json()['items'][0]['rating_count'] == 0


def test_deleted_telegram_review_hidden_from_admin_list(client, admin):
    place = insert(client.app, 'Место с удалённым отзывом')
    with client.app.state.engine.begin() as c:
        id = c.scalar(text("INSERT INTO place_reviews(place_id,user_id,text) VALUES (:id,123,'Удаляемый отзыв') RETURNING id"), {'id': place})
    assert admin.delete(f'/api/admin/reviews/{-id}').status_code == 200
    result = admin.get('/api/admin/reviews').json()
    assert result['items'] == []
    assert result['total'] == 0
    assert client.get(f'/api/places/{place}/reviews?source=telegram').json()['total'] == 0
