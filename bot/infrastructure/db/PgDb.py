import os
from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from infrastructure.repository import (
    PlacesRepository,
    RolesRepository,
    ResourcesRepository,
    UsersRepository,
)


class AsyncDatabase:
    def __init__(
        self,
        user_admin_name: Optional[str] = None,
        user_admin_id: Optional[int] = None,
        pg_database: Optional[str] = None,
        pg_user: Optional[str] = None,
        pg_password: Optional[str] = None,
        pg_host: Optional[str] = None,
        pg_port: Optional[int] = None,
    ):
        self.user_admin_name = user_admin_name
        self.user_admin_id = int(user_admin_id) if user_admin_id is not None else None
        self.pg_database = pg_database
        self.pg_user = pg_user
        self.pg_password = pg_password
        self.pg_host = pg_host or ("db" if os.path.exists("/.dockerenv") else "localhost")
        self.pg_port = int(pg_port) if pg_port is not None else 5432

        self.engine = None
        self.async_session = None
        self.places: Optional[PlacesRepository] = None
        self.roles: Optional[RolesRepository] = None
        self.resources: Optional[ResourcesRepository] = None
        self.users: Optional[UsersRepository] = None

    async def connect(self):
        url = (
            f"postgresql+asyncpg://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )
        self.engine = create_async_engine(url, future=True)
        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        self.__add_repositories()
        # Schema management is handled by Alembic migrations.
        await self.roles.ensure_base_roles()
        await self.users.ensure_admin_user(
            user_admin_id=self.user_admin_id,
            user_admin_name=self.user_admin_name,
        )
        
    def __add_repositories(self):
        self.places = PlacesRepository(self.async_session)
        self.roles = RolesRepository(self.async_session)
        self.resources = ResourcesRepository(self.async_session)
        self.users = UsersRepository(self.async_session)

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
