import logging
import queue
import threading
import time

import requests

# URL вашего Loki-сервера
LOKI_URL = "http://loki:3100/loki/api/v1/push"
LOKI_QUEUE_MAXSIZE = 5000

_queue: "queue.Queue[dict]" = queue.Queue(maxsize=LOKI_QUEUE_MAXSIZE)
_thread_started = False
_thread_lock = threading.Lock()
logger = logging.getLogger(__name__)


def _build_payload(message: str, level: str) -> dict:
    timestamp = str(int(time.time() * 1e9))  # наносекунды
    return {
        "streams": [
            {
                "stream": {"job": "aiogram_bot", "level": level},
                "values": [[timestamp, message]],
            }
        ]
    }


def _loki_worker() -> None:
    session = requests.Session()
    while True:
        payload = _queue.get()
        try:
            session.post(LOKI_URL, json=payload, timeout=2)
        except Exception as error:
            logger.info("Ошибка при отправке в Loki: %s", error)
        finally:
            _queue.task_done()


def _ensure_worker_started() -> None:
    global _thread_started
    if _thread_started:
        return

    with _thread_lock:
        if _thread_started:
            return
        thread = threading.Thread(target=_loki_worker, daemon=True, name="loki-log-worker")
        thread.start()
        _thread_started = True


def send_to_loki(message: str, level: str = "INFO") -> None:
    """
    Отправка логов в Grafana Loki через очередь и фоновый поток.
    """
    _ensure_worker_started()
    payload = _build_payload(message=message, level=level)
    try:
        _queue.put_nowait(payload)
    except queue.Full:
        # Под нагрузкой не блокируем поток выполнения приложения из-за логов.
        pass
