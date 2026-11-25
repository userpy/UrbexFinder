from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, func

from .base import Base


class PlacePhoto(Base):  # noqa: D101
    """User photo for place."""

    __tablename__ = "place_photos"

    id = Column(Integer, primary_key=True)
    place_id = Column(
        Integer,
        ForeignKey("places.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(BigInteger, nullable=False)
    user_name = Column(String, nullable=True)
    file_id = Column(String, nullable=False)
    status = Column(String(30), nullable=False, server_default="published")
    reason = Column(Text, nullable=False, server_default="")
    caption = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
