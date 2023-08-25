from datetime import datetime, timedelta
from typing import Annotated, Sequence

import anyio
import orjson
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from config import OSM_CLIENT, OSM_SCOPES, OSM_SECRET, SECRET, USER_AGENT
from config_db import setup_mongo
from filter import get_changesets_time_range, query_changesets
from replication_worker import ReplicationWorker
from states.worker_state import WorkerStateEnum, get_worker_state
from user_session import (fetch_user_details, is_whitelisted,
                          require_user_details, require_whitelisted,
                          set_oauth_token, unset_oauth_token)
from utils import datetime_isoformat, print_run_time, tojson_orjson

INDEX_REDIRECT = RedirectResponse('/', status_code=status.HTTP_302_FOUND)

replication_worker = ReplicationWorker()

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET, max_age=2 * 365 * 24 * 3600, same_site='strict')  # 2 years
app.mount('/static', StaticFiles(directory='static'), name='static')

app_tg = anyio.create_task_group()

templates = Jinja2Templates(directory='templates')
templates.env.globals['datetime_isoformat'] = datetime_isoformat
templates.env.globals['timedelta'] = timedelta
templates.env.globals['tojson_orjson'] = tojson_orjson


@app.on_event('startup')
async def startup():
    worker_state = get_worker_state()

    await worker_state.init()

    if worker_state.is_primary:
        await setup_mongo()
        await app_tg.__aenter__()
        app_tg.start_soon(replication_worker.run)
        await worker_state.set_state(WorkerStateEnum.RUNNING)
    else:
        await worker_state.wait_for_state(WorkerStateEnum.RUNNING)


@app.get('/')
async def index(request: Request, user=Depends(fetch_user_details)):
    if user is not None:
        if is_whitelisted(user):
            return templates.TemplateResponse('authorized.jinja2', {
                'request': request,
                'user': user,
                'time_range': await get_changesets_time_range()
            })
        else:
            return templates.TemplateResponse('unauthorized.jinja2', {'request': request, 'user': user})
    else:
        return templates.TemplateResponse('index.jinja2', {'request': request})


@app.post('/query')
async def query(request: Request, from_: Annotated[datetime, Form()], to: Annotated[datetime, Form()], tags: Annotated[str, Form()] = None, user=Depends(require_whitelisted)):
    if tags:
        tags = orjson.loads(tags)
        tags = tuple(d['value'] for d in tags)
    else:
        tags = tuple()

    with print_run_time('Querying changesets'):
        changesets = await query_changesets(from_, to, tags)

    return templates.TemplateResponse('query.jinja2', {
        'request': request,
        'user': user,
        'changesets': changesets,
    })


@app.post('/login')
async def login(request: Request) -> RedirectResponse:
    async with AsyncOAuth2Client(
            client_id=OSM_CLIENT,
            scope=OSM_SCOPES,
            redirect_uri=str(request.url_for('get_callback'))) as oauth:
        authorization_url, state = oauth.create_authorization_url('https://www.openstreetmap.org/oauth2/authorize')

    request.session['oauth_state'] = state
    return RedirectResponse(authorization_url, status_code=status.HTTP_303_SEE_OTHER)


@app.get('/callback')
async def get_callback(request: Request):
    return templates.TemplateResponse('callback.jinja2', {'request': request})


@app.post('/callback')
async def post_callback(request: Request) -> RedirectResponse:
    state = request.session.pop('oauth_state', None)

    if state is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Invalid OAuth state')

    async with AsyncOAuth2Client(
            client_id=OSM_CLIENT,
            client_secret=OSM_SECRET,
            redirect_uri=str(request.url_for('get_callback')),
            state=state,
            headers={'User-Agent': USER_AGENT}) as oauth:
        token = await oauth.fetch_token('https://www.openstreetmap.org/oauth2/token', authorization_response=str(request.url))

    set_oauth_token(request, token)
    return INDEX_REDIRECT


@app.post('/logout')
def logout(_=Depends(unset_oauth_token)) -> RedirectResponse:
    return INDEX_REDIRECT
