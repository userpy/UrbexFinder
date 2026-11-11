# UrbexFinder

Проект для поиска и исследования мест: Telegram-бот и веб-приложение с картой,
общим каталогом, фотографиями, отзывами и маршрутами. Бот и сайт используют
единую базу PostgreSQL/PostGIS. Фоновый воркер загружает места из KMZ/KML и CSV
и обновляет поисковый индекс.

## Технологический стек

| Компонент | Технологии | Назначение |
|---|---|---|
| Telegram-бот | Python 3.11 в Docker, aiogram 3 | Асинхронная обработка сообщений через long polling, поиск и просмотр мест, взаимодействие с пользователями. |
| Backend API | FastAPI, Uvicorn, Pydantic Settings | HTTP API веб-приложения и конфигурация серверной части. |
| Веб-интерфейс | Next.js, React, TypeScript, Tailwind CSS | Страницы каталога, личного кабинета и управления местами. |
| Карта | MapLibre GL | Отображение мест на интерактивной карте. |
| База данных | PostgreSQL 15, PostGIS | Общие данные пользователей, мест и географические координаты. |
| Доступ к БД и миграции | SQLAlchemy, asyncpg, psycopg2, Alembic | Асинхронный доступ бота к БД, доступ API и версионирование схемы. Миграциями управляет API. |
| Поиск | Elasticsearch | Поиск мест по названию, описанию, категории и адресу. |
| Фотографии | MinIO, boto3 | S3-совместимое объектное хранилище фотографий для веб/API-части. |
| Фоновые задачи | RabbitMQ, aio-pika, Python-воркер | Импорт мест, удаление дубликатов, дополнение адресов и индексация; повторные попытки и dead-letter queue для неудачных задач. |
| Логирование | Loguru, Grafana Loki, Grafana | Логи бота и воркера, их сбор и просмотр. |
| Инфраструктура | Docker, Docker Compose, Poetry | Сборка, запуск сервисов и управление зависимостями бота. |
| Тестирование | pytest, pytest-asyncio, Playwright | Модульные, интеграционные и браузерные тесты. |

## Архитектура

Код разделён на доменный слой, прикладные сценарии и адаптеры инфраструктуры.
Telegram-интерфейс находится в `bot`, HTTP API — в `api`, веб-интерфейс —
в `frontend`. Пакет `shared` содержит общие элементы каталога для бота и API.

Бот публикует команду стартовой синхронизации в RabbitMQ, а отдельный
`places-worker` выполняет импорт и индексацию. PostgreSQL хранит данные каталога,
Elasticsearch обеспечивает поиск, MinIO хранит фотографии. Перед запуском
бота и воркера одноразовые контейнеры применяют миграции БД и создают очереди.

## Запуск и конфигурация

Сайт в Docker доступен по адресу `http://localhost` (порт 80 хоста, внутри контейнера — 3100).

В репозитории четыре файла Docker Compose и два файла настроек:

- `docker-compose.yml` — локальный сайт, Telegram-бот и их сервисы.
- `docker-compose.prod.yml` — самостоятельный production-стек, без монтирования исходников.
- `docker-compose.test.yml` — изолированные тесты API, бота, браузера и миграций.
- `docker-compose.mini.yaml` — бот, БД, RabbitMQ, воркер и необходимый Elasticsearch; без сайта, API-сервера, MinIO и мониторинга.
- `.env` — локальные настройки всех компонентов и секреты (не входит в Git).
- `.env.example` — единый шаблон; копировать только при первом запуске, не поверх заполненного `.env`.

```bash
# Сайт и бот полностью в Docker
docker compose up -d --build
# API в Docker, frontend с горячей перезагрузкой
docker compose up -d --build api
npm --prefix frontend run dev
# Production: задайте URBEX_PROD_ORIGIN и production-пароли в .env
docker compose -f docker-compose.prod.yml up -d --build
# Тесты
docker compose -f docker-compose.test.yml run --build --rm tests
docker compose -f docker-compose.test.yml run --build --rm bot-tests
docker compose -f docker-compose.test.yml run --build --rm verify
npm --prefix frontend test
# Удаление только временного тестового окружения
docker compose -f docker-compose.test.yml --profile '*' down
```

API-тесты используют профиль `api`, браузерные — `e2e`, бот — `bot`, совместимость миграций — `compat`. При `run` профиль выбранного сервиса активируется автоматически. Браузерный runner сам запускает отдельный проект `urbexfinder-e2e` и очищает его после тестов. Все тестовые базы временные; production-тома к ним не подключаются.

