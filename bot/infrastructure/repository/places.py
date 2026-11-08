import asyncio
import csv
from pathlib import Path
from typing import Optional, TypedDict

from loguru import logger
from urbex_shared.catalog import published_filter
from sqlalchemy import case, delete, func, select, update, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.models import Place as PlaceModel
from domain.models import PlaceNonexistentReport as PlaceNonexistentReportModel
from domain.models import PlacePhoto as PlacePhotoModel
from domain.models import PlaceRating as PlaceRatingModel
from domain.models import PlaceReview as PlaceReviewModel
from domain.decimal6 import d6 as Decimal6
from infrastructure.services.reverse_geocode import reverse_geocode


class Place(TypedDict):
    id: int
    name: str
    description: str | None
    type: str
    latitude: float
    longitude: float
    category: str
    full_address: str
    distance_km: float | None
    rating_avg: float
    rating_count: int
    rating_score: float
    nonexistent_reports_count: int


class PlacesRepository:
    _MERGE_FIELDS = ("name", "description", "type", "category", "full_address")
    _NONEXISTENT_REPORTS_HIDE_THRESHOLD = 10

    def __init__(self, async_session: async_sessionmaker[AsyncSession]):
        self.async_session = async_session

    async def import_places_csv(self, path, dry_run=False):
        from infrastructure.services.places_csv import read_places
        async with self.async_session() as session:
            async with session.begin():
                await session.execute(text('SELECT pg_advisory_xact_lock(734836210)'))
                existing = set((await session.execute(select(PlaceModel.latitude, PlaceModel.longitude))).all())
                categories = {}
                inserted = skipped = 0
                batch = []
                for values in read_places(path):
                    coordinates = (values['latitude'], values['longitude'])
                    if coordinates in existing:
                        skipped += 1
                        continue
                    existing.add(coordinates)
                    inserted += 1
                    if dry_run:
                        continue
                    category = values['category']
                    if category not in categories:
                        await session.execute(text('INSERT INTO web_categories(name) VALUES (:name) ON CONFLICT(name) DO NOTHING'), {'name':category})
                        categories[category] = await session.scalar(text('SELECT id FROM web_categories WHERE name=:name'), {'name':category})
                    values.update(category_id=categories[category], region=(values['full_address'] or 'Не указан')[:200], status='published')
                    batch.append(values)
                    if len(batch) >= 500:
                        await session.execute(insert(PlaceModel), batch)
                        batch = []
                if batch:
                    await session.execute(insert(PlaceModel), batch)
                return {'new':inserted, 'skipped':skipped, 'dry_run':dry_run}

    async def update_full_addresses_from_csv(self, csv_path: str | Path) -> int:
        rows = await asyncio.to_thread(self._read_full_address_csv, Path(csv_path))
        if not rows:
            return 0

        updated_count = 0
        async with self.async_session() as session:
            async with session.begin():
                for lat, lon, full_address in rows:
                    stmt = (
                        update(PlaceModel)
                        .where(PlaceModel.latitude == lat)
                        .where(PlaceModel.longitude == lon)
                        .where(
                            (PlaceModel.full_address.is_(None))
                            | (PlaceModel.full_address == "")
                        )
                        .values(full_address=full_address)
                    )
                    result = await session.execute(stmt)
                    updated_count += result.rowcount or 0

        return updated_count

    @staticmethod
    def _read_full_address_csv(csv_path: Path) -> list[tuple[object, object, str]]:
        if not csv_path.exists():
            logger.info(f"[INFO] full_address csv not found: {csv_path}")
            return []

        rows: list[tuple[object, object, str]] = []
        with csv_path.open(newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            for row_number, row in enumerate(reader, start=2):
                try:
                    full_address = (row.get("full_address") or "").strip()
                    if not full_address:
                        continue

                    lat = Decimal6(row.get("lat") or row.get("latitude"))
                    lon = Decimal6(row.get("lon") or row.get("longitude"))
                    if lat is None or lon is None:
                        continue

                    rows.append((lat, lon, full_address))
                except Exception as e:
                    logger.info(f"[ERROR] invalid full_address csv row={row_number}: {e}")

        return rows

    async def update_all_full_addresses(self, batch_size: int = 50) -> None:
        async with self.async_session() as session:
            q = (
                select(PlaceModel)
                .where(PlaceModel.latitude.isnot(None))
                .where(PlaceModel.longitude.isnot(None))
                .where(
                    (PlaceModel.full_address.is_(None))
                    | (PlaceModel.full_address == "")
                )
            )
            res = await session.execute(q)
            places = res.scalars().all()

        for place in places:
            try:
                full_address = await reverse_geocode(place.latitude, place.longitude)
                if not full_address:
                    continue

                async with self.async_session() as session:
                    stmt = (
                        update(PlaceModel)
                        .where(PlaceModel.id == place.id)
                        .values(full_address=full_address.get("display_name"))
                    )
                    await session.execute(stmt)
                    await session.commit()
                    logger.info(f"[INFO] updated full_address {place.id}")
                await asyncio.sleep(1)
            except Exception as e:
                logger.info(f"[ERROR] place_id={place.id}: {e}")

    async def add_or_update_place(
        self,
        name: str,
        description: Optional[str] = None,
        type_: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        category: Optional[str] = None,
    ) -> Optional[int]:
        if latitude is None or longitude is None:
            return None

        async with self.async_session() as session:
            async with session.begin():
                q = (
                    select(PlaceModel)
                    .where(PlaceModel.latitude == Decimal6(latitude))
                    .where(PlaceModel.longitude == Decimal6(longitude))
                )
                res = await session.execute(q)
                existing = res.scalars().first()
                if existing:
                    logger.info(f"[INFO] updated place * {existing.latitude} > {Decimal6(latitude)}")
                    existing.name = name
                    existing.description = description
                    existing.type = type_
                    existing.latitude = latitude
                    existing.longitude = longitude
                    existing.category = category
                    await session.flush()
                    return existing.id

                logger.info(f"[INFO] created place {name}")
                new_place = PlaceModel(
                    status="published",
                    name=name,
                    description=description,
                    type=type_,
                    latitude=latitude,
                    longitude=longitude,
                    category=category,
                )
                session.add(new_place)
                await session.flush()
                return new_place.id

        return None

    async def deduplicate_by_coordinates(self) -> int:
        async with self.async_session() as session:
            async with session.begin():
                res = await session.execute(
                    select(PlaceModel)
                    .where(PlaceModel.latitude.isnot(None))
                    .where(PlaceModel.longitude.isnot(None))
                    .order_by(PlaceModel.id.asc())
                )
                places = res.scalars().all()

                first_place_by_coords: dict[tuple[float, float], PlaceModel] = {}
                duplicate_ids: list[int] = []

                for place in places:
                    coords = (place.latitude, place.longitude)
                    first_place = first_place_by_coords.get(coords)

                    if first_place is None:
                        first_place_by_coords[coords] = place
                        continue

                    if (first_place.status != place.status or first_place.author_id != place.author_id
                            or first_place.telegram_author_id != place.telegram_author_id):
                        continue
                    # Never delete a record with photos, social data or web history.
                    references = await session.execute(text("""SELECT c.conrelid::regclass::text AS table_name,
                        a.attname AS column_name FROM pg_constraint c
                        JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=ANY(c.conkey)
                        WHERE c.contype='f' AND c.confrelid='places'::regclass"""))
                    linked = False
                    quote = session.bind.dialect.identifier_preparer.quote
                    for ref in references:
                        if await session.scalar(text(f'SELECT EXISTS(SELECT 1 FROM {quote(ref.table_name)} WHERE {quote(ref.column_name)}=:id)'), {'id': place.id}):
                            linked = True
                            break
                    if not linked and await session.scalar(text("SELECT to_regclass('web_audit')")):
                        linked = bool(await session.scalar(text("SELECT EXISTS(SELECT 1 FROM web_audit WHERE target=:target)"), {'target': f'places:{place.id}'}))
                    if not linked and await session.scalar(text("SELECT to_regclass('web_reports')")):
                        linked = bool(await session.scalar(text("SELECT EXISTS(SELECT 1 FROM web_reports WHERE target_type='places' AND target_id=:id)"), {'id': place.id}))
                    if linked:
                        continue
                    self._merge_missing_fields(target=first_place, source=place)
                    duplicate_ids.append(place.id)

                if duplicate_ids:
                    await session.execute(
                        delete(PlaceModel).where(PlaceModel.id.in_(duplicate_ids))
                    )

                return len(duplicate_ids)

    def _merge_missing_fields(self, target: PlaceModel, source: PlaceModel) -> None:
        for field in self._MERGE_FIELDS:
            target_value = getattr(target, field)
            source_value = getattr(source, field)
            if target_value in (None, "") and source_value not in (None, ""):
                setattr(target, field, source_value)

    @staticmethod
    def _serialize_place(place: PlaceModel, distance_km: float | None = None) -> Place:
        payload = dict(
            id=place.id,
            name=place.name,
            description=place.description,
            type=place.type,
            latitude=place.latitude,
            longitude=place.longitude,
            category=place.category,
            full_address=place.full_address,
            rating_avg=float(place.rating_avg or 0),
            rating_count=int(place.rating_count or 0),
            rating_score=float(place.rating_score or 0),
            nonexistent_reports_count=int(place.nonexistent_reports_count or 0),
        )
        if distance_km is not None:
            payload["distance_km"] = float(distance_km)
        return payload

    @classmethod
    def _visible_places_filter(cls):
        return published_filter(PlaceModel)

    async def _recalculate_place_rating(self, session: AsyncSession, place_id: int) -> None:
        ratings_stats = await session.execute(
            select(
                func.coalesce(func.avg(PlaceRatingModel.score), 0.0).label("avg"),
                func.count(PlaceRatingModel.id).label("count"),
            ).where(PlaceRatingModel.place_id == place_id)
        )
        row = ratings_stats.one()
        rating_avg = float(row.avg or 0.0)
        rating_count = int(row.count or 0)

        global_avg_raw = await session.scalar(select(func.avg(PlaceRatingModel.score)))
        global_avg = float(global_avg_raw or 0.0)
        min_votes = 10.0
        weighted = (
            (rating_count / (rating_count + min_votes)) * rating_avg
            + (min_votes / (rating_count + min_votes)) * global_avg
            if rating_count > 0
            else 0.0
        )

        await session.execute(
            update(PlaceModel)
            .where(PlaceModel.id == place_id)
            .values(
                rating_avg=round(rating_avg, 2),
                rating_count=rating_count,
                rating_score=round(weighted, 3),
            )
        )

    async def upsert_place_rating(self, place_id: int, user_id: int, score: int) -> bool:
        if score < 0 or score > 5:
            return False

        async with self.async_session() as session:
            async with session.begin():
                place_exists = await session.scalar(
                    select(PlaceModel.id).where(PlaceModel.id == place_id)
                )
                if place_exists is None:
                    return False

                if score == 0:
                    await session.execute(
                        delete(PlaceRatingModel)
                        .where(PlaceRatingModel.place_id == place_id)
                        .where(PlaceRatingModel.user_id == user_id)
                    )
                else:
                    stmt = (
                        insert(PlaceRatingModel)
                        .values(place_id=place_id, user_id=user_id, score=score)
                        .on_conflict_do_update(
                            constraint="uq_place_ratings_place_user",
                            set_={"score": score},
                        )
                    )
                    await session.execute(stmt)
                await self._recalculate_place_rating(session, place_id)
                return True

    async def get_user_place_rating(self, place_id: int, user_id: int) -> Optional[int]:
        async with self.async_session() as session:
            return await session.scalar(
                select(PlaceRatingModel.score)
                .where(PlaceRatingModel.place_id == place_id)
                .where(PlaceRatingModel.user_id == user_id)
            )

    async def get_user_ratings_count(self, user_id: int) -> int:
        async with self.async_session() as session:
            count = await session.scalar(
                select(func.count(PlaceRatingModel.id)).where(
                    PlaceRatingModel.user_id == user_id
                )
            )
            return int(count or 0)

    async def report_place_nonexistent(self, place_id: int, user_id: int) -> dict:
        async with self.async_session() as session:
            async with session.begin():
                place_exists = await session.scalar(
                    select(PlaceModel.id).where(PlaceModel.id == place_id)
                )
                if place_exists is None:
                    return {"added": False, "count": 0, "hidden": False, "not_found": True}

                stmt = (
                    insert(PlaceNonexistentReportModel)
                    .values(place_id=place_id, user_id=user_id)
                    .on_conflict_do_nothing(
                        constraint="uq_place_nonexistent_reports_place_user",
                    )
                )
                result = await session.execute(stmt)
                added = bool(result.rowcount)

                if added:
                    count = int(
                        await session.scalar(
                            update(PlaceModel)
                            .where(PlaceModel.id == place_id)
                            .values(
                                nonexistent_reports_count=PlaceModel.nonexistent_reports_count + 1
                            )
                            .returning(PlaceModel.nonexistent_reports_count)
                        )
                        or 0
                    )
                else:
                    count = int(
                        await session.scalar(
                            select(PlaceModel.nonexistent_reports_count).where(PlaceModel.id == place_id)
                        )
                        or 0
                    )

                return {
                    "added": added,
                    "count": count,
                    "hidden": count >= self._NONEXISTENT_REPORTS_HIDE_THRESHOLD,
                    "not_found": False,
                }

    async def user_reported_place_nonexistent(self, place_id: int, user_id: int) -> bool:
        async with self.async_session() as session:
            report_id = await session.scalar(
                select(PlaceNonexistentReportModel.id)
                .where(PlaceNonexistentReportModel.place_id == place_id)
                .where(PlaceNonexistentReportModel.user_id == user_id)
            )
            return report_id is not None

    async def cancel_place_nonexistent_report(self, place_id: int, user_id: int) -> dict:
        async with self.async_session() as session:
            async with session.begin():
                place_exists = await session.scalar(
                    select(PlaceModel.id).where(PlaceModel.id == place_id)
                )
                if place_exists is None:
                    return {"deleted": False, "count": 0, "hidden": False, "not_found": True}

                result = await session.execute(
                    delete(PlaceNonexistentReportModel)
                    .where(PlaceNonexistentReportModel.place_id == place_id)
                    .where(PlaceNonexistentReportModel.user_id == user_id)
                )
                deleted = bool(result.rowcount)

                if deleted:
                    count = int(
                        await session.scalar(
                            update(PlaceModel)
                            .where(PlaceModel.id == place_id)
                            .values(
                                nonexistent_reports_count=func.greatest(
                                    PlaceModel.nonexistent_reports_count - 1,
                                    0,
                                )
                            )
                            .returning(PlaceModel.nonexistent_reports_count)
                        )
                        or 0
                    )
                else:
                    count = int(
                        await session.scalar(
                            select(PlaceModel.nonexistent_reports_count).where(PlaceModel.id == place_id)
                        )
                        or 0
                    )

                return {
                    "deleted": deleted,
                    "count": count,
                    "hidden": count >= self._NONEXISTENT_REPORTS_HIDE_THRESHOLD,
                    "not_found": False,
                }

    async def add_place_review(
        self,
        place_id: int,
        user_id: int,
        text: str,
        user_name: str | None = None,
    ) -> bool:
        text = (text or "").strip()
        if not text:
            return False

        async with self.async_session() as session:
            async with session.begin():
                place_exists = await session.scalar(
                    select(PlaceModel.id).where(PlaceModel.id == place_id)
                )
                if place_exists is None:
                    return False
                session.add(
                    PlaceReviewModel(
                        place_id=place_id,
                        user_id=user_id,
                        user_name=user_name,
                        text=text,
                    )
                )
                return True

    async def get_recent_reviews(self, place_id: int, limit: int = 3) -> list[dict]:
        async with self.async_session() as session:
            res = await session.execute(
                select(PlaceReviewModel)
                .where(PlaceReviewModel.place_id == place_id)
                .where(PlaceReviewModel.status == 'published')
                .order_by(PlaceReviewModel.created_at.desc(), PlaceReviewModel.id.desc())
                .limit(limit)
            )
            rows = []
            for review in res.scalars().all():
                rows.append(
                    {
                        "id": review.id,
                        "user_id": review.user_id,
                        "user_name": review.user_name,
                        "text": review.text,
                        "created_at": review.created_at,
                    }
                )
            return rows

    async def get_reviews_count(self, place_id: int) -> int:
        async with self.async_session() as session:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(PlaceReviewModel)
                    .where(PlaceReviewModel.place_id == place_id)
                .where(PlaceReviewModel.status == 'published')
                )
                or 0
            )

    async def get_reviews_page(self, place_id: int, limit: int = 5, offset: int = 0) -> dict:
        offset = max(0, offset)
        async with self.async_session() as session:
            total = int(
                await session.scalar(
                    select(func.count())
                    .select_from(PlaceReviewModel)
                    .where(PlaceReviewModel.place_id == place_id)
                .where(PlaceReviewModel.status == 'published')
                )
                or 0
            )
            res = await session.execute(
                select(PlaceReviewModel)
                .where(PlaceReviewModel.place_id == place_id)
                .where(PlaceReviewModel.status == 'published')
                .order_by(PlaceReviewModel.created_at.desc(), PlaceReviewModel.id.desc())
                .limit(limit)
                .offset(offset)
            )
            items = []
            for review in res.scalars().all():
                items.append(
                    {
                        "id": review.id,
                        "user_id": review.user_id,
                        "user_name": review.user_name,
                        "text": review.text,
                        "created_at": review.created_at,
                    }
                )
            return {"total": total, "items": items}

    async def delete_place_review(self, review_id: int, user_id: int) -> bool:
        async with self.async_session() as session:
            async with session.begin():
                review_exists = await session.scalar(
                    select(PlaceReviewModel.id)
                    .where(PlaceReviewModel.id == review_id)
                    .where(PlaceReviewModel.user_id == user_id)
                )
                if review_exists is None:
                    return False
                await session.execute(
                    delete(PlaceReviewModel)
                    .where(PlaceReviewModel.id == review_id)
                    .where(PlaceReviewModel.user_id == user_id)
                )
                return True

    async def delete_all_user_reviews(self, place_id: int, user_id: int) -> int:
        async with self.async_session() as session:
            async with session.begin():
                result = await session.execute(
                    delete(PlaceReviewModel)
                    .where(PlaceReviewModel.place_id == place_id)
                    .where(PlaceReviewModel.user_id == user_id)
                )
                return int(result.rowcount or 0)

    async def add_place_photo(
        self,
        place_id: int,
        user_id: int,
        file_id: str,
        caption: str | None = None,
        user_name: str | None = None,
    ) -> bool:
        if not file_id:
            return False

        async with self.async_session() as session:
            async with session.begin():
                place_exists = await session.scalar(
                    select(PlaceModel.id).where(PlaceModel.id == place_id)
                )
                if place_exists is None:
                    return False
                session.add(
                    PlacePhotoModel(
                        place_id=place_id,
                        user_id=user_id,
                        user_name=user_name,
                        file_id=file_id,
                        caption=caption,
                        status="published",
                    )
                )
                return True

    _PUBLIC_PHOTOS_SQL = """
        SELECT f.* FROM (
            SELECT id, place_id, user_id, user_name, file_id,
                   NULL::text AS object_key, caption, created_at, status,
                   'telegram'::text AS source
            FROM place_photos
            UNION ALL
            SELECT -f.id, f.place_id, u.telegram_id, u.name, NULL::text,
                   f.object_key, NULL::text, f.created_at, f.status, 'website'::text
            FROM web_photos f JOIN web_users u ON u.id = f.author_id
        ) f JOIN places p ON p.id = f.place_id
        WHERE f.place_id = :place_id AND f.status = 'published'
          AND p.status = 'published' AND p.nonexistent_reports_count < 10
    """

    async def get_recent_photos(self, place_id: int, limit: int = 5) -> list[dict]:
        return (await self.get_photos_page(place_id, limit=limit))["items"]

    async def get_photos_page(self, place_id: int, limit: int = 1, offset: int = 0) -> dict:
        async with self.async_session() as session:
            total = await session.scalar(text(
                "SELECT count(*) FROM (" + self._PUBLIC_PHOTOS_SQL + ") photos"
            ), {"place_id": place_id})
            result = await session.execute(text(
                self._PUBLIC_PHOTOS_SQL +
                " ORDER BY f.created_at DESC, f.id DESC LIMIT :limit OFFSET :offset"
            ), {"place_id": place_id, "limit": max(0, limit), "offset": max(0, offset)})
            return {"total": int(total or 0), "items": [dict(row) for row in result.mappings()]}

    async def get_place_photos_count(self, place_id: int) -> int:
        async with self.async_session() as session:
            return int(await session.scalar(text(
                "SELECT count(*) FROM (" + self._PUBLIC_PHOTOS_SQL + ") photos"
            ), {"place_id": place_id}) or 0)

    async def delete_all_user_photos(self, place_id: int, user_id: int) -> int:
        async with self.async_session() as session:
            async with session.begin():
                result = await session.execute(
                    delete(PlacePhotoModel)
                    .where(PlacePhotoModel.place_id == place_id)
                    .where(PlacePhotoModel.user_id == user_id)
                )
                return int(result.rowcount or 0)

    @staticmethod
    def _category_priority():
        category = func.lower(func.trim(func.coalesce(PlaceModel.category, "")))
        return case((category.in_(["geocaching", "геокешинг", "геокэшинг"]), 1), else_=0)

    async def get_places(
        self,
        limit: Optional[int] = None,
        offset: int = 0,
        location: Optional[dict] = None,
    ) -> list[Place]:
        offset = max(0, offset)
        async with self.async_session() as session:
            if location is not None:
                lat = location["latitude"]
                lon = location["longitude"]
                dist = 6371 * func.acos(
                    func.cos(func.radians(lat))
                    * func.cos(func.radians(PlaceModel.latitude))
                    * func.cos(func.radians(PlaceModel.longitude) - func.radians(lon))
                    + func.sin(func.radians(lat))
                    * func.sin(func.radians(PlaceModel.latitude))
                )
                stmt = (
                    select(PlaceModel, dist.label("distance_km"))
                    .where(PlaceModel.latitude.isnot(None))
                    .where(PlaceModel.longitude.isnot(None))
                    .where(self._visible_places_filter())
                    .order_by(self._category_priority(), dist.asc(), PlaceModel.id.asc())
                )
                if limit is not None:
                    stmt = stmt.limit(limit).offset(offset)
                res = await session.execute(stmt)
                rows = []
                for place, distance in res.all():
                    rows.append(self._serialize_place(place=place, distance_km=distance))
                return rows

            stmt = select(PlaceModel).where(self._visible_places_filter()).order_by(
                self._category_priority(), PlaceModel.id.desc(),
            )
            if limit is not None:
                stmt = stmt.limit(limit).offset(offset)
            res = await session.execute(stmt)
            return [self._serialize_place(place=p) for p in res.scalars().all()]

    async def get_place_by_id(self, place_id: int) -> Optional[Place]:
        async with self.async_session() as session:
            res = await session.execute(
                select(PlaceModel)
                .where(PlaceModel.id == place_id)
                .where(self._visible_places_filter())
            )
            p = res.scalars().first()
            if not p:
                return None
            return dict(
                id=p.id,
                name=p.name,
                description=p.description,
                type=p.type,
                latitude=p.latitude,
                longitude=p.longitude,
                category=p.category,
                full_address=p.full_address,
                rating_avg=float(p.rating_avg or 0),
                rating_count=int(p.rating_count or 0),
                rating_score=float(p.rating_score or 0),
                nonexistent_reports_count=int(p.nonexistent_reports_count or 0),
            )

    async def get_places_by_ids(
        self,
        ids: list[int],
        limit: Optional[int] = None,
        offset: int = 0,
        location: Optional[dict] = None,
    ) -> dict:
        offset = max(0, offset)
        if not ids:
            return {"total": 0, "items": []}

        async with self.async_session() as session:
            if location is not None:
                total = await session.scalar(
                    select(func.count())
                    .select_from(PlaceModel)
                    .where(PlaceModel.id.in_(ids))
                    .where(PlaceModel.latitude.isnot(None))
                    .where(PlaceModel.longitude.isnot(None))
                    .where(self._visible_places_filter())
                )
                lat = location["latitude"]
                lon = location["longitude"]
                dist = 6371 * func.acos(
                    func.cos(func.radians(lat))
                    * func.cos(func.radians(PlaceModel.latitude))
                    * func.cos(func.radians(PlaceModel.longitude) - func.radians(lon))
                    + func.sin(func.radians(lat))
                    * func.sin(func.radians(PlaceModel.latitude))
                )
                stmt = (
                    select(PlaceModel, dist.label("distance_km"))
                    .where(PlaceModel.id.in_(ids))
                    .where(PlaceModel.latitude.isnot(None))
                    .where(PlaceModel.longitude.isnot(None))
                    .where(self._visible_places_filter())
                    .order_by(self._category_priority(), dist.asc(), PlaceModel.id.asc())
                )
            else:
                ordering = case(
                    {place_id: index for index, place_id in enumerate(ids)},
                    value=PlaceModel.id,
                    else_=len(ids),
                )
                total = await session.scalar(
                    select(func.count())
                    .select_from(PlaceModel)
                    .where(PlaceModel.id.in_(ids))
                    .where(self._visible_places_filter())
                )
                stmt = (
                    select(PlaceModel)
                    .where(PlaceModel.id.in_(ids))
                    .where(self._visible_places_filter())
                    .order_by(self._category_priority(), ordering)
                )

            if limit is not None:
                stmt = stmt.limit(limit).offset(offset)

            res = await session.execute(stmt)
            items = []
            if location is not None:
                for place, distance in res.all():
                    items.append(self._serialize_place(place=place, distance_km=distance))
            else:
                for place in res.scalars().all():
                    items.append(self._serialize_place(place=place))

            return {"total": int(total), "items": items}

    async def get_places_count(self) -> int:
        async with self.async_session() as session:
            return int(
                await session.scalar(
                    select(func.count()).select_from(PlaceModel)
                    .where(self._visible_places_filter())
                )
            )
