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

Контейнеры Docker Compose
----------------------------
Команда `docker compose up` запускает девять контейнеров. Часть имён
задана явно через `container_name`, а имена вида
`telegram_bot2-<service>-1` Docker Compose формирует из имени проекта,
сервиса и номера экземпляра.

| Контейнер (сервис) | Что делает |
|---|---|
| `aiogram_bot` (`bot`) | Основной долгоживущий процесс Telegram-бота. Запускает `python main.py`, получает обновления Telegram через long polling, обрабатывает команды, читает и изменяет данные в PostgreSQL, ищет места через Elasticsearch и отправляет логи в Loki. При включённом `ENQUEUE_PLACES_SYNC_ON_STARTUP` публикует в RabbitMQ команду синхронизации мест. |
| `telegram_bot2-places-worker-1` (`places-worker`) | Долгоживущий consumer RabbitMQ. По команде `places.bootstrap.requested` при необходимости загружает места из KMZ, удаляет дубликаты, дополняет адреса из CSV и пересоздаёт поисковый индекс Elasticsearch. При временной ошибке сообщение повторяется, а после исчерпания попыток попадает в dead-letter queue. |
| `telegram_bot2-migrations-1` (`migrations`) | Одноразовый контейнер: после готовности PostgreSQL выполняет `alembic upgrade head` и завершается. `bot` и `places-worker` запускаются только после его успешного завершения. |
| `telegram_bot2-rabbitmq-topology-1` (`rabbitmq-topology`) | Одноразовый контейнер: после готовности RabbitMQ создаёт durable exchange, основную очередь, retry-очередь, dead-letter-очередь и bindings, затем завершается. `bot` и `places-worker` ждут его успешного завершения. |
| `postgres_db` (`db`) | PostgreSQL 15 — основное хранилище данных бота: пользователей, ролей, мест и ресурсов. Healthcheck не даёт зависимым сервисам стартовать до готовности БД. В локальном Compose порт `5432` опубликован на хост. |
| `elasticsearch` (`elasticsearch`) | Одноузловой Elasticsearch 7.17.11 с включённой авторизацией. Хранит поисковый индекс мест для быстрого поиска; PostgreSQL остаётся основным источником данных. Порты `9200` (HTTP API) и `9300` (transport) опубликованы на хост, индекс хранится в volume `es_data`. |
| `rabbitmq` (`rabbitmq`) | Брокер сообщений между `bot` и `places-worker`. AMQP доступен на порту `5672`, web-панель управления — на `15672`. Очереди и сообщения хранятся в volume `rabbitmq_data`. |
| `loki` (`loki`) | Собирает и хранит логи приложения. Внутренний HTTP API `3100` доступен на хосте как `3110`; данные хранятся в локальной папке `./loki_data`. |
| `grafana` (`grafana`) | Web-интерфейс для запроса и визуализации логов из Loki. Открывается на `http://localhost:3000`, а настройки, подключённые источники и dashboards хранятся в volume `grafana_data`. |

Сервисы общаются по внутренней сети `telegram_bot2_default`, используя имена
сервисов (`db`, `rabbitmq`, `elasticsearch`, `loki`) как DNS-имена. Это не
контейнер: сеть создаётся `docker compose up` и удаляется
`docker compose down`. Поэтому в примере вывода `down 10/10` означает
девять удалённых контейнеров и одну удалённую сеть.

`docker compose down` без флага `-v` не удаляет named volumes
`es_data`, `rabbitmq_data` и `grafana_data`, а также не удаляет bind-mount
`./loki_data`. Однако в локальном `docker-compose.yml` к PostgreSQL не
подключён volume, поэтому удаление `postgres_db` также удаляет его
локальные данные. В production-конфигурации PostgreSQL использует
named volume `postgres_data`.

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
