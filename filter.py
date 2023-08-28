from datetime import datetime, timedelta
from itertools import islice
from typing import Sequence

import anyio
import pymongo
from asyncache import cached
from cachetools import TTLCache

from config import OSM_API_URL, OSM_PLANET_URL
from config_db import CHANGESET_COLLECTION
from utils import get_http_client, print_run_time, retry_exponential

_user_info_cache = TTLCache(maxsize=32 * 1024, ttl=60)


async def get_changesets_time_range() -> tuple[datetime, datetime]:
    first_doc = await CHANGESET_COLLECTION.find_one(sort=[('@closed_at', 1)], projection={'_id': False, '@closed_at': True})
    last_doc = await CHANGESET_COLLECTION.find_one(sort=[('@closed_at', -1)], projection={'_id': False, '@closed_at': True})
    return first_doc['@closed_at'], last_doc['@closed_at']


async def get_specific_changesets_time_range(changesets: Sequence[int]) -> tuple[datetime, datetime]:
    first_doc = await CHANGESET_COLLECTION.find_one({'@id': {'$in': changesets}}, sort=[('@closed_at', 1)], projection={'_id': False, '@closed_at': True})
    last_doc = await CHANGESET_COLLECTION.find_one({'@id': {'$in': changesets}}, sort=[('@closed_at', -1)], projection={'_id': False, '@closed_at': True})
    return first_doc['@closed_at'], last_doc['@closed_at']


@cached(TTLCache(maxsize=1, ttl=8 * 3600))
async def _fetch_deleted_users() -> frozenset[int]:
    async with get_http_client(OSM_PLANET_URL) as http:
        r = await http.get('users_deleted/users_deleted.txt')
        r.raise_for_status()

    result = set()

    for line in r.text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        result.add(int(line))

    return frozenset(result)


async def _fetch_latest_user_info(uids: Sequence[int]) -> dict[int, dict | None]:
    result = {}
    uids_set = set(uids)

    with print_run_time('Fetching deleted users'):
        deleted_uids = await _fetch_deleted_users()

    # check for deleted users
    for uid in uids_set.intersection(deleted_uids):
        result[uid] = None
        uids_set.remove(uid)

    # check for cached users
    for uid in tuple(uids_set):
        try:
            result[uid] = _user_info_cache[uid]
            uids_set.remove(uid)
        except KeyError:
            pass

    # small optimization
    if not uids_set:
        return result

    async with get_http_client(OSM_API_URL) as http, anyio.create_task_group() as tg:
        @retry_exponential(timedelta(seconds=30))
        async def process(batch: Sequence[int]):
            r = await http.get('users.json', params={'users': ','.join(map(str, batch))})

            # at some point, api returned 404 if at least one user is not found
            if r.status_code == 404:
                if len(batch) == 1:
                    uid = batch[0]
                    _user_info_cache[uid] = result[uid] = None
                else:
                    mid = len(batch) // 2
                    batch1, batch2 = batch[:mid], batch[mid:]
                    tg.start_soon(process, batch1)
                    tg.start_soon(process, batch2)
            else:
                r.raise_for_status()
                batch_set = set(batch)

                for user in r.json()['users']:
                    user = user['user']
                    uid = user['id']
                    _user_info_cache[uid] = result[uid] = user
                    batch_set.remove(uid)

                for uid in batch_set:
                    _user_info_cache[uid] = result[uid] = None

        uids_iter = iter(uids_set)
        batch_size = 500
        while batch := tuple(islice(uids_iter, batch_size)):
            tg.start_soon(process, batch)

    return result


async def query_changesets(from_: datetime, to: datetime, tags: Sequence[str]) -> dict[int, dict]:
    query = {
        '@closed_at': {
            '$gte': from_,
            '$lte': to,
        },
    }

    if tags:
        tag_query = {}

        for tag in tags:
            tag_split = tag.split('=', 1)

            if len(tag_split) == 2 and tag_split[1] != '*':
                key, value = tag_split
                tag_query[f'tags.{key}'] = value
            else:
                key = tag_split[0]
                tag_query[f'tags.{key}'] = {'$exists': True}

        query['$and'] = [{k: v} for k, v in tag_query.items()]

    cursor = CHANGESET_COLLECTION.find(query, projection={'_id': False}).sort('@id', pymongo.ASCENDING)

    result = {}
    result_uids = set()

    async for doc in cursor:
        result[doc['@id']] = doc
        result_uids.add(doc['@uid'])

    with print_run_time('Fetching latest user info'):
        latest_user_info = await _fetch_latest_user_info(result_uids)

    for doc in result.values():
        doc['user'] = latest_user_info[doc['@uid']]

    return result
