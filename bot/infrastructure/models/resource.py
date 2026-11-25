from sqlalchemy import Column, DateTime, Integer, String, Text, func

from .base import Base


class Resource(Base):  # noqa: D101
    """Resource model for storing links and resources."""

    __tablename__ = "resources"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    url = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
