from datetime import datetime
from zoneinfo import ZoneInfo
from urbex.domain.rules import DomainError


class ItinerariesService:
    def __init__(self, repo, places):
        self.repo, self.places = repo, places

    def owned(self, actor, id, lock=False):
        route = self.repo.get('itineraries', id, lock=lock)
        if route['author_id'] != actor.id:
            raise DomainError('Маршрут не найден', 404)
        return route

    def detail(self, actor, id):
        route = self.owned(actor,id)
        items = []
        for stop in route['stops']:
            try:
                place = self.places.place(stop['place_id'])
            except DomainError as error:
                if error.status != 404: raise
                place = None
            items.append(dict(stop,place=place))
        return dict(route,items=items)

    def save(self, actor, data, id=None):
        self.repo.get("users", actor.id, lock=True)
        data = dict(data)
        version = data.pop('version',None)
        old = self.owned(actor,id,lock=True) if id else None
        if old and version != old['version']:
            raise DomainError('Маршрут изменён. Откройте его заново.',409)
        previous = {s['place_id'] for s in old['stops']} if old else set()
        for stop in data['stops']:
            if stop['place_id'] not in previous:
                self.places.place(stop['place_id'])
                self.places.favorite(actor, stop['place_id'], True)
        data['version'] = old['version']+1 if old else 1
        if old:return self.repo.update('itineraries',id,data)
        return self.repo.add('itineraries',dict(data,author_id=actor.id))

    def activate(self, actor, id, active):
        self.repo.get('users', actor.id, lock=True)
        self.owned(actor, id, lock=True)
        if active: self.repo.clear_active_itineraries(actor.id)
        return self.repo.update('itineraries', id, {'active': active})

    def remove(self, actor, id):
        self.repo.get('users', actor.id, lock=True)
        self.owned(actor,id,lock=True)
        self.repo.delete('itineraries',{'id':id,'author_id':actor.id})
        return {'ok':True}

    def add_to_active(self, actor, place_id):
        self.repo.get('users', actor.id, lock=True)
        self.places.place(place_id)
        routes = self.repo.list('itineraries', {'author_id': actor.id, 'active': True})['items']
        route = routes[0] if routes else None
        if route and any(s['place_id'] == place_id for s in route['stops']):
            return {'route_id': route['id'], 'name': route['name'], 'already_added': True}
        if route and len(route['stops']) >= 50:
            raise DomainError('В активном маршруте уже 50 мест. Выберите другой маршрут.', 409)
        stop = {'place_id': place_id, 'note': '', 'status': 'planned'}
        if route:
            route = self.save(actor, dict(name=route['name'], trip_date=route['trip_date'],
                notes=route['notes'], stops=[*route['stops'], stop], version=route['version']), route['id'])
        else:
            date = datetime.now(ZoneInfo('Europe/Moscow')).strftime('%d.%m.%Y')
            route = self.save(actor, dict(name=f'Маршрут {date}', stops=[stop]))
            self.activate(actor, route['id'], True)
        return {'route_id': route['id'], 'name': route['name'], 'already_added': False}

    def active_place_state(self, actor, place_id):
        routes = self.repo.list('itineraries', {'author_id': actor.id, 'active': True})['items']
        route = routes[0] if routes else None
        return {'added': bool(route and any(s['place_id'] == place_id for s in route['stops']))}

    def remove_from_active(self, actor, place_id):
        self.repo.get('users', actor.id, lock=True)
        routes = self.repo.list('itineraries', {'author_id': actor.id, 'active': True})['items']
        if routes:
            route = routes[0]
            stops = [s for s in route['stops'] if s['place_id'] != place_id]
            if len(stops) != len(route['stops']):
                self.repo.update('itineraries', route['id'], {'stops': stops, 'version': route['version'] + 1})
        return {'added': False}
