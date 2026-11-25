"""Persist gallery metadata alongside images so reopening never waits on discovery."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
import logging
from threading import Lock
from time import time

from infrastructure.osint.osint_profile import build_place_profile


class SourceGalleryCache:
    FRESH_SECONDS = 900
    RETRY_SECONDS = 30

    def __init__(self, storage, load, *, scope=(), clock=time):
        self.storage, self.load, self.scope, self.clock = storage, load, scope, clock
        self.entries = OrderedDict()
        self.lock = Lock()
        self.requests = [Lock() for _ in range(32)]
        self.pending = set()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='source-gallery')

    def key(self, place, report):
        # Include all identity/verification inputs. An edited card or a new report
        # must not reuse photos accepted for the previous identity.
        context = (place.get('id'), asdict(build_place_profile(place)), report, self.scope)
        data = json.dumps(context, sort_keys=True, default=lambda value:
                          sorted(value) if isinstance(value, (set, frozenset)) else str(value))
        # Bump the namespace when source verification rules change.
        return f'source-galleries/v1/{sha256(data.encode()).hexdigest()}.json'

    def _remember(self, key, entry):
        with self.lock:
            self.entries[key] = entry
            self.entries.move_to_end(key)
            while len(self.entries) > 256:
                self.entries.popitem(last=False)

    def _read(self, key):
        try:
            entry = json.loads(self.storage.get(key))
            if (isinstance(entry, dict) and isinstance(entry.get('expires_at'), (int, float))
                    and isinstance(entry.get('photos'), list) and entry['photos']
                    and all(isinstance(photo, dict) and isinstance(photo.get('image_url'), str)
                            for photo in entry['photos'])):
                return entry
        except Exception:
            # A missing/unavailable manifest must not prevent the first load.
            pass
        return None

    def _store(self, key, photos):
        entry = {'expires_at': self.clock() + self.FRESH_SECONDS, 'photos': deepcopy(photos)}
        self._remember(key, entry)
        try:
            self.storage.put(key, json.dumps(entry).encode(), content_type='application/json')
        except Exception:
            logging.getLogger(__name__).warning('Could not persist source gallery metadata')

    def _refresh(self, key, place, report):
        try:
            photos = self.load(place, report)
            if photos:
                self._store(key, photos)
                return
        except Exception:
            logging.getLogger(__name__).warning('Source gallery refresh failed; keeping saved photos')
        finally:
            with self.lock:
                # Keep usable photos on temporary failures/empty source answers.
                entry = self.entries.get(key)
                if entry and entry['expires_at'] <= self.clock():
                    self.entries[key] = dict(entry, expires_at=self.clock() + self.RETRY_SECONDS)
                self.pending.discard(key)

    def photos(self, place, report):
        key = self.key(place, report)
        # Collapse concurrent cold requests without locking other galleries.
        with self.requests[hash(key) % len(self.requests)]:
            with self.lock:
                entry = self.entries.get(key)
                if entry:
                    self.entries.move_to_end(key)
            if entry is None:
                entry = self._read(key)
                if entry:
                    self._remember(key, entry)
            if entry:
                with self.lock:
                    if (entry['expires_at'] <= self.clock() and key not in self.pending
                            and len(self.pending) < 16):
                        self.pending.add(key)
                        self.pool.submit(self._refresh, key, deepcopy(place), deepcopy(report))
                return deepcopy(entry['photos'])
            photos = self.load(place, report)
            if photos:
                self._store(key, photos)
            return photos

    def close(self):
        self.pool.shutdown(wait=True)
