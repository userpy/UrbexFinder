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
- `SEED_PLACES` - запуск первичного сидинга мест (`True`/`False`).
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT`.
- `ELASTIC_URL`, `ELASTIC_USER`, `ELASTIC_PASSWORD`.

Дополнительно:
- `TG_CHANNEL_ID` - ID Telegram-канала.
- `GF_SECURITY_ADMIN_USER`, `GF_SECURITY_ADMIN_PASSWORD` - учётные данные Grafana.

Примечания:
- Для Docker путь `KMZ_PATH` должен быть внутри контейнера,
  например: `geo_data/Покинутые_индустриальные_объекты.kmz`.
- `docker-compose.yml` использует `.env` для конфигурации Postgres и Grafana.
- Elasticsearch запускается с включенной security, пользователь `elastic`.

Быстрый старт (Docker)
----------------------
1. Создайте `.env` в корне репозитория.
2. Соберите и запустите сервисы:
   `docker compose up --build`
3. Сервисы будут доступны:
   - Бот в контейнере `aiogram_bot`.
   - Postgres: `localhost:5432`.
   - Elasticsearch: `localhost:9200`.
   - Grafana: `localhost:3000`.
   - Loki: `localhost:3110`.

Локальный запуск (Poetry)
-------------------------
1. Установите зависимости:
   `cd bot`
   `poetry install`
2. Примените миграции БД:
   `poetry run alembic upgrade head`
3. Запустите бота:
   `poetry run python main.py`

Миграции базы данных (Alembic)
------------------------------
Внутри Docker-контейнера:
- Применить все миграции:
  `docker compose exec bot poetry run alembic upgrade head`
- Создать новую миграцию по изменениям моделей:
  `docker compose exec bot poetry run alembic revision --autogenerate -m "описание изменений"`
- Откатить одну миграцию:
  `docker compose exec bot poetry run alembic downgrade -1`

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
  - загружает места из KMZ;
  - обновляет отсутствующие адреса через reverse geocoding;
  - переиндексирует данные в Elasticsearch.
