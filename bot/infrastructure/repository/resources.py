import datetime
from typing import Optional, TypedDict

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.models import Resource as ResourceModel


class ResourceRow(TypedDict):
    id: int
    name: str
    type: str
    url: str
    description: str | None
    created_at: datetime.datetime


class ResourcesRepository:
    def __init__(self, async_session: async_sessionmaker[AsyncSession]):
        self.async_session = async_session

    async def add_resource(
        self,
        name: str,
        type_: str,
        url: str,
        description: Optional[str] = None,
    ) -> None:
        async with self.async_session() as session:
            async with session.begin():
                r = ResourceModel(
                    name=name, type=type_, url=url, description=description
                )
                session.add(r)

    async def get_resources(
        self, limit: int = 10, offset: int = 0
    ) -> list[ResourceRow]:
        async with self.async_session() as session:
            stmt = (
                select(ResourceModel)
                .order_by(desc(ResourceModel.id))
                .limit(limit)
                .offset(offset)
            )
            res = await session.execute(stmt)
            return [
                dict(
                    id=r.id,
                    name=r.name,
                    type=r.type,
                    url=r.url,
                    description=r.description,
                    created_at=r.created_at,
                )
                for r in res.scalars().all()
            ]

    async def get_resources_count(self) -> int:
        async with self.async_session() as session:
            return int(
                await session.scalar(
                    select(func.count()).select_from(ResourceModel)
                )
            )

    async def delete_resource(self, resource_id: int) -> bool:
        async with self.async_session() as session:
            res = await session.execute(
                select(ResourceModel).where(ResourceModel.id == resource_id)
            )
            r = res.scalars().first()
            if not r:
                return False
            await session.delete(r)
            await session.commit()
            return True