Сайт и бот используют один сервис PostgreSQL/PostGIS `db`, одну базу и общие `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` из `.env`. Постоянные данные хранятся в томе `urbex_pg`. Миграциями управляет только API. Старый каталог `./pg_data` сохранён как архив и больше не подключается к сервисам. Frontend npm-скрипты читают только `API_INTERNAL_URL` и `NEXT_PUBLIC_MAP_STYLE_URL`.

Структура проекта
-----------------

- `api/` - FastAPI-приложение, миграции общей БД и тесты API.
- `frontend/` - веб-приложение на Next.js и браузерные тесты.
- `shared/` - общий Python-пакет каталога для API и бота.
- `bot/domain/` - доменные модели (SQLAlchemy ORM).
- `bot/application/` - прикладные сервисы и сценарии запуска.
- `bot/interface/` - адаптеры фреймворка: handlers, middleware, filters.
- `bot/infrastructure/` - интеграции: БД, логирование, внешние сервисы.
- `bot/main.py` - точка входа.
- `bot/geo_data/` - KMZ/KML- и CSV-источники для наполнения мест.
- `docker-compose.yml` - полный локальный стек сайта, бота и инфраструктуры.

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
   миграции API до запуска бота и worker.
4. Сервисы будут доступны:
   - Бот в сервисе `bot`.
   - Worker стартовой синхронизации в сервисе `places-worker`.
   - RabbitMQ AMQP: `localhost:5672`, Management UI: `localhost:15672`.
   - Postgres: `localhost:5432`.
   - Elasticsearch: `http://elasticsearch:9200` внутри Docker (порт на хост не публикуется).
   - Grafana: `localhost:3000`.
   - Loki: `localhost:3110`.

Минимальный запуск бота (Docker)
-------------------------------
`docker-compose.mini.yaml` запускается самостоятельно, с настройками из `.env`:

```bash
docker compose -f docker-compose.mini.yaml up -d --build
docker compose -f docker-compose.mini.yaml logs -f bot places-worker
```

В составе: бот, PostgreSQL/PostGIS, RabbitMQ и `places-worker`, а также
Elasticsearch, необходимый для поиска и индексации мест. Одноразовые сервисы
`migrations` и `rabbitmq-topology` подготавливают схему БД и очереди до запуска
бота и воркера. Сайт, API-сервер, MinIO, Loki и Grafana не запускаются.
Логи доступны через `docker compose logs`.

Для сидинга задайте в `.env` `SEED_PLACES=True`,
`ENQUEUE_PLACES_SYNC_ON_STARTUP=True` и `SEED_PLACES_SOURCE=kmz`, `csv` или `both`.
Пути к исходным файлам должны быть доступны внутри `/app` (каталог `bot` на хосте).

Проект `urbexfinder-mini` использует отдельные volumes для БД, очередей и поиска;
данные основного Compose автоматически не переносятся. Перед запуском остановите
основной стек, чтобы освободить порты и не запускать два экземпляра одного бота.
Остановка минимального стека с сохранением данных:
`docker compose -f docker-compose.mini.yaml down`.

Контейнеры Docker Compose
----------------------------
Compose формирует имена контейнеров из имени проекта и сервиса (`urbexfinder-<service>-1`). Следующие сервисы бота запускаются по умолчанию; сервисы сайта описаны в `URBEXFINDER.md`.

| Контейнер (сервис) | Что делает |
|---|---|
| `bot` | Основной долгоживущий процесс Telegram-бота. Запускает `python main.py`, получает обновления Telegram через long polling, обрабатывает команды, читает и изменяет данные в PostgreSQL, ищет места через Elasticsearch и отправляет логи в Loki. При включённом `ENQUEUE_PLACES_SYNC_ON_STARTUP` публикует в RabbitMQ команду синхронизации мест. |
| `places-worker` | Долгоживущий consumer RabbitMQ. По команде `places.bootstrap.requested` при необходимости загружает места из KMZ, удаляет дубликаты, дополняет адреса из CSV и пересоздаёт поисковый индекс Elasticsearch. При временной ошибке сообщение повторяется, а после исчерпания попыток попадает в dead-letter queue. |
| `migrations` | Одноразовый контейнер: после готовности PostgreSQL выполняет `python -m urbex.bootstrap.migrate` и завершается. `bot` и `places-worker` запускаются только после его успешного завершения. |
| `rabbitmq-topology` | Одноразовый контейнер: после готовности RabbitMQ создаёт durable exchange, основную очередь, retry-очередь, dead-letter-очередь и bindings, затем завершается. `bot` и `places-worker` ждут его успешного завершения. |
| `db` | PostgreSQL 15 — основное хранилище данных бота: пользователей, ролей, мест и ресурсов. Healthcheck не даёт зависимым сервисам стартовать до готовности БД. В локальном Compose порт `5432` опубликован на хост. |
| `elasticsearch` | Общий Elasticsearch 7.17.11 для бота и сайта. Индексы `places` и `urbex_places_v1`, данные в `urbex_search`. Доступ только внутри Docker. |
| `rabbitmq` (`rabbitmq`) | Брокер сообщений между `bot` и `places-worker`. AMQP доступен на порту `5672`, web-панель управления — на `15672`. Очереди и сообщения хранятся в volume `rabbitmq_data`. |
| `loki` (`loki`) | Собирает и хранит логи приложения. Внутренний HTTP API `3100` доступен на хосте как `3110`; данные хранятся в локальной папке `./loki_data`. |
| `grafana` (`grafana`) | Web-интерфейс для запроса и визуализации логов из Loki. Открывается на `http://localhost:3000`, а настройки, подключённые источники и dashboards хранятся в volume `grafana_data`. |

