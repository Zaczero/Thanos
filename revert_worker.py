import io
import os
import sys
import traceback
from datetime import timedelta
from multiprocessing import Pipe, Process
from multiprocessing.connection import Connection
from queue import Full

import anyio
from anyio import get_cancelled_exc_class, open_file, to_thread

from config import CHANGESET_CONCURRENCY, VERSION_DATE
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
    iterator_delay_seconds = task.iterator_delay.total_seconds()
    send_stream, recv_stream = anyio.create_memory_object_stream(max_buffer_size=0)

    async def changeset_worker() -> None:
        async for changeset_id in recv_stream:
            changeset_id: int

            @retry_exponential(timedelta(hours=2), start=timedelta(seconds=15))
            async def inner(changeset_id: int) -> None:
                if task.aborted:
                    return

                log(f'[INFO] ⚙️ Reverting {changeset_id}...')

                r, w = Pipe(duplex=False)
                exitcode = None

                with anyio.fail_after(300), r, w:  # 5 minutes
                    async with anyio.create_task_group() as tg:

                        async def process_task():
                            nonlocal exitcode

                            proc = Process(
                                target=revert_worker_process,
                                kwargs={
                                    'conn': w,
                                    'env': {
                                        **task.envs,
                                        'OSM_REVERT_VERSION_DATE': VERSION_DATE,
                                        'OSM_REVERT_VERSION_SUFFIX': 'thanos',
                                    },
                                    'changeset_ids': [changeset_id],
                                    **task.hidden_options,
                                    **task.options,
                                },
                            )

                            proc.start()

                            try:
                                await to_thread.run_sync(proc.join, cancellable=True)
                            except get_cancelled_exc_class():
                                proc.kill()
                                raise

                            w.send_bytes(b'EOF\n')
                            exitcode = proc.exitcode

                        tg.start_soon(process_task)

                        async with await open_file(r.fileno(), closefd=False) as stdout:
                            async for line in stdout:
                                if line.endswith('EOF\n'):
                                    break
                                line = line.rstrip(' \n')
                                if num_workers > 1:
                                    line = f'({changeset_id}) {line}'
                                log(line)

                if exitcode is None or exitcode != 0:
                    log(f'[INFO] 🔁 Reverting {changeset_id} failed, retrying...')
                    raise RuntimeError(f'Reverting {changeset_id} failed: {exitcode}')

            try:
                await inner(changeset_id)
            except Exception:
                # revert exceptions are non-critical but should be avoided
                log(f'[INFO] ❌ Reverting {changeset_id} failed')
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
                for changeset_id in task.changesets:
                    if task.aborted:
                        log('[INFO] 🛑 Task aborted')
                        task.finished = True
                        return

                    await send_stream.send(changeset_id)
                    reverts += 1
                    task.progress = reverts / total_reverts

    assert reverts == total_reverts, f'{reverts} != {total_reverts}'
    log('[INFO] 🏁 Revert task finished')
    task.finished = True


def revert_worker_process(
    *,
    conn: Connection,
    env: dict[str, str],
    **kwargs,
) -> int:
    # Redirect stdout to the pipe
    sys.stdout = io.TextIOWrapper(os.fdopen(conn.fileno(), 'wb', buffering=0), write_through=True)

    for k, v in env.items():
        os.environ[k] = v

    import osm_revert

    return osm_revert.main(**kwargs)
