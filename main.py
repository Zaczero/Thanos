import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from queue import Queue
from typing import Annotated

import anyio
import orjson
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import ORJSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from config import DRY_RUN, LOGS_QUEUE_SIZE, OSM_CLIENT, OSM_SCOPES, OSM_SECRET, SECRET, USER_AGENT
from config_db import setup_mongo
from filter import get_changesets_time_range, get_specific_changesets_time_range, query_changesets
from replication_worker import ReplicationWorker
from revert_manager import RevertManager
from revert_task import RevertTask
from states.worker_state import WorkerStateEnum, get_worker_state
from user_session import (
    fetch_user_details,
    is_whitelisted,
    require_oauth_token,
    require_whitelisted,
    set_oauth_token,
    unset_oauth_token,
)
from utils import datetime_isoformat, print_run_time, tojson_orjson

INDEX_REDIRECT = RedirectResponse('/', status_code=status.HTTP_303_SEE_OTHER)

replication_worker = ReplicationWorker()
revert_manager: RevertManager


@asynccontextmanager
async def lifespan(_: FastAPI):
    global revert_manager

    worker_state = get_worker_state()

    await worker_state.init()

    if worker_state.is_primary:
        await setup_mongo()
        async with anyio.create_task_group() as tg:
            revert_manager = RevertManager(tg)

            tg.start_soon(replication_worker.run)

            await worker_state.set_state(WorkerStateEnum.RUNNING)
            yield

            # on shutdown, always abort the tasks
            tg.cancel_scope.cancel()
    else:
        await worker_state.wait_for_state(WorkerStateEnum.RUNNING)
        yield


app = FastAPI(lifespan=lifespan, default_response_class=ORJSONResponse)
app.add_middleware(SessionMiddleware, secret_key=SECRET, max_age=2 * 365 * 24 * 3600, same_site='strict')  # 2 years
app.mount('/static', StaticFiles(directory='static'), name='static')

templates = Jinja2Templates(directory='templates')
templates.env.globals['datetime_isoformat'] = datetime_isoformat
templates.env.globals['timedelta'] = timedelta
templates.env.globals['tojson_orjson'] = tojson_orjson


@app.get('/')
async def index(
    request: Request,
    user=Depends(fetch_user_details),
):
    if user is not None:
        if is_whitelisted(user):
            return templates.TemplateResponse(
                'authorized.jinja2',
                {
                    'request': request,
                    'user': user,
                    'time_range': await get_changesets_time_range(),
                    'tasks': revert_manager.get_all(ascending=False),
                },
            )
        else:
            return templates.TemplateResponse('unauthorized.jinja2', {'request': request, 'user': user})
    else:
        return templates.TemplateResponse('index.jinja2', {'request': request})


@app.post('/classify')
async def classify(
    request: Request,
    from_: Annotated[datetime, Form()],
    to: Annotated[datetime, Form()],
    tags: Annotated[str | None, Form()] = None,
    user=Depends(require_whitelisted),
):
    if tags:
        tags = orjson.loads(tags)
        tags = tuple(d['value'] for d in tags)
    else:
        tags = ()

    with print_run_time('Querying changesets'):
        changesets = await query_changesets(from_, to, tags)

    return templates.TemplateResponse(
        'classify.jinja2',
        {
            'request': request,
            'user': user,
            'changesets': changesets,
        },
    )


@app.post('/configure')
async def configure(
    request: Request,
    changesets: Annotated[str, Form()],
    user=Depends(require_whitelisted),
):
    changesets_encoded = changesets
    changesets = orjson.loads(changesets)

    if not changesets:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'No changesets specified')

    return templates.TemplateResponse(
        'configure.jinja2',
        {
            'request': request,
            'user': user,
            'changesets_encoded': changesets_encoded,
            'changesets': changesets,
            'time_range': await get_specific_changesets_time_range(changesets),
        },
    )