Сервисы общаются по внутренней сети `telegram_bot2_default`, используя имена
сервисов (`db`, `rabbitmq`, `elasticsearch`, `loki`) как DNS-имена. Это не
контейнер: сеть создаётся `docker compose up` и удаляется
`docker compose down`. Число контейнеров зависит от активных профилей.

`docker compose down` без флага `-v` не удаляет named volumes
`urbex_search`, `rabbitmq_data` и `grafana_data`, а также не удаляет bind-mount
`./loki_data`. Общая база сохраняется в томе `urbex_pg` и в локальной, и в production-конфигурации.

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
   `docker compose run --rm migrations`
3. Запустите бота:
   `poetry run python main.py`
4. В отдельном терминале запустите worker:
   `poetry run python -m application.workers.places_bootstrap_worker`

Тесты
-----
Тесты запускаются в отдельном Compose-проекте и используют временную PostgreSQL
в `tmpfs`. Рабочий `.env` и основная база данных не подключаются.

Запустить весь набор:
`docker compose -f docker-compose.test.yml run --build --rm bot-tests`

Остановить и удалить тестовые контейнеры:
`docker compose -f docker-compose.test.yml down --remove-orphans`

Для быстрого локального запуска только unit-тестов:
`cd bot`
`poetry install --with dev`
`poetry run pytest tests/unit`

Отчёт о покрытии:
`poetry run pytest --cov=. --cov-report=term-missing`

Локальный запуск API (Poetry)
----------------------------
Локальная установка и запуск API (Python 3.13–3.14):

```bash
cd api
poetry install --with dev
poetry run uvicorn urbex.bootstrap.main:app --reload
```

Poetry также устанавливает локальный пакет `../shared`. Зависимости API фиксируются в
`api/poetry.lock`; после изменения зависимостей обновляйте его командой `poetry lock`.
Тесты запускаются через `poetry run python -m pytest` с настроенным изолированным
тестовым окружением (БД и Elasticsearch), либо через существующий Docker Compose.

Миграции базы данных (API)
--------------------------
Единственный владелец миграций — API. Все ревизии находятся в `api/migrations/versions`, включая исторические ревизии бота. Сервис `migrations` использует образ API и команду `python -m urbex.bootstrap.migrate`. Бот, worker и API ждут его успешного завершения.

```bash
docker compose run --rm migrations
# Новая ревизия создаётся только в API, изменения схемы задаются явно:
docker compose run --rm --no-deps migrations alembic revision -m "описание изменений"
```

История сайта продолжена после исторической цепочки бота. Старая `alembic_version` сохраняется как архивный маркер, активная версия — `web_alembic_version`. Миграция старой базы бота подхватывает её ревизию без повторного создания таблиц. Повторный запуск безопасен; параллельные запуски сериализуются блокировкой PostgreSQL.

Сервис `migrations` обновляет единственную базу через `URBEX_DATABASE_URL`, который Compose формирует из общих `POSTGRES_*`. Бот подключается к той же базе. Отдельного подключения для чтения рейтингов больше нет.

Локально из `api/`: `poetry run python -m urbex.bootstrap.migrate`; передайте `URBEX_DATABASE_URL` через окружение. Автоматический откат общей схемы не предусмотрен: используйте резервную копию и проверенный план восстановления.

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

Экспорт всех мест в CSV
----------------------
Запустите `bash scripts/export_places.sh` при работающем сервисе `db` в Docker Compose.
Скрипт выгружает все строки и столбцы таблицы `places`, включая скрытые места и
записи без координат, в `places.csv` в корне проекта. Формат: UTF-8, разделитель
запятая, первая строка содержит названия столбцов, сортировка по `id`.

