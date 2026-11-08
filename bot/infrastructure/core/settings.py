from functools import lru_cache
from typing import Literal
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class BaseEnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


class DatabaseSettings(BaseEnvSettings):
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str
    postgres_port: str


class AppSettings(DatabaseSettings):
    token: str
    admin_name: str
    admin_id: str
    kmz_path: str
    csv_path: str
    elasticsearch_host: str
    elasticsearch_user: str
    elasticsearch_password: str
    seed_places_source: Literal["kmz", "csv", "both"] = "kmz"
    places_csv_path: str = "geo_data/places.csv"
    seed_places: bool
    rabbitmq_user: str
    rabbitmq_password: str
    rabbitmq_host: str
    rabbitmq_port: int
    rabbitmq_vhost: str = "/"
    rabbitmq_max_retry_attempts: int = Field(default=3, ge=0)
    rabbitmq_retry_delay_ms: int = Field(default=5_000, gt=0)
    rabbitmq_connection_max_attempts: int = Field(default=10, ge=1)
    rabbitmq_connection_retry_delay_ms: int = Field(default=500, gt=0)
    s3_endpoint: str = Field(default="http://localhost:59000", validation_alias="URBEX_S3_ENDPOINT")
    s3_access_key: str = Field(default="local-minio", validation_alias="URBEX_S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="local-minio-change-me", validation_alias="URBEX_S3_SECRET_KEY")
    s3_bucket: str = Field(default="urbex-private", validation_alias="URBEX_S3_BUCKET")
    enqueue_places_sync_on_startup: bool = True


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    return AppSettings()


@lru_cache(maxsize=1)
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()
