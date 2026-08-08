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
Создайте файл `.env` в корне репозитория. Полный пример есть в `.env.example`.

Обязательные переменные приложения:
- `TOKEN` - токен Telegram-бота.
- `ADMIN_NAME` - имя администратора.
- `ADMIN_ID` - Telegram ID администратора.
- `KMZ_PATH` - путь к KMZ-файлу с местами.
- `CSV_PATH` - путь к CSV-файлу с адресами мест.
- `SEED_PLACES` - запуск первичного сидинга мест (`True`/`False`).
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT`.
- `ELASTICSEARCH_HOST`, `ELASTICSEARCH_USER`, `ELASTICSEARCH_PASSWORD`.
- `RABBITMQ_USER`, `RABBITMQ_PASSWORD`, `RABBITMQ_HOST`, `RABBITMQ_PORT`.

RabbitMQ topology для стартовой синхронизации мест:
- topic exchange: `bot.commands.exchange`;
- queue: `bot.commands`;
- routing/binding key: `places.bootstrap.requested`;
- retry exchange/queue: `bot.commands.retry.exchange` / `bot.commands.retry`;
- dead-letter exchange/queue: `bot.commands.dead.exchange` / `bot.commands.dead`;
- `RABBITMQ_MAX_RETRY_ATTEMPTS` задаёт число повторов временно упавшей команды;
- `RABBITMQ_RETRY_DELAY_MS` задаёт задержку между попытками;
- `RABBITMQ_CONNECTION_MAX_ATTEMPTS` задаёт число попыток подключения
  topology-сервиса при старте;
- `RABBITMQ_CONNECTION_RETRY_DELAY_MS` задаёт начальную задержку между попытками
  подключения (далее используется exponential backoff до 5 секунд);
- модуль `exchange_queue_topology.py` создаёт topology до запуска bot и worker;
- `ENQUEUE_PLACES_SYNC_ON_STARTUP` включает публикацию startup-команды.

Некорректные JSON-сообщения и неизвестные routing key сразу попадают
в dead-letter queue. Ошибки бизнес-обработчика повторяются с задержкой, а после
исчерпания лимита перемещаются в `bot.commands.dead`.
RabbitMQ хранит свои данные в named volume `rabbitmq_data`.

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
3. Соберите и запустите сервисы:
   `docker compose up --build`
   Одноразовый сервис `migrations` дождётся готовности PostgreSQL и применит
   `alembic upgrade head` до запуска бота и worker.
4. Сервисы будут доступны:
   - Бот в контейнере `aiogram_bot`.
   - Worker стартовой синхронизации в сервисе `places-worker`.
   - RabbitMQ AMQP: `localhost:5672`, Management UI: `localhost:15672`.
   - Postgres: `localhost:5432`.
   - Elasticsearch: `localhost:9200`.
   - Grafana: `localhost:3000`.
   - Loki: `localhost:3110`.

Простой запуск в production
---------------------------
Production-конфигурация находится в `docker-compose.prod.yml`. Она не
монтирует исходный код внутрь контейнеров, сохраняет данные PostgreSQL в named
volume и не публикует порты PostgreSQL, Elasticsearch, RabbitMQ AMQP и Loki.

1. Заполните `.env` production-значениями и смените все стандартные пароли.
2. Соберите и запустите стек:
   `docker compose -f docker-compose.prod.yml up -d --build`
3. Проверьте состояние:
   `docker compose -f docker-compose.prod.yml ps`
4. Посмотрите логи приложения:
   `docker compose -f docker-compose.prod.yml logs -f bot places-worker`

Grafana (`3000`) и RabbitMQ Management (`15672`) слушают только
`127.0.0.1` сервера. Для доступа с рабочего компьютера используйте SSH-туннель
или настройте отдельный HTTPS reverse proxy с авторизацией.

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

Тесты
-----
Тесты запускаются в отдельном Compose-проекте и используют временную PostgreSQL
в `tmpfs`. Рабочий `.env` и основная база данных не подключаются.

Запустить весь набор:
`docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from tests`

Остановить и удалить тестовые контейнеры:
`docker compose -f docker-compose.test.yml down --remove-orphans`

Для быстрого локального запуска только unit-тестов:
`cd bot`
`poetry install --with dev`
`poetry run pytest tests/unit`

Отчёт о покрытии:
`poetry run pytest --cov=. --cov-report=term-missing`

Миграции базы данных (Alembic)
------------------------------
При запуске Docker Compose одноразовый сервис `migrations` автоматически
применяет все миграции до старта `bot` и `places-worker`. Если миграция завершится
с ошибкой, зависящие сервисы не запустятся.

Для Docker:
- Повторно применить все миграции вручную:
  `docker compose run --rm migrations`
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
- `ELASTICSEARCH_HOST` (например: `http://elasticsearch:9200`)
- `ELASTICSEARCH_USER` (например: `elastic`)
- `ELASTICSEARCH_PASSWORD`

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
