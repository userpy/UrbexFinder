from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, UniqueConstraint, func

from .base import Base


class PlaceNonexistentReport(Base):  # noqa: D101
    """User report that a place no longer exists."""

    __tablename__ = "place_nonexistent_reports"
    __table_args__ = (UniqueConstraint("place_id", "user_id", name="uq_place_nonexistent_reports_place_user"),)

    id = Column(Integer, primary_key=True)
    place_id = Column(
        Integer,
        ForeignKey("places.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
