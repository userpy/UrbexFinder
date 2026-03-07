import asyncio
from typing import Optional, TypedDict

from loguru import logger
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.models import Place as PlaceModel
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


class PlacesRepository:
    _MERGE_FIELDS = ("name", "description", "type", "category", "full_address")

    def __init__(self, async_session: async_sessionmaker[AsyncSession]):
        self.async_session = async_session

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

                await session.execute(
                    delete(PlaceModel)
                    .where(PlaceModel.latitude == latitude)
                    .where(PlaceModel.longitude == longitude)
                )
                logger.info(f"[INFO] created place {name}")
                new_place = PlaceModel(
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
        )
        if distance_km is not None:
            payload["distance_km"] = float(distance_km)
        return payload

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
                )
                or 0
            )
            res = await session.execute(
                select(PlaceReviewModel)
                .where(PlaceReviewModel.place_id == place_id)
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
                    )
                )
                return True

    async def get_recent_photos(self, place_id: int, limit: int = 5) -> list[dict]:
        async with self.async_session() as session:
            res = await session.execute(
                select(PlacePhotoModel)
                .where(PlacePhotoModel.place_id == place_id)
                .order_by(PlacePhotoModel.created_at.desc(), PlacePhotoModel.id.desc())
                .limit(limit)
            )
            rows = []
            for photo in res.scalars().all():
                rows.append(
                    {
                        "id": photo.id,
                        "user_id": photo.user_id,
                        "user_name": photo.user_name,
                        "file_id": photo.file_id,
                        "caption": photo.caption,
                        "created_at": photo.created_at,
                    }
                )
            return rows

    async def get_photos_page(self, place_id: int, limit: int = 1, offset: int = 0) -> dict:
        offset = max(0, offset)
        async with self.async_session() as session:
            total = int(
                await session.scalar(
                    select(func.count())
                    .select_from(PlacePhotoModel)
                    .where(PlacePhotoModel.place_id == place_id)
                )
                or 0
            )
            res = await session.execute(
                select(PlacePhotoModel)
                .where(PlacePhotoModel.place_id == place_id)
                .order_by(PlacePhotoModel.created_at.desc(), PlacePhotoModel.id.desc())
                .limit(limit)
                .offset(offset)
            )
            items = []
            for photo in res.scalars().all():
                items.append(
                    {
                        "id": photo.id,
                        "user_id": photo.user_id,
                        "user_name": photo.user_name,
                        "file_id": photo.file_id,
                        "caption": photo.caption,
                        "created_at": photo.created_at,
                    }
                )
            return {"total": total, "items": items}

    async def get_place_photos_count(self, place_id: int) -> int:
        async with self.async_session() as session:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(PlacePhotoModel)
                    .where(PlacePhotoModel.place_id == place_id)
                )
                or 0
            )

    async def delete_all_user_photos(self, place_id: int, user_id: int) -> int:
        async with self.async_session() as session:
            async with session.begin():
                result = await session.execute(
                    delete(PlacePhotoModel)
                    .where(PlacePhotoModel.place_id == place_id)
                    .where(PlacePhotoModel.user_id == user_id)
                )
                return int(result.rowcount or 0)

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
                    .order_by(dist.asc())
                )
                if limit is not None:
                    stmt = stmt.limit(limit).offset(offset)
                res = await session.execute(stmt)
                rows = []
                for place, distance in res.all():
                    rows.append(self._serialize_place(place=place, distance_km=distance))
                return rows

            stmt = select(PlaceModel).order_by(
                PlaceModel.id.desc(),
            )
            if limit is not None:
                stmt = stmt.limit(limit).offset(offset)
            res = await session.execute(stmt)
            return [self._serialize_place(place=p) for p in res.scalars().all()]

    async def get_place_by_id(self, place_id: int) -> Optional[Place]:
        async with self.async_session() as session:
            res = await session.execute(
                select(PlaceModel).where(PlaceModel.id == place_id)
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
                    .order_by(dist.asc())
                )
            else:
                total = await session.scalar(
                    select(func.count())
                    .select_from(PlaceModel)
                    .where(PlaceModel.id.in_(ids))
                )
                stmt = (
                    select(PlaceModel)
                    .where(PlaceModel.id.in_(ids))
                    .order_by(PlaceModel.id.asc())
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
                )
            )
