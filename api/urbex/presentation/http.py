from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Request, Response, UploadFile, Query
from urbex.domain.rules import DomainError
from urbex.application.users import public_user
from .schemas import Register, Login, PlaceInput, Search, ReviewInput, ReportInput, Decision, UserUpdate, CategoryInput, DescriptionUpdate, AdminPlaceUpdate, ItineraryInput

router = APIRouter(prefix='/api')


def context(request: Request):
    yield from request.app.state.request_context(request)


Ctx = Annotated[tuple, Depends(context)]


def signed(ctx):
    if ctx[2] is None:
        raise DomainError('Войдите в аккаунт', 401)
    return ctx[2]


def session_response(auth, user, request, response):
    token, csrf = auth.start(user, request.cookies.get('urbex_session'))
    response.set_cookie('urbex_session', token, httponly=True, secure=auth.config.secure_cookie,
                        samesite='lax', max_age=auth.config.session_hours*3600, path='/')
    return {'user': public_user(user), 'csrf': csrf}


@router.get('/health')
def health(request: Request):
    request.app.state.check_database()
    return {'status': 'ok'}


@router.get('/auth/me')
def me(ctx: Ctx):
    return {'user': ctx[4], 'csrf': ctx[3]}


@router.post('/auth/register', status_code=201)
def register(data: Register, request: Request, response: Response, ctx: Ctx):
    auth = ctx[1]
    auth.throttle('register:'+request.client.host)
    return session_response(auth, auth.register(data.model_dump()), request, response)


@router.post('/auth/login')
def login(data: Login, request: Request, response: Response, ctx: Ctx):
    return session_response(ctx[1], ctx[1].login(data.email, data.password, request.client.host), request, response)


@router.post('/auth/logout')
def logout(request: Request, response: Response, ctx: Ctx):
    signed(ctx)
    ctx[1].logout(request.cookies.get('urbex_session'))
    response.delete_cookie('urbex_session', path='/')
    return {'ok': True}


@router.post('/auth/revoke-all')
def revoke(ctx: Ctx, response: Response):
    ctx[1].revoke_all(signed(ctx))
    response.delete_cookie('urbex_session', path='/')
    return {'ok': True}


@router.get('/categories')
def categories(ctx: Ctx, page: int = Query(1, ge=1)):
    return ctx[0].categories(page)


@router.get('/search/locations')
def locations(ctx: Ctx, q: str = Query('', max_length=200)):
    return ctx[0].places.locations(q)


@router.get('/places')
def places(ctx: Ctx, params: Annotated[Search, Query()]):
    return ctx[0].places.search(params.filters())


@router.get('/map')
def map_points(ctx: Ctx, params: Annotated[Search, Query()]):
    if not params.bbox:
        raise DomainError('Для карты требуется bbox', 422)
    return ctx[0].places.map(params.filters(), params.zoom)


@router.get('/places/{id}/favorite')
def favorite_state(id: int, ctx: Ctx):
    return ctx[0].places.favorite_state(signed(ctx), id)


@router.get('/places/{id}')
def place(id: int, ctx: Ctx):
    return ctx[0].places.place(id, ctx[2])


@router.post('/places', status_code=201)
def submit(data: PlaceInput, ctx: Ctx):
    return ctx[0].places.submit(signed(ctx), data.model_dump())


@router.put('/places/{id}')
def resubmit(id: int, data: PlaceInput, ctx: Ctx):
    return ctx[0].places.submit(signed(ctx), data.model_dump(), id)


@router.delete('/places/{id}')
def delete_own_place(id: int, ctx: Ctx):
    return ctx[0].places.remove_own(signed(ctx), id)


@router.get('/me/{kind}')
def personal(kind: Literal['places', 'photos', 'reviews', 'reports', 'favorites'], ctx: Ctx, page: int = Query(1, ge=1), pending_only: bool = False, status: Literal['pending', 'published'] | None = None):
    actor = signed(ctx)
    return ctx[0].personal(actor, kind, page, pending_only=pending_only, status=status)


