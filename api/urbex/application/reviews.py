from .ports import Repository, PhotoStorage
from datetime import datetime, timezone
from urbex.domain.rules import DomainError, can_read, moderation_decision


class ReviewsService:
    def __init__(self, repo: Repository, storage: PhotoStorage | None = None, places=None):
        self.repo, self.storage, self.places = repo, storage, places

    def review(self, actor, id, data):
        p = self.places.place(id, actor)
        if p['status'] != 'published':
            raise DomainError('Место ещё не опубликовано')
        self.repo.get('users', actor.id, lock=True)
        existing = self.repo.list('reviews', dict(place_id=id, author_id=actor.id))['items']
        if existing:
            # Editing a hidden review cannot bypass a moderator's decision.
            status = 'published' if existing[0]['status'] == 'published' else 'pending'
            return self.repo.update('reviews', existing[0]['id'], dict(data, status=status))
        return self.repo.add('reviews', dict(data, place_id=id, author_id=actor.id))

    def report(self, actor, data):
        kind, id = data['target_type'], data['target_id']
        if kind == 'places':
            self.places.place(id, actor)
        else:
            target = self.repo.get(kind, id)
            self.places.place(target['place_id'], actor)
            if not can_read(target, actor):
                raise DomainError('Объект не найден', 404)
        return self.repo.add('reports', dict(data, author_id=actor.id))

