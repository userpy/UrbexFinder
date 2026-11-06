"""Website editorial projection; no mutations to Telegram-owned tables."""
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = 'web_users'
    id = Column(Integer, primary_key=True)
    email = Column(String(254), unique=True, nullable=False)
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
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    active = Column(Boolean, nullable=False, server_default='true')


class Place(Base):
    __tablename__ = 'web_places'
    id = Column(Integer, primary_key=True)
    legacy_place_id = Column(Integer, unique=True)  # Deliberately no FK: bot deduplicator can delete/merge source records.
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    longitude = Column(Float, nullable=False)
    latitude = Column(Float, nullable=False)
    region = Column(String(200), nullable=False)
    category_id = Column(Integer, ForeignKey('web_categories.id'), nullable=False)
    condition = Column(String(30), nullable=False, server_default='unknown')
    access = Column(Text, nullable=False, server_default='Сведения о доступе не подтверждены')
    author_id = Column(Integer, ForeignKey('web_users.id'))
    status = Column(String(30), nullable=False, server_default='pending')
    reason = Column(Text, nullable=False, server_default='')
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Photo(Base):
    __tablename__ = 'web_photos'
    id = Column(Integer, primary_key=True)
    place_id = Column(Integer, ForeignKey('web_places.id'), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey('web_users.id'), nullable=False)
    object_key = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, server_default='pending')
    reason = Column(Text, nullable=False, server_default='')
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Review(Base):
    __tablename__ = 'web_reviews'
    __table_args__ = (UniqueConstraint('place_id', 'author_id'),)
    id = Column(Integer, primary_key=True)
    place_id = Column(Integer, ForeignKey('web_places.id'), nullable=False, index=True)
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
    place_id = Column(Integer, ForeignKey('web_places.id'), nullable=False)
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
