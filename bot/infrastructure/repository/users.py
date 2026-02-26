from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.models import Role, User


class UsersRepository:
    def __init__(self, async_session: async_sessionmaker[AsyncSession]):
        self.async_session = async_session

    async def ensure_admin_user(
        self,
        user_admin_id: Optional[int],
        user_admin_name: Optional[str],
    ) -> None:
        if not user_admin_id or not user_admin_name:
            return
        async with self.async_session() as session:
            async with session.begin():
                q = select(User).where(User.user_id == int(user_admin_id))
                res = await session.execute(q)
                if not res.scalars().first():
                    session.add(
                        User(
                            name=user_admin_name,
                            user_id=int(user_admin_id),
                            role_id=3,
                        )
                    )

    async def get_user_role(self, user_id: int) -> Optional[str]:
        async with self.async_session() as session:
            q = select(User).where(User.user_id == user_id)
            res = await session.execute(q)
            u = res.scalars().first()
            if not u:
                return None
            rq = select(Role).where(Role.id == u.role_id)
            rres = await session.execute(rq)
            role = rres.scalars().first()
            return role.name if role else None

    async def add_user(self, name: str, user_id: int, role_id: int = 1) -> None:
        async with self.async_session() as session:
            res = await session.execute(
                select(User).where(User.user_id == user_id)
            )
            if res.scalars().first():
                return
            session.add(User(name=name, user_id=user_id, role_id=role_id))
            await session.commit()

    async def get_user(self, user_id: int) -> Optional[dict]:
        async with self.async_session() as session:
            res = await session.execute(
                select(User).where(User.user_id == user_id)
            )
            u = res.scalars().first()
            if not u:
                return None
            rres = await session.execute(
                select(Role).where(Role.id == u.role_id)
            )
            role = rres.scalars().first()
            return {
                "id": u.id,
                "name": u.name,
                "user_id": u.user_id,
                "role": role.name if role else None,
            }
