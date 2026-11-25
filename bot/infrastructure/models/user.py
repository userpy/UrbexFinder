from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String

from .base import Base


class User(Base):  # noqa: D101
    """User model for bot users."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    user_id = Column(BigInteger, nullable=False, unique=True)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
