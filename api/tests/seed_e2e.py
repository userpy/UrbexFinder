"""Fixtures for the disposable E2E stack only; never called in development/production."""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from urbex.bootstrap.config import Settings
from urbex.infrastructure.auth import hasher
from urbex.infrastructure.models import User, Place

config = Settings()
assert config.environment == 'test' and config.database_url.endswith('/urbex_test')
with Session(create_engine(config.database_url)) as session, session.begin():
    for role in ('admin', 'moderator'):
        session.add(User(email=f'{role}@e2e.example.com', name=f'E2E {role}',
                         role=role, password_hash=hasher.hash('e2e-only-password-12345')))
    for i in range(65):
        session.add(Place(name=f'Тестовая башня {i:02}', description='Тестовые данные изолированной браузерной проверки.',
                          latitude=55.75+i*0.00001, longitude=37.62+i*0.00001,
                          region='Москва', category_id=1, status='published'))
    session.add(Place(name='Войсковая часть за пределами карты',
                      description='Здесь служил Кувин. Историческое описание объекта.',
                      latitude=56.40926, longitude=38.72178,
                      region='Александров', category_id=1, status='published'))
