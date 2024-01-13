import subprocess
import traceback
from datetime import timedelta
from itertools import chain
from queue import Full

import anyio
from anyio.streams.buffered import BufferedByteReceiveStream

from config import CHANGESET_CONCURRENCY
from revert_task import RevertTask
from utils import retry_exponential


async def revert_worker(task: RevertTask) -> None:
    def log(text: str) -> None:
        try:
            task.logs.put_nowait(text)
        except Full:
            try:
                task.logs.get_nowait()
            finally:
                log(text)

    num_workers = CHANGESET_CONCURRENCY if task.parallel else 1
    envs = []
    options = tuple(chain(task.hidden_options, task.options))
    iterator_delay_seconds = task.iterator_delay.total_seconds()

    for k, v in task.envs.items():
        envs.append('--env')
        envs.append(f'{k}={v}')

    send_stream, recv_stream = anyio.create_memory_object_stream(max_buffer_size=0)

    async def changeset_worker() -> None:
        async for changeset in recv_stream:

            @retry_exponential(timedelta(hours=2), start=timedelta(seconds=15))
            async def inner(changeset) -> None:
                if task.aborted:
                    return

                log(f'[INFO] ⚙️ Reverting {changeset}...')

                async with await anyio.open_process(
                    (
                        'docker',
                        'run',
                        '--rm',
                        '--env',
                        'OSM_REVERT_VERSION_SUFFIX=thanos',
                        *envs,
                        'zaczero/osm-revert',
                        '--changeset_ids',
                        str(changeset),
                        *options,
                    ),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                ) as proc:
                    reader = BufferedByteReceiveStream(proc.stdout)

                    while True:
                        try:
                            buffer: bytes = await reader.receive_until(b'\n', 8192)
                        except anyio.IncompleteRead:
                            break
                        text = buffer.decode().rstrip()
                        if num_workers > 1:
                            text = f'({changeset}) {text}'
                        log(text)

                if proc.returncode != 0:
                    log(f'[INFO] 🔁 Reverting {changeset} failed, retrying...')
                    raise RuntimeError(f'Reverting {changeset} failed: {proc.returncode}')

            try:
                await inner(changeset)
            except Exception:
                # revert exceptions are non-critical but should be avoided
                log(f'[INFO] ❌ Reverting {changeset} failed')
                traceback.print_exc()

            if iterator_delay_seconds > 0:
                log(f'[INFO] 🕒 Delaying {iterator_delay_seconds} seconds...')
                await anyio.sleep(iterator_delay_seconds)

    total_reverts = len(task.changesets) * task.passes
    reverts = 0

    for pass_ in range(1, task.passes + 1):
        log(f'[INFO] 🔁 Starting pass {pass_} of {task.passes}')

        async with anyio.create_task_group() as tg:
            for _ in range(num_workers):
                tg.start_soon(changeset_worker)

            async with send_stream:
                for changeset in task.changesets:
                    if task.aborted:
                        log('[INFO] 🛑 Task aborted')
                        task.finished = True
                        return

                    await send_stream.send(changeset)
                    reverts += 1
                    task.progress = reverts / total_reverts

    assert reverts == total_reverts, f'{reverts} != {total_reverts}'
    log('[INFO] 🏁 Revert task finished')
    task.finished = True
