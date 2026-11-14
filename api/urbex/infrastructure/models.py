from sqlalchemy import BigInteger
from urbex_shared.catalog import PlaceColumns
"""Website accounts and content linked to the shared canonical catalog."""
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = 'web_users'
    deleted = Column(Boolean, nullable=False, server_default='false')
    id = Column(Integer, primary_key=True)
    email = Column(String(254), unique=True, nullable=True)
    telegram_id = Column(BigInteger, unique=True)
    name = Column(String(100), nullable=False)
    password_hash = Column(Text, nullable=False)
    role = Column(String(20), nullable=False, server_default='user')
    blocked = Column(Boolean, nullable=False, server_default='false')
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Session(Base):
    __tablename__ = 'web_sessions'
    id = Column(Integer, primary_key=True)
    token_hash = Column(String(64), unique=True, nullable=False)
    csrf = Column(String(100), nullable=False)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class Category(Base):
    __tablename__ = 'web_categories'
    icon = Column(String(32), nullable=True)
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    active = Column(Boolean, nullable=False, server_default='true')


class Place(PlaceColumns, Base):
    __tablename__ = "places"


class Photo(Base):
    __tablename__ = 'web_photos'
    id = Column(Integer, primary_key=True)
    place_id = Column(Integer, ForeignKey('places.id'), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    object_key = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, server_default='published')
    reason = Column(Text, nullable=False, server_default='')
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Review(Base):
    __tablename__ = 'web_reviews'
    __table_args__ = (UniqueConstraint('place_id', 'author_id'),)
    id = Column(Integer, primary_key=True)
    place_id = Column(Integer, ForeignKey('places.id'), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    text = Column(Text, nullable=False)
    score = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False, server_default='published')
    reason = Column(Text, nullable=False, server_default='')
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Favorite(Base):
    __tablename__ = 'web_favorites'
    __table_args__ = (UniqueConstraint('place_id', 'user_id'),)
    id = Column(Integer, primary_key=True)
    place_id = Column(Integer, ForeignKey('places.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)


class Report(Base):
    __tablename__ = 'web_reports'
    id = Column(Integer, primary_key=True)
    author_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    target_type = Column(String(20), nullable=False)
    target_id = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, server_default='pending')
    reason = Column(Text, nullable=False, server_default='')
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Audit(Base):
    __tablename__ = 'web_audit'
    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    action = Column(String(100), nullable=False)
    target = Column(String(100), nullable=False)
    detail = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


MODELS = {'users': User, 'sessions': Session, 'categories': Category, 'places': Place,
          'photos': Photo, 'reviews': Review, 'favorites': Favorite, 'reports': Report, 'audit': Audit}


from sqlalchemy import Date
from sqlalchemy.dialects.postgresql import JSONB


class Itinerary(Base):
    __tablename__ = 'web_itineraries'
    active = Column(Boolean, nullable=False, server_default='false')
    id = Column(Integer, primary_key=True)
    author_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    name = Column(String(120), nullable=False)
    share_token = Column(String(64), unique=True)
    trip_date = Column(Date)
    notes = Column(Text, nullable=False, server_default='')
    stops = Column(JSONB, nullable=False, server_default='[]')
    version = Column(Integer, nullable=False, server_default='1')
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

MODELS['itineraries'] = Itinerary


class TelegramLogin(Base):
    __tablename__ = 'web_telegram_logins'
    id = Column(Integer, primary_key=True)
    browser_hash = Column(String(64), unique=True, nullable=False)
    link_hash = Column(String(64), unique=True, nullable=False)
    code = Column(String(6), nullable=False)
    telegram_id = Column(BigInteger)
    display_name = Column(String(100))
    confirmed = Column(Boolean, nullable=False, server_default='false')
    consumed = Column(Boolean, nullable=False, server_default='false')
    expires_at = Column(DateTime(timezone=True), nullable=False)

MODELS['telegram_logins'] = TelegramLogin
