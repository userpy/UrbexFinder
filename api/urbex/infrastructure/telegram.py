"""Server-only Telegram photo transport. Never return upstream URLs or errors."""
import logging
from html import escape
import httpx
from urbex.domain.rules import DomainError
from .storage import MAX_PHOTO_BYTES, sanitize_photo


class TelegramPhotos:
    def __init__(self, token):
        self.token = token

    def get(self, file_id):
        # Telegram can fail transiently; retry without exposing token-bearing URLs.
        for attempt in range(2):
            try:
                return self._get_once(file_id)
            except DomainError as error:
                if error.status != 502 or attempt == 1:
                    raise

    def _get_once(self, file_id):
        if not self.token:
            raise DomainError('Фотографии Telegram временно недоступны', 503)
        try:
            with httpx.Client(timeout=15, follow_redirects=False) as client:
                response = client.post(f'https://api.telegram.org/bot{self.token}/getFile', json={'file_id': file_id})
                response.raise_for_status()
                payload = response.json()
                if not payload.get('ok'):
                    raise ValueError('File unavailable')
                file = payload['result']
                path = file['file_path']
                if '..' in path or path.startswith('/') or ':' in path:
                    raise ValueError('Invalid file path')
                if file.get('file_size', 0) > MAX_PHOTO_BYTES:
                    raise ValueError('File too large')
                data = bytearray()
                with client.stream('GET', f'https://api.telegram.org/file/bot{self.token}/{path}') as stream:
                    stream.raise_for_status()
                    for chunk in stream.iter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_PHOTO_BYTES:
                            raise ValueError('File too large')
                return sanitize_photo(bytes(data))
        except (httpx.HTTPError, ValueError, KeyError, DomainError):
            raise DomainError('Не удалось загрузить фотографию Telegram', 502) from None


def route_messages(route):
    """Pack complete place cards into conservative Telegram HTML message limits."""
    # Counting HTML source in UTF-16 is conservative: entities/tags only reduce
    # the rendered length, and astral characters count as two units.
    limit = 4000

    def size(value):
        return len(value.encode('utf-16-le')) // 2

    def label(value, maximum):
        value = str(value or '')
        if len(value) > maximum:
            value = value[:maximum - 1] + '…'
        return escape(value)

    title = f"<b>{label(route['name'], 150)}</b>"
    if route.get('trip_date'):
        title += f"\nДата поездки: {label(route['trip_date'], 40)}"
    statuses = {'planned': 'Планирую', 'visited': 'Посетил', 'skipped': 'Пропустил'}
    messages, current = [], title
    for index, item in enumerate(route['items'], 1):
        place = item.get('place')
        lines = [f"<b>{index}. {label(place['name'] if place else 'Место недоступно', 150)}</b>",
                 label(statuses.get(item['status'], item['status']), 40)]
        if place:
            lat = f"{float(place['latitude']):.6f}"
            lon = f"{float(place['longitude']):.6f}"
            address = place.get('full_address') or place.get('region')
            if address:
                lines.append(label(address, 250))
            lines.extend([f'Координаты: <code>{lat}, {lon}</code>',
                          f'<a href="https://yandex.ru/maps/?pt={lon},{lat}&amp;z=16&amp;l=map">Открыть на карте</a>'])
        card = '\n'.join(lines)
        if size(current + '\n\n' + card) > limit:
            messages.append(current)
            current = title + '\n(продолжение)'
        current += '\n\n' + card
    if not route['items']:
        current += '\n\nВ маршруте пока нет мест.'
    messages.append(current)
    return messages


def send_route(token, chat_id, route):
    """Send ordered place lists with copyable coordinates and map links."""
    if not token:
        raise DomainError('Отправка в Telegram временно недоступна', 503)
    sent = 0
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            for message in route_messages(route):
                response = client.post(f'https://api.telegram.org/bot{token}/sendMessage',
                    json={'chat_id': str(chat_id), 'text': message, 'parse_mode': 'HTML',
                          'link_preview_options': {'is_disabled': True}})
                response.raise_for_status()
                if not response.json().get('ok'):
                    raise ValueError('Delivery failed')
                sent += 1
    except (httpx.HTTPError, ValueError) as error:
        # Never log the exception text: httpx URLs contain the bot token.
        logging.getLogger(__name__).warning(
            'Telegram route delivery failed: type=%s sent=%d', type(error).__name__, sent)
        if sent:
            detail = (f'Маршрут отправлен частично: сообщений — {sent}. '
                      'Повторная отправка начнёт список заново.')
        elif isinstance(error, (httpx.ConnectTimeout, httpx.ConnectError)):
            detail = 'Сервер не смог подключиться к Telegram. Попробуйте отправить маршрут позже.'
        elif isinstance(error, httpx.TimeoutException):
            detail = 'Telegram не ответил вовремя. Проверьте чат перед повторной отправкой.'
        elif isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 403:
            detail = 'Бот не может отправить вам сообщение. Откройте чат с ботом, разблокируйте его и нажмите «Старт».'
        else:
            detail = 'Не удалось отправить маршрут в Telegram. Попробуйте позже.'
        raise DomainError(detail, 502) from None