@router.put('/places/{id}/favorite')
def favorite(id: int, ctx: Ctx):
    return ctx[0].places.favorite(signed(ctx), id, True)


@router.delete('/places/{id}/favorite')
def unfavorite(id: int, ctx: Ctx):
    return ctx[0].places.favorite(signed(ctx), id, False)


@router.get('/places/{id}/itinerary')
def active_place_state(ctx: Ctx, id: int):
    return ctx[0].itineraries.active_place_state(signed(ctx), id)


@router.get('/places/{id}/{kind}')
def related(id: int, kind: Literal['reviews', 'photos'], ctx: Ctx, page: int = Query(1, ge=1), source: Literal['telegram', 'website'] | None = None):
    return ctx[0].places.related(kind, id, ctx[2], page, source)


@router.put('/places/{id}/reviews')
def review(id: int, data: ReviewInput, ctx: Ctx):
    return ctx[0].reviews.review(signed(ctx), id, data.model_dump())


@router.post('/places/{id}/photos', status_code=201)
def photo(id: int, file: UploadFile, request: Request, ctx: Ctx):
    actor = signed(ctx)
    data = file.file.read(request.app.state.max_photo_bytes + 1)
    return ctx[0].places.photo(actor, id, request.app.state.sanitize_photo(data))


@router.delete('/photos/{id}')
def delete_own_photo(id: int, ctx: Ctx):
    return ctx[0].places.delete_photo(signed(ctx), id)


