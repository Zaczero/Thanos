from datetime import timedelta

from authlib.integrations.httpx_client import OAuth2Auth
from cachetools import TTLCache
from fastapi import Depends, HTTPException, Request, status
from fastapi.websockets import WebSocket

from config import DISABLE_USER_WHITELIST
from utils import get_http_client, retry_exponential

_user_cache = TTLCache(maxsize=1024, ttl=7200)  # 2 hours


@retry_exponential(timedelta(seconds=30))
async def fetch_user_details(request: Request = None, websocket: WebSocket = None) -> dict | None:
    if request is not None:
        session = request.session
    elif websocket is not None:
        session = websocket.session
    else:
        raise ValueError('Either request or websocket must be provided')

    try:
        token = session['oauth_token']
    except KeyError:
        return None

    cache_key: str = token['access_token']

    try:
        return _user_cache[cache_key]
    except KeyError:
        pass

    async with get_http_client('https://api.openstreetmap.org/api', auth=OAuth2Auth(token)) as http:
        r = await http.get('/0.6/user/details.json')
        if not r.is_success:
            return None

    try:
        user = r.json()['user']
    except Exception:
        return None

    # add img href if missing
    if 'img' not in user:
        user['img'] = {'href': None}

    print(f'[AUTH] 🔒 Logged in as {user["display_name"]} ({user["id"]})')

    _user_cache[cache_key] = user
    return user


async def require_user_details(user=Depends(fetch_user_details)) -> dict:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Unauthorized')
    return user


def require_oauth_token(request: Request) -> dict:
    try:
        return request.session['oauth_token']
    except KeyError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Unauthorized')


def set_oauth_token(request: Request, token: dict) -> bool:
    request.session['oauth_token'] = token
    return True


def unset_oauth_token(request: Request) -> bool:
    try:
        del request.session['oauth_token']
        return True
    except KeyError:
        return False


def is_whitelisted(user: dict) -> bool:
    if DISABLE_USER_WHITELIST:
        return True

    # whitelist by role
    if any(role in user['roles'] for role in ('moderator', 'administrator')):
        return True

    # whitelist by user id
    if user['id'] in {
        15215305,  # https://www.openstreetmap.org/user/NorthCrab
    }:
        return True

    return False


def require_whitelisted(user=Depends(require_user_details)) -> dict:
    if not is_whitelisted(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Forbidden')
    return user
