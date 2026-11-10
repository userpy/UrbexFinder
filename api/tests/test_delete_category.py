import pytest
from sqlalchemy import text
from conftest import register
from test_elasticsearch import insert


def test_delete_category_permissions_and_audit(client, admin, moderator):
    path = '/api/admin/categories/2'
    assert client.delete(path).status_code == 401
    register(client)
    assert client.delete(path).status_code == 403
    assert moderator.delete(path).status_code == 403
    assert admin.delete(path).status_code == 200
    assert all(c['id'] != 2 for c in client.get('/api/categories').json()['items'])
    assert all(c['id'] != 2 for c in admin.get('/api/admin/categories').json()['items'])
    assert admin.delete(path).status_code == 404
    with client.app.state.engine.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM web_audit WHERE action='category.delete' AND target='categories:2'")) == 1


@pytest.mark.parametrize('status,reason', [
    ('published', ''), ('pending', ''), ('rejected', 'Удалено модератором'),
])
def test_used_category_cannot_be_deleted(client, admin, status, reason):
    place = insert(client.app, 'Место в категории')
    with client.app.state.engine.begin() as c:
        c.execute(text('UPDATE places SET status=:status, reason=:reason WHERE id=:id'),
                  dict(id=place, status=status, reason=reason))
    response = admin.delete('/api/admin/categories/1')
    assert response.status_code == 409, response.text
    with client.app.state.engine.connect() as c:
        assert c.scalar(text('SELECT category_id FROM places WHERE id=:id'), {'id': place}) == 1
        assert c.scalar(text('SELECT count(*) FROM web_categories WHERE id=1')) == 1
        assert c.scalar(text("SELECT count(*) FROM web_audit WHERE action='category.delete'")) == 0
