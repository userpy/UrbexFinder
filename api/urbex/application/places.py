from .ports import Repository, PhotoStorage
from datetime import datetime, timezone
from uuid import uuid4
from urbex.domain.rules import DomainError, can_read, moderation_decision


class PlacesService:
    def __init__(self, repo: Repository, storage: PhotoStorage | None = None, places=None):
        self.repo, self.storage, self.places = repo, storage, places

    def place(self, id, actor=None):
        p = self.repo.get('places', id)
        if not can_read(p, actor):
            raise DomainError('Объект не найден', 404)
        # Reasons are only useful to the submitting user and moderation staff.
        if not actor or (actor.id != p['author_id'] and actor.role == 'user'):
            p.pop('reason', None)
        return p

    def submit(self, actor, data, id=None):
        category = self.repo.get('categories', data['category_id'])
        if not category['active']:
            raise DomainError('Категория недоступна')
        values = dict(data, status='pending', reason='', updated_at=datetime.now(timezone.utc))
        if id:
            old = self.repo.get('places', id, lock=True)
            if old['author_id'] != actor.id:
                raise DomainError('Можно редактировать только свои заявки', 403)
            if old['status'] not in {'changes_requested', 'rejected'}:
                raise DomainError('Редактирование доступно после возврата заявки', 409)
            return self.repo.update('places', id, values)
        return self.repo.add('places', dict(values, author_id=actor.id))

    def related(self, kind, id, actor, page=1, source=None):
        self.place(id, actor)
        filters = {'place_id': id, 'status': 'published'}
        if kind == 'reviews' and source: filters['source'] = source
        return self.repo.list(kind, filters, page)

    def favorite(self, actor, id, enabled):
        p = self.place(id, actor)
        if p['status'] != 'published':
            raise DomainError('Место ещё не опубликовано')
        self.repo.get('users', actor.id, lock=True)
        filters = dict(user_id=actor.id, place_id=id)
        self.repo.delete('favorites', filters)
        if enabled:
            self.repo.add('favorites', filters)
        return {'saved': enabled}

    def photo(self, actor, id, jpeg):
        self.place(id, actor)
        self.repo.get('places', id, lock=True)
        if self.repo.list('photos', {'place_id': id})['total'] >= 20:
            raise DomainError('Для места допускается до 20 фотографий', 409)
        key = f'photos/{uuid4().hex}.jpg'
        self.storage.put(key, jpeg)
        return self.repo.add('photos', dict(place_id=id, author_id=actor.id, object_key=key))

    def photo_bytes(self, id, actor):
        photo = self.repo.get('photos', id)
        self.place(photo['place_id'], actor)
        if not can_read(photo, actor):
            raise DomainError('Фотография не найдена', 404)
        if photo.get('file_id'):
            return self.storage.get_telegram(photo['file_id'])
        return self.storage.get(photo['object_key'])

    def favorite_state(self, actor, id):
        self.place(id, actor)
        return {"saved": bool(self.repo.list("favorites", {"user_id": actor.id, "place_id": id})["total"])}

    def search(self, filters):
        return self.repo.search(filters)

    def map(self, filters, zoom):
        return self.repo.map(filters, zoom)

    def locations(self, query):
        return self.repo.locations(query)
