import functools
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta
from math import inf
from typing import Generator

import anyio
import httpx
import orjson

from config import USER_AGENT


@contextmanager
def print_run_time(message: str | list) -> Generator[None, None, None]:
    start_time = time.perf_counter()
    try:
        yield
    finally:
        end_time = time.perf_counter()
        elapsed_time = end_time - start_time

        # support message by reference
        if isinstance(message, list):
            message = message[0]

        print(f'[⏱️] {message} took {elapsed_time:.3f}s')


def retry_exponential(timeout: timedelta | None, *, start: timedelta = timedelta(seconds=1)):
    if timeout is None:
        timeout_seconds = inf
    else:
        timeout_seconds = timeout.total_seconds()

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            ts = time.perf_counter()
            sleep = start.total_seconds()

            while True:
                try:
                    return await func(*args, **kwargs)
                except Exception:
                    print(f'[⛔] {func.__name__} failed')
                    traceback.print_exc()
                    if (time.perf_counter() + sleep) - ts > timeout_seconds:
                        raise
                    await anyio.sleep(sleep)
                    sleep = min(sleep * 2, 4 * 3600)  # max 4 hours

        return wrapper
    return decorator


def get_http_client(base_url: str = '', *, auth: tuple | None = None, headers: dict | None = None) -> httpx.AsyncClient:
    if not headers:
        headers = {}

    headers['User-Agent'] = USER_AGENT

    return httpx.AsyncClient(
        base_url=base_url,
        follow_redirects=True,
        timeout=60,
        auth=auth,
        headers=headers
    )


def datetime_isoformat(dt: datetime) -> str:
    return dt.isoformat('T', 'minutes')


def tojson_orjson(value) -> str:
    json = orjson.dumps(value, option=orjson.OPT_NON_STR_KEYS).decode()
    return (json
        .replace('\\', '\\\\')
        .replace('\'', '\\\''))
