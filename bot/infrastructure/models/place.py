from urbex_shared.catalog import PlaceColumns

from .base import Base


class Place(PlaceColumns, Base):
    __tablename__ = "places"
