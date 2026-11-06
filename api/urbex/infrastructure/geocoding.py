"""User-triggered reverse lookup, cached and serialized (one API process)."""
import threading
import time
from functools import lru_cache
import httpx
from urbex.domain.rules import DomainError

_lock = threading.Lock()
_last_request = 0.0


@lru_cache(maxsize=1024)
def reverse_address(url, origin, latitude, longitude):
    global _last_request
    if not url:
        raise DomainError('Сервис определения адреса не настроен', 503)
    with _lock:
        time.sleep(max(0, 1.1 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        try:
            response = httpx.get(url.rstrip('/') + '/reverse', params={
                'lat':latitude, 'lon':longitude, 'format':'jsonv2', 'accept-language':'ru'},
                headers={'User-Agent':f'UrbexFinder/1.0 ({origin})'}, timeout=10)
            response.raise_for_status()
            payload = response.json()
            address = payload.get('display_name')
        except (httpx.HTTPError, ValueError):
            raise DomainError('Не удалось получить адрес. Повторите попытку или введите адрес вручную.', 502)
        if not isinstance(address, str) or not address.strip():
            raise DomainError('Адрес для этой точки не найден', 404)
        parts = payload.get('address') or {}
        region = parts.get('state') or parts.get('region') or parts.get('county') or parts.get('city') or address
        return {'address':address[:2000], 'region':str(region)[:200]}