Другой путь можно передать аргументом: `bash scripts/export_places.sh /tmp/places.csv`.
Относительные пути считаются от корня проекта. Существующий файл заменяется
только после успешной выгрузки. Настройки подключения берутся из контейнера `db`.

Скачивание Geocaching в places CSV
---------------------------------
Из корня проекта запустите:

```bash
python3 scripts/import_geocaching.py
```

Скрипт скачивает все места, возвращаемые публичной картой geocaching.su для всего
мира, и создаёт `geocaching_places.csv` в текущей директории. Авторизация не нужна.
Требуются Python 3 и `curl`. Другой путь: `python3 scripts/import_geocaching.py -o /tmp/places.csv`.
Выгружаются название, координаты, тип и ссылка на карточку в `description`.
Полные описания и адреса публичная карта не возвращает. Полнота ограничена ответом
сайта: это не выгрузка его внутренней базы данных.

Также можно преобразовать ранее скачанный GPX с описаниями:

```bash
python3 scripts/import_geocaching.py caches.gpx geocaching_places.csv
```

Для локального GPX достаточно Python 3. Пути считаются от текущей
директории. Скрипт создаёт CSV в UTF-8 с полями таблицы `places`, кроме `id`
(при вставке его должна назначать база). Название и описания берутся из расширения
`cache`, если оно есть, иначе из стандартных полей GPX. Ссылка сохраняется в описании,
`category` равна `geocaching`, рейтинги и счётчик жалоб — нулю, адрес пустой.
Координаты округляются до шести знаков. При неверных координатах или пустой выгрузке
скрипт завершается с ошибкой, сохраняя прежний выходной файл.

Скрипт не записывает места в БД и не запускает индексацию.
Передать полученный CSV существующему обновлению
адресов нельзя: оно обрабатывает только `lat,lon,full_address` и не создаёт места.

Импорт CSV в таблицу places
--------------------------
Запустите при работающем сервисе `db` в Docker Compose:

```bash
python3 scripts/import_places.py
```

Выберите номер CSV из корня проекта или `bot/geo_data`, либо введите путь к другому
файлу. Можно сразу передать путь:

```bash
python3 scripts/import_places.py geocaching_places.csv
```

Для production явно укажите Compose-файл: проекты `urbexfinder` и
`urbexfinder-prod` используют разные тома PostgreSQL. Импорт в локальный стек
не заполняет production-базу. При `SEED_PLACES=False` стартовая задача также
не импортирует места. Разовая загрузка каталога и обновление поиска сайта:

```bash
docker compose -f docker-compose.prod.yml up -d db
python3 scripts/import_places.py -f docker-compose.prod.yml bot/geo_data/places.csv
docker compose -f docker-compose.prod.yml up -d api web
docker compose -f docker-compose.prod.yml exec api python -m urbex.bootstrap.cli reindex-search
```

Если используете автоматический CSV-импорт через бота, после обновления кода
пересоберите образы: `docker compose -f docker-compose.prod.yml up -d --build bot places-worker`.

CSV должен быть в UTF-8 (BOM допустим), с разделителем-запятой и заголовками
`name,latitude,longitude`. Дополнительные поля: `description,type,category,full_address`.
Колонки `id`, рейтингов и жалоб игнорируются: ID назначает база, статистика новых
мест начинается с нуля. Координаты обязательны и округляются до шести знаков.
При совпадении координат с существующим местом строка пропускается; среди повторов
в самом CSV используется первая строка. Существующие места не обновляются.

Весь файл проверяется до записи. Вставка выполняется одной транзакцией; при ошибке
БД изменения откатываются. В результате выводятся `csv_rows`, `inserted`, `skipped`.
Проверка без записи: `python3 scripts/import_places.py geocaching_places.csv --check`.
Скрипт меняет только PostgreSQL; для поиска новых мест через Elasticsearch потребуется
штатная переиндексация проекта.

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

## Импорт мест из CSV

Поддерживается `bot/geo_data/places.csv` в UTF-8 (в том числе BOM), с разделителем `,` или `;`. Обязательные колонки: `name,latitude,longitude` (также поддерживаются `lat,lon`). Дополнительные: `description,type,category,full_address` (или `address`). Числа с десятичной запятой должны быть корректно заключены в кавычки либо использовать `;` как разделитель.

