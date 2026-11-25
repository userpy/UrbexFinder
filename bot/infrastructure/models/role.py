from sqlalchemy import Column, Integer, String

from .base import Base


class Role(Base):  # noqa: D101
    """Role model for user permissions."""

    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
