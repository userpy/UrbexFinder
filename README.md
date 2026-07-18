Telegram Bot Project
====================

Этот репозиторий содержит Telegram-бота на базе aiogram с PostgreSQL,
Elasticsearch и логированием в Grafana Loki. Код организован в стиле
прагматичной clean architecture.

Структура проекта
-----------------
- `bot/domain/` - доменные модели (SQLAlchemy ORM).
- `bot/application/` - прикладные сервисы и сценарии запуска.
- `bot/interface/` - адаптеры фреймворка: handlers, middleware, filters.
- `bot/infrastructure/` - интеграции: БД, логирование, внешние сервисы.
- `bot/main.py` - точка входа.
- `bot/geo_data/` - KMZ/KML-источник для первичного наполнения мест.
- `docker-compose.yml` - локальный стек: Postgres, Elasticsearch, Loki, Grafana.

Требования
----------
- Python 3.10+
- Poetry (для локальной разработки)
- Docker и Docker Compose (для полного стека)

Переменные окружения
--------------------
Создайте файл `.env` в корне репозитория. Полный пример есть в `.env-example`.

Обязательные переменные приложения:
- `TOKEN` - токен Telegram-бота.
- `ADMIN_NAME` - имя администратора.
- `ADMIN_ID` - Telegram ID администратора.
- `KMZ_PATH` - путь к KMZ-файлу с местами.
- `CSV_PATH` - путь к CSV-файлу с адресами мест.
- `SEED_PLACES` - запуск первичного сидинга мест (`True`/`False`).
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT`.
- `ELASTIC_URL`, `ELASTIC_USER`, `ELASTIC_PASSWORD`.
- `RABBITMQ_USER`, `RABBITMQ_PASSWORD`, `RABBITMQ_HOST`, `RABBITMQ_PORT`.

RabbitMQ topology для стартовой синхронизации мест:
- topic exchange: `bot.commands`;
- queue: `places.bootstrap.commands`;
- routing/binding key: `places.bootstrap.requested`;
- модуль `exchange_queue_topology.py` создаёт topology до запуска bot и worker;
- `ENQUEUE_PLACES_SYNC_ON_STARTUP` включает публикацию startup-команды.

Дополнительно:
- `TG_CHANNEL_ID` - ID Telegram-канала.
- `GF_SECURITY_ADMIN_USER`, `GF_SECURITY_ADMIN_PASSWORD` - учётные данные Grafana.

Примечания:
- Для Docker путь `KMZ_PATH` должен быть внутри контейнера,
  например: `geo_data/Покинутые_индустриальные_объекты.kmz`.
- При первом запуске не забудьте включить сидирование мест:
  установите `SEED_PLACES=True` в `.env`, чтобы бот загрузил места из KMZ.
- `docker-compose.yml` использует `.env` для конфигурации Postgres и Grafana.
- Elasticsearch запускается с включенной security, пользователь `elastic`.

Быстрый старт (Docker)
----------------------
1. Создайте `.env` в корне репозитория.
   Для первого запуска установите `SEED_PLACES=True`, чтобы загрузить места из KMZ.
2. Создайте локальную папку данных Loki для bind-mount:
   `mkdir -p loki_data`
3. Примените миграции вручную. Миграции не запускаются вместе с ботом:
   `docker compose up -d db`
   `docker compose build bot`
   Примените миграции:
   `docker compose run --rm --no-deps bot alembic upgrade head`
4. Соберите и запустите остальные сервисы:
   `docker compose up --build`
5. Сервисы будут доступны:
   - Бот в контейнере `aiogram_bot`.
   - Worker стартовой синхронизации в сервисе `places-worker`.
   - RabbitMQ AMQP: `localhost:5672`, Management UI: `localhost:15672`.
   - Postgres: `localhost:5432`.
   - Elasticsearch: `localhost:9200`.
   - Grafana: `localhost:3000`.
   - Loki: `localhost:3110`.

Локальный запуск (Poetry)
-------------------------
1. Установите зависимости:
   `cd bot`
   `poetry install`
   Для первого запуска установите `SEED_PLACES=True` в `.env`, чтобы загрузить места из KMZ.
2. Примените миграции БД:
   `poetry run alembic upgrade head`
3. Запустите бота:
   `poetry run python main.py`
4. В отдельном терминале запустите worker:
   `poetry run python -m application.workers.places_bootstrap_worker`

Миграции базы данных (Alembic)
------------------------------
Миграции применяются только вручную и не запускаются при старте бота.

Для Docker:
- Применить все миграции:
  `docker compose run --rm --no-deps bot alembic upgrade head`
- Создать новую миграцию по изменениям моделей:
  `docker compose run --rm --no-deps bot alembic revision --autogenerate -m "описание изменений"`
- Откатить одну миграцию:
  `docker compose run --rm --no-deps bot alembic downgrade -1`

Из директории `bot/` (без Docker):
- Применить все миграции:
  `poetry run alembic upgrade head`
- Создать новую миграцию по изменениям моделей:
  `poetry run alembic revision --autogenerate -m "описание изменений"`
- Откатить одну миграцию:
  `poetry run alembic downgrade -1`

Alembic читает настройки Postgres из `.env`:
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`
- `POSTGRES_HOST` (по умолчанию: `db`)
- `POSTGRES_PORT` (по умолчанию: `5432`)

Elasticsearch читает настройки из `.env`:
- `ELASTIC_URL` (например: `http://elasticsearch:9200`)
- `ELASTIC_USER` (например: `elastic`)
- `ELASTIC_PASSWORD`

Экспорт адресов в CSV
---------------------
Для выгрузки колонок `lat,lon,full_address` используйте скрипт:
- `bash scripts/export_lat_lon_full_address.sh`

С указанием имени файла:
- `bash scripts/export_lat_lon_full_address.sh lat_lon_full_address.csv`

Операционные заметки
--------------------
- Логи пишутся в `bot/logs/`.
- При старте бот:
  - публикует в RabbitMQ команду `places.bootstrap.requested`;
  - `places-worker` загружает места из KMZ;
  - worker обновляет адреса и переиндексирует Elasticsearch;
  - consumer отправляет ACK только после успешной обработки.
- Перед reverse geocoding бот пытается восстановить отсутствующие `full_address`
  из `bot/geo_data/lat_lon_full_address.csv` по координатам `lat/lon`.
