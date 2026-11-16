"""Bounded primary-page enrichment for known public catalog sites."""
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from threading import Lock
from time import monotonic
from urllib.parse import urlparse
import httpx
from .osint_identity import extract_page_identity, source_key, verify_source

_HOSTS = {'wikimapia.org', 'geocaching.su', 'urban3p.ru', 'urban3p.com',
          'swalker.ru', 'podmoskovnye.ru', 'planetadorog.ru'}
_cache = OrderedDict()
_lock = Lock()


def _fetch(url):
    # Exact allowlist, no redirects/credentials/ports: arbitrary search results
    # cannot make this fetcher follow a redirect into the internal network.
    parsed = urlparse(url)
    try:
        if (parsed.scheme not in {'http', 'https'} or parsed.hostname not in _HOSTS
                or parsed.username or parsed.password or parsed.port not in {None, 80, 443}):
            return None
    except ValueError:
        return None
    key = source_key(url)
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > monotonic(): return cached[1]
    evidence = None
    try:
        with httpx.Client(timeout=httpx.Timeout(3, connect=2), follow_redirects=False) as client:
            with client.stream('GET', url) as response:
                if response.status_code == 200 and 'text/html' in response.headers.get('content-type', ''):
                    body = bytearray()
                    started = monotonic()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 1_000_000 or monotonic() - started > 3: break
                    else:
                        evidence = extract_page_identity(body.decode(response.encoding or 'utf-8', errors='replace'), url)
    except (httpx.HTTPError, ValueError, UnicodeError):
        pass
    with _lock:
        _cache[key] = (monotonic() + (900 if evidence else 60), evidence)
        _cache.move_to_end(key)
        while len(_cache) > 128: _cache.popitem(last=False)
    return evidence


def enrich_candidates(place, candidates, reference_urls):
    rows = [dict(row) for row in candidates]
    pending = [row for row in rows if verify_source(place, row, reference_urls).status == 'unconfirmed'][:4]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for row, evidence in zip(pending, pool.map(_fetch, [row.get('url', '') for row in pending])):
            if evidence: row['page_identity'] = evidence
    return rows
