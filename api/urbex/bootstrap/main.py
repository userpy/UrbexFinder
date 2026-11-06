import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from urbex.infrastructure.search import ElasticSearch
from urbex.infrastructure.geocoding import reverse_address
from urbex.infrastructure.telegram import send_route
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from urbex.domain.rules import DomainError
from urbex.infrastructure.storage import S3Storage
from urbex.presentation.http import router
from .config import Settings
from .dependencies import request_context
from urbex.infrastructure.storage import sanitize_photo, MAX_PHOTO_BYTES
from sqlalchemy import text


def create_app(config=None, storage=None):
    config = config or Settings()
    config.validate_runtime()
    @asynccontextmanager
    async def lifespan(app):
        task = None
        async def synchronize():
            while True:
                try:
                    await asyncio.to_thread(app.state.search.sync)
                except Exception:
                    logging.getLogger(__name__).warning('Search synchronization failed; queued changes will be retried')
                await asyncio.sleep(2)
        if config.elasticsearch_url and config.environment != 'test':
            # Initial indexing also has a CLI command; requests can still browse
            # PostgreSQL while ES is unavailable. Text search reports HTTP 503.
            task = asyncio.create_task(synchronize())
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title='UrbexFinder API', version='0.1.0', lifespan=lifespan)
    app.state.config = config
    app.state.send_route = lambda chat_id, route: send_route(config.telegram_bot_token, chat_id, route)
    app.state.reverse_address = lambda latitude, longitude: reverse_address(config.geocoder_url, config.origin, latitude, longitude)
    app.state.engine = create_engine(config.database_url, pool_pre_ping=True)
    app.state.search = ElasticSearch(config, app.state.engine)
    app.state.storage = storage or S3Storage(config)

    app.state.request_context = request_context
    app.state.sanitize_photo = sanitize_photo
    app.state.max_photo_bytes = MAX_PHOTO_BYTES

    def check_database():
        with app.state.engine.connect() as connection:
            connection.execute(text('SELECT 1 FROM web_alembic_version'))
    app.state.check_database = check_database

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse({'detail': exc.message}, status_code=exc.status)

    @app.exception_handler(IntegrityError)
    async def conflict(request, exc):
        return JSONResponse({'detail': 'Запись уже существует или связана с другими данными'}, status_code=409)

    app.include_router(router)
    return app


app = create_app()
