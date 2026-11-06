from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='URBEX_', extra='ignore')
    database_url: str = 'postgresql+psycopg2://urbex:local-only@localhost:5432/urbex'
    origin: str = 'http://localhost:3100'
    secure_cookie: bool = False
    session_hours: int = 168
    s3_endpoint: str = 'http://localhost:59000'
    s3_access_key: str = 'local-minio'
    s3_secret_key: str = 'local-minio-change-me'
    s3_bucket: str = 'urbex-private'
    telegram_bot_token: str = ''
    telegram_bot_username: str = ''
    elasticsearch_url: str = ''
    elasticsearch_index: str = 'urbex_places_v1'
    elasticsearch_user: str = 'elastic'
    elasticsearch_password: str = ''
    geocoder_url: str = ''
    environment: str = 'development'

    def validate_runtime(self):
        if self.environment == 'production' and (not self.secure_cookie or not self.origin.startswith('https://')):
            raise ValueError('Production requires HTTPS origin and Secure cookies')
