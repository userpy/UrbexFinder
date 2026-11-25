from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, func

from .base import Base


class PlaceReview(Base):  # noqa: D101
    """User review for place."""

    __tablename__ = "place_reviews"

    id = Column(Integer, primary_key=True)
    place_id = Column(
        Integer,
        ForeignKey("places.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(BigInteger, nullable=False)
    status = Column(String(30), nullable=False, server_default='published')
    reason = Column(Text, nullable=False, server_default='')
    user_name = Column(String, nullable=True)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