@router.get('/photos/{id}/content')
def content(id: int, ctx: Ctx):
    return Response(ctx[0].places.photo_bytes(id, ctx[2]), media_type='image/jpeg',
                    headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.post('/reports', status_code=201)
def report(data: ReportInput, ctx: Ctx):
    return ctx[0].reviews.report(signed(ctx), data.model_dump())


@router.get('/admin/{kind}')
def admin_list(kind: Literal['places','photos','reviews','reports','users','categories','audit'], ctx: Ctx,
               page: int = Query(1, ge=1), status: str | None = None, place_id: int | None = Query(None, gt=0), q: str = Query("", max_length=200)):
    return ctx[0].moderation.admin_list(signed(ctx), kind, page, status, place_id, q)


@router.post('/admin/{kind}/{id}/decision')
def decision(kind: Literal['places','photos','reviews','reports'], id: int, data: Decision, ctx: Ctx):
    return ctx[0].moderation.moderate(signed(ctx), kind, id, data.status, data.reason)


@router.put('/admin/users/{id}')
def user_update(id: int, data: UserUpdate, ctx: Ctx):
    return ctx[1].manage_user(signed(ctx), id, data.model_dump())


@router.post('/admin/categories', status_code=201)
def add_category(data: CategoryInput, ctx: Ctx):
    return ctx[0].moderation.category(signed(ctx), data.model_dump())


@router.put('/admin/categories/{id}')
def edit_category(id: int, data: CategoryInput, ctx: Ctx):
    return ctx[0].moderation.category(signed(ctx), data.model_dump(), id)


@router.patch('/admin/places/{id}/description')
def edit_description(id: int, data: DescriptionUpdate, ctx: Ctx):
    return ctx[0].moderation.edit_description(signed(ctx), id, data.description, data.expected_description)


@router.patch('/admin/places/{id}')
def edit_place(id: int, data: AdminPlaceUpdate, ctx: Ctx):
    return ctx[0].moderation.edit_place(signed(ctx), id, data.model_dump())


@router.get('/admin/geocode/reverse')
def reverse_geocode(request: Request, ctx: Ctx,
                    latitude: float = Query(ge=-85, le=85, allow_inf_nan=False),
                    longitude: float = Query(ge=-180, le=180, allow_inf_nan=False)):
    signed(ctx).require('moderator', 'admin')
    return request.app.state.reverse_address(round(latitude,6), round(longitude,6))


@router.get('/itineraries')
def itineraries(ctx: Ctx, page: int = Query(1,ge=1)):
    return ctx[0].repo.list('itineraries', {'author_id':signed(ctx).id},page)


@router.post('/itineraries', status_code=201)
def create_itinerary(ctx: Ctx, data: ItineraryInput):
    return ctx[0].itineraries.save(signed(ctx),data.model_dump())


@router.get('/itineraries/{id}')
def itinerary(ctx: Ctx,id:int):
    return ctx[0].itineraries.detail(signed(ctx),id)


@router.put('/itineraries/{id}')
def update_itinerary(ctx: Ctx,id:int,data:ItineraryInput):
    return ctx[0].itineraries.save(signed(ctx),data.model_dump(),id)


@router.delete('/itineraries/{id}')
def delete_itinerary(ctx: Ctx,id:int):
    return ctx[0].itineraries.remove(signed(ctx),id)


@router.post('/auth/telegram/start')
def telegram_start(request: Request, response: Response, ctx: Ctx):
    browser, data = ctx[1].telegram_begin(request.client.host)
    response.set_cookie('urbex_tg_login',browser,httponly=True,secure=ctx[1].config.secure_cookie,
                        samesite='strict',max_age=300,path='/api/auth/telegram')
    return data


@router.post('/auth/telegram/complete')
def telegram_complete(request: Request, response: Response, ctx: Ctx):
    user=ctx[1].telegram_complete(request.cookies.get('urbex_tg_login'))
    if user is None:return {'pending':True}
    response.delete_cookie('urbex_tg_login',path='/api/auth/telegram')
    return session_response(ctx[1],user,request,response)


@router.get('/public-config')
def public_config(request: Request):
    username = request.app.state.config.telegram_bot_username.strip().lstrip('@')
    return {'telegram_bot_username': username,
            'telegram_bot_url': f'https://t.me/{username}' if username else None}


@router.put('/itineraries/{id}/active')
def active_itinerary(ctx: Ctx, id: int, active: bool = True):
    return ctx[0].itineraries.activate(signed(ctx), id, active)


@router.post('/places/{id}/itinerary')
def add_place_to_active_itinerary(ctx: Ctx, id: int):
    return ctx[0].itineraries.add_to_active(signed(ctx), id)


@router.delete('/places/{id}/itinerary')
def remove_place_from_active(ctx: Ctx, id: int):
    return ctx[0].itineraries.remove_from_active(signed(ctx), id)


@router.delete('/admin/reviews/{id}')
def delete_review(ctx: Ctx, id: int):
    ctx[0].moderation.moderate(signed(ctx), 'reviews', id, 'rejected', 'Удалено модератором')
    return {'ok': True}


@router.get('/geocode/reverse')
def user_reverse_geocode(request: Request, ctx: Ctx,
                         latitude: float = Query(ge=-85, le=85, allow_inf_nan=False),
                         longitude: float = Query(ge=-180, le=180, allow_inf_nan=False)):
    signed(ctx)
    return request.app.state.reverse_address(round(latitude,6), round(longitude,6))


@router.delete('/admin/users/{id}')
def delete_user(id: int, ctx: Ctx):
    return ctx[1].delete_user(signed(ctx), id)


@router.post('/itineraries/{id}/telegram')
def send_itinerary_telegram(id: int, request: Request, ctx: Ctx):
    actor = signed(ctx)
    route = ctx[0].itineraries.detail(actor, id)
    user = ctx[0].repo.get('users', actor.id)
    if not user.get('telegram_id'):
        raise DomainError('Для отправки маршрута войдите через Telegram.', 400)
    request.app.state.send_route(user['telegram_id'], route)
    return {'ok': True}


@router.delete('/admin/places/{id}')
def delete_place(id: int, ctx: Ctx):
    ctx[0].moderation.moderate(signed(ctx), 'places', id, 'rejected', 'Удалено модератором')
    return {'ok': True}
