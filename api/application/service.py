"""Application facade; domain-specific use cases live in separate modules."""
from .ports import Repository, PhotoStorage
from .places import PlacesService
from .reviews import ReviewsService
from .itineraries import ItinerariesService
from .moderation import ModerationService


class Service:
    def __init__(self, repo: Repository, storage: PhotoStorage):
        self.repo = repo
        self.places = PlacesService(repo, storage)
        self.itineraries = ItinerariesService(repo,self.places)
        self.reviews = ReviewsService(repo, places=self.places)
        self.moderation = ModerationService(repo)

    def personal(self, actor, kind, page, pending_only=False, status=None):
        if kind == 'favorites':
            return self.repo.search({'favorite_user': actor.id, 'page': page})
        filters = {'author_id': actor.id}
        if kind == 'places':
            if pending_only:
                filters['status'] = 'pending'
            elif status:
                filters['status'] = status
        return self.repo.list(kind, filters, page)

    def categories(self, page):
        return self.repo.list('categories', {'active': True}, page)
