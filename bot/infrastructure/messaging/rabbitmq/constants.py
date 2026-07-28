"""Константы RabbitMQ topology и подключения."""

EXCHANGE_NAME = "bot.commands.exchange"
STARTUP_QUEUE_NAME = "bot.commands"
PLACES_BOOTSTRAP_ROUTING_KEY = "places.bootstrap.requested"
RETRY_EXCHANGE_NAME = "bot.commands.retry.exchange"
RETRY_QUEUE_NAME = "bot.commands.retry"
DEAD_LETTER_EXCHANGE_NAME = "bot.commands.dead.exchange"
DEAD_LETTER_QUEUE_NAME = "bot.commands.dead"
CONNECTION_TIMEOUT_SECONDS = 3.0
