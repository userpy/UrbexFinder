from conftest import register


def test_delete_user_permissions_sessions_and_anonymization(client,admin,moderator):
    user=register(client)
    id=user['id']
    url=f'/api/admin/users/{id}'
    assert client.delete(url).status_code==403
    assert moderator.delete(url).status_code==403
    route=client.post('/api/itineraries',json={'name':'Личный'}).json()['id']
    assert admin.delete(url).status_code==200
    assert client.get('/api/auth/me').json()['user'] is None
    assert id not in [r['id'] for r in admin.get('/api/admin/users').json()['items']]
    assert admin.put(url,json={'role':'user','blocked':False}).status_code==404
    admin_id=admin.get('/api/auth/me').json()['user']['id']
    assert admin.delete(f'/api/admin/users/{admin_id}').status_code==400
    from sqlalchemy import text
    with client.app.state.engine.connect() as c:
        row=c.execute(text('SELECT email,telegram_id,name,blocked,deleted FROM web_users WHERE id=:id'),{'id':id}).mappings().one()
        assert row['email'] is None and row['telegram_id'] is None and row['blocked'] and row['deleted']
        assert not c.scalar(text('SELECT count(*) FROM web_itineraries WHERE id=:id'),{'id':route})
