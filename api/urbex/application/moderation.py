from .ports import Repository, PhotoStorage
from datetime import datetime, timezone
from urbex.domain.rules import DomainError, can_read, moderation_decision


class ModerationService:
    def __init__(self, repo: Repository, storage: PhotoStorage | None = None, places=None):
        self.repo, self.storage, self.places = repo, storage, places

    def moderate(self, actor, kind, id, status, reason):
        actor.require('moderator', 'admin')
        moderation_decision(status, reason)
        self.repo.get(kind, id, lock=True)
        result = self.repo.update(kind, id, dict(status=status, reason=reason.strip()))
        if kind == 'places':
            result = self.repo.update(kind, id, {'updated_at': datetime.now(timezone.utc)})
        self.repo.audit(actor.id, status, f'{kind}:{id}', reason)
        return result

    def admin_list(self, actor, kind, page, status=None, place_id=None, q=""):
        actor.require('admin') if kind in {'users', 'audit', 'categories'} else actor.require('moderator', 'admin')
        filters = {'status': status} if status and kind in {'places', 'photos', 'reviews', 'reports'} else {}
        if place_id is not None:
            if kind != 'photos':
                raise DomainError('Фильтр места доступен только для фотографий')
            filters['place_id'] = place_id
        if kind == 'places' and q.strip(): filters['q'] = q.strip()
        if kind == 'users': filters['deleted'] = False
        result = self.repo.list(kind, filters, page)
        if kind == 'users':
            for u in result['items']:
                u.pop('password_hash')
        return result

    def category(self, actor, data, id=None):
        actor.require('admin')
        result = self.repo.update('categories', id, data) if id else self.repo.add('categories', data)
        self.repo.audit(actor.id, 'category.update', f"categories:{result['id']}", str(data))
        return result


    def delete_category(self, actor, id):
        actor.require('admin')
        category = self.repo.get('categories', id, lock=True)
        if self.repo.category_in_use(id):
            raise DomainError('Категория используется местами. Сначала смените их категорию.', 409)
        self.repo.delete('categories', {'id': id})
        self.repo.audit(actor.id, 'category.delete', f'categories:{id}', category['name'])
        return {'ok': True}

    def edit_description(self, actor, id, description, expected_description):
        actor.require('moderator', 'admin')
        place = self.repo.get('places', id, lock=True)
        if expected_description is not None and (place['description'] or '') != expected_description:
            raise DomainError('Описание уже изменено. Откройте карточку заново перед сохранением.', 409)
        result = self.repo.update('places', id, dict(description=description, updated_at=datetime.now(timezone.utc)))
        import json
        self.repo.audit(actor.id, 'description.update', f'places:{id}',
                        json.dumps({'before':place['description'], 'after':description}, ensure_ascii=False))
        return result

    def edit_place(self, actor, id, data):
        actor.require('moderator', 'admin')
        place = self.repo.get('places', id, lock=True)
        if place['updated_at'] != data['expected_updated_at']:
            raise DomainError('Место уже изменено. Откройте карточку заново перед сохранением.', 409)
        if data.get('name') is not None and len(data['name'].strip()) < 3:
            raise DomainError('Название должно содержать не менее 3 символов')
        address = data['address']
        values = dict(description=data['description'], latitude=data['latitude'], longitude=data['longitude'],
                      full_address=address, region=address[:200], updated_at=datetime.now(timezone.utc))
        if data.get('category_id') is not None:
            category = self.repo.get('categories', data['category_id'])
            if not category['active'] and data['category_id'] != place['category_id']:
                raise DomainError('Категория недоступна для выбора')
            values.update(category_id=category['id'], category=category['name'])
        if data.get('name') is not None: values['name'] = data['name'].strip()
        result = self.repo.update('places', id, values)
        import json
        self.repo.audit(actor.id, 'place.update', f'places:{id}', json.dumps(
            {'before':{k:place.get(k) for k in values}, 'after':values}, default=str, ensure_ascii=False))
        return result
