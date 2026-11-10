from urbex_shared.catalog import published_filter
from decimal import Decimal
import json
from sqlalchemy.orm import object_session
from sqlalchemy import select, func, delete, text, Numeric, bindparam, Integer, case, or_
from sqlalchemy.dialects.postgresql import ARRAY
from urbex.domain.rules import DomainError
from .locations import component_filter, resolve_locations
from .models import MODELS, Place, Favorite, Category


def serialize(obj):
    values = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    if isinstance(obj, Place) and obj.category_id:
        session = object_session(obj)
        category = session.get(Category, obj.category_id) if session else None
        if category:
            values.update(category=category.name, category_icon=category.icon)
    return {key: float(value) if isinstance(value, Decimal) else value for key, value in values.items()}


class SqlRepository:
    def __init__(self, session, search=None):
        self.session = session
        self.text_search = search
        self._text_matches = {}

    def enqueue_event(self, routing_key, message):
        # The request commits this insert together with the photo update.
        self.session.execute(text(
            "INSERT INTO photo_event_outbox (routing_key, payload) "
            "VALUES (:routing_key, CAST(:payload AS jsonb))"
        ), {'routing_key': routing_key, 'payload': json.dumps(message)})

    def clear_active_itineraries(self, author_id):
        self.session.execute(text('UPDATE web_itineraries SET active=false WHERE author_id=:id AND active'), {'id': author_id})
        self.session.expire_all()

    def telegram_user(self, telegram_id, name, password_hash):
        self.session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('telegram_auth:' || CAST(:id AS text),0))"), {'id':telegram_id})
        users=self.list('users',{'telegram_id':telegram_id})['items']
        return users[0] if users else self.add('users',dict(telegram_id=telegram_id,email=None,name=name or 'Telegram',password_hash=password_hash,role='user'))

    def get(self, kind, id, lock=False):
        if kind == 'reviews' and id < 0:
            row = self.session.execute(text("SELECT -id AS id,place_id,NULL::integer AS author_id,user_name AS author_name,text,NULL::integer AS score,status,reason,created_at,'telegram' AS source FROM place_reviews WHERE id=:id" + (' FOR UPDATE' if lock else '')), {'id':-id}).mappings().first()
            if row is None:raise DomainError('Отзыв не найден',404)
            return dict(row)
        if kind == 'photos' and id < 0:
            photo = self.session.execute(text("SELECT -id AS id, place_id, NULL::integer AS author_id, status, reason, file_id FROM place_photos WHERE id=:id"), {'id': -id}).mappings().first()
            if photo is None:
                raise DomainError('Фотография не найдена', 404)
            return dict(photo)
        model = MODELS[kind]
        q = select(model).where(model.id == id)
        if lock:
            q = q.with_for_update()
        obj = self.session.scalar(q)
        if obj is None:
            raise DomainError('Объект не найден', 404)
        return serialize(obj)

    def add(self, kind, values):
        if kind == "telegram_logins":
            self.session.execute(text("DELETE FROM web_telegram_logins WHERE expires_at < now()"))
        obj = MODELS[kind](**values)
        self.session.add(obj)
        self.session.flush()
        return serialize(obj)

    def update(self, kind, id, values):
        if kind == 'reviews' and id < 0:
            if not set(values) <= {'status','reason'}:raise ValueError('Unsupported review update')
            self.session.execute(text('UPDATE place_reviews SET '+','.join(f'{k}=:{k}' for k in values)+' WHERE id=:id'),dict(values,id=-id))
            return self.get(kind,id)
        if kind == 'photos' and id < 0:
            if not set(values) <= {'status', 'reason'}:
                raise ValueError('Unsupported Telegram photo update')
            assignments = ','.join(f'{key}=:{key}' for key in values)
            self.session.execute(text('UPDATE place_photos SET '+assignments+' WHERE id=:photo_id'), dict(values, photo_id=-id))
            photo = self.get(kind, id)
            photo.pop('file_id', None)
            return photo
        obj = self.session.get(MODELS[kind], id)
        if obj is None:
            raise DomainError('Объект не найден', 404)
        for k, v in values.items():
            setattr(obj, k, v)
        self.session.flush()
        return serialize(obj)

    def list(self, kind, filters, page=1):
        if kind == 'reviews':
            query = """SELECT id,place_id,author_id,NULL::text AS author_name,text,score,status,reason,created_at,'website' AS source FROM web_reviews
                UNION ALL SELECT -id,place_id,NULL::integer,user_name,text,NULL::integer,status,reason,created_at,'telegram' FROM place_reviews"""
            if not set(filters) <= {'place_id','author_id','status','source'}:raise ValueError('Unsupported review filter')
            where = ' AND '.join(f'{k}=:{k}' for k in filters) or 'true'
            where += " AND NOT (status='rejected' AND COALESCE(reason, '')='Удалено модератором')"
            params=dict(filters,offset=(page-1)*30)
            total=self.session.scalar(text('SELECT count(*) FROM ('+query+') r WHERE '+where),params)
            rows=self.session.execute(text('SELECT * FROM ('+query+') r WHERE '+where+' ORDER BY created_at DESC,id DESC LIMIT 30 OFFSET :offset'),params).mappings()
            return {'items':[dict(r) for r in rows],'total':total,'page':page}
        if kind == 'photos':
            query = """SELECT id, place_id, author_id, status, reason, created_at FROM web_photos
                UNION ALL SELECT -id, place_id, NULL::integer, status, reason, created_at FROM place_photos"""
            filters = dict(filters)
            visible_to = filters.pop('visible_to', None)
            staff = filters.pop('staff', False)
            allowed = {'place_id', 'author_id', 'status'}
            if not set(filters) <= allowed:
                raise ValueError('Unsupported photo filter')
            where = ' AND '.join(f'{key}=:{key}' for key in filters) or 'true'
            params = dict(filters, offset=(page-1)*30)
            if visible_to is not None:
                where += " AND (status='published' OR (status='pending' AND (:staff OR author_id=:visible_to)))"
                params.update(visible_to=visible_to, staff=staff)
            total = self.session.scalar(text('SELECT count(*) FROM ('+query+') photos WHERE '+where), params)
            items = self.session.execute(text('SELECT * FROM ('+query+') photos WHERE '+where+' ORDER BY created_at DESC, id DESC LIMIT 30 OFFSET :offset'), params).mappings().all()
            return {'items': [dict(row) for row in items], 'total': total, 'page': page}
        if kind == 'places' and filters.get('q'):
            filters = dict(filters)
            query = filters.pop('q')
            matches = self.search_matches({'q': query})
            document = func.to_tsvector('russian', func.concat_ws(' ', Place.name, Place.description, Place.full_address, Place.region))
            fulltext = document.op('@@')(func.plainto_tsquery('russian', query))
            conditions = [getattr(Place, k) == v for k, v in filters.items()]
            conditions.append(or_(matches.c.id.is_not(None), fulltext))
            conditions.append(~((Place.status == 'rejected') & (func.coalesce(Place.reason, '') == 'Удалено модератором')))
            source = select(Place).outerjoin(matches, Place.id == matches.c.id).where(*conditions)
            total = self.session.scalar(select(func.count()).select_from(source.subquery()))
            rows = self.session.scalars(source.order_by(matches.c.rank.asc().nulls_last(), Place.id.desc()).limit(30).offset((page-1)*30))
            return {'items': [serialize(row) for row in rows], 'total': total, 'page': page}
        model = MODELS[kind]
        conditions = [getattr(model, k) == v for k, v in filters.items()]
        if kind == 'places':
            conditions.append(~((Place.status == 'rejected') & (func.coalesce(Place.reason, '') == 'Удалено модератором')))
        total = self.session.scalar(select(func.count()).select_from(model).where(*conditions))
        ordering = [model.active.desc(), model.id.desc()] if kind == "itineraries" else [model.id.desc()]
        rows = self.session.scalars(select(model).where(*conditions).order_by(*ordering).limit(30).offset((page-1)*30))
        return {'items': [serialize(r) for r in rows], 'total': total, 'page': page}

    def category_in_use(self, id):
        # Include hidden and soft-deleted places, which still reference the category.
        return self.session.scalar(select(Place.id).where(Place.category_id == id).limit(1)) is not None

    def delete(self, kind, filters):
        model = MODELS[kind]
        self.session.execute(delete(model).where(*[getattr(model, k) == v for k, v in filters.items()]))

    def search_conditions(self, filters):
        p = dict(filters)
        conditions = [published_filter(Place)]
        if p.get('locality'):
            conditions.append(component_filter(p['locality']))
        if p.get('locality_bbox'):
            w,s,e,n = p['locality_bbox']
            conditions.extend([Place.longitude.between(w,e), Place.latitude.between(s,n)])
        for k in ('category_id', 'condition', 'region'):
            if p.get(k):
                conditions.append(getattr(Place, k) == p[k])
        if p.get('bbox'):
            west, south, east, north = p['bbox']
            if west <= east:
                conditions.append(text('geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)').bindparams(west=west,south=south,east=east,north=north))
            else:
                conditions.append(text('(geom && ST_MakeEnvelope(:west,:south,180,:north,4326) OR geom && ST_MakeEnvelope(-180,:south,:east,:north,4326))').bindparams(west=west,south=south,east=east,north=north))
        if p.get('near_lon') is not None:
            conditions.append(text('ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, :radius)').bindparams(lon=p['near_lon'],lat=p['near_lat'],radius=p['radius_km']*1000))
        if p.get('favorite_user'):
            conditions.append(Place.id.in_(select(Favorite.place_id).where(Favorite.user_id == p['favorite_user'])))
        return conditions

    def locations(self, query):
        return resolve_locations(self.session, query)

    def search_matches(self, filters):
        query = filters.get('q', '').strip()
        if not query:
            return None
        if self.text_search is None:
            raise DomainError('Поисковый сервис не настроен', 503)
        key = (query, filters.get('search_in', 'all'))
        if key not in self._text_matches:
            self._text_matches[key] = self.text_search.ids(query, key[1])
        # An array parameter and an ordinal relation keep ordering efficient even
        # for large result sets; no truncation to 1000 or 10000 matches.
        return func.unnest(bindparam('search_ids', self._text_matches[key], type_=ARRAY(Integer))).table_valued(
            'id', with_ordinality='rank').render_derived(name='search_matches')

    def search(self, filters):
        p = dict(filters)
        conditions = self.search_conditions(p)
        matches = self.search_matches(p)
        count_query = select(func.count()).select_from(Place)
        # Apply category priority before LIMIT/OFFSET, across the entire result
        # set. Keep ES relevance (or newest first) within each category group.
        category_name = func.lower(func.trim(func.coalesce(Category.name, Place.category, '')))
        geocaching_last = case((category_name.in_(['geocaching', 'геокешинг', 'геокэшинг']), 1), else_=0)
        rows_query = select(Place).outerjoin(Category, Place.category_id == Category.id).order_by(geocaching_last)
        if matches is not None:
            count_query = count_query.join(matches, Place.id == matches.c.id)
            rows_query = rows_query.join(matches, Place.id == matches.c.id).order_by(matches.c.rank)
        else:
            rows_query = rows_query.order_by(Place.id.desc())
        total = self.session.scalar(count_query.where(*conditions))
        page, limit = p.get('page', 1), p.get('limit', 30)
        rows = self.session.scalars(rows_query.where(*conditions).limit(limit).offset((page-1)*limit))
        items = [serialize(r) for r in rows]
        if items:
            stats = self.session.execute(text("""
                SELECT p.id,
                    (SELECT count(*) FROM place_ratings r WHERE r.place_id=p.id) AS telegram_rating_count,
                    (SELECT coalesce(sum(score),0) FROM place_ratings r WHERE r.place_id=p.id) AS telegram_rating_sum,
                    (SELECT count(*) FROM place_reviews r WHERE r.place_id=p.id AND r.status='published') AS reviews_count,
                    (SELECT count(*) FROM web_photos f WHERE f.place_id=p.id AND f.status='published')
                    + (SELECT count(*) FROM place_photos f WHERE f.place_id=p.id AND f.status='published') AS photos_count,
                    (SELECT count(*) FROM web_reviews r WHERE r.place_id=p.id AND r.status='published') AS web_rating_count,
                    (SELECT coalesce(sum(score),0) FROM web_reviews r WHERE r.place_id=p.id AND r.status='published') AS web_rating_sum
                FROM places p WHERE p.id = ANY(:ids)
            """), {'ids': [p['id'] for p in items]}).mappings()
            by_id = {r['id']: r for r in stats}
            for item in items:
                stat = by_id[item['id']]
                count = stat['telegram_rating_count'] + stat['web_rating_count']
                average = ((stat['telegram_rating_sum'] + stat['web_rating_sum']) / count) if count else 0
                item.update(reviews_count=stat['reviews_count'], photos_count=stat['photos_count'],
                            rating_count=count, rating_avg=round(float(average), 2))
        return {'items': items, 'total': total, 'page': page}

    def audit(self, actor, action, target, detail):
        self.add('audit', dict(actor_id=actor, action=action, target=target, detail=detail))

    def rate_attempt(self, key):
        # Failed logins must count even when the request transaction rolls back.
        with self.session.bind.begin() as conn:
            conn.execute(text('DELETE FROM web_login_attempts WHERE expires_at < now()'))
            return conn.execute(text("""INSERT INTO web_login_attempts(key, attempts, expires_at)
                VALUES (:key,1,now()+interval '15 minutes') ON CONFLICT(key) DO UPDATE SET
                attempts=web_login_attempts.attempts+1 RETURNING attempts"""), {'key': key}).scalar_one()

    def map(self, filters, zoom):
        if not filters.get('cluster', True):
            query = select(Place.id, Place.longitude, Place.latitude,
                           Category.name.label('category'), Category.icon.label('category_icon')) \
                .outerjoin(Category, Place.category_id == Category.id).where(*self.search_conditions(filters))
            matches = self.search_matches(filters)
            if matches is not None:
                query = query.join(matches, Place.id == matches.c.id)
            features = [
                {'type': 'Feature', 'geometry': {'type': 'Point',
                 'coordinates': [float(row.longitude), float(row.latitude)]},
                 'properties': {'id': row.id, 'category': row.category or 'Другое', 'category_icon': row.category_icon}}
                for row in self.session.execute(query.order_by(Place.id))
            ]
            return {'type': 'FeatureCollection', 'features': features, 'total': len(features)}
        west, south, east, north = filters['bbox']
        width = east - west if west <= east else east + 360 - west
        # Adapt the grid to the viewport, bounding the response to at most 49x49 cells.
        # Aggregation happens in PostgreSQL, never by downloading all place records.
        step = max(360 / 2 ** (zoom + 3), width / 48, (north - south) / 48, 0.000001)
        longitude = Place.longitude if west <= east else func.mod(Place.longitude.cast(Numeric) + 360, 360)
        x = func.floor((longitude - west) / step)
        y = func.floor((Place.latitude - south) / step)
        query = select(
            func.count().label('count'), func.min(Place.id).label('id'),
            func.min(Category.name).label('category'),
            func.min(Category.icon).label('category_icon'),
            func.avg(longitude).label('lon'), func.avg(Place.latitude).label('lat'),
            func.min(longitude).label('west'), func.min(Place.latitude).label('south'),
            func.max(longitude).label('east'), func.max(Place.latitude).label('north'),
        ).outerjoin(Category, Place.category_id == Category.id).where(*self.search_conditions(filters)).group_by(x, y).order_by(x, y)
        matches = self.search_matches(filters)
        if matches is not None:
            query = query.join(matches, Place.id == matches.c.id)
        features, total = [], 0
        for row in self.session.execute(query).mappings():
            count = row['count']
            total += count
            lon = float(row['lon'])
            properties = {'id': row['id'], 'category': row['category'] or 'Другое', 'category_icon': row['category_icon']} if count == 1 else {
                'cluster': True, 'point_count': count, 'point_count_abbreviated': str(count),
                'west': float(row['west']), 'south': float(row['south']),
                'east': float(row['east']), 'north': float(row['north']),
            }
            features.append({'type': 'Feature', 'geometry': {'type': 'Point',
                'coordinates': [lon if lon <= 180 else lon - 360, float(row['lat'])]}, 'properties': properties})
        return {'type': 'FeatureCollection', 'features': features, 'total': total}
