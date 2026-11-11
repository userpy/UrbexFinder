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


def test_all_category_icons_can_be_saved(admin):
    from typing import get_args
    from urbex.presentation.schemas import CategoryInput
    icons = get_args(get_args(CategoryInput.model_fields['icon'].annotation)[0])
    assert len(icons) == 30
    assert 'architecture' in icons
    for icon in icons:
        response = admin.post('/api/admin/categories', json={'name': f'Иконка {icon}', 'icon': icon})
        assert response.status_code == 201, response.text
        assert response.json()['icon'] == icon


def test_imported_categories_receive_icons_without_overwriting_choices(app):
    from sqlalchemy import text

    with app.state.engine.begin() as c:
        for name, icon, expected in (
            ('geocaching', None, 'geocache'),
            ('Бомбоубежища', '', 'shelter'),
            (' Церкви ', '  ', 'church'),
            ('Неизвестная категория', None, 'other'),
            ('Дом культуры', 'castle', 'castle'),
            ('Красивые природные места', 'other', 'other'),
        ):
            actual = c.execute(text('''
                INSERT INTO web_categories(name, icon) VALUES (:name, :icon)
                RETURNING icon
            '''), {'name': name, 'icon': icon}).scalar_one()
            assert actual == expected
        c.execute(text("INSERT INTO web_categories(name) VALUES ('Дом культуры') ON CONFLICT(name) DO NOTHING"))
        assert c.execute(text("SELECT icon FROM web_categories WHERE name='Дом культуры'")).scalar_one() == 'castle'


def test_icon_migration_repairs_missing_values_and_preserves_saved_icons(app):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    path = Path(__file__).resolve().parents[1] / 'migrations/versions/012_imported_category_icons.py'
    spec = importlib.util.spec_from_file_location('imported_category_icons', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with app.state.engine.connect() as c:
        transaction = c.begin()
        try:
            with Operations.context(MigrationContext.configure(c)):
                migration.downgrade()
                c.execute(text("""
                    INSERT INTO web_categories(name, icon) VALUES
                    ('geocaching', NULL), ('Церкви', ' '),
                    ('Дом культуры', 'castle'), ('Бомбоубежища', 'other')
                """))
                migration.upgrade()
                icons = dict(c.execute(text('SELECT name, icon FROM web_categories')).all())
                assert icons['geocaching'] == 'geocache'
                assert icons['Церкви'] == 'church'
                assert icons['Дом культуры'] == 'castle'
                assert icons['Бомбоубежища'] == 'other'
        finally:
            transaction.rollback()
