import gzip
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import anyio
import xmltodict
import yaml
from httpx import AsyncClient
from pymongo import UpdateOne

from config import CHANGESET_MAX_AGE, REPLICATION_FREQUENCY, REPLICATION_SLEEP, REPLICATION_URL
from config_db import CHANGESET_COLLECTION
from state import get_state_doc, set_state_doc
from utils import get_http_client, retry_exponential
from xmltodict_postprocessor import xmltodict_postprocessor


def _format_sequence_number(sequence_number: int) -> str:
    result = f'{sequence_number:09d}'
    result = '/'.join(result[i : i + 3] for i in range(0, 9, 3))
    return result


async def _get_last_replication_id() -> int:
    doc = await get_state_doc('replication')

    if doc is not None:
        return doc['last_replication_id']

    async with get_http_client(REPLICATION_URL) as http:
        r = await http.get('state.yaml')
        r.raise_for_status()

        remote_state = yaml.safe_load(r.text)
        remote_sequence_number = remote_state['sequence']
        current_sequence_number = remote_sequence_number - int(CHANGESET_MAX_AGE / REPLICATION_FREQUENCY)

        local_date = datetime.utcnow().replace(tzinfo=UTC)

        while True:
            print(f'[REPL] Synchronizing sequence: {current_sequence_number}')

            r = await http.get(f'{_format_sequence_number(current_sequence_number)}.state.txt')
            r.raise_for_status()

            sequence_state = yaml.safe_load(r.text)
            sequence_date = sequence_state['last_run']
            sequence_time_to_target = (local_date - sequence_date) - CHANGESET_MAX_AGE

            if sequence_time_to_target < timedelta():
                break

            sequence_step_to_target = sequence_time_to_target / REPLICATION_FREQUENCY

            if sequence_step_to_target > 10:
                current_sequence_number += int(sequence_step_to_target / 2)
            else:
                current_sequence_number += 1

        return current_sequence_number


async def _set_last_replication_id(repl_id: int):
    await set_state_doc('replication', {'last_replication_id': repl_id})


@retry_exponential(None)
async def _download_changesets(http: AsyncClient, repl_id: int) -> Sequence[dict] | None:
    r = await http.get(f'{_format_sequence_number(repl_id)}.osm.gz')

    # not found is expected
    if r.status_code == 404:
        return None

    r.raise_for_status()

    compressed = await r.aread()
    xml = gzip.decompress(compressed).decode()
    json = xmltodict.parse(
        xml,
        postprocessor=xmltodict_postprocessor,
        force_list=('changeset', 'action', 'node', 'way', 'relation', 'member', 'tag', 'nd'),
    )

    changesets = json['osm'].get('changeset', [])
    changesets = tuple(c for c in changesets if c['@comments_count'] == 0 and c['@num_changes'] > 0 and not c['@open'])

    for c in changesets:
        if 'tag' in c:
            c['tags'] = {tag['@k']: tag['@v'] for tag in c['tag']}
            del c['tag']

        # make empty tags easily searchable
        else:
            c['tags'] = {'__empty__': '1'}

    return changesets


async def _save_changesets(changesets: Sequence[dict]) -> None:
    bulk_write_args = [UpdateOne({'@id': cs['@id']}, {'$set': cs}, upsert=True) for cs in changesets]
    if bulk_write_args:
        await CHANGESET_COLLECTION.bulk_write(bulk_write_args, ordered=False)


async def _cleanup_expired_changesets() -> None:
    await CHANGESET_COLLECTION.delete_many({'@closed_at': {'$lt': datetime.utcnow() - CHANGESET_MAX_AGE}})


class ReplicationWorker:
    @retry_exponential(None)
    async def run(self):
        last_replication_id = await _get_last_replication_id()
        repl_id = last_replication_id + 1
        is_synchronized = False

        async with get_http_client(REPLICATION_URL) as http:
            while True:
                if is_synchronized:
                    await _cleanup_expired_changesets()
                    await anyio.sleep(REPLICATION_SLEEP.total_seconds())

                changesets = await _download_changesets(http, repl_id)

                if changesets is None:
                    is_synchronized = True
                    continue

                print(f'[REPL][{repl_id}] Downloaded {len(changesets)} changesets')
                await _save_changesets(changesets)
                await _set_last_replication_id(repl_id)
                repl_id += 1
