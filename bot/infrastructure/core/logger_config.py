import os
import sys
import threading
import tempfile

from loguru import logger

from infrastructure.core.send_to_loki import send_to_loki

_LOGGER_CONFIGURED = False
_LOGGER_LOCK = threading.Lock()


def _resolve_log_dir() -> str:
    """Возвращает директорию для логов с fallback на /tmp при проблемах с правами."""
    preferred = os.path.abspath("logs")
    fallback = os.path.join(tempfile.gettempdir(), "telegram_bot2_logs")
    for path in (preferred, fallback):
        try:
            os.makedirs(path, exist_ok=True)
            if os.access(path, os.W_OK):
                return path
        except OSError:
            continue
    return fallback


def setup_logger() -> logger:
    """
    Настройка логов для бота:
    - Логи идут в консоль с цветами
    - Логи пишутся в файлы с ротацией и сжатием
    - Логи отправляются в Grafana Loki
    """
    global _LOGGER_CONFIGURED
    if _LOGGER_CONFIGURED:
        return logger

    with _LOGGER_LOCK:
        if _LOGGER_CONFIGURED:
            return logger

        log_dir = _resolve_log_dir()
        logger.remove()  # убираем стандартный обработчик

        # INFO и выше в файл
        logger.add(
            os.path.join(log_dir, "bot_info_{time}.log"),
            rotation="1 MB",
            compression="zip",
            level="INFO",
            enqueue=True,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        )

        # ERROR и выше в файл
        logger.add(
            os.path.join(log_dir, "bot_error_{time}.log"),
            rotation="1 MB",
            compression="zip",
            level="ERROR",
            enqueue=True,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        )

        # Цветной вывод в консоль
        logger.add(
            sys.stdout,
            colorize=True,
            level="INFO",
            enqueue=True,
            format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | <cyan>{message}</cyan>",
        )

        # Отправка в Loki с использованием фоновой очереди.
        logger.add(
            lambda msg: send_to_loki(msg, level=msg.record["level"].name),
            level="INFO",
            enqueue=True,
        )

        _LOGGER_CONFIGURED = True
        return logger
