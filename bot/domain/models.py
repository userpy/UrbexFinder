"""SQLAlchemy ORM models for telegram bot database."""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Role(Base):  # noqa: D101
    """Role model for user permissions."""

    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)


class User(Base):  # noqa: D101
    """User model for bot users."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    user_id = Column(Integer, nullable=False, unique=True)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)


class Place(Base):  # noqa: D101
    """Place model for storing geographic locations."""

    __tablename__ = "places"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    type = Column(String, nullable=True)
    latitude = Column(Numeric(10, 6), nullable=True)
    longitude = Column(Numeric(10, 6), nullable=True)
    category = Column(String, nullable=True)
    full_address = Column(Text, nullable=True)
    rating_avg = Column(Numeric(3, 2), nullable=False, server_default="0")
    rating_count = Column(Integer, nullable=False, server_default="0")
    rating_score = Column(Numeric(5, 3), nullable=False, server_default="0")
    nonexistent_reports_count = Column(Integer, nullable=False, server_default="0")


class PlaceNonexistentReport(Base):  # noqa: D101
    """User report that a place no longer exists."""

    __tablename__ = "place_nonexistent_reports"
    __table_args__ = (UniqueConstraint("place_id", "user_id", name="uq_place_nonexistent_reports_place_user"),)

    id = Column(Integer, primary_key=True)
    place_id = Column(Integer, ForeignKey("places.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class PlaceRating(Base):  # noqa: D101
    """User rating for place."""

    __tablename__ = "place_ratings"
    __table_args__ = (UniqueConstraint("place_id", "user_id", name="uq_place_ratings_place_user"),)

    id = Column(Integer, primary_key=True)
    place_id = Column(Integer, ForeignKey("places.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, nullable=False)
    score = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class PlaceReview(Base):  # noqa: D101
    """User review for place."""

    __tablename__ = "place_reviews"

    id = Column(Integer, primary_key=True)
    place_id = Column(Integer, ForeignKey("places.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, nullable=False)
    user_name = Column(String, nullable=True)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class PlacePhoto(Base):  # noqa: D101
    """User photo for place."""

    __tablename__ = "place_photos"

    id = Column(Integer, primary_key=True)
    place_id = Column(Integer, ForeignKey("places.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, nullable=False)
    user_name = Column(String, nullable=True)
    file_id = Column(String, nullable=False)
    caption = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class Resource(Base):  # noqa: D101
    """Resource model for storing links and resources."""

    __tablename__ = "resources"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    url = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
