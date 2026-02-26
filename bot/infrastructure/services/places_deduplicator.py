from infrastructure.db.PgDb import AsyncDatabase


class PlacesDeduplicationService:
    def __init__(self, db: AsyncDatabase):
        self.db = db

    async def run(self) -> int:
        return await self.db.places.deduplicate_by_coordinates()
