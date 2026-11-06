from conftest import register
from test_elasticsearch import insert


def test_delete_place_permissions_and_visibility(client, moderator):
    id = insert(client.app, 'Удаляемая башня')
    url = f'/api/admin/places/{id}'
    assert client.delete(url).status_code == 401
    register(client)
    assert client.delete(url).status_code == 403
    assert moderator.delete(url).status_code == 200
    assert client.get(f'/api/places/{id}').status_code == 404
    assert client.get('/api/places?q=башня').json()['total'] == 0
    assert moderator.get('/api/admin/places').json()['total'] == 0
    assert moderator.get('/api/admin/places?q=башня').json()['total'] == 0
    assert moderator.delete(url).status_code == 200