@app.post('/revert')
async def post_revert(
    request: Request,
    changesets: Annotated[str, Form()],
    comment: Annotated[str, Form()],
    fix_parents: Annotated[bool, Form()],
    query_filter: Annotated[str | None, Form()] = None,
    discussion: Annotated[str | None, Form()] = None,
    revert_to_date: Annotated[datetime | None, Form()] = None,
    only_tags: Annotated[str | None, Form()] = None,
    iterator_delay: Annotated[str | None, Form()] = None,
    oauth_token=Depends(require_oauth_token),
    user=Depends(require_whitelisted),
):
    changesets: list[int] = orjson.loads(changesets)
    changesets.sort()
    changesets.reverse()  # descending order

    if not changesets:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'No changesets specified')

    comment = comment.strip()
    query_filter = query_filter.strip() if query_filter else ''
    discussion = discussion.strip() if discussion else ''

    time_range = await get_specific_changesets_time_range(changesets)
    envs = {}

    if revert_to_date:
        if time_range[0] <= revert_to_date:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Revert to date must be before the oldest changeset')

        envs['REVERT_TO_DATE'] = datetime_isoformat(revert_to_date, 'seconds') + 'Z'

    if only_tags:
        only_tags = orjson.loads(only_tags)
        only_tags = tuple(d['value'] for d in only_tags)
    else:
        only_tags = ()

    iterator_delay = float(iterator_delay) if iterator_delay else 0
    if iterator_delay < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'Iterator delay must be non-negative')

    hidden_options = {
        'oauth_token': oauth_token,
    }

    options = {
        'comment': comment,
        'discussion': discussion,
        'discussion_target': 'all',
        'query_filter': query_filter,
        'only_tags': only_tags,
        'fix_parents': fix_parents,
    }

    if DRY_RUN:
        options['print_osc'] = True

    task = RevertTask(
        id=datetime_isoformat(datetime.utcnow(), 'seconds'),
        changesets=changesets,
        time_range=time_range,
        envs=envs,
        hidden_options=hidden_options,
        options=options,
        passes=1,
        progress=0,
        logs=Queue(maxsize=LOGS_QUEUE_SIZE),
        iterator_delay=timedelta(minutes=iterator_delay),
        parallel=bool(revert_to_date) and not iterator_delay,
        aborted=False,
        finished=False,
    )

    revert_manager.submit(task)
    return RedirectResponse(f'/revert/{task.id}', status_code=status.HTTP_303_SEE_OTHER)


@app.get('/revert/{id}')
async def get_revert(
    request: Request,
    id: str,
    user=Depends(require_whitelisted),
):
    task = revert_manager.get_by_id(id)

    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Task not found')

    return templates.TemplateResponse(
        'revert.jinja2',
        {
            'request': request,
            'user': user,
            'time_range': await get_specific_changesets_time_range(task.changesets),
            'task': task,
        },
    )


@app.post('/revert/{id}/abort')
async def post_revert_abort(
    request: Request,
    id: str,
    user=Depends(require_whitelisted),
):
    revert_manager.abort_by_id(id)
    return RedirectResponse(f'/revert/{id}', status_code=status.HTTP_303_SEE_OTHER)


@app.post('/revert/{id}/delete')
async def post_revert_delete(
    request: Request,
    id: str,
    user=Depends(require_whitelisted),
):
    revert_manager.delete_by_id(id)
    return INDEX_REDIRECT


@app.post('/login')
async def login(request: Request) -> RedirectResponse:
    async with AsyncOAuth2Client(
        client_id=OSM_CLIENT,
        scope=OSM_SCOPES,
        redirect_uri=str(request.url_for('get_callback')),
    ) as oauth:
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
        headers={'User-Agent': USER_AGENT},
    ) as oauth:
        token = await oauth.fetch_token(
            'https://www.openstreetmap.org/oauth2/token',
            authorization_response=str(request.url),
        )

    set_oauth_token(request, token)
    return INDEX_REDIRECT


@app.post('/logout')
def logout(_=Depends(unset_oauth_token)) -> RedirectResponse:
    return INDEX_REDIRECT