В `.env` и `.env.example` добавлены `PLACES_CSV_PATH=geo_data/places.csv` и `SEED_PLACES_SOURCE=kmz|csv|both`. `SEED_PLACES=True` включает импорт при стартовой задаче бота; `both` сначала обрабатывает KMZ, затем CSV. После изменения настроек пересоздайте бота и worker: `docker compose up -d bot places-worker`. По умолчанию автоматическое заполнение остаётся выключенным. `CSV_PATH` — прежний файл дополнения адресов, это отдельная настройка.

Явный запуск CSV-импорта независимо от `SEED_PLACES`:

```bash
# Проверка без добавления мест
docker compose exec places-worker python -m application.startup.import_places_csv --dry-run
# Импорт настроенного файла
docker compose exec places-worker python -m application.startup.import_places_csv
# Другой файл внутри контейнера
docker compose exec places-worker python -m application.startup.import_places_csv --path geo_data/another.csv
```

Совпадения координат с точностью 6 знаков пропускаются, включая дубликаты внутри CSV. Существующие карточки не перезаписываются. ID из файла, оценки, жалобы и состояния публикации не импортируются; новые ID создаёт база. Новые записи из CSV сразу получают статус `published` и доступны в поиске сайта и бота после обновления индексов. Ошибка в любой строке отменяет весь импорт; сначала исправьте указанную строку и повторите. В CSV-режиме нет автоматических запросов внешнего геокодера.

Новые места из KMZ и из `scripts/import_places.py` также публикуются сразу.
Места, добавленные через сайт, получают `pending` и проходят модерацию.
Повторный импорт не меняет статус существующих мест.

### Регистрация и вход через Telegram

На странице входа и регистрации доступна кнопка «Войти / зарегистрироваться через Telegram».
Сайт показывает одноразовый код и ссылку на бота. Пользователь нажимает «Старт»,
сверяет код и подтверждает вход в личном чате. После возвращения в тот же браузер
вход завершается автоматически. При первом входе создаётся обычный пользователь,
при следующих используется тот же Telegram ID. Аккаунты с email (включая администратора)
автоматически не объединяются с Telegram-аккаунтами.

`URBEX_TELEGRAM_BOT_USERNAME` в `.env` — имя бота без `@`; `TOKEN` — его серверный токен.
API и бот должны работать с общей базой `urbex_catalog`; перед запуском применяется
миграция `web_005`. Ссылка действует 5 минут, подтверждается только получившим её
Telegram-пользователем и завершается только браузером, создавшим запрос.
Токен бота не передаётся на сайт. Публичный HTTPS callback для этого способа не нужен.

Карточка места показывает отзывы из Telegram; формы отзыва, оценки и загрузки фото
на сайте временно скрыты. Кнопка «Добавить в маршрутный лист» сразу добавляет место в активный маршрут.
Если активного листа нет, он создаётся автоматически с текущей датой. Повторное
нажатие не создаёт дубликат места.
При сохранении новых точек маршрута они также добавляются в избранное в той же
транзакции. Удаление точки или маршрута не удаляет ранее сохранённое избранное.

Бот, worker и API используют один Elasticsearch. Compose задаёт всем URL из
`URBEX_ELASTICSEARCH_URL` и авторизацию из `URBEX_ELASTICSEARCH_USER/PASSWORD`.
Старый том `telegram_bot2_es_data` после объединения сохранён для отката,
но действующие сервисы его не используют.

Маршрутный лист создаётся кнопкой «+ Новый маршрут» с названием по текущей дате.
Дата создания сохраняется сервером автоматически. В списке можно удалить лист
или отметить его активным; у пользователя может быть только один активный лист.
Снятие галочки оставляет список без активного маршрута. Дата поездки редактируется
отдельно и не меняет дату создания.

### Отправка маршрута через сервер Next.js

Кнопка «В Telegram» вызывает `POST /api/itineraries/{id}/telegram` — серверный
Route Handler Next.js. Он обращается к FastAPI по `API_INTERNAL_URL`
(в Docker — `http://api:8000`) и передаёт исходный Origin, cookie сессии и
CSRF-токен. FastAPI проверяет источник, сессию и владельца маршрута и отправляет
сообщения в Telegram. Токен бота остаётся в API; автоматического повтора отправки
при сетевой ошибке нет, чтобы избежать дубликатов.

Публичный адрес сайта по-прежнему должен совпадать с `URBEX_ORIGIN` для локального
стека или `URBEX_PROD_ORIGIN` для production. Внутренний адрес `http://api:8000`
не является публичным Origin. После изменения обработчика пересоберите web:
`docker compose up -d --build --no-deps web` (для production добавьте
`-f docker-compose.prod.yml` после `compose`).

Проверки обработчика: `cd frontend && node --test tests/telegram-handler.test.mjs`.
