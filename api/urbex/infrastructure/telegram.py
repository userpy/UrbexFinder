"""Server-only Telegram photo transport. Never return upstream URLs or errors."""
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


def send_route(token, chat_id, route):
    """Deliver a complete route as a UTF-8 document, without message-size truncation."""
    if not token:
        raise DomainError('Отправка в Telegram временно недоступна', 503)
    lines = [route['name']]
    if route.get('trip_date'):
        lines.append(f"Дата поездки: {route['trip_date']}")
    statuses = {'planned': 'Планирую', 'visited': 'Посетил', 'skipped': 'Пропустил'}
    for index, item in enumerate(route['items'], 1):
        place = item.get('place')
        lines.extend(['', f"{index}. {place['name'] if place else 'Место недоступно'}",
                      statuses.get(item['status'], item['status'])])
        if place:
            lat, lon = place['latitude'], place['longitude']
            lines.extend([place.get('full_address') or place.get('region') or '',
                          f'{lat}, {lon}', f'https://yandex.ru/maps/?pt={lon},{lat}&z=16&l=map'])
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            response = client.post(f'https://api.telegram.org/bot{token}/sendDocument',
                data={'chat_id': str(chat_id), 'caption': route['name']},
                files={'document': (f"route-{route['id']}.txt", '\n'.join(lines).encode('utf-8'), 'text/plain')})
            response.raise_for_status()
            if not response.json().get('ok'):
                raise ValueError('Delivery failed')
    except (httpx.HTTPError, ValueError):
        raise DomainError('Не удалось отправить маршрут. Откройте чат с ботом, нажмите «Старт» и повторите отправку.', 502) from None
