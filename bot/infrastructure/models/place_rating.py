from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, UniqueConstraint, func

from .base import Base


class PlaceRating(Base):  # noqa: D101
    """User rating for place."""

    __tablename__ = "place_ratings"
    __table_args__ = (UniqueConstraint("place_id", "user_id", name="uq_place_ratings_place_user"),)

    id = Column(Integer, primary_key=True)
    place_id = Column(Integer, ForeignKey("places.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, nullable=False)
    score = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
