from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.models import Role


class RolesRepository:
    def __init__(self, async_session: async_sessionmaker[AsyncSession]):
        self.async_session = async_session

    async def ensure_base_roles(self) -> None:
        async with self.async_session() as session:
            async with session.begin():
                for rid, rname in ((1, "user"), (2, "moderator"), (3, "admin")):
                    q = select(Role).where(Role.id == rid)
                    res = await session.execute(q)
                    if not res.scalars().first():
                        session.add(Role(id=rid, name=rname))
