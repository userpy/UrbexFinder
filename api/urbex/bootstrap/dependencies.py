import secrets
from sqlalchemy.orm import Session
from urbex.application.service import Service
from urbex.infrastructure.repository import SqlRepository
from urbex.infrastructure.auth import Auth
from urbex.domain.rules import DomainError


def request_context(request):
    if (request.method == 'GET' and request.url.path in {'/api/places', '/api/map', '/api/admin/places'}
            and request.query_params.get('q', '').strip()):
        # Synchronize before acquiring the request's DB connection, avoiding
        # nested pool acquisition when many searches arrive simultaneously.
        request.app.state.search.sync()
    with Session(request.app.state.engine) as session:
        repo = SqlRepository(session, request.app.state.search)
        auth = Auth(repo, request.app.state.config)
        actor, csrf, user = auth.resolve(request.cookies.get('urbex_session'))
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            if request.headers.get('origin') != request.app.state.config.origin:
                raise DomainError('Недопустимый источник запроса', 403)
            if actor and not secrets.compare_digest(request.headers.get('x-csrf-token', ''), csrf):
                raise DomainError('Недействительный CSRF-токен', 403)
        try:
            yield Service(repo, request.app.state.storage), auth, actor, csrf, user
            session.commit()
        except Exception:
            session.rollback()
            raise

