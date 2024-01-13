from collections.abc import Sequence

from revert_task import RevertTask
from revert_worker import revert_worker


class RevertManager:
    def __init__(self, tg) -> None:
        self._tg = tg
        self._tasks: list[RevertTask] = []

    def get_all(self, *, ascending: bool = True) -> Sequence[RevertTask]:
        if ascending:
            return tuple(self._tasks)  # oldest first
        else:
            return tuple(reversed(self._tasks))  # newest first

    def get_by_id(self, id_: str) -> RevertTask | None:
        return next((task for task in self._tasks if task.id == id_), None)

    def abort_by_id(self, id_: str) -> bool:
        task = self.get_by_id(id_)
        if task is None:
            return False
        task.aborted = True
        return True

    def delete_by_id(self, id_: str) -> bool:
        task = self.get_by_id(id_)
        if task is None or not task.finished:
            return False
        self._tasks.remove(task)
        return True

    def submit(self, task: RevertTask) -> None:
        assert self.get_by_id(task.id) is None, f'Task with ID {task.id!r} already exists'
        self._tasks.append(task)
        self._tg.start_soon(revert_worker, task)
