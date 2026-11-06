from datetime import datetime
from typing import Literal, Annotated
from pydantic import StringConstraints, BaseModel, ConfigDict, Field, EmailStr, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Login(Input):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)

    @field_validator('email')
    @classmethod
    def normalize(cls, value):
        return value.lower()


class Register(Login):
    name: str = Field(min_length=2, max_length=100)


class PlaceInput(Input):
    name: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=20, max_length=20000)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    region: str = Field(min_length=2, max_length=200)
    category_id: int = Field(gt=0)
    condition: Literal['unknown', 'standing', 'ruined', 'demolished'] = 'unknown'
    access: str = Field(min_length=5, max_length=2000)


class Search(Input):
    q: str = Field(default='', max_length=200)
    search_in: Literal['all', 'name', 'address', 'description'] = 'all'
    locality: str | None = Field(default=None, max_length=200)
    locality_bbox: str | None = None
    zoom: int = Field(default=9, ge=0, le=22)
    bbox: str | None = None
    category_id: int | None = Field(default=None, gt=0)
    condition: Literal['unknown', 'standing', 'ruined', 'demolished'] | None = None
    region: str | None = Field(default=None, max_length=200)
    page: int = Field(default=1, ge=1, le=10000)
    limit: int = Field(default=30, ge=1, le=200)
    near_lon: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    near_lat: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    radius_km: float = Field(default=10, ge=0.1, le=200, allow_inf_nan=False)

    @model_validator(mode='after')
    def validate_geo(self):
        if (self.near_lat is None) != (self.near_lon is None):
            raise ValueError('Для поиска рядом нужны обе координаты')
        if self.bbox:
            values = [float(x) for x in self.bbox.split(',')]
            if len(values) != 4:
                raise ValueError('bbox: west,south,east,north')
            w,s,e,n = values
            if not (-180 <= w <= 180 and -180 <= e <= 180 and -90 <= s <= n <= 90):
                raise ValueError('Некорректная область карты')
        if self.locality_bbox:
            values = [float(x) for x in self.locality_bbox.split(',')]
            if len(values) != 4 or not (-180 <= values[0] <= values[2] <= 180 and -85 <= values[1] <= values[3] <= 85):
                raise ValueError('Некорректные границы территории')
            if not self.locality:
                raise ValueError('Укажите населённый пункт')
        return self

    def filters(self):
        d = self.model_dump()
        if self.bbox:
            d['bbox'] = [float(x) for x in self.bbox.split(',')]
        if self.locality_bbox:
            d['locality_bbox'] = [float(x) for x in self.locality_bbox.split(',')]
        return d


class ReviewInput(Input):
    text: str = Field(min_length=5, max_length=4000)
    score: int = Field(ge=1, le=5)


class ReportInput(Input):
    target_type: Literal['places', 'photos', 'reviews']
    target_id: int

    @model_validator(mode="after")
    def valid_target(self):
        if self.target_id == 0 or (self.target_id < 0 and self.target_type not in {"photos", "reviews"}):
            raise ValueError("Некорректный идентификатор")
        return self
    text: str = Field(min_length=5, max_length=4000)


class Decision(Input):
    status: Literal['published', 'rejected', 'changes_requested']
    reason: str = Field(default='', max_length=4000)


class UserUpdate(Input):
    role: Literal['user', 'moderator', 'admin']
    blocked: bool


class CategoryInput(Input):
    icon: Literal["other", "estate", "shelter", "military", "camp", "school", "culture", "industry", "church", "nature", "geocache", "infrastructure"] | None = None
    name: str = Field(min_length=2, max_length=100)
    active: bool = True


class DescriptionUpdate(Input):
    description: str = Field(min_length=1, max_length=20000)
    expected_description: Annotated[str, StringConstraints(strip_whitespace=False)] | None = Field(default=None, max_length=20000)


class AdminPlaceUpdate(Input):
    category_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=3, max_length=200)
    description: str = Field(min_length=1, max_length=20000)
    latitude: float = Field(ge=-85, le=85, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    address: str = Field(min_length=1, max_length=2000)
    expected_updated_at: datetime


from datetime import date


class RouteStop(Input):
    place_id: int = Field(gt=0)
    note: str = Field(default='', max_length=2000)
    status: Literal['planned','visited','skipped'] = 'planned'


class ItineraryInput(Input):
    name: str = Field(min_length=1, max_length=120)
    trip_date: date | None = None
    notes: str = Field(default='', max_length=5000)
    stops: list[RouteStop] = Field(default_factory=list, max_length=50)
    version: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def unique_places(self):
        if len({s.place_id for s in self.stops}) != len(self.stops):
            raise ValueError('Место уже есть в маршруте')
        return self
