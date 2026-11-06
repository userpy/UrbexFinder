from conftest import register
from test_elasticsearch import insert


def test_category_icons_create_edit_and_permissions(client, admin, moderator):
    register(client)
    data = {'name': 'Новая категория', 'icon': 'nature', 'active': True}
    assert client.post('/api/admin/categories', json=data).status_code == 403
    assert moderator.post('/api/admin/categories', json=data).status_code == 403
    response = admin.post('/api/admin/categories', json=data)
    assert response.status_code in (200, 201), response.text
    category = response.json()
    assert category['icon'] == 'nature'
    updated = admin.put(f"/api/admin/categories/{category['id']}", json={**data, 'name': 'Парк', 'icon': 'estate'})
    assert updated.status_code == 200
    assert updated.json()['icon'] == 'estate'
    assert admin.put(f"/api/admin/categories/{category['id']}", json={**data, 'icon': 'invalid'}).status_code == 422
    place = insert(client.app, 'Место с иконкой')
    from sqlalchemy import text
    with client.app.state.engine.begin() as c:
        c.execute(text('UPDATE places SET category_id=:category WHERE id=:id'), {'id': place, 'category': category['id']})
    result = client.get(f'/api/places/{place}').json()
    assert result['category_icon'] == 'estate'
    assert result['category'] == 'Парк'
