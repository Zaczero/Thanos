from dataclasses import dataclass
from datetime import datetime, timedelta
from queue import Queue
from typing import Sequence


@dataclass(kw_only=True, slots=True)
class RevertTask:
    id: str
    changesets: Sequence[int]
    time_range: tuple[datetime, datetime]
    envs: dict[str, str]
    hidden_options: Sequence[str]
    options: Sequence[str]
    passes: int
    progress: float
    logs: Queue[str]
    iterator_delay: timedelta
    parallel: bool
    aborted: bool
    finished: bool
