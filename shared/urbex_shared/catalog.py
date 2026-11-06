"""One physical catalog schema; each service owns its SQLAlchemy registry.

Cross-service account foreign keys are added by the website migration, since a
standalone bot does not have website accounts. Telegram identities stay separate.
"""
from sqlalchemy import BigInteger, Column, DateTime, Integer, Numeric, String, Text, func

NONEXISTENT_HIDE_THRESHOLD = 10


class PlaceColumns:
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    type = Column(String)
    latitude = Column(Numeric(10, 6))
    longitude = Column(Numeric(10, 6))
    category = Column(String)
    full_address = Column(Text)
    rating_avg = Column(Numeric(3, 2), nullable=False, server_default="0")
    rating_count = Column(Integer, nullable=False, server_default="0")
    rating_score = Column(Numeric(5, 3), nullable=False, server_default="0")
    nonexistent_reports_count = Column(Integer, nullable=False, server_default="0", index=True)
    region = Column(String(200), nullable=False, server_default="Не указан")
    category_id = Column(Integer)
    condition = Column(String(30), nullable=False, server_default="unknown")
    access = Column(Text, nullable=False, server_default="Сведения о доступе не подтверждены")
    author_id = Column(Integer)
    telegram_author_id = Column(BigInteger)
    status = Column(String(30), nullable=False, server_default="pending")
    reason = Column(Text, nullable=False, server_default="")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


def published_filter(model):
    return (model.status == "published") & (model.nonexistent_reports_count < NONEXISTENT_HIDE_THRESHOLD)
