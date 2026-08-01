# Отчёт об ошибке: `rabbitmq-topology` завершается с кодом 1 при запуске Compose

**ID:** BUG-RMQ-001  
**Дата обнаружения:** 2026-08-01  
**Статус:** Open  
**Приоритет:** High  
**Серьёзность:** Major  
**Компоненты:** Docker Compose, RabbitMQ, `rabbitmq-topology`  
**Воспроизводимость:** периодическая при холодном старте

## Краткое описание

При запуске проекта одноразовый сервис `rabbitmq-topology` начинает работу после
успешного healthcheck RabbitMQ, однако AMQP listener RabbitMQ на порту 5672 в этот
момент ещё может быть недоступен. Первая и единственная попытка подключения
получает `ConnectionRefusedError`, контейнер завершается с кодом 1, после чего
Docker Compose не запускает зависящие от него сервисы `bot` и `places-worker`.

Сообщение верхнего уровня:

```text
Container telegram_bot2-rabbitmq-topology-1 Error service "rabbitmq-topology" didn't complete successfully: exit 1
service "rabbitmq-topology" didn't complete successfully: exit 1
```

## Окружение

- Revision: `0f09db9`
- ОС: Linux 7.0.0-28-generic x86_64
- Docker Engine: 29.6.1 (client/server)
- Docker Compose: v5.3.1
- RabbitMQ image: `rabbitmq:3-management`
- Конфигурация подключения: `RABBITMQ_HOST=rabbitmq`, порт 5672

## Предусловия

- Docker доступен и Compose-сервисы остановлены.
- `.env` содержит обязательные переменные RabbitMQ.
- RabbitMQ запускается заново или восстанавливается после остановки.

## Шаги воспроизведения

1. Запустить стек командой `docker compose up --build`.
2. Дождаться прохождения healthcheck сервиса `rabbitmq`.
3. Наблюдать запуск `rabbitmq-topology`.
4. Проверить состояние сервисов командой `docker compose ps -a`.
5. Проверить первичную ошибку командой
   `docker compose logs --no-color rabbitmq-topology`.

## Фактический результат

- `rabbitmq-topology` имеет состояние `Exited (1)`.
- `bot` и `places-worker` остаются в состоянии `Created`, поскольку используют
  зависимость `condition: service_completed_successfully`.
- В логе `rabbitmq-topology` присутствует ошибка подключения:

```text
aiormq.exceptions.AMQPConnectionError: [Errno 111] Connect call failed ('172.24.0.4', 5672)
```

Зафиксированная последовательность событий (UTC):

| Событие | Время |
|---|---:|
| Старт контейнера RabbitMQ | `02:28:12.393` |
| Старт `rabbitmq-topology` | `02:28:18.077` |
| Завершение `rabbitmq-topology`, exit 1 | `02:28:18.969` |
| RabbitMQ открыл AMQP listener на 5672 | `02:28:19.004` |
| RabbitMQ сообщил о полном завершении запуска | `02:28:19.035` |

Таким образом, topology-сервис начал подключение примерно за 927 мс до открытия
AMQP-порта и завершился примерно за 36 мс до его открытия.

## Ожидаемый результат

- `rabbitmq-topology` запускается только после готовности AMQP listener либо
  повторяет подключение при временном отказе.
- Exchange, queues и bindings успешно создаются.
- `rabbitmq-topology` завершается с кодом 0.
- `bot` и `places-worker` переходят в состояние `Running`.

## Причина

В `docker-compose.yml` готовность RabbitMQ проверяется командой:

```yaml
healthcheck:
  test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"]
```

Этот healthcheck подтверждает работоспособность узла RabbitMQ, но в
зафиксированном запуске стал успешным до открытия клиентского AMQP listener.
После этого Compose немедленно запустил `rabbitmq-topology`.

В `exchange_queue_topology.py` задано подключение с таймаутом 3 секунды, но нет
повторных попыток при `AMQPConnectionError`/`ConnectionRefusedError`. Таймаут
ограничивает длительность отдельной попытки и не предотвращает немедленный отказ
при отклонённом TCP-соединении.

**Корневая причина:** гонка между healthcheck, не проверяющим фактическую
доступность AMQP listener, и одноразовым клиентом без retry на старте.

## Влияние

- Полный запуск приложения блокируется из-за отказа вспомогательного one-shot
  сервиса.
- Автоматический перезапуск не выполняется, поскольку для `rabbitmq-topology`
  задано `restart: "no"`.
- Ошибка носит временный характер: RabbitMQ становится готов практически сразу
  после завершения topology-контейнера, что усложняет диагностику.

## Рекомендации по исправлению

1. Изменить healthcheck RabbitMQ так, чтобы он проверял готовность клиентских
   listener'ов, например с помощью `rabbitmq-diagnostics -q
   check_port_connectivity` (после проверки совместимости с используемым
   образом).
2. Добавить в `rabbitmq-topology` ограниченные повторные попытки подключения с
   задержкой/backoff для временных сетевых ошибок. Это защитит также от других
   кратковременных расхождений между healthcheck и доступностью сервиса.
3. Логировать номер попытки, предельное число попыток и адрес подключения без
   вывода пароля.

## Временный обходной путь

После того как RabbitMQ полностью запущен, повторно запустить стек либо только
завершившийся topology-сервис. Это не устраняет гонку и не подходит как
постоянное решение.

## Критерии приёмки

- На чистом и повторно используемом `rabbitmq_data` не менее 10 последовательных
  холодных стартов завершаются без `exit 1` у `rabbitmq-topology`.
- В момент запуска `rabbitmq-topology` AMQP-порт RabbitMQ доступен для
  подключения из Compose-сети.
- Временный `ConnectionRefusedError` не завершает процесс до исчерпания
  настроенного количества попыток или общего startup timeout.
- После успешной инициализации `rabbitmq-topology` завершается с кодом 0, а
  `bot` и `places-worker` запускаются.
- Ошибки аутентификации, несовместимой topology и некорректной конфигурации не
  маскируются бесконечными повторами и завершают сервис с понятным сообщением.

