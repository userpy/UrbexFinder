import argparse
import getpass
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from urbex.bootstrap.config import Settings
from urbex.infrastructure.repository import SqlRepository
from urbex.infrastructure.auth import hasher
from urbex.infrastructure.storage import S3Storage
from urbex.presentation.schemas import Register


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['create-admin', 'seed-demo', 'init-storage', 'import-bot', 'sync-search', 'reindex-search'])
    parser.add_argument('--email')
    args = parser.parse_args()
    config = Settings()
    if args.command in {'sync-search', 'reindex-search'}:
        from urbex.infrastructure.search import ElasticSearch
        engine = create_engine(config.database_url)
        if args.command == 'reindex-search':
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO web_search_outbox(place_id) SELECT id FROM places ON CONFLICT(place_id) DO UPDATE SET revision=nextval('web_search_revision')"))
        print(f'Обновлено документов: {ElasticSearch(config, engine).sync()}')
        engine.dispose()
        return
    if args.command == 'init-storage':
        store = S3Storage(config)
        buckets = [b['Name'] for b in store.client.list_buckets()['Buckets']]
        if store.bucket not in buckets:
            store.client.create_bucket(Bucket=store.bucket)
        # No public-read ACL or policy is ever installed.
        print('Private bucket ready')
        return
    with Session(create_engine(config.database_url)) as session, session.begin():
        repo = SqlRepository(session)
        if args.command == 'create-admin':
            password = getpass.getpass('Пароль администратора (минимум 12 символов): ')
            if password != getpass.getpass('Повторите пароль: '):
                raise SystemExit('Пароли не совпадают')
            data = Register(email=args.email or input('Email: '), name='Администратор', password=password)
            repo.add('users', dict(email=data.email, name=data.name, password_hash=hasher.hash(data.password), role='admin'))
        elif args.command == 'seed-demo':
            if config.environment != 'development':
                raise SystemExit('Демонстрационные данные разрешены только в development')
            for name, lat, lon, category in [('ДЕМО · Ткацкая фабрика',55.79,37.65,1), ('ДЕМО · Водонапорная башня',55.72,37.55,3), ('ДЕМО · Усадьба у реки',55.83,37.48,2)]:
                if not repo.list('places', {'name': name})['total']:
                    repo.add('places', dict(name=name, latitude=lat, longitude=lon, category_id=category, region='Москва',
                        description='Вымышленный демонстрационный объект для проверки интерфейса. Координаты не являются рекомендацией к посещению.',
                        condition='unknown', access='Демонстрация. Доступ не подтверждён.', status='published'))
        elif args.command == 'import-bot':
            print('Общий каталог places подключён напрямую; импорт больше не требуется.')
    print('Готово')


if __name__ == '__main__':
    main()
