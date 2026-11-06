from sqlalchemy import text
from conftest import PLACE, register
from test_elasticsearch import insert


def test_admin_search_includes_pending_and_description(client, moderator):
    public = insert(client.app, 'Башня', description='Рядом располагалась усадьба')
    register(client)
    pending = client.post('/api/places', json={**PLACE, 'name': 'Старинная усадьба'}).json()['id']
    response = moderator.get('/api/admin/places', params={'q': 'усадьбе'})
    assert response.status_code == 200, response.text
    assert {row['id'] for row in response.json()['items']} == {public, pending}
    assert response.json()['total'] == 2
    assert client.get('/api/admin/places?q=усадьба').status_code == 403
    assert moderator.get('/api/admin/places?q=несуществующийзапрос').json()['total'] == 0
    with client.app.state.engine.begin() as c:
        c.execute(text("UPDATE places SET full_address='Александров, Советская улица' WHERE id=:id"), {'id': pending})
    assert moderator.get('/api/admin/places?q=Советская').json()['items'][0]['id'] == pending
